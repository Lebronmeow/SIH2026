# ORCA — Marine Ecosystem Reasoning with Collaborative Agents

**SIH26176** — an agentic marine decision-support prototype for Indian fishermen.

**Live:** frontend <https://sih.lebronpereira.in> · backend <https://orca-backend-whvh.onrender.com> (API reference at `/docs`)

Ask in natural language or voice:

> *“Where is the safest and most productive fishing zone 20 km off Rameswaram tomorrow morning?”*

ORCA parses the request, retrieves **real** ocean/weather/geospatial data through official
provider APIs, runs **deterministic** scientific/geospatial engines (front detection,
hazard scoring, A* routing), checks maritime safety constraints (IMBL proximity,
protected areas), ranks candidate fishing zones, and returns an **evidence-backed**
recommendation with full provenance on an interactive map.

## The critical design rule

```
LLM  = reasoning, orchestration, explanation        (never computes science)
Engines = data retrieval + deterministic calculation (never hallucinated)
```

The LLM never answers “is this point inside the IMBL?”, never invents an SST value,
and never fabricates a wave height. It calls tools; the tools compute; every number
carries provenance (`source`, `dataset`, `retrieved_at`, `valid_time`, `unit`,
`confidence`, `mode`). When data is missing, ORCA says **“INSUFFICIENT_DATA”**.

## Why ORCA is different (the selling point)

Ask a general-purpose LLM “is it safe to fish off Rameswaram tomorrow?” and it will
answer confidently — inventing wave heights, recalling boundaries from memory,
guessing a confidence score. In a life-at-sea domain that confidence is the bug.
ORCA is engineered around the opposite premise:

| Typical "AI fishing advisor" | ORCA |
| --- | --- |
| LLM generates the answer, numbers included | LLM only orchestrates and explains — **deterministic engines compute every number** from real data |
| Boundaries recalled from model memory (often wrong) | IMBL treaty line, MPA/restricted polygons and land are **hard geofences enforced below the LLM** — it cannot argue its way across |
| “Waves ~1–2 m” (fabricated) | Every value carries **source, dataset, retrieval + valid time, unit and quality flag** — provenance or it doesn't ship |
| Missing data → confident guess | Missing data → **honest `MISSING` / `INSUFFICIENT_DATA`**; stale data → CACHED badge with the true observation date |
| One provider, one point of failure | **Fallback chains, circuit breakers, 429-aware retries, caches** — and the last real field served honestly labelled for 72 h |
| English text wall | **Voice in/out, 8 Indian languages**, GO / CAREFUL / STOP verdict plates built for low-literacy users |
| Unverifiable output | **Evidence records** (claim → basis → computation) + workflow trace + 38 offline tests incl. the 8 mandated critical ones |

One sentence: **the ocean's numbers come from satellites and models, the engines do
the science, the boundaries are law, the AI explains — and when the data isn't there,
ORCA tells the fisherman the truth instead of a confident guess.**

## Core features

- 🗣 **Ask anything, in your language** — natural-language or voice queries; replies
  natively in 8 Indian languages (English, Tamil, Telugu, Malayalam, Hindi, Bengali,
  Odia, Gujarati); read-aloud on every advisory.
- 🎯 **Ranked fishing zones** — 12 distance/bearing-ring candidates scored on SST and
  chlorophyll fronts, hazards and currents; every zone carries its own verdict and
  hazard flags; full scrollable ranking, not just the winner.
- 📊 **Zone comparison charts** — per-zone score bars (recommended zone highlighted,
  the rest de-emphasised) and wave bars checked against a red 2.5 m rough-sea line;
  tap a bar to select that zone; labelled in all 8 languages.
- 🛑 **Safety that cannot be overridden** — IMBL proximity, protected areas, land
  masking; per-zone rough-sea/strong-wind cautions; official cyclone and high-wave
  alerts (GDACS + INCOIS GEMINI, IMD hook ready).
- 🧭 **Safe routes** — A* routing in safe/shortest/fuel/risk modes that physically
  cannot cross a hard boundary; trip card with distance, duration and max wave on path.
