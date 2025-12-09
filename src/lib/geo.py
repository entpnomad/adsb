"""
Geographic utilities for ADS-B tracker.

Includes:
- Address geocoding (via Nominatim/OpenStreetMap)
- Elevation lookup (via Open-Elevation API)
- Distance calculations (haversine, 3D)
- Bearing calculation
- Home location management
"""

import json
import math
import os
import sys
from typing import Optional
import urllib.request
import urllib.parse

from .config import HOME_CONFIG_FILE


# Cache for home location
_cached_home_location = None


def geocode_address(address: str) -> Optional[dict]:
    """
    Geocode an address using Nominatim (OpenStreetMap).

    Args:
        address: Human-readable address string

    Returns:
        dict with lat, lon, display_name or None if failed
    """
    try:
        encoded_address = urllib.parse.quote(address)
        url = f"https://nominatim.openstreetmap.org/search?q={encoded_address}&format=json&limit=1"

        req = urllib.request.Request(url, headers={
            'User-Agent': 'ADS-B Tracker/1.0 (personal use)'
        })

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data and len(data) > 0:
                result = data[0]
                return {
                    'lat': float(result['lat']),
                    'lon': float(result['lon']),
                    'display_name': result.get('display_name', address)
                }
    except Exception as e:
        print(f"Geocoding failed: {e}", file=sys.stderr)

    return None


def get_elevation(lat: float, lon: float) -> Optional[float]:
    """
    Get elevation for coordinates using Open-Elevation API.

    Uses NASA SRTM (Shuttle Radar Topography Mission) data.

    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees

    Returns:
        Elevation in meters or None if failed
    """
    try:
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"

        req = urllib.request.Request(url, headers={
            'User-Agent': 'ADS-B Tracker/1.0 (personal use)'
        })

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if data and 'results' in data and len(data['results']) > 0:
                return float(data['results'][0]['elevation'])
    except Exception as e:
        print(f"Elevation lookup failed: {e}", file=sys.stderr)

    return None


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the bearing (heading) from point 1 to point 2.

    Args:
        lat1, lon1: Starting point coordinates
        lat2, lon2: Ending point coordinates

    Returns:
        Bearing in degrees (0-360, where 0 is North)
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


def calculate_3d_distance(lat1: float, lon1: float, alt1_m: float,
                          lat2: float, lon2: float, alt2_m: float) -> float:
    """
    Calculate 3D distance between two points accounting for altitude.

    Uses Haversine formula for horizontal distance and Pythagorean
    theorem for the final 3D distance.

    Args:
        lat1, lon1, alt1_m: First point (e.g., home) - altitude in meters
        lat2, lon2, alt2_m: Second point (e.g., aircraft) - altitude in meters

    Returns:
        Distance in kilometers
    """
    # Earth's radius in km
    R = 6371.0

    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    # Haversine formula for horizontal distance
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    horizontal_distance_km = R * c

    # Altitude difference in km
    alt_diff_km = (alt2_m - alt1_m) / 1000.0

    # 3D distance using Pythagorean theorem
    distance_3d_km = math.sqrt(horizontal_distance_km ** 2 + alt_diff_km ** 2)

    return distance_3d_km


def setup_home_location() -> Optional[dict]:
    """
    Interactive setup for home location.
    Prompts user for address, geocodes it, and gets elevation.

    Returns:
        dict with lat, lon, elevation_m, address, or None if cancelled
    """
    print("\n" + "=" * 60)
    print("HOME LOCATION SETUP")
    print("=" * 60)
    print("\nEnter your home address or location name.")
    print("Examples:")
    print("  - 123 Main Street, New York, NY")
    print("  - 10 Downing Street, London, UK")
    print("  - Piazza del Duomo, Milan, Italy")
    print()

    address = input("Enter your location: ").strip()

    if not address:
        print("No address provided, using default location.")
        return None

    print(f"\nGeocoding '{address}'...")
    geo_result = geocode_address(address)

    if not geo_result:
        print("Could not find that location. Please try again with a different address.")
        return None

    lat, lon = geo_result['lat'], geo_result['lon']
    display_name = geo_result['display_name']

    print(f"Found: {display_name}")
    print(f"Coordinates: {lat:.6f}, {lon:.6f}")

    print("\nLooking up elevation...")
    elevation = get_elevation(lat, lon)

    if elevation is not None:
        elevation_ft = elevation * 3.28084
        print(f"Elevation: {elevation:.1f} m ({elevation_ft:.0f} ft)")
    else:
        print("Could not determine elevation, using 0m (sea level)")
        elevation = 0.0

    # Confirm with user
    print()
    confirm = input("Is this correct? (y/n): ").strip().lower()

    if confirm != 'y':
        print("Setup cancelled.")
        return None

    home_config = {
        'address': address,
        'display_name': display_name,
        'lat': lat,
        'lon': lon,
        'elevation_m': elevation,
        'elevation_ft': elevation * 3.28084
    }

    # Save to config file
    save_home_location(home_config)

    return home_config


