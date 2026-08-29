"""Build the Rameswaram demo pack from REAL public data.

This script runs ORCA itself in LIVE mode (the same OceanDataHub the product
uses) and caches the retrieved fields into ``data/demo/rams/``. That is the
point: the demo pack is a replay of a genuine live retrieval, not invented
numbers. Every artifact is recorded in ``manifest.json`` with source, dataset
id, retrieval time and license note; anything that had to be synthesized
(coarse land mask, demo MPA) is marked ``synthetic: true`` — and the UI
labels the whole pack "DEMO / CACHED DATA".

Sources:
- NOAA ERDDAP (SST, chlorophyll, currents, waves, wind) — public domain
- Open-Meteo marine + forecast (weather cache) — CC-BY 4.0, attribution in manifest
- VLIZ Marine Regions WFS (India–Sri Lanka IMBL, line_id 1306 + 1311) —
  CC-BY 4.0, DOI 10.14284/632, attribution written to boundaries/ATTRIBUTION.md

Usage:
    cd backend && .venv/Scripts/python -X utf8 scripts/fetch_demo_data.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config.settings import get_settings  # noqa: E402
from app.providers.hub import OceanDataHub  # noqa: E402
from app.schemas.common import BoundingBox  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fetch-demo")

# Rameswaram advisory box (Palk Strait + Gulf of Mannar approach)
BOX = BoundingBox(south=8.3, north=10.4, west=78.2, east=80.5)
ORIGIN = (9.29, 79.31)  # Rameswaram
RAMESWARAM_LAT, RAMESWARAM_LON = ORIGIN

VARIABLES = [
    "sst",
    "chlorophyll",
    "wave_height",
    "wave_period",
    "wave_direction",
    "current_u",
    "current_v",
    "wind_u",
    "wind_v",
]

IMBL_WFS = (
    "https://geo.vliz.be/geoserver/MarineRegions/ows"
    "?service=WFS&version=1.0.0&request=GetFeature"
    "&typeName=MarineRegions:eez_boundaries&outputFormat=application/json"
    "&CQL_FILTER=line_id={line_id}"
)
IMBL_LINES = {1306: "India–Sri Lanka boundary, 1974 agreement (Palk Strait)",
              1311: "India–Sri Lanka boundary, 1976 agreement (Gulf of Mannar)"}


def main() -> int:
    asyncio.run(_run())
    return 0


async def _run() -> None:
    settings = get_settings()
    pack = settings.demo_dir / "rams"
    (pack / "ocean").mkdir(parents=True, exist_ok=True)
    (pack / "weather").mkdir(parents=True, exist_ok=True)
    (pack / "boundaries").mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    manifest: dict = {
        "pack": "rams",
        "origin": {"place": "Rameswaram", "lat": RAMESWARAM_LAT, "lon": RAMESWARAM_LON},
        "bbox": BOX.model_dump(),
        "retrieved_at": now.isoformat(),
        "data_mode": "DEMO — cached from a live retrieval; NOT live observations",
        "variables": {},
        "weather": {},
        "boundaries": {},
    }

    # ---------------- 1. ocean fields via the live provider stack ------------
    # (same providers the product uses; nothing dataset-specific is scripted)
    import os

    os.environ["ORCA_DATA_MODE"] = "live"
    get_settings.cache_clear()
    hub = OceanDataHub()
    for var in VARIABLES:
        try:
            field = await hub.get_field(var, BOX, now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: live fetch failed (%s) — writing SYNTHETIC fallback", var, exc)
            _write_synthetic(pack, var, now)
            manifest["variables"][var] = {"synthetic": True, "source_name": "synthetic fallback (live fetch failed)", "unit": "unknown"}
            continue
        if field.is_empty:
            logger.warning("%s: provider returned no data — writing SYNTHETIC fallback", var)
            _write_synthetic(pack, var, now)
            manifest["variables"][var] = {"synthetic": True, "source_name": "synthetic fallback (provider empty)", "unit": "unknown"}
            continue
        da = field.data
        da = _ensure_time_dim(da)
        out = pack / "ocean" / f"{var}.nc"
        da.to_netcdf(out)
        prov = field.provenance
        manifest["variables"][var] = {
            "synthetic": False,
            "source_id": prov.source_id,
            "source_name": prov.source_name,
            "dataset_id": prov.dataset,
            "unit": field.unit or prov.unit,
            "spatial_resolution": prov.spatial_resolution,
            "valid_time": str(prov.valid_time),
            "license": "public domain (NOAA)" if "noaa" in prov.source_id else prov.source_name,
        }
        logger.info("%s: cached %s (%s, %d cells)", var, out.name, field.unit, int(np.isfinite(da.values).sum()))

    # ---------------- 2. weather caches (Open-Meteo) --------------------------
    await _write_weather_cache(pack, manifest, now)

    # ---------------- 3. boundaries ------------------------------------------
    _write_imbl(pack, manifest)
    _write_demo_mpa(pack, manifest)
    _write_demo_land_mask(pack, manifest)

    # ---------------- 4. manifest --------------------------------------------
    (pack / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("manifest written: %s", pack / "manifest.json")
    synthetic = [k for k, v in manifest["variables"].items() if v.get("synthetic")]
    if synthetic:
        logger.warning("SYNTHETIC fallback fields (fetch failed for): %s — the pack is NOT fully live-derived", synthetic)


# ------------------------------------------------------------------ helpers
def _ensure_time_dim(da: xr.DataArray) -> xr.DataArray:
    if "time" not in da.dims:
        da = da.expand_dims(time=[np.datetime64(datetime.now(timezone.utc).replace(tzinfo=None))])
    return da.sortby("time")


def _write_synthetic(pack: Path, var: str, now: datetime) -> None:
    """Clearly-labeled synthetic field so the demo never breaks offline."""
    lats = np.linspace(BOX.south, BOX.north, 40)
    lons = np.linspace(BOX.west, BOX.east, 40)
    LON, LAT = np.meshgrid(lons, lats)
    base = {
        "sst": 28.6 + 0.9 * np.sin((LON - 79.3) / 0.8) + 0.3 * np.cos((LAT - 9.3) / 0.6),
        "chlorophyll": 0.35 + 1.1 / (1.0 + np.exp(-(LON - 79.9) / 0.25)),
        "wave_height": 1.0 + 0.5 * np.sin((LAT - 9.0) / 0.7),
        "wave_period": 7.0 + 1.5 * np.cos((LAT - 9.0) / 0.7),
        "wave_direction": 250.0 + 20.0 * np.sin((LON - 79.0) / 0.9),
        "current_u": 0.25 * np.sin((LAT - 9.2) / 0.5),
        "current_v": 0.2 * np.cos((LON - 79.4) / 0.6),
        "wind_u": -3.0 + 1.0 * np.sin((LON - 79.0) / 1.0),
        "wind_v": 5.0 + 1.0 * np.cos((LAT - 9.0) / 1.0),
    }[var]
    da = xr.DataArray(
        base[np.newaxis, :, :],
        coords={
            "time": [np.datetime64(now.replace(tzinfo=None))],
            "latitude": lats,
            "longitude": lons,
        },
        dims=("time", "latitude", "longitude"),
    )
    da.to_netcdf(pack / "ocean" / f"{var}.nc")


async def _write_weather_cache(pack: Path, manifest: dict, now: datetime) -> None:
    import httpx

    lat, lon = ORIGIN
    jobs = {
        "wind": (
            "https://api.open-meteo.com/v1/forecast",
            {"latitude": lat, "longitude": lon, "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
             "forecast_days": 3, "timezone": "UTC"},
        ),
        "waves": (
            "https://marine-api.open-meteo.com/v1/marine",
            {"latitude": lat, "longitude": lon, "hourly": "wave_height,wave_period,wave_direction",
             "forecast_days": 3, "timezone": "UTC"},
        ),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        for kind, (url, params) in jobs.items():
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
            except Exception as exc:  # noqa: BLE001
                logger.warning("open-meteo %s cache failed: %s", kind, exc)
                continue
            payload = {
                "retrieved_at": now.isoformat(),
                "location": {"lat": lat, "lon": lon},
                "source": "Open-Meteo (CC-BY 4.0 attribution required)",
                "hourly": data.get("hourly", {}),
            }
            (pack / "weather" / f"{kind}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
            manifest["weather"][kind] = {"source_id": "open-meteo", "source_name": "Open-Meteo", "license": "CC-BY 4.0", "synthetic": False}
            logger.info("weather/%s.json cached", kind)


def _write_imbl(pack: Path, manifest: dict) -> None:
    import httpx

    features = []
    for line_id, description in IMBL_LINES.items():
        try:
            import httpx as _hx

            r = _hx.get(IMBL_WFS.format(line_id=line_id), timeout=60)
            r.raise_for_status()
            fc = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("VLIZ IMBL line %d fetch failed: %s", line_id, exc)
            continue
        for feat in fc.get("features", []):
            props = dict(feat.get("properties", {}))
            props.update(
                {
                    "kind": "imbl",
                    # VLIZ geometry is a REFERENCE digitization of the treaty
                    # lines — official survey coordinates would be required to
                    # label it authoritative. Still a HARD routing constraint.
                    "authority": "reference",
                    "hard_constraint": True,
                    "source_id": "marine-regions",
                    "name": description,
                    "notes": (
                        f"Treaty-based maritime boundary line (line_id={line_id}); geometry digitized by "
                        "VLIZ Marine Regions, CC-BY 4.0, DOI 10.14284/632. REFERENCE product — replace "
                        "with official survey coordinates for legal use; ORCA still treats it as a hard constraint."
                    ),
                }
            )
            features.append({"type": "Feature", "geometry": feat["geometry"], "properties": props})
    if features:
        out = pack / "boundaries" / "imbl_india_sri_lanka.geojson"
        out.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")
        manifest["boundaries"]["imbl"] = {
            "source_id": "marine-regions",
            "source_name": "Flanders Marine Institute (VLIZ), Marine Regions",
            "license": "CC-BY 4.0",
            "doi": "10.14284/632",
            "url": "https://www.marineregions.org/",
            "line_ids": list(IMBL_LINES),
            "synthetic": False,
        }
        attribution = (
            "# Attribution\n\n"
            "India–Sri Lanka maritime boundary lines (WFS line_id 1306 and 1311) from:\n\n"
            "Flanders Marine Institute (VLIZ) — Marine Regions, Maritime Boundaries Geodatabase.\n"
            "https://www.marineregions.org/ · DOI 10.14284/632 · Licensed CC-BY 4.0.\n\n"
            f"Retrieved {manifest['retrieved_at']} by scripts/fetch_demo_data.py.\n"
        )
        (pack / "boundaries" / "ATTRIBUTION.md").write_text(attribution, encoding="utf-8")
        logger.info("IMBL geometry cached (%d features)", len(features))
    else:
        logger.warning("NO IMBL geometry available — boundary checks will be REFERENCE-only")


def _write_demo_mpa(pack: Path, manifest: dict) -> None:
    """SYNTHETIC demo MPA (Gulf of Mannar approx). Real MPAs come from the
    WDPA runtime provider with the operator's own key — never redistributed."""
    ring = [(-0.35, -0.15), (-0.1, 0.3), (0.25, 0.35), (0.45, 0.05), (0.3, -0.3), (-0.05, -0.35)]
    coords = [[79.55 + dx, 9.05 + dy] for dx, dy in ring] + [[79.55 - 0.35, 9.05 - 0.15]]
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {
                    "kind": "mpa",
                    "authority": "reference",
                    "hard_constraint": True,
                    "source_id": "orca-demo",
                    "name": "Gulf of Mannar Marine National Park (SYNTHETIC demo polygon)",
                    "notes": "SYNTHETIC approximation for demo mode only — NOT the official WDPA boundary. Replace via ProtectedAreaProvider (WDPA) at runtime.",
                },
            }
        ],
    }
    (pack / "boundaries" / "demo_mpa_gulf_of_mannar.geojson").write_text(json.dumps(fc, indent=1), encoding="utf-8")
    manifest["boundaries"]["demo_mpa"] = {"source_id": "orca-demo", "synthetic": True}


