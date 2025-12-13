# Project: ADS-B → CSV/DB → 3D Map (Unreal)

## 1. Goal

Build a **portable** (macOS / Linux / Raspberry Pi) toolchain that:

1. Connects to a local **dump1090** instance (using an RTL-SDR receiver).
2. Reads **ADS-B aircraft data** from dump1090 over TCP.
3. **Step 1 (MVP):** saves parsed aircraft positions to a **CSV file**.
4. **Step 2:** saves positions into a **database** for long-term storage and queries.
5. Exposes data via a small **HTTP API** so a colleague can:
   - Render aircraft in a **3D Unreal Engine map** (based on LiDAR data).
   - Query **historical trajectories**.

All code should be **multi-platform** and run unmodified on:

- macOS (desktop)
- Generic Linux
- Raspberry Pi OS

Language for the implementation: **Python 3.x** (preferably 3.9+).


## 2. Current Status / Known Working Pieces

Already working:

- Hardware: RTL-SDR dongle.
- Software: `dump1090` built on macOS.
- Command:

  ```bash
  dump1090 --net --interactive
  ```

* `dump1090` is successfully receiving ADS-B traffic and showing an interactive table like:

  ```text
  Hex    Mode  Sqwk  Flight   Alt    Spd  Hdg    Lat      Long   RSSI  Msgs
  --------------------------------------------------------------------------
  3C5EF2 S     2531  EWG4TV   11100  376  158   45.630   8.936  -32.6  1012
  ...
  ```

When run with `--net`, `dump1090` also opens:

* SBS-1 (BaseStation) ASCII output on **TCP port 30003**.
* Beast binary output on **TCP port 30005**, etc.

For this project, we will use the **SBS-1 ASCII stream on port 30003**.

## 3. High-Level Architecture

### 3.1 Components

1. **Unified Entry Point (Shell Script)**

   * `adsb.sh` - One script to rule them all.
   * Automatically starts `dump1090` in the background (if not already running).
   * Launches the appropriate Python collector/API server.
   * Handles cleanup on exit.

2. **Receiver + Decoder**

   * `dump1090` (already working).
   * Started automatically by `adsb.sh` with `--net` flag.
   * Provides SBS-1 data on `127.0.0.1:30003`.

3. **Collector / Parser (Python script)**

   * Connects to `HOST:PORT` (default `127.0.0.1:30003`).
   * Reads SBS-1 lines continuously.
   * Parses each line to extract:

     * ICAO hex ID
     * Flight/callsign
     * Latitude / longitude
     * Altitude
     * Speed
     * Heading
     * Squawk (if available)
     * Message timestamp (either from SBS fields or local receive time)
   * Filters out lines without usable lat/lon.

4. **Output Layer**

   * **Phase A (MVP):** write parsed position records to **two CSV files**:
     * Historical CSV: all position records (append-only)
     * Current CSV: latest position per aircraft (snapshot, updated continuously)
   * **Phase B:** write parsed records into a **database**.

5. **API Layer**

   * Small HTTP API server (Python, e.g. FastAPI or Flask).
   * Serves data from the DB:

     * **Current positions** (per aircraft, for last N seconds).
     * **Historical trajectories** (for a given aircraft / time window).

6. **Consumer (Unreal Engine)**

   * Unreal project, maintained by a colleague.
   * Periodically calls HTTP endpoints:

     * For real-time rendering of current aircraft positions on a 3D map.
     * For trajectory playback based on historical data.

### 3.2 Portability Principles

* The unified shell script (`adsb.sh`):

  * Uses standard POSIX shell commands (`lsof`, `kill`, etc.).
  * Works on macOS, Linux, and Raspberry Pi.
  * Automatically handles dump1090 startup and cleanup.
* The collector script:

  * Uses only Python standard library networking (`socket`) and file I/O for CSV.
  * No OS-specific APIs.
* Database access:

  * Use a common Python DB driver (e.g. `psycopg2` for PostgreSQL).
  * DB connection parameters come from **environment variables**.
* API server:

  * Runs identically on macOS / Linux / Raspberry Pi.
  * Started via the unified `adsb.sh` script.

## 4. Step 1 – CSV Logger Specification

### 4.1. Input: SBS-1 / BaseStation stream

`dump1090 --net` sends ASCII lines on TCP port 30003, e.g.:

```text
MSG,3,111,11111,3C5EF2,111111,2025/12/07,17:01:58.200,2025/12/07,17:01:58.400,EWG4TV,38000,376,158,45.630,8.936,,,0,0,0,0
```

Typical fields we care about (0-based indexes after `split(",")`):

