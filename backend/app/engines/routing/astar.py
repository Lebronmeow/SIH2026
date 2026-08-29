"""Generic grid A* over lat/lon grids (own implementation).

Design notes (informed by, but containing no code from, SIMROUTE — Grifoll et
al. 2022, Ocean Engineering 255:111427, which carries **no open license**):

* ``heapq``-based open set (SIMROUTE's linear scan is O(N) per expansion).
* Neighbor fan: a 48-neighbour forward fan (4 cardinal + offsets up to ±4
  cells) produces smoother headings than an 8-connected grid — same concept
  SIMROUTE uses; the geometry here is computed independently.
* Edge cost functions are supplied by the caller (the routing engine wires in
  hazard terms); returning ``inf`` blocks the edge — hard constraints are
  enforced by cost, never by post-hoc route editing.
* Heuristic must be admissible: the engine supplies geodesic_distance / v_max.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AStarResult:
    path: list[tuple[int, int]]  # (x=lon_idx, y=lat_idx) cells
    cost: float
    expanded: int

    @property
    def found(self) -> bool:
        return bool(self.path)


def astar(
    start: tuple[int, int],
    goal: tuple[int, int],
    *,
    neighbors: object,  # Callable[[int, int], list[tuple[int, int]]]
    cost: object,  # Callable[[tuple, tuple], float]
    heuristic: object,  # Callable[[tuple[int, int]], float]
    max_expansions: int = 200_000,
) -> AStarResult:
    """A* on a discrete grid. ``cost(a, b)`` must return ``inf`` for blocked
    edges; ``heuristic(node)`` must never overestimate remaining cost."""
    open_heap: list[tuple[float, float, tuple[int, int]]] = []
    g_score: dict[tuple[int, int], float] = {start: 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    counter = 0
    h0 = heuristic(start)
    heapq.heappush(open_heap, (h0, 0.0, start))
    closed: set[tuple[int, int]] = set()
    expanded = 0

    while open_heap:
        f, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return AStarResult(path=path, cost=g_score[goal], expanded=expanded)
        closed.add(current)
        expanded += 1
        if expanded > max_expansions:  # safety valve for degenerate grids
            break
        gc = g_score[current]
        for nxt in neighbors(*current):  # type: ignore[operator]
            if nxt in closed:
                continue
            step = cost(current, nxt)  # type: ignore[misc]
            if not math.isfinite(step):
                continue
            tentative = gc + step
            if tentative < g_score.get(nxt, math.inf):
                g_score[nxt] = tentative
                came_from[nxt] = current
                counter += 1
                heapq.heappush(open_heap, (tentative + heuristic(nxt), float(counter), nxt))

    return AStarResult(path=[], cost=math.inf, expanded=expanded)
