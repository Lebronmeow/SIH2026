"""Place resolution: user text -> coordinates.

Two resolvers, tried in order:
1. **Open-Meteo geocoding** (live; free, no key) — global coverage.
2. **Built-in coarse port gazetteer** — a handful of well-known Indian fishing
   centres with rounded coordinates (public reference facts, clearly labeled
   coarse). Used in demo mode / offline; never presented as survey-grade.
"""

from __future__ import annotations

import logging

import httpx

from app.config.registry import registry
from app.schemas.recommendation import Origin

logger = logging.getLogger(__name__)

# Coarse reference coordinates for major Indian fishing centres (degrees,
# rounded to ~0.01°). These are public geographic facts, not measurements.
_BUILTIN_PORTS: dict[str, tuple[float, float]] = {
    "rameswaram": (9.29, 79.31),
    "mandapam": (9.28, 79.12),
    "pamban": (9.28, 79.22),
    "thoothukudi": (8.76, 78.13),
    "tuticorin": (8.76, 78.13),
    "kanyakumari": (8.08, 77.55),
    "chennai": (13.08, 80.27),
    "kochi": (9.93, 76.27),
    "cochin": (9.93, 76.27),
    "visakhapatnam": (17.69, 83.29),
    "vizag": (17.69, 83.29),
    "paradip": (20.32, 86.61),
    "puri": (19.81, 85.83),
    "mumbai": (18.94, 72.84),
    "veraval": (20.91, 70.37),
    "porbandar": (21.64, 69.61),
    "kakinada": (16.99, 82.24),
    "machilipatnam": (16.17, 81.14),
    "chidambaranar": (8.76, 78.13),
    "gulf of mannar": (9.15, 79.30),
    "palk strait": (9.80, 79.65),
}


class PlaceResolver:
    source_id = "open-meteo-geocoding"

    async def resolve(self, name: str) -> Origin | None:
        key = name.strip().lower()
        origin = await self._via_geocoding(name)
        if origin:
            return origin
        return self._builtin(key, name)

    async def _via_geocoding(self, name: str) -> Origin | None:
        src = registry.get("open-meteo")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": name, "count": 1, "language": "en", "format": "json"},
                )
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001 — degrade to builtin gazetteer
            logger.info("geocoding failed for %r: %s", name, exc)
            return None
        results = data.get("results") or []
        if not results:
            return None
        top = results[0]
        return Origin(
            place=top.get("name", name),
            lat=float(top["latitude"]),
            lon=float(top["longitude"]),
            resolver=src.name,
            resolver_note=f"country={top.get('country')} (coastal check applied downstream)",
        )

    @staticmethod
    def _builtin(key: str, original: str) -> Origin | None:
        for port, (lat, lon) in _BUILTIN_PORTS.items():
            if port in key or key in port:
                return Origin(
                    place=original.title(),
                    lat=lat,
                    lon=lon,
                    resolver="ORCA builtin port gazetteer (coarse)",
                    resolver_note="coarse reference coordinates — not survey-grade",
                )
        return None
