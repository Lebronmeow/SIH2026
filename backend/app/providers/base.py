"""Provider abstractions for ocean data.

Providers are the ONLY components allowed to touch remote or cached scientific
data. They return :class:`Measurement` / :class:`OceanField` objects with full
provenance. A provider that cannot obtain data returns a *missing* measurement
— it never guesses.

Keep scientific computation OUT of providers: providers fetch/subset/sample;
engines (front detection, scoring, routing) compute.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import xarray as xr

from app.schemas.common import BoundingBox, Measurement, Provenance


class ProviderError(RuntimeError):
    """Raised for transport/protocol failures. Providers translate this into
    missing measurements at the hub level; engines treat it as no-data."""


@dataclass(slots=True)
class OceanField:
    """A spatially-resolved variable window (gridded) with provenance.

    Wraps an ``xarray.DataArray`` with canonical coordinate names
    (``time``, ``latitude``, ``longitude``) so downstream engines can be
    provider-agnostic.
    """

    variable: str
    unit: str
    data: xr.DataArray
    provenance: Provenance
    bbox: BoundingBox

    @property
    def is_empty(self) -> bool:
        return self.data is None or self.data.size == 0

    @classmethod
    def empty(cls, variable: str, unit: str, provenance: Provenance, bbox: BoundingBox) -> "OceanField":
        """A truthful EMPTY field (xr.DataArray() alone is a 0-d NaN, size 1)."""
        return cls(variable, unit, xr.DataArray(np.empty(0)), provenance, bbox)

    def summary(self) -> dict[str, object]:
        """Compact JSON-safe summary (never ship the raw array to the LLM)."""
        if self.is_empty:
            return {"variable": self.variable, "n_cells": 0}
        finite = np.asarray(self.data.values, dtype=float)
        finite = finite[np.isfinite(finite)]
        stats = (
            {
                "min": float(finite.min()),
                "max": float(finite.max()),
                "mean": float(finite.mean()),
                "n_cells": int(finite.size),
            }
            if finite.size
            else {"n_cells": 0}
        )
        return {"variable": self.variable, "unit": self.unit, **stats}


class OceanDataProvider(ABC):
    """Interface every ocean-data provider implements.

    Contract:
    * Point getters return :class:`Measurement` (``value=None`` ⇒ no data).
    * ``get_field`` returns a gridded window for engines (fronts, routing).
    * All timestamps are UTC.
    """

    source_id: str

    @abstractmethod
    async def get_available_datasets(self) -> list[dict[str, object]]:
        """Datasets this provider can currently serve."""

    @abstractmethod
    async def get_dataset_metadata(self, dataset_id: str) -> dict[str, object]:
        """Metadata (variables, units, coverage, resolution) for a dataset."""

    @abstractmethod
    async def get_sst(self, lat: float, lon: float, valid_time: datetime) -> Measurement: ...

    @abstractmethod
    async def get_chlorophyll(self, lat: float, lon: float, valid_time: datetime) -> Measurement: ...

    @abstractmethod
    async def get_currents(
        self, lat: float, lon: float, valid_time: datetime
    ) -> list[Measurement]:
        """u/v (and optionally speed) current components."""

    @abstractmethod
    async def get_wave_data(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        """Wave height (and optionally period/direction)."""

    @abstractmethod
    async def get_ocean_forecast(
        self, lat: float, lon: float, start: datetime, end: datetime
    ) -> list[Measurement]:
        """Forecast-window series at a point (variables per provider support)."""

    @abstractmethod
    async def get_field(
        self, variable: str, bbox: BoundingBox, valid_time: datetime
    ) -> OceanField:
        """Gridded window of a logical variable (from the dataset catalog)."""

    async def get_wind(self, lat: float, lon: float, valid_time: datetime) -> list[Measurement]:
        """Wind components/observations. Optional capability — default is a
        single ``missing`` measurement so engines can rely on the shape."""
        return [
            Measurement(
                variable="wind_speed",
                value=None,
                unit="km/h",
                provenance=Provenance(source_id=self.source_id, source_name=self.source_id),
                quality=QualityFlag.MISSING,
                notes="wind not provided by this provider",
            )
        ]
