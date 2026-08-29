"""AIS vessel-traffic ingestion (Phase 8).

Two implementations behind one protocol:

* :class:`FileAisProvider` — demo mode. Reads ``ais.json`` from a demo pack.
  Pack files are built by ``scripts/fetch_demo_data.py`` and are *clearly
  labeled synthetic*: there is no free national AIS feed we may redistribute,
  so the demo pack contains fabricated vessel positions and every value
  derived from them says so.
* :func:`decode_nmea` — ops mode helper around **pyais** (verdict A, MIT):
  decode live NMEA sentences from a terrestrial receiver feed. Operators wire
  their own transport (TCP/UDP/WebSocket); ORCA consumes the decoded states.

The LLM never sees raw AIS traffic — only counts/summaries produced here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from app.schemas.common import BoundingBox

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AisVesselState:
    mmsi: str
    lat: float
    lon: float
    sog_kn: float | None = None  # speed over ground
    cog_deg: float | None = None  # course over ground
    vessel_type: str | None = None
    timestamp: datetime | None = None
    synthetic: bool = False


class AisProvider(Protocol):
    async def vessels_in_bbox(self, bbox: BoundingBox, valid_time: datetime | None = None) -> list[AisVesselState]:
        """Vessel states within the bbox (nearest report ≤ valid_time)."""
        ...  # pragma: no cover


class FileAisProvider:
    """Demo pack AIS reader (``<pack>/ais.json``). Missing file → empty."""

    def __init__(self, pack_dir: Path | str) -> None:
        self._path = Path(pack_dir) / "ais.json"
        self._cache: list[AisVesselState] | None = None

    def _load(self) -> list[AisVesselState]:
        if self._cache is not None:
            return self._cache
        vessels: list[AisVesselState] = []
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                synthetic = bool(raw.get("synthetic", False))
                for v in raw.get("vessels", []):
                    ts = v.get("timestamp")
                    vessels.append(
                        AisVesselState(
                            mmsi=str(v["mmsi"]),
                            lat=float(v["lat"]),
                            lon=float(v["lon"]),
                            sog_kn=v.get("sog_kn"),
                            cog_deg=v.get("cog_deg"),
                            vessel_type=v.get("vessel_type"),
                            timestamp=datetime.fromisoformat(ts) if ts else None,
                            synthetic=synthetic,
                        )
                    )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning("cannot read AIS pack %s: %s", self._path, exc)
        else:
            logger.info("no AIS pack at %s — traffic features disabled (honest absence)", self._path)
        self._cache = vessels
        return vessels

    async def vessels_in_bbox(self, bbox: BoundingBox, valid_time: datetime | None = None) -> list[AisVesselState]:
        return [
            v
            for v in self._load()
            if bbox.south <= v.lat <= bbox.north and bbox.west <= v.lon <= bbox.east
        ]


def decode_nmea(sentences: list[str]) -> list[AisVesselState]:
    """Decode NMEA AIS sentences (A-D or multi-part) via pyais.

    Raises nothing: a malformed line is skipped and logged — a broken feed
    must degrade to fewer vessels, never to invented states.
    """
    from pyais import decode  # lazy: keeps pyais off the demo import path

    states: list[AisVesselState] = []
    for raw in sentences:
        try:
            # pyais.decode(*parts) is varargs and requires bytes; a one-line
            # call decodes a single message (multipart feeds pass all parts)
            payload = raw.encode("ascii") if isinstance(raw, str) else raw
            decoded = decode(payload)
            for msg in decoded if isinstance(decoded, (list, tuple)) else [decoded]:
                lat, lon = msg.lat, msg.lon
                if lat is None or lon is None:
                    continue
                states.append(
                    AisVesselState(
                        mmsi=str(getattr(msg, "mmsi", "")),
                        lat=float(lat),
                        lon=float(lon),
                        sog_kn=float(msg.sog) if getattr(msg, "sog", None) is not None else None,
                        cog_deg=float(msg.cog) if getattr(msg, "cog", None) is not None else None,
                        timestamp=datetime.now(timezone.utc),
                    )
                )
        except Exception as exc:  # noqa: BLE001 — feed robustness over purity
            logger.warning("AIS decode failed for one sentence: %s", exc)
    return states


def count_within_radius(vessels: list[AisVesselState], lat: float, lon: float, radius_km: float) -> int:
    """Count vessels within radius_km of (lat, lon) — geodesic, pyproj Geod."""
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    n = 0
    for v in vessels:
        _, _, dist_m = geod.inv(lon, lat, v.lon, v.lat)
        if dist_m <= radius_km * 1000.0:
            n += 1
    return n
