"""Phase 5 smoke test: full advisory pipeline over synthetic ocean fields.

Temporary integration check (pytest suites come in Phase 10). Builds a fake
hub whose fields contain a known SST front and verifies the whole pipeline:
parse → ring candidates → sampling → front detection → scoring → ranking →
route → evidence → explanation, with the geospatial safety engine active.
"""

import asyncio
import logging
import sys
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import xarray as xr

warnings.filterwarnings("ignore")
logging.disable(logging.INFO)
sys.path.insert(0, "H:/orca/backend")

from app.config.settings import get_settings  # noqa: E402
from app.engines.geospatial.safety import GeospatialSafetyEngine  # noqa: E402
from app.providers.base import OceanField  # noqa: E402
from app.schemas.common import BoundingBox, Provenance  # noqa: E402
from app.services.zone_evaluator import ZoneEvaluationService  # noqa: E402

RAMESWARAM = (9.29, 79.31)
BBOX = BoundingBox(south=8.5, north=10.1, west=78.5, east=80.1)
N = 33


def grid(vals=None, base=0.0):
    lats = np.linspace(BBOX.south, BBOX.north, N)
    lons = np.linspace(BBOX.west, BBOX.east, N)
    if vals is None:
        vals = np.full((N, N), base)
    return xr.DataArray(
        vals,
        coords={"latitude": lats, "longitude": lons},
        dims=("latitude", "longitude"),
    )


def prov(var):
    return Provenance(
        source_id="smoke", source_name="synthetic smoke data", dataset="synthetic",
        retrieved_at=datetime.now(timezone.utc), valid_time=datetime.now(timezone.utc),
        spatial_resolution="0.05 deg", unit="synthetic", confidence=1.0, mode="demo",
    )


class SmokeHub:
    """Hub stand-in: warm-water front running N-S at 79.55°E (east of origin)."""

    async def get_field(self, variable, bbox, valid_time):
        lats = np.linspace(BBOX.south, BBOX.north, N)
        lons = np.linspace(BBOX.west, BBOX.east, N)
        LON, LAT = np.meshgrid(lons, lats)
        if variable == "sst":
            vals = 28.0 + 1.6 / (1.0 + np.exp(-(LON - 79.55) / 0.06))  # sharp front
            return OceanField(variable, "°C", grid(vals), prov(variable), BBOX)
        if variable == "chlorophyll":
            vals = 0.4 + 1.8 / (1.0 + np.exp(-(LON - 79.62) / 0.10))  # co-located bloom
            return OceanField(variable, "mg m-3", grid(vals), prov(variable), BBOX)
        if variable == "wave_height":
            return OceanField(variable, "m", grid(base=0.9), prov(variable), BBOX)
        if variable == "wind_u":
            return OceanField(variable, "m s-1", grid(base=-2.0), prov(variable), BBOX)
        if variable == "wind_v":
            return OceanField(variable, "m s-1", grid(base=3.0), prov(variable), BBOX)
        if variable in ("current_u", "current_v"):
            return OceanField(variable, "m s-1", grid(base=0.1), prov(variable), BBOX)
        return OceanField.empty(variable, "unknown", prov(variable), BBOX)


async def main():
    settings = get_settings()
    safety = GeospatialSafetyEngine.from_directory(settings.boundaries_dir)
    svc = ZoneEvaluationService(SmokeHub(), safety, vessel_speed_knots=6.5)

    from app.schemas.recommendation import ParsedQuery
    from app.services.place_resolver import PlaceResolver

    origin_resolved = await PlaceResolver().resolve("Rameswaram")
    parsed = ParsedQuery(raw_text="smoke test", origin=origin_resolved, distance_km=20.0)

    from app.schemas.common import LatLon

    resp = await svc.evaluate(LatLon(lat=origin_resolved.lat, lon=origin_resolved.lon), parsed, request_id="smoke001")

    print("mode:", resp.mode, "| zones returned:", len(resp.zones))
    print("data_available:", resp.data_available)
    for z in resp.zones[:6]:
        s = z.score
        print(
            f"  {z.candidate.id} brg={z.candidate.bearing_deg:5.1f} "
            f"overall={s.overall_score} prod={s.productivity_score} risk={s.risk_score} "
            f"cov={s.weight_coverage} excl={z.excluded} rank={z.rank}"
        )
    print("recommended:", resp.recommended.candidate.id if resp.recommended else None)
    print("  measurements:", [(m.variable, None if m.value is None else round(m.value, 3)) for m in resp.recommended.measurements] if resp.recommended else None)
    print("  front_strength:", {k: (round(v, 3) if v else v) for k, v in (resp.recommended.front_strength.items() if resp.recommended else {})})
    print("route:", None if resp.route is None else (round(resp.route.distance_km, 2), "km", round(resp.route.estimated_time_h, 2), "h"))
    print("warnings:", [(w.code, w.severity) for w in resp.warnings])
    print("insufficient:", resp.insufficient.code if resp.insufficient else None)
    print("evidence:", len(resp.evidence), "| sources:", len(resp.sources))
    print("trace:", len(resp.trace.steps), "steps |", round(resp.trace.duration_seconds, 2), "s")

    assert resp.recommended is not None, "expected a recommendation with synthetic data"
    assert resp.recommended.score.overall_score is not None
    rec = resp.recommended
    # the front is EAST of origin → the best zone should be on an eastward bearing
    assert 45.0 <= rec.candidate.bearing_deg <= 135.0, f"expected eastward winner, got {rec.candidate.bearing_deg}"
    assert resp.route is not None and resp.route.distance_km > 0
    assert resp.insufficient is None
    assert len(resp.evidence) >= 3
    print("\nOK: pipeline end-to-end (parse → evaluate → rank → route → evidence)")


asyncio.run(main())
