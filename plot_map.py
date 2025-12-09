#!/usr/bin/env python3
"""
ADS-B Map Plotter

Plots aircraft positions from CSV files onto an interactive map.
Supports both current positions and historical trajectories.

Usage:
    python3 plot_map.py                    # Plot current positions
    python3 plot_map.py --historical       # Plot all historical positions
    python3 plot_map.py --icao 3C5EF2     # Plot trajectory for specific aircraft
"""

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the bearing (heading) from point 1 to point 2.
    Returns bearing in degrees (0-360, where 0 is North).
    """
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    lon_diff = math.radians(lon2 - lon1)

    x = math.sin(lon_diff) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(lon_diff)

    bearing = math.atan2(x, y)
    bearing_deg = math.degrees(bearing)

    # Normalize to 0-360
    return (bearing_deg + 360) % 360

# Import aircraft database for type lookup
try:
    from aircraft_db import get_aircraft_info, get_icon_for_type, AircraftDatabase
    AIRCRAFT_DB_AVAILABLE = True
except ImportError:
    AIRCRAFT_DB_AVAILABLE = False
    print("Warning: aircraft_db module not available, using default icons", file=sys.stderr)


def read_csv_positions(csv_path: str) -> List[Dict[str, Any]]:
    """Read positions from a CSV file."""
    positions = []
    
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        return positions
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):  # Start at 2 because row 1 is header
            try:
                # Skip empty rows
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


def get_altitude_color(altitude_ft: Optional[int]) -> str:
    """
    Get color based on altitude with progressive interpolation.
    Returns folium-compatible colors: orange, lightred, green, lightblue, blue, purple
    """
    if altitude_ft is None:
        return "gray"
    
    # Color stops: (altitude_ft, folium_color)
    # Mapped to valid folium colors: orange -> lightred -> green -> lightblue -> blue -> purple
    color_stops = [
        (0, "orange"),        # 0ft - orange
        (4000, "lightred"),   # 4000ft - yellow-ish (using lightred as closest)
        (8000, "green"),      # 8000ft - green
        (20000, "lightblue"), # 20000ft - cyan-ish (using lightblue)
        (30000, "blue"),      # 30000ft - blue
        (40000, "purple"),    # 40000ft - magenta-ish (using purple)
    ]
    
    # Find the two stops to interpolate between
    if altitude_ft <= color_stops[0][0]:
        return color_stops[0][1]
    if altitude_ft >= color_stops[-1][0]:
        return color_stops[-1][1]
    
    # Find the segment
    for i in range(len(color_stops) - 1):
        if color_stops[i][0] <= altitude_ft <= color_stops[i + 1][0]:
            # Interpolate between these two colors
            alt1, color1 = color_stops[i]
            alt2, color2 = color_stops[i + 1]
            
            # Simple interpolation - use the lower color if close, higher if far
            ratio = (altitude_ft - alt1) / (alt2 - alt1)
            if ratio < 0.5:
                return color1
            else:
                return color2
    
    return "gray"


def create_map(positions: List[Dict[str, Any]], output_path: str = "adsb_map.html", 
                title: str = "ADS-B Aircraft Positions", refresh_interval: int = 1,
                current_icaos: Optional[set] = None) -> None:
    """Create an interactive map with aircraft positions using folium."""
    try:
        import folium
        from folium import plugins
    except ImportError:
        print("Error: folium is not installed.", file=sys.stderr)
        print("Install it with: pip install folium", file=sys.stderr)
        sys.exit(1)
    
    if not positions:
        print("No positions to plot.", file=sys.stderr)
        return

    # Center map on home position, zoomed out to see all aircraft
    home_lat = float(os.getenv("ADSB_HOME_LAT", "46.0359"))
    home_lon = float(os.getenv("ADSB_HOME_LON", "8.9661"))
    center_lat = home_lat
    center_lon = home_lon
    print(f"Centering map on home position: {center_lat}, {center_lon}")

    # Create map
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=9,  # Zoomed out to see all detected aircraft
        tiles="OpenStreetMap"
    )
    
    # Add different tile layers
    folium.TileLayer("CartoDB positron").add_to(m)
    folium.TileLayer("CartoDB dark_matter").add_to(m)
    
    # Add home position marker if specified (default to Via Pezzolo 6, Cannobio, Ticino)
    # Note: This is likely Canobbio in Ticino, Switzerland (not Cannobio, Italy)
    # Using approximate coordinates for Canobbio, Ticino - user should provide exact coordinates
    home_lat = os.getenv("ADSB_HOME_LAT", "46.0359")
    home_lon = os.getenv("ADSB_HOME_LON", "8.9661")
    home_lat_str = ""
    home_lon_str = ""
    if home_lat and home_lon:
        try:
            home_lat_float = float(home_lat)
            home_lon_float = float(home_lon)
            home_lat_str = str(home_lat_float)
            home_lon_str = str(home_lon_float)
            # Use DivIcon for custom "H" icon
            from folium import DivIcon
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
                className='home-marker'  # Important: allows JavaScript to identify and preserve this marker
            )
            folium.Marker(
                location=[home_lat_float, home_lon_float],
                popup=folium.Popup("<b>Home Position</b>", max_width=200),
                tooltip="Home",
                icon=home_icon,
            ).add_to(m)
        except (ValueError, TypeError):
            pass  # Skip if coordinates are invalid
    
    # Determine which aircraft are currently visible (have recent positions)
    # If current_icaos is provided, use it; otherwise determine from timestamps
    if current_icaos is None:
        current_icaos = set()
        from datetime import datetime, timezone
        try:
            current_time = datetime.now(timezone.utc)
            for pos in positions:
                if pos.get("timestamp_utc"):
                    try:
                        pos_time = datetime.fromisoformat(pos["timestamp_utc"].replace('Z', '+00:00'))
                        # If position is within last 2 minutes, consider it current
                        if (current_time - pos_time).total_seconds() < 120:
                            current_icaos.add(pos["icao"])
                    except:
                        pass
        except:
            # Fallback: if we can't determine, show markers for all
            current_icaos = set(p["icao"] for p in positions)
    
    # Group positions by ICAO for trajectories
    
    if len(positions) > 0:
        # Group all positions by ICAO
        icao_groups = {}
        for pos in positions:
            icao = pos["icao"]
            if icao not in icao_groups:
                icao_groups[icao] = []
            icao_groups[icao].append(pos)
        
        for idx, (icao, pos_list) in enumerate(icao_groups.items()):
            # Sort by timestamp if available
            try:
                pos_list_sorted = sorted(
                    pos_list,
                    key=lambda p: p.get("timestamp_utc", ""),
                    reverse=True
                )
            except:
                pos_list_sorted = pos_list
            
            # Latest position
            latest = pos_list_sorted[0]
            
            # Get color based on latest altitude
            marker_color = get_altitude_color(latest.get("altitude_ft"))
            
            # Only show marker for currently visible aircraft
            # But always draw trajectory lines for all aircraft with multiple positions
            is_current = icao in current_icaos if current_icaos else True
            
            # NOTE: Markers for current aircraft are created dynamically by JavaScript
            # to avoid duplicates and allow real-time updates. Only trajectory lines
            # are created here in Python.
            
            # Always draw trajectory if we have multiple positions (for both current and historical aircraft)
            # Sort by timestamp for proper trajectory order
            try:
                pos_list_sorted_by_time = sorted(
                    pos_list,
                    key=lambda p: p.get("timestamp_utc", ""),
                    reverse=False  # Oldest first for trajectory
                )
            except:
                pos_list_sorted_by_time = pos_list
            
            # Draw trajectory line connecting all historical positions
            if len(pos_list_sorted_by_time) > 1:
                trajectory_coords = [[p["lat"], p["lon"]] for p in pos_list_sorted_by_time]
                # Use altitude-based color for all lines, but different opacity
                # Current aircraft: full opacity (0.6), historical: semi-transparent (0.3)
                line_opacity = 0.6 if is_current else 0.3
                folium.PolyLine(
                    trajectory_coords,
                    color=marker_color,  # Always use altitude-based color
                    weight=2,
                    opacity=line_opacity,
                    popup=f"Trajectory: {icao} ({len(pos_list_sorted_by_time)} points)",
                    tooltip=f"{icao} path",
                ).add_to(m)
    else:
        # Single position or single aircraft
        # NOTE: Markers are created dynamically by JavaScript to avoid duplicates
        # Only trajectory lines are created here in Python (if multiple positions exist)
        pass
    
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

    # Calculate headings from trajectory for positions that don't have heading data
    # Group positions by ICAO and sort by timestamp to calculate bearing between consecutive points
    icao_positions = {}
    for p in positions:
        icao = p["icao"]
        if icao not in icao_positions:
            icao_positions[icao] = []
        icao_positions[icao].append(p)

    # For aircraft with only one position, try to load recent historical positions for heading calculation
    history_path = os.getenv("ADSB_CSV_PATH", "adsb_history.csv")
    if os.path.exists(history_path):
        # Load last few positions from history for each ICAO that needs heading calculation
        icaos_needing_history = {icao for icao, pos_list in icao_positions.items()
                                  if len(pos_list) == 1 and pos_list[0].get("heading_deg") is None}
        if icaos_needing_history:
            # Read history file in reverse to get recent positions
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                # Parse from end, collect up to 5 recent positions per ICAO
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
                    # Stop if we have enough for all ICAOs
                    if all(len(v) >= 2 for v in history_positions.values()):
                        break
                # Add historical positions to icao_positions for heading calculation
                for icao, hist_list in history_positions.items():
                    if hist_list:
                        # Reverse to get chronological order
                        hist_list.reverse()
                        # Prepend historical positions (they're older than current)
                        icao_positions[icao] = hist_list + icao_positions[icao]
            except Exception as e:
                print(f"Warning: Could not load history for heading calculation: {e}", file=sys.stderr)

    # Sort each ICAO's positions by timestamp and calculate headings
    for icao, pos_list in icao_positions.items():
        # Sort by timestamp
        pos_list.sort(key=lambda x: x.get("timestamp_utc", ""))

        # Calculate heading from consecutive positions
        for i in range(len(pos_list)):
            if pos_list[i].get("heading_deg") is None:
                # Try to calculate from previous position (where we came from)
                if i > 0:
                    prev_pos = pos_list[i - 1]
                    # Only calculate if positions are different
                    if prev_pos["lat"] != pos_list[i]["lat"] or prev_pos["lon"] != pos_list[i]["lon"]:
                        heading = calculate_bearing(
                            prev_pos["lat"], prev_pos["lon"],
                            pos_list[i]["lat"], pos_list[i]["lon"]
                        )
                        pos_list[i]["heading_deg"] = round(heading, 1)
                # Try to calculate from next position if no previous
                elif i < len(pos_list) - 1:
                    next_pos = pos_list[i + 1]
                    if next_pos["lat"] != pos_list[i]["lat"] or next_pos["lon"] != pos_list[i]["lon"]:
                        heading = calculate_bearing(
                            pos_list[i]["lat"], pos_list[i]["lon"],
                            next_pos["lat"], next_pos["lon"]
                        )
                        pos_list[i]["heading_deg"] = round(heading, 1)

    # Prepare positions data for JavaScript (will be embedded in HTML)
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

    # Aircraft types JSON for icon lookup
    aircraft_types_json = json.dumps(aircraft_types)

    # Load SVG icons from files
    icons_dir = os.path.join(os.path.dirname(__file__), "icons")
    svg_icons = {}
    for icon_name in ["plane", "helicopter", "light", "glider"]:
        svg_path = os.path.join(icons_dir, f"{icon_name}.svg")
        if os.path.exists(svg_path):
            with open(svg_path, "r") as f:
                # Read SVG and add size attributes, escape for JSON
                svg_content = f.read().strip()
                # Add width/height to the svg tag if not present
                if 'width=' not in svg_content:
                    svg_content = svg_content.replace('<svg ', '<svg width="28" height="28" ')
                svg_icons[icon_name] = svg_content
    svg_icons_json = json.dumps(svg_icons)
    
    # Prepare current ICAOs list for JavaScript (aircraft that should show markers)
    current_icaos_list = list(current_icaos) if current_icaos else []
    current_icaos_json = json.dumps(current_icaos_list)
    
    # Also save to JSON file for HTTP fetching
    json_path = os.path.splitext(output_path)[0] + "_data.json"
    json_filename = os.path.basename(json_path)  # Just the filename for JavaScript fetch
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(positions_json)
    
    # Add CSS for aircraft icons
    icon_css = '''
    <style>
    .aircraft-icon {
        background: transparent !important;
        border: none !important;
    }
    .aircraft-icon svg {
        filter: drop-shadow(1px 1px 1px rgba(0,0,0,0.5));
    }
    </style>
    '''
    m.get_root().html.add_child(folium.Element(icon_css))

    # Add title
    title_html = f'''
    <h3 id="map-title" style="position:fixed;
               top:10px;left:50px;width:320px;z-index:1000;
               background-color:white;padding:10px;
               border:2px solid grey;border-radius:5px;
               font-size:14px">
    {title}<br>
    <span id="map-stats" style="font-size:12px">Aircraft: {len(set(p["icao"] for p in positions))} | Positions: {len(positions)}</span><br>
    <span style="font-size:10px;color:#666;">Auto-updating every 1s</span>
    </h3>
    '''
    m.get_root().html.add_child(folium.Element(title_html))
    
    # Add JavaScript for dynamic marker updates
    # Embed positions data directly in HTML to avoid CORS issues with file:// protocol
    update_js = f'''
    <script>
    // Embedded positions data (updated when HTML is regenerated or via HTTP fetch)
    let embeddedPositionsData = {positions_json};

    // Current ICAOs (aircraft that should show markers, not just lines)
    let currentICAOs = new Set({current_icaos_json});

    // Aircraft type information from database (for icon selection)
    let aircraftTypes = {aircraft_types_json};

    // SVG icons loaded from files (pointing UP by default, rotated by heading)
    const SVG_ICONS = {svg_icons_json};

    let markerLayer = null;
    let lineLayer = null;
    let currentMarkers = {{}};
    let currentLines = {{}};
    let homeMarker = null;  // Global reference to home marker - NEVER remove this
    
    // Initialize layers after map loads - run immediately to prevent static markers from showing
    (function initializeMap() {{
        function findMap() {{
            // Find the map object - folium creates a variable with the map div ID
            let mapObj = null;
            
            // Method 1: Find the folium map div and get its variable
            const mapDiv = document.querySelector('.folium-map, [id^="map_"]');
            if (mapDiv && mapDiv.id) {{
                // Folium creates a variable with the same name as the div ID
                const mapVarName = mapDiv.id;
                if (typeof window[mapVarName] !== 'undefined' && window[mapVarName] instanceof L.Map) {{
                    mapObj = window[mapVarName];
                }}
            }}
            
            // Method 2: Check window.map (fallback)
            if (!mapObj && typeof window.map !== 'undefined' && window.map instanceof L.Map) {{
                mapObj = window.map;
            }}
            
            // Method 3: Try to find via Leaflet instances (if available)
            if (!mapObj && typeof L !== 'undefined' && L.Map && L.Map._instances) {{
                const instanceIds = Object.keys(L.Map._instances);
                if (instanceIds.length > 0) {{
                    mapObj = L.Map._instances[instanceIds[0]];
                }}
            }}
            
            // Method 4: Find map div and get from _leaflet_id (if available)
            if (!mapObj && mapDiv) {{
                const leafletId = mapDiv._leaflet_id;
                if (leafletId && L.Map && L.Map._instances && L.Map._instances[leafletId]) {{
                    mapObj = L.Map._instances[leafletId];
                }}
            }}
            
            if (mapObj && mapObj instanceof L.Map) {{
                // AGGRESSIVELY remove ALL existing aircraft markers (but preserve home marker)
                // This ensures we start with a clean slate - only JavaScript will create aircraft markers
                const layersToRemove = [];
                mapObj.eachLayer(function(layer) {{
                    // Remove ALL markers EXCEPT home marker
                    if (layer instanceof L.Marker) {{
                        // Check if this is the home marker by checking icon className
                        const isHomeMarker = layer.options && 
                                           layer.options.icon && 
                                           (layer.options.icon.options || layer.options.icon) &&
                                           (layer.options.icon.options ? layer.options.icon.options.className : layer.options.icon.className) === 'home-marker';
                        if (!isHomeMarker) {{
                            layersToRemove.push(layer);
                        }}
                    }}
                }});
                // Also check for markers in any feature groups before removing (preserve home marker)
                mapObj.eachLayer(function(layer) {{
                    if (layer instanceof L.FeatureGroup || layer instanceof L.LayerGroup) {{
                        layer.eachLayer(function(sublayer) {{
                            if (sublayer instanceof L.Marker) {{
                                const isHomeMarker = sublayer.options && 
                                                   sublayer.options.icon && 
                                                   (sublayer.options.icon.options || sublayer.options.icon) &&
                                                   (sublayer.options.icon.options ? sublayer.options.icon.options.className : sublayer.options.icon.className) === 'home-marker';
                                if (!isHomeMarker) {{
                                    layersToRemove.push(sublayer);
                                }}
                            }}
                        }});
                    }}
                }});
                
                // Remove all collected markers (home marker is excluded)
                // CRITICAL: Never remove homeMarker - it's stored globally and must always be visible
                layersToRemove.forEach(function(layer) {{
                    try {{
                        // Double-check: never remove the home marker
                        if (layer === homeMarker) {{
                            console.log('WARNING: Attempted to remove home marker - skipping!');
                            return;
                        }}
                        if (layer._map) {{
                            layer._map.removeLayer(layer);
                        }} else {{
                            mapObj.removeLayer(layer);
                        }}
                    }} catch(e) {{
                        // Ignore errors if layer already removed
                    }}
                }});
                
                // Create feature groups for markers and lines
                markerLayer = L.featureGroup();
                lineLayer = L.featureGroup();
                mapObj.addLayer(markerLayer);
                mapObj.addLayer(lineLayer);
                
                // ALWAYS add home position marker - this is CRITICAL and must NEVER be removed
                const homeLat = '{home_lat_str}';
                const homeLon = '{home_lon_str}';
                console.log('Home position:', homeLat, homeLon);
                if (homeLat && homeLon && homeLat !== '' && homeLon !== '') {{
                    try {{
                        const lat = parseFloat(homeLat);
                        const lon = parseFloat(homeLon);
                        console.log('Parsed home coordinates:', lat, lon);
                        if (!isNaN(lat) && !isNaN(lon)) {{
                            // Remove existing home marker if it exists
                            if (homeMarker && mapObj.hasLayer(homeMarker)) {{
                                mapObj.removeLayer(homeMarker);
                            }}
                            
                            const homeIcon = L.divIcon({{
                                className: 'home-marker',
                                html: '<div style="background-color: red; border: 2px solid white; border-radius: 50%; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">H</div>',
                                iconSize: [30, 30],
                                iconAnchor: [15, 15]
                            }});
                            homeMarker = L.marker([lat, lon], {{
                                icon: homeIcon
                            }}).bindPopup('<b>Home Position<br>Cannobio, Ticino</b>');
                            mapObj.addLayer(homeMarker);
                            console.log('HOME MARKER ADDED at:', lat, lon);
                        }} else {{
                            console.log('Invalid home coordinates:', lat, lon);
                        }}
                    }} catch(e) {{
                        console.log('Could not add home marker:', e);
                    }}
                }} else {{
                    console.log('Home coordinates not provided');
                }}
                
                // Initial render
                updateMarkers(embeddedPositionsData);
                
                // Start checking for updates
                startAutoUpdate();
            }} else {{
                console.log('Map not found, retrying...');
                setTimeout(findMap, 100);
            }}
        }}
        
        // Wait for window.onload to ensure Folium's map script has executed
        // This is more reliable than DOMContentLoaded since Folium adds its map script at end of body
        if (document.readyState === 'complete') {{
            // Page already loaded, find map immediately
            findMap();
        }} else {{
            // Wait for full page load including all scripts
            window.addEventListener('load', findMap);
        }}
    }})();
    
    function formatTimeAgo(timestamp_utc) {{
        // Convert ISO timestamp to "now" or "X seconds/minutes ago" format
        if (!timestamp_utc) return '';
        try {{
            const posTime = new Date(timestamp_utc);
            const now = new Date();
            const diffMs = now - posTime;
            const diffSec = Math.floor(diffMs / 1000);

            if (diffSec < 5) return 'now';
            if (diffSec < 60) return `${{diffSec}} seconds ago`;

            const diffMin = Math.floor(diffSec / 60);
            if (diffMin === 1) return '1 minute ago';
            if (diffMin < 60) return `${{diffMin}} minutes ago`;

            const diffHr = Math.floor(diffMin / 60);
            if (diffHr === 1) return '1 hour ago';
            return `${{diffHr}} hours ago`;
        }} catch(e) {{
            return timestamp_utc;
        }}
    }}

    function getAltitudeColor(altitude_ft) {{
        // Returns HEX color for SVG fill based on altitude
        if (altitude_ft === null || altitude_ft === undefined) return '#808080';  // gray

        const colorStops = [
            [0, '#FF8C00'],      // 0ft - orange
            [4000, '#FFD700'],   // 4000ft - gold/yellow
            [8000, '#32CD32'],   // 8000ft - lime green
            [20000, '#00CED1'], // 20000ft - dark turquoise
            [30000, '#1E90FF'],  // 30000ft - dodger blue
            [40000, '#9932CC']   // 40000ft - dark orchid/purple
        ];

        if (altitude_ft <= colorStops[0][0]) return colorStops[0][1];
        if (altitude_ft >= colorStops[colorStops.length - 1][0]) return colorStops[colorStops.length - 1][1];

        for (let i = 0; i < colorStops.length - 1; i++) {{
            if (altitude_ft >= colorStops[i][0] && altitude_ft <= colorStops[i + 1][0]) {{
                const ratio = (altitude_ft - colorStops[i][0]) / (colorStops[i + 1][0] - colorStops[i][0]);
                return ratio < 0.5 ? colorStops[i][1] : colorStops[i + 1][1];
            }}
        }}
        return '#808080';
    }}

    function getAircraftIconType(icao) {{
        // Get icon type from aircraft database, default to 'plane'
        if (aircraftTypes[icao] && aircraftTypes[icao].icon) {{
            return aircraftTypes[icao].icon;
        }}
        return 'plane';
    }}

    function getAircraftInfo(icao) {{
        // Get full aircraft info for popup
        return aircraftTypes[icao] || null;
    }}

    function createSvgIcon(icao, altitude_ft, heading_deg) {{
        // Create a rotatable SVG icon for the aircraft
        const iconType = getAircraftIconType(icao);
        const color = getAltitudeColor(altitude_ft);
        const rotation = heading_deg !== null && heading_deg !== undefined ? heading_deg : 0;

        // Get the SVG template and replace color placeholder
        let svgTemplate = SVG_ICONS[iconType] || SVG_ICONS['plane'];
        let svg = svgTemplate.replace(/\{{COLOR\}}/g, color);

        // Create a div with the rotated SVG
        const html = `<div style="transform: rotate(${{rotation}}deg); transform-origin: center center;">
            ${{svg}}
        </div>`;

        return L.divIcon({{
            html: html,
            className: 'aircraft-icon',
            iconSize: [28, 28],
            iconAnchor: [14, 14],  // Center of the icon
            popupAnchor: [0, -14]
        }});
    }}

    function startAutoUpdate() {{
        // Check if we're being served via HTTP (not file://)
        const isHttp = window.location.protocol === 'http:' || window.location.protocol === 'https:';
        
        if (isHttp) {{
            // HTTP mode: fetch JSON data file
            updateMapData();
            setInterval(updateMapData, 1000);
        }} else {{
            // file:// mode: use embedded data (will update when HTML is regenerated)
            // Update markers with embedded data every second
            setInterval(function() {{
                updateMarkers(embeddedPositionsData);
            }}, 1000);
        }}
    }}
    
    function updateMapData() {{
        // Fetch JSON data file (works when served via HTTP)
        fetch('{json_filename}?t=' + new Date().getTime())
            .then(response => response.json())
            .then(data => {{
                embeddedPositionsData = data; // Update embedded data
                
                // IMPORTANT: currentICAOs should ONLY come from adsb_current.csv (embedded set)
                // Do NOT recalculate from timestamps - this ensures aircraft in adsb_current.csv
                // always show markers, regardless of timestamp age
                // The embedded currentICAOs set is the source of truth
                
                updateMarkers(data);
            }})
            .catch(error => {{
                console.log('Update failed:', error);
            }});
    }}
    
    function updateMarkers(positions) {{
        if (!markerLayer || !lineLayer) return;
        
        // CRITICAL: ENSURE HOME MARKER IS ALWAYS PRESENT - CHECK FIRST, BEFORE ANYTHING ELSE
        const mapObj = markerLayer._map;
        if (mapObj) {{
            if (!homeMarker) {{
                // Home marker doesn't exist, create it
                const homeLat = '{home_lat_str}';
                const homeLon = '{home_lon_str}';
                if (homeLat && homeLon && homeLat !== '' && homeLon !== '') {{
                    try {{
                        const lat = parseFloat(homeLat);
                        const lon = parseFloat(homeLon);
                        if (!isNaN(lat) && !isNaN(lon)) {{
                            const homeIcon = L.divIcon({{
                                className: 'home-marker',
                                html: '<div style="background-color: red; border: 2px solid white; border-radius: 50%; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">H</div>',
                                iconSize: [30, 30],
                                iconAnchor: [15, 15]
                            }});
                            homeMarker = L.marker([lat, lon], {{
                                icon: homeIcon
                            }}).bindPopup('<b>Home Position<br>Cannobio, Ticino</b>');
                            mapObj.addLayer(homeMarker);
                            console.log('HOME MARKER RE-CREATED at:', lat, lon);
                        }}
                    }} catch(e) {{
                        console.log('Could not create home marker:', e);
                    }}
                }}
            }} else if (!mapObj.hasLayer(homeMarker)) {{
                // Home marker exists but not on map, re-add it
                console.log('Home marker missing from map, re-adding it!');
                mapObj.addLayer(homeMarker);
            }}
        }}
        
        console.log('=== updateMarkers called with', positions.length, 'positions ===');
        console.log('currentICAOs (from adsb_current.csv):', Array.from(currentICAOs));
        console.log('currentICAOs size:', currentICAOs.size);
        console.log('currentICAOs.has(4405EA):', currentICAOs.has('4405EA'));
        console.log('currentICAOs.has(4CA88C):', currentICAOs.has('4CA88C'));
        
        // Group by ICAO
        const icaoGroups = {{}};
        positions.forEach(pos => {{
            if (!icaoGroups[pos.icao]) {{
                icaoGroups[pos.icao] = [];
            }}
            icaoGroups[pos.icao].push(pos);
        }});
        
        console.log('ICAO groups in data:', Object.keys(icaoGroups));
        console.log('ICAOs that should have markers:', Array.from(currentICAOs).filter(icao => icaoGroups[icao]));
        
        // Update stats
        const statsEl = document.getElementById('map-stats');
        if (statsEl) {{
            statsEl.textContent = `Aircraft: ${{Object.keys(icaoGroups).length}} | Positions: ${{positions.length}} | Current: ${{currentICAOs.size}}`;
        }}
        
        // CRITICAL: Remove markers for aircraft that are NOT in currentICAOs (adsb_current.csv)
        // This ensures only aircraft in adsb_current.csv have markers
        // BUT: Never touch the home marker!
        Object.keys(currentMarkers).forEach(icao => {{
            if (!currentICAOs.has(icao)) {{
                console.log('Removing marker for ICAO not in adsb_current.csv:', icao);
                const marker = currentMarkers[icao];
                // Double-check: never remove home marker
                if (marker !== homeMarker) {{
                    markerLayer.removeLayer(marker);
                    delete currentMarkers[icao];
                }} else {{
                    console.log('WARNING: Attempted to remove home marker - preserving it!');
                }}
            }}
        }});
        
        // Remove all lines and recreate them
        lineLayer.clearLayers();
        currentLines = {{}};
        
        // Process each aircraft
        Object.keys(icaoGroups).forEach(icao => {{
            const posList = icaoGroups[icao];
            // Sort by timestamp
            posList.sort((a, b) => {{
                return (a.timestamp_utc || '').localeCompare(b.timestamp_utc || '');
            }});
            
            const latest = posList[posList.length - 1];
            const color = getAltitudeColor(latest.altitude_ft);
            
            // Only show marker for aircraft in adsb_current.csv (currentICAOs set)
            const isCurrent = currentICAOs.has(icao);
            
            console.log('ICAO:', icao, 'isCurrent (in adsb_current.csv):', isCurrent, 'currentICAOs.has:', currentICAOs.has(icao));
            
            if (isCurrent) {{
                // This aircraft is in adsb_current.csv, so it should have a marker
                console.log('*** PROCESSING CURRENT AIRCRAFT:', icao, 'at', latest.lat, latest.lon, 'altitude:', latest.altitude_ft);

                // Build popup text with aircraft info from database
                const acInfo = getAircraftInfo(icao);
                let popupText = `<b>ICAO:</b> ${{latest.icao}}<br>`;
                if (acInfo && acInfo.registration) popupText += `<b>Reg:</b> ${{acInfo.registration}}<br>`;
                if (acInfo && acInfo.type) popupText += `<b>Type:</b> ${{acInfo.type}}<br>`;
                if (acInfo && acInfo.model) popupText += `<b>Model:</b> ${{acInfo.model}}<br>`;
                if (latest.flight) popupText += `<b>Flight:</b> ${{latest.flight}}<br>`;
                if (latest.altitude_ft) popupText += `<b>Altitude:</b> ${{latest.altitude_ft.toLocaleString()}} ft<br>`;
                if (latest.speed_kts) popupText += `<b>Speed:</b> ${{Math.round(latest.speed_kts)}} kts<br>`;
                if (latest.heading_deg !== null && latest.heading_deg !== undefined) popupText += `<b>Heading:</b> ${{Math.round(latest.heading_deg)}}°<br>`;
                if (latest.squawk) popupText += `<b>Squawk:</b> ${{latest.squawk}}<br>`;
                if (latest.timestamp_utc) popupText += `<b>Spotted:</b> ${{formatTimeAgo(latest.timestamp_utc)}}`;

                // Update existing marker or create new one
                if (currentMarkers[icao]) {{
                    console.log('Updating existing marker for:', icao);
                    // Update existing marker position and popup
                    currentMarkers[icao].setLatLng([latest.lat, latest.lon]);
                    currentMarkers[icao].setPopupContent(popupText);

                    // Update SVG icon with new heading/altitude
                    const newIcon = createSvgIcon(icao, latest.altitude_ft, latest.heading_deg);
                    currentMarkers[icao].setIcon(newIcon);
                    console.log('Marker updated for:', icao);
                }} else {{
                    // Create new marker for aircraft in adsb_current.csv
                    console.log('*** CREATING NEW MARKER for ICAO:', icao, 'at', latest.lat, latest.lon);

                    try {{
                        const svgIcon = createSvgIcon(icao, latest.altitude_ft, latest.heading_deg);
                        const marker = L.marker([latest.lat, latest.lon], {{
                            icon: svgIcon
                        }}).bindPopup(popupText);
                        markerLayer.addLayer(marker);
                        currentMarkers[icao] = marker;
                        console.log('*** AIRCRAFT MARKER SUCCESSFULLY CREATED for ICAO:', icao, 'type:', getAircraftIconType(icao));
                    }} catch(e) {{
                        console.error('ERROR creating marker for', icao, ':', e);
                    }}
                }}
            }}
            
            // Draw trajectory line if multiple positions (for ALL aircraft, current and historical)
            if (posList.length > 1) {{
                const coords = posList.map(p => [p.lat, p.lon]);
                // Use altitude-based color for all lines, but different opacity
                // Current aircraft: full opacity (0.6), historical: semi-transparent (0.3)
                const lineOpacity = isCurrent ? 0.6 : 0.3;
                const line = L.polyline(coords, {{
                    color: color,  // Always use altitude-based color
                    weight: 2,
                    opacity: lineOpacity
                }}).bindPopup(`Trajectory: ${{icao}} (${{posList.length}} points)`);
                lineLayer.addLayer(line);
                currentLines[icao] = line;
            }}
        }});
        
        // FINAL CHECK: Ensure home marker is still on map after all updates
        if (homeMarker && mapObj && !mapObj.hasLayer(homeMarker)) {{
            console.log('Home marker lost during update, re-adding it!');
            mapObj.addLayer(homeMarker);
        }}
        
        console.log('updateMarkers complete. Total markers on map:', Object.keys(currentMarkers).length, 'ICAOs:', Object.keys(currentMarkers));
    }}
    </script>
    '''
    m.get_root().html.add_child(folium.Element(update_js))
    
    # Save map
    m.save(output_path)
    print(f"Map saved to: {output_path}")
    print(f"Open it in your browser. The map file updates automatically without page reload.")


def main():
    parser = argparse.ArgumentParser(
        description="Plot ADS-B aircraft positions on an interactive map",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Plot current positions with historical trajectories
  python3 plot_map.py

  # Plot all historical positions
  python3 plot_map.py --historical

  # Plot trajectory for specific aircraft
  python3 plot_map.py --icao 3C5EF2

  # Current positions only (no historical trajectories)
  python3 plot_map.py --no-history

  # Custom CSV file
  python3 plot_map.py --csv custom_positions.csv
        """
    )
    
    parser.add_argument(
        "--csv",
        default=None,
        help="Path to CSV file (default: adsb_current.csv or adsb_history.csv)"
    )
    parser.add_argument(
        "--historical",
        action="store_true",
        help="Use historical CSV file (adsb_history.csv) instead of current"
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Don't load historical data for trajectories (current positions only)"
    )
    parser.add_argument(
        "--icao",
        default=None,
        help="Filter to specific ICAO hex code"
    )
    parser.add_argument(
        "--output",
        default="adsb_map.html",
        help="Output HTML file path (default: adsb_map.html)"
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Map title (default: auto-generated)"
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=0,
        help="Auto-refresh interval in seconds (default: 0 = disabled, map updates via file regeneration)"
    )
    parser.add_argument(
        "--home-lat",
        type=float,
        default=None,
        help="Home position latitude (or set ADSB_HOME_LAT env var)"
    )
    parser.add_argument(
        "--home-lon",
        type=float,
        default=None,
        help="Home position longitude (or set ADSB_HOME_LON env var)"
    )
    
    args = parser.parse_args()
    
    # Determine CSV file
    if args.csv:
        csv_path = args.csv
        # Still load historical data for trajectories unless --no-history is set
        if not args.no_history:
            historical_csv_path = os.getenv("ADSB_CSV_PATH", "adsb_history.csv")
        else:
            historical_csv_path = None
    elif args.historical:
        csv_path = os.getenv("ADSB_CSV_PATH", "adsb_history.csv")
        historical_csv_path = None
    else:
        csv_path = os.getenv("ADSB_CURRENT_CSV_PATH", "adsb_current.csv")
        # Load historical data for trajectories unless --no-history is set
        if not args.no_history:
            historical_csv_path = os.getenv("ADSB_CSV_PATH", "adsb_history.csv")
        else:
            historical_csv_path = None
    
    # Read positions
    print(f"Reading positions from: {csv_path}")
    positions = read_csv_positions(csv_path)
    
    # If we have current positions and historical file exists, merge trajectories
    if historical_csv_path and os.path.exists(historical_csv_path) and not args.historical:
        print(f"Loading historical trajectories from: {historical_csv_path}")
        historical_positions = read_csv_positions(historical_csv_path)
        
        if historical_positions:
            # Get ICAOs from current positions
            current_icaos = set(p["icao"] for p in positions)
            
            # Group historical positions by ICAO to find aircraft with trajectories
            historical_by_icao = {}
            for hist_pos in historical_positions:
                icao = hist_pos["icao"]
                if icao not in historical_by_icao:
                    historical_by_icao[icao] = []
                historical_by_icao[icao].append(hist_pos)
            
            # Determine whether to show all historical trajectories or only current aircraft
            # When --csv is used (current map): only show trajectories for current aircraft
            # When no --csv (main map): show ALL historical trajectories
            show_all_history = not args.csv

            for hist_pos in historical_positions:
                if show_all_history:
                    # Main map: add ALL historical positions
                    if hist_pos["icao"] in current_icaos:
                        # For current aircraft, avoid duplicates
                        is_duplicate = any(
                            p["icao"] == hist_pos["icao"] and
                            abs(p["lat"] - hist_pos["lat"]) < 0.0001 and
                            abs(p["lon"] - hist_pos["lon"]) < 0.0001
                            for p in positions
                        )
                        if not is_duplicate:
                            positions.append(hist_pos)
                    else:
                        # For non-current aircraft, add all positions
                        positions.append(hist_pos)
                else:
                    # Current map: only add historical positions for current aircraft
                    if hist_pos["icao"] in current_icaos:
                        is_duplicate = any(
                            p["icao"] == hist_pos["icao"] and
                            abs(p["lat"] - hist_pos["lat"]) < 0.0001 and
                            abs(p["lon"] - hist_pos["lon"]) < 0.0001
                            for p in positions
                        )
                        if not is_duplicate:
                            positions.append(hist_pos)
            
            print(f"Loaded {len(historical_positions)} historical positions for {len(historical_by_icao)} aircraft")
    
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
    
    # Determine current ICAOs (aircraft with recent positions) for marker display
    current_icaos_for_map = set()
    if not args.historical:
        # Read current CSV to get current ICAOs
        current_csv_path = os.getenv("ADSB_CURRENT_CSV_PATH", "adsb_current.csv")
        if os.path.exists(current_csv_path):
            current_only = read_csv_positions(current_csv_path)
            current_icaos_for_map = set(p["icao"] for p in current_only)
            print(f"Current ICAOs from {current_csv_path}: {current_icaos_for_map}")
            
            # CRITICAL: Ensure positions from adsb_current.csv are in the positions list
            # Add current positions if they're not already there (by ICAO and coordinates)
            # This ensures markers can be created for aircraft in adsb_current.csv
            current_positions_by_icao = {p["icao"]: p for p in current_only}
            for icao, current_pos in current_positions_by_icao.items():
                # Check if this position is already in the positions list
                is_duplicate = any(
                    p["icao"] == icao and 
                    abs(p["lat"] - current_pos["lat"]) < 0.0001 and
                    abs(p["lon"] - current_pos["lon"]) < 0.0001
                    for p in positions
                )
                if not is_duplicate:
                    # Add the current position to ensure it's in the embedded data
                    positions.insert(0, current_pos)  # Insert at beginning to prioritize current positions
                    print(f"Added current position for ICAO {icao} to embedded data: lat={current_pos['lat']}, lon={current_pos['lon']}")
                else:
                    print(f"Current position for ICAO {icao} already in positions list")
    
    # Set home position from args or environment variables
    if args.home_lat and args.home_lon:
        os.environ["ADSB_HOME_LAT"] = str(args.home_lat)
        os.environ["ADSB_HOME_LON"] = str(args.home_lon)
    
    print(f"Total positions for map: {len(positions)}, ICAOs: {len(set(p['icao'] for p in positions))}")
    print(f"Current ICAOs for markers: {current_icaos_for_map}")
    
    # Create map (will show markers for current aircraft, lines for all)
    create_map(positions, args.output, title, args.refresh, current_icaos_for_map)


if __name__ == "__main__":
    main()

