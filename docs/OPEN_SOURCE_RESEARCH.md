# Open-Source Research — SIH26176 ORCA

Researched **before** implementation, per the problem statement. Every listed
component was inspected (README, API surface, examples, license file) by
dedicated research passes on 2026-08-29; dataset IDs quoted here were
**live-verified against the actual servers** the same day.

Verdict legend:

| Verdict | Meaning |
|---------|---------|
| **A** | Direct dependency — used as published |
| **B** | Copy/adapt small parts (license permits) or integrate with glue |
| **C** | Reference only — read design/papers, no code reuse |
| **D** | Rejected — license or fitness problem |

---

## 1. Agent orchestration

### Microsoft Agent Framework (`agent-framework`) — **A**
- **License**: MIT · **Version inspected/installed**: 1.16.0 (PyPI `agent-framework`)
- **What it is**: Microsoft's unified agent + workflow framework (successor to
  Semantic Kernel agents / AutoGen patterns). Pure-Python workflow engine:
  `Executor` subclasses with `@handler` methods, `WorkflowBuilder(start_executor=…)
  .add_edge(a, b).build()`, `workflow.run(msg)` → `WorkflowRunResult.get_outputs()`.
- **Key API facts verified by running code**: handler return values are *ignored* —
  data moves only via `await ctx.send_message(msg, target_executor_id)` and
  `await ctx.yield_output(msg)`; handlers must annotate the context
  (`WorkflowContext[T]`, `WorkflowContext[T, U]`); `WorkflowBuilder.__init__` takes
  `start_executor` as a keyword-only arg.
- **How ORCA uses it**: `backend/app/agents/orchestrator.py` expresses the ORCA
  pipeline (parse → master → specialists → verify → explain) once as a MAF graph.
  All executors are thin wrappers around deterministic ORCA services. When an LLM
  key is configured, parser/master/explainer swap to Agent-backed variants; the
  scientific executors never do.
- **Why not LangGraph supervisor**: `langgraph-supervisor` is **soft-deprecated**
  (README directs new work to Agent Framework / other options) → verdict **C**.
  `agent-framework-samples` repo → verdict **C** (worked examples, no reuse needed).

## 2. Ocean / weather data access

### erddapy — **A**
- **License**: BSD-3-Clause · **Version**: 3.3.0
- ERDDAP→Python client. `ERDDAP(server=…, protocol="griddap", dataset_id=…)` →
  `griddap_initialize()` seeds `constraints`; you narrow time/lat/lon, pin extra
  dimensions (ww3_global has `depth`, NESDIS chlorophyll has `altitude`), then
  `to_xarray()`.
- **How ORCA uses it**: `backend/app/providers/erddap_provider.py`. Dataset IDs are
  **never hardcoded** — `backend/app/config/datasets.json` maps logical variable →
  concrete `{server, dataset_id, variable, extra_dim}` (verified live, below).
- **Live-verified datasets (2026-08-29)**:

| Logical var | Server | dataset_id / var | Resolution | Notes |
|---|---|---|---|---|
| SST | NOAA `https://coastwatch.pfeg.noaa.gov/erddap` | `jplMURSST41` / `analysed_sst` | 0.01°, daily | verified 30.254 °C at Rameswaram |
| Chlorophyll | NOAA | `nesdisVHNSQchlaDaily` / `chlor_a` | 0.0375°, daily | has `altitude` dim — pinned |
| Currents (NRT) | NOAA NWS | `noaacwBLENDEDNRTcurrentsDaily` / `u_current`,`v_current` | 0.25°, daily | |
| Currents (fallback) | NOAA | `nesdisSSH1day` / `ugos`,`vgos` | ~5-month publication lag | fallback only, provenance marks lag |
| Waves | NOAA NWS | `ww3_global` / `Thgt`,`Tper`,`Tdir` | 0.5°, hourly, +7 d | has `depth` dim — pinned |
| Wind | NOAA NWS | `ncep_global` / `ugrd10m`,`vgrd10m` | 0.25°, 6-hourly | |
| SST anomaly / DHW | NOAA | `dhw_5km` / `CRW_SSTANOMALY` | 5 km | |
| Argo profiles | INCOIS | `Indian_ARGO_Floats` (tabledap) | profiles | INCOIS ERDDAP |

- **INCOIS ERDDAP server**: correct base URL is
  `https://erddap.incois.gov.in/erddap` (the older `incois.gov.in/erddap` 404s).
  Its TLS chain is incomplete → provider uses `requests_kwargs={"verify": False}`
  **only for this server**, logged, and its gridded holdings are archival rather
  than NRT. Verdict for INCOIS as a source: **B** (server integration, no code).

### xarray (+ netCDF4) — **A**
- **License**: Apache-2.0 · **Version**: 2026.7.0
- Canonical in-memory field representation. ORCA renames every provider's dims to
  `time/latitude/longitude` once at ingestion so engines stay provider-agnostic.

