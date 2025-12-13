#!/usr/bin/env python3
"""
Simulated dump1090 SBS-1 TCP stream.

Starts a simple TCP server on port 30003 that emits moving aircraft
messages (MSG type 3 for position and MSG type 4 for velocity).
Useful for local demos without hardware.
"""

from __future__ import annotations

import math
import random
import socket
import threading
import time
from datetime import datetime, timezone
from typing import List, Tuple

PORT = 30003
TICK_SECONDS = 1.0


class Aircraft:
    def __init__(self, icao: str, flight: str, lat: float, lon: float, alt_ft: float, speed_kts: float, heading_deg: float):
        self.icao = icao
        self.flight = flight
        self.lat = lat
        self.lon = lon
        self.alt_ft = alt_ft
        self.speed_kts = speed_kts
        self.heading_deg = heading_deg

    def step(self) -> Tuple[float, float, float, float, float]:
        # Move forward based on speed/heading; add small noise
        distance_nm = self.speed_kts * (TICK_SECONDS / 3600.0)
        distance_km = distance_nm * 1.852
        delta_lat = (distance_km / 111.0) * math.cos(math.radians(self.heading_deg))
        delta_lon = (distance_km / (111.0 * math.cos(math.radians(max(min(self.lat, 89.9), -89.9))))) * math.sin(math.radians(self.heading_deg))
        self.lat += delta_lat
        self.lon += delta_lon
        self.alt_ft += random.uniform(-200, 200)
        self.heading_deg = (self.heading_deg + random.uniform(-5, 5)) % 360
        return self.lat, self.lon, self.alt_ft, self.speed_kts, self.heading_deg


def format_msg(ac: Aircraft) -> Tuple[str, str]:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y/%m/%d")
    time_str = now.strftime("%H:%M:%S.%f")[:-3]
    # Position message (MSG,3)
    msg3 = f"MSG,3,1,1,{ac.icao},1,{date_str},{time_str},{date_str},{time_str},{ac.flight},{int(ac.alt_ft)},{int(ac.speed_kts)},{int(ac.heading_deg)},{ac.lat:.4f},{ac.lon:.4f},,,,"
    # Velocity message (MSG,4)
    msg4 = f"MSG,4,1,1,{ac.icao},1,{date_str},{time_str},{date_str},{time_str},{ac.flight},{int(ac.alt_ft)},{int(ac.speed_kts)},{int(ac.heading_deg)},,,,"
    return msg3, msg4


def client_sender(conn: socket.socket, aircraft: List[Aircraft]) -> None:
    try:
        while True:
            lines: List[str] = []
            for ac in aircraft:
                ac.step()
                msg3, msg4 = format_msg(ac)
                lines.extend([msg3, msg4])
            payload = ("\n".join(lines) + "\n").encode("utf-8")
            conn.sendall(payload)
            time.sleep(TICK_SECONDS)
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main() -> None:
    # Seed some aircraft around a central point
    center_lat, center_lon = 40.4168, -3.7038  # Madrid as default
    aircraft = []
    for idx in range(5):
        icao = f"D{random.randrange(16**5):05X}"
        flight = f"DEMO{idx:02d}"
        lat = center_lat + random.uniform(-0.1, 0.1)
        lon = center_lon + random.uniform(-0.1, 0.1)
        alt = random.uniform(5000, 35000)
        speed = random.uniform(220, 450)
        heading = random.uniform(0, 360)
        aircraft.append(Aircraft(icao, flight, lat, lon, alt, speed, heading))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", PORT))
        server.listen()
        print(f"SBS simulator listening on port {PORT}...")
        while True:
            conn, addr = server.accept()
            print(f"Client connected: {addr}")
            threading.Thread(target=client_sender, args=(conn, aircraft), daemon=True).start()


if __name__ == "__main__":
    main()
