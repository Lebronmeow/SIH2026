"""GeospatialSafetyEngine — deterministic geometry answers to safety questions.

The LLM must NEVER decide whether a point is inside a restricted area or how
far it is from the IMBL. It calls this engine; this engine answers with
numbers, hit records and warnings.

Metric accuracy: distances are computed in a local UTM projection (zone chosen
from the point's longitude), keeping error well under 0.1% within the zone —
more than sufficient for km-scale proximity rules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field

from pyproj import Geod, Transformer
from shapely.geometry import LineString, Point
from shapely.ops import transform as shp_transform
from shapely.prepared import prep

from app.config.registry import Authority
from app.engines.geospatial.layers import BoundaryKind, BoundaryLayer
from app.schemas.common import LatLon, Warning as OrcaWarning

_GEOD = Geod(ellps="WGS84")

# IMBL proximity thresholds (m) — operational caution bands used for warnings.
IMBL_CAUTION_M = 10_000.0  # 10 km: caution band
IMBL_CRITICAL_M = 5_000.0  # 5 km: do-not-approach band


def utm_crs_for(lon: float, lat: float) -> str:
    """EPSG string for the local UTM zone covering (lon, lat)."""
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    zone = min(max(zone, 1), 60)
    return f"EPSG:{32600 + zone}" if lat >= 0 else f"EPSG:{32700 + zone}"


@dataclass(frozen=True, slots=True)
class BoundaryHit:
    layer_id: str
    layer_name: str
    kind: BoundaryKind
    authority: Authority
    source_id: str
    inside: bool
    distance_m: float
    hard_constraint: bool
    notes: str = ""


@dataclass(frozen=True, slots=True)
class GeofenceResult:
    point: LatLon
    hits: list[BoundaryHit] = dc_field(default_factory=list)
    inside_mpa: bool = False
    inside_restricted: bool = False
    inside_imbl_violation: bool = False  # on the wrong side / inside critical band
    distance_to_imbl_m: float | None = None
    on_land: bool = False
    warnings: list[OrcaWarning] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no hard constraint is violated at this point."""
        return not (self.inside_mpa or self.inside_restricted or self.inside_imbl_violation or self.on_land)


@dataclass(slots=True)
class RouteSafetyResult:
    route_id: str | None
    crosses_restricted: bool = False
    crosses_imbl: bool = False
    crosses_land: bool = False
    hits: list[BoundaryHit] = dc_field(default_factory=list)
    min_imbl_distance_m: float | None = None
    warnings: list[OrcaWarning] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.crosses_restricted or self.crosses_imbl or self.crosses_land)


