#!/usr/bin/env python3
"""
Lightweight HTTP API backed by Postgres.

Endpoints:
- GET /api/aircraft/current?since_seconds=300
- GET /api/aircraft/{icao}/history?hours=6
- GET /api/aircraft/tracks?since_seconds=1800&max_points_per_aircraft=80&icaos=ABC,DEF
- GET /api/health

Static map (Leaflet) at /map reading /api/aircraft/current every 5s.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import psycopg2
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field, validator

from src.lib.config import AIRCRAFT_DB_FILE

try:
    from aircraft_db import get_icon_for_type, get_aircraft_info
except Exception:  # pragma: no cover
    get_icon_for_type = None
    get_aircraft_info = None

DB_URL = os.getenv("ADSB_DB_URL")
if not DB_URL:
    raise RuntimeError("ADSB_DB_URL is not set")

RETENTION_HOURS = int(os.getenv("ADSB_RETENTION_HOURS", "12"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("adsb_api")

app = FastAPI(title="ADS-B API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "api_static"
ASSETS_DIR = Path(__file__).parent / "assets"
if not ASSETS_DIR.exists():
    ASSETS_DIR = Path(__file__).parent / ".." / "assets"

AIRCRAFT_DB_URL = "https://raw.githubusercontent.com/wiedehopf/tar1090-db/csv/aircraft_db.csv"

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS aircraft (
        icao TEXT PRIMARY KEY,
        first_seen_utc TIMESTAMPTZ NOT NULL,
        last_seen_utc  TIMESTAMPTZ NOT NULL,
        last_flight    TEXT
    );
    """,
    """
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
    """,
    "CREATE INDEX IF NOT EXISTS idx_positions_ts ON positions(ts);",
    "CREATE INDEX IF NOT EXISTS idx_positions_icao_ts ON positions(icao, ts);",
]


def ensure_schema_exists() -> None:
    """Create tables/indexes if they don't exist (useful for fresh DBs)."""
    try:
        with psycopg2.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                for ddl in DDL_STATEMENTS:
                    cur.execute(ddl)
            conn.commit()
        logger.info("Schema ensured (aircraft, positions).")
    except Exception as exc:  # pragma: no cover - startup failure is fatal
        logger.error("Schema init failed: %s", exc)
        raise


def prune_old_positions() -> None:
    """Keep DB size reasonable by trimming old rows."""
    if RETENTION_HOURS <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RETENTION_HOURS)
    try:
        with psycopg2.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM positions WHERE ts < %s", (cutoff,))
                deleted = cur.rowcount
            conn.commit()
        if deleted:
            logger.info("Pruned %s old position rows (older than %s hours)", deleted, RETENTION_HOURS)
    except Exception as exc:  # pragma: no cover
        logger.warning("Prune old positions failed: %s", exc)


def fetch_all(query: str, params: tuple) -> list:
    try:
        with psycopg2.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        logger.error("DB query failed: %s", exc)
        raise


def enrich(row: dict) -> dict:
    """Add icon/type info from aircraft_db if available."""
    if not get_aircraft_info or not get_icon_for_type:
        row["icon"] = "plane"
        return row
    info = get_aircraft_info(row["icao"])
    if info:
        row["registration"] = info.get("registration", "")
        row["type"] = info.get("type", "")
        row["model"] = info.get("model", "")
        row["manufacturer"] = info.get("manufacturer", "")
        row["icon"] = get_icon_for_type(info.get("type", ""))
    else:
        row["icon"] = "plane"
    return row


def ensure_aircraft_db() -> None:
    """Download aircraft_db.csv if missing so we can resolve icons."""
    if AIRCRAFT_DB_FILE.exists():
        return
    try:
        AIRCRAFT_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading aircraft_db.csv from %s", AIRCRAFT_DB_URL)
        resp = requests.get(AIRCRAFT_DB_URL, timeout=20)
        resp.raise_for_status()
        AIRCRAFT_DB_FILE.write_bytes(resp.content)
        logger.info("Downloaded aircraft_db to %s", AIRCRAFT_DB_FILE)
    except Exception as exc:
        logger.warning("Could not download aircraft_db.csv: %s", exc)


# Ensure DB file exists so icon/type enrichment works when available
ensure_aircraft_db()
# Ensure DB schema exists for fresh databases, and trim old rows to avoid huge history
ensure_schema_exists()
prune_old_positions()


class PositionIn(BaseModel):
    icao: str = Field(..., min_length=3, max_length=6, description="ICAO hex code")
    flight: str | None = Field(None, max_length=8)
    lat: float | None = None
    lon: float | None = None
    altitude_ft: float | None = None
    speed_kts: float | None = None
    heading_deg: float | None = None
    squawk: str | None = Field(None, max_length=8)
    ts: datetime | None = None

    @validator("icao")
    def normalize_icao(cls, v: str) -> str:
        return v.strip().upper()


class IngestPayload(BaseModel):
    positions: list[PositionIn]


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/api/aircraft/current")
def current(since_seconds: int = 300) -> List[dict]:
    since = datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
    rows = fetch_all(
        """
        SELECT DISTINCT ON (p.icao)
               p.icao,
               a.last_flight AS flight,
               p.ts,
               p.lat,
               p.lon,
               p.altitude_ft,
               p.speed_kts,
               p.heading_deg,
               p.squawk
        FROM positions p
        LEFT JOIN aircraft a ON a.icao = p.icao
        WHERE p.ts >= %s
        ORDER BY p.icao, p.ts DESC
        """,
        (since,),
    )
    return [enrich(r) for r in rows]


