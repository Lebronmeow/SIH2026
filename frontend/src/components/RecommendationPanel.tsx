/**
 * Right panel: WHY THIS ZONE explanation, scores, measurements with
 * provenance, evidence list, warnings and route info. Every number shown
 * traces back to a backend measurement — the panel renders, never computes.
 */

import { api } from "../api";
import type { AdvisoryResponse, Evidence, Measurement, Warning, ZoneEvaluation } from "../types";

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

function ProvenanceRow({ m }: { m: Measurement }) {
  const p = m.provenance;
  return (
    <li key={m.variable} className="measurement">
      <div>
        <strong>{m.variable}</strong>: {m.value == null ? "—" : fmt(m.value, 3)} <span className="dim">{m.unit}</span>
        {m.quality === "missing" && <span className="badge missing">MISSING</span>}
        {m.quality === "stale" && <span className="badge stale">CACHED</span>}
      </div>
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

function ZoneDetail({ zone }: { zone: ZoneEvaluation }) {
  const s = zone.score;
  return (
    <>
      <h3>Zone scores</h3>
      <ul className="kv">
        <li>Overall: <strong>{fmt(s.overall_score, 3)}</strong></li>
        <li>Productivity: {fmt(s.productivity_score, 3)} (higher better)</li>
        <li>Risk: {fmt(s.risk_score, 3)} (lower better)</li>
        {zone.distance_to_boundary_km != null && (
          <li>Distance to maritime boundary: {fmt(zone.distance_to_boundary_km, 1)} km</li>
        )}
        {zone.front_strength?.sst_front_c_per_km != null && (
          <li>SST front strength: {fmt(zone.front_strength.sst_front_c_per_km, 3)} °C/km</li>
        )}
      </ul>
      <h3>Measurements at the zone</h3>
      <ul className="measurements">{zone.measurements.map((m) => <ProvenanceRow key={m.variable} m={m} />)}</ul>
    </>
  );
}

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  return (
    <>
      <h3>Evidence ({evidence.length})</h3>
      <ul className="evidence">
        {evidence.map((e, i) => (
          <li key={i}>
            <div>{e.claim}</div>
            <div className="dim prov">{e.basis}{e.computation ? ` · ${e.computation}` : ""}</div>
          </li>
        ))}
      </ul>
    </>
  );
}

export default function RecommendationPanel(props: {
  response: AdvisoryResponse | null;
  selectedZone: ZoneEvaluation | null;
  language: string;
}) {
  const { response, selectedZone, language } = props;
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

  return (
    <aside className="panel right">
      {response.insufficient ? (
        <>
          <h3>Unable to make a reliable recommendation</h3>
          <p>{response.insufficient.detail}</p>
          {response.insufficient.missing_variables && (
            <p className="dim">Missing: {response.insufficient.missing_variables.join(", ")}</p>
          )}
        </>
      ) : (
        <>
          <h3>WHY THIS ZONE</h3>
          <p className="explanation">{response.explanation ?? "No explanation generated."}</p>
          {rec && (
            <p className="note">
              Valid for <strong>{ist(response.valid_time)}</strong> IST · generated {ist(response.generated_at)}
            </p>
          )}
          <button
            className="link small"
            onClick={() => response.explanation && api.speak(response.explanation, language).catch(() => alert("Speech unavailable — Bhashini not configured."))}
          >
            🔊 Read aloud
          </button>
          {shown && <ZoneDetail zone={shown} />}
          {route && (
            <>
              <h3>Suggested route</h3>
              <ul className="kv">
                <li>Mode: <strong>{route.mode}</strong></li>
                <li>Distance: <strong>{fmt(route.distance_km, 1)} km</strong></li>
                <li>Estimated time: {fmt(route.estimated_time_h, 1)} h</li>
                {route.hazard_stats.max_wave_m != null && <li>Max wave along route: {fmt(route.hazard_stats.max_wave_m)} m</li>}
                {route.blocked_by_constraints && <li className="sev-critical">Blocked by hard constraints!</li>}
              </ul>
              {route.notes.length > 0 && <p className="note dim">{route.notes.join(" · ")}</p>}
            </>
          )}
          <EvidenceList evidence={response.evidence} />
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

      <details className="trace">
        <summary>Raw response ({response.request_id})</summary>
        <pre>{JSON.stringify(response, null, 1).slice(0, 4000)}</pre>
      </details>
    </aside>
  );
}
