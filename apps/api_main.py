#!/usr/bin/env python3
"""
Lightweight HTTP API backed by Postgres.

Endpoints:
- GET /api/aircraft/current?since_seconds=300
- GET /api/aircraft/{icao}/history?hours=6
- GET /api/aircraft/{icao}/route?start_utc=...&end_utc=...&limit=...
- GET /api/aircraft/tracks?since_seconds=1800&max_points_per_aircraft=80&icaos=ABC,DEF
- GET /api/health

Static map (Leaflet) at /map reading /api/aircraft/current every 5s.
"""

from __future__ import annotations

import logging
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401
import psycopg2
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field, validator

from adsb.config import AIRCRAFT_DB_FILE, OUTPUT_DIR, PROJECT_ROOT

try:
    from apps.aircraft_db import get_icon_for_type, get_aircraft_info
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


@app.on_event("startup")
def _on_startup() -> None:
    _generate_portal()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = PROJECT_ROOT / "api_static"
ASSETS_DIR = PROJECT_ROOT / "assets"

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

_INGEST_EVENTS: deque[datetime] = deque()


def _record_ingest_event(ts: datetime | None = None) -> None:
    """Track ingest hits for the last hour (best-effort, in-memory)."""
    now = ts or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)
    _INGEST_EVENTS.append(now)
    # Trim old events
    while _INGEST_EVENTS and _INGEST_EVENTS[0] < cutoff:
        _INGEST_EVENTS.popleft()


def _generate_portal() -> None:
    """
    (Best-effort) regenerate the HTML portal with DB stats and CSV previews.

    Keeps UX consistent when running under docker-compose: root (/) will serve
    output/index.html if present.
    """
    try:
        from apps import portal  # noqa: WPS433

        portal.main()
    except Exception as exc:  # pragma: no cover - non-critical
        logger.warning("Portal generation failed: %s", exc)


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


@app.get("/api/aircraft/{icao}/route")
def full_route(
    icao: str,
    start_utc: Optional[datetime] = None,
    end_utc: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> dict:
    """Return every stored point for an aircraft (optionally bounded)."""
    icao = icao.strip().upper()
    if limit is not None and limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0 when provided")

    filters = ["p.icao = %s", "p.lat IS NOT NULL", "p.lon IS NOT NULL"]
    params: list = [icao]
    if start_utc:
        filters.append("p.ts >= %s")
        params.append(start_utc)
    if end_utc:
        filters.append("p.ts <= %s")
        params.append(end_utc)
    where_clause = " AND ".join(filters)

    limit_clause = ""
    if limit:
        limit_clause = " LIMIT %s"
        params.append(limit)

    rows = fetch_all(
        f"""
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
        WHERE {where_clause}
        ORDER BY p.ts ASC{limit_clause}
        """,
        tuple(params),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="ICAO not found in database")

    positions = [
        {
            "ts": row["ts"].isoformat() if isinstance(row["ts"], datetime) else row["ts"],
            "lat": row["lat"],
            "lon": row["lon"],
            "altitude_ft": row["altitude_ft"],
            "speed_kts": row["speed_kts"],
            "heading_deg": row["heading_deg"],
            "squawk": row["squawk"],
        }
        for row in rows
    ]
    meta = enrich({"icao": rows[0]["icao"], "flight": rows[0].get("flight")})
    return {
        "icao": meta.get("icao", icao),
        "flight": meta.get("flight"),
        "registration": meta.get("registration"),
        "type": meta.get("type"),
        "model": meta.get("model"),
        "manufacturer": meta.get("manufacturer"),
        "icon": meta.get("icon", "plane"),
        "count": len(positions),
        "start_ts": positions[0]["ts"],
        "end_ts": positions[-1]["ts"],
        "positions": positions,
    }


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


@app.get("/api/stats/overview")
def stats_overview() -> dict:
    """Summary stats for portal/UI (counts and recency)."""
    rows = fetch_all(
        """
        SELECT
            (SELECT COUNT(*) FROM aircraft) AS aircraft_count,
            (SELECT COUNT(*) FROM positions) AS position_count,
            (SELECT MAX(ts) FROM positions) AS latest_ts,
            (SELECT COUNT(*) FROM positions WHERE ts >= NOW() - interval '1 hour') AS last_hour,
            (SELECT COUNT(*) FROM positions WHERE ts >= NOW() - interval '24 hours') AS last_day
        """,
        (),
    )
    row = rows[0] if rows else {}
    latest = row.get("latest_ts")
    return {
        "aircraft_count": row.get("aircraft_count", 0),
        "position_count": row.get("position_count", 0),
        "latest_ts": latest.isoformat() if isinstance(latest, datetime) else latest,
        "last_hour": row.get("last_hour", 0),
        "last_day": row.get("last_day", 0),
        "status": "ok",
        "ingests_last_hour": len(_INGEST_EVENTS),
    }


@app.get("/api/aircraft/recent")
def recent_aircraft(limit: int = 15) -> List[dict]:
    """Most recently seen aircraft with last point and counters."""
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")
    rows = fetch_all(
        """
        SELECT
            a.icao,
            a.last_flight AS flight,
            a.first_seen_utc,
            a.last_seen_utc,
            counts.position_count,
            last_pos.ts AS last_ts,
            last_pos.lat,
            last_pos.lon,
            last_pos.altitude_ft
        FROM aircraft a
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS position_count FROM positions p WHERE p.icao = a.icao
        ) counts ON TRUE
        LEFT JOIN LATERAL (
            SELECT ts, lat, lon, altitude_ft
            FROM positions p
            WHERE p.icao = a.icao
            ORDER BY ts DESC
            LIMIT 1
        ) last_pos ON TRUE
        ORDER BY a.last_seen_utc DESC
        LIMIT %s
        """,
        (limit,),
    )

    def to_json(row: dict) -> dict:
        base = {
            "icao": row["icao"],
            "flight": row.get("flight"),
            "first_seen_utc": row.get("first_seen_utc").isoformat() if isinstance(row.get("first_seen_utc"), datetime) else row.get("first_seen_utc"),
            "last_seen_utc": row.get("last_seen_utc").isoformat() if isinstance(row.get("last_seen_utc"), datetime) else row.get("last_seen_utc"),
            "position_count": row.get("position_count", 0),
            "last_ts": row.get("last_ts").isoformat() if isinstance(row.get("last_ts"), datetime) else row.get("last_ts"),
            "last_lat": row.get("lat"),
            "last_lon": row.get("lon"),
            "last_altitude_ft": row.get("altitude_ft"),
        }
        # Enrich with registration/icon/model if available
        return enrich(base)

    return [to_json(r) for r in rows]


@app.post("/api/ingest")
def ingest(payload: IngestPayload):
    """Ingest positions (typically from remote senders) into Postgres."""
    if not payload.positions:
        _record_ingest_event()
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
        _record_ingest_event()
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

    _record_ingest_event()
    return {"ingested": len(position_rows)}


@app.get("/map")
def map_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
def root():
    generated_portal = OUTPUT_DIR / "index.html"
    if generated_portal.exists():
        return FileResponse(generated_portal)
    home = STATIC_DIR / "home.html"
    if home.exists():
        return FileResponse(home)
    return {"endpoints": ["/api/aircraft/current", "/api/aircraft/{icao}/history", "/map"]}


# Static mounts for assets and JS/CSS
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
