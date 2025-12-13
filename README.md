# ADS-B Aircraft Tracker

Lightweight Python toolchain to capture ADS-B, log to CSV or Postgres, build maps, and send readings from remote antennas. Remote senders now publish JSON `AdsbPositionEvent` messages to a NATS subject (`adsb.position.v1`) by default; the legacy HTTP ingest remains available for local/testing.

## Run modes
### 1) Full local (capture + map)
- Needs Python 3.9+ and optional `dump1090 --net` on port `30003` (the script tries to start it if available).
```bash
./adsb.sh
```
- Captures to `output/adsb_history.csv` and `output/adsb_current.csv`, refreshes the map, serves it at `http://127.0.0.1:8000/adsb_current_map.html`.
- Cross-platform CLI (no bash):
```bash
python -m apps.adsb_cli csv
```
- Set home location once for 3D distances:
```bash
python -m apps.plot_map --home-address "Your City, Country"
```

### 2) Antenna on Raspberry Pi (sender only)
- Needs Raspberry Pi OS, RTL-SDR + 1090 MHz antenna, `dump1090 --net`, Python 3.9+.
```bash
sudo apt update && sudo apt install -y git python3-venv python3-pip dump1090-fa
git clone <repo-url> adsb && cd adsb
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.antenna.example .env.antenna  # set ADSB_SOURCE_ID/ADSB_NATS_URL/ADSB_NATS_SUBJECT, check ADSB_HOST/ADSB_PORT
```
- Publish positions to NATS (recommended, host networking works on Pi):
```bash
ADSB_SOURCE_ID=LISTENING_POST_LUGANO_01 \
ADSB_NATS_URL=nats://nats:4222 \
ADSB_NATS_SUBJECT=adsb.position.v1 \
docker compose --env-file .env.antenna -f deploy/compose.antenna.yml up -d adsb_sender
```
- Legacy HTTP ingest: set `ADSB_OUTPUT_MODE=http` and `ADSB_INGEST_URL=http://server:8000/api/ingest` if you still need to POST batches.

### 3) Antenna on PC with Docker Desktop
- Needs Docker Desktop and a host-accessible `dump1090` feed (usually port `30003`).
```bash
cp .env.antenna.example .env.antenna  # set ADSB_SOURCE_ID/ADSB_NATS_URL/ADSB_NATS_SUBJECT
# ADSB_HOST defaults to host.docker.internal in the compose file
docker compose --env-file .env.antenna -f deploy/compose.antenna.desktop.yml up -d adsb_sender
```
- Logs:
```bash
docker compose -f deploy/compose.antenna.desktop.yml logs -f adsb_sender
```
- For legacy HTTP ingest from Docker Desktop: set `ADSB_OUTPUT_MODE=http` and `ADSB_INGEST_URL` in `.env.antenna`.

### 4) Ingest server + portal (Postgres + FastAPI)
- Start database and API:
```bash
docker compose -f deploy/compose.api.yml up -d postgres adsb_view_db
```
- Portal and API: `http://localhost:8000` (`/map`, `/docs`, `/api/health`).
- Ingest from a live `dump1090` feed on your host:
```bash
ADSB_DB_URL=postgresql://adsb:adsb@localhost:5432/adsb \
python -m apps.adsb_cli db --stream --batch-size 200
```
- Generate demo data (no antenna):
```bash
ADSB_DB_URL=postgresql://adsb:adsb@localhost:5432/adsb \
python -m apps.adsb_cli db --simulate 200
```
- Export CSVs from the database for maps:
```bash
ADSB_DB_URL=postgresql://adsb:adsb@localhost:5432/adsb \
python -m apps.db_export --hours 6
```

## Env vars and paths
- `.env.antenna` for `ADSB_SOURCE_ID`, `ADSB_NATS_URL`, `ADSB_NATS_SUBJECT`, `ADSB_HOST`, `ADSB_PORT` (set `ADSB_OUTPUT_MODE=http` and `ADSB_INGEST_URL` only if you need legacy POST ingest).
- `ADSB_DB_URL` for Postgres operations.
- `ADSB_HOME_LAT`, `ADSB_HOME_LON`, `ADSB_HOME_ELEVATION_M` stored under `config/home_location.json` after set.
- Outputs and maps live in `output/`.

The HTTP API and legacy ingest remain for local flows, but external integrations should consume `adsb.position.v1` events directly from `ADSB_NATS_URL`.

## Repo map (short)
- `apps/`: entry points (`adsb_cli`, `adsb_to_db`, `adsb_sender`, `plot_map`, `portal`, etc.).
- `deploy/`: compose files for API and antenna senders.
- `assets/`, `api_static/`: icons and map UI assets.

## Testing
```bash
pytest
```

## Docs
- `docs/raspberry-pi.md`: Pi sender details.
- `docs/desktop-antenna.md`: Desktop sender details.
- `docs/api-server.md`: API stack notes.

## Credits
- Aircraft silhouettes from tar1090 by wiedehopf.
- Aircraft database from tar1090-db.

## License
MIT License - see `LICENSE`.