- 🔍 **Evidence for every claim** — expandable evidence records and a workflow trace;
  measurement tiles show the exact dataset and observation date behind each number.
- 🛰 **Real data, resilient by design** — NOAA/PacIOOS/INCOIS/Open-Meteo provider chains
  with failover, caching and honest staleness labelling (see workflow below).

## Workflow

The full pipeline of one query — every box is real code in this repo:

```mermaid
flowchart TD
    U["🐟 Fisherman<br/>voice 🎙 or text"] --> UI["Frontend (React + MapLibre GL)<br/>8 Indian languages · liquid-glass UI"]

    U -- "voice" --> ASR["ASR: Bhashini Dhruva<br/>(fallback: local faster-whisper / Web Speech)"]
    ASR --> T
    U -- "text" --> T["Non-English? Bhashini NMT → English"]

    UI -->|"POST /api/query"| QP["Query Parser agent<br/>deterministic → ParsedQuery<br/>(origin, distance km, IST window, objective)"]

    QP --> HUB["OceanDataHub — provider failover"]

    subgraph SRC["Live data (all keyless / open)"]
        direction TB
        E1["NOAA PFEL ERDDAP<br/>SST (MUR GHRSST L4)"]
        E2["NOAA CoastWatch ERDDAP<br/>chlorophyll (VIIRS DINEOF)<br/>currents (blended NRT)"]
        E3["PacIOOS ERDDAP<br/>waves (WW3) · wind (GFS)<br/>SST fallback (CRW CoralTemp)"]
        E4["INCOIS ERDDAP<br/>Argo in-situ profiles"]
        E5["Open-Meteo<br/>point-forecast fallback grids"]
    end

    CACHE["Resilience layer<br/>429-aware retry · 30-min subset cache<br/>72-h last-good cache, disk-persisted across restarts (honestly labelled)"]
    HUB --> SRC
    HUB --> CACHE

    OW["Official warnings<br/>GDACS cyclones (keyless) · INCOIS GEMINI<br/>high-wave/swell/storm-surge · IMD hook (config)"]

    HUB --> GEO["Geospatial engine<br/>IMBL treaty line · MPA/restricted polygons<br/>land mask · coastal band (hard constraints)"]
    HUB --> FR["Front detection engine<br/>deterministic SST & log-chlorophyll gradients"]
    HUB --> ZE["Zone evaluator<br/>12 ring candidates → geofence check →<br/>productivity + risk scoring → per-zone hazard flags"]

    ZE --> RO["Routing engine — A*<br/>safe / shortest / fuel / risk · wave+wind penalty<br/>never crosses IMBL or protected polygons"]
    RO --> TC["Trip card<br/>distance · duration · max wave on path"]

    ZE --> ADV["Advisory assembler<br/>warnings + evidence (claim/basis/computation)<br/>+ provenance + workflow trace"]
    OW --> ADV
    GEO --> ADV

    ADV --> EX["Explainer<br/>native language output (no translation of output)<br/>LLM narrates when configured (free Gemini tier)<br/>deterministic templates are the fallback — never numbers"]
    EX --> UI

    UI --> OUT["Verdict plate (GO / CAREFUL / STOP)<br/>per-zone verdict on any selected zone<br/>all 12 ranked zones (scrollable) · zone detail<br/>evidence · trip card · read-aloud 🔊"]

    KA["Keep-alive pinger (GitHub Actions, 5 min)<br/>hits /api/system/warm — wakes the free tier<br/>AND refreshes every data cache"] -.-> UI
```

## Live data sources (all open / keyless)