* `0` → `"MSG"` (message type).
* `1` → subtype (e.g., `3` = position).
* `4` → ICAO hex address (e.g. `3C5EF2`).
* `6` + `7` → date/time (generated).
* `10` → Flight/callsign (may be empty).
* `11` → Altitude (feet).
* `12` → Ground speed (knots).
* `13` → Track / heading (degrees).
* `14` → Latitude (decimal degrees).
* `15` → Longitude (decimal degrees).
* `17` → Squawk (in some variants; must guard by length).

Not all lines have all fields populated; parser must be defensive.

### 4.2. Unified Shell Script Behavior

The `adsb.sh` script should:

1. **Check prerequisites**

   * Verify `dump1090` command is available (or use `DUMP1090_CMD` env var).
   * Check if port 30003 is already in use (dump1090 may already be running).

2. **Start dump1090** (if needed)

   * If port is not in use, start `dump1090 --net --interactive` in background.
   * Wait for dump1090 to be ready (check port is listening).
   * Store PID for cleanup on exit.

3. **Launch Python collector**

   * Run the appropriate Python script based on mode (`csv`, `db`, `api`).
   * Pass through environment variables for configuration.

4. **Cleanup**

   * On exit (Ctrl+C, TERM, etc.), kill the dump1090 process if it was started by this script.
   * Use trap handlers for graceful cleanup.

### 4.3. Collector Script Behavior (CSV mode)

Script (`adsb_to_csv.py`) should:

1. **Config**

   * Read configuration from environment variables (with defaults):

     * `ADSB_HOST` (default: `127.0.0.1`)
     * `ADSB_PORT` (default: `30003`)
     * `ADSB_CSV_PATH` (default: `adsb_positions.csv`)
2. **Startup**

   * Ensure both CSV files exist with header rows if newly created:
     * Historical CSV: `adsb_positions.csv` (or `ADSB_CSV_PATH`)
     * Current CSV: `adsb_current.csv` (or `ADSB_CURRENT_CSV_PATH`)
   * Header format: `timestamp_utc,icao,flight,lat,lon,altitude_ft,speed_kts,heading_deg,squawk`
   * Initialize in-memory dictionary to track latest position per aircraft (keyed by ICAO)
3. **Connection loop**

   * Connect to `ADSB_HOST:ADSB_PORT` using `socket.create_connection`.
   * Wrap socket in a text file-like object (`makefile("r")`) for line iteration.
   * On connection failure, wait a few seconds and retry.
4. **Processing loop**

   * For each line:

     * Strip newline, ignore empty lines.
     * Parse into SBS fields.
     * If the line:

       * Is a `MSG` type, and
       * Contains valid latitude & longitude values,
       * Then build a record with:

         * `timestamp_utc`: current UTC time (`datetime.utcnow()` in ISO8601)
         * `icao`, `flight`, `lat`, `lon`, `altitude_ft`, `speed_kts`, `heading_deg`, `squawk`
     * **Historical CSV**: Append this record as a CSV row (append-only).
     * **Current CSV**: Update the in-memory dictionary with latest position for this ICAO, then periodically rewrite the entire current CSV file with all latest positions (snapshot).
     * Optional: flush periodically (not necessarily after every row).
5. **Error handling**

   * On parsing errors, log and skip the line (no crash).
   * On socket errors, log, close, and reconnect after a delay.
   * On `KeyboardInterrupt`, exit gracefully.

### 4.4. Acceptance Criteria for Step 1

* Running `./adsb.sh csv`:

  * Automatically starts dump1090 (if not already running).
  * Produces/updates two CSV files:
    * `adsb_history.csv`: Historical positions (all records, append-only)
    * `adsb_current.csv`: Current positions (latest per aircraft, snapshot)
  * Both CSV files have headers and proper data.
  * Each row has:

    * ISO UTC timestamp
    * ICAO hex
    * Optional flight/callsign
    * Lat/Lon, altitude, speed, heading where available.
  * Historical CSV grows over time with all positions.
  * Current CSV contains one row per unique aircraft (latest position).
  * On Ctrl+C, cleanly stops both the Python script and dump1090 (if started by the script), and writes final current positions snapshot.

## 5. Step 2 – Database Storage Specification

After CSV logging is validated, the next step is to log directly to a database.

### 5.1. Target DB

* Use **PostgreSQL** (can later extend with TimescaleDB if needed).
* DB connection string through environment variable, e.g.:

  * `ADSB_DB_URL=postgresql://user:pass@host:5432/adsb`

### 5.2. Schema

Two core tables:

