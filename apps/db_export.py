#!/usr/bin/env python3
"""
Export positions from Postgres to CSV for map rendering.

Usage:
  ADSB_DB_URL=postgresql://user:pass@host:5432/adsb \
  python db_export.py --hours 6
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401
import psycopg2

from adsb.config import CSV_COLUMNS, OUTPUT_DIR


def export_positions(db_url: str, hours: int, history_csv: Path, current_csv: Path) -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with psycopg2.connect(db_url) as conn:
        with conn.cursor() as cur:
            # History: positions in window
            cur.execute(
                """
                SELECT ts, icao, lat, lon, altitude_ft, speed_kts, heading_deg, squawk, flight
                FROM positions
                WHERE ts >= %s
                ORDER BY ts ASC
                """,
                (since,),
            )
            rows = cur.fetchall()

            history_csv.parent.mkdir(parents=True, exist_ok=True)
            with open(history_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_COLUMNS)
                for ts, icao, lat, lon, alt, spd, hdg, squawk, flight in rows:
                    writer.writerow([
                        ts.isoformat(),
                        icao,
                        flight or "",
                        lat,
                        lon,
                        alt or "",
                        spd or "",
                        hdg or "",
                        squawk or "",
                    ])

            # Current: latest per ICAO
            cur.execute(
                """
                SELECT DISTINCT ON (icao) ts, icao, lat, lon, altitude_ft, speed_kts, heading_deg, squawk, flight
                FROM positions
                WHERE ts >= %s
                ORDER BY icao, ts DESC
                """,
                (since,),
            )
            rows = cur.fetchall()
            with open(current_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_COLUMNS)
                for ts, icao, lat, lon, alt, spd, hdg, squawk, flight in rows:
                    writer.writerow([
                        ts.isoformat(),
                        icao,
                        flight or "",
                        lat,
                        lon,
                        alt or "",
                        spd or "",
                        hdg or "",
                        squawk or "",
                    ])

    print(f"History CSV:  {history_csv} ({len(rows)} current aircraft)")
    print(f"Current CSV:  {current_csv}")


def main():
    parser = argparse.ArgumentParser(description="Export positions from Postgres to CSVs")
    parser.add_argument("--db-url", default=None, help="PostgreSQL URL (env ADSB_DB_URL)")
    parser.add_argument("--hours", type=int, default=6, help="Hours of history to export (default: 6)")
    parser.add_argument("--history-csv", default=str(OUTPUT_DIR / "adsb_history.csv"), help="History CSV path")
    parser.add_argument("--current-csv", default=str(OUTPUT_DIR / "adsb_current.csv"), help="Current CSV path")
    args = parser.parse_args()

    db_url = args.db_url or None
    if not db_url:
        import os
        db_url = os.getenv("ADSB_DB_URL")
    if not db_url:
        raise SystemExit("ADSB_DB_URL not set and --db-url not provided")

    export_positions(
        db_url=db_url,
        hours=args.hours,
        history_csv=Path(args.history_csv),
        current_csv=Path(args.current_csv),
    )


if __name__ == "__main__":
    main()
