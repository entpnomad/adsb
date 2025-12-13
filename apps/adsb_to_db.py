#!/usr/bin/env python3
"""
ADS-B to PostgreSQL ingestor.

- Streams SBS-1/BaseStation data from dump1090 into Postgres
- Or ingests existing CSV snapshots
- Or generates synthetic demo data (for environments without an antenna)
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Ensure project root is on sys.path
try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401

import psycopg2
import psycopg2.extras

from adsb.adsb import AircraftStateTracker, ParsedMessage, parse_sbs_line
from adsb.config import (
    CSV_COLUMNS,
    FLUSH_INTERVAL,
    RECONNECT_DELAY,
    get_current_max_age,
    get_current_csv_path,
    get_db_url,
    get_dump1090_host,
    get_dump1090_port,
    get_history_csv_path,
)
from adsb.geo import get_home_location


DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS aircraft (
        icao TEXT PRIMARY KEY,
        first_seen_utc TIMESTAMPTZ NOT NULL,
        last_seen_utc  TIMESTAMPTZ NOT NULL,
        last_flight    TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id BIGSERIAL PRIMARY KEY,
        icao TEXT NOT NULL REFERENCES aircraft(icao),
        ts   TIMESTAMPTZ NOT NULL,
        lat  DOUBLE PRECISION NOT NULL,
        lon  DOUBLE PRECISION NOT NULL,
        altitude_ft INTEGER,
        speed_kts   REAL,
        heading_deg REAL,
        squawk      TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_positions_ts ON positions(ts);",
    "CREATE INDEX IF NOT EXISTS idx_positions_icao_ts ON positions(icao, ts);",
]


def connect_db(db_url: str):
    return psycopg2.connect(db_url)


def ensure_schema(conn) -> None:
    with conn:
        with conn.cursor() as cur:
            for ddl in DDL_STATEMENTS:
                cur.execute(ddl)


def flush_batches(
    conn,
    aircraft_rows: List[Tuple[Any, ...]],
    position_rows: List[Tuple[Any, ...]],
) -> None:
    if not aircraft_rows and not position_rows:
        return

    with conn:
        with conn.cursor() as cur:
            if aircraft_rows:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO aircraft (icao, first_seen_utc, last_seen_utc, last_flight)
                    VALUES %s
                    ON CONFLICT (icao) DO UPDATE SET
                        last_seen_utc = EXCLUDED.last_seen_utc,
                        last_flight   = COALESCE(EXCLUDED.last_flight, aircraft.last_flight)
                    """,
                    aircraft_rows,
                )

            if position_rows:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO positions (icao, ts, lat, lon, altitude_ft, speed_kts, heading_deg, squawk)
                    VALUES %s
                    """,
                    position_rows,
                )


def position_to_rows(position: Dict[str, Any], ts: datetime) -> Tuple[Tuple[Any, ...], Tuple[Any, ...]]:
    """Prepare row tuples for aircraft and positions tables."""
    ts_iso = ts.replace(tzinfo=timezone.utc)
    aircraft_row = (
        position["icao"],
        ts_iso,
        ts_iso,
        position.get("flight") or None,
    )
    position_row = (
        position["icao"],
        ts_iso,
        position["lat"],
        position["lon"],
        position.get("altitude_ft"),
        position.get("speed_kts"),
        position.get("heading_deg"),
        position.get("squawk"),
    )
    return aircraft_row, position_row


def connect_to_dump1090(host: str, port: int) -> socket.socket:
    """Create a TCP connection to dump1090."""
    try:
        sock = socket.create_connection((host, port), timeout=10)
        print(f"Connected to dump1090 at {host}:{port}")
        return sock
    except (socket.error, OSError) as e:
        print(f"Failed to connect to {host}:{port}: {e}")
        raise


def stream_from_dump1090(db_url: str, batch_size: int = 100) -> None:
    host = get_dump1090_host()
    port = get_dump1090_port()
    max_age = get_current_max_age()

    print(f"Streaming from dump1090 {host}:{port} -> {db_url}")
    conn = connect_db(db_url)
    ensure_schema(conn)
    tracker = AircraftStateTracker()

    aircraft_rows: List[Tuple[Any, ...]] = []
    position_rows: List[Tuple[Any, ...]] = []
    record_count = 0
    last_log = 0

    while True:
        try:
            sock = connect_to_dump1090(host, port)
            with sock.makefile("r", encoding="utf-8", errors="replace") as f:
                print("Reading SBS-1 stream... (Ctrl+C to stop)")
                for line in f:
                    parsed: Optional[ParsedMessage] = parse_sbs_line(line)
                    if not parsed:
                        continue

                    position, _has_full = tracker.update(parsed)
                    if position:
                        ts = datetime.now(timezone.utc)
                        a_row, p_row = position_to_rows(position, ts)
                        aircraft_rows.append(a_row)
                        position_rows.append(p_row)
                        record_count += 1

                    if record_count and record_count % batch_size == 0:
                        flush_batches(conn, aircraft_rows, position_rows)
                        aircraft_rows.clear()
                        position_rows.clear()

                    if record_count - last_log >= FLUSH_INTERVAL:
                        if record_count % 100 == 0:
                            print(f"Logged {record_count} positions...", end="\r")
                        last_log = record_count

        except KeyboardInterrupt:
            flush_batches(conn, aircraft_rows, position_rows)
            print(f"\nStopped. Total positions: {record_count}")
            sys.exit(0)
        except (socket.error, OSError, ConnectionError) as e:
            print(f"Connection error: {e}")
            flush_batches(conn, aircraft_rows, position_rows)
            print(f"Reconnecting in {RECONNECT_DELAY} seconds... (Press Ctrl+C to exit)")
            time.sleep(RECONNECT_DELAY)
        except Exception as e:
            print(f"Unexpected error: {e}")
            flush_batches(conn, aircraft_rows, position_rows)
            print(f"Reconnecting in {RECONNECT_DELAY} seconds...")
            time.sleep(RECONNECT_DELAY)


def ingest_csv(db_url: str, csv_path: str, batch_size: int = 500) -> None:
    conn = connect_db(db_url)
    ensure_schema(conn)

    aircraft_rows: List[Tuple[Any, ...]] = []
    position_rows: List[Tuple[Any, ...]] = []
    count = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                if not row.get("icao") or not row.get("lat") or not row.get("lon"):
                    continue

                ts_str = row.get("timestamp_utc") or ""
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except ValueError:
                    ts = datetime.now(timezone.utc)

                position = {
                    "icao": row.get("icao", "").strip(),
                    "flight": row.get("flight", "").strip(),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "altitude_ft": int(float(row["altitude_ft"])) if row.get("altitude_ft") else None,
                    "speed_kts": float(row["speed_kts"]) if row.get("speed_kts") else None,
                    "heading_deg": float(row["heading_deg"]) if row.get("heading_deg") else None,
                    "squawk": row.get("squawk", "").strip(),
                }
                a_row, p_row = position_to_rows(position, ts)
                aircraft_rows.append(a_row)
                position_rows.append(p_row)
                count += 1

                if count % batch_size == 0:
                    flush_batches(conn, aircraft_rows, position_rows)
                    aircraft_rows.clear()
                    position_rows.clear()
                    print(f"Ingested {count} rows...", end="\r")
            except Exception as e:
                print(f"Skipping row: {e}")
                continue

    flush_batches(conn, aircraft_rows, position_rows)
    print(f"\nFinished ingesting {count} rows from {csv_path}")


def generate_demo_positions(center_lat: float, center_lon: float, aircraft: int = 5, points_per_ac: int = 20) -> Iterable[Dict[str, Any]]:
    """
    Generate synthetic positions near a center point.
    """
    for ac_idx in range(aircraft):
        icao = f"D{random.randrange(16**5):05X}"
        heading = random.uniform(0, 360)
        speed = random.uniform(180, 460)
        alt = random.uniform(3000, 38000)

        lat = center_lat + random.uniform(-0.05, 0.05)
        lon = center_lon + random.uniform(-0.05, 0.05)

        for step in range(points_per_ac):
            # Simple drift
            distance_km = (speed / 3600) * 5  # 5-second step equivalent
            delta_lat = (distance_km / 111) * math.cos(math.radians(heading))
            delta_lon = (distance_km / (111 * math.cos(math.radians(lat)))) * math.sin(math.radians(heading))
            lat += delta_lat
            lon += delta_lon
            alt += random.uniform(-200, 200)
            heading = (heading + random.uniform(-5, 5)) % 360

            yield {
                "icao": icao,
                "flight": f"DEMO{ac_idx:02d}",
                "lat": lat,
                "lon": lon,
                "altitude_ft": int(alt),
                "speed_kts": speed,
                "heading_deg": heading,
                "squawk": None,
            }


def simulate_to_db(db_url: str, total_positions: int = 200, batch_size: int = 200) -> None:
    conn = connect_db(db_url)
    ensure_schema(conn)

    home = get_home_location()
    center_lat = home["lat"]
    center_lon = home["lon"]

    aircraft = max(3, total_positions // 20)
    points_per = max(5, total_positions // aircraft)

    aircraft_rows: List[Tuple[Any, ...]] = []
    position_rows: List[Tuple[Any, ...]] = []
    count = 0

    for position in generate_demo_positions(center_lat, center_lon, aircraft=aircraft, points_per_ac=points_per):
        ts = datetime.now(timezone.utc)
        a_row, p_row = position_to_rows(position, ts)
        aircraft_rows.append(a_row)
        position_rows.append(p_row)
        count += 1

        if len(position_rows) >= batch_size:
            flush_batches(conn, aircraft_rows, position_rows)
            aircraft_rows.clear()
            position_rows.clear()

        if count >= total_positions:
            break

    flush_batches(conn, aircraft_rows, position_rows)
    print(f"Inserted {count} synthetic positions for {aircraft} aircraft centered at ({center_lat:.4f}, {center_lon:.4f})")


def simulate_to_csv(
    total_positions: int = 200,
    history_path: Optional[Path] = None,
    current_path: Optional[Path] = None,
) -> None:
    """
    Generate synthetic positions into CSV files (history + current snapshot).
    """
    history_path = history_path or get_history_csv_path()
    current_path = current_path or get_current_csv_path()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.parent.mkdir(parents=True, exist_ok=True)

    home = get_home_location()
    center_lat = home["lat"]
    center_lon = home["lon"]

    aircraft = max(3, total_positions // 20)
    points_per = max(5, total_positions // aircraft)

    positions = list(generate_demo_positions(center_lat, center_lon, aircraft=aircraft, points_per_ac=points_per))

    # Assign timestamps with small deltas so they sort nicely
    now = datetime.now(timezone.utc)
    for idx, pos in enumerate(positions):
        pos["timestamp_utc"] = (now + timedelta(seconds=idx)).isoformat()

    # Write history
    with open(history_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for pos in positions:
            writer.writerow([
                pos["timestamp_utc"],
                pos["icao"],
                pos["flight"],
                pos["lat"],
                pos["lon"],
                pos.get("altitude_ft") or "",
                pos.get("speed_kts") or "",
                pos.get("heading_deg") or "",
                pos.get("squawk") or "",
            ])

    # Current snapshot: take latest per ICAO
    latest_by_icao: Dict[str, Dict[str, Any]] = {}
    for pos in positions:
        latest_by_icao[pos["icao"]] = pos

    with open(current_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for icao, pos in sorted(latest_by_icao.items()):
            writer.writerow([
                pos["timestamp_utc"],
                pos["icao"],
                pos["flight"],
                pos["lat"],
                pos["lon"],
                pos.get("altitude_ft") or "",
                pos.get("speed_kts") or "",
                pos.get("heading_deg") or "",
                pos.get("squawk") or "",
            ])

    print(f"Wrote synthetic CSV data: {len(positions)} records -> {history_path}, current snapshot -> {current_path}")


def main():
    parser = argparse.ArgumentParser(description="ADS-B to PostgreSQL ingestor")
    parser.add_argument("--db-url", help="PostgreSQL URL (fallback env ADSB_DB_URL)")
    parser.add_argument("--batch-size", type=int, default=200, help="Batch size for inserts (default: 200)")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stream", action="store_true", help="Stream live from dump1090")
    group.add_argument("--from-csv", dest="from_csv", help="Ingest existing CSV file")
    group.add_argument("--simulate", type=int, nargs="?", const=200, help="Generate synthetic positions (default 200)")

    args = parser.parse_args()

    if args.db_url:
        os_db_url = args.db_url
    else:
        os_db_url = get_db_url()

    if args.stream:
        stream_from_dump1090(os_db_url, batch_size=args.batch_size)
    elif args.from_csv:
        ingest_csv(os_db_url, args.from_csv, batch_size=args.batch_size)
    elif args.simulate:
        simulate_to_db(os_db_url, total_positions=args.simulate, batch_size=args.batch_size)
    else:
        parser.error("No mode selected")


if __name__ == "__main__":
    main()
