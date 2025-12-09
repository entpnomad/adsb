#!/usr/bin/env python3
"""
Aircraft database lookup for ADS-B visualization.

Maps ICAO hex codes to aircraft types and determines appropriate icons.
Uses the tar1090 aircraft database (CSV format).

Usage:
    # As a module
    from aircraft_db import get_aircraft_info, get_aircraft_icon

    # As a CLI tool
    python3 aircraft_db.py 4B4437
"""

import csv
import sys
from typing import Dict, Optional

from src.lib.config import AIRCRAFT_DB_FILE

# Aircraft type categories for icon selection (matching SVG filenames in assets/icons/)
ICON_AIRLINER = "plane"
ICON_HELICOPTER = "helicopter"
ICON_GLIDER = "glider"
ICON_LIGHT = "light"
ICON_UNKNOWN = "plane"

# Type designator patterns that indicate aircraft category
# Based on ICAO type designators

HELICOPTER_TYPES = {
    # Airbus Helicopters
    'AS35', 'AS50', 'AS55', 'AS65', 'EC20', 'EC25', 'EC30', 'EC35', 'EC45',
    'EC55', 'EC75', 'EC13', 'EC15', 'EC63', 'EC65', 'H120', 'H125',
    'H130', 'H135', 'H145', 'H155', 'H160', 'H175', 'H215', 'H225',
    # Bell
    'B06', 'B06T', 'B105', 'B204', 'B205', 'B206', 'B209', 'B212', 'B214',
    'B222', 'B230', 'B407', 'B412', 'B429', 'B430', 'B505', 'B525',
    # Robinson
    'R22', 'R44', 'R66',
    # Sikorsky
    'S55', 'S58', 'S61', 'S64', 'S65', 'S70', 'S76', 'S92',
    # Leonardo/AgustaWestland
    'A109', 'A119', 'A139', 'A149', 'A169', 'A189', 'AW09', 'AW10', 'AW13',
    'AW16', 'AW18', 'AW19',
    # MD Helicopters
    'MD52', 'MD60', 'MD90', 'EXPL', 'NOTR',
    # Eurocopter (older designations)
    'BK17', 'BO10', 'GAZL', 'LAMA', 'PUMA', 'SA31', 'SA34', 'SA36', 'SA37',
    # Generic
    'HELI', 'GYRO',
}

GLIDER_TYPES = {
    'GLID', 'GL', 'ASW', 'ASK', 'ASH', 'DG', 'LS', 'SZD', 'PIK', 'PW5',
    'NIMB', 'DISC', 'VENT', 'JANT', 'ARCX', 'DUO', 'ARCS',
    'SLIN', 'GRAB', 'GLAS', 'SPER', 'STEM', 'G102', 'G103', 'G109',
    'ULAC',
}

AIRLINER_TYPES = {
    # Airbus
    'A10', 'A19', 'A20', 'A21', 'A30', 'A31', 'A32', 'A33', 'A34', 'A35',
    'A38', 'A318', 'A319', 'A320', 'A321', 'A330', 'A340', 'A350', 'A380',
    # Boeing
    'B70', 'B71', 'B72', 'B73', 'B74', 'B75', 'B76', 'B77', 'B78',
    'B701', 'B703', 'B712', 'B720', 'B721', 'B722', 'B731', 'B732', 'B733',
    'B734', 'B735', 'B736', 'B737', 'B738', 'B739', 'B741', 'B742', 'B743',
    'B744', 'B748', 'B752', 'B753', 'B762', 'B763', 'B764', 'B772', 'B773',
    'B77L', 'B77W', 'B788', 'B789', 'B78X',
    # Embraer
    'E70', 'E75', 'E90', 'E95', 'E170', 'E175', 'E190', 'E195', 'E290', 'E295',
    # Bombardier
    'CRJ', 'CRJ1', 'CRJ2', 'CRJ7', 'CRJ9', 'CRJX', 'BCS1', 'BCS3',
    # ATR
    'AT43', 'AT45', 'AT72', 'AT75', 'AT76', 'ATR',
    # Other
    'DH8', 'DHC8', 'MD80', 'MD81', 'MD82', 'MD83', 'MD87', 'MD88', 'MD90',
    'DC9', 'DC10', 'MD11', 'L101', 'F100', 'F70', 'BAE1', 'RJ', 'AVRO',
    'AN24', 'AN26', 'IL76', 'IL96', 'TU15', 'TU20', 'TU21', 'TU22',
}

LIGHT_AIRCRAFT_PATTERNS = {
    # Cessna
    'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8',
    'C150', 'C152', 'C162', 'C170', 'C172', 'C175', 'C177', 'C180', 'C182',
    'C185', 'C188', 'C190', 'C195', 'C206', 'C207', 'C208', 'C210', 'C303',
    'C310', 'C336', 'C337', 'C340', 'C401', 'C402', 'C404', 'C411', 'C414',
    'C421', 'C425', 'C441', 'C500', 'C501', 'C510', 'C525', 'C550', 'C560',
    # Piper
    'P28', 'PA18', 'PA22', 'PA23', 'PA24', 'PA27', 'PA28', 'PA30', 'PA31',
    'PA32', 'PA34', 'PA38', 'PA44', 'PA46', 'PA60', 'PAY',
    # Beechcraft
    'B35', 'B36', 'B55', 'B58', 'B60', 'BE17', 'BE18', 'BE19', 'BE20',
    'BE23', 'BE24', 'BE33', 'BE35', 'BE36', 'BE40', 'BE55', 'BE58', 'BE60',
    'BE76', 'BE77', 'BE80', 'BE9', 'BE90', 'BE95', 'BE99',
    # Cirrus
    'SR20', 'SR22', 'SF50',
    # Diamond
    'DA20', 'DA40', 'DA42', 'DA50', 'DA62', 'DV20',
    # Mooney
    'M20',
    # Other
    'AA5', 'DR40', 'PA11', 'J3', 'RV', 'VANS', 'TOBA', 'TB', 'TB20', 'TB21',
    'AQUI', 'SONI', 'RALL', 'ROBIN', 'CAP', 'EXTR',
}