```sql
CREATE TABLE IF NOT EXISTS aircraft (
    icao TEXT PRIMARY KEY,
    first_seen_utc TIMESTAMPTZ NOT NULL,
    last_seen_utc  TIMESTAMPTZ NOT NULL,
    last_flight    TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id BIGSERIAL PRIMARY KEY,
    icao TEXT NOT NULL REFERENCES aircraft(icao),
    ts   TIMESTAMPTZ NOT NULL,
    lat  DOUBLE PRECISION NOT NULL,
    lon  DOUBLE PRECISION NOT NULL,
    altitude_ft INTEGER,
    speed_kts   REAL,
    heading_deg REAL,
    squawk      TEXT
);

CREATE INDEX IF NOT EXISTS idx_positions_ts ON positions(ts);
CREATE INDEX IF NOT EXISTS idx_positions_icao_ts ON positions(icao, ts);
```

### 5.3. Collector Script Behavior (DB mode)

A second script (or a configurable mode), e.g. `adsb_to_db.py`:

1. Reads SBS stream exactly like `adsb_to_csv.py`.
2. Connects to Postgres using `ADSB_DB_URL`.
3. Ensures tables exist on startup (runs the `CREATE TABLE IF NOT EXISTS` statements).
4. For each parsed position:

   * Upsert row in `aircraft`:

     * If new ICAO: insert with current `first_seen_utc` and `last_seen_utc`.
     * If existing: update `last_seen_utc` (and `last_flight` if changed).
   * Insert row into `positions` with:

     * `icao`, `ts`, `lat`, `lon`, `altitude_ft`, `speed_kts`, `heading_deg`, `squawk`.
5. Prefer **batched inserts** (e.g. group N rows or periodic flush) for performance.

### 5.4. Portability

* No DB-specific OS behavior; relies on network connection to Postgres.
* Script can run on:

  * The same machine as dump1090 (e.g. Raspberry Pi).
  * Or a different machine (e.g. macOS or Linux) pointed at a remote DB.

## 6. Step 3 – HTTP API for Unreal / External Consumers

The Unreal Engine client (and other tools) will read from the DB via a small HTTP API.

### 6.1. Tech Choice

* Python web framework (FastAPI recommended for clarity and typing).
* Server runs alongside the DB (or on any machine with DB access).

### 6.2. Endpoints

#### 1. `GET /api/aircraft/current`

* Query params:

  * `since_seconds` (optional, default: 60)
* Behavior:

  * For each aircraft with a position in the last `since_seconds`, return its **latest** position.
* Response (JSON):

  ```json
  [
    {
      "icao": "3C5EF2",
      "flight": "EWG4TV",
      "ts": "2025-12-07T17:02:01Z",
      "lat": 45.630,
      "lon": 8.936,
      "altitude_ft": 11100,
      "speed_kts": 376,
      "heading_deg": 158,
      "squawk": "2531"
    },
    ...
  ]
  ```

#### 2. `GET /api/aircraft/{icao}/history`

* Path param: `icao` (hex)
* Query params:

  * `from` (ISO8601 UTC timestamp)
  * `to` (ISO8601 UTC timestamp)
* Behavior:

  * Return all positions for this `icao` between `from` and `to`, ordered by time ascending.
* Response (JSON):

  ```json
  {
    "icao": "3C5EF2",
    "flight": "EWG4TV",
    "positions": [
      {
        "ts": "2025/12/07T17:00:00Z",
        "lat": 45.620,
        "lon": 8.930,
        "altitude_ft": 11000,
        "speed_kts": 370,
        "heading_deg": 158,
        "squawk": "2531"
      },
      ...
    ]
  }
  ```

### 6.3. Unreal Engine Usage (High Level)

* Unreal tick / timer:

  * Every X seconds: call `/api/aircraft/current`.
  * For each aircraft:

    * Convert (lat, lon, altitude) → local world coordinates, based on LiDAR map origin and scale.
    * Move/spawn Actor representing the aircraft.
* For trajectories:

  * When user requests playback for an aircraft:

    * Call `/api/aircraft/{icao}/history` with desired time range.
    * Use the returned positions to create a spline/trajectory in 3D.

## 7. Event Bus & JSON Envelope Specification

### 7.1. AdsbPositionEvent structure

Producers now emit one JSON event per position over NATS. The contract is explicitly versioned via `eventType` (`adsb.position.v1`) and timestamps use the local receive time in UTC milliseconds (`tsUnixMs = int(time.time() * 1000)`).

Example payload:

