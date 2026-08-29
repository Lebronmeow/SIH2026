"""FastAPI surface tests (in-process TestClient, demo mode, no network
beyond the disabled-service paths)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

CANONICAL_QUERY = (
    "Where is the safest and most productive fishing zone 20 km off Rameswaram tomorrow morning?"
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_query_endpoint_full_response(client):
    r = client.post("/api/query", json={"query": CANONICAL_QUERY, "language": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["recommended"] is not None
    assert body["recommended"]["candidate"]["id"]
    assert body["explanation"]
    assert body["valid_time"]
    assert body["demo_banner_required"] is True
    # every provenance-carrying piece the UI promises is present
    assert body["warnings"] and any(w["code"] == "DEMO_MODE" for w in body["warnings"])
    assert body["evidence"]
    assert body["sources"]
    assert body["trace"]["steps"]


def test_query_endpoint_rejects_unparseable(client):
    """A query with no resolvable place must 422 with an honest message."""
    r = client.post("/api/query", json={"query": "zone 20 km off Middle Of Nowhere"})
    assert r.status_code == 422
    assert "departure place" in r.json()["detail"].lower()


def test_recommendation_roundtrip_and_404(client):
    created = client.post("/api/query", json={"query": CANONICAL_QUERY}).json()
    request_id = created["request_id"]
    fetched = client.get(f"/api/recommendations/{request_id}")
    assert fetched.status_code == 200
    assert fetched.json()["request_id"] == request_id

    missing = client.get("/api/recommendations/does-not-exist")
    assert missing.status_code == 404


def test_safety_check_sea_point_is_ok(client):
    r = client.post("/api/safety/check", json={"lat": 9.24, "lon": 79.14})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["on_land"] is False
    assert body["inside_mpa"] is False
    assert body["imbl_violation"] is False


def test_safety_layers_endpoint(client):
    r = client.get("/api/safety/layers")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    kinds = {f["properties"]["kind"] for f in body["features"]}
    assert "imbl" in kinds
    for feature in body["features"]:
        props = feature["properties"]
        assert props["authority"] in ("reference", "authoritative")
        assert "hard_constraint" in props


def test_voice_status_reports_capabilities(client):
    r = client.get("/api/voice/status")
    assert r.status_code == 200
    body = r.json()
    for key in ("configured", "transcribe", "translate", "speak", "english_only_fallback", "message"):
        assert key in body


def test_voice_endpoints_honest_503_when_disabled(client):
    """Without ORCA_BHASHINI_* the endpoints fail with a structured 503 body —
    never with a fake translation or silent success."""
    r = client.post("/api/translate", json={"text": "vanakkam", "source": "ta", "target": "en"})
    assert r.status_code in (502, 503)  # 503 disabled / 502 only if misconfigured
    detail = r.json()["detail"]
    assert detail["code"] in ("SERVICE_DISABLED", "SERVICE_ERROR")
    assert detail["message"]


def test_system_status_discloses_mode(client):
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "demo"
    assert body["demo_banner_required"] is True
    assert "DEMO" in body["banner_text"].upper()
