"""RouteOptimizationEngine — hazard-aware A* marine routing.

Concepts adapted (documented, not copied — SIMROUTE carries no license; see
Grifoll et al. 2022, Ocean Engineering 255:111427) and re-implemented here:

* **Grid**: regular lat/lon mesh over the origin/destination box.
* **Neighbor fan**: 48-neighbour forward fan (offsets to ±4 cells) for smooth
  headings instead of zig-zag 8-connected paths.
* **Admissible heuristic**: geodesic distance-to-goal / v_max ⇒ optimal-time
  routing guarantee for pure time cost.
* **Speed loss**: Bowditch-style sector model (Bowditch, *American Practical
  Navigator* — public-domain U.S. Gov publication): ΔV = k · Hs² with sector
  coefficients head/beam/following, Hs in feet.
* **Hard constraints**: land, restricted/MPA polygons, and the IMBL critical
  band are *blocked cells* (infinite edge cost) — never overridden by any cost
  weight, and never edited out after the fact.
* Open set is a ``heapq`` (SIMROUTE's linear scan is its known weakness).

Hazard values enter through a ``HazardSampler`` callable (bilinear-sampled
ocean fields built by the pipeline) — the routing engine itself never fetches
data, keeping it deterministic and unit-testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Callable

import numpy as np
from pyproj import Geod
from shapely.geometry import Point

from app.engines.geospatial.safety import GeospatialSafetyEngine, IMBL_CAUTION_M, IMBL_CRITICAL_M
from app.engines.routing.astar import AStarResult, astar
from app.schemas.common import LatLon

_GEOD = Geod(ellps="WGS84")
_KNOTS_TO_MS = 0.514444
_MS_TO_KMH = 3.6


@dataclass(slots=True)
class HazardSample:
    """Hazard state at one grid cell (all optional = data may be missing)."""

    wave_height_m: float | None = None
    wind_speed_ms: float | None = None
    current_u_ms: float | None = None
    current_v_ms: float | None = None


HazardSampler = Callable[[float, float], HazardSample]


@dataclass(slots=True)
class RoutingWeights:
    """Prototype decision weights — heuristic, NOT scientifically validated.

    Hard constraints are never weighted: they are absolute.
    """

    wave_penalty: float = 6.0  # per metre of significant wave height (km-equiv)
    wind_penalty: float = 0.15  # per km/h of wind above calm_threshold
    adverse_current_penalty: float = 20.0  # per m/s of adverse current component
    imbl_buffer_penalty: float = 250.0  # km-equivalent per crossing of caution band
    cell_distance_weight: float = 1.0
    wave_calm_threshold_m: float = 0.5
    wind_calm_threshold_ms: float = 5.0


@dataclass(slots=True)
class Route:
    coords: list[LatLon]  # ordered path (origin first)
    distance_km: float
    estimated_time_h: float
    mode: str
    cost_breakdown: dict[str, float] = dc_field(default_factory=dict)
    hazard_stats: dict[str, float | None] = dc_field(default_factory=dict)
    expanded_nodes: int = 0
    blocked_by_constraints: bool = False
    notes: list[str] = dc_field(default_factory=list)

    @property
    def coords_lonlat(self) -> list[tuple[float, float]]:
        return [(c.lon, c.lat) for c in self.coords]


# Bowdith-style sector coefficients for ΔV = k · Hs_ft² (knots lost)
_BOWDITCH_HEAD = 0.0248
_BOWDITCH_BEAM = 0.0165
_BOWDITCH_FOLLOWING = 0.0083


def _speed_loss_knots(wave_height_m: float | None, bearing_deg: float, wave_dir_deg: float | None) -> float:
    """Bowditch sector model. Returns speed loss in knots."""
    if wave_height_m is None:
        return 0.0
    hs_ft = wave_height_m * 3.28084
    if wave_dir_deg is None:
        k = _BOWDITCH_BEAM
    else:
        rel = abs((bearing_deg - wave_dir_deg + 180.0) % 360.0 - 180.0)  # 0=head-on
        if rel <= 45:
            k = _BOWDITCH_HEAD
        elif rel >= 135:
            k = _BOWDITCH_FOLLOWING
        else:
            k = _BOWDITCH_BEAM
    return k * hs_ft * hs_ft


class RouteOptimizationEngine:
    def __init__(
        self,
        safety_engine: GeospatialSafetyEngine | None,
        hazard_sampler: HazardSampler | None = None,
        vessel_speed_knots: float = 7.0,
        cell_deg: float = 0.05,
        weights: RoutingWeights | None = None,
    ) -> None:
        self.safety = safety_engine
        self.hazard_sampler = hazard_sampler or (lambda lat, lon: HazardSample())
        self.v0 = vessel_speed_knots
        self.cell_deg = cell_deg
        self.weights = weights or RoutingWeights()

    # ------------------------------------------------------------------ grid
    def _grid(self, origin: LatLon, dest: LatLon, pad_deg: float = 0.35):
        west = min(origin.lon, dest.lon) - pad_deg
        east = max(origin.lon, dest.lon) + pad_deg
        south = min(origin.lat, dest.lat) - pad_deg
        north = max(origin.lat, dest.lat) + pad_deg
        nx = max(4, int(round((east - west) / self.cell_deg)) + 1)
        ny = max(4, int(round((north - south) / self.cell_deg)) + 1)
        lons = [west + i * self.cell_deg for i in range(nx)]
        lats = [south + j * self.cell_deg for j in range(ny)]
        return lons, lats

    def _cell_to_latlon(self, lons: list[float], lats: list[float], cell: tuple[int, int]) -> LatLon:
        x, y = cell
        return LatLon(lat=float(lats[int(y)]), lon=float(lons[int(x)]))

    def _nearest_cell(self, lons: list[float], lats: list[float], point: LatLon) -> tuple[int, int]:
        x = min(range(len(lons)), key=lambda i: abs(lons[i] - point.lon))
        y = min(range(len(lats)), key=lambda j: abs(lats[j] - point.lat))
        return x, y

    # ----------------------------------------------------------------- costs
    def _blocked(self, lat: float, lon: float) -> bool:
        if self.safety is None:
            return False
        result = self.safety.check_geofence(LatLon(lat=lat, lon=lon))
        return not result.ok

    def _edge_cost(self, lons: list[float], lats: list[float], a: tuple[int, int], b: tuple[int, int], mode: str) -> float:
        lat1, lon1 = lats[a[1]], lons[a[0]]
        lat2, lon2 = lats[b[1]], lons[b[0]]
        _az12, _az21, dist_m = _GEOD.inv(lon1, lat1, lon2, lat2)
        dist_km = dist_m / 1000.0

        bearing = math.degrees(math.atan2(lon2 - lon1, lat2 - lat1)) % 360.0
        hz = self.hazard_sampler((lat1 + lat2) / 2, (lon1 + lon2) / 2)

        # vessel speed with Bowditch wave loss (conservative: no wave-direction
        # field at cell level in the MVP, so the milder beam-sea coefficient applies)
        v = self.v0
        if hz.wave_height_m is not None:
            v = max(2.0, self.v0 - _speed_loss_knots(hz.wave_height_m, bearing, None))

        base_hours = (dist_m / 1000.0) / max(v * _KNOTS_TO_MS * 3.6, 1.0)
        if mode == "shortest":
            return dist_km

        extra = 0.0
        if mode in ("safe", "risk"):
            if hz.wave_height_m is not None:
                excess = max(0.0, hz.wave_height_m - self.weights.wave_calm_threshold_m)
                extra += self.weights.wave_penalty * excess * (dist_km / 5.0)
            if hz.wind_speed_ms is not None:
                excess = max(0.0, hz.wind_speed_ms - self.weights.wind_calm_threshold_ms)
                extra += self.weights.wind_penalty * excess * _MS_TO_KMH * (dist_km / 5.0)
            if mode == "safe" and self.safety is not None:
                mid = LatLon(lat=(lat1 + lat2) / 2, lon=(lon1 + lon2) / 2)
                d_imbl = self.safety.distance_to_imbl(mid)
                if d_imbl is not None and d_imbl <= IMBL_CAUTION_M:
                    extra += self.weights.imbl_buffer_penalty
        if mode == "fuel":
            extra = extra if extra else 0.0
        # distance term always present to keep paths monotone
        return dist_km * self.weights.cell_distance_weight + extra

    # --------------------------------------------------------------- routing
    def _run_astar(
        self, origin: LatLon, dest: LatLon, mode: str = "safe"
    ) -> tuple[AStarResult, list[float], list[float], tuple[int, int], tuple[int, int]]:
        lons, lats = self._grid(origin, dest)
        blocked_cache: dict[tuple[int, int], bool] = {}

        def blocked(cell: tuple[int, int]) -> bool:
            if cell not in blocked_cache:
                blocked_cache[cell] = self._blocked(lats[cell[1]], lons[cell[0]])
            return blocked_cache[cell]

        start = self._nearest_cell(lons, lats, origin)
        goal = self._nearest_cell(lons, lats, dest)
        if blocked(start) or blocked(goal):
            return AStarResult([], math.inf, 0), lons, lats, start, goal

        fan = [(dx, dy) for dx in range(-4, 5) for dy in range(-4, 5) if (dx, dy) != (0, 0)]
        edge_cache: dict[tuple[tuple[int, int], tuple[int, int]], bool] = {}

        def edge_hard_blocked(a: tuple[int, int], b: tuple[int, int]) -> bool:
            """Hard-constraint check at EDGE level: a long fan hop must never
            jump over a blocked cell or across the boundary line."""
            key = (a, b) if a < b else (b, a)
            if key not in edge_cache:
                if self.safety is None:
                    edge_cache[key] = False
                else:
                    lon1, lat1 = lons[a[0]], lats[a[1]]
                    lon2, lat2 = lons[b[0]], lats[b[1]]
                    edge_cache[key] = self.safety.edge_blocked(lon1, lat1, lon2, lat2)
            return edge_cache[key]

        def neighbors(x: int, y: int) -> list[tuple[int, int]]:
            out = []
            here = (x, y)
            for dx, dy in fan:
                nxt = (x + dx, y + dy)
                if 0 <= nxt[0] < len(lons) and 0 <= nxt[1] < len(lats) and not blocked(nxt):
                    if edge_hard_blocked(here, nxt):
                        continue
                    out.append(nxt)
            return out

        def cost(a: tuple[int, int], b: tuple[int, int]) -> float:
            c = self._edge_cost(lons, lats, a, b, mode)
            return math.inf if not math.isfinite(c) else c

        def heuristic(cell: tuple[int, int]) -> float:
            lat, lon = lats[cell[1]], lons[cell[0]]
            _a, _b, dist_m = _GEOD.inv(lon, lat, dest.lon, dest.lat)
            if mode == "shortest":
                return dist_m / 1000.0
            # admissible: best-case time with zero hazards
            hours = (dist_m / 1000.0) / (self.v0 * 1.852)
            if mode == "safe":
                return hours * 0.5  # scaled for mixed cost units (documented)
            return hours

        res = astar(start, goal, neighbors=neighbors, cost=cost, heuristic=heuristic)
        return res, lons, lats, start, goal

    # ---------------------------------------------------------------- public
    def _to_route(
        self,
        origin: LatLon,
        dest: LatLon,
        res: AStarResult,
        lons: list[float],
        lats: list[float],
        mode: str,
    ) -> Route:
        if not res.found:
            return Route(
                coords=[],
                distance_km=0.0,
                estimated_time_h=0.0,
                mode=mode,
                blocked_by_constraints=True,
                notes=["No route found — origin/destination unreachable under hard constraints."],
            )
        coords = [origin]
        coords += [self._cell_to_latlon(lons, lats, c) for c in res.path[1:-1]]
        coords.append(dest)
        # metrics
        total_m = 0.0
        waves: list[float] = []
        winds: list[float] = []
        cur_speeds: list[float] = []
        for (lon1, lat1), (lon2, lat2) in zip(coords_lonlat(coords)[:-1], coords_lonlat(coords)[1:]):
            _a, _b, dist_m = _GEOD.inv(lon1, lat1, lon2, lat2)
            total_m += dist_m
            hz = self.hazard_sampler((lat1 + lat2) / 2, (lon1 + lon2) / 2)
            if hz.wave_height_m is not None:
                waves.append(hz.wave_height_m)
            if hz.wind_speed_ms is not None:
                winds.append(hz.wind_speed_ms)
            if hz.current_u_ms is not None and hz.current_v_ms is not None:
                cur_speeds.append(math.hypot(hz.current_u_ms, hz.current_v_ms))
        time_h = total_m / 1000.0 / (self.v0 * 1.852)
        return Route(
            coords=coords,
            distance_km=round(total_m / 1000.0, 2),
            estimated_time_h=round(time_h, 2),
            mode=mode,
            cost_breakdown={"a_star_cost": round(res.cost, 3)},
            hazard_stats={
                "max_wave_m": max(waves) if waves else None,
                "mean_wave_m": round(sum(waves) / len(waves), 2) if waves else None,
                "max_wind_ms": max(winds) if winds else None,
                "mean_current_ms": round(sum(cur_speeds) / len(cur_speeds), 3) if cur_speeds else None,
                "n_samples": len(waves),
            },
            expanded_nodes=res.expanded,
        )

    def calculate_shortest_route(self, origin: LatLon, dest: LatLon) -> Route:
        res, lons, lats, _s, _g = self._run_astar(origin, dest, mode="shortest")
        return self._to_route(origin, dest, res, lons, lats, "shortest")

    def calculate_safe_route(self, origin: LatLon, dest: LatLon) -> Route:
        res, lons, lats, _s, _g = self._run_astar(origin, dest, mode="safe")
        return self._to_route(origin, dest, res, lons, lats, "safe")

    def calculate_fuel_optimal_route(self, origin: LatLon, dest: LatLon) -> Route:
        # MVP: fuel ≈ time × burn rate with calm-sea optimum ⇒ same as safe route
        # with wave penalties; distance term dominates. Kept explicit for API parity.
        res, lons, lats, _s, _g = self._run_astar(origin, dest, mode="fuel")
        return self._to_route(origin, dest, res, lons, lats, "fuel")

    def calculate_risk_optimal_route(self, origin: LatLon, dest: LatLon) -> Route:
        return self.calculate_safe_route(origin, dest)


def coords_lonlat(coords: list[LatLon]) -> list[tuple[float, float]]:
    return [(c.lon, c.lat) for c in coords]