| Variable | Primary source | Link | Fallback |
| --- | --- | --- | --- |
| Sea surface temperature | MUR GHRSST L4 (NASA JPL), 0.01°, daily | [jplMURSST41 @ NOAA PFEL](https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41) | CRW CoralTemp 5 km daily ([dhw_5km @ PacIOOS](https://pae-paha.pacioos.hawaii.edu/erddap/griddap/dhw_5km)) |
| Chlorophyll-a | VIIRS S-NPP/NOAA-20, DINEOF gap-filled, 9 km, NRT daily | [noaacwNPPN20VIIRSDINEOFDaily @ CoastWatch](https://coastwatch.noaa.gov/erddap/griddap/noaacwNPPN20VIIRSDINEOFDaily) | 72-h last-good cache, honestly labelled |
| Ocean currents | Blended NRT geostrophic (altimetry), 0.25°, daily | [noaacwBLENDEDNRTcurrentsDaily @ CoastWatch](https://coastwatch.noaa.gov/erddap/griddap/noaacwBLENDEDNRTcurrentsDaily) | Open-Meteo derived grid |
| Significant wave height | WAVEWATCH III global, 0.5°, hourly +7 d | [ww3_global @ PacIOOS](https://pae-paha.pacioos.hawaii.edu/erddap/griddap/ww3_global) | Open-Meteo marine |
| Wind (u/v 10 m) | NCEP GFS, 0.5°, 3-hourly +7 d | [ncep_global @ PacIOOS](https://pae-paha.pacioos.hawaii.edu/erddap/griddap/ncep_global) | Open-Meteo |
| SST anomaly | NOAA Coral Reef Watch v3.1, 5 km, daily | [dhw_5km (CRW_SSTANOMALY) @ PacIOOS](https://pae-paha.pacioos.hawaii.edu/erddap/griddap/dhw_5km) | — |
| In-situ profiles | INCOIS Indian Argo floats | [Indian_ARGO_Floats @ INCOIS](https://erddap.incois.gov.in/erddap/tabledap/Indian_ARGO_Floats) | — |
| Point forecasts (fallback) | Open-Meteo marine & weather | [open-meteo.com](https://open-meteo.com/) | — |
| Cyclone alerts | GDACS (EC JRC), keyless RSS | [gdacs.org](https://www.gdacs.org/) | INCOIS GEMINI high-wave/swell/storm-surge |
| Maritime boundaries | India–Sri Lanka IMBL treaty line, VLIZ maritime regions | [marineregions.org](https://www.marineregions.org/) | committed GeoJSON in `data/` |
| Voice (ASR/NMT/TTS) | Bhashini Dhruva (MeitY NLTM) | [bhashini.gov.in](https://bhashini.gov.in) | local faster-whisper + edge-tts, Web Speech |

Swapping or adding a source is a **`datasets.json` entry, not a code change** —
variables map to fallback *chains* (priority-ordered), the hub tries servers by
configured priority, and staleness is flagged, never hidden.

## Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.11+, FastAPI, Pydantic v2 | typed API contracts mirrored 1:1 in the frontend `types.ts` |
| Ocean science | erddapy, xarray, netCDF4, numpy, scipy, pandas | ERDDAP subsetting + gridded windows without downloading full datasets |
| Geospatial | geopandas, shapely, pyproj, geojson-pydantic | IMBL/MPA geofencing, distances, bearings — deterministic |
| Routing | A* (custom, `app/engines/routing`) | safe/shortest/fuel/risk modes with hard constraint pruning |
| Persistence | SQLite + SQLAlchemy (PostGIS optional via Docker) | query log; spatial DB not required for the demo |
| Voice | Bhashini Dhruva; fallback faster-whisper + edge-tts; client Web Speech | works with zero keys, better with keys |
| Frontend | React 19, TypeScript 5, Vite 6, MapLibre GL 6 | no map API key, free basemaps |
| i18n | hand-rolled dictionary, 8 languages (en, ta, te, ml, hi, bn, or, gu) | fishermen-facing labels translated, template explainer native |
| Infra | Render (backend) + Vercel (frontend) + GitHub Actions keep-alive | free tier, zero-cost demo |
| Tests | pytest, 38 tests incl. 8 mandated critical tests | run fully offline |

## Problem-statement coverage

Audited against SIH26176 in [docs/REQUIREMENTS_COVERAGE.md](docs/REQUIREMENTS_COVERAGE.md)
(every ✅ names the code path that proves it). Summary:

- ✅ PFZ-style zone ranking, safe-to-venture verdict, chlorophyll + SST favourability,
  safe route optimization, hazardous/geofenced-zone avoidance
- ✅ NL intent understanding, autonomous dataset discovery + failover, spatial/temporal
  reasoning across sources, explainable evidence + maps, multi-agent modularity,
  geofencing (IMBL / MPA / restricted), reliable provenance-backed recommendations
- 🟡 honest gaps: **tides** not ingested, **lightning** has no feed, **multi-turn
  conversation** and **language auto-detect** pending (see *Future scope*)

## Feasibility & viability

**Technical feasibility — proven, running.** The stack is deployed and serving real
advisories on free tiers (Render 512 MB + Vercel). Every data source is keyless/open
(or optionally Bhashini/INCOIS keys), so there is no procurement blocker. The provider
layer degrades gracefully: host-down circuit breakers, 429-aware retries, a short-TTL
subset cache, per-variable fallback chains, and a 72-h last-good cache — **persisted to
disk, so it survives free-tier restarts** — that serves the last real observations
honestly labelled. A five-minute keep-alive pinger targets `/api/system/warm`, which
re-seeds every data cache after a restart before the next fisherman arrives. The
38-test suite runs fully offline.

**Economic viability — zero recurring cost at demo scale.** No paid APIs, no map keys,
free hosting. Scaling cost is bandwidth/compute on commodity hosting; the heavy assets
(satellite grids) stay on the providers' own ERDDAPs — ORCA fetches only small bounding
boxes, so per-request cost stays in kilobytes.

**Operational viability — built for the field.** Voice-first interaction in 8 Indian
languages, verdict plates designed for low-literacy users (GO / CAREFUL / STOP with
icons), read-aloud output, mobile-responsive layout. For production deployment the
config-only hooks to INCOIS (GEMINI alerts, ERDDAP) and IMD (warnings) mean an
authoritative Indian backend can replace international primaries **without code
changes** — this is the intended path to a government-blessed deployment.

**Viability risks, stated:** ERDDAP public hosts throttle cloud egress IPs
(mitigated by retries/caches, eliminated by partnering with INCOIS for Indian hosting);
recommendation weights are heuristic until validated against catch data (labelled as
such in the UI).

## Impact & benefits

- **Safety of life at sea** — IMBL and protected-area hard geofences, rough-sea and
  strong-wind cautions per zone, official cyclone / high-wave / swell alerts, routes
  that never cross hard boundaries, max-wave-on-path in the trip card.
- **Livelihood** — SST + chlorophyll front detection ranks zones where fish actually
  aggregate, cutting blind fuel-burning search time; distance/bearing/trip cost are
  shown before departure.
- **Inclusion** — speaks the user's language (8 languages), listens and talks back,
  avoids literacy barriers, works on a phone.
- **Trust** — every number carries source, dataset, retrieval and valid time, unit and
  quality flag; missing data is announced (`INSUFFICIENT_DATA`), stale data is badged
  CACHED with its true date; the LLM cannot override any computation.
- **Institutional** — complements INCOIS PFZ bulletins with a conversational, map-first
  front end; evidence records (claim/basis/computation) are auditable end-to-end.

## Evaluation rubric self-check

Honest mapping of the SIH26176 rubric to what is in this repo — written to be
checkable, not promotional.

| Rubric criterion | Verdict | Where to look |
| --- | --- | --- |
| Novelty & uniqueness | ✅ | The inverted architecture: [the critical design rule](#the-critical-design-rule) — the LLM explains, deterministic engines compute; geofences the LLM cannot override; honest `MISSING` / `INSUFFICIENT_DATA` instead of a confident guess |
| Technical approach — feasibility of technology & methodology | ✅ | Every box in the [workflow](#workflow) is committed code: A* routing, front detection, shapely geofencing, provider failover; 38 offline tests incl. the 8 mandated critical ones; free tiers, no paid API |
| Functionality & prototype — quality, usability, completeness | ✅ | Deployed and live (links at top): 12 ranked zones, safe routing, official warnings, voice in/out, 8 languages, [comparison charts](#core-features), evidence records, phone-ready layout. 🟡 Honest gaps: multi-turn, tides, lightning |
| Feasibility & viability — practical implementation & risk handling | ✅ | [Feasibility & viability](#feasibility--viability): failover chains, circuit breakers, 429-aware retries, disk-persisted 72-h last-good cache, warm pinger; risks stated openly with mitigations |
| Stakeholder inputs & user/domain-expert consideration | 🟡 | Grounded in official Indian domain sources — INCOIS PFZ methodology + GEMINI alerts, Bhashini/NLTM for the 8 languages, FAO/ILO/IMO small-vessel safety recommendations — and every UX choice maps to a stated fisherman constraint (low literacy → verdict plates + read-aloud; phones → mobile-first layout). Systematic fishing-community interviews and catch-data validation are the first post-prototype milestone ([Future scope](#future-scope) 7) |
| Impact & benefits — social, economic, environmental | ✅ | [Impact & benefits](#impact--benefits): safety of life at sea, less blind fuel burn, protected-area compliance, auditable trust |
| Scalability & scale of impact | ✅ | Stateless API; heavy satellite grids stay on the providers' ERDDAPs (ORCA fetches kilobyte bboxes); a new source is a `datasets.json` entry; PostGIS path in docker compose; zero recurring cost at demo scale |
| Presentation, UX & potential for future work | ✅ | Map-first liquid-glass UI, GO / CAREFUL / STOP verdict plates, charts, read-aloud; 8-item [future scope](#future-scope); full docs set ([Architecture](docs/ARCHITECTURE.md), [Coverage](docs/REQUIREMENTS_COVERAGE.md), [Safety](docs/SAFETY.md)) |

## Future scope

1. **Multi-turn conversation** — session-scoped state to diff follow-ups against the
   last `ParsedQuery` (“what about tomorrow?”, “further out”, “zone 3”).
2. **Tides** — ingest a tidal-harmonic product for the pilot coast as a provider entry;
   tide state on the trip card.
3. **Lightning nowcast** — wire the existing IMD config hook to a thunderstorm nowcast
   feed (`OFFICIAL_LIGHTNING` warning code; the template machinery is already generic).
4. **Language auto-detection** — script-range detection on the query path (Bhashini
   language-ID when configured) instead of selector-picked language.
5. **Indian primaries** — swap `datasets.json` entries to INCOIS/MosDAC gridded NRT
   products as they become available on reachable endpoints.
6. **Offline/low-connectivity** — PWA with the last advisory cached on-device; SMS/IVR
   channel for feature-phone users.
7. **Model validation** — partner with fishing communities to log catch outcomes and
   calibrate the productivity weights from data instead of heuristics.
8. **Fleet features** — shareable zone links, community-reported hazards, group advisories.

## Research & references

- Beckers, J.-M. & Rixen, M. (2003). *EOF calculations and data filling from
  incomplete oceanographic datasets.* J. Atmos. Oceanic Technol., 20(12) — the DINEOF
  method behind the gap-filled chlorophyll product.
- Alvera-Azcárate, A. et al. (2005). *Reconstruction of incomplete oceanographic data
  using a neural-network-based technique (DINEOF).* JGR Oceans.
- O'Reilly, J.E. et al. (1998, 2012). *Ocean color chlorophyll algorithms (OC3/OC4).*
  NASA Ocean Biology DAAC.
- JPL GHRSST MUR L4 SST analysis — NASA/JPL Physical Oceanography DAAC
  (<https://podaac.jpl.nasa.gov/dataset/MUR-JPL-L4-GLOB-v4.1>).
- NOAA Coral Reef Watch v3.1 daily 5 km products — CoralTemp SST
  (<https://coralreefwatch.noaa.gov/product/5km/index.php>).
- NOAA CoastWatch blended near-real-time geostrophic currents —
  <https://coastwatch.noaa.gov>.
- NOAA/NCEP WAVEWATCH III global wave model — <https://polar.ncep.noaa.gov/waves/>.
- Hart, P.E., Nilsson, N.J. & Raphael, B. (1968). *A formal basis for the heuristic
  determination of minimum cost paths.* IEEE Trans. SSC — A*.
- Simons, R. — ERDDAP data server, NOAA NMFS SWFSC (<https://coastwatch.pfeg.noaa.gov/erddap>).
- INCOIS Potential Fishing Zone advisory methodology and GEMINI high-wave/swell/storm-surge
  alerts — Indian National Centre for Ocean Information Services (<https://incois.gov.in>).
- FAO/ILO/IMO (2013, rev.). *Safety recommendations for decked fishing vessels of less
  than 12 m* — safety-constraint framing.
- GDACS — Global Disaster Alert and Coordination System, EC JRC / UN OCHA
  (<https://www.gdacs.org>).
- Bhashini / National Language Translation Mission, MeitY (<https://bhashini.gov.in>).
- Flanders Marine Institute (VLIZ) maritime boundaries —
  <https://www.marineregions.org>.

## Quick start (local, no Docker)

```bash
# backend
cd backend
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
copy ..\.env.example ..\.env                        # then edit as needed
uvicorn app.main:app --reload --port 8000

# frontend (new terminal)
cd frontend
npm install
npm run dev            # http://localhost:5173
```

Open **http://localhost:8000/docs** for the API reference.

> The system boots in **DEMO mode** by default (cached data, clearly labelled).
> Set `ORCA_DATA_MODE=live` in `.env` (gitignored) to fetch from the configured
> live providers. Live queries take ~20–30 s (several datasets are fetched and
> merged per request; a repeat query within 30 min is served from the subset
> cache). Public ERDDAP hosts occasionally throttle or drop cloud egress IPs —
> the hub retries (429-aware), falls through the provider chain, and serves the
> last successful field for up to 72 h, **honestly labelled** — otherwise it
> reports MISSING rather than inventing a value. Reference boundary layers
> (India–Sri Lanka IMBL treaty lines, protected areas, land masks) load in
> **both** modes.
>
> **Why NOAA/PacIOOS serve the forecast fields and not INCOIS/MOSDAC**: the
> provider layer is deliberately source-agnostic — INCOIS *is* in the chain
> (Argo profiles via INCOIS ERDDAP, and official High-Wave/Swell/Storm-Surge
> alerts via the GEMINI API when `ORCA_INCOIS_API_KEY` is set), but INCOIS's
> gridded ERDDAP holdings end 2011, so live forecast fields come from whichever
> provider publishes current numeric grids (NOAA/PacIOOS/Open-Meteo). Swapping
> in an Indian provider is a `datasets.json` entry, not a code change. Cyclone /
> high-wave warnings ingest from GDACS (keyless) + INCOIS GEMINI + a config-only
> IMD hook — see `app/providers/official_warnings.py`.

### Demo data pack

The Rameswaram demo pack (real cached ERDDAP subsets + Open-Meteo + VLIZ IMBL
geometry) is committed under `data/demo/rams/` with full provenance in
`manifest.json` and attribution in `ATTRIBUTION.md`. To rebuild or refresh it
from live sources:

```bash
cd backend
.venv/Scripts/python -X utf8 scripts/fetch_demo_data.py
```

### Tests

```bash
cd backend
.venv/Scripts/python -m pytest tests/ -v
```

38 tests, including the **eight mandated critical tests**
([backend/tests/test_critical.py](backend/tests/test_critical.py)):

1. a restricted/protected polygon is never traversed (A* detours or gives up)
2. a route never crosses the IMBL hard boundary (unreachable ⇒ blocked, never invented)
3. missing data is never fabricated (empty pack ⇒ `INSUFFICIENT_DATA`, no recommendation)
4. stale/cached data is always flagged `STALE` with a DEMO/CACHED note
5. user constraints survive the pipeline (distance, place, IST time window, objectives)
6. every evidence claim maps to a real measurement with provenance
7. demo mode is visibly labeled (banner + `DEMO_MODE` warning + provenance envelope)
8. every available measurement carries an explicit unit

Plus the resilience suite ([tests/test_last_good_cache.py](backend/tests/test_last_good_cache.py)):
an outage serves the last real field honestly labelled, never past its
72-hour representative horizon, and — via the disk cache — even across a
process restart.

Tests run fully offline: geocoding is monkeypatched off and Bhashini/Dhruva
HTTP is stubbed.

### Voice & translation

Voice input (🎙) and read-aloud (🔊) work **without any API key**: when Bhashini
is not configured the UI falls back to the browser's built-in Web Speech API
(Chrome/Edge recommended), with a server-side faster-whisper + edge-tts option
available. Speech recognition runs on-device in the fallback path, and the UI
honestly labels the voice it uses — never as Bhashini when it is not.

To enable Bhashini (better Indian-language ASR / translation / TTS):

1. Register at <https://bhashini.gov.in> and obtain Dhruva API credentials.
2. Copy `.env.example` → `.env`, set `ORCA_BHASHINI_ENABLED=true`,
   `ORCA_BHASHINI_API_KEY=…` and the `ORCA_BHASHINI_*_SERVICE_ID` values.
3. Restart the backend. `GET /api/voice/status` then reports `configured: true`
   and the UI automatically prefers Bhashini over the fallback voice.

`GET /api/voice/status` always reports what is actually available — the UI never
pretends a voice service is configured when it is not.

### AI reasoning layer (optional — free, keyless by default)

ORCA works with **zero AI keys** — query parsing and the advisory explanation
are deterministic templates. Setting `ORCA_LLM_*` adds a language model on top
for exactly two jobs:

1. **Reading the question** — extracting place, distance, day, part-of-day and
   objective into the structured `ParsedQuery`. The regex parser remains the
   fallback, and the place name is always resolved against the gazetteer —
   the model never produces coordinates.
2. **Writing the explanation** — turning the engines' computed facts into a
   few plain sentences. The prompt passes only the computed JSON and forbids
   invention; on any error or rate limit ORCA silently falls back to the
   template text. **No number ever comes from the model.**

The live demo uses Google's free tier — key from
<https://aistudio.google.com/apikey>:

```bash
ORCA_LLM_PROVIDER=openai-compatible
ORCA_LLM_MODEL=gemini-3.5-flash-lite   # 2.5-lite is retired for new keys
ORCA_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
ORCA_LLM_API_KEY=...                   # .env / host env only — never committed
```

Any OpenAI-compatible endpoint works identically (OpenRouter `:free` models, a
local Ollama at `http://localhost:11434/v1`, vLLM) — see `.env.example`.
`GET /api/system/status` reports `llm_reasoning_enabled`, so you can always
verify which path is live.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

Brings up `postgis` (spatial database), `backend` (FastAPI), `frontend` (Vite build
served by nginx). PostGIS is **optional** for development — the geospatial engine
works on file-based GeoJSON/GeoPackage layers without a database.

## Documentation

| Doc | Contents |
| --- | --- |
| [docs/REQUIREMENTS_COVERAGE.md](docs/REQUIREMENTS_COVERAGE.md) | full audit against the SIH26176 statement, with code-path evidence |
| [docs/OPEN_SOURCE_RESEARCH.md](docs/OPEN_SOURCE_RESEARCH.md) | inspected OSS projects, verdicts (direct dep / adapt / reference / reject), licenses |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | agent graph, data flow, LLM-vs-tools boundary, scoring model |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | phase plan mapped to concrete deliverables |
| [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) | third-party license inventory and compatibility notes |
| [docs/SAFETY.md](docs/SAFETY.md) | non-negotiable safety & trust requirements |

## Safety posture (non-negotiable)

- Never fabricate weather, waves, currents, boundaries, protected areas, or warnings.
- Hard constraints (IMBL / maritime boundary, protected polygons, land) can **never**
  be overridden by an LLM or a soft cost.
- Every recommendation ships with timestamp, sources, valid time, confidence and warnings.
- Demo/cached data is always visibly labelled **“DEMO / CACHED DATA”**.
- Reference GIS boundaries are distinguished from legally authoritative ones.

*Prototype decision weights are heuristic and clearly labelled as such — not a
scientifically validated fish-stock or safety model.*
