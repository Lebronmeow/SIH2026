"""The eight critical acceptance tests mandated by the ORCA specification.

Each test maps 1:1 to a hard product rule:

1. ``test_restricted_polygon_never_traversed``  — routing hard constraint (MPA)
2. ``test_route_never_crosses_imbl``            — routing hard constraint (IMBL)
3. ``test_missing_data_never_fabricated``       — INSUFFICIENT_DATA, never invented values
4. ``test_stale_data_is_flagged``               — stale/cached data is never presented as live
5. ``test_user_constraints_retained``           — user query parameters survive the pipeline
6. ``test_evidence_maps_to_data``               — every evidence claim traces to a measurement
7. ``test_demo_mode_is_labeled``                — DEMO / CACHED DATA disclosure
8. ``test_units_are_explicit``                  — every available measurement carries a unit
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from shapely.geometry import LineString

from app.agents.query_parser import DeterministicQueryParser
from app.config.settings import get_settings
from app.engines.geospatial.safety import GeospatialSafetyEngine
from app.engines.routing.engine import RouteOptimizationEngine
from app.providers.demo_provider import DemoOceanProvider
from app.providers.hub import OceanDataHub
from app.schemas.common import LatLon, QualityFlag
from app.workflows.advisory import FishingAdvisoryWorkflow
from tests.conftest import run

CANONICAL_QUERY = (
    "Where is the safest and most productive fishing zone 20 km off Rameswaram tomorrow morning?"
)


def _write_layer(directory, feature) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "test_layer.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))


@pytest.fixture(scope="module")
def demo():
    """One full pipeline run over the committed demo pack, shared by tests 6-8."""
    workflow = FishingAdvisoryWorkflow()
    response = run(workflow.run(CANONICAL_QUERY))
    return workflow, response


# 1 ----------------------------------------------------------------- routing
def test_restricted_polygon_never_traversed(tmp_path):
    """A hard-constraint MPA between origin and destination is never crossed."""
    mpa = {
        "type": "Feature",
        "properties": {
            "id": "test-mpa",
            "name": "Test MPA",
            "kind": "mpa",
            "authority": "reference",
            "source_id": "test-suite",
            "hard_constraint": True,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[79.38, 9.28], [79.44, 9.28], [79.44, 9.32], [79.38, 9.32], [79.38, 9.28]]],
        },
    }
    _write_layer(tmp_path, mpa)
    safety = GeospatialSafetyEngine.from_directory(tmp_path)
    origin, dest = LatLon(lat=9.25, lon=79.30), LatLon(lat=9.35, lon=79.52)

    # guard: the straight line WOULD cross the polygon (test is meaningful)
    assert LineString([(origin.lon, origin.lat), (dest.lon, dest.lat)]).intersects(safety.layers()[0].geometry)

    engine = RouteOptimizationEngine(safety, cell_deg=0.02)
    route = engine.calculate_safe_route(origin, dest)

    assert route.coords, "a detour exists around the MPA and must be found"
    assert not route.blocked_by_constraints
    safety_result = safety.check_route_safety(route.coords_lonlat)
    assert safety_result.ok
    assert not safety_result.crosses_restricted
    # belt and braces: no individual waypoint inside the polygon either
    for coord in route.coords:
        assert not safety.is_inside_restricted_area(coord)


def test_route_never_crosses_imbl(tmp_path):
    """A fully-spanning IMBL line makes the destination unreachable — the
    router must give up (blocked), never produce a crossing path."""
    imbl = {
        "type": "Feature",
        "properties": {
            "id": "test-imbl",
            "name": "Test maritime boundary",
            "kind": "imbl",
            "authority": "reference",
            "source_id": "test-suite",
            "hard_constraint": True,
        },
        "geometry": {"type": "LineString", "coordinates": [[79.50, 8.0], [79.50, 10.0]]},
    }
    _write_layer(tmp_path, imbl)
    safety = GeospatialSafetyEngine.from_directory(tmp_path)
    engine = RouteOptimizationEngine(safety)
    route = engine.calculate_safe_route(LatLon(lat=9.30, lon=79.30), LatLon(lat=9.30, lon=79.65))

    assert route.blocked_by_constraints, "no legal path exists and none may be invented"
    assert not route.coords
    safety_result = safety.check_route_safety(route.coords_lonlat)
    assert not safety_result.crosses_imbl


# 3 ------------------------------------------------------- honest data gaps
def test_missing_data_never_fabricated(tmp_path, monkeypatch):
    """An empty data pack → INSUFFICIENT_DATA verdict, no recommendation,
    no invented measurement values anywhere in the response."""
    (tmp_path / "empty-pack").mkdir()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_dir", tmp_path)
    hub = OceanDataHub()
    workflow = FishingAdvisoryWorkflow(hub=hub)

    response = run(workflow.run(CANONICAL_QUERY))

    assert response.recommended is None, "no zone may be recommended without data"
    assert response.insufficient is not None
    assert response.insufficient.code == "INSUFFICIENT_DATA"
    for zone in response.zones:
        for measurement in zone.measurements:
            assert measurement.value is None
            assert measurement.quality == QualityFlag.MISSING
    assert "Unable" in (response.explanation or "") or "unable" in (response.explanation or "")


# 4 ------------------------------------------------------------ stale flags
def test_stale_data_is_flagged():
    """Demo-pack values are real but cached — they must carry the STALE
    quality flag and a DEMO/CACHED note, never pass as live."""
    settings = get_settings()
    provider = DemoOceanProvider(settings.demo_dir)
    measurement = run(provider.get_sst(9.29, 79.31, datetime.now(timezone.utc)))

    assert measurement.value is not None, "the committed pack holds real SST"
    assert measurement.quality == QualityFlag.STALE
    assert "DEMO" in (measurement.notes or "").upper() or "CACHED" in (measurement.notes or "").upper()
    assert measurement.provenance.mode == "demo"


# 5 ----------------------------------------------------- constraints kept
def test_user_constraints_retained():
    """Distance, place, time window and objectives survive parsing intact."""
    parsed = run(DeterministicQueryParser().parse(CANONICAL_QUERY))

    assert parsed.distance_km == 20.0
    assert parsed.origin is not None
    assert "rameswaram" in parsed.origin.place.lower()
    assert abs(parsed.origin.lat - 9.29) < 0.1 and abs(parsed.origin.lon - 79.31) < 0.1
    assert parsed.time_window is not None
    assert parsed.time_window.start < parsed.time_window.end
    assert "low_risk" in parsed.objectives
    assert "high_productivity" in parsed.objectives


# 6 ------------------------------------------------------ evidence honesty
def test_evidence_maps_to_data(demo):
    """The verifier must find zero integrity problems on the demo response:
    every evidence claim maps to a real measurement with provenance."""
    workflow, response = demo

    problems = workflow._verify(response)
    assert problems == []

    rec = response.recommended
    assert rec is not None
    measured = {m.variable for m in rec.measurements}
    for ev in response.evidence:
        if ev.measurement_variable is not None:
            assert ev.measurement_variable in measured
    # hard-constraint integrity must be clean; a town-centre origin on land is
    # expected under the Natural Earth coastline and is disclosed as a caution
    verification_steps = [s for s in response.trace.steps if s.startswith("verification:")]
    assert verification_steps, "verifier ran"
    assert not any("violates" in s or "problem" in s for s in verification_steps)


# 7 --------------------------------------------------------- demo labeling
def test_demo_mode_is_labeled(demo):
    _, response = demo

    assert response.demo_banner_required is True
    assert any(w.code == "DEMO_MODE" for w in response.warnings)
    assert response.sources, "provenance envelope present"
    for source in response.sources:
        assert source.retrieved_at is not None


# 8 ----------------------------------------------------------- units shown
def test_units_are_explicit(demo):
    _, response = demo

    assert response.recommended is not None
    for measurement in response.recommended.measurements:
        if measurement.value is not None:
            assert measurement.unit, f"{measurement.variable} has a value but no unit"


# 9 ------------------------------------------------- supported-region gate
def test_query_outside_supported_region_is_refused():
    """A departure point outside the validated pilot bbox raises ValueError
    (the API route turns it into HTTP 422) — no confident answers where the
    boundary layers don't exist."""
    workflow = FishingAdvisoryWorkflow()
    parsed = run(DeterministicQueryParser().parse("safest fishing zone 20 km off Mumbai"))

    assert parsed.origin is not None, "Mumbai itself parses fine"
    with pytest.raises(ValueError, match="outside the region"):
        workflow.require_origin_in_supported_region(parsed)
