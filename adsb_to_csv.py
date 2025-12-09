#!/usr/bin/env python3
"""
ADS-B to CSV Logger

Connects to dump1090 SBS-1 stream (TCP port 30003) and logs aircraft positions
to two CSV files:
1. Historical: all position records (append-only)
2. Current: latest position per aircraft seen in the last 60 seconds (snapshot)

Usage:
    python3 adsb_to_csv.py

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

# Import shared configuration
from src.lib.config import (
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


def parse_sbs_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single SBS-1 format line.

    Expected format:
    MSG,subtype,transmission_type,session_id,icao,flight_id,date,time,date2,time2,
    callsign,altitude,speed,track,lat,lon,vertical_rate,squawk,alert,emergency,spi,surface

    MSG types:
    - MSG,1: Callsign (flight number)
    - MSG,3: Airborne position (lat, lon, altitude)
    - MSG,4: Airborne velocity (speed, heading)
    - MSG,5: Surface position
    - MSG,6: Surveillance altitude
    - MSG,7: Air-to-air
    - MSG,8: All call reply

    Returns dict with parsed fields (partial data allowed), or None if line is invalid.
    """
    line = line.strip()
    if not line:
        return None

    fields = line.split(",")

    # Must be a MSG type
    if len(fields) < 5 or fields[0] != "MSG":
        return None

    icao = fields[4].strip()
    if not icao:
        return None

    # Initialize result with ICAO
    result = {
        "icao": icao,
        "flight": None,
        "lat": None,
        "lon": None,
        "altitude_ft": None,
        "speed_kts": None,
        "heading_deg": None,
        "squawk": None,
        "has_position": False,
    }

    # Extract callsign/flight (field 10)
    if len(fields) > 10 and fields[10].strip():
        result["flight"] = fields[10].strip()

    # Extract altitude (field 11)
    if len(fields) > 11 and fields[11].strip():
        try:
            result["altitude_ft"] = int(float(fields[11]))
        except ValueError:
            pass

    # Extract speed (field 12)
    if len(fields) > 12 and fields[12].strip():
        try:
            result["speed_kts"] = float(fields[12])
        except ValueError:
            pass

    # Extract heading/track (field 13)
    if len(fields) > 13 and fields[13].strip():
        try:
            result["heading_deg"] = float(fields[13])
        except ValueError:
            pass

    # Extract lat/lon (fields 14, 15)
    if len(fields) > 15:
        try:
            lat_str = fields[14].strip()
            lon_str = fields[15].strip()

            if lat_str and lon_str:
                lat = float(lat_str)
                lon = float(lon_str)

                # Basic validation
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    result["lat"] = lat
                    result["lon"] = lon
                    result["has_position"] = True
        except (ValueError, IndexError):
            pass

    # Extract squawk (field 17)
    if len(fields) > 17 and fields[17].strip():
        result["squawk"] = fields[17].strip()

    return result


# Track aircraft state across multiple messages
aircraft_state: Dict[str, Dict[str, Any]] = {}


def update_aircraft_state(parsed: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], bool]:
    """
    Update tracked aircraft state with new data.
    Returns tuple of (position_record, is_complete).
    - position_record: dict if we have lat/lon, None otherwise (for history CSV)
    - is_complete: True if we have position AND velocity data (for current CSV)
    """
    icao = parsed["icao"]

    # Initialize state if new aircraft
    if icao not in aircraft_state:
        aircraft_state[icao] = {
            "icao": icao,
            "flight": "",
            "lat": None,
            "lon": None,
            "altitude_ft": None,
            "speed_kts": None,
            "heading_deg": None,
            "squawk": None,
            "last_update": None,
        }

    state = aircraft_state[icao]

    # Update state with any non-None values from this message
    if parsed["flight"]:
        state["flight"] = parsed["flight"]
    if parsed["lat"] is not None:
        state["lat"] = parsed["lat"]
    if parsed["lon"] is not None:
        state["lon"] = parsed["lon"]
    if parsed["altitude_ft"] is not None:
        state["altitude_ft"] = parsed["altitude_ft"]
    if parsed["speed_kts"] is not None:
        state["speed_kts"] = parsed["speed_kts"]
    if parsed["heading_deg"] is not None:
        state["heading_deg"] = parsed["heading_deg"]
    if parsed["squawk"]:
        state["squawk"] = parsed["squawk"]

    state["last_update"] = datetime.now(timezone.utc).isoformat()

    # Only return a record if we have a valid position
    if state["lat"] is not None and state["lon"] is not None:
        record = {
            "icao": state["icao"],
            "flight": state["flight"] or "",
            "lat": state["lat"],
            "lon": state["lon"],
            "altitude_ft": state["altitude_ft"],
            "speed_kts": state["speed_kts"],
            "heading_deg": state["heading_deg"],
            "squawk": state["squawk"],
        }
        # Consider complete if we have both position and velocity data
        is_complete = (state["speed_kts"] is not None and state["heading_deg"] is not None)
        return record, is_complete

    return None, False


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
                        parsed = parse_sbs_line(line)
                        if parsed:
                            # Update aircraft state with this message's data
                            position, is_complete = update_aircraft_state(parsed)

                            # Only write complete records (with position + velocity)
                            # to avoid incomplete data in both history and current CSVs
                            if position and is_complete:
                                timestamp_utc = datetime.now(timezone.utc).isoformat()
                                position_with_ts = {**position, "timestamp_utc": timestamp_utc}

                                # Write to historical CSV
                                write_position(csv_path, position, timestamp_utc)

                                # Update current positions
                                icao = position["icao"]
                                current_positions[icao] = position_with_ts

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
                                    print(f"Logged {record_count} positions ({aircraft_count} aircraft)...", end="\r")
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
