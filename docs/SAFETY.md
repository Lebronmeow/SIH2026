# ORCA — Safety & Trust Requirements (non-negotiable)

These rules were part of the original problem statement and are enforced in
code, not in prose. Each rule lists where it is enforced.

## 1. The LLM never computes science

The LLM layer (when `ORCA_LLM_*` is configured) does exactly three things:
parse refinement, orchestration, and explanation drafting. It may never
calculate a coordinate, distance, score, geofence verdict, or override a
safety statement.

| Question | Who answers | Where |
| --- | --- | --- |
| Is this point inside a protected area? | `GeospatialSafetyEngine.check_geofence` (Shapely prepared geometries) | `app/engines/geospatial/safety.py` |
| How far is the IMBL? | UTM-projected distance in the same engine | `app/engines/geospatial/safety.py` |
| Is this route legal? | `edge_blocked` per segment + `check_route_safety` | `app/engines/routing/engine.py`, `app/engines/geospatial/safety.py` |
| Which zone ranks first? | `ZoneEvaluationService` (deterministic scoring) | `app/services/zone_evaluator.py` |
| What does the SST value mean for the fisherman? | LLM/template *explains* the computed numbers | `app/agents/explainer.py` |

## 2. Never fabricate

* A missing measurement is returned as `quality=MISSING, value=None` — never
  interpolated into a number, never skipped silently.
  (`app/providers/hub.py` wraps provider failures into MISSING.)
* A failed Bhashini call raises (`BhashiniError`) → HTTP 502/503 structured
  body — never a invented translation. Same-language requests echo without
  touching an MT model.
* An empty data pack produces the honest verdict
  **INSUFFICIENT_DATA**: *"Unable to make a reliable recommendation with the
  currently available data"* — no zones ranked, no recommendation emitted.
  (Enforced by `FishingAdvisoryWorkflow._verify`: `INSUFFICIENT_DATA` + a
  recommendation is a verification failure.)

## 3. Hard constraints are absolute

IMBL proximity, protected-area polygons and land are **blocked cells and
blocked edges** in the A* router — infinite edge cost, never a soft weight,
never editable after the fact (`app/engines/routing/engine.py`). The verifier
re-checks the recommended zone's geofence and the route's legality before the
response leaves the pipeline.

## 4. Provenance on every scientific value

Every measurement carries `provenance`: source id/name, dataset, retrieval
time, valid time, unit, spatial resolution and **mode** (`demo`/`live`).
Evidence claims are cross-checked against the measurements they cite
(variable, value ±1e-6, unit, provenance presence) by the verifier.

## 5. Demo mode is visible by design

* Every demo value is flagged `quality=STALE` with a `DEMO/CACHED` note.
* The API sets `demo_banner_required` and the UI renders the banner
  **DEMO / CACHED DATA — not live observations** persistently.
* `/api/system/status` is the banner source of truth for the frontend.
* Synthetic demo inputs (AIS traffic, MPA polygon, land mask) are labeled
  `synthetic: true` in the pack and in every derived claim.

## 6. Authority labeling for boundaries

Geometry from GIS aggregators (VLIZ/Marine Regions) is `authority="reference"`
— displayed with a REFERENCE ONLY badge. Only treaty-annex survey coordinates
may be marked `authority="authoritative"`. Reference boundaries still act as
hard constraints for routing; authority affects *legal display*, not caution.

## 7. No secrets, no invented identifiers

* All configuration via `ORCA_`-prefixed environment variables (`.env`, git-ignored).
* ERDDAP dataset ids live in `backend/app/config/datasets.json` — never
  hardcoded in Python.
* Bhashini serviceIds come from `ORCA_BHASHINI_*_SERVICE_ID` (per-tenant
  catalog picks) — never guessed in code.