```json
{
  "eventType": "adsb.position.v1",
  "source": "LISTENING_POST_LUGANO_01",
  "tsUnixMs": 1733870000000,
  "aircraft": {
    "icaoHex": "4CA123",
    "callsign": "RYR12AB",
    "registration": "EI-ABC",
    "icaoType": "B738",
    "model": "BOEING 737-8AS",
    "isMilitary": false,
    "isInteresting": false,
    "isPIA": false,
    "isLADD": false
  },
  "position": {
    "lat": 46.29419,
    "lon": 8.87816,
    "altitudeFt": 36000,
    "groundSpeedKts": 420.3,
    "trackDeg": 178.2,
    "verticalRateFpm": -128
  },
  "codes": {
    "squawk": "7700",
    "alert": false,
    "emergency": false,
    "spi": false,
    "onGround": false
  },
  "raw": {
    "sbs": "MSG,3,111,11111,4CA123,111111,2025/12/12,15:46:01.200,2025/12/12,15:46:01.200,RYR12AB,36000,420,178,46.29419,8.87816,,,0,7700,0,0",
    "messageType": "MSG",
    "transmissionType": 3
  }
}
```

### 7.2. Field reference

Top-level:

| Field | Type | Unit | Origin |
| --- | --- | --- | --- |
| eventType | string | - | Constant `adsb.position.v1` |
| source | string | - | Env `ADSB_SOURCE_ID` |
| tsUnixMs | integer | ms since epoch (UTC) | Calculated on receive (`time.time()*1000`) |

Aircraft:

| Field | Type | Unit | Origin |
| --- | --- | --- | --- |
| icaoHex | string | hex | SBS field 4 |
| callsign | string (optional) | - | SBS field 10 (trimmed) |
| registration | string (optional) | - | `aircraft_db.csv` |
| icaoType | string (optional) | - | `aircraft_db.csv` (type/code) |
| model | string (optional) | - | `aircraft_db.csv` |
| isMilitary | bool (optional) | - | `aircraft_db.csv` flags (bit 0) |
| isInteresting | bool (optional) | - | `aircraft_db.csv` flags (bit 1) |
| isPIA | bool (optional) | - | `aircraft_db.csv` flags (bit 2) |
| isLADD | bool (optional) | - | `aircraft_db.csv` flags (bit 3) |

Position:

| Field | Type | Unit | Origin |
| --- | --- | --- | --- |
| lat | float | degrees | SBS field 14 |
| lon | float | degrees | SBS field 15 |
| altitudeFt | integer | feet | SBS field 11 |
| groundSpeedKts | float | knots | SBS field 12 |
| trackDeg | float | degrees | SBS field 13 |
| verticalRateFpm | integer (optional) | feet/min | SBS field 16 |

Codes:

| Field | Type | Unit | Origin |
| --- | --- | --- | --- |
| squawk | string (optional) | code | SBS field 17 |
| alert | bool (optional) | flag | SBS field 18 (0/1) |
| emergency | bool (optional) | flag | SBS field 19 (0/1) |
| spi | bool (optional) | flag | SBS field 20 (0/1) |
| onGround | bool (optional) | flag | SBS field 21 (0/1) |

Raw:

| Field | Type | Unit | Origin |
| --- | --- | --- | --- |
| sbs | string | - | Original SBS-1 line (trimmed) |
| messageType | string | - | SBS field 0 (e.g., `MSG`) |
| transmissionType | integer (optional) | - | SBS field 1 (1–8) |

### 7.3. SBS-1 mapping (BaseStation → JSON)

| JSON path | SBS index | Notes |
| --- | --- | --- |
| aircraft.icaoHex | 4 | Required |
| aircraft.callsign | 10 | Trim spaces |
| position.altitudeFt | 11 | Feet |
| position.groundSpeedKts | 12 | Knots |
| position.trackDeg | 13 | Degrees |
| position.lat | 14 | Decimal degrees |
| position.lon | 15 | Decimal degrees |
| position.verticalRateFpm | 16 | Feet/min |
| codes.squawk | 17 | String |
| codes.alert | 18 | `0/1` → `false/true` |
| codes.emergency | 19 | `0/1` → `false/true` |
| codes.spi | 20 | `0/1` → `false/true` |
| codes.onGround | 21 | `0/1` → `false/true` |

Aircraft metadata (registration, type/model, PIA/LADD/military/interesting) are enriched from `data/aircraft_db.csv` when available. Flag bits follow the Mictronics/tar1090 database ordering: bit 0 = military, bit 1 = interesting, bit 2 = PIA, bit 3 = LADD.

Optional fields may be null or omitted; consumers should treat missing keys as "unknown" rather than false/zero.

### 7.4. Consumption via NATS

