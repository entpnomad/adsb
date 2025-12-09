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

## Architecture

- **Capture pipeline**: `dump1090` emits SBS-1 messages on TCP 30003, which `adsb_cli.py csv`/`adsb_to_csv.py` consumes to produce `output/adsb_current.csv` (rolling window) and `output/adsb_history.csv` (append-only).
- **File-based maps**: `plot_map.py` renders HTML from CSV files, `watch_map.py` keeps the map fresh, `serve_map.py` hosts the output, and `portal.py` builds `output/index.html` with links to maps and CSVs.
- **Database + API path**: `adsb_cli.py db`/`adsb_to_db.py` ingest streams, CSV snapshots, or simulated tracks into Postgres. `api_main.py` exposes `/api/aircraft/*` and serves the Leaflet UI at `/map`, using `api_static/` assets.
- **Simulation and demos**: `simulate_stream.py` fakes a dump1090 feed for local demos; Docker Compose stacks spin up Postgres plus ingestion, plotting, or the API using the same code paths.
- **Remote sender**: `Dockerfile.sender` builds an `adsb_sender` image that reads a friend's dump1090 feed and POSTs to the API ingest endpoint (`/api/ingest`), keeping the database closed from remote collectors.

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

### Docker Compose (server: API + Postgres)

Bring up the server stack (Postgres + FastAPI viewer/map):

```bash
docker compose up -d postgres adsb_view_db
```

- API and map UI: `http://localhost:8000` (see `/map`, `/docs`, `/api/health`).
- Database: `postgresql://adsb:adsb@localhost:5432/adsb`.
- Ingest endpoint for remote senders: `POST /api/ingest` with `{"positions": [...]}`.

Feed data into Postgres with your preferred pipeline. Examples from the host:

```bash
# Live from dump1090 (SBS-1 on 30003)
ADSB_DB_URL=postgresql://adsb:adsb@localhost:5432/adsb python adsb_cli.py db --stream

# Ingest an existing CSV snapshot
ADSB_DB_URL=postgresql://adsb:adsb@localhost:5432/adsb python adsb_cli.py db --from-csv output/adsb_history.csv
```

### Docker Compose (antenna sender)

Use a dedicated compose per environment to forward local dump1090 data to the central API ingest endpoint:

```bash
# Linux (host networking)
docker compose --env-file .env.antenna -f docker-compose.antenna.yml up -d adsb_sender

# Docker Desktop (mac/Windows, no host networking)
docker compose --env-file .env.antenna -f docker-compose.antenna.desktop.yml up -d adsb_sender
```

Fill in `.env.antenna` (copy from `.env.antenna.example`) with at least:
```
ADSB_INGEST_URL=http://SERVER_IP:8000/api/ingest
ADSB_HOST=127.0.0.1            # use host.docker.internal on Desktop
ADSB_PORT=30003
ADSB_BATCH_SIZE=100
```
The Desktop compose already maps `host.docker.internal` for you via `extra_hosts`.

### Simulated antenna (sends to ingest)

To simulate an antenna sending live data to the ingest API:

```bash
# With Docker (uses .env.sim for defaults)
cp .env.sim.example .env.sim   # edit as needed
docker compose --env-file .env.sim -f docker-compose.sim-sender.yml up -d adsb_sim_sender

# Or run locally
ADSB_INGEST_URL=http://localhost:8000/api/ingest \
python simulate_sender.py --center-lat 40.4168 --center-lon -3.7038 --aircraft 5 --points-per-ac 10 --interval 5
```

Tune via env/flags: `ADSB_INGEST_URL`, `ADSB_SIM_CENTER_LAT`, `ADSB_SIM_CENTER_LON`, `ADSB_SIM_AIRCRAFT`, `ADSB_SIM_POINTS`, `ADSB_SIM_INTERVAL`.

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

- `adsb.sh` - main entry script that chains capture -> CSV -> map/server.
- `adsb_cli.py` - Python CLI with `csv`, `plot`, `watch`, and `db` subcommands.
- `adsb_to_csv.py` - SBS-1 stream to CSV logger (current + historical).
- `adsb_to_db.py` - stream/CSV/simulated ingest into Postgres.
- `plot_map.py` / `watch_map.py` - render HTML maps from CSV and refresh on change.
- `serve_map.py` / `portal.py` - lightweight HTTP server plus index page for outputs.
- `api_main.py` - FastAPI service backed by Postgres with a Leaflet UI at `/map`.
- `api_static/` - static HTML/CSS/JS used by the API-hosted UI.
- `assets/icons/` - 91 SVG silhouettes used for aircraft icons.
- `output/` - generated CSVs/maps (gitignored).
- `config/` - user configuration such as `home_location.json` (gitignored).
- `data/` - downloaded datasets like `aircraft_db.csv` (gitignored).
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
