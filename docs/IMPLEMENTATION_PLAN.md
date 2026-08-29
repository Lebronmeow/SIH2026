# ORCA Implementation Plan — 10 Phases

Status: ✅ done · 🔶 partial · ⬜ pending. Verified = smoke-tested with the
command/output noted.

| # | Phase | Status | What landed / what remains |
|---|-------|--------|-----------------------------|
| 0 | **Repo research (17 projects) before coding** | ✅ | OPEN_SOURCE_RESEARCH.md; every dataset ID live-verified 2026-08-29; licenses checked before any reuse (pgRouting → D, SIMROUTE → concepts only) |
| 1 | **Skeleton**: FastAPI + React + config + Docker | ✅ | create_app factory, CORS, `/api/health`, `/api/system/status` (demo-banner source of truth), settings (`ORCA_` prefix, .env, no secrets), docker-compose + 2 Dockerfiles (Docker not required to develop — file/SQLite fallback path) |
| 2 | **Data providers + analytics** | ✅ | OceanDataHub (demo/live failover), ErddapProvider (erddapy; extra-dim pinning for `depth`/`altitude`; verify=False only for INCOIS), OpenMeteoProvider, DemoOceanProvider (STALE labels), canonical dims, `OceanField`+Provenance, front detection engine (gradient/percentile/label + Strategy plug point). Verified: synthetic 0.468 °C/km front → strength 1.0. 🔶 live ERDDAP pass-through happens in the demo-pack fetch (Phase 9); AIS proxy is Phase 8+ |
| 3 | **Geospatial safety engine** | ✅ | BoundaryLayer loading with authority/hard-constraint metadata; `check_geofence` (MPA/restricted/IMBL band/land), `distance_to_imbl`, `edge_blocked` (segment vs prepared geometry), `check_route_safety` (densified sampling); per-UTM-zone transformer + projected-geometry caches (10.9 s → 0.19–1.5 s). Verified: caution at 8.79 km, violation at 5 km, MPA-inside rejection, route-crossing rejection |
| 4 | **Routing engine** | ✅ | heapq A* + 80-neighbor fan, 4 modes (shortest/safe/fuel/risk), Bowditch speed loss, time-indexed hazards, **edge-level hard-constraint enforcement** (the ±4-cell hop-over fix — shortest route went from illegal 75 km crossing to legal 138 km detour). Verified: all modes legal, east-side detour 47.5 km |
| 5 | **Multi-agent orchestration** | ✅ | MAF 1.16.0 graph (`orchestrator.py`) = same topology as direct `workflows/advisory.py`; deterministic query parser + LLM variant; template explainer + LLM variant; Verification executor; ZoneEvaluationService (fetch-once, sample-per-candidate, rank, route, evidence, INSUFFICIENT_DATA); API: `/api/query`, `/api/ocean/*`, `/api/safety/check`, `/api/route/optimize`, `/api/recommendations/{id}`. Verified end-to-end: synthetic eastward front → east zones rank 1–3, route 20 km/1.66 h, evidence 6 items; honest INSUFFICIENT_DATA with empty pack; all endpoints 200 |
| 6 | **Bhashini speech services** | ✅ | `services/bhashini.py` — `BhashiniClient` (Dhruva pipeline v2 POST, `Authorization` header, `pipelineTasks`+`inputData`), `TranslationService`/`SpeechService` (ASR)/`TextToSpeechService`; serviceIds from config (`ORCA_BHASHINI_*_SERVICE_ID`), disabled without key (`ServiceDisabled` → HTTP 503 structured body). Routes: `/api/voice/status` (UI capability map), `/api/voice/transcribe`, `/api/translate`, `/api/voice/speak`. `/api/query` accepts `language`: translates query→en + explanation→user language when enabled; otherwise honest `ENGLISH_ONLY` info warning (never a fabricated translation). Verified: disabled fallbacks 503, same-language echo, payload shape via stubbed client (caught dict-vs-list bug), bad base64 rejected |
| 7 | **Frontend dashboard** | ✅ | Vite+React dark 3-panel grid: QueryPanel (examples, language picker, mic when voice enabled, trace + sources), MapPanel (MapLibre + deck.gl via MapboxOverlay — land/MPA/IMBL/route/zone layers, click-to-select), RecommendationPanel (WHY-THIS-ZONE explanation, IST valid time, read-aloud TTS, per-zone scores + measurements with provenance/MISSING/CACHED badges, route stats, evidence, severity-coded warnings, raw response). Demo banner from `/api/system/status` + every response. Verified in browser: canonical query renders recommendation, route 20 km/1.7 h, 5 measurements, 6 evidence, zero console errors |
| 8 | **Verifier + evidence hardening** | ✅ | `_verify` integrity gates: evidence→measurement cross-check (variable/value ±1e-6/unit/provenance), unit audit, valid_time required, excluded/geofence/route-blocked/DEMO_MODE/INSUFFICIENT checks, ORIGIN_INLAND coastal check. AIS ingestion (`services/ais.py`: FileAisProvider over pack `ais.json` + pyais NMEA `decode_nmea`), 5 km traffic radius evidence + map features, synthetic traffic honestly labeled. JUNO front strategy documented as upgrade path (`build_front_strategy("juno")` raises until validated). Verified: `verification: ok` on demo response, AIS evidence claim, pyais decodes real NMEA |
| 9 | **Rameswaram demo pack** | ✅ | Pack built and committed: 9/9 variables from REAL ERDDAP subsets (jplMURSST41, nesdisVHNSQchlaDaily, ww3_global, noaacwBLENDEDNRTcurrentsDaily, ncep_global) + Open-Meteo weather caches + VLIZ IMBL (`line_id=1306`+`1311`, REFERENCE authority, hard constraint) + manifest.json with retrieval dates/licenses. Synthetic fallbacks (MPA, land mask) clearly labeled. Verified end-to-end in demo mode: zone-17 recommended (real SST 30.32 °C, waves 1.38 m, currents 0.27 m/s), IMBL distance 42.7 km from real geometry, 13/24 candidates excluded by hard constraints, DEMO banner + /api/system/status banner live. Fixes landed: erddapy lru_cache/UA transport patch, descending-latitude demo slices, `from_settings()` boundary loading (shared dir + every pack), lowercase BoundaryKind, dtype-safe demo time selection |
| 10 | **Tests + docs** | ✅ | 32 pytest tests, all green (`pytest tests/ -v` from `backend/`): **the 8 mandated critical tests** in `tests/test_critical.py` (1 MPA never traversed — detour found; 2 IMBL line fully spans grid → route blocked, never crossing; 3 empty pack → INSUFFICIENT_DATA, no recommendation, all measurements MISSING/None; 4 demo values STALE + DEMO/CACHED notes; 5 user constraints retained (20 km / Rameswaram / IST morning window / both objectives); 6 `_verify` → zero problems, evidence variables ⊆ measurements; 7 demo_banner_required + DEMO_MODE warning + provenance envelope; 8 every available measurement has a unit) plus `test_parsing.py` (8), `test_bhashini.py` (8, stubbed Dhruva payload shape), `test_api.py` (8, TestClient). README run/test instructions, docs/SAFETY.md |

## Verification commands

```bash
cd backend
.venv/Scripts/python -X utf8 scripts/smoke_phase5.py   # full pipeline over synthetic fields
.venv/Scripts/python -m pytest tests/ -v               # 32 tests incl. the 8 critical ones
```

## Definition of done (prototype)

1. The canonical query returns an evidence-backed recommendation with map layers,
   WHY panel, route, warnings, provenance and trace — in demo mode with the banner.
2. With the demo pack emptied, the same query returns the honest
   INSUFFICIENT_DATA response (never a fabricated zone).
3. The 8 critical tests pass.
4. No GPL component in the default path; licenses documented.
