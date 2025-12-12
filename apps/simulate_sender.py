#!/usr/bin/env python3
"""
Simulate an antenna by sending synthetic ADS-B positions to NATS (default)
or legacy HTTP ingest.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401

from apps.adsb_to_db import generate_demo_positions
from apps.bus_nats import NatsPublisher
from adsb.adsb import AircraftState, build_adsb_position_event


def build_payload(center_lat: float, center_lon: float, aircraft: int, points_per_ac: int) -> List[Dict[str, Any]]:
    positions: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for pos in generate_demo_positions(center_lat, center_lon, aircraft=aircraft, points_per_ac=points_per_ac):
        positions.append(
            {
                "icao": pos["icao"],
                "flight": pos.get("flight"),
                "lat": pos["lat"],
                "lon": pos["lon"],
                "altitude_ft": pos.get("altitude_ft"),
                "speed_kts": pos.get("speed_kts"),
                "heading_deg": pos.get("heading_deg"),
                "squawk": pos.get("squawk"),
                "ts": now,
            }
        )
    return positions


def build_events(center_lat: float, center_lon: float, aircraft: int, points_per_ac: int, source_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for pos in generate_demo_positions(center_lat, center_lon, aircraft=aircraft, points_per_ac=points_per_ac):
        state = AircraftState(
            icao=pos["icao"],
            flight=pos.get("flight") or "",
            lat=pos["lat"],
            lon=pos["lon"],
            altitude_ft=pos.get("altitude_ft"),
            speed_kts=pos.get("speed_kts"),
            heading_deg=pos.get("heading_deg"),
            squawk=pos.get("squawk"),
        )
        events.append(
            build_adsb_position_event(
                state,
                source=source_id,
                raw_sbs=None,
                message_type="SIM",
                transmission_type=None,
            )
        )
    return events


def send_once_http(ingest_url: str, payload: List[Dict[str, Any]]) -> None:
    if not payload:
        return
    resp = requests.post(ingest_url, json={"positions": payload}, timeout=10)
    resp.raise_for_status()


async def send_loop_nats(
    center_lat: float,
    center_lon: float,
    aircraft: int,
    points_per_ac: int,
    interval: float,
    source_id: str,
) -> None:
    async with NatsPublisher() as publisher:
        print(f"[sim] Publishing demo positions to NATS {publisher.nats_url} subject {publisher.subject} every {interval}s")
        while True:
            events = build_events(center_lat, center_lon, aircraft, points_per_ac, source_id)
            for event in events:
                await publisher.publish(event)
            print(f"[sim] Sent {len(events)} events", end="\r")
            await asyncio.sleep(interval)


def loop_send_http(
    ingest_url: str,
    center_lat: float,
    center_lon: float,
    aircraft: int,
    points_per_ac: int,
    interval: float,
) -> None:
    print(f"[sim] Sending demo positions to {ingest_url} every {interval}s")
    while True:
        payload = build_payload(center_lat, center_lon, aircraft, points_per_ac)
        try:
            send_once_http(ingest_url, payload)
            print(f"[sim] Sent {len(payload)} positions", end="\r")
        except Exception as exc:  # noqa: BLE001
            print(f"[sim] Send failed: {exc}", file=sys.stderr)
        time.sleep(interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate ADS-B sender posting to NATS or API ingest")
    parser.add_argument("--ingest-url", default=os.getenv("ADSB_INGEST_URL"), help="API ingest endpoint (http legacy)")
    parser.add_argument("--center-lat", type=float, default=float(os.getenv("ADSB_SIM_CENTER_LAT", "40.4168")), help="Center latitude for demo tracks")
    parser.add_argument("--center-lon", type=float, default=float(os.getenv("ADSB_SIM_CENTER_LON", "-3.7038")), help="Center longitude for demo tracks")
    parser.add_argument("--aircraft", type=int, default=int(os.getenv("ADSB_SIM_AIRCRAFT", "5")), help="Number of aircraft to simulate")
    parser.add_argument("--points-per-ac", type=int, default=int(os.getenv("ADSB_SIM_POINTS", "10")), help="Points per aircraft per batch")
    parser.add_argument("--interval", type=float, default=float(os.getenv("ADSB_SIM_INTERVAL", "5")), help="Seconds between batches")
    parser.add_argument("--output-mode", default=os.getenv("ADSB_OUTPUT_MODE", "nats"), choices=["nats", "http"], help="Send via NATS (default) or HTTP legacy ingest")
    parser.add_argument("--source-id", default=os.getenv("ADSB_SOURCE_ID", "SIMULATOR"), help="Source identifier for events (NATS mode)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mode = (args.output_mode or "nats").lower()
    if mode == "nats":
        asyncio.run(
            send_loop_nats(
                center_lat=args.center_lat,
                center_lon=args.center_lon,
                aircraft=args.aircraft,
                points_per_ac=args.points_per_ac,
                interval=args.interval,
                source_id=args.source_id,
            )
        )
    else:
        if not args.ingest_url:
            print("ADSB_INGEST_URL (or --ingest-url) is required for HTTP mode", file=sys.stderr)
            sys.exit(1)
        loop_send_http(
            ingest_url=args.ingest_url,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            aircraft=args.aircraft,
            points_per_ac=args.points_per_ac,
            interval=args.interval,
        )


if __name__ == "__main__":
    main()
