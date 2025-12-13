#!/usr/bin/env python3
"""
ADS-B to CSV Logger

Connects to dump1090 SBS-1 stream (TCP port 30003) and logs aircraft positions
to two CSV files:
1. Historical: all position records (append-only)
2. Current: latest position per aircraft seen in the last 60 seconds (snapshot)

Usage:
    python -m apps.adsb_to_csv

Environment Variables:
    ADSB_HOST: dump1090 host (default: 127.0.0.1)
    ADSB_PORT: dump1090 port (default: 30003)
    ADSB_CSV_PATH: historical CSV file path (default: output/adsb_history.csv)
    ADSB_CURRENT_CSV_PATH: current positions CSV (default: output/adsb_current.csv)
    ADSB_CURRENT_MAX_AGE_SECONDS: max age in seconds for current CSV (default: 60)
"""

import csv
import socket
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

# Ensure project root is on sys.path
try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401

# Import shared configuration
from adsb.adsb import (
    AircraftStateTracker,
    ParsedMessage,
    parse_sbs_line,
)
from adsb.config import (
    get_history_csv_path,
    get_current_csv_path,
    get_dump1090_host,
    get_dump1090_port,
    get_current_max_age,
    CSV_COLUMNS,
    RECONNECT_DELAY,
    FLUSH_INTERVAL,
    CURRENT_UPDATE_INTERVAL,
)


def ensure_csv_header(csv_path) -> None:
    """Ensure CSV file exists with header row."""
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)
        print(f"Created CSV file: {csv_path}")


def write_current_positions_csv(csv_path, current_positions: Dict[str, Dict[str, Any]],
                                 max_age_seconds: int = 60) -> None:
    """
    Write the current positions CSV file with latest position for each aircraft.
    Only includes aircraft seen within the last max_age_seconds.
    """
    now = datetime.now(timezone.utc)
    cutoff_time = now - timedelta(seconds=max_age_seconds)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)

        # Filter to only recent positions
        recent_positions = []
        for icao, pos in current_positions.items():
            try:
                pos_time = datetime.fromisoformat(pos["timestamp_utc"].replace("Z", "+00:00"))
                if pos_time >= cutoff_time:
                    recent_positions.append((icao, pos))
            except (ValueError, KeyError):
                recent_positions.append((icao, pos))

        # Write sorted by ICAO for consistency
        for icao, pos in sorted(recent_positions, key=lambda x: x[0]):
            writer.writerow([
                pos["timestamp_utc"],
                pos["icao"],
                pos["flight"],
                pos["lat"],
                pos["lon"],
                pos["altitude_ft"] if pos["altitude_ft"] is not None else "",
                pos["speed_kts"] if pos["speed_kts"] is not None else "",
                pos["heading_deg"] if pos["heading_deg"] is not None else "",
                pos["squawk"] if pos["squawk"] else "",
            ])


def write_position(csv_path, position: Dict[str, Any], timestamp_utc: Optional[str] = None) -> None:
    """Write a position record to the CSV file."""
    if timestamp_utc is None:
        timestamp_utc = datetime.now(timezone.utc).isoformat()

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            timestamp_utc,
            position["icao"],
            position["flight"],
            position["lat"],
            position["lon"],
            position["altitude_ft"] if position["altitude_ft"] is not None else "",
            position["speed_kts"] if position["speed_kts"] is not None else "",
            position["heading_deg"] if position["heading_deg"] is not None else "",
            position["squawk"] if position["squawk"] else "",
        ])


def connect_to_dump1090(host: str, port: int) -> socket.socket:
    """Create a TCP connection to dump1090."""
    try:
        sock = socket.create_connection((host, port), timeout=10)
        print(f"Connected to dump1090 at {host}:{port}")
        return sock
    except (socket.error, OSError) as e:
        print(f"Failed to connect to {host}:{port}: {e}")
        raise


def main():
    """Main processing loop."""
    # Get configuration
    host = get_dump1090_host()
    port = get_dump1090_port()
    csv_path = get_history_csv_path()
    current_csv_path = get_current_csv_path()
    max_age = get_current_max_age()

    print(f"Starting ADS-B CSV logger")
    print(f"  Host: {host}:{port}")
    print(f"  Historical CSV: {csv_path}")
    print(f"  Current CSV: {current_csv_path}")

    ensure_csv_header(csv_path)
    ensure_csv_header(current_csv_path)

    # Track latest position for each aircraft
    current_positions: Dict[str, Dict[str, Any]] = {}
    tracker = AircraftStateTracker()

    record_count = 0
    last_flush_count = 0
    last_current_update = 0

    while True:
        try:
            sock = connect_to_dump1090(host, port)

            with sock.makefile("r", encoding="utf-8", errors="replace") as f:
                print("Reading SBS-1 stream... (Ctrl+C to stop)")

                for line in f:
                    try:
                        parsed_msg = parse_sbs_line(line)
                        if parsed_msg:
                            position, _has_full_velocity = tracker.update(parsed_msg)

                            if position:
                                timestamp_utc = datetime.now(timezone.utc).isoformat()
                                position_with_ts = {**position, "timestamp_utc": timestamp_utc}

                                # Write to historical CSV even if we do not yet have velocity
                                write_position(csv_path, position, timestamp_utc)

                                # Update current positions snapshot
                                current_positions[position["icao"]] = position_with_ts

                            record_count += 1

                            # Update current positions CSV periodically
                            if record_count - last_current_update >= CURRENT_UPDATE_INTERVAL:
                                write_current_positions_csv(
                                    current_csv_path,
                                    current_positions,
                                    max_age
                                )
                                last_current_update = record_count

                            # Periodic status update
                            if record_count - last_flush_count >= FLUSH_INTERVAL:
                                if record_count % 100 == 0:
                                    aircraft_count = len(current_positions)
                                    print(f"Logged {record_count} records ({aircraft_count} aircraft)...", end="\r")
                                last_flush_count = record_count

                    except Exception as e:
                        print(f"\nWarning: Error parsing line: {e}", file=sys.stderr)
                        continue

        except KeyboardInterrupt:
            # Final update before exit
            if current_positions:
                write_current_positions_csv(current_csv_path, current_positions, max_age)

            now = datetime.now(timezone.utc)
            cutoff_time = now - timedelta(seconds=max_age)
            recent_count = sum(
                1 for pos in current_positions.values()
                if datetime.fromisoformat(pos["timestamp_utc"].replace("Z", "+00:00")) >= cutoff_time
            )
            aircraft_count = len(current_positions)
            print(f"\n\nStopped by user. Total positions logged: {record_count} "
                  f"({aircraft_count} unique aircraft, {recent_count} in last {max_age}s)")
            sys.exit(0)

        except (socket.error, OSError, ConnectionError) as e:
            print(f"Connection error: {e}")
            print(f"Reconnecting in {RECONNECT_DELAY} seconds... (Press Ctrl+C to exit)")
            time.sleep(RECONNECT_DELAY)

        except Exception as e:
            print(f"\nUnexpected error: {e}", file=sys.stderr)
            print(f"Reconnecting in {RECONNECT_DELAY} seconds...")
            time.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    main()
