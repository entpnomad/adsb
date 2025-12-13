"""
Centralized configuration and paths for ADS-B tracker.

All file paths and constants should be defined here for consistency.
"""

import os
from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Directory paths
OUTPUT_DIR = PROJECT_ROOT / "output"
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
ASSETS_DIR = PROJECT_ROOT / "assets"
ICONS_DIR = ASSETS_DIR / "icons"

# Ensure directories exist
OUTPUT_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

# Default file paths
DEFAULT_HISTORY_CSV = OUTPUT_DIR / "adsb_history.csv"
DEFAULT_CURRENT_CSV = OUTPUT_DIR / "adsb_current.csv"
DEFAULT_MAP_HTML = OUTPUT_DIR / "adsb_map.html"
DEFAULT_CURRENT_MAP_HTML = OUTPUT_DIR / "adsb_current_map.html"
HOME_CONFIG_FILE = CONFIG_DIR / "home_location.json"
AIRCRAFT_DB_FILE = DATA_DIR / "aircraft_db.csv"
DEFAULT_DB_URL = None  # Explicitly require env for DB

# Environment variable overrides
def get_history_csv_path() -> Path:
    """Get historical CSV path from env or default."""
    return Path(os.getenv("ADSB_CSV_PATH", str(DEFAULT_HISTORY_CSV)))

def get_current_csv_path() -> Path:
    """Get current CSV path from env or default."""
    return Path(os.getenv("ADSB_CURRENT_CSV_PATH", str(DEFAULT_CURRENT_CSV)))

# Network defaults
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 30003

def get_dump1090_host() -> str:
    """Get dump1090 host from env or default."""
    return os.getenv("ADSB_HOST", DEFAULT_HOST)

def get_dump1090_port() -> int:
    """Get dump1090 port from env or default."""
    return int(os.getenv("ADSB_PORT", str(DEFAULT_PORT)))

def get_db_url() -> str:
    """Get database URL from env or raise if missing."""
    db_url = os.getenv("ADSB_DB_URL", DEFAULT_DB_URL)
    if not db_url:
        raise RuntimeError("ADSB_DB_URL is not set")
    return db_url

# Timing defaults
RECONNECT_DELAY = 5  # seconds
FLUSH_INTERVAL = 10  # flush CSV every N records
CURRENT_UPDATE_INTERVAL = 5  # update current CSV every N new positions
CURRENT_MAX_AGE_SECONDS = 60  # only show aircraft seen in last N seconds

def get_current_max_age() -> int:
    """Get max age for current aircraft from env or default."""
    return int(os.getenv("ADSB_CURRENT_MAX_AGE_SECONDS", str(CURRENT_MAX_AGE_SECONDS)))

# CSV header columns (shared between collector and reader)
CSV_COLUMNS = [
    "timestamp_utc",
    "icao",
    "flight",
    "lat",
    "lon",
    "altitude_ft",
    "speed_kts",
    "heading_deg",
    "squawk",
]
