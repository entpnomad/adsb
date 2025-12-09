#!/usr/bin/env python3
"""
Minimal ADS-B sender that reads dump1090 (SBS-1) and POSTS positions to the API ingest endpoint.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.lib.adsb import AircraftStateTracker, ParsedMessage, parse_sbs_line
from src.lib.config import FLUSH_INTERVAL, RECONNECT_DELAY, get_dump1090_host, get_dump1090_port


def connect_to_dump1090(host: str, port: int) -> socket.socket:
    try:
        print(f"[sender] Connecting to dump1090 at {host}:{port}...", flush=True)
        sock = socket.create_connection((host, port), timeout=10)
        print(f"[sender] Connected to dump1090 at {host}:{port}", flush=True)
        return sock
    except (socket.error, OSError) as exc:
        print(f"[sender] Failed to connect to {host}:{port}: {exc}", flush=True)
        raise


def send_batch(session: requests.Session, ingest_url: str, batch: List[Dict[str, Any]]) -> None:
    if not batch:
        return
    try:
        resp = session.post(ingest_url, json={"positions": batch}, timeout=10)
        resp.raise_for_status()
        print(f"[sender] Sent batch of {len(batch)} positions -> {ingest_url} (status {resp.status_code})", flush=True)
    except Exception as exc:  # noqa: BLE001
        # Log response content if available to aid debugging
        err_txt = ""
        if "resp" in locals():
            try:
                err_txt = f" | response: {resp.status_code} {resp.text[:500]}"
            except Exception:
                err_txt = ""
        print(f"[sender] Failed to send batch of {len(batch)} positions: {exc}{err_txt}", flush=True)
        raise


def stream_to_api(ingest_url: str, batch_size: int = 100) -> None:
    host = get_dump1090_host()
    port = get_dump1090_port()
    tracker = AircraftStateTracker()
    session = requests.Session()

    batch: List[Dict[str, Any]] = []
    total = 0
    last_log = 0

    while True:
        try:
            sock = connect_to_dump1090(host, port)
            with sock.makefile("r", encoding="utf-8", errors="replace") as f:
                print(f"[sender] Streaming SBS-1 and forwarding to {ingest_url} (batch_size={batch_size})", flush=True)
                for line in f:
                    if not line:
                        continue
                    parsed: Optional[ParsedMessage] = parse_sbs_line(line)
                    if not parsed:
                        continue

                    position, _has_full = tracker.update(parsed)
                    if not position or position.get("lat") is None or position.get("lon") is None:
                        continue

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
                    total += 1

                    if len(batch) >= batch_size:
                        send_batch(session, ingest_url, batch)
                        batch.clear()

                    if total - last_log >= FLUSH_INTERVAL:
                        print(f"[sender] Forwarded {total} positions... (current batch={len(batch)})", flush=True)
                        last_log = total

        except KeyboardInterrupt:
            if batch:
                try:
                    send_batch(session, ingest_url, batch)
                except Exception as exc:  # noqa: BLE001
                    print(f"[sender] Final batch failed: {exc}")
            print(f"\n[sender] Stopped. Total forwarded: {total}")
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            try:
                if batch:
                    send_batch(session, ingest_url, batch)
                    batch.clear()
            except Exception as send_exc:  # noqa: BLE001
                print(f"[sender] Failed to send batch during error handling: {send_exc}")
            print(f"[sender] Error: {exc}")
            print(f"[sender] Reconnecting in {RECONNECT_DELAY} seconds... (Ctrl+C to exit)")
            time.sleep(RECONNECT_DELAY)


def main() -> None:
    ingest_url = os.getenv("ADSB_INGEST_URL")
    if not ingest_url:
        print("ADSB_INGEST_URL is required (e.g. http://server:8000/api/ingest)", file=sys.stderr)
        sys.exit(1)

    batch_size = int(os.getenv("ADSB_BATCH_SIZE", "100"))
    print(
        f"[sender] Starting ADS-B sender with ADSB_HOST={get_dump1090_host()} ADSB_PORT={get_dump1090_port()} "
        f"ADSB_INGEST_URL={ingest_url} BATCH_SIZE={batch_size}",
        flush=True,
    )
    stream_to_api(ingest_url, batch_size=batch_size)


if __name__ == "__main__":
    main()
