/**
 * Right panel: WHY THIS ZONE explanation, scores, measurements with
 * provenance, evidence list, warnings and route info. Every number shown
 * traces back to a backend measurement — the panel renders, never computes.
 */

import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import { api, stopSpeak } from "../api";
import { browserSpeak, browserStop } from "../speech";
import * as i18n from "../i18n";
import {
  AlertTriangleIcon, BanIcon, CheckCircleIcon, ClockIcon, CompassIcon,
  CurrentIcon, LeafIcon, PinIcon, StopSoundIcon, SpeakerIcon, TempIcon,
  WaveIcon, WindIcon,
} from "./icons";
import type { AdvisoryResponse, Measurement, RouteOut, VoiceStatus, Warning, ZoneEvaluation } from "../types";

type L = Record<i18n.Key, string>;
type IconCmp = ComponentType<{ size?: number }>;

const SEVERITY_CLASS: Record<string, string> = {
  info: "sev-info",
  caution: "sev-caution",
  warning: "sev-warning",
  critical: "sev-critical",
};

const SEV_KEY: Record<string, i18n.Key> = {
  info: "sev_info",
  caution: "sev_caution",
  warning: "sev_warning",
  critical: "sev_critical",
};

function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

function ist(t: string | null | undefined, lang: string): string {
  if (!t) return "—";
  try {
    return new Date(t).toLocaleString(i18n.localeOf(lang), { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" });
  } catch {
    return t;
  }
}

/* ---- plain-language presentation helpers --------------------------------
   These only re-word numbers the backend already reported. Wording bands are
   WMO Douglas-style sea states and Beaufort-style wind bands, chosen so that
   "rough sea" (>= 2.5 m) and "very strong wind" (>= 30 km/h) coincide exactly
   with the backend's ROUGH_SEA / STRONG_WIND caution thresholds. No science
   is computed here. */

function waveWord(m: number | null | undefined, L: L): string {
  if (m == null) return "";
  if (m < 0.5) return L.w_calm;
  if (m < 1.25) return L.w_slight;
  if (m < 2.5) return L.w_moderate;
  if (m < 4) return L.w_rough;
  return L.w_vrough;
}

function windWord(kmh: number | null | undefined, L: L): string {
  if (kmh == null) return "";
  if (kmh < 12) return L.wn_light;
  if (kmh < 20) return L.wn_gentle;
  if (kmh < 30) return L.wn_strong;
  return L.wn_vstrong;
}

function hoursToWords(h: number | null | undefined, L: L): string {
  if (h == null) return "—";
  const mins = Math.round(h * 60);
  const hh = Math.floor(mins / 60);
  const mm = mins % 60;
  if (hh === 0) return i18n.fmt(L.h_min, { m: mm });
  if (mm === 0) return i18n.fmt(L.h_h, { h: hh });
  return i18n.fmt(L.h_hm, { h: hh, m: mm });
}

/** Plain direction from a compass bearing (8 points) — e.g. "20 km NE". */
function dirWords(bearing: number | null | undefined, L: L): string {
  if (bearing == null) return "";
  const names = [L.d_N, L.d_NE, L.d_E, L.d_SE, L.d_S, L.d_SW, L.d_W, L.d_NW];
  const idx = Math.round(((bearing % 360) + 360) % 360 / 45) % 8;
  return names[idx];
}

/** Overall score 0–1 → "82%" (display only, no computation). */
function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%`;
}

/** Friendly label for a measurement variable (names as emitted by
 *  zone_evaluator). The value/unit still come from the backend untouched —
 *  we only change the wording around it. */
const FRIENDLY: Record<string, { icon: IconCmp; key: i18n.Key; meaning: i18n.Key | ""; digits: number }> = {
  sst_c: { icon: TempIcon, key: "t_sst", meaning: "t_sst_m", digits: 1 },
  chlorophyll_mg_m3: { icon: LeafIcon, key: "t_chl", meaning: "t_chl_m", digits: 2 },
  wave_height_m: { icon: WaveIcon, key: "t_wave", meaning: "", digits: 2 },
  wind_speed_kmh: { icon: WindIcon, key: "t_wind", meaning: "", digits: 1 },
  current_speed_ms: { icon: CurrentIcon, key: "t_cur", meaning: "t_cur_m", digits: 2 },
};

function ConditionTile({ m, L }: { m: Measurement; L: L }) {
  const f = FRIENDLY[m.variable];
  const p = m.provenance;
  const Icon = f?.icon ?? PinIcon;
  const value = m.value == null ? "—" : fmt(m.value, f?.digits ?? 2);
  const word =
    m.variable === "wave_height_m" ? waveWord(m.value, L) : m.variable === "wind_speed_kmh" ? windWord(m.value, L) : "";
  return (
    <li className="tile">
      <div className="tile-head">
        <span className="tile-icon" aria-hidden><Icon size={15} /></span>
        <span className="tile-name">{f ? L[f.key] : m.variable}</span>
        {m.quality === "missing" && <span className="badge missing">{L.badge_missing}</span>}
        {m.quality === "stale" && <span className="badge stale">{L.badge_cached}</span>}
      </div>
      <div className="tile-value">
        {value} <span className="tile-unit">{m.unit ?? ""}</span>
        {word && <span className="tile-word">{word}</span>}
      </div>
      {f?.meaning && <div className="tile-meaning dim">{L[f.meaning]}</div>}
      {p && (
        <div className="prov dim">
          {p.source_name}
          {p.dataset ? ` · ${p.dataset}` : ""}
          {p.spatial_resolution ? ` · ${p.spatial_resolution}` : ""} · {L.retrieved} {ist(p.retrieved_at, "")}
        </div>
      )}
      {p?.notes && <div className="prov note dim">{p.notes}</div>}
    </li>
  );
}

function ScoreMeter(props: { label: string; value: number | null; hint: string; kind: "good" | "risk" }) {
  const pct = props.value == null ? 0 : Math.max(0, Math.min(1, props.value)) * 100;
  return (
    <li className="meter">
      <div className="meter-head">
        <span>{props.label}</span>
        <strong>{props.value == null ? "—" : `${Math.round(pct)}%`}</strong>
      </div>
      <div className="meter-bar">
        <div className={`meter-fill ${props.kind}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="dim meter-hint">{props.hint}</div>
    </li>
  );
}

