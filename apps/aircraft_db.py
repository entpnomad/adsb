#!/usr/bin/env python3
"""
Aircraft database lookup for ADS-B visualization.

Maps ICAO hex codes to aircraft types and determines appropriate icons.
Uses the tar1090 aircraft database (CSV format) and icon mappings.

Usage:
    # As a module
    from aircraft_db import get_aircraft_info, get_aircraft_icon

    # As a CLI tool
    python -m apps.aircraft_db 4B4437
"""

import csv
import sys
from typing import Any, Dict, Optional

# Ensure project root is on sys.path
try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401

from adsb.config import AIRCRAFT_DB_FILE

# Default icon for unknown aircraft
ICON_UNKNOWN = "unknown"

# Type designator to icon mapping - from tar1090 markers.js
# Maps ICAO type designators (e.g., "B738") directly to icon names
TYPE_DESIGNATOR_ICONS = {
    'A10': 'a10',
    'A124': 'b707',
    'A139': 's61',
    'A148': 'airliner',
    'A149': 's61',
    'A169': 's61',
    'A189': 's61',
    'A19N': 'a319',
    'A20J': 'glider',
    'A20N': 'a320',
    'A21N': 'a321',
    'A225': 'a225',
    'A3': 'hi_perf',
    'A306': 'heavy_2e',
    'A318': 'a319',
    'A319': 'a319',
    'A320': 'a320',
    'A321': 'a321',
    'A32E': 'glider',
    'A32P': 'glider',
    'A330': 'a332',
    'A332': 'a332',
    'A333': 'a332',
    'A337': 'beluga',
    'A338': 'a332',
    'A339': 'a332',
    'A33E': 'glider',
    'A33P': 'glider',
    'A34E': 'glider',
    'A359': 'a359',
    'A35K': 'a359',
    'A37': 'hi_perf',
    'A388': 'a380',
    'A3ST': 'beluga',
    'A4': 'md_a4',
    'A400': 'a400',
    'A6': 'hi_perf',
    'A700': 'hi_perf',
    'AJET': 'alpha_jet',
    'ALO2': 'gazelle',
    'ALO3': 'gazelle',
    'ARCE': 'glider',
    'ARCP': 'glider',
    'AS14': 'glider',
    'AS16': 'glider',
    'AS20': 'glider',
    'AS21': 'glider',
    'AS22': 'glider',
    'AS24': 'glider',
    'AS25': 'glider',
    'AS26': 'glider',
    'AS28': 'glider',
    'AS29': 'glider',
    'AS30': 'glider',
    'AS31': 'glider',
    'AS32': 'puma',
    'AS3B': 'puma',
    'AS50': 'gazelle',
    'AS55': 'gazelle',
    'AS65': 'dauphin',
    'ASTR': 'jet_nonswept',
    'AT3': 'hi_perf',
    'B1': 'b1b_lancer',
    'B17': 'lancaster',
    'B29': 'lancaster',
    'B37M': 'b737',
    'B38M': 'b738',
    'B39M': 'b739',
    'B3XM': 'b739',
    'B461': 'b707',
    'B462': 'b707',
    'B463': 'b707',
    'B52': 'b52',
    'B609': 'v22_slow',
    'B609F': 'v22_fast',
    'B701': 'b707',
    'B703': 'b707',
    'B712': 'jet_swept',
    'B721': 'jet_swept',
    'B722': 'jet_swept',
    'B731': 'b737',
    'B732': 'b737',
    'B733': 'b737',
    'B734': 'b737',
    'B735': 'b737',
    'B736': 'b737',
    'B737': 'b737',
    'B738': 'b738',
    'B739': 'b739',
    'B741': 'heavy_4e',
    'B742': 'heavy_4e',
    'B743': 'heavy_4e',
    'B744': 'heavy_4e',
    'B748': 'heavy_4e',
    'B74D': 'heavy_4e',
    'B74R': 'heavy_4e',
    'B74S': 'heavy_4e',
    'B752': 'heavy_2e',
    'B753': 'heavy_2e',
    'B772': 'heavy_2e',
    'B773': 'heavy_2e',
    'B77L': 'heavy_2e',
    'B77W': 'heavy_2e',
    'BALL': 'balloon',
    'BCS1': 'airliner',
    'BCS3': 'airliner',
    'BE20': 'twin_large',
    'BE40': 'jet_nonswept',
    'BLCF': 'heavy_4e',
    'BSCA': 'heavy_4e',
    'C130': 'c130',
    'C17': 'c17',
    'C2': 'c2',
    'C25A': 'jet_nonswept',
    'C25B': 'jet_nonswept',
    'C25C': 'jet_nonswept',
    'C30J': 'c130',
    'C501': 'jet_nonswept',
    'C510': 'jet_nonswept',
    'C525': 'jet_nonswept',
    'C550': 'jet_nonswept',
    'C560': 'jet_nonswept',
    'C56X': 'jet_nonswept',
    'C5M': 'c5',
    'C650': 'jet_nonswept',
    'C680': 'jet_swept',
    'C68A': 'jet_swept',
    'C750': 'jet_swept',
    'C97': 'super_guppy',
    'CKUO': 'hi_perf',
    'CL30': 'jet_swept',
    'CL35': 'jet_swept',
    'CL60': 'jet_swept',
    'CRJ1': 'jet_swept',
    'CRJ2': 'jet_swept',
    'CRJ7': 'jet_swept',
    'CRJ9': 'jet_swept',
    'CRJX': 'jet_swept',
    'DC10': 'md11',
    'DC91': 'jet_swept',
    'DC92': 'jet_swept',
    'DC93': 'jet_swept',
    'DC94': 'jet_swept',
    'DC95': 'jet_swept',
    'DG1T': 'glider',
    'DG80': 'glider',
    'DISC': 'glider',
    'DLTA': 'verhees',
    'DRON': 'uav',
    'DUOD': 'glider',
    'E135': 'jet_swept',
    'E145': 'jet_swept',
    'E170': 'airliner',
    'E190': 'airliner',
    'E195': 'airliner',
    'E2': 'c2',
    'E290': 'airliner',
    'E295': 'airliner',
    'E35L': 'jet_swept',
    'E390': 'e390',
    'E3CF': 'e3awacs',
    'E3TF': 'e3awacs',
    'E45X': 'jet_swept',
    'E50P': 'jet_nonswept',
    'E55P': 'jet_nonswept',
    'E737': 'e737',
    'E75L': 'airliner',
    'E75S': 'airliner',
    'EA50': 'jet_nonswept',
    'EC25': 's61',
    'EC55': 's61',
    'EC75': 's61',
    'EH10': 's61',
    'EMER': 'ground_emergency',
    'EUFI': 'typhoon',
    'F1': 'hi_perf',
    'F100': 'jet_swept',
    'F104': 't38',
    'F111': 'hi_perf',
    'F117': 'hi_perf',
    'F14': 'hi_perf',
    'F15': 'md_f15',
    'F16': 'hi_perf',
    'F18': 'f18',
    'F18H': 'f18',
    'F18S': 'f18',
    'F22': 'f35',
    'F22A': 'f35',
    'F28': 'jet_swept',
    'F2TH': 'jet_swept',
    'F35': 'f35',
    'F4': 'hi_perf',
    'F5': 'f5_tiger',
    'F70': 'jet_swept',
    'F900': 'jet_swept',
    'FA10': 'jet_nonswept',
    'FA20': 'jet_swept',
    'FA50': 'jet_swept',
    'FA7X': 'jet_swept',
    'FA8X': 'jet_swept',
    'FOUG': 'm326',
    'G150': 'jet_nonswept',
    'G200': 'jet_swept',
    'G280': 'jet_swept',
    'GA5C': 'jet_swept',
    'GA6C': 'jet_swept',
    'GA7C': 'jet_swept',
    'GA8C': 'jet_swept',
    'GAZL': 'gazelle',
    'GL5T': 'jet_swept',
    'GL6T': 'jet_swept',
    'GL7T': 'jet_swept',
    'GLEX': 'jet_swept',
    'GLF2': 'jet_swept',
    'GLF3': 'jet_swept',
    'GLF4': 'jet_swept',
    'GLF5': 'jet_swept',
    'GLF6': 'jet_swept',
    'GLID': 'glider',
    'GND': 'ground_unknown',
    'GRND': 'ground_unknown',
    'GYRO': 'gyrocopter',
    'H160': 's61',
    'H25A': 'jet_nonswept',
    'H25B': 'jet_nonswept',
    'H25C': 'jet_nonswept',
    'H46': 'chinook',
    'H47': 'chinook',
    'H53': 's61',
    'H53S': 's61',
    'H60': 'blackhawk',
    'H64': 'apache',
    'HA4T': 'jet_swept',
    'HAWK': 'bae_hawk',
    'HDJT': 'jet_nonswept',
    'HRON': 'uav',
    'HUNT': 'hunter',
    'IL62': 'il_62',
    'J328': 'airliner',
    'J8A': 'hi_perf',
    'J8B': 'hi_perf',
    'JANU': 'glider',
    'JH7': 'hi_perf',
    'K35E': 'b707',
    'K35R': 'b707',
    'KFIR': 'mirage',
    'L159': 'l159',
    'L39': 'l159',
    'LANC': 'lancaster',
    'LEOP': 'hi_perf',
    'LJ23': 'jet_nonswept',
    'LJ24': 'jet_nonswept',
    'LJ25': 'jet_nonswept',
    'LJ28': 'jet_nonswept',
    'LJ31': 'jet_nonswept',
    'LJ35': 'jet_nonswept',
    'LJ40': 'jet_nonswept',
    'LJ45': 'jet_nonswept',
    'LJ55': 'jet_nonswept',
    'LJ60': 'jet_nonswept',
    'LJ70': 'jet_nonswept',
    'LJ75': 'jet_nonswept',
    'LJ85': 'jet_nonswept',
    'LK17': 'glider',
    'LK19': 'glider',
    'LK20': 'glider',
    'LR35': 'jet_nonswept',
    'LR45': 'jet_nonswept',
    'LS10': 'glider',
    'LS8': 'glider',
    'LS9': 'glider',
    'LTNG': 'hi_perf',
    'M326': 'm326',
    'M339': 'm326',
    'M346': 'hi_perf',
    'MD11': 'md11',
    'MD80': 'jet_swept',
    'MD81': 'jet_swept',
    'MD82': 'jet_swept',
    'MD83': 'jet_swept',
    'MD87': 'jet_swept',
    'MD88': 'jet_swept',
    'MD90': 'jet_swept',
    'ME62': 'hi_perf',
    'METR': 'hi_perf',
    'MG19': 'hi_perf',
    'MG25': 'hi_perf',
    'MG29': 'hi_perf',
    'MG31': 'hi_perf',
    'MG44': 'hi_perf',
    'MI24': 'mil24',
    'MIR2': 'mirage',
    'MIR4': 'hi_perf',
    'MRF1': 'miragef1',
    'MT2': 'hi_perf',
    'NH90': 'blackhawk',
    'NIMB': 'glider',
    'P3': 'p3_orion',
    'P8': 'p8',
    'PA24': 'pa24',
    'PARA': 'para',
    'PK20': 'glider',
    'PRM1': 'jet_nonswept',
    'PRTS': 'rutan_veze',
    'PUMA': 'puma',
    'Q1': 'uav',
    'Q25': 'uav',
    'Q4': 'uav',
    'Q5': 'hi_perf',
    'Q9': 'uav',
    'QINT': 'glider',
    'R22': 'helicopter',
    'R44': 'helicopter',
    'R66': 'helicopter',
    'RFAL': 'rafale',
    'RJ1H': 'b707',
    'RJ70': 'b707',
    'RJ85': 'b707',
    'S10S': 'glider',
    'S12': 'glider',
    'S12S': 'glider',
    'S22T': 'cirrus_sr22',
    'S3': 'hi_perf',
    'S37': 'hi_perf',
    'S6': 'glider',
    'S61': 's61',
    'S61R': 's61',
    'S76': 'dauphin',
    'S92': 'blackhawk',
    'SB39': 'sb39',
    'SERV': 'ground_service',
    'SF50': 'jet_nonswept',
    'SGUP': 'super_guppy',
    'SHIP': 'blimp',
    'SLCH': 'strato',
    'SR20': 'cirrus_sr22',
    'SR22': 'cirrus_sr22',
    'SR71': 'hi_perf',
    'SU15': 'hi_perf',
    'SU24': 'hi_perf',
    'SU25': 'hi_perf',
    'SU27': 'hi_perf',
    'T154': 'jet_swept',
    'T2': 'hi_perf',
    'T22M': 'hi_perf',
    'T33': 'm326',
    'T37': 'hi_perf',
    'T38': 't38',
    'T4': 'hi_perf',
    'TIGR': 'tiger',
    'TOR': 'tornado',
    'TS1J': 'glider',
    'TU22': 'hi_perf',
    'TWR': 'ground_tower',
    'U2': 'u2',
    'V22': 'v22_slow',
    'V22F': 'v22_fast',
    'VAUT': 'hi_perf',
    'VELO': 'rutan_veze',
    'VENT': 'glider',
    'VEZE': 'rutan_veze',
    'VF35': 'f35',
    'VNTE': 'glider',
    'WB57': 'wb57',
    'WHK2': 'strato',
    'Y130': 'hi_perf',
    'YK28': 'hi_perf',
    'YK40': 'jet_swept',
}

