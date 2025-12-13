#!/usr/bin/env python3
"""
Cross-platform ADS-B helper CLI.

Replaces the bash-only wrapper with a simple Python entry point that works on
Windows, macOS, Linux, and Raspberry Pi. For now it exposes the CSV collector
and leaves placeholders for future DB/API modes.
"""

import argparse
import os
import sys
from typing import Optional

# Ensure project root is on sys.path
try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401


def _set_if(value: Optional[str], env_var: str) -> None:
    if value is not None:
        os.environ[env_var] = str(value)


def cmd_csv(args: argparse.Namespace) -> None:
    """Run the CSV collector with optional overrides."""
    _set_if(args.host, "ADSB_HOST")
    _set_if(args.port, "ADSB_PORT")
    _set_if(args.history, "ADSB_CSV_PATH")
    _set_if(args.current, "ADSB_CURRENT_CSV_PATH")
    _set_if(args.max_age, "ADSB_CURRENT_MAX_AGE_SECONDS")

    # Lazy import so env vars are set first
    from apps import adsb_to_csv

    adsb_to_csv.main()


def cmd_plot(args: argparse.Namespace) -> None:
    """Convenience passthrough to plot_map.py."""
    plot_args = []
    if args.historical:
        plot_args.append("--historical")
    if args.icao:
        plot_args += ["--icao", args.icao]
    if args.output:
        plot_args += ["--output", args.output]
    if args.csv:
        plot_args += ["--csv", args.csv]
    if args.home_address:
        plot_args += ["--home-address", args.home_address]

    from apps import plot_map  # noqa: WPS433

    # Patch sys.argv to reuse plot_map's argparse setup
    sys.argv = ["plot_map.py"] + plot_args
    plot_map.main()


def cmd_watch(args: argparse.Namespace) -> None:
    """Passthrough to watch_map.py for auto-refresh maps."""
    watch_args = []
    if args.historical:
        watch_args.append("--historical")
    if args.csv:
        watch_args += ["--csv", args.csv]
    if args.output:
        watch_args += ["--output", args.output]
    if args.interval:
        watch_args += ["--interval", str(args.interval)]

    from apps import watch_map  # noqa: WPS433

    sys.argv = ["watch_map.py"] + watch_args
    watch_map.main()


def cmd_api(_args: argparse.Namespace) -> None:
    print("HTTP API not implemented yet. Coming soon.", file=sys.stderr)
    sys.exit(1)


def cmd_db(args: argparse.Namespace) -> None:
    """Run DB ingestor (stream, CSV, or simulated)."""
    db_args = []
    if args.db_url:
        db_args += ["--db-url", args.db_url]
    if args.batch_size:
        db_args += ["--batch-size", str(args.batch_size)]
    if args.stream:
        db_args.append("--stream")
    if args.from_csv:
        db_args += ["--from-csv", args.from_csv]
    if args.simulate is not None:
        db_args += ["--simulate", str(args.simulate)]

    from apps import adsb_to_db  # noqa: WPS433

    sys.argv = ["adsb_to_db.py"] + db_args
    adsb_to_db.main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ADS-B helper CLI (CSV, plot, watch)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    csv_p = sub.add_parser("csv", help="Run CSV collector")
    csv_p.add_argument("--host", help="dump1090 host (default: env ADSB_HOST or 127.0.0.1)")
    csv_p.add_argument("--port", help="dump1090 port (default: env ADSB_PORT or 30003)")
    csv_p.add_argument("--history", help="Historical CSV path (env ADSB_CSV_PATH)")
    csv_p.add_argument("--current", help="Current snapshot CSV path (env ADSB_CURRENT_CSV_PATH)")
    csv_p.add_argument("--max-age", dest="max_age", type=int, help="Max age seconds for current snapshot")
    csv_p.set_defaults(func=cmd_csv)

    plot_p = sub.add_parser("plot", help="Generate a map once (plot_map.py)")
    plot_p.add_argument("--historical", action="store_true", help="Use full historical CSV")
    plot_p.add_argument("--icao", help="Filter to a single ICAO")
    plot_p.add_argument("--csv", help="Custom CSV path")
    plot_p.add_argument("--output", help="Output HTML path")
    plot_p.add_argument("--home-address", help="Set home location by address before plotting")
    plot_p.set_defaults(func=cmd_plot)

    watch_p = sub.add_parser("watch", help="Auto-regenerate map as CSV changes")
    watch_p.add_argument("--historical", action="store_true", help="Watch historical CSV")
    watch_p.add_argument("--csv", help="Custom CSV path")
    watch_p.add_argument("--output", help="Output HTML path")
    watch_p.add_argument("--interval", type=int, default=1, help="Refresh interval seconds")
    watch_p.set_defaults(func=cmd_watch)

    db_p = sub.add_parser("db", help="DB collector (stream, CSV, or simulated)")
    db_p.add_argument("--db-url", help="PostgreSQL URL (fallback env ADSB_DB_URL)")
    db_p.add_argument("--batch-size", type=int, default=200, help="Batch insert size")
    db_mode = db_p.add_mutually_exclusive_group(required=True)
    db_mode.add_argument("--stream", action="store_true", help="Stream from dump1090")
    db_mode.add_argument("--from-csv", help="Ingest an existing CSV file")
    db_mode.add_argument("--simulate", type=int, nargs="?", const=200, help="Generate synthetic positions (default 200)")
    db_p.set_defaults(func=cmd_db)

    api_p = sub.add_parser("api", help="(Placeholder) HTTP API server")
    api_p.set_defaults(func=cmd_api)

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