function ZoneDetail({ zone, L }: { zone: ZoneEvaluation; L: L }) {
  const s = zone.score;
  return (
    <>
      <h3>{L.z_conds}</h3>
      <p className="dim section-hint">{L.z_conds_hint}</p>
      <ul className="tiles">{zone.measurements.map((m) => <ConditionTile key={m.variable} m={m} L={L} />)}</ul>

      <details className="expert">
        <summary>{L.expert_scores}</summary>
        <ul className="kv">
          <li>{L.kv_overall}: <strong>{fmt(s.overall_score, 3)}</strong> {L.kv_overall_note}</li>
          {zone.distance_to_boundary_km != null && (
            <li>{L.kv_boundary}: {fmt(zone.distance_to_boundary_km, 1)} {L.km}</li>
          )}
          {zone.front_strength?.sst_front_c_per_km != null && (
            <li>{L.kv_front}: {fmt(zone.front_strength.sst_front_c_per_km, 3)} °C/km</li>
          )}
        </ul>
        <ul className="meters">
          <ScoreMeter label={L.m_fish} value={s.productivity_score} hint={L.m_fish_hint} kind="good" />
          <ScoreMeter label={L.m_risk} value={s.risk_score} hint={L.m_risk_hint} kind="risk" />
        </ul>
      </details>
    </>
  );
}

type Verdict = { cls: string; icon: IconCmp; title: string; sub: string };