### Open-Meteo — **A**
- **License/attribution**: free, no key, non-commercial use, **CC-BY 4.0 — attribution
  required** (carried in ORCA's sources list and UI footer).
- Marine API (waves), weather API (wind), **geocoding API** (place → lat/lon, used by
  the PlaceResolver with a coarse built-in port gazetteer as offline fallback).

## 3. Geospatial

### GeoPandas / Shapely / pyproj — **A**
- **Licenses**: BSD-3 / BSD-3 / MIT. Shapely ≥2.0 `prepared` geometries for fast
  point-in-polygon + edge/segment tests; pyproj `Geod` (WGS84) for all geodesic
  distance/bearing math and per-UTM-zone `Transformer` projections (EPSG:32644 for
  ~79°E) with projection caching.

### Marine Regions (VLIZ) — **A** (data source)
- **License**: CC-BY 4.0 · DOI 10.14284/632 · WFS `MarineRegions:eez_boundaries`.
- **India–Sri Lanka IMBL** fetched as GeoJSON via
  `CQL_FILTER=line_id=1306` (1974 treaty, Palk Strait) and `line_id=1311` (1976
  Gulf of Mannar extension) — treaty-based boundary lines, the legally relevant
  geometry for the "did the route cross the IMBL" test. Cached in
  `data/demo/boundaries/` **with attribution file**.

### WDPA / Protected Planet — **B** (runtime-only, licensed data)
- **License**: free API key after manual approval; **redistribution of WDPA
  geometry is NOT permitted**.
- **How ORCA uses it**: `ProtectedAreaProvider` fetches at *runtime* with the
  operator's own key (`ORCA_PROTECTED_PLANET_API_KEY`); geometry is never committed
  to the repo and never shipped in the demo pack. Demo MPA polygons are synthetic
  and clearly labeled.

### PostGIS — **D** (for this prototype; optional in deployment)
- **License**: GPL-2.0. Docker-compose includes it for the "ops" configuration, but
  the default path is file-based GeoJSON + SQLite so the demo runs without GPL
  components installed. The geospatial engine is written against an abstract layer
  store, so a PostGIS backend can be swapped in without touching engines.

## 4. Routing

### SIMROUTE — **C** (no license → never copy code)
- **License**: **NONE** (all rights reserved). We inspected the algorithms only.
- **What we took as *concepts*** (citing Grifoll,-fontela & Sotillo, *Ocean
  Engineering* 255:111427, 2022): 8/16/48-neighbor fan grid, admissible heuristic
  `dist/v0`, time-indexed environmental fields, NaN-land masking, cost factors for
  waves/wind/currents.
- **What we wrote instead**: `backend/app/engines/routing/` — ~350-line A* on
  Python's `heapq` with **edge-level hard-constraint enforcement**
  (`GeospatialSafetyEngine.edge_blocked` — segment-vs-geometry, so no hop can jump
  over the IMBL or land), Bowditch (public-domain) speed-loss model
  `ΔV = k·Hs_ft²` (k = 0.0248 head / 0.0165 beam / 0.0083 following).

### pgRouting — **D** (rejected)
- **License**: GPL-2.0 → incompatible with ORCA's permissive composition. Also
  would force PostGIS into the default path. This is the problem statement's
  explicit GPL test case.

### `pathfinding` (PyPI) — **C**
- Simple grid A*/Dijkstra, but grid-only (no edge-level geofence hooks, no
  time-indexed costs). Our own A* is smaller than the glue it would need.

## 5. Front detection (productivity features)

### ORCA deterministic front engine (own code, informed by literature) — shipped
- `backend/app/engines/ocean/front_detection.py`: gradient magnitude → per-km via
  `111.32·cos(lat)`, windowed local contrast (`scipy.ndimage.uniform_filter`),
  percentile threshold, connected components (`ndimage.label`), normalized strength
  vs documented caps (SST 0.25 °C/km, chlorophyll 0.30 log₁₀/km).
- Strategy Protocol is the plug point: an ML detector can be dropped in without
  touching the workflow.

### JUNO — **A/B**
- **License**: MIT. Front-detection package with importable `detect_fronts`
  (Canny/BOA/CCA) — needs `opencv-python`. Kept as the **optional ML upgrade
  path** behind the Strategy Protocol; not a runtime dependency of the demo
  (image-binary dependency not worth it for the hackathon build).

### MIT-STARLab — **C** (research reference; MATLAB-centric)

### MSP-Symphony — **C** (marine spatial planning workflow reference)

## 6. Vessel data

### pyais — **A**
- **License**: MIT · **Version**: 3.2.1. AIS NMEA decoding. AIS stream ingestion
  runs through a backend proxy (aisstream.io free WS allows ~3 connections/IP);
  a clearly-labeled simulator is the fallback so the demo never depends on
  external socket availability.

## 7. Speech / translation

### Bhashini (Dhruva pipeline) — **B**
- **License**: free Government of India platform (API key per app). We studied
  `bhashini-api-examples` (Apache-2.0) → verdict **B**, and ULCA docs → **C**.
- **Pipeline API shape** (verified from docs): POST to the pipeline URL with
  `Authorization: <api-key>` and `pipelineTasks` for **asr / translation / tts**;
  each task carries its `serviceId`. ORCA wraps this behind
  `SpeechService` / `TranslationService` / `TextToSpeechService` with
  `ORCA_BHASHINI_ENABLED=false` default and graceful English-only fallback.

## 8. Frontend

### MapLibre GL JS — **A** (BSD-3, v6.6) + `@vis.gl/react-maplibre` (MIT)
### deck.gl — **A** (MIT, v9.3) + `@deck.gl/mapbox` `MapboxOverlay` for MapLibre
- **Basemap**: OpenFreeMap `https://tiles.openfreemap.org/styles/liberty` —
  verified no-key, no billing.
- All geo layers render from the same GeoJSON the engines computed — no client-side
  recomputation of anything scientific.

## 9. Rejected / not adopted (summary)

| Component | Verdict | Reason |
|---|---|---|
| pgRouting | **D** | GPL-2.0; forces PostGIS; own A* is small |
| SIMROUTE (code) | **C** | **No license** — concepts/paper only |
| langgraph-supervisor | **C** | soft-deprecated upstream |
| `pathfinding` | **C** | no edge-geofence / time-indexed cost support |
| WDPA geometry redistribution | **B** | license forbids redistribution → runtime fetch only |

## 10. Rule kept throughout

> No code was copied from any repository before its license was checked. GPL
> components never entered the dependency tree of ORCA's default path. Dataset
> IDs were verified live, never invented.