# Type description (L2J, H, etc.) to icon fallback - from tar1090
# Used when type designator is not in the direct mapping
TYPE_DESCRIPTION_ICONS = {
    'A1P': 'cessna',
    'A2P': 'twin_large',
    'A2P-M': 'twin_large',
    'A2T': 'twin_large',
    'A2T-M': 'twin_large',
    'G': 'gyrocopter',
    'H': 'helicopter',
    'L1J': 'hi_perf',
    'L1J-L': 'jet_nonswept',
    'L1P': 'cessna',
    'L1T': 'single_turbo',
    'L2J-H': 'heavy_2e',
    'L2J-L': 'jet_nonswept',
    'L2J-M': 'airliner',
    'L2P': 'twin_small',
    'L2T': 'twin_large',
    'L2T-M': 'twin_large',
    'L3J-H': 'md11',
    'L4J': 'b707',
    'L4J-H': 'b707',
    'L4J-M': 'b707',
    'L4T': 'c130',
    'L4T-H': 'c130',
    'L4T-M': 'c130',
}


def decode_flag_bits(flag_str: str) -> Dict[str, bool]:
    """
    Decode Mictronics/tar1090 aircraft database flag string into booleans.

    The source database stores a 4-bit string (military, interesting, PIA, LADD)
    but trims trailing zeroes in some rows. This normalizes the flag to 4 chars
    and maps bits to explicit booleans.
    """
    if not flag_str:
        return {"is_military": False, "is_interesting": False, "is_pia": False, "is_ladd": False}

    flags = flag_str.strip()
    if len(flags) == 1:
        flags = f"{flags}000"
    elif len(flags) == 2:
        flags = f"{flags}00"
    elif len(flags) == 3:
        flags = f"{flags}0"
    elif len(flags) > 4:
        flags = flags[-4:]

    flags = flags.rjust(4, "0")

    return {
        "is_military": flags[0] == "1",
        "is_interesting": flags[1] == "1",
        "is_pia": flags[2] == "1",
        "is_ladd": flags[3] == "1",
    }


