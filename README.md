# ADS-B Aircraft Tracker

A portable Python toolchain for collecting, visualizing, and tracking ADS-B aircraft position data. Features interactive maps with real-time updates, aircraft type detection, altitude-based color gradients, and 3D distance calculations.

## Features

- **Real-time ADS-B data collection** from dump1090
- **Interactive map visualization** with Folium/Leaflet
- **Aircraft type detection** using a 500k+ aircraft database (ICAO hex lookup)
- **Custom SVG icons** for different aircraft types (airliner, helicopter, light aircraft, glider)
- **Altitude-based color gradients** (orange → yellow → green → cyan → blue → purple)
- **Heading-aware icons** that rotate to show flight direction
- **Home location configuration** with address geocoding and elevation lookup
- **3D distance calculation** accounting for altitude differences
- **Auto-updating maps** that refresh without page reload

## Quick Start

### 1. Start Data Collection

```bash
./adsb.sh
```

This starts dump1090 (if not running) and begins collecting ADS-B data to CSV files.

### 2. Set Your Home Location

```bash
python3 plot_map.py --home-address "Your Address, City, Country"
```

Example:
```bash
python3 plot_map.py --home-address "10 Downing Street, London, UK"
```

This geocodes your address, looks up the elevation, and saves it for distance calculations.

### 3. View the Map

Open `output/adsb_map.html` in your browser. The map shows:
- Aircraft positions with type-specific icons
- Color-coded by altitude
- Trajectory lines showing flight paths
- Click any aircraft to see details including distance from home

## Installation

### Prerequisites

- Python 3.9+
- `dump1090` installed and in PATH
- RTL-SDR dongle with antenna

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Download Aircraft Database (Optional but Recommended)

The aircraft database enables type detection and registration lookup:

```bash
mkdir -p data
curl -o data/aircraft_db.csv https://raw.githubusercontent.com/wiedehopf/tar1090-db/csv/aircraft_db.csv
```

## Usage

### Data Collection

```bash
# Start ADS-B capture (runs dump1090 + CSV logger)
./adsb.sh

# Or with live map updates
./adsb.sh live
```

### Map Generation

```bash
# Generate map with current + historical trajectories
python3 plot_map.py

# Current positions only (no historical data)
python3 plot_map.py --csv output/adsb_current.csv

# Historical positions only
python3 plot_map.py --historical

# Track specific aircraft by ICAO
python3 plot_map.py --icao 3C5EF2

# Custom output file
python3 plot_map.py --output my_map.html
```

### Home Location Setup

```bash
# Set home by address (geocodes automatically)
python3 plot_map.py --home-address "Piazza del Duomo, Milan, Italy"

# Or use environment variables
export ADSB_HOME_LAT=51.5007
export ADSB_HOME_LON=-0.1246
export ADSB_HOME_ELEVATION_M=5
```

### Real-Time Map Updates

**Terminal 1:** Start data capture
```bash
./adsb.sh
```

**Terminal 2:** Auto-update maps
```bash
# Update current map every second
while true; do python3 plot_map.py --csv output/adsb_current.csv --output output/adsb_current_map.html; sleep 1; done

# Update main map every 2 seconds
while true; do python3 plot_map.py --output output/adsb_map.html; sleep 2; done
```

**Browser:** Open the HTML files - they auto-update via JavaScript polling.

## Project Structure

```
adsb/
├── adsb.sh              # Main entry script (starts dump1090 + logger)
├── adsb_to_csv.py       # ADS-B to CSV logger
├── plot_map.py          # Map visualization with all features
├── aircraft_db.py       # Aircraft database lookup
├── serve_map.py         # HTTP server for maps
├── watch_map.py         # Auto-update map watcher
├── README.md
├── SPEC.md
├── requirements.txt
├── .gitignore
│
├── src/                 # Shared library code
│   ├── __init__.py
│   └── lib/
│       ├── __init__.py
│       ├── config.py    # Centralized paths and settings
│       ├── geo.py       # Geocoding, elevation, distance
│       └── colors.py    # Altitude color mapping
│
├── assets/              # Static assets
│   └── icons/           # Aircraft SVG icons
│       ├── plane.svg
│       ├── helicopter.svg
│       ├── light.svg
│       └── glider.svg
│
├── output/              # Generated files (gitignored)
│   ├── adsb_history.csv
│   ├── adsb_current.csv
│   ├── adsb_map.html
│   ├── adsb_current_map.html
│   └── *_data.json
│
├── config/              # User configuration (gitignored)
│   └── home_location.json
│
└── data/                # Downloaded data (gitignored)
    └── aircraft_db.csv
```

## Map Features

### Aircraft Icons

Different SVG icons based on aircraft type (from tar1090):
- **Airliner** (plane.svg): Commercial jets, large aircraft
- **Helicopter** (helicopter.svg): Rotorcraft
- **Light Aircraft** (light.svg): Cessnas, small props
- **Glider** (glider.svg): Sailplanes

### Altitude Color Scale

Aircraft are color-coded by altitude with smooth gradients:
- **Orange**: 0 ft (ground level)
- **Yellow**: 4,000 ft
- **Green**: 8,000 ft
- **Cyan**: 20,000 ft
- **Blue**: 30,000 ft
- **Purple**: 40,000 ft+

### Distance Calculation

The popup shows true 3D distance from your home position, calculated using:
- Haversine formula for horizontal distance
- Pythagorean theorem for altitude difference
- Accounts for your home elevation vs aircraft altitude

### Aircraft Information

Click any aircraft to see:
- ICAO hex code
- Registration number (if in database)
- Aircraft type and model
- Flight number
- Altitude, speed, heading
- Squawk code
- Time since last seen
- 3D distance from home

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DUMP1090_CMD` | `dump1090` | dump1090 command path |
| `ADSB_HOST` | `127.0.0.1` | dump1090 host |
| `ADSB_PORT` | `30003` | dump1090 SBS-1 port |
| `ADSB_CSV_PATH` | `output/adsb_history.csv` | Historical positions file |
| `ADSB_CURRENT_CSV_PATH` | `output/adsb_current.csv` | Current positions file |
| `ADSB_CURRENT_MAX_AGE_SECONDS` | `60` | Max age for "current" aircraft |
| `ADSB_HOME_LAT` | - | Home latitude (optional) |
| `ADSB_HOME_LON` | - | Home longitude (optional) |
| `ADSB_HOME_ELEVATION_M` | - | Home elevation in meters (optional) |

### Home Location File

The `config/home_location.json` file (created by `--home-address`) stores:
```json
{
  "address": "Your input address",
  "display_name": "Geocoded full address",
  "lat": 51.5007,
  "lon": -0.1246,
  "elevation_m": 5.0,
  "elevation_ft": 16.4
}
```

## Troubleshooting

### No aircraft showing on map
- Verify dump1090 is receiving signals (check its web interface)
- Ensure you have ADS-B traffic in your area
- Check that CSV files are being written: `tail -f output/adsb_history.csv`

### Aircraft icons not showing
- Ensure the `assets/icons/` directory exists with SVG files
- Check browser console for JavaScript errors

### Home location not working
- Run `python3 plot_map.py --home-address "Your Address"` to set it
- Check that `config/home_location.json` was created
- Verify internet connection for geocoding API

### dump1090 not found
- Install dump1090 or set `DUMP1090_CMD` to full path
- On macOS: `brew install dump1090`

## APIs Used

- **OpenStreetMap Nominatim**: Address geocoding (free, no API key)
- **Open-Elevation**: Elevation lookup (free, no API key)
- **tar1090-db**: Aircraft database from wiedehopf

## License

MIT License - See LICENSE file for details.
