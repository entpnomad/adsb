"""
Core ADS-B parsing and state tracking utilities.

This module contains reusable pieces for reading SBS-1/BaseStation lines,
merging partial messages into a per-aircraft state, and producing position
records ready for storage or exposure via APIs.

It is intentionally light on I/O so callers can reuse the logic in
different contexts (CSV logger, DB writer, API server, tests).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple


EVENT_TYPE = "adsb.position.v1"


@dataclass
class ParsedMessage:
    """Structured representation of a single SBS-1 line."""

    raw: str
    message_type: str
    transmission_type: Optional[int]
    icao: str
    callsign: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    altitude_ft: Optional[int] = None
    ground_speed_kts: Optional[float] = None
    track_deg: Optional[float] = None
    vertical_rate_fpm: Optional[int] = None
    squawk: Optional[str] = None
    alert: Optional[bool] = None
    emergency: Optional[bool] = None
    spi: Optional[bool] = None
    on_ground: Optional[bool] = None
    has_position: bool = False

    @property
    def flight(self) -> Optional[str]:
        """Backwards-compatible alias used throughout the codebase."""
        return self.callsign


def _parse_flag(value: str) -> Optional[bool]:
    """Convert SBS flag fields (0/1) to booleans."""
    value = value.strip()
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def parse_sbs_line(line: str) -> Optional[ParsedMessage]:
    """
    Parse a single SBS-1/BaseStation CSV line.

    Returns ParsedMessage or None if the line is not usable.
    """
    raw_line = line.strip()
    if not raw_line:
        return None

    fields = raw_line.split(",")

    # Must be a MSG line with an ICAO code
    if len(fields) < 5:
        return None

    message_type = fields[0].strip()
    if message_type != "MSG":
        return None

    transmission_type: Optional[int] = None
    if len(fields) > 1 and fields[1].strip():
        try:
            transmission_type = int(fields[1])
        except ValueError:
            transmission_type = None

    icao = fields[4].strip().upper()
    if not icao:
        return None

    parsed = ParsedMessage(raw=raw_line, message_type=message_type, transmission_type=transmission_type, icao=icao)

    # Callsign / flight
    if len(fields) > 10 and fields[10].strip():
        parsed.callsign = fields[10].strip()

    # Altitude (ft)
    if len(fields) > 11 and fields[11].strip():
        try:
            parsed.altitude_ft = int(float(fields[11]))
        except ValueError:
            pass

    # Ground speed (kts)
    if len(fields) > 12 and fields[12].strip():
        try:
            parsed.ground_speed_kts = float(fields[12])
        except ValueError:
            pass

    # Track / heading (deg)
    if len(fields) > 13 and fields[13].strip():
        try:
            parsed.track_deg = float(fields[13])
        except ValueError:
            pass

    # Position
    if len(fields) > 15:
        lat_str = fields[14].strip()
        lon_str = fields[15].strip()
        try:
            if lat_str and lon_str:
                lat = float(lat_str)
                lon = float(lon_str)
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    parsed.lat = lat
                    parsed.lon = lon
                    parsed.has_position = True
        except ValueError:
            pass

    # Vertical rate
    if len(fields) > 16 and fields[16].strip():
        try:
            parsed.vertical_rate_fpm = int(float(fields[16]))
        except ValueError:
            pass

    # Squawk
    if len(fields) > 17 and fields[17].strip():
        parsed.squawk = fields[17].strip()

    # Flags (alert, emergency, SPI, on ground)
    if len(fields) > 18 and fields[18].strip():
        parsed.alert = _parse_flag(fields[18])
    if len(fields) > 19 and fields[19].strip():
        parsed.emergency = _parse_flag(fields[19])
    if len(fields) > 20 and fields[20].strip():
        parsed.spi = _parse_flag(fields[20])
    if len(fields) > 21 and fields[21].strip():
        parsed.on_ground = _parse_flag(fields[21])

    return parsed


@dataclass
class AircraftState:
    """Tracks the latest known data for a single aircraft."""

    icao: str
    flight: str = ""
    registration: Optional[str] = None
    icao_type: Optional[str] = None
    model: Optional[str] = None
    is_military: Optional[bool] = None
    is_interesting: Optional[bool] = None
    is_pia: Optional[bool] = None
    is_ladd: Optional[bool] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    altitude_ft: Optional[int] = None
    speed_kts: Optional[float] = None
    heading_deg: Optional[float] = None
    vertical_rate_fpm: Optional[int] = None
    squawk: Optional[str] = None
    alert: Optional[bool] = None
    emergency: Optional[bool] = None
    spi: Optional[bool] = None
    on_ground: Optional[bool] = None
    last_update: Optional[str] = None

    def as_position(self) -> Optional[Dict[str, Any]]:
        """Return a position dict if we have at least a valid lat/lon."""
        if self.lat is None or self.lon is None:
            return None
        return {
            "icao": self.icao,
            "flight": self.flight,
            "lat": self.lat,
            "lon": self.lon,
            "altitude_ft": self.altitude_ft,
            "speed_kts": self.speed_kts,
            "heading_deg": self.heading_deg,
            "vertical_rate_fpm": self.vertical_rate_fpm,
            "squawk": self.squawk,
            "alert": self.alert,
            "emergency": self.emergency,
            "spi": self.spi,
            "on_ground": self.on_ground,
        }


@dataclass
class AircraftStateTracker:
    """
    Maintains per-aircraft state across multiple messages.

    update() merges the latest ParsedMessage and returns:
      - position dict (if we have lat/lon), otherwise None
      - boolean indicating whether the record has full position+velocity data
    """

    lookup_aircraft_info: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None
    _state: Dict[str, AircraftState] = field(default_factory=dict)

    def _apply_aircraft_info(self, state: AircraftState) -> None:
        if not self.lookup_aircraft_info:
            return

        try:
            info = self.lookup_aircraft_info(state.icao)
        except Exception:
            return

        if not info:
            return

        state.registration = info.get("registration") or state.registration
        state.icao_type = info.get("type") or state.icao_type
        state.model = info.get("model") or state.model

        for attr in ("is_pia", "is_ladd", "is_military", "is_interesting"):
            value = info.get(attr)
            if value is not None:
                setattr(state, attr, bool(value))

    def update(self, msg: ParsedMessage) -> Tuple[Optional[Dict[str, Any]], bool]:
        state = self._state.get(msg.icao)
        if state is None:
            state = AircraftState(icao=msg.icao)
            self._apply_aircraft_info(state)
            self._state[msg.icao] = state

        if msg.flight:
            state.flight = msg.flight
        if msg.lat is not None:
            state.lat = msg.lat
        if msg.lon is not None:
            state.lon = msg.lon
        if msg.altitude_ft is not None:
            state.altitude_ft = msg.altitude_ft
        if msg.ground_speed_kts is not None:
            state.speed_kts = msg.ground_speed_kts
        if msg.track_deg is not None:
            state.heading_deg = msg.track_deg
        if msg.vertical_rate_fpm is not None:
            state.vertical_rate_fpm = msg.vertical_rate_fpm
        if msg.squawk:
            state.squawk = msg.squawk
        if msg.alert is not None:
            state.alert = msg.alert
        if msg.emergency is not None:
            state.emergency = msg.emergency
        if msg.spi is not None:
            state.spi = msg.spi
        if msg.on_ground is not None:
            state.on_ground = msg.on_ground

        state.last_update = datetime.now(timezone.utc).isoformat()

        position = state.as_position()
        has_full_velocity = position is not None and state.speed_kts is not None and state.heading_deg is not None
        return position, has_full_velocity

    def get_state(self, icao: str) -> Optional[AircraftState]:
        """Return the tracked state for a given ICAO hex (if any)."""
        return self._state.get(icao)

    def latest_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """
        Return a snapshot of latest positions (including timestamps) keyed by ICAO.
        Only includes aircraft with a valid position.
        """
        snapshot: Dict[str, Dict[str, Any]] = {}
        for icao, state in self._state.items():
            position = state.as_position()
            if position:
                snapshot[icao] = {
                    **position,
                    "timestamp_utc": state.last_update or datetime.now(timezone.utc).isoformat(),
                }
        return snapshot


def _drop_none(values: Dict[str, Any]) -> Dict[str, Any]:
    """Utility to strip None values while retaining valid falsy values like False/0."""
    return {k: v for k, v in values.items() if v is not None}


def build_adsb_position_event(
    state: AircraftState,
    source: str,
    raw_sbs: Optional[str] = None,
    message_type: Optional[str] = None,
    transmission_type: Optional[int] = None,
    timestamp_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Build a JSON-serializable ADS-B position event from an AircraftState.

    Args:
        state: AircraftState with at least lat/lon populated.
        source: Identifier of the producing station (ADSB_SOURCE_ID).
        raw_sbs: Raw SBS-1 line as received (optional).
        message_type: SBS message type, usually "MSG".
        transmission_type: SBS transmission subtype (1..8).
        timestamp_ms: Optional override for event timestamp in ms since epoch (UTC).
    """
    if state.lat is None or state.lon is None:
        raise ValueError("Cannot build ADS-B position event without lat/lon")

    ts_ms = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)

    aircraft_block = _drop_none(
        {
            "icaoHex": state.icao,
            "callsign": state.flight or None,
            "registration": state.registration,
            "icaoType": state.icao_type,
            "model": state.model,
            "isMilitary": state.is_military,
            "isInteresting": state.is_interesting,
            "isPIA": state.is_pia,
            "isLADD": state.is_ladd,
        }
    )

    position_block = _drop_none(
        {
            "lat": state.lat,
            "lon": state.lon,
            "altitudeFt": state.altitude_ft,
            "groundSpeedKts": state.speed_kts,
            "trackDeg": state.heading_deg,
            "verticalRateFpm": state.vertical_rate_fpm,
        }
    )

    codes_block = _drop_none(
        {
            "squawk": state.squawk,
            "alert": state.alert,
            "emergency": state.emergency,
            "spi": state.spi,
            "onGround": state.on_ground,
        }
    )

    raw_block = _drop_none(
        {
            "sbs": raw_sbs,
            "messageType": message_type,
            "transmissionType": transmission_type,
        }
    )

    return {
        "eventType": EVENT_TYPE,
        "source": source,
        "tsUnixMs": ts_ms,
        "aircraft": aircraft_block,
        "position": position_block,
        "codes": codes_block,
        "raw": raw_block,
    }
