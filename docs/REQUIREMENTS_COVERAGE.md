# ORCA — SIH26176 requirements coverage audit

Audited against the SIH26176 problem statement on **2026-08-30**, commit `3bb2c4e`.
Statuses: **✅ satisfied** · **🟡 partial** · **❌ gap**. Every satisfied row names the
code path that proves it — the audit is meant to survive scrutiny, not to sell.

## Typical queries from the problem statement

| # | Query | Status | Evidence |
|---|-------|--------|----------|
| 1 | "Where is the nearest Potential Fishing Zone (PFZ) today?" | ✅ | Ring candidates ranked by overall score (SST + chlorophyll fronts, hazards) in `zone_evaluator.py`; distances/bearings from the departure point shown per zone; ranked list + map. |
| 2 | "Is it safe to venture into the sea tomorrow morning?" | ✅ | Verdict banner derives from backend warnings only (`verdictOf`); forecast fields carry `valid_time`; time-window parsing ("tomorrow morning") in the query parser. |
| 3 | "Tide, weather, and sea conditions near my location" | 🟡 | Weather + sea state fully covered (SST, waves, wind, currents with provenance). **Tides are not ingested** — see gaps. |
| 4 | "Are there any lightning or cyclone alerts in my area?" | 🟡 | Cyclones ✅ (GDACS keyless TC feed + INCOIS GEMINI high-wave/swell/storm-surge + config-only IMD hook, `official_warnings.py`). **Lightning has no feed** — see gaps. |
| 5 | "Which regions show high chlorophyll concentration and favourable SST?" | ✅ | Deterministic front detection on both variables (`front_detection.py`); chlorophyll gradients feed per-zone scores; chlorophyll restored via MODIS NRT with cloud-gap fallback (2026-08-30). |
| 6 | "What is the safest route … considering weather and sea-state?" | ✅ | A\* routing with wave/wind penalty + hard geofence constraints (`routing/engine.py`); zone-click routes via `POST /api/route/optimize` (2026-08-30); land origins snapped to water with an honest note. |
| 7 | "Why has fish productivity declined in a particular coastal region?" | 🟡 | The evidence/explanation machinery exists (claim + basis + computation per claim), but the workflow is advisory-shaped, not a regional trend diagnostic — a "why" question about a region needs time-series anomaly analysis that is not built. |
| 8 | "Which fishing zones should be avoided due to hazardous conditions or geofencing?" | ✅ | Zones carry `excluded` + `exclusion_reason`; MPA/restricted polygons, IMBL line and coastal band are hard constraints in candidate generation; boundaries render as authority-labeled layers. |

## Platform capabilities required by the statement

| Capability | Status | Evidence |
|------------|--------|----------|
| Natural-language intent understanding | ✅ | `agents/query_parser.py` → structured `ParsedQuery` (origin, distance, window, objective); LLM used for reasoning/orchestration only — all numbers computed deterministically. |
| Auto language identification, reply in same language, Indian languages | 🟡 | 8 Indian languages end-to-end (UI, explanations, voice); non-English queries translated for parsing (Bhashini when configured); **the user currently picks the language rather than the system auto-detecting it** — a small addition on the query path. |
| Contextual multi-turn conversation | ❌ | The query API is stateless (`/api/query`); contextual refinement today = picking zones on the map/list (its details + route swap). There is no conversational memory or follow-up parsing ("what about tomorrow?"). |
| Autonomous dataset discovery, retrieval, integration | ✅ | Provider registry (`registry.py`) + dataset catalog (`datasets.json`) + failover hub with health probing and host-down TTL (`hub.py`); swapping a source is a catalog edit, not code. |
| Spatial / temporal / contextual reasoning across sources | ✅ | `zone_evaluator.py` correlates SST fronts, chlorophyll fronts, wave/wind hazards, currents, geofence distance and route cost into one score with per-zone evidence. |
| Explainable, evidence-based recommendations + maps | ✅ | Every response carries evidence (claim/basis/computation), provenance (source, dataset, retrieved/valid time), workflow trace, map layers; panel renders, never computes. |
| Proactive safety alerts (weather, high waves, lightning, cyclones) | 🟡 | ROUGH_SEA / STRONG_WIND / MANY_MISSING_PRODUCTS + official cyclone & INCOIS high-wave/swell/storm-surge alerts. **Lightning not covered.** |
| Geofencing notifications (IMBL, restricted waters, MPAs, sensitive zones) | ✅ | Geofence engine checks every candidate, route vertex and route outcome; IMBL proximity carries a caution penalty and a distance readout; MPAs/restricted polygons hard-block. |
| Route optimization, safe navigation, operational planning | ✅ | Safe/shortest/fuel/risk-optimal modes; trip card shows distance, duration, max wave on path, blocked flag, shore-launch notes. |
| Reliable recommendations with supporting evidence and reasoning | ✅ | Insufficient data ⇒ explicit `INSUFFICIENT_DATA` response naming missing variables; stale data ⇒ CACHED badge + true observation date; no fabricated values anywhere in the chain. |
| Modular multi-agent architecture with autonomous collaboration | ✅ | Agents (parser, explainer, orchestrator) coordinate specialized deterministic engines (geospatial, ocean/fronts, routing/A\*, scoring) over a provider layer; workflow trace shows each step. |

## Gaps, honestly stated (with the smallest honest fix)

1. **Multi-turn conversation (❌)** — add session-scoped conversation state: keep the last
   `ParsedQuery` + response id, parse follow-ups against it ("tomorrow", "further out",
   "zone 3"). The parser already returns a structured object to diff against.
2. **Tides (🟡→✅)** — ingest a tidal harmonic product for the pilot region (e.g. INCOIS
   sea-level or a FES/TPXO endpoint) as a new provider entry; surface tide state as a
   measurement + a shallow-water note on the trip card.
3. **Lightning (🟡→✅)** — wire the existing IMD config hook to a lightning/thunderstorm
   nowcast feed (IMD "nowcast" bulletins or WWLLN via a partner), emitting an
   `OFFICIAL_LIGHTNING` warning code; the UI template machinery is already generic.
4. **Language auto-detect (🟡→✅)** — detect script/keywords on the query endpoint
   (Devanagari/Bengali/Tamil/etc. ranges are unambiguous) and override the selector;
   Bhashini's language-ID API is the configured upgrade.

*Everything else in the statement is implemented and running on the deployed stack.*
