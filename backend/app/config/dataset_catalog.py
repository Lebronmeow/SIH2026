"""DatasetCatalog — configurable mapping of *logical variables* to concrete
provider dataset IDs.

Dataset IDs are configuration, never Python literals, so a dataset retirement
or a switch of server never requires a code change. Unknown/missing entries
cause providers to report ``QualityFlag.MISSING`` — they never silently fall
back to a different variable or fabricated numbers.

JSON shape::

    {
      "sst": {
        "provider": "erddap",
        "source_id": "erddap-noaa",
        "dataset_id": "…",          # verified against the server
        "protocol": "griddap",
        "variable": "sst",
        "unit": "degree_C",
        "spatial_resolution": "0.01°"
      },
      ...
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class DatasetEntry(BaseModel):
    key: str  # logical variable, e.g. "sst"
    provider: str  # "erddap" | "open-meteo-marine" | "demo"
    source_id: str
    dataset_id: str | None = None
    protocol: str | None = None  # "griddap" | "tabledap"
    variable: str | None = None  # variable name inside the dataset
    unit: str | None = None
    spatial_resolution: str | None = None
    extras: dict[str, str | int | float] = Field(default_factory=dict)


class DatasetCatalog:
    def __init__(self, entries: dict[str, DatasetEntry]) -> None:
        self._entries = entries

    def get(self, key: str) -> DatasetEntry | None:
        return self._entries.get(key)

    def keys(self) -> list[str]:
        return sorted(self._entries)

    def all(self) -> list[DatasetEntry]:
        return list(self._entries.values())


def load_catalog(path: Path | None = None) -> DatasetCatalog:
    settings = get_settings()
    cfg_path = Path(path or settings.datasets_config)
    if not cfg_path.exists():
        logger.warning("Dataset catalog not found at %s — no datasets configured.", cfg_path)
        return DatasetCatalog({})
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    entries: dict[str, DatasetEntry] = {}
    for key, item in raw.get("datasets", {}).items():
        if not isinstance(item, dict):
            continue
        entries[key] = DatasetEntry(key=key, **item)
    logger.info("Loaded %d dataset mappings from %s", len(entries), cfg_path)
    return DatasetCatalog(entries)
