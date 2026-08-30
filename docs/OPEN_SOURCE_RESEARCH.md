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
- Marine API (waves, SST, ocean currents), weather API (wind), **geocoding API**
  (place → lat/lon, used by the PlaceResolver with a coarse built-in port gazetteer
  as offline fallback).
- **Resilience role**: when a primary ERDDAP host is unreachable (outage, or
  datacenter-IP blocking), the hub falls back to Open-Meteo point forecasts sampled
  on a deterministic lattice over the query bbox — wind and current vectors are
  decomposed from the provider's speed+direction by documented formulas recorded in
  provenance (never invented numbers). Provider resolution ~8 km for currents, so
  provenance marks those grids indicative near coasts.

## 3. Geospatial

### GeoPandas / Shapely / pyproj — **A**
- **Licenses**: BSD-3 / BSD-3 / MIT. Shapely ≥2.0 `prepared` geometries for fast
  point-in-polygon + edge/segment tests; pyproj `Geod` (WGS84) for all geodesic
  distance/bearing math and per-UTM-zone `Transformer` projections (EPSG:32644 for
  ~79°E) with projection caching.

### GSHHG shoreline — **A** (data source, replaces Natural Earth 10m for land)
- **License**: LGPL-3.0 · **Citation**: Wessel, P., and W. H. F. Smith (1996),
  *A global, self-consistent, hierarchical, high-resolution geography database*,
  J. Geophys. Res. — the shoreline product behind chart plotters.
