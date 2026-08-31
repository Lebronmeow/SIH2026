"""Last-good field cache: an outage must serve the last REAL field honestly
labeled — never silence, never a fabricated value, never data past its
representative horizon."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import xarray as xr

from app.config.settings import get_settings
from app.providers.base import OceanField
from app.providers.hub import _LAST_GOOD_TTL_S, OceanDataHub
from app.schemas.common import BoundingBox, Provenance


def _field(age_h: float) -> OceanField:
    prov = Provenance(
        source_id="erddap-noaa-nws",
        source_name="NOAA CoastWatch National ERDDAP",
        dataset="noaacwNPPN20VIIRSDINEOFDaily",
        valid_time=datetime.now(timezone.utc) - timedelta(hours=age_h),
        unit="mg m-3",
        mode=get_settings().data_mode,
    )
    da = xr.DataArray(np.array([[1.0, 2.0], [3.0, np.nan]]), dims=("latitude", "longitude"))
    bbox = BoundingBox(south=8.0, north=10.0, west=77.0, east=79.0)
    return OceanField(variable="chlorophyll", unit="mg m-3", data=da, provenance=prov, bbox=bbox)


def _hub() -> OceanDataHub:
    return OceanDataHub()


def test_recent_cached_field_is_served_with_note() -> None:
    hub = _hub()
    hub._last_good["chlorophyll"] = _field(age_h=5.0)
    out = hub._serve_cached("chlorophyll")
    assert out is not None
    assert "last successful retrieval" in (out.provenance.notes or "")
    # provenance stays truthful: original valid_time and source
    assert out.provenance.source_id == "erddap-noaa-nws"
    assert out.provenance.valid_time is not None and not out.is_empty


def test_cached_field_past_ttl_is_refused() -> None:
    hub = _hub()
    hub._last_good["chlorophyll"] = _field(age_h=(_LAST_GOOD_TTL_S / 3600.0) + 1.0)
    assert hub._serve_cached("chlorophyll") is None


def test_cached_field_without_valid_time_is_refused() -> None:
    hub = _hub()
    f = _field(age_h=1.0)
    f.provenance.valid_time = None
    hub._last_good["chlorophyll"] = f
    assert hub._serve_cached("chlorophyll") is None


def test_no_cache_means_none_not_crash() -> None:
    assert _hub()._serve_cached("chlorophyll") is None


def test_cache_survives_process_restart_via_disk(tmp_path) -> None:
    """A free-tier host restarts between requests; the last good field must
    survive by persisting to the cache directory (this is the exact failure
    that made chlorophyll vanish on Render after every redeploy)."""
    hub1 = _hub()
    hub1._cache_dir = tmp_path
    hub1._remember("chlorophyll", _field(age_h=2.0))

    hub2 = _hub()  # a brand-new instance — empty memory, same disk
    hub2._cache_dir = tmp_path
    assert hub2._last_good == {}
    out = hub2._serve_cached("chlorophyll")
    assert out is not None and not out.is_empty
    assert "last successful retrieval" in (out.provenance.notes or "")
    assert out.provenance.source_id == "erddap-noaa-nws"
    # and it re-populates memory for the next request
    assert "chlorophyll" in hub2._last_good