/** Verdict derived ONLY from the backend's warning severities — no new logic. */
function verdictOf(warnings: Warning[], L: L): Verdict {
  if (warnings.some((w) => w.severity === "critical")) {
    return { cls: "stop", icon: BanIcon, title: L.v_stop_t, sub: L.v_stop_s };
  }
  if (warnings.some((w) => w.severity === "warning" || w.severity === "caution")) {
    return { cls: "careful", icon: AlertTriangleIcon, title: L.v_care_t, sub: L.v_care_s };
  }
  return { cls: "go", icon: CheckCircleIcon, title: L.v_go_t, sub: L.v_go_s };
}

/** Missing-data chips: map the backend's *field* variable names (sst,
 *  current_u, …) to the same friendly labels + icons the measurement tiles
 *  use. Unknown names keep their raw code — never a made-up translation. */
const MISSING_VAR: Record<string, { icon: IconCmp; key: i18n.Key }> = {
  sst: { icon: TempIcon, key: "t_sst" },
  chlorophyll: { icon: LeafIcon, key: "t_chl" },
  wave_height: { icon: WaveIcon, key: "t_wave" },
  wind_u: { icon: WindIcon, key: "t_wind" },
  wind_v: { icon: WindIcon, key: "t_wind" },
  current_u: { icon: CurrentIcon, key: "t_cur" },
  current_v: { icon: CurrentIcon, key: "t_cur" },
};

/** Localize value-bearing warning messages; unknown codes keep the backend's
 *  honest English text rather than a made-up translation. */
function warningText(w: Warning, L: L): string {
  const p = (w.params ?? {}) as Record<string, string | number>;
  switch (w.code) {
    case "ROUGH_SEA":
      return i18n.fmt(L.wt_ROUGH_SEA, { v: fmt(p.wave_m as number, 1) });
    case "STRONG_WIND":
      return i18n.fmt(L.wt_STRONG_WIND, { v: fmt(p.wind_kmh as number, 0) });
    case "NO_WAVE_DATA":
      return L.wt_NO_WAVE_DATA;
    case "DEMO_MODE":
      return L.wt_DEMO_MODE;
    case "MANY_MISSING_PRODUCTS":
      return i18n.fmt(L.wt_MANY_MISSING_PRODUCTS, { n: p.count ?? "—", total: p.total ?? "—" });
    case "ORIGIN_INLAND":
      return i18n.fmt(L.wt_ORIGIN_INLAND, { v: p.place ?? "" });
    case "OFFICIAL_CYCLONE":
      return i18n.fmt(L.wt_OFFICIAL_CYCLONE, { n: p.name ?? "—", v: p.level ?? "—" });
    case "OFFICIAL_HIGH_WAVE":
      return i18n.fmt(L.wt_OFFICIAL_HIGH_WAVE, { v: p.level ?? "—" });
    case "OFFICIAL_SWELL_SURGE":
      return i18n.fmt(L.wt_OFFICIAL_SWELL_SURGE, { v: p.level ?? "—" });
    case "OFFICIAL_STORM_SURGE":
      return i18n.fmt(L.wt_OFFICIAL_STORM_SURGE, { v: p.level ?? "—" });
    case "OFFICIAL_IMD":
      return i18n.fmt(L.wt_OFFICIAL_IMD, { v: p.level ?? "—", n: p.name ?? "" });
    default:
      return w.message;
  }
}

/** Route notes arrive in English from the backend; the known shore-launch
 *  disclosure is shown in the UI language, others stay verbatim. */
function noteText(n: string, L: L): string {
  if (n.includes("nearest water point to the origin")) return L.rt_shore;
  return n;
}