def get_icon_for_type(type_code: str) -> str:
    """
    Determine the appropriate icon based on aircraft type designator.

    Args:
        type_code: ICAO aircraft type designator (e.g., "B738", "R44", "C172")

    Returns:
        Icon name matching SVG filename (plane, helicopter, light, glider)
    """
    if not type_code:
        return ICON_UNKNOWN

    type_upper = type_code.upper().strip()

    # Check helicopters first (most specific)
    for heli_type in HELICOPTER_TYPES:
        if type_upper.startswith(heli_type) or type_upper == heli_type:
            return ICON_HELICOPTER

    # Check gliders
    for glider_type in GLIDER_TYPES:
        if type_upper.startswith(glider_type) or type_upper == glider_type:
            return ICON_GLIDER

    # Check airliners
    for airliner_type in AIRLINER_TYPES:
        if type_upper.startswith(airliner_type) or type_upper == airliner_type:
            return ICON_AIRLINER

    # Check light aircraft
    for light_type in LIGHT_AIRCRAFT_PATTERNS:
        if type_upper.startswith(light_type) or type_upper == light_type:
            return ICON_LIGHT

    # Default to airliner (most common in ADS-B)
    return ICON_UNKNOWN


class AircraftDatabase:
    """Aircraft database for looking up ICAO hex codes."""

    def __init__(self, db_path=None):
        """
        Initialize the aircraft database.

        Args:
            db_path: Path to CSV database file. If None, uses default location.
        """
        self.db_path = db_path or AIRCRAFT_DB_FILE
        self._cache: Dict[str, Dict[str, str]] = {}
        self._loaded = False

    def load(self) -> bool:
        """
        Load the aircraft database from CSV file.

        Returns:
            True if database loaded successfully, False otherwise.
        """
        if self._loaded:
            return True

        if not self.db_path.exists():
            print(f"Aircraft database not found: {self.db_path}")
            return False

        try:
            with open(self.db_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Handle different column naming conventions
                    icao = row.get("icao24") or row.get("icao") or row.get("hex") or ""
                    icao = icao.upper().strip()
                    if icao:
                        self._cache[icao] = {
                            "registration": row.get("registration") or row.get("reg") or "",
                            "type": row.get("typecode") or row.get("type") or row.get("aircraft_type") or "",
                            "manufacturer": row.get("manufacturername") or row.get("manufacturer") or "",
                            "model": row.get("model") or "",
                            "owner": row.get("owner") or row.get("operator") or "",
                        }

            self._loaded = True
            print(f"Loaded {len(self._cache)} aircraft from database")
            return True

        except Exception as e:
            print(f"Error loading aircraft database: {e}")
            return False

    def lookup(self, icao_hex: str) -> Optional[Dict[str, str]]:
        """
        Look up aircraft by ICAO hex code.

        Args:
            icao_hex: 6-character ICAO hex code (e.g., "4B4437")

        Returns:
            Dict with aircraft info, or None if not found.
        """
        if not self._loaded:
            self.load()

        return self._cache.get(icao_hex.upper().strip())

    def get_icon(self, icao_hex: str) -> str:
        """
        Get the appropriate icon for an aircraft.

        Args:
            icao_hex: 6-character ICAO hex code

        Returns:
            Icon name (plane, helicopter, light, glider)
        """
        info = self.lookup(icao_hex)

        if info:
            type_code = info.get("type", "").upper()
            return get_icon_for_type(type_code)

        return ICON_UNKNOWN


# Global database instance (lazy-loaded singleton)
_db: Optional[AircraftDatabase] = None


def get_database() -> AircraftDatabase:
    """Get the global aircraft database instance."""
    global _db
    if _db is None:
        _db = AircraftDatabase()
    return _db


def get_aircraft_icon(icao_hex: str) -> str:
    """
    Get the appropriate icon for an aircraft by ICAO hex code.

    This is the main function to use from other modules.

    Args:
        icao_hex: 6-character ICAO hex code

    Returns:
        Icon name (plane, helicopter, light, glider)
    """
    db = get_database()
    return db.get_icon(icao_hex)


def get_aircraft_info(icao_hex: str) -> Optional[Dict[str, str]]:
    """
    Get full aircraft information by ICAO hex code.

    Args:
        icao_hex: 6-character ICAO hex code

    Returns:
        Dict with registration, type, manufacturer, model, owner
        or None if not found
    """
    db = get_database()
    return db.lookup(icao_hex)


if __name__ == "__main__":
    # CLI mode - lookup aircraft by ICAO
    if len(sys.argv) > 1:
        icao = sys.argv[1]
        info = get_aircraft_info(icao)
        icon = get_aircraft_icon(icao)

        print(f"ICAO: {icao}")
        print(f"Icon: {icon}")
        if info:
            print(f"Registration: {info.get('registration', 'N/A')}")
            print(f"Type: {info.get('type', 'N/A')}")
            print(f"Manufacturer: {info.get('manufacturer', 'N/A')}")
            print(f"Model: {info.get('model', 'N/A')}")
            print(f"Owner: {info.get('owner', 'N/A')}")
        else:
            print("Not found in database")
    else:
        print("Usage: python3 aircraft_db.py <ICAO_HEX>")
        print("Example: python3 aircraft_db.py 4B4437")
