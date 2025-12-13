#!/usr/bin/env python3
"""
ADS-B Map Plotter

Plots aircraft positions from CSV files onto an interactive map.
Supports both current positions and historical trajectories.

Usage:
    python -m apps.plot_map                    # Plot current positions
    python -m apps.plot_map --historical       # Plot all historical positions
    python -m apps.plot_map --icao 3C5EF2     # Plot trajectory for specific aircraft
    python -m apps.plot_map --home-address "Milan, Italy"  # Set home location
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401

# Import shared modules
from adsb.config import (
    PROJECT_ROOT, OUTPUT_DIR, ICONS_DIR,
    get_history_csv_path, get_current_csv_path,
    DEFAULT_MAP_HTML, DEFAULT_CURRENT_MAP_HTML,
)
from adsb.geo import (
    get_home_location, set_home_from_address, setup_home_location,
    calculate_bearing, calculate_3d_distance,
)
from adsb.colors import get_altitude_color, get_altitude_color_js

# Import aircraft database
try:
    from apps.aircraft_db import get_aircraft_info, get_icon_for_type, AircraftDatabase
    AIRCRAFT_DB_AVAILABLE = True
except ImportError:
    AIRCRAFT_DB_AVAILABLE = False
    print("Warning: aircraft_db module not available, using default icons", file=sys.stderr)


def read_csv_positions(csv_path) -> List[Dict[str, Any]]:
    """Read positions from a CSV file."""
    positions = []

    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        return positions

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            try:
                if not row.get("icao") or not row.get("lat") or not row.get("lon"):
                    continue

                lat = float(row["lat"])
                lon = float(row["lon"])

                position = {
                    "timestamp_utc": row.get("timestamp_utc", ""),
                    "icao": row.get("icao", "").strip(),
                    "flight": row.get("flight", "").strip(),
                    "lat": lat,
                    "lon": lon,
                    "altitude_ft": int(float(row["altitude_ft"])) if row.get("altitude_ft") and row["altitude_ft"].strip() else None,
                    "speed_kts": float(row["speed_kts"]) if row.get("speed_kts") and row["speed_kts"].strip() else None,
                    "heading_deg": float(row["heading_deg"]) if row.get("heading_deg") and row["heading_deg"].strip() else None,
                    "squawk": row.get("squawk", "").strip(),
                }
                positions.append(position)
            except (ValueError, KeyError) as e:
                print(f"Warning: Skipping row {row_num} in {csv_path}: {e}", file=sys.stderr)
                continue

    return positions


def calculate_headings_from_trajectory(positions: List[Dict[str, Any]], history_path=None) -> None:
    """
    Calculate headings from trajectory for positions without heading data.
    Modifies positions in place.
    """
    # Group positions by ICAO
    icao_positions = {}
    for p in positions:
        icao = p["icao"]
        if icao not in icao_positions:
            icao_positions[icao] = []
        icao_positions[icao].append(p)

    # For aircraft with only one position, try to load recent historical positions
    if history_path and os.path.exists(history_path):
        icaos_needing_history = {
            icao for icao, pos_list in icao_positions.items()
            if len(pos_list) == 1 and pos_list[0].get("heading_deg") is None
        }

        if icaos_needing_history:
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                history_positions = {icao: [] for icao in icaos_needing_history}
                reader = csv.DictReader(lines)
                all_rows = list(reader)

                for row in reversed(all_rows):
                    icao = row.get("icao", "").strip()
                    if icao in icaos_needing_history and len(history_positions[icao]) < 5:
                        try:
                            lat = float(row["lat"])
                            lon = float(row["lon"])
                            history_positions[icao].append({
                                "lat": lat,
                                "lon": lon,
                                "timestamp_utc": row.get("timestamp_utc", "")
                            })
                        except (ValueError, KeyError):
                            pass

                    if all(len(v) >= 2 for v in history_positions.values()):
                        break

                # Add historical positions for heading calculation
                for icao, hist_list in history_positions.items():
                    if hist_list:
                        hist_list.reverse()
                        icao_positions[icao] = hist_list + icao_positions[icao]
            except Exception as e:
                print(f"Warning: Could not load history for heading calculation: {e}", file=sys.stderr)

    # Calculate heading from consecutive positions
    for icao, pos_list in icao_positions.items():
        pos_list.sort(key=lambda x: x.get("timestamp_utc", ""))

        for i in range(len(pos_list)):
            if pos_list[i].get("heading_deg") is None:
                if i > 0:
                    prev_pos = pos_list[i - 1]
                    if prev_pos["lat"] != pos_list[i]["lat"] or prev_pos["lon"] != pos_list[i]["lon"]:
                        heading = calculate_bearing(
                            prev_pos["lat"], prev_pos["lon"],
                            pos_list[i]["lat"], pos_list[i]["lon"]
                        )
                        pos_list[i]["heading_deg"] = round(heading, 1)
                elif i < len(pos_list) - 1:
                    next_pos = pos_list[i + 1]
                    if next_pos["lat"] != pos_list[i]["lat"] or next_pos["lon"] != pos_list[i]["lon"]:
                        heading = calculate_bearing(
                            pos_list[i]["lat"], pos_list[i]["lon"],
                            next_pos["lat"], next_pos["lon"]
                        )
                        pos_list[i]["heading_deg"] = round(heading, 1)


def load_svg_icons() -> Dict[str, str]:
    """Load all SVG icons from assets/icons/ directory dynamically."""
    svg_icons = {}
    if ICONS_DIR.exists():
        for svg_path in ICONS_DIR.glob("*.svg"):
            icon_name = svg_path.stem  # filename without extension
            with open(svg_path, "r") as f:
                svg_content = f.read().strip()
                if 'width=' not in svg_content:
                    svg_content = svg_content.replace('<svg ', '<svg width="28" height="28" ')
                svg_icons[icon_name] = svg_content
    return svg_icons


def create_map(positions: List[Dict[str, Any]], output_path: str = None,
               title: str = "ADS-B Aircraft Positions", refresh_interval: int = 1,
               current_icaos: Optional[set] = None) -> None:
    """Create an interactive map with aircraft positions using folium."""
    try:
        import folium
        from folium import DivIcon
    except ImportError:
        print("Error: folium is not installed.", file=sys.stderr)
        print("Install it with: pip install folium", file=sys.stderr)
        sys.exit(1)

    if output_path is None:
        output_path = str(DEFAULT_MAP_HTML)

    if not positions:
        print("No positions to plot.", file=sys.stderr)
        return

    # Get home location
    home = get_home_location()
    home_lat = home['lat']
    home_lon = home['lon']
    home_elevation_m = home.get('elevation_m', 0)
    home_elevation_ft = home.get('elevation_ft', 0)
    home_display_name = home.get('display_name', 'Home')
    print(f"Home location: {home_display_name}")
    print(f"Coordinates: {home_lat}, {home_lon} | Elevation: {home_elevation_m:.0f}m ({home_elevation_ft:.0f}ft)")

    # Calculate bounds to fit all current aircraft
    latest_positions = {}
    for p in positions:
        if current_icaos is None or p["icao"] in current_icaos:
            icao = p["icao"]
            if icao not in latest_positions or p.get("timestamp_utc", "") > latest_positions[icao].get("timestamp_utc", ""):
                latest_positions[icao] = p

    current_positions_list = list(latest_positions.values())
    all_lats = [home_lat] + [p["lat"] for p in current_positions_list]
    all_lons = [home_lon] + [p["lon"] for p in current_positions_list]

    bounds = None
    if len(current_positions_list) > 0:
        min_lat, max_lat = min(all_lats), max(all_lats)
        min_lon, max_lon = min(all_lons), max(all_lons)
        lat_padding = (max_lat - min_lat) * 0.05 or 0.01
        lon_padding = (max_lon - min_lon) * 0.05 or 0.01
        bounds = [
            [min_lat - lat_padding, min_lon - lon_padding],
            [max_lat + lat_padding, max_lon + lon_padding]
        ]
        print(f"Fitting map to {len(current_positions_list)} current aircraft")
    else:
        print("No current aircraft, centering on home")

    # Create map
    m = folium.Map(location=[home_lat, home_lon], zoom_start=10, tiles="OpenStreetMap")

    if bounds:
        m.fit_bounds(bounds)

    # Add tile layers
    folium.TileLayer("CartoDB positron").add_to(m)
    folium.TileLayer("CartoDB dark_matter").add_to(m)

    # Add home marker
    home_icon_html = '''
    <div style="
        background-color: red;
        border: 2px solid white;
        border-radius: 50%;
        width: 30px;
        height: 30px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        font-size: 18px;
        color: white;
        box-shadow: 0 2px 4px rgba(0,0,0,0.3);
    ">H</div>
    '''
    home_icon = DivIcon(
        html=home_icon_html,
        icon_size=(30, 30),
        icon_anchor=(15, 15),
        class_name='home-marker'
    )
    home_popup_html = f"<b>Home Position</b><br>{home_display_name}<br><b>Elevation:</b> {home_elevation_ft:.0f} ft ({home_elevation_m:.0f} m)"
    folium.Marker(
        location=[home_lat, home_lon],
        popup=folium.Popup(home_popup_html, max_width=300),
        tooltip="Home",
        icon=home_icon,
    ).add_to(m)

    # Determine current ICAOs if not provided
    if current_icaos is None:
        current_icaos = set()
        try:
            current_time = datetime.now(timezone.utc)
            for pos in positions:
                if pos.get("timestamp_utc"):
                    try:
                        pos_time = datetime.fromisoformat(pos["timestamp_utc"].replace('Z', '+00:00'))
                        if (current_time - pos_time).total_seconds() < 120:
                            current_icaos.add(pos["icao"])
                    except:
                        pass
        except:
            current_icaos = set(p["icao"] for p in positions)

    # Draw trajectory lines for all aircraft
    icao_groups = {}
    for pos in positions:
        icao = pos["icao"]
        if icao not in icao_groups:
            icao_groups[icao] = []
        icao_groups[icao].append(pos)

    for icao, pos_list in icao_groups.items():
        pos_list_sorted = sorted(pos_list, key=lambda p: p.get("timestamp_utc", ""))
        latest = pos_list_sorted[-1] if pos_list_sorted else pos_list[0]
        marker_color = get_altitude_color(latest.get("altitude_ft"))
        is_current = icao in current_icaos if current_icaos else True

        if len(pos_list_sorted) > 1:
            line_opacity = 0.6 if is_current else 0.3
            # Draw each segment with color based on altitude (rainbow effect)
            for i in range(len(pos_list_sorted) - 1):
                p1 = pos_list_sorted[i]
                p2 = pos_list_sorted[i + 1]
                # Use the altitude at the start of each segment for coloring
                segment_color = get_altitude_color(p1.get("altitude_ft"))
                folium.PolyLine(
                    [[p1["lat"], p1["lon"]], [p2["lat"], p2["lon"]]],
                    color=segment_color,
                    weight=3,
                    opacity=line_opacity,
                ).add_to(m)

    # Add layer control
    folium.LayerControl().add_to(m)

    # Load aircraft database for type lookup
    aircraft_types = {}
    if AIRCRAFT_DB_AVAILABLE:
        db = AircraftDatabase()
        if db.load():
            unique_icaos = set(p["icao"] for p in positions)
            for icao in unique_icaos:
                info = db.lookup(icao)
                if info and info.get("type"):
                    aircraft_types[icao] = {
                        "type": info.get("type", ""),
                        "registration": info.get("registration", ""),
                        "model": info.get("model", ""),
                        "manufacturer": info.get("manufacturer", ""),
                        "icon": get_icon_for_type(info.get("type", ""))
                    }

    # Calculate headings from trajectory
    history_path = get_history_csv_path()
    calculate_headings_from_trajectory(positions, str(history_path))

    # Prepare data for JavaScript
    positions_data = [
        {
            "icao": p["icao"],
            "flight": p.get("flight", ""),
            "lat": p["lat"],
            "lon": p["lon"],
            "altitude_ft": p.get("altitude_ft"),
            "speed_kts": p.get("speed_kts"),
            "heading_deg": p.get("heading_deg"),
            "squawk": p.get("squawk", ""),
            "timestamp_utc": p.get("timestamp_utc", "")
        }
        for p in positions
    ]
    positions_json = json.dumps(positions_data)
    aircraft_types_json = json.dumps(aircraft_types)
    svg_icons_json = json.dumps(load_svg_icons())
    current_icaos_json = json.dumps(list(current_icaos) if current_icaos else [])

    # Save JSON data file
    json_path = os.path.splitext(output_path)[0] + "_data.json"
    json_filename = os.path.basename(json_path)
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(positions_json)

    # Add CSS
    icon_css = '''
    <style>
    .aircraft-icon {
        background: transparent !important;
        border: none !important;
    }
    .aircraft-icon svg {
        filter: drop-shadow(1px 1px 1px rgba(0,0,0,0.5));
    }
    .leaflet-popup .leaflet-popup-content-wrapper,
    .leaflet-popup-content-wrapper {
        background: rgba(0, 0, 0, 0.6) !important;
        background-color: rgba(0, 0, 0, 0.6) !important;
        backdrop-filter: blur(20px) saturate(180%) !important;
        -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
        border-radius: 14px !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4) !important;
        color: #fff !important;
    }
    .leaflet-popup .leaflet-popup-content,
    .leaflet-popup-content {
        margin: 14px 16px !important;
        min-width: 260px !important;
        color: #fff !important;
    }
    .leaflet-popup .leaflet-popup-tip-container .leaflet-popup-tip,
    .leaflet-popup-tip {
        background: rgba(0, 0, 0, 0.6) !important;
        background-color: rgba(0, 0, 0, 0.6) !important;
        box-shadow: none !important;
    }
    .leaflet-popup-close-button {
        color: #fff !important;
    }
    .leaflet-popup-close-button:hover {
        color: #ccc !important;
    }
    </style>
    '''
    m.get_root().html.add_child(folium.Element(icon_css))

    # Add title with dark glassmorphism style
    title_html = f'''
    <h3 id="map-title" style="position:fixed;
               top:10px;left:50px;width:320px;z-index:1000;
               background:rgba(0,0,0,0.6);
               backdrop-filter:blur(20px) saturate(180%);
               -webkit-backdrop-filter:blur(20px) saturate(180%);
               padding:12px 16px;
               border:1px solid rgba(255,255,255,0.15);
               border-radius:14px;
               box-shadow:0 8px 32px rgba(0,0,0,0.4);
               color:#fff;
               font-size:14px;
               font-weight:normal">
    {title}<br>
    <span id="map-stats" style="font-size:12px;color:#fff;">Aircraft: {len(set(p["icao"] for p in positions))} | Positions: {len(positions)}</span><br>
    <span style="font-size:10px;color:rgba(255,255,255,0.6);">Auto-updating every 1s</span>
    </h3>
    '''
    m.get_root().html.add_child(folium.Element(title_html))

    # Add JavaScript for dynamic updates
    home_display_name_escaped = home_display_name.replace("'", "\\'")
    altitude_color_js = get_altitude_color_js()

    update_js = f'''
    <script>
    let embeddedPositionsData = {positions_json};
    let currentICAOs = new Set({current_icaos_json});
    let aircraftTypes = {aircraft_types_json};
    const SVG_ICONS = {svg_icons_json};

    const HOME_LOCATION = {{
        lat: {home_lat},
        lon: {home_lon},
        elevation_m: {home_elevation_m},
        elevation_ft: {home_elevation_ft},
        name: '{home_display_name_escaped}'
    }};

    function calculate3DDistance(aircraft_lat, aircraft_lon, aircraft_alt_ft) {{
        const R = 6371.0;
        const lat1 = HOME_LOCATION.lat * Math.PI / 180;
        const lat2 = aircraft_lat * Math.PI / 180;
        const dlat = (aircraft_lat - HOME_LOCATION.lat) * Math.PI / 180;
        const dlon = (aircraft_lon - HOME_LOCATION.lon) * Math.PI / 180;

        const a = Math.sin(dlat / 2) * Math.sin(dlat / 2) +
                  Math.cos(lat1) * Math.cos(lat2) * Math.sin(dlon / 2) * Math.sin(dlon / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        const horizontalDistKm = R * c;

        const aircraftAltM = (aircraft_alt_ft || 0) * 0.3048;
        const altDiffKm = (aircraftAltM - HOME_LOCATION.elevation_m) / 1000.0;

        return Math.sqrt(horizontalDistKm * horizontalDistKm + altDiffKm * altDiffKm);
    }}

    function formatDistance(distanceKm) {{
        if (distanceKm < 1) return `${{Math.round(distanceKm * 1000)}} m`;
        if (distanceKm < 10) return `${{distanceKm.toFixed(2)}} km`;
        return `${{distanceKm.toFixed(1)}} km`;
    }}

    {altitude_color_js}

    let markerLayer = null;
    let lineLayer = null;
    let currentMarkers = {{}};
    let currentLines = {{}};
    let homeMarker = null;

    (function initializeMap() {{
        function findMap() {{
            let mapObj = null;
            const mapDiv = document.querySelector('.folium-map, [id^="map_"]');
            if (mapDiv && mapDiv.id && typeof window[mapDiv.id] !== 'undefined') {{
                mapObj = window[mapDiv.id];
            }}
            if (!mapObj && typeof window.map !== 'undefined') mapObj = window.map;

            if (mapObj && mapObj instanceof L.Map) {{
                const layersToRemove = [];
                mapObj.eachLayer(function(layer) {{
                    if (layer instanceof L.Marker) {{
                        const isHome = layer.options && layer.options.icon &&
                                      (layer.options.icon.options || layer.options.icon) &&
                                      ((layer.options.icon.options || layer.options.icon).className === 'home-marker');
                        if (!isHome) layersToRemove.push(layer);
                    }}
                }});
                layersToRemove.forEach(l => {{ try {{ mapObj.removeLayer(l); }} catch(e) {{}} }});

                markerLayer = L.featureGroup();
                lineLayer = L.featureGroup();
                mapObj.addLayer(markerLayer);
                mapObj.addLayer(lineLayer);

                const homeLat = {home_lat};
                const homeLon = {home_lon};
                if (homeLat && homeLon) {{
                    const homeIcon = L.divIcon({{
                        className: 'home-marker',
                        html: '<div style="background-color: red; border: 2px solid white; border-radius: 50%; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">H</div>',
                        iconSize: [30, 30],
                        iconAnchor: [15, 15]
                    }});
                    homeMarker = L.marker([homeLat, homeLon], {{ icon: homeIcon }}).bindPopup('<b>Home Position</b>');
                    mapObj.addLayer(homeMarker);
                }}

                updateMarkers(embeddedPositionsData);
                startAutoUpdate();
            }} else {{
                setTimeout(findMap, 100);
            }}
        }}
        if (document.readyState === 'complete') findMap();
        else window.addEventListener('load', findMap);
    }})();

    function formatTimeAgo(timestamp_utc) {{
        if (!timestamp_utc) return '';
        try {{
            const posTime = new Date(timestamp_utc);
            const now = new Date();
            const diffSec = Math.floor((now - posTime) / 1000);
            if (diffSec < 5) return 'now';
            if (diffSec < 60) return `${{diffSec}} seconds ago`;
            const diffMin = Math.floor(diffSec / 60);
            if (diffMin === 1) return '1 minute ago';
            if (diffMin < 60) return `${{diffMin}} minutes ago`;
            const diffHr = Math.floor(diffMin / 60);
            return diffHr === 1 ? '1 hour ago' : `${{diffHr}} hours ago`;
        }} catch(e) {{ return timestamp_utc; }}
    }}

    function getAircraftIconType(icao) {{
        return (aircraftTypes[icao] && aircraftTypes[icao].icon) || 'plane';
    }}

    function getAircraftInfo(icao) {{
        return aircraftTypes[icao] || null;
    }}

    function createSvgIcon(icao, altitude_ft, heading_deg) {{
        const iconType = getAircraftIconType(icao);
        const color = getAltitudeColor(altitude_ft);
        const rotation = heading_deg !== null && heading_deg !== undefined ? heading_deg : 0;
        let svg = (SVG_ICONS[iconType] || SVG_ICONS['plane']).replace(/\\{{COLOR\\}}/g, color);
        const html = `<div style="transform: rotate(${{rotation}}deg); transform-origin: center center;">${{svg}}</div>`;
        return L.divIcon({{ html: html, className: 'aircraft-icon', iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -14] }});
    }}

    function startAutoUpdate() {{
        const isHttp = window.location.protocol.startsWith('http');
        if (isHttp) {{
            updateMapData();
            setInterval(updateMapData, 1000);
        }} else {{
            setInterval(() => updateMarkers(embeddedPositionsData), 1000);
        }}
    }}

    function updateMapData() {{
        fetch('{json_filename}?t=' + new Date().getTime())
            .then(r => r.json())
            .then(data => {{
                embeddedPositionsData = data;
                updateMarkers(data);
            }})
            .catch(e => console.log('Update failed:', e));
    }}

    function updateMarkers(positions) {{
        if (!markerLayer || !lineLayer) return;

        const mapObj = markerLayer._map;
        if (mapObj && homeMarker && !mapObj.hasLayer(homeMarker)) {{
            mapObj.addLayer(homeMarker);
        }}

        const icaoGroups = {{}};
        positions.forEach(pos => {{
            if (!icaoGroups[pos.icao]) icaoGroups[pos.icao] = [];
            icaoGroups[pos.icao].push(pos);
        }});

        const statsEl = document.getElementById('map-stats');
        if (statsEl) {{
            statsEl.textContent = `Aircraft: ${{Object.keys(icaoGroups).length}} | Positions: ${{positions.length}} | Current: ${{currentICAOs.size}}`;
        }}

        Object.keys(currentMarkers).forEach(icao => {{
            if (!currentICAOs.has(icao)) {{
                markerLayer.removeLayer(currentMarkers[icao]);
                delete currentMarkers[icao];
            }}
        }});

        lineLayer.clearLayers();
        currentLines = {{}};

        Object.keys(icaoGroups).forEach(icao => {{
            const posList = icaoGroups[icao].sort((a, b) => (a.timestamp_utc || '').localeCompare(b.timestamp_utc || ''));
            const latest = posList[posList.length - 1];
            const color = getAltitudeColor(latest.altitude_ft);
            const isCurrent = currentICAOs.has(icao);

            if (isCurrent) {{
                const acInfo = getAircraftInfo(icao);

                // Build popup with three sections
                let popup = '<div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 13px;">';

                // Section 1: Aircraft Data (static info)
                popup += '<table style="width: 100%; border-collapse: collapse; margin-bottom: 8px; table-layout: fixed;">';
                popup += `<tr><td style="width: 50%; padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">ICAO</td><td style="width: 50%; padding: 2px 0; font-weight: 600; color: #fff;">${{latest.icao}}</td></tr>`;
                if (latest.flight) popup += `<tr><td style="padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Flight</td><td style="padding: 2px 0; font-weight: 600; color: #fff;">${{latest.flight}}</td></tr>`;
                if (acInfo && acInfo.registration) popup += `<tr><td style="padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Registration</td><td style="padding: 2px 0; color: #fff;">${{acInfo.registration}}</td></tr>`;
                if (acInfo && acInfo.type) popup += `<tr><td style="padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Type</td><td style="padding: 2px 0; color: #fff;">${{acInfo.type}}</td></tr>`;
                if (acInfo && acInfo.model) popup += `<tr><td style="padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Model</td><td style="padding: 2px 0; color: #fff;">${{acInfo.model}}</td></tr>`;
                popup += '</table>';

                // Divider
                popup += '<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.2); margin: 6px 0;">';

                // Section 2: Live Data (dynamic info)
                popup += '<table style="width: 100%; border-collapse: collapse; margin-bottom: 8px; table-layout: fixed;">';
                if (latest.timestamp_utc) popup += `<tr><td style="width: 50%; padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Spotted</td><td style="width: 50%; padding: 2px 0; color: #fff;">${{formatTimeAgo(latest.timestamp_utc)}}</td></tr>`;
                popup += `<tr><td style="padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Distance</td><td style="padding: 2px 0; color: #fff;">${{formatDistance(calculate3DDistance(latest.lat, latest.lon, latest.altitude_ft))}}</td></tr>`;
                if (latest.altitude_ft) popup += `<tr><td style="padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Altitude</td><td style="padding: 2px 0; color: #fff;">${{latest.altitude_ft.toLocaleString()}} ft <span style="color:rgba(255,255,255,0.5);">(${{Math.round(latest.altitude_ft * 0.3048).toLocaleString()}} m)</span></td></tr>`;
                if (latest.speed_kts) popup += `<tr><td style="padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Speed</td><td style="padding: 2px 0; color: #fff;">${{Math.round(latest.speed_kts)}} kts <span style="color:rgba(255,255,255,0.5);">(${{Math.round(latest.speed_kts * 1.852)}} km/h)</span></td></tr>`;
                if (latest.heading_deg != null) popup += `<tr><td style="padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Heading</td><td style="padding: 2px 0; color: #fff;">${{Math.round(latest.heading_deg)}}°</td></tr>`;
                if (latest.squawk) popup += `<tr><td style="padding: 2px 4px 2px 0; color: rgba(255,255,255,0.6);">Squawk</td><td style="padding: 2px 0; color: #fff;">${{latest.squawk}}</td></tr>`;
                popup += '</table>';

                // Section 3: Tracking Links
                popup += '<hr style="border: none; border-top: 1px solid rgba(255,255,255,0.2); margin: 6px 0;">';
                popup += '<div style="text-align: center; padding-top: 2px;">';
                popup += `<a href="https://globe.adsbexchange.com/?icao=${{latest.icao.toLowerCase()}}" target="_blank" style="color:#6cb8ff; text-decoration:none; margin-right: 12px;">ADSBexchange</a>`;
                if (acInfo && acInfo.registration) {{
                    popup += `<a href="https://www.flightradar24.com/data/aircraft/${{acInfo.registration.toLowerCase()}}" target="_blank" style="color:#6cb8ff; text-decoration:none;">FlightRadar24</a>`;
                }}
                popup += '</div>';
                popup += '</div>';

                if (currentMarkers[icao]) {{
                    currentMarkers[icao].setLatLng([latest.lat, latest.lon]);
                    currentMarkers[icao].setPopupContent(popup);
                    currentMarkers[icao].setIcon(createSvgIcon(icao, latest.altitude_ft, latest.heading_deg));
                }} else {{
                    const marker = L.marker([latest.lat, latest.lon], {{ icon: createSvgIcon(icao, latest.altitude_ft, latest.heading_deg) }}).bindPopup(popup);
                    markerLayer.addLayer(marker);
                    currentMarkers[icao] = marker;
                }}
            }}

            if (posList.length > 1) {{
                // Draw each segment with color based on altitude (rainbow effect)
                const lineOpacity = isCurrent ? 0.6 : 0.3;
                const segments = [];
                for (let i = 0; i < posList.length - 1; i++) {{
                    const p1 = posList[i];
                    const p2 = posList[i + 1];
                    const segmentColor = getAltitudeColor(p1.altitude_ft);
                    const segment = L.polyline([[p1.lat, p1.lon], [p2.lat, p2.lon]], {{
                        color: segmentColor,
                        weight: 3,
                        opacity: lineOpacity
                    }});
                    lineLayer.addLayer(segment);
                    segments.push(segment);
                }}
                currentLines[icao] = segments;
            }}
        }});
    }}
    </script>
    '''
    m.get_root().html.add_child(folium.Element(update_js))

    # Save map
    m.save(output_path)
    print(f"Map saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Plot ADS-B aircraft positions on an interactive map",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m apps.plot_map                    # Current positions with trajectories
  python -m apps.plot_map --historical       # All historical positions
  python -m apps.plot_map --icao 3C5EF2      # Specific aircraft trajectory
  python -m apps.plot_map --no-history       # Current positions only
  python -m apps.plot_map --home-address "Milan, Italy"  # Set home location
        """
    )

    parser.add_argument("--csv", default=None, help="Path to CSV file")
    parser.add_argument("--historical", action="store_true", help="Use historical CSV file")
    parser.add_argument("--no-history", action="store_true", help="Don't load historical data")
    parser.add_argument("--icao", default=None, help="Filter to specific ICAO hex code")
    parser.add_argument("--output", default=None, help="Output HTML file path")
    parser.add_argument("--title", default=None, help="Map title")
    parser.add_argument("--refresh", type=int, default=0, help="Auto-refresh interval in seconds")
    parser.add_argument("--home-lat", type=float, default=None, help="Home position latitude")
    parser.add_argument("--home-lon", type=float, default=None, help="Home position longitude")
    parser.add_argument("--setup-home", action="store_true", help="Interactive home location setup")
    parser.add_argument("--home-address", type=str, default=None, help="Set home location by address")

    args = parser.parse_args()

    # Handle --home-address flag
    if args.home_address:
        result = set_home_from_address(args.home_address)
        sys.exit(0 if result else 1)

    # Handle --setup-home flag
    if args.setup_home:
        result = setup_home_location()
        if result:
            print("\nHome location configured successfully!")
        else:
            print("\nHome location setup cancelled or failed.")
        sys.exit(0)

    # Determine CSV file
    if args.csv:
        csv_path = args.csv
        historical_csv_path = None if args.no_history else str(get_history_csv_path())
    elif args.historical:
        csv_path = str(get_history_csv_path())
        historical_csv_path = None
    else:
        csv_path = str(get_current_csv_path())
        historical_csv_path = None if args.no_history else str(get_history_csv_path())

    # Determine output path
    if args.output:
        output_path = args.output
    elif args.historical:
        output_path = str(DEFAULT_MAP_HTML)
    else:
        output_path = str(DEFAULT_CURRENT_MAP_HTML) if args.csv else str(DEFAULT_MAP_HTML)

    # Read positions
    print(f"Reading positions from: {csv_path}")
    positions = read_csv_positions(csv_path)

    # Merge historical trajectories if applicable
    if historical_csv_path and os.path.exists(historical_csv_path) and not args.historical:
        print(f"Loading historical trajectories from: {historical_csv_path}")
        historical_positions = read_csv_positions(historical_csv_path)

        if historical_positions:
            current_icaos = set(p["icao"] for p in positions)
            show_all_history = not args.csv

            for hist_pos in historical_positions:
                if show_all_history or hist_pos["icao"] in current_icaos:
                    is_duplicate = any(
                        p["icao"] == hist_pos["icao"] and
                        abs(p["lat"] - hist_pos["lat"]) < 0.0001 and
                        abs(p["lon"] - hist_pos["lon"]) < 0.0001
                        for p in positions
                    )
                    if not is_duplicate:
                        positions.append(hist_pos)

            print(f"Loaded {len(historical_positions)} historical positions")

    if not positions:
        print("No positions found.", file=sys.stderr)
        sys.exit(1)

    # Filter by ICAO if specified
    if args.icao:
        positions = [p for p in positions if p["icao"].upper() == args.icao.upper()]
        if not positions:
            print(f"No positions found for ICAO: {args.icao}", file=sys.stderr)
            sys.exit(1)

    # Generate title
    if args.title:
        title = args.title
    elif args.icao:
        title = f"ADS-B Aircraft {args.icao.upper()}"
    elif args.historical:
        title = "ADS-B Historical Positions"
    else:
        title = "ADS-B Current Positions with Trajectories"

    # Determine current ICAOs for marker display
    current_icaos_for_map = set()
    if not args.historical:
        current_csv_path = get_current_csv_path()
        if current_csv_path.exists():
            current_only = read_csv_positions(str(current_csv_path))
            current_icaos_for_map = set(p["icao"] for p in current_only)

            # Ensure current positions are in the data
            for icao, current_pos in {p["icao"]: p for p in current_only}.items():
                is_duplicate = any(
                    p["icao"] == icao and
                    abs(p["lat"] - current_pos["lat"]) < 0.0001 and
                    abs(p["lon"] - current_pos["lon"]) < 0.0001
                    for p in positions
                )
                if not is_duplicate:
                    positions.insert(0, current_pos)

    # Set home position from args
    if args.home_lat and args.home_lon:
        os.environ["ADSB_HOME_LAT"] = str(args.home_lat)
        os.environ["ADSB_HOME_LON"] = str(args.home_lon)

    print(f"Total positions: {len(positions)}, ICAOs: {len(set(p['icao'] for p in positions))}")
    create_map(positions, output_path, title, args.refresh, current_icaos_for_map)


if __name__ == "__main__":
    main()
