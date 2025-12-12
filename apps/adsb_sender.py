#!/usr/bin/env python3
"""
ADS-B sender that reads dump1090 (SBS-1) and publishes one event per
position to NATS (default) or, in legacy mode, batches to HTTP ingest.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401

from apps.aircraft_db import AircraftDatabase
from apps.bus_nats import NatsPublisher
from adsb.adsb import AircraftStateTracker, build_adsb_position_event, parse_sbs_line
from adsb.config import FLUSH_INTERVAL, RECONNECT_DELAY, get_dump1090_host, get_dump1090_port

SOURCE_ID = os.getenv("ADSB_SOURCE_ID", "UNKNOWN_SOURCE")
DEFAULT_OUTPUT_MODE = os.getenv("ADSB_OUTPUT_MODE", "nats").lower()


async def connect_to_dump1090(host: str, port: int):
    print(f"[sender] Connecting to dump1090 at {host}:{port}...", flush=True)
    reader, writer = await asyncio.open_connection(host, port)
    print(f"[sender] Connected to dump1090 at {host}:{port}", flush=True)
    return reader, writer


def send_batch(session: requests.Session, ingest_url: str, batch: List[Dict[str, Any]]) -> None:
    if not batch:
        return
    resp = session.post(ingest_url, json={"positions": batch}, timeout=10)
    resp.raise_for_status()
    print(f"[sender] Sent batch of {len(batch)} positions -> {ingest_url} (status {resp.status_code})", flush=True)


async def stream_positions(output_mode: str, ingest_url: Optional[str], batch_size: int = 100) -> None:
    host = get_dump1090_host()
    port = get_dump1090_port()
    tracker = AircraftStateTracker(lookup_aircraft_info=AircraftDatabase().lookup)
    publisher: Optional[NatsPublisher] = None
    session: Optional[requests.Session] = None

    if output_mode == "nats":
        publisher = NatsPublisher()
        await publisher.connect()
        print(f"[sender] Streaming SBS-1 to NATS subject {publisher.subject} @ {publisher.nats_url}")
    else:
        if not ingest_url:
            print("ADSB_INGEST_URL is required for HTTP mode", file=sys.stderr)
            sys.exit(1)
        session = requests.Session()
        print(f"[sender] Streaming SBS-1 to HTTP {ingest_url} (batch_size={batch_size})")

    batch: List[Dict[str, Any]] = []
    total = 0
    last_log = 0

    while True:
        reader = None
        writer = None
        try:
            reader, writer = await connect_to_dump1090(host, port)
            while True:
                line_bytes = await reader.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace")
                parsed = parse_sbs_line(line)
                if not parsed:
                    continue

                position, _has_full = tracker.update(parsed)
                if not position or position.get("lat") is None or position.get("lon") is None:
                    continue

                state = tracker.get_state(parsed.icao)
                if not state:
                    continue

                if output_mode == "nats" and publisher:
                    event = build_adsb_position_event(
                        state,
                        source=SOURCE_ID,
                        raw_sbs=parsed.raw,
                        message_type=parsed.message_type,
                        transmission_type=parsed.transmission_type,
                    )
                    await publisher.publish(event)
                elif output_mode == "http" and session:
                    batch.append(
                        {
                            "icao": position["icao"],
                            "flight": position.get("flight"),
                            "lat": position["lat"],
                            "lon": position["lon"],
                            "altitude_ft": position.get("altitude_ft"),
                            "speed_kts": position.get("speed_kts"),
                            "heading_deg": position.get("heading_deg"),
                            "squawk": position.get("squawk"),
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                    if len(batch) >= batch_size:
                        await asyncio.to_thread(send_batch, session, ingest_url, list(batch))
                        batch.clear()

                total += 1
                if total - last_log >= FLUSH_INTERVAL:
                    print(f"[sender] Forwarded {total} positions... (current batch={len(batch)})", flush=True)
                    last_log = total

        except KeyboardInterrupt:
            if output_mode == "http" and session and batch:
                try:
                    await asyncio.to_thread(send_batch, session, ingest_url or "", list(batch))
                except Exception as exc:  # noqa: BLE001
                    print(f"[sender] Final batch failed: {exc}")
            print(f"\n[sender] Stopped. Total forwarded: {total}")
            break
        except Exception as exc:  # noqa: BLE001
            if output_mode == "http" and session and batch:
                try:
                    await asyncio.to_thread(send_batch, session, ingest_url or "", list(batch))
                    batch.clear()
                except Exception as send_exc:  # noqa: BLE001
                    print(f"[sender] Failed to send batch during error handling: {send_exc}")
            print(f"[sender] Error: {exc}")
            print(f"[sender] Reconnecting in {RECONNECT_DELAY} seconds... (Ctrl+C to exit)")
            await asyncio.sleep(RECONNECT_DELAY)
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    if publisher:
        await publisher.close()


def main() -> None:
    output_mode = DEFAULT_OUTPUT_MODE
    if output_mode not in ("nats", "http"):
        print(f"[sender] Unknown ADSB_OUTPUT_MODE={output_mode}, defaulting to nats")
        output_mode = "nats"
    ingest_url = os.getenv("ADSB_INGEST_URL")
    batch_size = int(os.getenv("ADSB_BATCH_SIZE", "100"))

    print(
        f"[sender] ADSB_SOURCE_ID={SOURCE_ID} ADSB_HOST={get_dump1090_host()} ADSB_PORT={get_dump1090_port()} "
        f"OUTPUT_MODE={output_mode}",
        flush=True,
    )

    asyncio.run(stream_positions(output_mode=output_mode, ingest_url=ingest_url, batch_size=batch_size))


if __name__ == "__main__":
    main()
