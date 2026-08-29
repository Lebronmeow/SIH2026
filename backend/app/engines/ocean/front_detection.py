"""FrontDetectionEngine — deterministic ocean-front detection.

MVP method (fully reproducible, no ML):

1. *gradient* — centred finite differences (``numpy.gradient``) of the scalar
   field along latitude/longitude, converted to metric units (per km).
2. *magnitude* — Euclidean norm of the two gradient components.
3. *local contrast* — windowed standard deviation (broadens the classic
   Cayula-Cornillon *single-image edge detection* idea of distinguishing
   between-water fronts from noise, without its histogram bimodality test).
4. *threshold* — cells whose magnitude exceeds ``max(fixed_min,
   percentile(field))`` are front candidates.
5. *components* — connected-component labelling (4-neighbour) groups candidate
   cells; each component becomes one detected front with centroid + mean
   strength (``scipy.ndimage.label``).

The ML hook: ``strategy`` parameter — pass any object exposing
``detect(da) -> DataArray`` of front probabilities (e.g. a model ported from
MIT-STARLab's deep-learning ocean front detection) to replace/augment steps
1-4. Nothing else in the codebase changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field
from typing import Protocol

import numpy as np
import xarray as xr
from scipy import ndimage

from app.providers.base import OceanField

# --------------------------------------------------------------------- model


class FrontStrategy(Protocol):
    """Pluggable front-detection strategy (deterministic default, ML later)."""

    def detect(self, da: xr.DataArray) -> xr.DataArray:  # pragma: no cover
        """Return a front-strength array (same shape, same coords)."""


@dataclass(slots=True)
class FrontPoint:
    lat: float
    lon: float
    strength: float  # field units per km (e.g. °C/km)
    bearing: float  # degrees from north — direction of the front (normal to gradient)
    size_cells: int


@dataclass(slots=True)
class FrontResult:
    variable: str
    unit_per_km: str
    threshold: float
    percentile_used: float
    fronts: list[FrontPoint] = dc_field(default_factory=list)
    gradient: xr.DataArray | None = None  # full gradient field (for map heatmap)
    grid_summary: dict[str, float] = dc_field(default_factory=dict)

    @property
    def max_strength(self) -> float:
        return max((f.strength for f in self.fronts), default=0.0)

    def to_geojson(self) -> list[dict[str, object]]:
        return [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(f.lon, 4), round(f.lat, 4)]},
                "properties": {
                    "variable": self.variable,
                    "strength": round(f.strength, 4),
                    "unit": self.unit_per_km,
                    "bearing": round(f.bearing, 1),
                    "size_cells": f.size_cells,
                },
            }
            for f in self.fronts
        ]


@dataclass(slots=True)
class GradientFrontStrategy:
    """The deterministic default: gradient magnitude + local contrast."""

    min_gradient: float = 0.01  # units per km — absolute floor
    percentile: float = 90.0
    contrast_window: int = 5

    def detect(self, da: xr.DataArray) -> xr.DataArray:
        vals = da.values.astype(float)
        lat = da["latitude"].values.astype(float)
        lon = da["longitude"].values.astype(float)

        if vals.shape[0] < 2 or vals.shape[1] < 2:
            return xr.zeros_like(da)

        # metric conversion: deg -> km at field's mean latitude
        mean_lat = float(np.nanmean(lat)) if lat.size else 0.0
        km_per_deg_lat = 111.32
        km_per_deg_lon = max(1e-6, 111.32 * math.cos(math.radians(mean_lat)))
        dlat_km = float(np.mean(np.abs(np.diff(lat)))) * km_per_deg_lat
        dlon_km = float(np.mean(np.abs(np.diff(lon)))) * km_per_deg_lon
        if dlat_km <= 0 or dlon_km <= 0:
            return xr.zeros_like(da)

        gy, gx = np.gradient(np.nan_to_num(vals, nan=0.0))
        gx = gx / dlon_km  # units per km (zonal)
        gy = gy / dlat_km  # units per km (meridional)
        magnitude = np.hypot(gx, gy)

        # local contrast (windowed std) — suppress speckle, keep real fronts
        w = self.contrast_window
        if min(vals.shape) > w:
            local_mean = ndimage.uniform_filter(magnitude, size=w)
            local_sq = ndimage.uniform_filter(magnitude**2, size=w)
            local_std = np.sqrt(np.maximum(local_sq - local_mean**2, 0.0))
            magnitude = magnitude * (1.0 + local_std / (local_mean + 1e-9))

        out = da.copy(data=magnitude)
        out.name = "front_strength"
        return out


# -------------------------------------------------------------------- engine


class FrontDetectionEngine:
    def __init__(self, strategy: FrontStrategy | None = None) -> None:
        self.strategy = strategy or GradientFrontStrategy()

    # -------------------------------------------------------------- internals
    def _field_ok(self, f: OceanField) -> bool:
        return (
            not f.is_empty
            and "latitude" in f.data.dims
            and "longitude" in f.data.dims
            and f.data.sizes.get("latitude", 0) >= 2
            and f.data.sizes.get("longitude", 0) >= 2
        )

    def _strength_field(self, f: OceanField) -> xr.DataArray:
        """Collapse time dim (if any) by taking the latest valid slice."""
        da = f.data
        if "time" in da.dims:
            da = da.isel(time=-1, drop=True)
        return da

    # ---------------------------------------------------------------- public
    def detect_fronts(self, field: OceanField, max_fronts: int = 12) -> FrontResult:
        """Detect fronts in a scalar ocean field (SST or chlorophyll)."""
        result = FrontResult(variable=field.variable, unit_per_km=f"{field.unit}/km", threshold=0.0, percentile_used=0.0)
        if not self._field_ok(field):
            return result

        da = self._strength_field(field)
        strength = self.strategy.detect(da)
        vals = strength.values

        finite = vals[np.isfinite(vals)]
        if finite.size == 0:
            return result

        strat = self.strategy if isinstance(self.strategy, GradientFrontStrategy) else GradientFrontStrategy()
        pct_value = float(np.percentile(finite, strat.percentile))
        threshold = max(strat.min_gradient, pct_value)
        result.threshold = float(threshold)
        result.percentile_used = strat.percentile
        result.gradient = strength

        mask = np.isfinite(vals) & (vals >= threshold)
        if not mask.any():
            return result

        labels, n = ndimage.label(mask)
        lat_vals = strength["latitude"].values.astype(float)
        lon_vals = strength["longitude"].values.astype(float)
        grid = strength.sizes

        fronts: list[FrontPoint] = []
        for label_idx in range(1, n + 1):
            ys, xs = np.nonzero(labels == label_idx)
            comp_strength = vals[ys, xs]
            mean_strength = float(np.mean(comp_strength))
            cy, cx = float(ys.mean()), float(xs.mean())
            # gradient direction -> front bearing is normal to it
            gy, gx = np.gradient(vals)
            g_merid, g_zonal = float(gy[int(round(cy)), int(round(cx))]), float(gx[int(round(cy)), int(round(cx))])
            bearing = (math.degrees(math.atan2(g_zonal, g_merid)) + 180.0) % 360.0
            fronts.append(
                FrontPoint(
                    lat=float(np.interp(cy, np.arange(grid["latitude"]), lat_vals)),
                    lon=float(np.interp(cx, np.arange(grid["longitude"]), lon_vals)),
                    strength=mean_strength,
                    bearing=bearing,
                    size_cells=int(ys.size),
                )
            )
        fronts.sort(key=lambda p: p.strength, reverse=True)
        result.fronts = fronts[:max_fronts]

        finite_vals = vals[np.isfinite(vals)]
        result.grid_summary = {
            "mean": float(finite_vals.mean()),
            "max": float(finite_vals.max()),
            "p90": float(np.percentile(finite_vals, 90)),
            "n_front_components": int(n),
        }
        return result

    def detect_sst_fronts(self, field: OceanField, max_fronts: int = 12) -> FrontResult:
        return self.detect_fronts(field, max_fronts=max_fronts)

    def detect_chlorophyll_fronts(self, field: OceanField, max_fronts: int = 12) -> FrontResult:
        return self.detect_fronts(field, max_fronts=max_fronts)

    def compute_front_strength(self, field: OceanField) -> float | None:
        """Scalar 0-1 normalized front activity for scoring.

        Normalized against a soft cap (e.g. 0.25 °C/km is a strong SST front in
        this region) — a calibration choice, documented as prototype-level.
        """
        result = self.detect_fronts(field, max_fronts=50)
        if result.max_strength <= 0:
            return None
        cap = {"sst": 0.25, "chlorophyll": 0.30}.get(field.variable, 1.0)
        return min(1.0, result.max_strength / cap)

    def generate_productivity_features(
        self, sst_field: OceanField | None, chl_field: OceanField | None
    ) -> dict[str, float | None]:
        """Compact feature dict for the scoring engine (no raw arrays)."""
        return {
            "sst_front_strength": self.compute_front_strength(sst_field) if sst_field and not sst_field.is_empty else None,
            "chlorophyll_front_strength": self.compute_front_strength(chl_field)
            if chl_field and not chl_field.is_empty
            else None,
        }
