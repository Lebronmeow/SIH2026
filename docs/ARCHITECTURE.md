# ORCA Architecture — SIH26176

```
                                  ┌──────────────────────────────────────────────┐
   fisher query (text/voice)      │                FRONTEND (React)              │
   "safest productive zone 20 km  │  MapLibre + deck.gl · 3-panel · WHY THIS ZONE│
    off Rameswaram tomorrow"      │  DEMO banner from /api/system/status         │
                                  └──────────────────┬───────────────────────────┘
                                                     │ POST /api/query
                                  ┌──────────────────▼───────────────────────────┐
                                  │              FASTAPI (thin)                  │
                                  └──────────────────┬───────────────────────────┘
                                                     │
        ┌────────────────────────────────────────────▼──────────────────────────────────┐
        │                     AGENT LAYER (Microsoft Agent Framework)                   │
        │                                                                               │
        │  QueryUnderstandingExecutor ──► MasterExecutor ──► ZoneEvaluationExecutor      │
        │  (deterministic parser;   │     (thin router,      │  (deterministic engines)  │
        │   LLM optional, JSON-only)│      LLM optional)     │                           │
        │                                                    ▼                          │
        │                              VerificationExecutor ──► ExplanationExecutor      │
        │                              (integrity + hard         (template; LLM optional,│
        │                               constraint re-check)      evidence-constrained)  │
        └──────────────┬───────────────────────────────────────────────────┬────────────┘
                       │ calls                                             │
        ┌──────────────▼─────────────────────┐   ┌─────────────────────────▼───────────┐
        │        SCIENTIFIC ENGINES          │   │            PROVIDERS                │
        │  (pure deterministic Python)       │   │  (all external data, provenance)    │
        │                                    │   │                                     │
        │ OceanDataHub ─► ErddapProvider     │   │ ERDDAP (NOAA/INCOIS via erddapy)    │
        │                OpenMeteoProvider   │   │ Open-Meteo (marine/weather/geo)     │
        │                DemoOceanProvider   │   │ VLIZ Marine Regions WFS (IMBL)      │
        │                                    │   │ WDPA runtime fetch (no redistribution│
        │ FrontDetectionEngine               │   │ AIS proxy (pyais / simulator)       │
        │   (gradient → components;          │   │ Bhashini Dhruva (asr/mt/tts, opt.)  │
        │    ML Strategy plug point)         │   └─────────────────────────────────────┘
        │ GeospatialSafetyEngine             │
        │   (geofence, IMBL distance,        │
        │    edge-level route blocking)      │
        │ RouteOptimizationEngine (A*)       │
        │   (shortest/safe/fuel/risk modes)  │
        │ RecommendationScoringEngine        │
        │   (configurable, PROTOTYPE-labeled)│
        └────────────────────────────────────┘
```

## The non-negotiable boundary

| Concern | Who does it | Never |
|---|---|---|
| Parsing intent, explaining | LLM (optional) or deterministic templates/regex | — |
| Retrieving data | Providers (erddapy / httpx / file) | LLM |
| Point-in-MPA / IMBL distance / route-leg blocking | Shapely + pyproj | LLM |
| Scores, ranks, route cost, ETA | Scoring + routing engines | LLM |
| "Is this inside the IMBL?" | `GeospatialSafetyEngine.check_geofence` | LLM |

The LLM (when configured) only **refines parsing** (strict JSON, coordinates still
resolved by the PlaceResolver) and **narrates evidence** (constrained to the
evidence list; warnings and DEMO notices must survive). Hard constraints are
absolute and are re-checked by the Verification executor *after* any LLM step.

## Component map (repo)

