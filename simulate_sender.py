#!/usr/bin/env python3
"""
Simulate an antenna by sending synthetic ADS-B positions to the API ingest endpoint.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from adsb_to_db import generate_demo_positions


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


def send_once(ingest_url: str, payload: List[Dict[str, Any]]) -> None:
    if not payload:
        return
    resp = requests.post(ingest_url, json={"positions": payload}, timeout=10)
    resp.raise_for_status()


def loop_send(
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
            send_once(ingest_url, payload)
            print(f"[sim] Sent {len(payload)} positions", end="\r")
        except Exception as exc:  # noqa: BLE001
            print(f"[sim] Send failed: {exc}", file=sys.stderr)
        time.sleep(interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate ADS-B sender posting to API ingest")
    parser.add_argument("--ingest-url", default=os.getenv("ADSB_INGEST_URL"), help="API ingest endpoint (e.g., http://server:8000/api/ingest)")
    parser.add_argument("--center-lat", type=float, default=float(os.getenv("ADSB_SIM_CENTER_LAT", "40.4168")), help="Center latitude for demo tracks")
    parser.add_argument("--center-lon", type=float, default=float(os.getenv("ADSB_SIM_CENTER_LON", "-3.7038")), help="Center longitude for demo tracks")
    parser.add_argument("--aircraft", type=int, default=int(os.getenv("ADSB_SIM_AIRCRAFT", "5")), help="Number of aircraft to simulate")
    parser.add_argument("--points-per-ac", type=int, default=int(os.getenv("ADSB_SIM_POINTS", "10")), help="Points per aircraft per batch")
    parser.add_argument("--interval", type=float, default=float(os.getenv("ADSB_SIM_INTERVAL", "5")), help="Seconds between batches")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.ingest_url:
        print("ADSB_INGEST_URL (or --ingest-url) is required", file=sys.stderr)
        sys.exit(1)

    loop_send(
        ingest_url=args.ingest_url,
        center_lat=args.center_lat,
        center_lon=args.center_lon,
        aircraft=args.aircraft,
        points_per_ac=args.points_per_ac,
        interval=args.interval,
    )


if __name__ == "__main__":
    main()
