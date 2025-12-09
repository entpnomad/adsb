#!/usr/bin/env python3
"""
Lightweight HTTP API backed by Postgres.

Endpoints:
- GET /api/aircraft/current?since_seconds=300
- GET /api/aircraft/{icao}/history?hours=6
- GET /api/health

Static map (Leaflet) at /map reading /api/aircraft/current every 5s.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import psycopg2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:
    from aircraft_db import get_icon_for_type, get_aircraft_info
except Exception:  # pragma: no cover
    get_icon_for_type = None
    get_aircraft_info = None

DB_URL = os.getenv("ADSB_DB_URL")
if not DB_URL:
    raise RuntimeError("ADSB_DB_URL is not set")

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


def fetch_all(query: str, params: tuple) -> list:
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


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
