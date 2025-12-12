"""
Lightweight NATS publisher helpers for ADS-B events.

Exposes a one-shot publish function and a reusable publisher that keeps
the connection open for higher throughput senders.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional

from nats.aio.client import Client as NATS

DEFAULT_NATS_URL = os.getenv("ADSB_NATS_URL", "nats://localhost:4222")
DEFAULT_SUBJECT = os.getenv("ADSB_NATS_SUBJECT", "adsb.position.v1")


async def publish_event(event: Dict[str, Any], nats_url: Optional[str] = None, subject: Optional[str] = None) -> None:
    """
    Publish a single event to NATS, opening and closing the connection per call.

    Suitable for low-volume scripts; for continuous senders use NatsPublisher.
    """
    nats_url = nats_url or DEFAULT_NATS_URL
    subject = subject or DEFAULT_SUBJECT

    nc = NATS()
    await nc.connect(servers=[nats_url])

    payload = json.dumps(event).encode("utf-8")
    await nc.publish(subject, payload)
    await nc.flush()
    await nc.drain()


class NatsPublisher:
    """Reusable NATS publisher that keeps the connection open."""

    def __init__(self, nats_url: Optional[str] = None, subject: Optional[str] = None) -> None:
        self.nats_url = nats_url or DEFAULT_NATS_URL
        self.subject = subject or DEFAULT_SUBJECT
        self._nc = NATS()
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            await self._nc.connect(servers=[self.nats_url])
            self._connected = True

    async def publish(self, event: Dict[str, Any]) -> None:
        if not self._connected:
            await self.connect()
        payload = json.dumps(event).encode("utf-8")
        await self._nc.publish(self.subject, payload)

    async def close(self) -> None:
        async with self._lock:
            if not self._connected:
                return
            await self._nc.flush()
            await self._nc.drain()
            self._connected = False

    async def __aenter__(self) -> "NatsPublisher":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
