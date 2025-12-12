import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adsb.adsb import AircraftStateTracker, ParsedMessage, parse_sbs_line  # noqa: E402


def test_parse_sbs_line_with_position():
    line = "MSG,3,111,11111,3C5EF2,111111,2025/12/07,17:01:58.200,2025/12/07,17:01:58.400,EWG4TV,38000,376,158,45.630,8.936,,,0,0,0,0"
    msg = parse_sbs_line(line)
    assert msg is not None
    assert msg.icao == "3C5EF2"
    assert msg.has_position is True
    assert msg.lat == pytest.approx(45.63)
    assert msg.lon == pytest.approx(8.936)
    assert msg.altitude_ft == 38000
    assert msg.ground_speed_kts == 376
    assert msg.track_deg == 158
    assert msg.flight == "EWG4TV"
    assert msg.message_type == "MSG"
    assert msg.transmission_type == 3
    assert msg.alert is False
    assert msg.on_ground is False


def test_parse_sbs_line_ignores_non_msg():
    assert parse_sbs_line("SEL,foo,bar") is None
    assert parse_sbs_line("") is None


def test_tracker_merges_partial_messages():
    tracker = AircraftStateTracker()

    # Position without velocity
    msg_pos = ParsedMessage(
        raw="MSG,3,,,",
        message_type="MSG",
        transmission_type=None,
        icao="ABC123",
        callsign="TEST123",
        lat=40.0,
        lon=-3.0,
        altitude_ft=10000,
        has_position=True,
    )
    pos_record, has_full = tracker.update(msg_pos)
    assert pos_record is not None
    assert has_full is False
    assert pos_record["heading_deg"] is None

    # Velocity update (no lat/lon)
    msg_vel = ParsedMessage(
        raw="MSG,4,,,",
        message_type="MSG",
        transmission_type=None,
        icao="ABC123",
        ground_speed_kts=250.0,
        track_deg=90.0,
    )
    pos_record, has_full = tracker.update(msg_vel)
    # Position still present and now has velocity merged
    assert pos_record is not None
    assert has_full is True
    assert pos_record["speed_kts"] == 250.0
    assert pos_record["heading_deg"] == 90.0
