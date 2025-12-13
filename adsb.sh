#!/bin/bash
#
# ADS-B Aircraft Tracker - One Script to Rule Them All
#
# Usage:
#   ./adsb.sh   # Start everything and open browser
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { printf "${GREEN}[+]${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}[!]${NC} %s\n" "$1"; }
err() { printf "${RED}[x]${NC} %s\n" "$1"; }

# Configuration
DUMP1090_CMD="${DUMP1090_CMD:-dump1090}"
HTTP_PORT="${ADSB_HTTP_PORT:-8000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/output"

mkdir -p "$OUTPUT_DIR"

# ============================================
# CLEANUP - Kill all existing processes first
# ============================================
cleanup_existing() {
    warn "Killing any existing processes..."
    pkill -f dump1090 2>/dev/null || true
    pkill -f "python3.*adsb_to_csv" 2>/dev/null || true
    pkill -f "python3.*plot_map" 2>/dev/null || true
    pkill -f "python3.*serve_map" 2>/dev/null || true
    lsof -ti:"$HTTP_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 2
}

# Cleanup on exit
cleanup() {
    printf "\n"
    warn "Shutting down..."
    pkill -f dump1090 2>/dev/null || true
    pkill -f "python3.*adsb_to_csv" 2>/dev/null || true
    pkill -f "python3.*plot_map" 2>/dev/null || true
    pkill -f "python3.*serve_map" 2>/dev/null || true
    log "Stopped."
}

trap cleanup EXIT INT TERM

# ============================================
# MAIN
# ============================================

printf "\n"
printf "============================================\n"
printf "       ADS-B Aircraft Tracker\n"
printf "============================================\n"
printf "\n"

# Check requirements
if ! command -v "$DUMP1090_CMD" &> /dev/null; then
    err "dump1090 not found. Install it or set DUMP1090_CMD"
    exit 1
fi

if ! python3 -c "import folium" 2>/dev/null; then
    err "folium not installed. Run: pip install folium"
    exit 1
fi

# Kill everything first
cleanup_existing

# Start dump1090
log "Starting dump1090..."
"$DUMP1090_CMD" --net --interactive > /dev/null 2>&1 &
sleep 3

# Verify dump1090 started
if ! lsof -Pi :30003 -sTCP:LISTEN -t >/dev/null 2>&1; then
    err "dump1090 failed to start"
    exit 1
fi
log "dump1090 ready on port 30003"

# Start CSV logger
log "Starting data collector..."
cd "$SCRIPT_DIR"
python3 -m apps.adsb_to_csv > /dev/null 2>&1 &
sleep 2

# Start HTTP server
log "Starting HTTP server on port $HTTP_PORT..."
python3 -m apps.serve_map --port "$HTTP_PORT" > /dev/null 2>&1 &
sleep 2

# Verify HTTP server started
if ! lsof -Pi :"$HTTP_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
    err "HTTP server failed to start"
    exit 1
fi

# Start map updater
log "Starting map updater..."
(
    while true; do
        python3 -m apps.plot_map --csv output/adsb_current.csv --output output/adsb_current_map.html 2>/dev/null
        sleep 1
    done
) &
sleep 3

# Open browser
log "Opening browser..."
open "http://127.0.0.1:$HTTP_PORT/adsb_current_map.html"

printf "\n"
printf "============================================\n"
printf "${GREEN}All systems running!${NC}\n"
printf "============================================\n"
printf "\n"
printf "  Map URL:    http://127.0.0.1:$HTTP_PORT/adsb_current_map.html\n"
printf "  Output:     $OUTPUT_DIR\n"
printf "\n"
printf "${YELLOW}Press Ctrl+C to stop${NC}\n"
printf "\n"

# Keep running
while true; do sleep 60; done
