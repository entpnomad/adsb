"""
Shared library modules for ADS-B tracker.

This package contains reusable utilities:
- config: Centralized paths and configuration
- geo: Geocoding, elevation lookup, distance calculations
- colors: Altitude-based color mapping
"""

from .config import *
from .geo import *
from .colors import *