def _make_entry(
    registration: str = "",
    type_code: str = "",
    manufacturer: str = "",
    model: str = "",
    owner: str = "",
    flags: str = "",
) -> Dict[str, Any]:
    """Build a normalized entry with decoded flags."""
    bits = decode_flag_bits(flags)
    return {
        "registration": registration,
        "type": type_code,
        "manufacturer": manufacturer,
        "model": model,
        "owner": owner,
        "flags": flags,
        "is_military": bits["is_military"],
        "is_interesting": bits["is_interesting"],
        "is_pia": bits["is_pia"],
        "is_ladd": bits["is_ladd"],
    }


def get_icon_for_type(type_code: str) -> str:
    """
    Determine the appropriate icon based on aircraft type designator.
    Uses tar1090 TypeDesignatorIcons mapping with fallback logic.

    Args:
        type_code: ICAO aircraft type designator (e.g., "B738", "R44", "C172")

    Returns:
        Icon name matching SVG filename in assets/icons/
    """
    if not type_code:
        return ICON_UNKNOWN

    type_upper = type_code.upper().strip()

    # Direct lookup first
    if type_upper in TYPE_DESIGNATOR_ICONS:
        return TYPE_DESIGNATOR_ICONS[type_upper]

    # Try prefix matching for types like B737, B738, etc.
    # Check progressively shorter prefixes
    for prefix_len in range(len(type_upper) - 1, 2, -1):
        prefix = type_upper[:prefix_len]
        if prefix in TYPE_DESIGNATOR_ICONS:
            return TYPE_DESIGNATOR_ICONS[prefix]

    # Fallback to unknown icon
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

        Supports two formats:
        1. Semicolon-delimited (tar1090): icao;reg;type;flags;model;;;
        2. Comma-delimited with headers (OpenSky)

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
                first_line = f.readline()
                f.seek(0)

                # Detect format: semicolon-delimited (tar1090) vs comma with headers
                if ';' in first_line and not first_line.lower().startswith('icao'):
                    # tar1090 format: icao;registration;type;flags;model;;;
                    for line in f:
                        parts = line.strip().split(';')
                        if len(parts) >= 3:
                            icao = parts[0].upper().strip()
                            if icao and len(icao) == 6:
                                self._cache[icao] = _make_entry(
                                    registration=parts[1] if len(parts) > 1 else "",
                                    type_code=parts[2] if len(parts) > 2 else "",
                                    model=parts[4] if len(parts) > 4 else "",
                                    flags=parts[3] if len(parts) > 3 else "",
                                )
                else:
                    # Comma-delimited with headers (OpenSky format)
                    reader = csv.DictReader(f)
                    for row in reader:
                        icao = row.get("icao24") or row.get("icao") or row.get("hex") or ""
                        icao = icao.upper().strip()
                        if icao:
                            self._cache[icao] = _make_entry(
                                registration=row.get("registration") or row.get("reg") or "",
                                type_code=row.get("typecode") or row.get("type") or row.get("aircraft_type") or "",
                                manufacturer=row.get("manufacturername") or row.get("manufacturer") or "",
                                model=row.get("model") or "",
                                owner=row.get("owner") or row.get("operator") or "",
                                flags=row.get("flags") or "",
                            )

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
            Icon name matching SVG file in assets/icons/
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
        Icon name matching SVG file in assets/icons/
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
        print("Usage: python -m apps.aircraft_db <ICAO_HEX>")
        print("Example: python -m apps.aircraft_db 4B4437")
