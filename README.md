# ORCA — Marine Ecosystem Reasoning with Collaborative Agents

**SIH26176** — an agentic marine decision-support prototype for Indian fishermen.

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
> Switch to `ORCA_DATA_MODE=live` to fetch from configured live providers.

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

32 tests, including the **eight mandated critical tests**
([backend/tests/test_critical.py](backend/tests/test_critical.py)):

1. a restricted/protected polygon is never traversed (A* detours or gives up)
2. a route never crosses the IMBL hard boundary (unreachable ⇒ blocked, never invented)
3. missing data is never fabricated (empty pack ⇒ `INSUFFICIENT_DATA`, no recommendation)
4. stale/cached data is always flagged `STALE` with a DEMO/CACHED note
5. user constraints survive the pipeline (distance, place, IST time window, objectives)
6. every evidence claim maps to a real measurement with provenance
7. demo mode is visibly labeled (banner + `DEMO_MODE` warning + provenance envelope)
8. every available measurement carries an explicit unit

Tests run fully offline: geocoding is monkeypatched off and Bhashini/Dhruva
HTTP is stubbed.

### Voice & translation

Voice input (🎙) and read-aloud (🔊) work **without any API key**: when Bhashini
is not configured the UI falls back to the browser's built-in Web Speech API
(Chrome/Edge recommended). Speech recognition runs on-device, read-aloud uses
the browser's installed voices, and the UI honestly labels it as the browser's
voice — never as Bhashini.

To enable Bhashini (better Indian-language ASR / translation / TTS):

1. Register at <https://bhashini.gov.in> and obtain Dhruva API credentials.
2. Copy `.env.example` → `.env`, set `ORCA_BHASHINI_ENABLED=true`,
   `ORCA_BHASHINI_API_KEY=…` and the `ORCA_BHASHINI_*_SERVICE_ID` values.
3. Restart the backend. `GET /api/voice/status` then reports `configured: true`
   and the UI automatically prefers Bhashini over the browser voice.

`GET /api/voice/status` always reports what is actually available — the UI never
pretends a voice service is configured when it is not.

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
