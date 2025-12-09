# ADS-B Aircraft Tracker

A portable Python toolchain for collecting, visualizing, and tracking ADS-B aircraft position data. Features interactive maps with real-time updates, aircraft type detection, altitude-based color gradients, and 3D distance calculations.

## Features

- **Real-time ADS-B data collection** from dump1090
- **Interactive map visualization** with Folium/Leaflet
- **Aircraft type detection** using a 500k+ aircraft database (ICAO hex lookup)
- **91 custom SVG aircraft silhouettes** from tar1090 (A380, B737, F-35, helicopters, gliders, etc.)
- **370+ type designator mappings** for accurate icon selection
- **Altitude-based trajectory coloring** - flight paths show rainbow gradients as aircraft climb/descend
- **Heading-aware icons** that rotate to show flight direction
- **Dark glassmorphism UI** - semi-transparent popups and status box with blur effects
- **Home location configuration** with address geocoding and elevation lookup
- **3D distance calculation** accounting for altitude differences
- **Auto-updating maps** that refresh without page reload (1-second intervals)

## Quick Start

```bash
./adsb.sh
```

Or cross-platform without the bash wrapper:

```bash
python adsb_cli.py csv
```

This single command:
1. Starts dump1090 (if not running)
2. Begins collecting ADS-B data to CSV
3. Starts an HTTP server on port 8000
4. Starts the map auto-updater
5. Opens your browser to the live map

Press `Ctrl+C` to stop all components.

### Set Your Home Location

```bash
python3 plot_map.py --home-address "Your Address, City, Country"
```

Example:
```bash
python3 plot_map.py --home-address "10 Downing Street, London, UK"
```

This geocodes your address, looks up the elevation, and saves it for distance calculations.

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

### One-Command Start

```bash
./adsb.sh
```

Opens the live map at `http://127.0.0.1:8000/adsb_current_map.html`

### Manual Map Generation

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

### Python CLI (multiplatform, beta)

Use the Python entry point instead of the bash script:

```bash
# CSV logger (honors ADSB_* env vars)
python adsb_cli.py csv --host 127.0.0.1 --port 30003

# Generate a map once
python adsb_cli.py plot --csv output/adsb_current.csv --output output/adsb_current_map.html

# Watch CSV and refresh map
python adsb_cli.py watch --csv output/adsb_current.csv --output output/adsb_current_map.html --interval 2
```

### PostgreSQL (ingest y datos de demo)

Configura `ADSB_DB_URL` (p. ej. `postgresql://user:pass@host:5432/adsb`) y usa el CLI:

```bash
# Docker-compose por modo (sin tocar entorno):
# 1) Simulación de datos (default)
docker compose up -d adsb_app postgres
# 2) Ingerir un CSV histórico
docker compose up -d adsb_app_from_csv postgres
# 3) Stream en vivo desde dump1090
docker compose up -d adsb_app_stream postgres

# 4) Demo con mapa servido en http://localhost:8000/adsb_current_map.html
docker compose up -d adsb_map_demo  # incluye portal en /index.html

# Sin Docker, comandos equivalentes:
ADSB_DB_URL=... python adsb_cli.py db --from-csv output/adsb_history.csv   # volcar CSV
ADSB_DB_URL=... python adsb_cli.py db --simulate 300                       # datos sintéticos
ADSB_DB_URL=... python adsb_cli.py db --stream                             # en vivo desde dump1090
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

## Project Structure

```
adsb/
├── adsb.sh              # Main entry script (starts everything)
├── adsb_to_csv.py       # ADS-B to CSV logger
├── plot_map.py          # Map visualization with all features
├── aircraft_db.py       # Aircraft database lookup (370+ type mappings)
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
│   └── icons/           # 91 aircraft SVG silhouettes from tar1090
│       ├── a380.svg, a320.svg, b737.svg   # Commercial airliners
│       ├── f35.svg, f18.svg, typhoon.svg  # Military jets
│       ├── helicopter.svg, blackhawk.svg  # Rotorcraft
│       ├── glider.svg, cessna.svg         # Light aircraft
│       ├── c130.svg, c17.svg              # Military transport
│       └── ... (91 total icons)
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

91 unique SVG silhouettes from tar1090, automatically selected based on aircraft type:

| Category | Examples |
|----------|----------|
| **Commercial** | A320, A380, B737, B747, B777, E190 |
| **Military Jets** | F-35, F-18, Typhoon, Rafale, F-15 |
| **Military Transport** | C-130, C-17, A400M |
| **Helicopters** | Blackhawk, Apache, Chinook, S-61 |
| **Light Aircraft** | Cessna, Cirrus SR22, twin props |
| **Gliders** | Sailplanes |
| **Special** | Balloons, blimps, UAVs, V-22 Osprey |

### Altitude-Colored Trajectories

Flight paths are drawn with each segment colored by altitude, creating a gradient effect as aircraft climb or descend:

- **Orange**: 0 ft (ground level)
- **Yellow**: 4,000 ft
- **Green**: 8,000 ft
- **Cyan**: 20,000 ft
- **Blue**: 30,000 ft
- **Purple**: 40,000+ ft

Colors interpolate smoothly between these stops.

### Altitude Color Scale (Aircraft Icons)

Aircraft icons use the same altitude color scale:
- **Orange**: Ground level / low altitude
- **Yellow**: ~4,000 ft
- **Green**: ~8,000 ft
- **Cyan/Turquoise**: ~20,000 ft
- **Blue**: ~30,000 ft
- **Purple**: 40,000 ft+ (cruise altitude)

### Aircraft Information Popup

Click any aircraft to see (organized in sections):

**Static Data:**
- ICAO hex code
- Flight number
- Registration number
- Aircraft type and model

**Live Data:**
- Time since last seen
- 3D distance from home
- Altitude
- Speed
- Heading
- Squawk code

**Tracking Links:**
- ADSBexchange
- FlightRadar24
- FlightAware

### Distance Calculation

The popup shows true 3D distance from your home position, calculated using:
- Haversine formula for horizontal distance
- Pythagorean theorem for altitude difference
- Accounts for your home elevation vs aircraft altitude

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DUMP1090_CMD` | `dump1090` | dump1090 command path |
| `ADSB_HOST` | `127.0.0.1` | dump1090 host |
| `ADSB_PORT` | `30003` | dump1090 SBS-1 port |
| `ADSB_HTTP_PORT` | `8000` | HTTP server port |
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

### Port 8000 already in use
- Set a different port: `ADSB_HTTP_PORT=8080 ./adsb.sh`
- Or kill the existing process: `lsof -ti:8000 | xargs kill`

## Testing

```bash
pytest
```

## APIs Used

- **OpenStreetMap Nominatim**: Address geocoding (free, no API key)
- **Open-Elevation**: Elevation lookup (free, no API key)
- **tar1090-db**: Aircraft database from wiedehopf

## Credits

- Aircraft silhouettes from [tar1090](https://github.com/wiedehopf/tar1090) by wiedehopf
- Aircraft database from [tar1090-db](https://github.com/wiedehopf/tar1090-db)

## License

MIT License - See LICENSE file for details.
