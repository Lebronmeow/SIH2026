/**
 * Right panel: WHY THIS ZONE explanation, scores, measurements with
 * provenance, evidence list, warnings and route info. Every number shown
 * traces back to a backend measurement — the panel renders, never computes.
 */

import { api } from "../api";
import { browserSpeak } from "../speech";
import type { AdvisoryResponse, Measurement, RouteOut, VoiceStatus, Warning, ZoneEvaluation } from "../types";

const SEVERITY_CLASS: Record<string, string> = {
  info: "sev-info",
  caution: "sev-caution",
  warning: "sev-warning",
  critical: "sev-critical",
};

function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

function ist(t: string | null | undefined): string {
  if (!t) return "—";
  try {
    return new Date(t).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" });
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

function waveWord(m: number | null | undefined): string {
  if (m == null) return "";
  if (m < 0.5) return "calm sea";
  if (m < 1.25) return "slight waves";
  if (m < 2.5) return "moderate waves";
  if (m < 4) return "rough sea";
  return "very rough sea";
}

function windWord(kmh: number | null | undefined): string {
  if (kmh == null) return "";
  if (kmh < 12) return "light wind";
  if (kmh < 20) return "gentle breeze";
  if (kmh < 30) return "strong wind";
  return "very strong wind";
}

function hoursToWords(h: number | null | undefined): string {
  if (h == null) return "—";
  const mins = Math.round(h * 60);
  const hh = Math.floor(mins / 60);
  const mm = mins % 60;
  if (hh === 0) return `about ${mm} min`;
  if (mm === 0) return `about ${hh} h`;
  return `about ${hh} h ${mm} min`;
}

/** Plain direction from a compass bearing (8 points) — e.g. "20 km NE". */
function dirWords(bearing: number | null | undefined): string {
  if (bearing == null) return "distance";
  const names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
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
const FRIENDLY: Record<string, { icon: string; name: string; meaning: string; digits: number }> = {
  sst_c: { icon: "🌡️", name: "Water temperature", meaning: "Where the temperature changes quickly, fish often gather", digits: 1 },
  chlorophyll_mg_m3: { icon: "🌿", name: "Plant life in the water", meaning: "More plant life → more small fish → bigger fish come to feed", digits: 2 },
  wave_height_m: { icon: "🌊", name: "Wave height", meaning: "", digits: 2 },
  wind_speed_kmh: { icon: "💨", name: "Wind speed", meaning: "", digits: 1 },
  current_speed_ms: { icon: "🌀", name: "Current strength", meaning: "How hard the water pushes against the boat", digits: 2 },
};

function ConditionTile({ m }: { m: Measurement }) {
  const f = FRIENDLY[m.variable];
  const p = m.provenance;
  const value = m.value == null ? "—" : fmt(m.value, f?.digits ?? 2);
  const word =
    m.variable === "wave_height_m" ? waveWord(m.value) : m.variable === "wind_speed_kmh" ? windWord(m.value) : "";
  return (
    <li className="tile">
      <div className="tile-head">
        <span className="tile-icon" aria-hidden>{f?.icon ?? "📍"}</span>
        <span className="tile-name">{f?.name ?? m.variable}</span>
        {m.quality === "missing" && <span className="badge missing">MISSING</span>}
        {m.quality === "stale" && <span className="badge stale">CACHED</span>}
      </div>
      <div className="tile-value">
        {value} <span className="tile-unit">{m.unit ?? ""}</span>
        {word && <span className="tile-word">{word}</span>}
      </div>
      {f?.meaning && <div className="tile-meaning dim">{f.meaning}</div>}
      {p && (
        <div className="prov dim">
          {p.source_name}
          {p.dataset ? ` · ${p.dataset}` : ""}
          {p.spatial_resolution ? ` · ${p.spatial_resolution}` : ""} · retrieved {ist(p.retrieved_at)}
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

function ZoneDetail({ zone }: { zone: ZoneEvaluation }) {
  const s = zone.score;
  return (
    <>
      <h3>Fishing conditions at this zone</h3>
      <p className="dim section-hint">What the sea is like at this exact spot, measured by satellites and buoys.</p>
      <ul className="tiles">{zone.measurements.map((m) => <ConditionTile key={m.variable} m={m} />)}</ul>

      <details className="expert">
        <summary>Expert detail: scores &amp; numbers</summary>
        <ul className="kv">
          <li>Overall score: <strong>{fmt(s.overall_score, 3)}</strong> (higher is better)</li>
          {zone.distance_to_boundary_km != null && (
            <li>Distance to maritime boundary: {fmt(zone.distance_to_boundary_km, 1)} km</li>
          )}
          {zone.front_strength?.sst_front_c_per_km != null && (
            <li>SST front strength: {fmt(zone.front_strength.sst_front_c_per_km, 3)} °C/km</li>
          )}
        </ul>
        <ul className="meters">
          <ScoreMeter label="Fish potential" value={s.productivity_score} hint="How promising the water looks for fish (0–100%)" kind="good" />
          <ScoreMeter label="Safety risk" value={s.risk_score} hint="How risky the conditions are (lower is better)" kind="risk" />
        </ul>
      </details>
    </>
  );
}

type Verdict = { cls: string; icon: string; title: string; sub: string };

/** Verdict derived ONLY from the backend's warning severities — no new logic. */
function verdictOf(warnings: Warning[]): Verdict {
  if (warnings.some((w) => w.severity === "critical")) {
    return { cls: "stop", icon: "⛔", title: "Do not go out", sub: "A critical warning is active. Stay in harbour." };
  }
  if (warnings.some((w) => w.severity === "warning" || w.severity === "caution")) {
    return { cls: "careful", icon: "⚠️", title: "Go with care", sub: "Read the warnings below before you leave." };
  }
  return { cls: "go", icon: "✅", title: "Good day to fish", sub: "No safety warnings were raised for this trip." };
}

function TripCard({ route }: { route: RouteOut }) {
  return (
    <section className="card">
      <h3>Your boat trip</h3>
      <ul className="kv trip">
        <li>🧭 Distance to travel: <strong>{fmt(route.distance_km, 1)} km</strong></li>
        <li>⏱️ Time on the water: <strong>{hoursToWords(route.estimated_time_h)}</strong></li>
        {route.hazard_stats.max_wave_m != null && (
          <li>🌊 Biggest wave on the way: <strong>{fmt(route.hazard_stats.max_wave_m)} m</strong> — {waveWord(route.hazard_stats.max_wave_m)}</li>
        )}
      </ul>
      {route.blocked_by_constraints && (
        <p className="blocked-note">
          ⛔ No safe route could be drawn — a hard boundary or protected area blocks the path. Read the warnings below.
        </p>
      )}
      {route.notes.length > 0 && <p className="note dim">{route.notes.join(" · ")}</p>}
      <details className="expert">
        <summary>What does "safe route" mean?</summary>
        <p>
          ORCA plans the boat's path from the coast to the fishing zone and checks every step against real map layers:
          the India–Sri Lanka maritime boundary (IMBL), protected marine parks and land. A route is only drawn if it
          stays clear of all of them, and wave and wind data along the way steer it toward calmer water. The path is
          computed by a deterministic routing engine — the AI never draws or approves it.
        </p>
      </details>
    </section>
  );
}

export default function RecommendationPanel(props: {
  response: AdvisoryResponse | null;
  selectedZone: ZoneEvaluation | null;
  language: string;
  voice: VoiceStatus | null;
  onPickZone: (zoneId: string | null) => void;
}) {
  const { response, selectedZone, language, voice } = props;
  if (!response) {
    return (
      <aside className="panel right">
        <h3>Recommendation</h3>
        <p className="dim">Ask a question to see the evidence-backed recommendation.</p>
      </aside>
    );
  }
  const rec = response.recommended;
  const shown = selectedZone ?? rec;
  const route = response.route;
  const verdict = verdictOf(response.warnings);
  const ranked = response.zones
    .filter((z) => !z.excluded && z.rank != null)
    .slice(0, 5);

  async function listen() {
    const text = response?.explanation;
    if (!text) return;
    if (voice?.speak) {
      try {
        await api.speak(text, language);
      } catch (e) {
        alert(`Read-aloud failed: ${(e as Error).message}`);
      }
      return;
    }
    if (!browserSpeak(text, language)) {
      alert("Read-aloud needs Chrome or Edge — or a Bhashini API key (see README).");
    }
  }

  return (
    <aside className="panel right">
      {response.insufficient ? (
        <>
          <div className="verdict stop" role="status">
            <span className="verdict-icon" aria-hidden>🚫</span>
            <div>
              <div className="verdict-title">Cannot advise right now</div>
              <div className="verdict-sub">{response.insufficient.detail}</div>
            </div>
          </div>
          {response.insufficient.missing_variables && (
            <p className="dim">Missing data: {response.insufficient.missing_variables.join(", ")}</p>
          )}
          <p className="note dim">What you can do: ask again later, when more data is available.</p>
        </>
      ) : (
        <>
          <div className={`verdict ${verdict.cls}`} role="status">
            <span className="verdict-icon" aria-hidden>{verdict.icon}</span>
            <div>
              <div className="verdict-title">{verdict.title}</div>
              <div className="verdict-sub">{verdict.sub}</div>
            </div>
          </div>

          {ranked.length > 0 && (
            <>
              <h3>Best zones — tap one</h3>
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
                          {z.candidate.distance_from_origin_km} km {dirWords(z.candidate.bearing_deg)}
                        </span>
                        <span className="z-score">{pct(z.score.overall_score)}</span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              <p className="section-hint dim">The map shows the same numbers on each dot.</p>
            </>
          )}

          <h3>Why this zone?</h3>
          <p className="explanation">{response.explanation ?? "No explanation generated."}</p>
          {rec && (
            <p className="note">
              Valid for <strong>{ist(response.valid_time)}</strong> IST · generated {ist(response.generated_at)}
            </p>
          )}
          <button className="link small" onClick={() => void listen()}>🔊 Listen to this</button>
          {selectedZone && rec && selectedZone.candidate.id !== rec.candidate.id && (
            <p className="note dim">You picked a different zone on the map — its details are below.</p>
          )}
          {shown && <ZoneDetail zone={shown} />}
          {route && <TripCard route={route} />}
        </>
      )}

      {response.warnings.length > 0 && (
        <>
          <h3>Warnings</h3>
          <ul className="warnings">
            {response.warnings.map((w: Warning, i) => (
              <li key={i} className={SEVERITY_CLASS[w.severity] ?? "sev-info"}>
                <strong>{w.severity.toUpperCase()}</strong> {w.message}
              </li>
            ))}
          </ul>
        </>
      )}

      {response.evidence.length > 0 && (
        <details className="expert">
          <summary>Expert detail: evidence ({response.evidence.length})</summary>
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
        <summary>Word list — what these terms mean</summary>
        <ul className="glossary">
          <li><strong>Zone</strong> — a patch of sea that ORCA scored for fishing and safety.</li>
          <li><strong>Front</strong> — a line where warm and cool water meet; small fish gather there.</li>
          <li><strong>IMBL</strong> — the India–Sri Lanka maritime boundary line. Crossing it is not allowed.</li>
          <li><strong>MPA</strong> — a Marine Protected Area where fishing is restricted.</li>
          <li><strong>Chlorophyll</strong> — plant life in the water; a sign of fish feeding.</li>
          <li><strong>SST</strong> — sea surface temperature.</li>
          <li><strong>Cached</strong> — measured earlier and stored, not live this minute.</li>
        </ul>
      </details>

      <details className="trace">
        <summary>Raw response ({response.request_id})</summary>
        <pre>{JSON.stringify(response, null, 1).slice(0, 4000)}</pre>
      </details>
    </aside>
  );
}
