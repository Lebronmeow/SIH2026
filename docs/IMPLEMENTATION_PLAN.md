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
| 6 | **Bhashini speech services** | ⬜ | SpeechService / TranslationService / TextToSpeechService (Dhruva pipeline POST, `Authorization` header, serviceIds from config), English-only graceful fallback default |
| 7 | **Frontend dashboard** | 🔶 | Vite+React skeleton, dark 3-panel CSS grid, deps pinned (MapLibre 6.6, deck.gl 9.3, OpenFreeMap liberty style). ⬜ map layers (zones/IMBL/MPA/route/front gradient), query panel, WHY-THIS-ZONE panel, demo banner wiring, evidence list |
| 8 | **Verifier + evidence hardening** | 🔶 | Basic verification executor live. ⬜ evidence cross-checks (each claim → measurement provenance), unit audit, coastal-check for resolved places, AIS ingestion, JUNO Strategy note |
| 9 | **Rameswaram demo pack** | ✅ | Pack built and committed: 9/9 variables from REAL ERDDAP subsets (jplMURSST41, nesdisVHNSQchlaDaily, ww3_global, noaacwBLENDEDNRTcurrentsDaily, ncep_global) + Open-Meteo weather caches + VLIZ IMBL (`line_id=1306`+`1311`, REFERENCE authority, hard constraint) + manifest.json with retrieval dates/licenses. Synthetic fallbacks (MPA, land mask) clearly labeled. Verified end-to-end in demo mode: zone-17 recommended (real SST 30.32 °C, waves 1.38 m, currents 0.27 m/s), IMBL distance 42.7 km from real geometry, 13/24 candidates excluded by hard constraints, DEMO banner + /api/system/status banner live. Fixes landed: erddapy lru_cache/UA transport patch, descending-latitude demo slices, `from_settings()` boundary loading (shared dir + every pack), lowercase BoundaryKind, dtype-safe demo time selection |
| 10 | **Tests + docs** | ⬜ | pytest suites incl. the 8 mandated critical tests (restricted polygon never traversed; route never crosses hard boundary; missing data never fabricated; stale flagged; user constraints retained; evidence maps to data; demo labeled; units explicit), README run instructions |

## Verification commands

```bash
cd backend
.venv/Scripts/python -X utf8 scripts/smoke_phase5.py   # full pipeline over synthetic fields
```

## Definition of done (prototype)

1. The canonical query returns an evidence-backed recommendation with map layers,
   WHY panel, route, warnings, provenance and trace — in demo mode with the banner.
2. With the demo pack emptied, the same query returns the honest
   INSUFFICIENT_DATA response (never a fabricated zone).
3. The 8 critical tests pass.
4. No GPL component in the default path; licenses documented.