@app.get("/api/aircraft/{icao}/history")
def history(icao: str, hours: Optional[int] = 6) -> dict:
    if hours is None:
        hours = 6
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = fetch_all(
        """
        SELECT p.icao,
               a.last_flight AS flight,
               p.ts,
               p.lat,
               p.lon,
               p.altitude_ft,
               p.speed_kts,
               p.heading_deg,
               p.squawk
        FROM positions p
        LEFT JOIN aircraft a ON a.icao = p.icao
        WHERE p.icao = %s AND p.ts >= %s
        ORDER BY p.ts ASC
        """,
        (icao.upper(), since),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="ICAO not found in window")
    return {"icao": icao.upper(), "count": len(rows), "positions": [enrich(r) for r in rows]}


@app.get("/api/aircraft/tracks")
def tracks(
    since_seconds: int = 900,
    max_points_per_aircraft: int = 80,
    icaos: Optional[str] = None,
) -> List[dict]:
    """
    Return recent trajectories for aircraft in the given window.

    - since_seconds: time window to look back for positions
    - max_points_per_aircraft: cap to avoid returning huge track histories
    - icaos: optional comma-separated list to filter results
    """
    if max_points_per_aircraft <= 0:
        raise HTTPException(status_code=400, detail="max_points_per_aircraft must be > 0")

    since = datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
    icao_list: Optional[list[str]] = None
    if icaos:
        parsed = [x.strip().upper() for x in icaos.split(",") if x.strip()]
        icao_list = parsed or None

    filters = ["p.ts >= %s", "p.lat IS NOT NULL", "p.lon IS NOT NULL"]
    params: list = [since]
    if icao_list:
        filters.append("p.icao = ANY(%s)")
        params.append(icao_list)
    filter_clause = " AND ".join(filters)
    params.append(max_points_per_aircraft)

    rows = fetch_all(
        f"""
        WITH ranked AS (
            SELECT
                p.icao,
                a.last_flight AS flight,
                p.ts,
                p.lat,
                p.lon,
                p.altitude_ft,
                p.speed_kts,
                p.heading_deg,
                p.squawk,
                ROW_NUMBER() OVER (PARTITION BY p.icao ORDER BY p.ts DESC) AS rn
            FROM positions p
            LEFT JOIN aircraft a ON a.icao = p.icao
            WHERE {filter_clause}
        )
        SELECT icao,
               flight,
               ts,
               lat,
               lon,
               altitude_ft,
               speed_kts,
               heading_deg,
               squawk
        FROM ranked
        WHERE rn <= %s
        ORDER BY icao, ts ASC
        """,
        tuple(params),
    )

    tracks_by_icao: dict[str, dict] = {}
    for row in rows:
        icao = row["icao"]
        if icao not in tracks_by_icao:
            meta = enrich({"icao": icao, "flight": row.get("flight")})
            meta["positions"] = []
            tracks_by_icao[icao] = meta
        tracks_by_icao[icao]["positions"].append(
            {
                "ts": row["ts"].isoformat() if isinstance(row["ts"], datetime) else row["ts"],
                "lat": row["lat"],
                "lon": row["lon"],
                "altitude_ft": row["altitude_ft"],
                "speed_kts": row["speed_kts"],
                "heading_deg": row["heading_deg"],
                "squawk": row["squawk"],
            }
        )

    return list(tracks_by_icao.values())


@app.post("/api/ingest")
def ingest(payload: IngestPayload):
    """Ingest positions (typically from remote senders) into Postgres."""
    if not payload.positions:
        return {"ingested": 0}

    aircraft_rows = []
    position_rows = []
    now = datetime.now(timezone.utc)
    for pos in payload.positions:
        if pos.lat is None or pos.lon is None:
            continue
        ts = pos.ts or now
        aircraft_rows.append(
            (
                pos.icao,
                ts,
                ts,
                pos.flight,
            )
        )
        position_rows.append(
            (
                pos.icao,
                ts,
                pos.lat,
                pos.lon,
                pos.altitude_ft,
                pos.speed_kts,
                pos.heading_deg,
                pos.squawk,
            )
        )

    if not position_rows:
        return {"ingested": 0}

    try:
        with psycopg2.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO aircraft (icao, first_seen_utc, last_seen_utc, last_flight)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (icao) DO UPDATE
                        SET last_seen_utc = EXCLUDED.last_seen_utc,
                            last_flight   = COALESCE(EXCLUDED.last_flight, aircraft.last_flight)
                    """,
                    aircraft_rows,
                )
                cur.executemany(
                    """
                    INSERT INTO positions (icao, ts, lat, lon, altitude_ft, speed_kts, heading_deg, squawk)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    position_rows,
                )
            conn.commit()
    except Exception as exc:
        logger.error("Ingest failed: %s", exc)
        raise HTTPException(status_code=500, detail="Ingest failed")

    return {"ingested": len(position_rows)}


@app.get("/map")
def map_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
def root():
    home = STATIC_DIR / "home.html"
    if home.exists():
        return FileResponse(home)
    return {"endpoints": ["/api/aircraft/current", "/api/aircraft/{icao}/history", "/map"]}


# Static mounts for assets and JS/CSS
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