function TripCard({ route, L }: { route: RouteOut; L: L }) {
  return (
    <section className="card">
      <h3>{L.trip}</h3>
      <ul className="kv trip">
        <li><CompassIcon size={14} /> {L.tr_distance}: <strong>{fmt(route.distance_km, 1)} {L.km}</strong></li>
        <li><ClockIcon size={14} /> {L.tr_time}: <strong>{hoursToWords(route.estimated_time_h, L)}</strong></li>
        {route.hazard_stats.max_wave_m != null && (
          <li><WaveIcon size={14} /> {L.tr_wave}: <strong>{fmt(route.hazard_stats.max_wave_m)} m</strong> — {waveWord(route.hazard_stats.max_wave_m, L)}</li>
        )}
      </ul>
      {route.blocked_by_constraints && <p className="blocked-note"><BanIcon size={14} /> {L.tr_blocked}</p>}
      {route.notes.length > 0 && <p className="note dim">{route.notes.map((n) => noteText(n, L)).join(" · ")}</p>}
      <details className="expert">
        <summary>{L.tr_explain}</summary>
        <p>{L.tr_explain_b}</p>
      </details>
    </section>
  );
}

export default function RecommendationPanel(props: {
  response: AdvisoryResponse | null;
  selectedZone: ZoneEvaluation | null;
  selectedRoute: RouteOut | null;
  routeLoading: boolean;
  routeError: boolean;
  language: string;
  voice: VoiceStatus | null;
  onPickZone: (zoneId: string | null) => void;
}) {
  const { response, selectedZone, language, voice } = props;
  const L = i18n.t(language);

  // voice playback state — hooks stay above the early return so the component
  // can unmount cleanly while audio is playing
  const [speaking, setSpeaking] = useState(false);
  useEffect(() => () => { stopSpeak(); browserStop(); }, []);

  if (!response) {
    return (
      <aside className="panel right">
        <h3>{L.recommendation}</h3>
        <p className="dim">{L.emptyRight}</p>
      </aside>
    );
  }
  const rec = response.recommended;
  const shown = selectedZone ?? rec;
  // picked zone shows ITS route (fetched on pick); the recommended zone shows
  // the advisory's own route — the panel renders whatever the backend sent
  const route = props.selectedRoute ?? response.route;
  const verdict = verdictOf(response.warnings, L);
  const VIcon = verdict.icon;
  const missing: { label: string; icon: IconCmp }[] = [];
  if (response.insufficient?.missing_variables) {
    const seen = new Set<string>();
    for (const v of response.insufficient.missing_variables) {
      const f = MISSING_VAR[v];
      const label = f ? L[f.key] : v;
      if (!seen.has(label)) {
        seen.add(label);
        missing.push({ label, icon: f?.icon ?? PinIcon });
      }
    }
  }
  const ranked = response.zones
    .filter((z) => !z.excluded && z.rank != null)
    .slice(0, 5);

  function endPlayback() {
    stopSpeak();
    browserStop();
    setSpeaking(false);
  }

  async function listen() {
    const text = response?.explanation;
    if (!text) return;
    endPlayback();
    setSpeaking(true);
    const done = () => setSpeaking(false);
    if (voice?.speak) {
      try {
        await api.speak(text, language, done);
      } catch (e) {
        done();
        alert(i18n.fmt(L.speakFail, { e: (e as Error).message }));
      }
      return;
    }
    if (!browserSpeak(text, language, done)) {
      setSpeaking(false);
      alert(L.speakUnavailable);
    }
  }

  return (
    <aside className="panel right">
      {response.insufficient ? (
        <>
          <div className="verdict stop" role="status">
            <span className="verdict-icon" aria-hidden><BanIcon size={22} /></span>
            <div>
              <div className="verdict-title">{L.v_none_t}</div>
              <div className="verdict-sub">{response.insufficient.detail}</div>
            </div>
          </div>
          {missing.length > 0 && (
            <div className="missing-card">
              <div className="missing-label">{L.missingData}</div>
              <ul className="missing-chips">
                {missing.map((mv) => {
                  const MIcon = mv.icon;
                  return (
                    <li key={mv.label} className="missing-chip">
                      <MIcon size={13} /> {mv.label}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          <p className="note dim">{L.whatToDo}</p>
        </>
      ) : (
        <>
          <div className={`verdict ${verdict.cls}`} role="status">
            <span className="verdict-icon" aria-hidden><VIcon size={22} /></span>
            <div>
              <div className="verdict-title">{verdict.title}</div>
              <div className="verdict-sub">{verdict.sub}</div>
            </div>
          </div>

          {ranked.length > 0 && (
            <>
              <h3>{L.bestZones}</h3>
              <ol className="zones-list">
                {ranked.map((z) => {
                  const active = shown?.candidate.id === z.candidate.id;
                  const isBest = z.candidate.id === rec?.candidate.id;
                  return (
                    <li key={z.candidate.id}>
                      <button
                        className={active ? "active" : ""}
                        aria-pressed={active}
                        onClick={() => props.onPickZone(z.candidate.id)}
                      >
                        <span className="rank">{isBest ? "★" : "#"}{z.rank}</span>
                        <span className="z-where">
                          {z.candidate.distance_from_origin_km} {L.km} {dirWords(z.candidate.bearing_deg, L)}
                        </span>
                        <span className="z-score">{pct(z.score.overall_score)}</span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              <p className="section-hint dim">{L.rankHint}</p>
            </>
          )}

          <h3>{L.whyZone}</h3>
          <p className="explanation">{response.explanation ?? L.noExplanation}</p>
          {rec && (
            <p className="note">
              {L.validFor} <strong>{ist(response.valid_time, language)}</strong> IST · {L.generated}{" "}
              {ist(response.generated_at, language)}
            </p>
          )}
          {speaking ? (
            <button className="link small stop-sound" onClick={endPlayback}><StopSoundIcon size={14} /> {L.stopSound}</button>
          ) : (
            <button className="link small" onClick={() => void listen()}><SpeakerIcon size={14} /> {L.listen}</button>
          )}
          {selectedZone && rec && selectedZone.candidate.id !== rec.candidate.id && (
            <p className="note dim">{L.pickedNote}</p>
          )}
          {shown && <ZoneDetail zone={shown} L={L} />}
          {route && <TripCard route={route} L={L} />}
          {props.routeLoading && <p className="note dim">{L.route_loading}</p>}
          {props.routeError && !props.routeLoading && <p className="note dim">{L.route_failed}</p>}
        </>
      )}

      {response.warnings.length > 0 && (
        <>
          <h3>{L.wTitle}</h3>
          <ul className="warnings">
            {response.warnings.map((w: Warning, i) => (
              <li key={i} className={SEVERITY_CLASS[w.severity] ?? "sev-info"}>
                <strong>{L[SEV_KEY[w.severity] ?? "sev_info"]}</strong> {warningText(w, L)}
              </li>
            ))}
          </ul>
        </>
      )}

      {response.evidence.length > 0 && (
        <details className="expert">
          <summary>{L.expert_evidence} ({response.evidence.length})</summary>
          <ul className="evidence">
            {response.evidence.map((e, i) => (
              <li key={i}>
                <div>{e.claim}</div>
                <div className="dim prov">{e.basis}{e.computation ? ` · ${e.computation}` : ""}</div>
              </li>
            ))}
          </ul>
        </details>
      )}

      <details className="expert">
        <summary>{L.glossary}</summary>
        <ul className="glossary">
          <li>{L.gl_zone}</li>
          <li>{L.gl_front}</li>
          <li>{L.gl_imbl}</li>
          <li>{L.gl_mpa}</li>
          <li>{L.gl_chl}</li>
          <li>{L.gl_sst}</li>
          <li>{L.gl_cached}</li>
        </ul>
      </details>

      <details className="trace">
        <summary>{L.raw} ({response.request_id})</summary>
        <pre>{JSON.stringify(response, null, 1).slice(0, 4000)}</pre>
      </details>
    </aside>
  );
}
