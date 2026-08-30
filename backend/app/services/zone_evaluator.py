"""Zone generation and evaluation — the deterministic heart of ORCA.

Candidate zones are generated on the requested-distance ring around the
origin, pre-filtered by hard geospatial constraints, then evaluated with real
provider data (fields fetched once per variable over the ring box, then
sampled per candidate — one network round-trip per variable, not per zone).

Everything numeric carries provenance; everything hard is decided by the
GeospatialSafetyEngine; the scoring engine stays deterministic.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import numpy as np
import xarray as xr
from pyproj import Geod

from app.config.settings import DataMode, get_settings
from app.engines.geospatial.safety import GeospatialSafetyEngine
from app.engines.ocean.front_detection import FrontDetectionEngine, FrontResult, GradientFrontStrategy
from app.engines.routing.engine import RouteOptimizationEngine, Route
from app.engines.scoring.engine import RecommendationScoringEngine, ScoreBreakdown, ScoringWeights
from app.providers.base import OceanField
from app.providers.hub import OceanDataHub
from app.providers.official_warnings import official_warnings, OfficialWarningResult
from app.schemas.common import (
    BoundingBox,
    Evidence,
    GeoJSONFeature,
    InsufficiencyReason,
    LatLon,
    Measurement,
    Provenance,
    QualityFlag,
    Warning as OrcaWarning,
)
from app.schemas.recommendation import (
    ParsedQuery,
    RecommendationResponse,
    RouteOut,
    WorkflowTrace,
    ZoneCandidate,
    ZoneEvaluation,
)

logger = logging.getLogger(__name__)
_GEOD = Geod(ellps="WGS84")

if TYPE_CHECKING:
    from app.services.ais import AisProvider

# traffic-context radius around the recommended zone (km)
AIS_TRAFFIC_RADIUS_KM = 5.0

# small-craft hazard caution thresholds (deterministic, prototype heuristics —
# not a validated safety model; bands align with the WMO "rough" sea state and
# a fresh-breeze wind). Exceeding either raises a *caution*, never a critical:
# critical severity is reserved for hard geospatial constraint violations.
ROUGH_SEA_M = 2.5
STRONG_WIND_KMH = 30.0


def distance_km_between(a: LatLon, b: LatLon) -> float:
    _az, _back, m = _GEOD.inv(a.lon, a.lat, b.lon, b.lat)
    return m / 1000.0


class _FastSampler:
    """Nearest-cell lookup on a plain numpy array.

    xarray ``.sel(method='nearest')`` costs ~1000× more per call than index
    arithmetic — irrelevant for one-off point reads, decisive inside A*,
    which samples hazard fields tens of thousands of times per route.
    Values are read-only snapshots; the fields do not change during a route.
    """

    __slots__ = ("vals", "lats", "lons")

    def __init__(self, da: xr.DataArray | None) -> None:
        ok = False
        vals = lats = lons = None
        if da is not None and not da.size == 0:
            v = da
            if "time" in v.dims and v.sizes.get("time", 0) > 1:
                v = v.isel(time=-1, drop=True)
            vals = np.asarray(v.values, dtype=float)
            lat_c = v.coords.get("latitude")
            lon_c = v.coords.get("longitude")
            if vals.ndim == 2 and lat_c is not None and lon_c is not None:
                lats = np.asarray(lat_c.values, dtype=float)
                lons = np.asarray(lon_c.values, dtype=float)
                ok = lats.ndim == 1 and lons.ndim == 1 and vals.shape == (lats.size, lons.size)
        if not ok:
            vals = lats = lons = None
        self.vals = vals
        self.lats = lats
        self.lons = lons

    def at(self, lat: float, lon: float) -> float | None:
        if self.vals is None:
            return None
        j = int(np.abs(self.lats - lat).argmin())
        i = int(np.abs(self.lons - lon).argmin())
        v = self.vals[j, i]
        return float(v) if math.isfinite(v) else None


class ZoneEvaluationService:
    def __init__(
        self,
        hub: OceanDataHub,
        safety: GeospatialSafetyEngine,
        front_engine: FrontDetectionEngine | None = None,
        scorer: RecommendationScoringEngine | None = None,
        n_bearings: int = 24,
        vessel_speed_knots: float = 6.5,
        max_zones_returned: int = 12,
        ais: "AisProvider | None" = None,
    ) -> None:
        self.hub = hub
        self.safety = safety
        self.front_engine = front_engine or FrontDetectionEngine(GradientFrontStrategy())
        self.scorer = scorer or RecommendationScoringEngine()
        self.n_bearings = n_bearings
        self.vessel_speed_knots = vessel_speed_knots
        self.max_zones_returned = max_zones_returned
        self._pre_excluded: dict[str, str] = {}
        self._fields: dict[str, OceanField] = {}
        self.ais = ais or self._default_ais_provider()

    @staticmethod
    def _default_ais_provider() -> "AisProvider | None":
        """Demo packs may carry a (clearly-labeled) AIS file; ops mode wires
        a live feed via app.services.ais.decode_nmea. No pack → None."""
        from app.services.ais import FileAisProvider

        settings = get_settings()
        if settings.demo_dir.exists():
            for pack in sorted(settings.demo_dir.iterdir()):
                if (pack / "ais.json").exists():
                    return FileAisProvider(pack)
        return None

    # --------------------------------------------------------------- AIS ctx
    async def _ais_context(self, recommended: ZoneEvaluation | None) -> tuple[list[GeoJSONFeature], list[Evidence]]:
        """Traffic context around the recommended zone (Phase 8).

        Counts vessels within AIS_TRAFFIC_RADIUS_KM; every claim is labeled
        when the source pack is synthetic. No AIS source → no claim at all.
        """
        if self.ais is None or recommended is None:
            return [], []
        try:
            vessels = await self.ais.vessels_in_bbox(self._bbox_of([recommended.candidate], LatLon(lat=recommended.candidate.lat, lon=recommended.candidate.lon)))
        except Exception:  # noqa: BLE001 — traffic context must never kill the advisory
            logger.exception("AIS provider failed")
            return [], []
        if not vessels:
            return [], []
        from app.services.ais import count_within_radius

        n = count_within_radius(vessels, recommended.candidate.lat, recommended.candidate.lon, AIS_TRAFFIC_RADIUS_KM)
        synthetic = all(v.synthetic for v in vessels)
        claim = (
            f"{n} AIS vessel report(s) within {AIS_TRAFFIC_RADIUS_KM:.0f} km of the recommended zone"
            + (" [SYNTHETIC demo traffic]" if synthetic else "")
        )
        evidence = [
            Evidence(
                claim=claim,
                basis="AIS ingestion (app.services.ais)" + (" — SYNTHETIC demo pack" if synthetic else ""),
                value=float(n),
                unit="count",
            )
        ]
        features = [
            GeoJSONFeature(
                geometry={"type": "Point", "coordinates": [v.lon, v.lat]},
                properties={
                    "kind": "ais",
                    "mmsi": v.mmsi,
                    "vessel_type": v.vessel_type,
                    "synthetic": v.synthetic,
                    "name": f"AIS {v.mmsi}",
                },
            )
            for v in vessels
        ]
        return features, evidence

    # ---------------------------------------------------------- candidates
    # Deterministic radius spread (fractions of the requested distance). A
    # single-radius ring reads as an artificial circle on the chart; this
    # spread scatters candidates across the 0.75–1.25× annulus so the layout
    # matches how real fishing grounds are charted. Same pattern every run.
    _RADII_SPREAD = (0.75, 1.0, 1.25)

    def generate_candidates(self, origin: LatLon, distance_km: float) -> list[ZoneCandidate]:
        """Ring candidates every (360/n)° with a deterministic radius spread;
        hard-constraint failures kept and flagged so the response can show
        *why* a bearing was excluded."""
        band_m = get_settings().coastal_exclusion_band_m
        candidates: list[ZoneCandidate] = []
        self._pre_excluded = {}
        for i in range(self.n_bearings):
            bearing = i * (360.0 / self.n_bearings)
            radius_km = distance_km * self._RADII_SPREAD[i % len(self._RADII_SPREAD)]
            lon2, lat2, _back = _GEOD.fwd(origin.lon, origin.lat, bearing, radius_km * 1000.0)
            cand = ZoneCandidate(
                id=f"zone-{i:02d}",
                lat=round(float(lat2), 4),
                lon=round(float(lon2), 4),
                bearing_deg=round(bearing, 1),
                distance_from_origin_km=round(radius_km, 1),
            )
            geofence = self.safety.check_geofence(LatLon(lat=cand.lat, lon=cand.lon))
            if not geofence.ok:
                reasons = [w.code for w in geofence.warnings if w.severity == "critical"]
                self._pre_excluded[cand.id] = "/".join(reasons) if reasons else "hard constraint"
                continue
            # coastal band: shoreline datasets disagree by kilometres around
            # complicated coasts, and zones hugging the surf are not usable —
            # require a minimum clearance from the land polygons
            d_land = self.safety.distance_to_land(LatLon(lat=cand.lat, lon=cand.lon))
            if d_land is not None and d_land < band_m:
                self._pre_excluded[cand.id] = "COASTAL_BAND"
                continue
            candidates.append(cand)
        return candidates

    # ------------------------------------------------------------- sampling
    @staticmethod
    def _sample(da: xr.DataArray | None, lat: float, lon: float) -> float | None:
        if da is None or da.size == 0 or "latitude" not in da.dims:
            return None
        try:
            sel = da.sel(latitude=lat, longitude=lon, method="nearest")
            v = float(np.asarray(sel.values).squeeze())
            if math.isfinite(v):
                return v
            # cloud-masked (or otherwise missing) at the exact pixel: mean the
            # finite cells in a small ±3-cell neighbourhood — deterministic,
            # and honest for 4 km ocean-colour products with single-pixel holes
            lat_idx = da.indexes["latitude"].get_indexer([sel.latitude.item()], method="nearest")[0]
            lon_idx = da.indexes["longitude"].get_indexer([sel.longitude.item()], method="nearest")[0]
            win = da.isel(
                latitude=slice(max(0, lat_idx - 3), lat_idx + 4),
                longitude=slice(max(0, lon_idx - 3), lon_idx + 4),
            )
            vals = np.asarray(win.values, dtype=float)
            finite = vals[np.isfinite(vals)]
            return float(finite.mean()) if finite.size else None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _bbox_of(candidates: list[ZoneCandidate], origin: LatLon, margin_deg: float = 0.6) -> BoundingBox:
        lats = [origin.lat] + [c.lat for c in candidates]
        lons = [origin.lon] + [c.lon for c in candidates]
        return BoundingBox(
            south=min(lats) - margin_deg, north=max(lats) + margin_deg,
            west=min(lons) - margin_deg, east=max(lons) + margin_deg,
        )

    # ------------------------------------------------------------ evaluation
    async def evaluate(
        self, origin: LatLon, parsed: ParsedQuery, request_id: str | None = None
    ) -> RecommendationResponse:
        request_id = request_id or uuid.uuid4().hex[:12]
        settings = get_settings()
        trace = WorkflowTrace(steps=[], started_at=datetime.now(timezone.utc))

        # ---- 1. time window (default: tomorrow 07:00 IST — dawn departure)
        if parsed.time_window:
            valid_time = parsed.time_window.start.replace(tzinfo=parsed.time_window.start.tzinfo or timezone.utc)
        else:
            ist = timezone(timedelta(hours=5.5))
            valid_time = (datetime.now(ist) + timedelta(days=1)).replace(
                hour=7, minute=0, second=0, microsecond=0
            ).astimezone(timezone.utc)
        distance_km = parsed.distance_km or 20.0

        # ---- 2. candidates
        candidates = self.generate_candidates(origin, distance_km)
        trace.steps.append(
            f"generated {self.n_bearings} ring candidates, "
            f"{len(candidates)} passed hard pre-filter "
            f"({len(self._pre_excluded)} excluded: {sorted(set(self._pre_excluded.values()))})"
        )

        if not candidates:
            return self._insufficient_response(
                request_id, parsed, trace,
                InsufficiencyReason(
                    code="NO_ACCESSIBLE_ZONES",
                    detail="All candidate zones at the requested distance violate hard constraints (land/boundary/protected areas).",
                ),
            )

        # ---- 3. fetch fields once per variable over the whole ring box
        # Concurrent across variables: a dead ERDDAP server blackholes until
        # connect-timeout, and sequential fetches would stack those penalties
        # (7 variables × servers × timeout) past the edge proxy's patience.
        # Priority ordering is preserved WITHIN each variable.
        bbox = self._bbox_of(candidates, origin)

        async def _fetch_one(var: str) -> OceanField:
            try:
                return await self.hub.get_field(var, bbox, valid_time)
            except Exception as exc:  # noqa: BLE001
                logger.warning("field fetch failed for %s: %s", var, exc)
                return OceanField.empty(
                    var, "unknown",
                    Provenance(source_id="none", source_name="fetch-failed", mode=settings.data_mode),
                    bbox,
                )

        variables = ("sst", "chlorophyll", "wave_height", "wind_u", "wind_v", "current_u", "current_v")
        t_fields = time.perf_counter()

        # official hazard warnings run concurrently with the field fetches —
        # they are independent network I/O and must never stack on top
        official_task = asyncio.create_task(
            official_warnings(
                bbox,
                valid_time,
                incois_api_key=settings.incois_api_key,
                imd_alerts_url=settings.imd_alerts_url,
                imd_api_key=settings.imd_api_key,
                incois_base_url=settings.incois_alerts_base_url,
                include_gdacs=settings.gdacs_enabled,
                timeout=settings.official_warnings_timeout_seconds,
            )
        )

        self._fields = dict(zip(variables, await asyncio.gather(*(_fetch_one(v) for v in variables))))
        fields = self._fields
        trace.steps.append(
            "fetched ocean fields: "
            + ", ".join(f"{k}={'ok' if not v.is_empty else 'MISSING'}" for k, v in fields.items())
            + f" ({time.perf_counter() - t_fields:.1f}s)"
        )

        # ---- 4. front detection (deterministic)
        sst_front: FrontResult | None = None
        chl_front: FrontResult | None = None
        if not fields["sst"].is_empty:
            sst_front = self.front_engine.detect_sst_fronts(fields["sst"])
        chl_field_log = self._log_field(fields["chlorophyll"])
        if chl_field_log is not None and not chl_field_log.is_empty:
            chl_front = self.front_engine.detect_chlorophyll_fronts(chl_field_log)
        trace.steps.append(f"front detection: sst={'ok' if sst_front else 'missing'} chl={'ok' if chl_front else 'missing'}")

        # gradient fields for per-candidate strength
        sst_grad = sst_front.gradient if sst_front else None
        chl_grad = chl_front.gradient if chl_front else None

        # current speed field
        current_speed = self._speed_field(fields.get("current_u"), fields.get("current_v"))

        # ---- 5. per-candidate evaluation
        t_zones = time.perf_counter()
        zones: list[ZoneEvaluation] = []
        for cand in candidates:
            zone = await self._evaluate_one(
                cand, origin, valid_time, fields, sst_grad, chl_grad, current_speed,
                sst_front, chl_front,
            )
            zones.append(zone)
        zone_s = time.perf_counter() - t_zones

        # ---- 6. rank (excluded last, then by overall score desc)
        zones.sort(key=lambda z: (z.excluded, -(z.score.overall_score if z.score.overall_score is not None else -999)))
        for rank, zone in enumerate(zones, start=1):
            if not zone.excluded:
                zone.rank = rank

        # ---- 7. data availability + insufficient verdict
        availability = {k: not v.is_empty for k, v in fields.items()}
        n_missing_products = sum(1 for ok in availability.values() if not ok)
        scored = [z for z in zones if not z.excluded]
        best = next((z for z in scored if not z.score.insufficient), None)

        warnings: list[OrcaWarning] = []
        official_sources: list[Provenance] = []
        if settings.data_mode is DataMode.DEMO:
            warnings.append(
                OrcaWarning(severity="info", code="DEMO_MODE",
                            message="Served from cached DEMO data pack — values are not live observations.",
                            source="orca")
            )
        if n_missing_products >= 4:
            warnings.append(OrcaWarning(severity="caution", code="MANY_MISSING_PRODUCTS",
                                        message=f"{n_missing_products} of {len(availability)} ocean products unavailable from providers.",
                                        source="orca",
                                        params={"count": n_missing_products, "total": len(availability)}))
        if availability.get("wave_height") is False:
            warnings.append(OrcaWarning(severity="warning", code="NO_WAVE_DATA",
                                        message="No wave data available — wave risk NOT evaluated. Treat safety assessment as incomplete.",
                                        source="orca"))

        # deterministic hazard cautions from the recommended zone's own
        # measurements (never fabricated: only fires when a value exists)
        if best is not None:
            vals = {m.variable: m.value for m in best.measurements}
            wave_m = vals.get("wave_height_m")
            wind_kmh = vals.get("wind_speed_kmh")
            if wave_m is not None and wave_m >= ROUGH_SEA_M:
                warnings.append(OrcaWarning(
                    severity="caution", code="ROUGH_SEA",
                    message=f"Waves of {wave_m:.1f} m expected at the recommended zone — rough sea; small craft should be cautious.",
                    source="orca",
                    params={"wave_m": round(wave_m, 1)}))
            if wind_kmh is not None and wind_kmh >= STRONG_WIND_KMH:
                warnings.append(OrcaWarning(
                    severity="caution", code="STRONG_WIND",
                    message=f"Wind of {wind_kmh:.0f} km/h expected at the recommended zone — strong wind; handle small craft with care.",
                    source="orca",
                    params={"wind_kmh": round(wind_kmh, 0)}))

        # ---- official hazard warnings (GDACS / INCOIS / IMD) — deterministic
        # ingestion of machine-readable alert feeds; failures degrade to notes
        # inside the result, never to a fabricated "no warnings".
        try:
            official = await official_task
        except Exception as exc:  # noqa: BLE001 — warnings are best-effort context
            logger.warning("official warnings failed: %s", exc)
            official = OfficialWarningResult(notes=[f"official warning feeds failed ({type(exc).__name__})"])
        official_sources.extend(official.provenance)
        warnings.extend(official.warnings)
        if official.warnings:
            codes = ", ".join(sorted({w.code or "?" for w in official.warnings}))
            trace.steps.append(f"official warnings: {len(official.warnings)} active ({codes})")
        trace.steps.append("official warning feeds: " + "; ".join(official.notes))

        recommended = best
        route_out: RouteOut | None = None
        if recommended is not None:
            t_route = time.perf_counter()
            route = await self._build_route(origin, recommended)
            route_s = time.perf_counter() - t_route
            route_out = self._route_to_out(route)
            trace.steps.append(
                f"ranked {len(scored)} scorable zones; recommended {recommended.candidate.id} "
                f"(overall={recommended.score.overall_score}); safe route {route_out.distance_km:.1f} km "
                f"({zone_s:.1f}s zone scoring, {route_s:.1f}s routing)"
            )
        else:
            trace.steps.append(f"ranked {len(scored)} scorable zones; none scoreable → INSUFFICIENT_DATA")

        # ---- 8. evidence + sources (+ AIS traffic context, Phase 8)
        evidence = self._build_evidence(recommended, sst_front, chl_front)
        sources = self._collect_sources(fields, sst_front, chl_front)
        sources.extend(official_sources)
        ais_features, ais_evidence = await self._ais_context(recommended)
        evidence.extend(ais_evidence)

        insufficient = None
        if best is None:
            insufficient = InsufficiencyReason(
                code="INSUFFICIENT_DATA",
                detail="No zone could be scored with the currently available data (see missing variables).",
                missing_variables=[k for k, ok in availability.items() if not ok],
            )

        trace.finished_at = datetime.now(timezone.utc)
        trace.duration_seconds = round((trace.finished_at - trace.started_at).total_seconds(), 2)

        return RecommendationResponse(
            request_id=request_id,
            parsed_query=parsed,
            mode=settings.data_mode.value,
            demo_banner_required=settings.data_mode is DataMode.DEMO,
            generated_at=datetime.now(timezone.utc),
            valid_time=valid_time,
            data_available=availability,
            zones=zones[: self.max_zones_returned],
            recommended=recommended,
            route=route_out,
            map_layers=self._map_layers(origin, distance_km) + ais_features,
            warnings=warnings,
            evidence=evidence,
            sources=sources,
            insufficient=insufficient,
            trace=trace,
        )

    # ------------------------------------------------------------ internals
    def _map_layers(self, origin: LatLon | None = None, radius_km: float | None = None) -> list[GeoJSONFeature]:
        """Boundary layers (IMBL/MPA/land, authority-labeled) for the map UI.

        When ``origin``/``radius_km`` are given, a deterministic geodesic
        ``search_ring`` polygon (the circle the candidates were generated on)
        is appended so users can see exactly where ORCA looked.
        """
        layers: list[GeoJSONFeature] = []
        from app.engines.geospatial.layers import layers_to_geojson

        try:
            fc = layers_to_geojson(self.safety.layers())
            layers.extend(
                GeoJSONFeature(geometry=f["geometry"], properties=f.get("properties", {}))
                for f in fc["features"]
            )
        except Exception:  # noqa: BLE001 — map decoration must never kill the advisory
            pass
        if origin is not None and radius_km is not None:
            try:
                layers.append(self._search_ring_feature(origin, radius_km))
            except Exception:  # noqa: BLE001
                logger.warning("search-ring generation failed", exc_info=True)
        return layers

    @staticmethod
    def _search_ring_feature(origin: LatLon, radius_km: float) -> GeoJSONFeature:
        """Geodesic circle (pyproj, 5° steps) — the candidate search ring."""
        coords: list[list[float]] = []
        for bearing in range(0, 360, 5):
            lon2, lat2, _ = _GEOD.fwd(origin.lon, origin.lat, float(bearing), radius_km * 1000.0)
            coords.append([round(float(lon2), 5), round(float(lat2), 5)])
        coords.append(coords[0])  # GeoJSON rings must be closed
        return GeoJSONFeature(
            geometry={"type": "Polygon", "coordinates": [coords]},
            properties={
                "kind": "search_ring",
                "name": f"Search ring — {radius_km:g} km from origin",
                "radius_km": radius_km,
                "origin": [origin.lon, origin.lat],
                "authority": "orca",
                "hard_constraint": False,
            },
        )
    async def _evaluate_one(
        self,
        cand: ZoneCandidate,
        origin: LatLon,
        valid_time: datetime,
        fields: dict[str, OceanField],
        sst_grad: xr.DataArray | None,
        chl_grad: xr.DataArray | None,
        current_speed: xr.DataArray | None,
        sst_front: FrontResult | None,
        chl_front: FrontResult | None,
    ) -> ZoneEvaluation:
        point = LatLon(lat=cand.lat, lon=cand.lon)
        geofence = self.safety.check_geofence(point)
        measurements: list[Measurement] = []

        sst_val = self._sample(fields["sst"].data, cand.lat, cand.lon)
        chl_val = self._sample(fields["chlorophyll"].data, cand.lat, cand.lon)
        wave_val = self._sample(fields["wave_height"].data, cand.lat, cand.lon)
        wind_u = self._sample(fields["wind_u"].data, cand.lat, cand.lon)
        wind_v = self._sample(fields["wind_v"].data, cand.lat, cand.lon)
        cur_speed = self._sample(current_speed, cand.lat, cand.lon)
        sst_front_local = self._sample(sst_grad, cand.lat, cand.lon)
        chl_front_local = self._sample(chl_grad, cand.lat, cand.lon)

        measurements.append(self._as_measurement("sst_c", sst_val, "°C", fields["sst"]))
        measurements.append(self._as_measurement("chlorophyll_mg_m3", chl_val, "mg m-3", fields["chlorophyll"]))
        measurements.append(self._as_measurement("wave_height_m", wave_val, "m", fields["wave_height"]))
        if wind_u is not None and wind_v is not None:
            measurements.append(self._as_measurement("wind_speed_kmh", math.hypot(wind_u, wind_v) * 3.6, "km/h", fields["wind_u"]))
        measurements.append(self._as_measurement("current_speed_ms", cur_speed, "m s-1", fields.get("current_u", fields.get("current_v"))))

        dist_imbl_m = self.safety.distance_to_imbl(point)
        dist_imbl_km = (dist_imbl_m / 1000.0) if dist_imbl_m is not None else None

        wind_kmh = math.hypot(wind_u, wind_v) * 3.6 if wind_u is not None and wind_v is not None else None
        score = self.scorer.score_zone(
            sst_front_strength=sst_front_local,
            chl_value=chl_val,
            chl_gradient=chl_front_local,
            current_speed_ms=cur_speed,
            wave_height_m=wave_val,
            wind_speed_kmh=wind_kmh,
            distance_to_boundary_km=dist_imbl_km,
        )
        excluded = geofence is not None and not geofence.ok
        reason = None
        if excluded:
            critical = [w.code for w in geofence.warnings if w.severity == "critical"]
            reason = "/".join(critical) if critical else "hard constraint violation"
        return ZoneEvaluation(
            candidate=cand,
            score=score,
            measurements=measurements,
            front_strength={"sst_front_c_per_km": sst_front_local, "chl_gradient_log_per_km": chl_front_local},
            geofence=geofence,
            distance_to_boundary_km=round(dist_imbl_km, 2) if dist_imbl_km is not None else None,
            excluded=excluded,
            exclusion_reason=reason,
        )

    @staticmethod
    def _as_measurement(variable: str, value: float | None, unit: str, field: OceanField | None) -> Measurement:
        if field is None or field.is_empty:
            prov = Provenance(source_id="none", source_name="unavailable", mode=get_settings().data_mode)
            return Measurement(variable=variable, value=None, unit=unit, provenance=prov, quality=QualityFlag.MISSING)
        prov = field.provenance.model_copy(deep=True)
        # an older observation must not present as current — the UI renders
        # STALE as a "cached" badge and shows prov.valid_time (the real date)
        flag = QualityFlag.OK
        if value is not None and prov.valid_time is not None:
            vt = prov.valid_time if prov.valid_time.tzinfo else prov.valid_time.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - vt).total_seconds() > 3 * 86400:
                flag = QualityFlag.STALE
        return Measurement(
            variable=variable,
            value=value,
            unit=unit,
            provenance=prov,
            quality=flag if value is not None else QualityFlag.MISSING,
        )

    @staticmethod
    def _log_field(field: OceanField | None) -> OceanField | None:
        """log10 transform for chlorophyll (spans decades)."""
        if field is None or field.is_empty:
            return None
        da = field.data
        if "time" in da.dims:
            da = da.isel(time=-1, drop=True)
        vals = da.values.astype(float)
        with np.errstate(all="ignore"):
            logged = np.where(vals > 0, np.log10(vals), np.nan)
        return OceanField(variable=f"log10({field.variable})", unit="log10(mg m-3)", data=da.copy(data=logged), provenance=field.provenance, bbox=field.bbox)

    @staticmethod
    def _speed_field(u: OceanField | None, v: OceanField | None) -> xr.DataArray | None:
        if u is None or v is None or u.is_empty or v.is_empty:
            return None
        da_u, da_v = u.data, v.data
        if "time" in da_u.dims:
            da_u = da_u.isel(time=-1, drop=True)
        if "time" in da_v.dims:
            da_v = da_v.isel(time=-1, drop=True)
        try:
            speed = np.hypot(da_u.values, da_v.values)
            return da_u.copy(data=speed)
        except Exception:  # noqa: BLE001
            return None

    async def _build_route(self, origin: LatLon, zone: ZoneEvaluation) -> Route:
        dest = LatLon(lat=zone.candidate.lat, lon=zone.candidate.lon)
        engine = RouteOptimizationEngine(
            safety_engine=self.safety,
            hazard_sampler=self._route_hazard_sampler(),
            vessel_speed_knots=self.vessel_speed_knots,
            # 0.025° ≈ 2.7 km cells: fine enough to thread the Palk Strait /
            # Pamban channel (a 5.5 km cell could not resolve the island
            # passages) while keeping A* in the sub-second range.
            cell_deg=0.025,
        )
        return engine.calculate_safe_route(origin, dest)

    def _route_hazard_sampler(self):
        """Hazard sampler for the router, built ONCE per route.

        Fields are already in memory (no network); the numpy-backed
        samplers make each cell read ~µs instead of an xarray `.sel()`.
        """
        from app.engines.routing.engine import HazardSample

        wave = _FastSampler(self._latest(self._fields.get("wave_height")))
        wind_u = _FastSampler(self._latest(self._fields.get("wind_u")))
        wind_v = _FastSampler(self._latest(self._fields.get("wind_v")))
        cur_u = _FastSampler(self._latest(self._fields.get("current_u")))
        cur_v = _FastSampler(self._latest(self._fields.get("current_v")))

        def sample(lat: float, lon: float) -> HazardSample:
            wu = wind_u.at(lat, lon)
            wv = wind_v.at(lat, lon)
            return HazardSample(
                wave_height_m=wave.at(lat, lon),
                wind_speed_ms=math.hypot(wu, wv) if wu is not None and wv is not None else None,
                current_u_ms=cur_u.at(lat, lon),
                current_v_ms=cur_v.at(lat, lon),
            )

        return sample

    @staticmethod
    def _latest(field: OceanField | None) -> xr.DataArray | None:
        if field is None or field.is_empty:
            return None
        da = field.data
        if "time" in da.dims and da.sizes.get("time", 0) > 1:
            da = da.isel(time=-1, drop=True)
        return da

    @staticmethod
    def _route_to_out(route: Route) -> RouteOut:
        return RouteOut(
            mode=route.mode,
            coords=route.coords_lonlat,
            distance_km=route.distance_km,
            estimated_time_h=route.estimated_time_h,
            hazard_stats=route.hazard_stats,
            blocked_by_constraints=route.blocked_by_constraints,
            notes=route.notes,
        )

    def _build_evidence(
        self, zone: ZoneEvaluation | None, sst_front: FrontResult | None, chl_front: FrontResult | None
    ) -> list[Evidence]:
        if zone is None:
            return []
        evidence: list[Evidence] = []
        for m in zone.measurements:
            if m.value is None:
                continue
            evidence.append(
                Evidence(
                    claim=f"{m.variable} = {round(m.value, 3)} {m.unit}",
                    basis="provider measurement at zone point",
                    measurement_variable=m.variable,
                    value=m.value,
                    unit=m.unit,
                    provenance=m.provenance,
                )
            )
        if zone.distance_to_boundary_km is not None:
            evidence.append(
                Evidence(
                    claim=f"distance to maritime boundary ≈ {zone.distance_to_boundary_km} km",
                    basis="GeospatialSafetyEngine geodesic distance (reference boundary geometry)",
                    computation="geospatial.distance_to_imbl",
                )
            )
        if zone.geofence is not None:
            evidence.append(
                Evidence(
                    claim="no hard-constraint violation (boundary/MPA/land)" if zone.geofence.ok else "hard-constraint violation",
                    basis="GeospatialSafetyEngine.check_geofence",
                    computation="geospatial.check_geofence",
                )
            )
        return evidence

    def _collect_sources(
        self, fields: dict[str, OceanField], sst_front: FrontResult | None, chl_front: FrontResult | None
    ) -> list[Provenance]:
        seen: dict[str, Provenance] = {}
        for f in fields.values():
            if f.provenance.source_id not in seen:
                seen[f.provenance.source_id] = f.provenance
        return list(seen.values())

    def _insufficient_response(
        self, request_id: str, parsed: ParsedQuery, trace: WorkflowTrace, reason: InsufficiencyReason
    ) -> RecommendationResponse:
        trace.finished_at = datetime.now(timezone.utc)
        trace.duration_seconds = round((trace.finished_at - trace.started_at).total_seconds(), 2)
        return RecommendationResponse(
            request_id=request_id,
            parsed_query=parsed,
            mode=get_settings().data_mode.value,
            demo_banner_required=get_settings().data_mode is DataMode.DEMO,
            generated_at=datetime.now(timezone.utc),
            insufficient=reason,
            warnings=[OrcaWarning(severity="warning", code=reason.code, message=reason.detail, source="orca")],
            trace=trace,
        )