def save_home_location(config: dict) -> bool:
    """Save home location to config file."""
    try:
        HOME_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HOME_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"\nHome location saved to: {HOME_CONFIG_FILE}")
        return True
    except Exception as e:
        print(f"Warning: Could not save config file: {e}")
        return False


def get_home_location() -> dict:
    """
    Get home location from config file, environment variables, or prompt user.

    Priority:
    1. Environment variables (ADSB_HOME_LAT, ADSB_HOME_LON, ADSB_HOME_ELEVATION_M)
    2. Config file (config/home_location.json)
    3. Interactive setup (if running in terminal)
    4. Default location (Central London)

    Returns:
        dict with lat, lon, elevation_m, elevation_ft, address, display_name
    """
    global _cached_home_location

    # Return cached location if available
    if _cached_home_location:
        return _cached_home_location

    # Check environment variables first
    env_lat = os.getenv("ADSB_HOME_LAT")
    env_lon = os.getenv("ADSB_HOME_LON")
    env_elev = os.getenv("ADSB_HOME_ELEVATION_M")

    if env_lat and env_lon:
        try:
            lat = float(env_lat)
            lon = float(env_lon)
            elev = float(env_elev) if env_elev else 0.0
            _cached_home_location = {
                'lat': lat,
                'lon': lon,
                'elevation_m': elev,
                'elevation_ft': elev * 3.28084,
                'address': 'Environment variables',
                'display_name': f'{lat}, {lon}'
            }
            return _cached_home_location
        except ValueError:
            pass

    # Check config file
    if HOME_CONFIG_FILE.exists():
        try:
            with open(HOME_CONFIG_FILE, 'r') as f:
                config = json.load(f)
                if 'lat' in config and 'lon' in config:
                    _cached_home_location = config
                    print(f"Loaded home location: {config.get('display_name', 'Unknown')}")
                    return _cached_home_location
        except Exception as e:
            print(f"Warning: Could not load config file: {e}", file=sys.stderr)

    # No config found - run interactive setup if running interactively
    if sys.stdin.isatty():
        print("\nNo home location configured.")
        setup = input("Would you like to set up your home location now? (y/n): ").strip().lower()
        if setup == 'y':
            result = setup_home_location()
            if result:
                _cached_home_location = result
                return _cached_home_location

    # Fallback default (Central London - Big Ben)
    print("Using default location (Central London)")
    _cached_home_location = {
        'lat': 51.5007,
        'lon': -0.1246,
        'elevation_m': 5.0,
        'elevation_ft': 16.4,
        'address': 'Default',
        'display_name': 'Central London, UK'
    }
    return _cached_home_location


def set_home_from_address(address: str) -> Optional[dict]:
    """
    Non-interactive home location setup from address string.

    Args:
        address: Address to geocode

    Returns:
        Home config dict or None if failed
    """
    print(f"Geocoding '{address}'...")
    geo_result = geocode_address(address)

    if not geo_result:
        print("Could not find that location.")
        return None

    lat, lon = geo_result['lat'], geo_result['lon']
    display_name = geo_result['display_name']
    print(f"Found: {display_name}")
    print(f"Coordinates: {lat:.6f}, {lon:.6f}")

    print("Looking up elevation...")
    elevation = get_elevation(lat, lon)
    if elevation is None:
        print("Could not determine elevation, using 0m")
        elevation = 0.0
    else:
        print(f"Elevation: {elevation:.1f}m ({elevation * 3.28084:.0f}ft)")

    home_config = {
        'address': address,
        'display_name': display_name,
        'lat': lat,
        'lon': lon,
        'elevation_m': elevation,
        'elevation_ft': elevation * 3.28084
    }

    save_home_location(home_config)
    return home_config