class GeospatialSafetyEngine:
    """Boundary checks against loaded layers (file-based demo or PostGIS-backed)."""

    def __init__(self, layers: list[BoundaryLayer]) -> None:
        self._layers = layers
        # prepared geometries speed up repeated point-in-polygon tests
        self._prepared: list[tuple[BoundaryLayer, object]] = [
            (layer, prep(layer.geometry)) for layer in layers
        ]
        # caches: projecting layer geometry + building transformers are the
        # hot path for distance checks — do each at most once per UTM zone
        self._transformer_cache: dict[str, Transformer] = {}
        self._projected_cache: dict[tuple[str, str], object] = {}

    @classmethod
    def from_directory(cls, directory) -> "GeospatialSafetyEngine":
        """Build the engine from GeoJSON layers in a directory (demo/ops mode)."""
        return cls.from_directories([directory])

    @classmethod
    def from_directories(cls, directories) -> "GeospatialSafetyEngine":
        """Build the engine from every GeoJSON layer found in the given dirs.

        Demo packs carry their own ``boundaries/`` (self-contained pack), so
        callers pass settings.boundaries_dir *plus* each pack's boundaries dir;
        layer ids are de-duplicated (first wins) in case of overlap.
        """
        from pathlib import Path as _Path

        from app.engines.geospatial.layers import load_layers_from_dir

        layers: list[BoundaryLayer] = []
        seen: set[str] = set()
        for d in directories:
            d = _Path(d)
            if not d.exists():
                continue
            for layer in load_layers_from_dir(d):
                if layer.id in seen:
                    continue
                seen.add(layer.id)
                layers.append(layer)
        return cls(layers)

    @classmethod
    def from_settings(cls) -> "GeospatialSafetyEngine":
        """Engine over settings.boundaries_dir + every demo pack's boundaries."""
        from app.config.settings import get_settings

        settings = get_settings()
        dirs = [settings.boundaries_dir]
        # Reference boundary layers (IMBL treaty lines, protected areas, land
        # masks) ship inside the demo packs but apply in EVERY mode — a live
        # advisory needs the same hard geofence protection as a demo one.
        if settings.demo_dir.exists():
            dirs.extend(p / "boundaries" for p in settings.demo_dir.iterdir() if p.is_dir())
        return cls.from_directories(dirs)

    def _projector(self, lon: float, lat: float) -> Transformer:
        crs = utm_crs_for(lon, lat)
        if crs not in self._transformer_cache:
            self._transformer_cache[crs] = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        return self._transformer_cache[crs]

    def _projected_geometry(self, layer: BoundaryLayer, crs: str):
        key = (layer.id, crs)
        if key not in self._projected_cache:
            fwd = self._transformer_cache[crs]
            self._projected_cache[key] = shp_transform(fwd.transform, layer.geometry)
        return self._projected_cache[key]

    # ----------------------------------------------------------------- query
    def layers(self, kind: BoundaryKind | None = None) -> list[BoundaryLayer]:
        return [l for l in self._layers if kind is None or l.kind == kind]

    def _hit(self, layer: BoundaryLayer, point: Point, lon: float, lat: float) -> BoundaryHit:
        prepared = prep(layer.geometry)
        inside = prepared.contains(point) or prepared.intersects(point)
        if inside:
            distance_m = 0.0
        else:
            fwd = self._projector(lon, lat)
            projected = self._projected_geometry(layer, utm_crs_for(lon, lat))
            projected_point = fwd.transform(lon, lat)
            distance_m = float(projected.distance(Point(projected_point)))
        return BoundaryHit(
            layer_id=layer.id,
            layer_name=layer.name,
            kind=layer.kind,
            authority=layer.authority,
            source_id=layer.source_id,
            inside=inside,
            distance_m=round(distance_m, 1),
            hard_constraint=layer.hard_constraint,
            notes=layer.notes,
        )

    # ---------------------------------------------------------------- public
    def is_inside_restricted_area(self, point: LatLon) -> BoundaryHit | None:
        return next(
            (
                h
                for h in self._hits_at_point(point)
                if h.kind in (BoundaryKind.RESTRICTED, BoundaryKind.MPA) and h.inside
            ),
            None,
        )

    def is_inside_mpa(self, point: LatLon) -> BoundaryHit | None:
        return next(
            (h for h in self._hits_at_point(point) if h.kind == BoundaryKind.MPA and h.inside),
            None,
        )

    def distance_to_imbl(self, point: LatLon) -> float | None:
        hits = [h for h in self._hits_at_point(point) if h.kind == BoundaryKind.IMBL]
        return min((h.distance_m for h in hits), default=None)

    def distance_to_land(self, point: LatLon) -> float | None:
        """Metres to the nearest land polygon (0 when the point is on land)."""
        hits = [h for h in self._hits_at_point(point) if h.kind == BoundaryKind.LAND]
        return min((h.distance_m for h in hits), default=None)

    distance_to_boundary = distance_to_imbl  # alias per spec naming

    def check_geofence(self, point: LatLon) -> GeofenceResult:
        hits = self._hits_at_point(point)
        inside_mpa = any(h.inside and h.kind == BoundaryKind.MPA for h in hits)
        inside_restricted = any(h.inside and h.kind == BoundaryKind.RESTRICTED for h in hits)
        on_land = any(h.inside and h.kind == BoundaryKind.LAND for h in hits)
        imbl_hits = [h for h in hits if h.kind == BoundaryKind.IMBL]
        distance_to_imbl = min((h.distance_m for h in imbl_hits), default=None)
        inside_imbl_violation = any(h.inside and h.kind == BoundaryKind.IMBL for h in hits) or (
            distance_to_imbl is not None and distance_to_imbl <= IMBL_CRITICAL_M
        )

        warnings: list[OrcaWarning] = []
        if inside_imbl_violation:
            warnings.append(
                OrcaWarning(
                    severity="critical",
                    code="IMBL_VIOLATION",
                    message=(
                        f"Point is at/inside the maritime boundary critical band "
                        f"({(distance_to_imbl or 0)/1000:.1f} km). Cross-boundary fishing is prohibited."
                    ),
                    source="geospatial-engine",
                )
            )
        elif distance_to_imbl is not None and distance_to_imbl <= IMBL_CAUTION_M:
            warnings.append(
                OrcaWarning(
                    severity="warning",
                    code="IMBL_CAUTION",
                    message=f"Point is within {distance_to_imbl/1000:.1f} km of the maritime boundary — maintain clear distance.",
                    source="geospatial-engine",
                )
            )
        if inside_mpa:
            warnings.append(
                OrcaWarning(
                    severity="critical",
                    code="MPA_INSIDE",
                    message="Point lies inside a protected/marine area — fishing is restricted.",
                    source="geospatial-engine",
                )
            )
        if on_land:
            warnings.append(
                OrcaWarning(severity="critical", code="LAND", message="Point is on land.", source="geospatial-engine")
            )
        # reference-layer disclosure warning
        if any(h.kind == BoundaryKind.IMBL and h.authority != Authority.AUTHORITATIVE for h in imbl_hits):
            warnings.append(
                OrcaWarning(
                    severity="info",
                    code="REFERENCE_BOUNDARY",
                    message="Boundary geometry is a REFERENCE GIS product — not a legally definitive border.",
                    source="geospatial-engine",
                )
            )

        return GeofenceResult(
            point=point,
            hits=hits,
            inside_mpa=inside_mpa,
            inside_restricted=inside_restricted,
            inside_imbl_violation=inside_imbl_violation,
            distance_to_imbl_m=distance_to_imbl,
            on_land=on_land,
            warnings=warnings,
        )

    # ----------------------------------------------------------------- route
    def edge_blocked(self, lon1: float, lat1: float, lon2: float, lat2: float) -> bool:
        """True when the straight segment crosses any hard-constraint geometry.

        Used by the routing engine so a single long edge can never *jump over*
        a blocked cell (land polygon, restricted/MPA polygon, or the IMBL line
        itself). This is the load-bearing hard-constraint guarantee.
        """
        seg = LineString([(lon1, lat1), (lon2, lat2)])
        for layer, prepared in self._prepared:
            if not layer.hard_constraint:
                continue
            if prepared.intersects(seg):
                return True
        return False

    def check_route_safety(self, route_coords: list[tuple[float, float]], route_id: str | None = None) -> RouteSafetyResult:
        """route_coords: [(lon, lat), ...] — the raw geometry (deterministic engines use lon/lat order)."""
        result = RouteSafetyResult(route_id=route_id)
        if len(route_coords) < 2:
            return result
        line = LineString(route_coords)
        sample_points = [Point(c) for c in route_coords]
        # densify sample points along the line for polygon-crossing checks
        n_samples = max(len(route_coords), 64)
        sample_points += [Point(line.interpolate(i / (n_samples - 1), normalized=True)) for i in range(n_samples)]

        for layer, prepared in self._prepared:
            if layer.kind == BoundaryKind.LAND:
                if any(prepared.intersects(p) for p in sample_points):
                    result.crosses_land = True
                    result.hits.append(self._hit(layer, sample_points[0], *route_coords[0]))
                continue
            if layer.kind == BoundaryKind.IMBL:
                intersects = prepared.intersects(line)
                if intersects:
                    result.crosses_imbl = True
                distances = [self._imbl_distance_m(p) for p in sample_points]
                distances = [d for d in distances if d is not None]
                result.min_imbl_distance_m = min(distances) if distances else None
                continue
            if layer.kind in (BoundaryKind.RESTRICTED, BoundaryKind.MPA) and prepared.intersects(line):
                if layer.kind == BoundaryKind.RESTRICTED:
                    result.crosses_restricted = True
                result.hits.append(self._hit(layer, sample_points[0], *route_coords[0]))

        if result.crosses_imbl:
            result.warnings.append(
                OrcaWarning(
                    severity="critical",
                    code="ROUTE_IMBL",
                    message="Route crosses the maritime boundary — rejected by hard constraint.",
                    source="geospatial-engine",
                )
            )
        if result.crosses_restricted:
            result.warnings.append(
                OrcaWarning(
                    severity="critical",
                    code="ROUTE_RESTRICTED",
                    message="Route crosses a restricted/protected area — rejected by hard constraint.",
                    source="geospatial-engine",
                )
            )
        if result.crosses_land:
            result.warnings.append(
                OrcaWarning(
                    severity="critical",
                    code="ROUTE_LAND",
                    message="Route crosses land — rejected by hard constraint.",
                    source="geospatial-engine",
                )
            )
        return result

    # -------------------------------------------------------------- internals
    def _hits_at_point(self, point: LatLon) -> list[BoundaryHit]:
        shp_point = Point(point.lon, point.lat)
        return [self._hit(layer, shp_point, point.lon, point.lat) for layer, _ in self._prepared]

    def _imbl_distance_m(self, point: Point) -> float | None:
        imbl_layers = self.layers(BoundaryKind.IMBL)
        if not imbl_layers:
            return None
        crs = utm_crs_for(point.x, point.y)
        fwd = self._projector(point.x, point.y)
        projected_point = fwd.transform(point.x, point.y)
        return min(float(self._projected_geometry(l, crs).distance(Point(projected_point))) for l in imbl_layers)