- Producer publishes `AdsbPositionEvent` to `ADSB_NATS_URL` (default `nats://localhost:4222`) on subject `ADSB_NATS_SUBJECT` (default `adsb.position.v1`).
- Consumers only need the bus coordinates and this contract; they do not need internal repo details.
- External services (e.g., airspace-core) simply subscribe to `ADSB_NATS_SUBJECT` and deserialize the JSON.

Python (asyncio) subscriber sketch:

```python
import asyncio, json, os
from nats.aio.client import Client as NATS

async def main():
    nc = NATS()
    await nc.connect(servers=[os.getenv("ADSB_NATS_URL", "nats://localhost:4222")])

    async def handler(msg):
        event = json.loads(msg.data)
        print(event["aircraft"]["icaoHex"], event["position"]["lat"], event["position"]["lon"])

    await nc.subscribe(os.getenv("ADSB_NATS_SUBJECT", "adsb.position.v1"), cb=handler)
    await asyncio.Future()

asyncio.run(main())
```

Go (pseudocode) subscriber sketch:

```go
nc, _ := nats.Connect(os.Getenv("ADSB_NATS_URL"))
nc.Subscribe(os.Getenv("ADSB_NATS_SUBJECT"), func(m *nats.Msg) {
    var evt map[string]any
    json.Unmarshal(m.Data, &evt)
    // use evt["aircraft"].(map[string]any)["icaoHex"] ...
})
select {}
```

## 8. Configuration & Environment

Use environment variables for runtime configuration:

* `DUMP1090_CMD` – dump1090 command name or path (default: `dump1090`).
* `ADSB_HOST` – default `127.0.0.1` (SBS source).
* `ADSB_PORT` – default `30003`.
* `ADSB_CSV_PATH` – path to historical CSV file (default: `adsb_history.csv`).
* `ADSB_CURRENT_CSV_PATH` – path to current positions CSV file (default: `adsb_current.csv`).
* `ADSB_DB_URL` – PostgreSQL connection string.
* `ADSB_API_HOST` – API bind host (default `0.0.0.0`).
* `ADSB_API_PORT` – API port (default `8000`).
* `ADSB_OUTPUT_MODE` – sender output (`nats` default, `http` legacy ingest).
* `ADSB_NATS_URL` – NATS server URL (default `nats://localhost:4222`).
* `ADSB_NATS_SUBJECT` – NATS subject for events (default `adsb.position.v1`).
* `ADSB_SOURCE_ID` – identifier for the producing station (included in events).
* `ADSB_BATCH_SIZE` – HTTP batch size (legacy sender/simulator mode).

This keeps the code identical across macOS, Linux, and Raspberry Pi—only the environment changes.

### Usage

All operations are started via the unified shell script:

```bash
# CSV logger (Step 1)
./adsb.sh csv

# Database logger (Step 2 - when implemented)
./adsb.sh db

# HTTP API server (Step 3 - when implemented)
./adsb.sh api
```

The shell script handles dump1090 startup automatically, so no manual intervention is needed.

## 9. Tasks for Implementation

### Task A – Implement Unified Shell Script and CSV Logger

* File: `adsb.sh` (shell script)
  * Implement behavior described in section 4.2.
  * Handle dump1090 startup, port checking, and cleanup.
* File: `adsb_to_csv.py` (Python script)
  * Implement behavior described in section 4.3.
* Test on macOS with:

  1. `./adsb.sh csv`
* Validate that:
  * dump1090 starts automatically
  * `adsb_positions.csv` fills with reasonable data
  * Cleanup works on Ctrl+C

### Task B – Implement DB Logger

* File: `adsb_to_db.py`
* Implement behavior described in section 5.
* Use Postgres with a simple local/docker instance.
* Verify tables and sample queries (e.g. `SELECT * FROM positions LIMIT 10;`).

### Task C – Implement HTTP API

* File structure suggestion:

  * `api/main.py` (FastAPI app)
  * `api/models.py` (Pydantic schemas)
  * `api/db.py` (connection + queries)
* Implement endpoints in section 6.
* Test with `curl` or a browser.

### Task D – Integration with Unreal

* The Unreal team consumes:

  * `/api/aircraft/current` for live positions.
  * `/api/aircraft/{icao}/history` for trajectories.
* Coordinate mapping (lat/lon → world coordinates) is handled inside Unreal based on the LiDAR data.

## 10. Future Extensions (Optional)

* Switch or augment storage with **TimescaleDB** for better time-series performance.
* Add **WebSockets** for push-based updates to clients instead of polling.
* Aggregate and export historical tracks for AI analysis:

  * Clustering, anomaly detection, route analysis, etc.
* Add a simple **web map frontend** (Leaflet/Mapbox/Google Maps) to visualize flights in 2D as well.

