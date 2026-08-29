"""Boundary layers: authoritative vs reference, loaded from files or PostGIS.

CRITICAL LEGAL DISTINCTION (enforced in the type system and propagated to the
UI): a maritime boundary or protected-area polygon fetched from a GIS
aggregator is a *reference* product. It is NOT a legally definitive boundary.
Only geometry explicitly marked ``authority="authoritative"`` (e.g. coordinates
from a treaty annex) may be displayed as legal. ORCA ships demo layers that are
explicitly labeled; the demo fetch script replaces them with real GIS data
(Marine Regions / WDPA) when available, preserving the authority label.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.config.registry import Authority

logger = logging.getLogger(__name__)


class BoundaryKind(str, Enum):
    IMBL = "imbl"  # india–sri lanka maritime boundary line
    EEZ_LIMIT = "eez_limit"  # 200 nm / 12 nm limit lines
    MPA = "mpa"  # marine protected area
    RESTRICTED = "restricted"  # defence / port / other exclusion zones
    LAND = "land"  # coastline / land polygons (collision avoidance)


@dataclass(frozen=True, slots=True)
class BoundaryLayer:
    id: str
    name: str
    kind: BoundaryKind
    authority: Authority
    source_id: str
    geometry: BaseGeometry
    hard_constraint: bool  # True = never traversable / never inside
    notes: str = ""
    properties: dict[str, object] | None = None


def load_layers_from_dir(directory: Path) -> list[BoundaryLayer]:
    """Load GeoJSON layer files. Each file may contain one Feature or a
    FeatureCollection; per-feature metadata lives in ``properties``."""
    layers: list[BoundaryLayer] = []
    if not directory.exists():
        logger.warning("boundaries dir missing: %s", directory)
        return layers
    for file in sorted(directory.glob("*.geojson")):
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("cannot read boundary layer %s: %s", file, exc)
            continue
        features = raw.get("features", [raw]) if raw.get("type") == "FeatureCollection" else [raw]
        for feature in features:
            props = feature.get("properties", {}) or {}
            try:
                geom = shape(feature["geometry"])
            except (KeyError, ValueError) as exc:
                logger.warning("bad geometry in %s: %s", file, exc)
                continue
            try:
                kind = BoundaryKind(props.get("kind", "restricted"))
                authority = Authority(props.get("authority", "reference"))
            except ValueError as exc:
                logger.warning("bad kind/authority in %s: %s", file, exc)
                continue
            layers.append(
                BoundaryLayer(
                    id=str(props.get("id", file.stem)),
                    name=str(props.get("name", file.stem)),
                    kind=kind,
                    authority=authority,
                    source_id=str(props.get("source_id", "unknown")),
                    geometry=geom,
                    hard_constraint=bool(props.get("hard_constraint", kind in (BoundaryKind.IMBL, BoundaryKind.MPA, BoundaryKind.RESTRICTED, BoundaryKind.LAND))),
                    notes=str(props.get("notes", "")),
                    properties=props,
                )
            )
        logger.info("loaded boundary layer file %s (%d features)", file.name, len(features))
    return layers


def layers_to_geojson(layers: list[BoundaryLayer]) -> dict[str, object]:
    """Serialize layers for map display — includes authority labels so the UI
    can render 'REFERENCE ONLY' badges."""
    features = []
    for layer in layers:
        props = dict(layer.properties or {})
        props.update(
            {
                "id": layer.id,
                "name": layer.name,
                "kind": layer.kind.value,
                "authority": layer.authority.value,
                "source_id": layer.source_id,
                "hard_constraint": layer.hard_constraint,
                "notes": layer.notes,
            }
        )
        features.append(
            {
                "type": "Feature",
                "geometry": layer.geometry.__geo_interface__,
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": features}