- Full-resolution (L1) land polygons clipped to the pilot bbox are committed at
  `data/demo/rams/boundaries/land_gshhg_full.geojson` (~100 m coastal accuracy vs
  Natural Earth 10m's ~2–3 km error). Zone placement, coastal exclusion and route
  safety all test against this layer. Attribution + retrieval date in
  `data/demo/rams/boundaries/ATTRIBUTION.md`.

### OpenStreetMap (Overpass API) — **A** (data source, protected-area geometry)
- **License**: ODbL 1.0. Real marine-protected-area boundaries can be pulled from
  OSM relations (`protect_class=2`): the Gulf of Mannar Marine National Park
  (relation 415570, polygonized from its member ways, ~480 km² vs the official
  ~560 km²) ships at `data/demo/rams/boundaries/mpa_gulf_of_mannar.geojson`,
  replacing the synthetic demo polygon. Labeled REFERENCE in ATTRIBUTION.md —
  OSM boundaries are not legally definitive.

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
  to the repo and never shipped in the demo pack. The demo pack's MPA layer is the
  OSM polygon above (see OpenStreetMap entry).

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

## 10. Team-sourced resources — evaluated 2026-08-30

The team circulated nine additional resources mid-build. Each was inspected for
license, machine readability, and fitness as **advisory input** (ORCA's honesty
rules: deterministic engines need numeric, attributable, current data — imagery
portals and synthetic datasets cannot feed a safety recommendation).

### Float-Chat (github.com/ARPANPATRA111/Float-Chat) — **C**
- **License**: **NONE** (no LICENSE file ⇒ all rights reserved) → never copy code.
- SIH-2025 prior art: RAG chatbot over Argo floats (Streamlit + Ollama Llama 3.2 +
  PostGIS + ChromaDB, fully local). Validates the "ask the ocean data" UX.
- ORCA deliberately differs: the LLM explains *deterministic engine output* and is
  never the thing that computes an answer — a RAG-bot that answers numeric
  questions from a vector store cannot guarantee that containment.

### WOD introduction PDF (NCEI `wod_intro.pdf`) — **C**
- NOAA World Ocean Database documentation (public domain as US-gov work). Bulk
  archival profile data with no advisory-latency API; background reference for
  in-situ/Argo provenance. Nothing to wire.

### Kaggle "Shifting Seas" dataset — **D** (as data source)
- Apache-2.0, but 500 rows / 34 kB, **explicitly synthetic** ("synthetic-yet-realistic"),
  global reefs (Great Barrier Reef, Red Sea), frozen 2015–2023, "never" updated.
- Synthetic values must never enter a real advisory (the no-fabrication rule);
  wrong geography, no currency. Usable only as a toy CSV for slide mock-ups —
  never behind a recommendation.

### NESDIS "Earth in Real-Time" — **C** (viewer) · underlying data already **A**
- ArcGIS-browser map app; the page documents no public machine-readable endpoints.
- The *numeric* NESDIS product ORCA needs (daily chlorophyll) is already wired
  programmatically via NOAA CoastWatch ERDDAP (`nesdisVHNSQchlaDaily`, §2) — the
  team's link is the human-facing face of the same agency's holdings.

### MOSDAC AFS (Alerts & Forewarning) — **C**
- ISRO MOSDAC portal: registration-gated, browser-first; no documented public
  GeoJSON/alert API was found (page content is JS-only).
- The official-alert requirement is now covered by the deterministic
  `official_warnings` provider (2026-08-30): keyless GDACS mirror + config-gated
  INCOIS GEMINI feeds (High Wave / Swell Surge / Storm Surge) + an IMD hook. If
  MOSDAC ever exposes a machine-readable feed, it slots in there as one more
  config-driven source.

### MOSDAC oil-spill page — **C**
- Title-only page, no documented API. Oil-spill detection is a research product;
  relevant to the problem statement's pollutant-drift stretch goal as a concept,
  not a wireable feed today.

### NASA Worldview — **C**
- Browser for NASA GIBS. GIBS does expose WMTS + an image-download API, but the
  layers are **imagery** (PNG/JPEG), not numeric grids — cannot feed engines.
  Public domain; useful for visual satellite context in slides/demo, not as input.

### Copernicus Browser (Dataspace) — **C**
- ESA's interactive Sentinel browser (team tested an OCEAN-theme custom composite).
  Interactive-first; programmatic access (openEO/OGC) needs registration.
  Sentinel-3 OLCI chlorophyll/SST via openEO is a credible post-hackathon upgrade
  path; not needed for the prototype (ERDDAP covers it keyless).

### Copernicus Marine Service (CMEMS) — **B** (strongest of the nine)
- Free with registration; `copernicusmarine` toolbox, OPeNDAP/ARCO access;
  global analysis+forecast physics / waves / biogeochemistry, Indian Ocean
  covered. The page itself confirms scope ("free, open … blue, white, green").
- **Role for ORCA**: production failover/upgrade for currents, waves and
  biogeochemistry behind the same provider-resolution pattern as the Open-Meteo
  fallback — config-gated, never a hardcoded dependency of the demo path.

### zoom.earth — **C**
- Neave Interactive viewer (GOES/Meteosat/Himawari imagery, ICON/GFS overlays,
  storm tracks from NHC/JTWC/IBTrACS). **No public API**; ToS-gated; its fire
  layer is explicitly "not for the preservation of life or property".
- At best a manual cross-check screen during the demo; ORCA's cyclone warnings
  come from GDACS/INCOIS/IMD machine feeds directly (one step upstream of what
  zoom.earth itself consumes).

### Outcome of the evaluation
- Shipped as a direct result: `backend/app/providers/official_warnings.py`
  (GDACS keyless cyclone check + INCOIS GEMINI + IMD hooks) — closing the
  problem statement's "Cyclone / High Wave Warnings (IMD)" input.
- Recorded as production path: CMEMS behind the provider registry.
- Rejected as advisory input: synthetic Kaggle data, imagery-only viewers
  (NESDIS viewer, Worldview, Copernicus Browser, zoom.earth) — honest-capability
  verdicts, not blanket dismissals; each has the exact reason above.

## 11. Rule kept throughout

> No code was copied from any repository before its license was checked. GPL
> components never entered the dependency tree of ORCA's default path. Dataset
> IDs were verified live, never invented.
