#!/usr/bin/env python3
"""
HTTP Server for ADS-B Map

Serves the map HTML and JSON data files via HTTP to avoid CORS issues.
This allows the map to fetch updates dynamically without page reload.

Usage:
    python3 serve_map.py [--port 8000] [--host 127.0.0.1]
"""

import argparse
import http.server
import socketserver
import sys

from src.lib.config import OUTPUT_DIR


class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler with CORS headers."""

    def __init__(self, *args, **kwargs):
        # Serve files from the output directory
        super().__init__(*args, directory=str(OUTPUT_DIR), **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging for cleaner output
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Serve ADS-B map files via HTTP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 serve_map.py               # Serve on default port 8000
  python3 serve_map.py --port 8080   # Serve on custom port
  python3 serve_map.py --host 0.0.0.0  # Serve on all interfaces
        """
    )

    parser.add_argument("--port", type=int, default=8000, help="Port to serve on (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")

    args = parser.parse_args()

    try:
        with socketserver.TCPServer((args.host, args.port), CORSRequestHandler) as httpd:
            print(f"Serving ADS-B map files from: {OUTPUT_DIR}")
            print(f"Server running at http://{args.host}:{args.port}")
            print(f"Open http://{args.host}:{args.port}/adsb_map.html in your browser")
            print("Press Ctrl+C to stop")
            httpd.serve_forever()
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"Error: Port {args.port} is already in use.", file=sys.stderr)
            print(f"Try a different port: python3 serve_map.py --port {args.port + 1}", file=sys.stderr)
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nServer stopped.")


if __name__ == "__main__":
    main()
