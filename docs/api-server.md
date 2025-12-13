# API Server (Postgres + FastAPI)

Run the database-backed API stack and feed it with live or simulated ADS-B data.

## Start the stack
```bash
docker compose -f deploy/compose.api.yml up -d postgres adsb_view_db
```
Services:
- Postgres: `postgresql://adsb:adsb@localhost:5432/adsb`
- FastAPI: `http://localhost:8000` (see `/map`, `/docs`, `/api/health`)

## Ingest data into Postgres
From the host (requires dump1090 on 30003):
```bash
ADSB_DB_URL=postgresql://adsb:adsb@localhost:5432/adsb \
python -m apps.adsb_to_db --stream --batch-size 200
```
From an existing CSV snapshot:
```bash
ADSB_DB_URL=postgresql://adsb:adsb@localhost:5432/adsb \
python -m apps.adsb_to_db --from-csv output/adsb_history.csv
```
Generate demo data (no antenna required):
```bash
ADSB_DB_URL=postgresql://adsb:adsb@localhost:5432/adsb \
python -m apps.adsb_to_db --simulate 200
```

## API overview
- `GET /api/aircraft/current?since_seconds=300`
- `GET /api/aircraft/{icao}/history?hours=6`
- `GET /api/aircraft/{icao}/route?start_utc=...&end_utc=...&limit=...` (all stored points)
- `GET /api/aircraft/tracks?since_seconds=1800&max_points_per_aircraft=80&icaos=ABC,DEF`
- `GET /api/health`
- Map UI under `/map` (uses `api_static/` assets)

### View the full route of one aircraft
- Every stored point for a given ICAO:  
  `GET /api/aircraft/{icao}/route`
- Optional filters: `start_utc` and/or `end_utc` (ISO8601) to bound by date, and `limit` to trim results.
- The `/map` page now has a "Full route ICAO" control that draws the full path using this endpoint.

## Export back to CSV for maps
```bash
ADSB_DB_URL=postgresql://adsb:adsb@localhost:5432/adsb \
python -m apps.db_export --hours 6
```
Outputs to `output/adsb_history.csv` and `output/adsb_current.csv`.