| Path | Role |
|---|---|
| `backend/app/config/` | Settings (env-prefixed `ORCA_`), DataSourceRegistry (authority labels), `datasets.json` (logical→concrete dataset mapping, **no hardcoded IDs in code**), `erddap_servers.json` (priority + failover) |
| `backend/app/providers/` | `OceanDataHub` (mode-aware failover), `ErddapProvider` (erddapy; extra-dim pinning; freshness flags), `OpenMeteoProvider`, `DemoOceanProvider` (STALE-labeled), `base.OceanField` (canonical dims + provenance) |
| `backend/app/engines/ocean/` | `FrontDetectionEngine` + `FrontStrategy` protocol (deterministic first, ML pluggable) |
| `backend/app/engines/geospatial/` | `BoundaryLayer` loading (GeoJSON, authority metadata), `GeospatialSafetyEngine` (`check_geofence`, `distance_to_imbl`, `edge_blocked`, `check_route_safety`) with per-UTM-zone projection caches |
| `backend/app/engines/routing/` | `astar.py` (heapq A*), `RouteOptimizationEngine` (80-neighbor fan, edge-level hard constraints, Bowditch speed loss, time-indexed hazards) |
| `backend/app/engines/scoring/` | `RecommendationScoringEngine` — weight-redistributing missing components; `weight_coverage < 0.5 → insufficient`; every response labels weights "prototype — not scientifically validated" |
| `backend/app/agents/` | MAF `orchestrator.py` (topology), `query_parser.py` (deterministic + LLM), `explainer.py` (template + LLM) |
| `backend/app/services/` | `zone_evaluator.py` (ring candidates → fetch-once → sample → score → rank → route → evidence), `place_resolver.py`, `response_store.py` |
| `backend/app/workflows/` | `advisory.py` — the same pipeline driven directly (no-framework path, used as fallback) |
| `backend/app/api/routes/` | `health` (`/api/health`, `/api/system/status` incl. demo-banner truth), `advisory` (`/api/query`, `/api/recommendations/{id}`), `ocean` (`/api/ocean/point|fields|sources`), `safety` (`/api/safety/check`, `/api/route/optimize`) |
| `frontend/src/` | 3-panel dashboard; map layers = the exact GeoJSON the engines emitted |
| `data/demo/` | Demo pack: `ocean/*.nc`, `weather/*.json`, `boundaries/*.geojson` (+ attribution), `manifest.json` with retrieval dates |
| `docs/` | This file, OPEN_SOURCE_RESEARCH, IMPLEMENTATION_PLAN, THIRD_PARTY_LICENSES |

## Data flow for the demo query

1. **Parse** — deterministic regex/keyword parser extracts distance (20 km),
   objectives (safe+productive), relative time ("tomorrow morning" → 05:00–11:00 IST
   of tomorrow, as UTC), and the place phrase ("Rameswaram", trimmed before time
   words). Coordinates come from Open-Meteo geocoding (builtin gazetteer fallback).
2. **Candidates** — 24 ring points at exactly 20 km (pyproj `Geod.fwd`), each
   geofence-checked *before* any data fetch; failures recorded with reasons (they
   still appear in the UI as "why this bearing was excluded").
3. **Fetch once** — 7 fields (SST, chlorophyll, waves, wind u/v, currents u/v) over
   the ring bounding box; one round-trip per variable, not per candidate. Empty
   results are `OceanField.empty()` — honest MISSING, never zeros.
4. **Front detection** — deterministic gradient/percentile engine on SST (°C/km) and
   log₁₀-chlorophyll (per km); strength normalized against documented caps.
5. **Score** — per candidate: nearest-cell samples → productivity (SST front,
   chl gradient, chl magnitude, current smoothness) and risk (wave, wind, current,
   boundary proximity); missing components redistribute weight; <50% coverage ⇒
   `insufficient`.
6. **Rank + route** — excluded zones sink; best zone gets a *safe-mode* A* route
   with edge-level IMBL/MPA/land blocking and hazard stats along the path.
7. **Evidence** — every number in the WHY panel maps to a `Measurement` with
   `Provenance` (source, dataset, retrieved_at, valid_time, resolution, unit,
   confidence, mode, authority).
8. **Verify** — integrity re-checks (recommended zone not excluded, geofence ok,
   route legal, DEMO banner consistent, INSUFFICIENT_DATA ⇒ no recommendation).
9. **Explain** — template renders the WHY from response fields only; LLM (if
   configured) may rewrite narration under the same evidence constraint.

## Safety & honesty model

- **Demo mode default** (`ORCA_DATA_MODE=demo`): every cached value carries
  `quality=STALE`, "DEMO / CACHED" notes, and the UI banner comes from
  `/api/system/status` (`demo_banner_required`) — not from a frontend flag.
- **Missing ≠ zero**: unavailable data returns `value: null` + explicit warnings
  (`NO_WAVE_DATA` etc.); the scoring engine reports which components were missing.
- **INSUFFICIENT_DATA**: when no zone can be scored (or all are excluded), the
  response says "Unable to make a reliable recommendation with the currently
  available data" with structured reasons and missing-variable list.
- **Authority labeling**: boundary layers carry `authority=authoritative|reference`;
  reference-only geometry produces a `REFERENCE_BOUNDARY` warning and a UI badge.
- **Staleness**: `max_age_days` per product → `QualityFlag.STALE` when exceeded.
- **Hard constraints**: IMBL/MPA/restricted/land layers are `hard_constraint=true`;
  the router treats them as absolute (edge-level check), and the verifier re-checks
  the final route. No LLM or weight can override them.

## Determinism & reproducibility

- The pipeline is the same code path in demo and live mode; only providers differ.
- Every response embeds a `WorkflowTrace` (per-step log with timings) — the demo
  panel shows exactly which engine ran and what it decided.
- Scores are labeled "prototype decision weights" everywhere they appear.