def _write_demo_land_mask(pack: Path, manifest: dict) -> None:
    """Coarse land polygons around the demo box so routing avoids obvious land.
    Labeled synthetic/coarse; a real coastline layer replaces this in ops mode."""
    india = [
        [78.6, 10.4], [78.9, 10.4], [79.05, 9.95], [79.1, 9.6], [79.25, 9.45],
        [79.45, 9.35], [79.5, 9.15], [79.6, 9.05], [79.75, 9.1], [79.85, 9.3],
        [80.3, 9.6], [80.5, 10.0], [80.5, 10.4], [78.6, 10.4],
    ]
    srilanka = [
        [79.6, 9.05], [80.0, 9.05], [80.3, 9.2], [80.5, 9.5], [80.5, 8.3],
        [79.9, 8.3], [79.75, 8.6], [79.6, 8.8], [79.6, 9.05],
    ]
    features = []
    for name, poly in (("India (coarse demo mask)", india), ("Sri Lanka (coarse demo mask)", srilanka)):
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [poly]},
                "properties": {
                    "kind": "land",
                    "authority": "reference",
                    "hard_constraint": True,
                    "source_id": "orca-demo",
                    "name": name,
                    "notes": "SYNTHETIC coarse coastline for demo routing — NOT survey-grade. Replace with Natural Earth/OSM land layer in ops mode.",
                },
            }
        )
    fc = {"type": "FeatureCollection", "features": features}
    (pack / "boundaries" / "demo_land_mask.geojson").write_text(json.dumps(fc, indent=1), encoding="utf-8")
    manifest["boundaries"]["demo_land_mask"] = {"source_id": "orca-demo", "synthetic": True}


if __name__ == "__main__":
    raise SystemExit(main())
