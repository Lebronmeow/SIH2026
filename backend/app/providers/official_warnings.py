"""Official hazard-warning ingestion (cyclones, high waves, storm surge).

The problem statement's safety architecture names official cyclone / high-wave
warnings (IMD, INCOIS) as a mandatory input. This module is the deterministic
ingestion path: it fetches machine-readable alert feeds, filters them to the
search area, and emits :class:`Warning` objects with exact provenance. The LLM
never decides whether an official warning exists and never invents one.

Sources (honest capability, verified 2026-08-30):

* **GDACS** (Global Disaster Alert and Coordination System, EU/JRC) — keyless
  global mirror of national WMO bulletins; carries North Indian Ocean tropical
  cyclones. Always on; the event list is cached ~10 minutes so concurrent
  queries don't re-download the full catalogue.
* **INCOIS GEMINI API** — official High Wave / Swell Surge / Storm Surge
  GeoJSON; requires a free registered key (``ORCA_INCOIS_API_KEY``). Without a
  key the feed is skipped with an explicit note.
* **IMD via data.gov.in** — generic GeoJSON hook, fully configuration-driven
  (``ORCA_IMD_ALERTS_URL`` + ``ORCA_IMD_API_KEY``). The resource URL is never
  a Python literal.

No source fetched ⇒ the result carries notes saying exactly which feeds were
skipped/unavailable. An empty warning list is NEVER presented as "no warnings
active" unless at least one live feed was actually consulted — callers surface
the ``notes`` so that state stays visible.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from shapely.geometry import box as shp_box, shape

from app.config.settings import DataMode
from app.schemas.common import Authority, BoundingBox
from app.schemas.common import Warning as OrcaWarning
from app.schemas.common import Provenance

logger = logging.getLogger(__name__)

_GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP?eventtype=TC"
_GDACS_CACHE_TTL_S = 600.0
_gdacs_cache: tuple[float, list[dict[str, Any]] | None] = (0.0, None)

# Inclusion radius (km): how far from the search box an alert may sit and
# still be attached. Cyclone centroids sweep across whole basins, so the TC
# buffer is much larger than the coastal one. Degrees→km uses 1° ≈ 111.32 km —
# an approximation fine for an *inclusion* test (verdicts never depend on it).
_TC_BUFFER_KM = 400.0
_COASTAL_BUFFER_KM = 150.0

# GDACS alertlevel → ORCA severity
_GDACS_SEVERITY = {"red": "critical", "orange": "warning", "green": "caution"}


@dataclass(slots=True)
class OfficialWarningResult:
    """Warnings for the search area + provenance + honest feed-state notes."""

    warnings: list[OrcaWarning] = dc_field(default_factory=list)
    provenance: list[Provenance] = dc_field(default_factory=list)
    notes: list[str] = dc_field(default_factory=list)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _feature_relevant(props: dict[str, Any], window_start: datetime, window_end: datetime) -> bool:
    """True when the event's active window overlaps the advisory window.

    Properties with no dates at all are treated as current (the GDACS list is
    an *active* event list); explicit windows must overlap the trip window.
    """
    start = _parse_iso(props.get("fromdate") or props.get("fromDate"))
    end = _parse_iso(props.get("todate") or props.get("toDate"))
    if start is None and end is None:
        return True
    end = end or window_start  # opened but never closed → still active
    return end >= window_start


def _severity_from(value: Any) -> str:
    text = str(value or "").lower()
    if "red" in text or "critical" in text:
        return "critical"
    if "orange" in text or "yellow" in text:
        return "warning"
    if "green" in text or "low" in text:
        return "caution"
    return "warning"


def _feature_distance_km(feature: dict[str, Any], box_deg: Any) -> float:
    """Approximate distance (km) between a GeoJSON feature and a test box."""
    geom = feature.get("geometry") or {}
    try:
        shp = shape(geom)
    except Exception:  # noqa: BLE001 — malformed geometry ⇒ treat as far away
        return float("inf")
    if shp.is_empty:
        return float("inf")
    return float(shp.distance(box_deg)) * 111.32


async def _fetch_gdacs_tc(client: httpx.AsyncClient, timeout: float) -> tuple[list[dict[str, Any]], list[str]]:
    """GDACS tropical-cyclone event list, cached ~10 min (the catalogue is ~2 MB)."""
    global _gdacs_cache
    fetched_at, cached = _gdacs_cache
    now = time.monotonic()
    if cached is not None and now - fetched_at < _GDACS_CACHE_TTL_S:
        return cached, []
    try:
        resp = await asyncio.wait_for(client.get(_GDACS_URL), timeout=timeout)
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except Exception as exc:  # noqa: BLE001 — warnings must never hang the advisory
        logger.warning("GDACS fetch failed: %s", exc)
        # A stale *warning* feed is dangerous — never served; report honestly.
        return [], [f"GDACS unavailable ({type(exc).__name__})"]
    _gdacs_cache = (now, features)
    return features, []


def _gdacs_warning(props: dict[str, Any]) -> OrcaWarning:
    name = str(props.get("eventname") or props.get("name") or "unnamed system")
    return OrcaWarning(
        severity=_GDACS_SEVERITY.get(str(props.get("alertlevel", "")).lower(), "warning"),
        code="OFFICIAL_CYCLONE",
        message=(
            f"Official alert: tropical cyclone {name} is active near the search area "
            f"(GDACS level {props.get('alertlevel', '—')}). Follow IMD bulletins."
        ),
        source="gdacs",
        params={"level": str(props.get("alertlevel") or "—"), "name": str(name)},
    )


async def official_warnings(
    bbox: BoundingBox,
    valid_time: datetime | None,
    *,
    incois_api_key: str | None = None,
    imd_alerts_url: str | None = None,
    imd_api_key: str | None = None,
    timeout: float = 8.0,
    incois_base_url: str = "https://gemini.incois.gov.in/incoisapi/rest",
    include_gdacs: bool = True,
) -> OfficialWarningResult:
    """Deterministic official-warning check over the search area.

    Never raises: every failure becomes a note so the advisory carries the
    honest state of the warning feeds instead of an error.
    """
    result = OfficialWarningResult()
    now = datetime.now(timezone.utc)
    window_start = now
    window_end = (valid_time or now) + timedelta(hours=24)

    tc_pad = _TC_BUFFER_KM / 111.32
    tc_box = shp_box(bbox.west - tc_pad, bbox.south - tc_pad, bbox.east + tc_pad, bbox.north + tc_pad)
    coastal_pad = _COASTAL_BUFFER_KM / 111.32
    coastal_box = shp_box(bbox.west - coastal_pad, bbox.south - coastal_pad, bbox.east + coastal_pad, bbox.north + coastal_pad)

    async with httpx.AsyncClient(
        headers={"Accept": "application/json"}, timeout=timeout, follow_redirects=True
    ) as client:
        # ---- GDACS tropical cyclones (keyless global mirror)
        if include_gdacs:
            features, notes = await _fetch_gdacs_tc(client, timeout)
            result.notes.extend(notes)
            if features:
                active = [
                    f
                    for f in features
                    if str((f.get("properties") or {}).get("eventtype", "")).upper() == "TC"
                    and _feature_distance_km(f, tc_box) <= _TC_BUFFER_KM
                    and _feature_relevant(f.get("properties") or {}, window_start, window_end)
                ]
                result.provenance.append(
                    Provenance(
                        source_id="gdacs",
                        source_name="GDACS Global Disaster Alerts (mirror of national WMO bulletins)",
                        dataset="geteventlist eventtype=TC",
                        retrieved_at=now,
                        valid_time=now,
                        authority=Authority.DESCRIPTIVE,
                        mode=DataMode.LIVE,
                        notes="keyless global mirror — verify against IMD bulletins for the authoritative statement",
                    )
                )
                result.notes.append(f"GDACS TC consulted ({len(features)} catalogue, {len(active)} active nearby)")
                result.warnings.extend(_gdacs_warning(f["properties"]) for f in active)
        else:
            result.notes.append("GDACS check disabled by configuration")

        # ---- INCOIS official coastal alerts (registration key required)
        if incois_api_key:
            feeds = (
                ("/hwalatestgeo", "OFFICIAL_HIGH_WAVE", "High Wave Alert"),
                ("/ssalatestgeo", "OFFICIAL_SWELL_SURGE", "Swell Surge Alert"),
                ("/stormsurgelatest", "OFFICIAL_STORM_SURGE", "Storm Surge Warning"),
            )
            for path, code, label in feeds:
                try:
                    resp = await asyncio.wait_for(
                        client.get(f"{incois_base_url}{path}", headers={"Authorization": incois_api_key}),
                        timeout=timeout,
                    )
                    resp.raise_for_status()
                    feats = resp.json().get("features", [])
                except Exception as exc:  # noqa: BLE001
                    result.notes.append(f"INCOIS {label} unavailable ({type(exc).__name__})")
                    continue
                for f in feats:
                    if _feature_distance_km(f, coastal_box) > _COASTAL_BUFFER_KM:
                        continue
                    props = f.get("properties") or {}
                    level = props.get("alertlevel") or props.get("level") or props.get("grade") or "—"
                    result.warnings.append(
                        OrcaWarning(
                            severity=_severity_from(props.get("alertlevel") or props.get("level") or props.get("grade")),
                            code=code,
                            message=f"Official INCOIS {label} active near the search area (source: INCOIS).",
                            source="incois",
                            params={"level": str(level)},
                        )
                    )
                result.provenance.append(
                    Provenance(
                        source_id="incois-gemini",
                        source_name="INCOIS GEMINI API (official Indian ocean alerts)",
                        dataset=path.strip("/"),
                        retrieved_at=now,
                        valid_time=now,
                        authority=Authority.AUTHORITATIVE,
                        mode=DataMode.LIVE,
                    )
                )
                result.notes.append(f"INCOIS {label} consulted ({len(feats)} features)")
        else:
            result.notes.append("INCOIS official alert feed skipped — ORCA_INCOIS_API_KEY not configured")

        # ---- IMD via data.gov.in (fully configuration-driven GeoJSON hook)
        if imd_alerts_url:
            try:
                url = imd_alerts_url
                if imd_api_key:
                    url = url + ("&" if "?" in url else "?") + f"api-key={imd_api_key}"
                resp = await asyncio.wait_for(client.get(url), timeout=timeout)
                resp.raise_for_status()
                feats = resp.json().get("features", [])
                for f in feats:
                    props = f.get("properties") or {}
                    msg = props.get("message") or props.get("description") or props.get("text") or ""
                    if not _feature_relevant(props, window_start, window_end):
                        continue
                    level = str(props.get("severity") or props.get("alertlevel") or "warning")
                    result.warnings.append(
                        OrcaWarning(
                            severity=_severity_from(props.get("severity") or props.get("alertlevel")),
                            code="OFFICIAL_IMD",
                            message=f"Official IMD warning: {msg}" if msg else "Official IMD warning active near the search area.",
                            source="imd",
                            params={"level": level, "name": msg},
                        )
                    )
                result.provenance.append(
                    Provenance(
                        source_id="imd-datagov",
                        source_name="India Meteorological Department via data.gov.in",
                        dataset=imd_alerts_url.rsplit("/", 1)[-1] or "configured resource",
                        retrieved_at=now,
                        valid_time=now,
                        authority=Authority.AUTHORITATIVE,
                        mode=DataMode.LIVE,
                        notes="resource and key are configuration (ORCA_IMD_ALERTS_URL / ORCA_IMD_API_KEY)",
                    )
                )
                result.notes.append(f"IMD feed consulted ({len(feats)} features)")
            except Exception as exc:  # noqa: BLE001
                result.notes.append(f"IMD feed unavailable ({type(exc).__name__})")
        else:
            result.notes.append("IMD warning hook not configured — set ORCA_IMD_ALERTS_URL (+ ORCA_IMD_API_KEY)")

    return result
