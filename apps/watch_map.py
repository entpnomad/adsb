#!/usr/bin/env python3
"""
Watch and auto-update map from ADS-B CSV files.

Continuously regenerates the map HTML file as new positions are captured.

Usage:
    python -m apps.watch_map              # Watch current positions
    python -m apps.watch_map --historical # Watch historical positions
    python -m apps.watch_map --interval 5 # Update every 5 seconds
"""

import argparse
import os
import time

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401

from adsb.config import (
    get_history_csv_path, get_current_csv_path,
    DEFAULT_MAP_HTML, DEFAULT_CURRENT_MAP_HTML,
)
from apps.plot_map import read_csv_positions, create_map


def watch_and_update(csv_path: str, output_path: str = None,
                     interval: int = 1, historical: bool = False):
    """Watch CSV file and regenerate map periodically."""
    if output_path is None:
        output_path = str(DEFAULT_MAP_HTML)

    print(f"Watching {csv_path}")
    print(f"Updating {output_path} every {interval} second{'s' if interval != 1 else ''}...")
    print("Press Ctrl+C to stop.")
    print()

    # Determine historical CSV path for merging trajectories
    historical_csv_path = None
    if not historical:
        historical_csv_path = str(get_history_csv_path())

    try:
        while True:
            positions = []
            if os.path.exists(csv_path):
                positions = read_csv_positions(csv_path)

            # Merge historical data for trajectories
            if positions and historical_csv_path and os.path.exists(historical_csv_path) and not historical:
                historical_positions = read_csv_positions(historical_csv_path)

                if historical_positions:
                    current_icaos = set(p["icao"] for p in positions)

                    for hist_pos in historical_positions:
                        if hist_pos["icao"] in current_icaos:
                            is_duplicate = any(
                                p["icao"] == hist_pos["icao"] and
                                abs(p["lat"] - hist_pos["lat"]) < 0.0001 and
                                abs(p["lon"] - hist_pos["lon"]) < 0.0001
                                for p in positions
                            )
                            if not is_duplicate:
                                positions.append(hist_pos)
                        else:
                            positions.append(hist_pos)

            if positions:
                title = "ADS-B Current Positions with Trajectories" if not historical else "ADS-B Historical Positions"

                # Determine current ICAOs for marker display
                current_icaos_for_map = set()
                if not historical:
                    current_csv_path = get_current_csv_path()
                    if current_csv_path.exists():
                        current_only = read_csv_positions(str(current_csv_path))
                        current_icaos_for_map = set(p["icao"] for p in current_only)

                create_map(positions, output_path, title, refresh_interval=0, current_icaos=current_icaos_for_map)
                print(f"Map updated: {len(positions)} positions, {len(set(p['icao'] for p in positions))} aircraft")
            else:
                print("No positions found, skipping update...")

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\nStopped.")


def main():
    parser = argparse.ArgumentParser(
        description="Watch ADS-B CSV and auto-update map",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m apps.watch_map               # Watch current positions (default)
  python -m apps.watch_map --historical  # Watch historical positions
  python -m apps.watch_map --interval 5  # Update every 5 seconds
        """
    )

    parser.add_argument("--csv", default=None, help="Path to CSV file")
    parser.add_argument("--historical", action="store_true", help="Watch historical CSV file")
    parser.add_argument("--output", default=None, help="Output HTML file path")
    parser.add_argument("--interval", type=int, default=1, help="Update interval in seconds (default: 1)")

    args = parser.parse_args()

    # Determine CSV file
    if args.csv:
        csv_path = args.csv
    elif args.historical:
        csv_path = str(get_history_csv_path())
    else:
        csv_path = str(get_current_csv_path())

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        output_path = str(DEFAULT_MAP_HTML)

    watch_and_update(csv_path, output_path, args.interval, args.historical)


if __name__ == "__main__":
    main()
