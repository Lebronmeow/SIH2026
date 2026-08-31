/**
 * Zone comparison mini-charts (pure CSS bars — no chart library).
 *
 * Dataviz contract (per design review):
 *  - Emphasis form: the RECOMMENDED zone wears the accent green; every other
 *    zone wears one de-emphasis gray. The list above the chart is the table
 *    view carrying every exact value — that is the relief channel that makes
 *    the sub-3:1 gray legal, per the palette validator output.
 *  - Thin marks (10px), rounded data-end only (square at the baseline),
 *    solid hairline gridlines, no borders around marks, no legend (each
 *    panel's title names its single series).
 *  - Waves panel draws the ROUGH_SEA threshold (2.5 m) as a 2px status line
 *    with a visible "2.5 m" tag — never color-alone.
 *  - Rows are real <button>s driving the same onPickZone as the ranked list,
 *    with aria-pressed + a title tooltip; values never gated behind hover.
 */

import type { CSSProperties } from "react";
import * as i18n from "../i18n";
import type { ZoneEvaluation } from "../types";

type L = Record<i18n.Key, string>;

/** De-emphasis step for non-recommended bars. Validated against the accent
 *  green (CVD ΔE 18.4 protan / 19.8 tritan, normal-vision 21.2 — all pass;
 *  contrast 2.0:1 is deliberately low because it is context, and every exact
 *  value sits in the ranked list right above = table-view relief). */
const DEEMPH = "#7f94a3";

const ROUGH_SEA_M = 2.5; // mirrors the backend's ROUGH_SEA caution threshold

function scorePct(v: number | null | undefined): number {
  return v == null ? 0 : Math.max(0, Math.min(1, v)) * 100;
}

function fmtScore(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%`;
}

export default function ZoneCharts(props: {
  zones: ZoneEvaluation[];
  recommendedId: string | undefined;
  selectedId: string | undefined;
  onPickZone: (zoneId: string | null) => void;
  L: L;
}) {
  const { zones, recommendedId, selectedId, L } = props;
  const ranked = zones
    .filter((z) => !z.excluded && z.rank != null)
    .sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));
  if (ranked.length === 0) return null;

  const waves = ranked.map(
    (z) => z.measurements.find((m) => m.variable === "wave_height_m")?.value ?? null,
  );
  const hasWaves = waves.some((w) => w != null);
  const waveMax = Math.max(
    ROUGH_SEA_M + 0.5,
    ...waves.filter((w): w is number => w != null).map((w) => Math.ceil(w)),
  );
  const activeId = selectedId ?? recommendedId;

  return (
    <div
      className="zone-chart"
      style={{ "--thr": `${(ROUGH_SEA_M / waveMax) * 100}%` } as CSSProperties}
    >

      <div className="zc-head" aria-hidden>
        <span />
        <span className="zc-head-label">{L.c_scores}</span>
        {hasWaves && <span className="zc-head-label">{L.c_waves}</span>}
      </div>
      <ol className="zc-rows">
        {ranked.map((z, i) => {
          const id = z.candidate.id;
          const active = activeId === id;
          const isBest = id === recommendedId;
          const sp = scorePct(z.score.overall_score);
          const wv = waves[i];
          const label = `#${z.rank} · ${L.c_scores} ${fmtScore(z.score.overall_score)}${
            hasWaves ? ` · ${L.c_waves} ${wv == null ? "—" : `${wv} m`}` : ""
          }`;
          return (
            <li key={id} className={active ? "active" : ""}>
              <button
                type="button"
                aria-pressed={active}
                aria-label={label}
                title={label}
                onClick={() => props.onPickZone(id)}
              >
                <span className="zc-rank" aria-hidden>{isBest ? "★" : z.rank}</span>
                <span className="zc-cell" aria-hidden>
                  {z.score.overall_score != null ? (
                    <>
                      <span className="zc-bar acc" style={{ width: `${sp}%`, background: isBest ? undefined : DEEMPH }} />
                      {/* selective direct label: only the recommended bar carries
                          its value at the tip — the axis, tooltips and the ranked
                          list above carry the rest */}
                      {isBest && (sp >= 78 ? (
                        <span className="zc-val in" style={{ left: `calc(${sp}% - 4px)` }}>{fmtScore(z.score.overall_score)}</span>
                      ) : (
                        <span className="zc-val" style={{ left: `calc(${sp}% + 4px)` }}>{fmtScore(z.score.overall_score)}</span>
                      ))}
                    </>
                  ) : (
                    <span className="zc-miss">—</span>
                  )}
                </span>
                {hasWaves && (
                  <span className="zc-cell wave" aria-hidden>
                    {wv != null ? (
                      <span className="zc-bar" style={{ width: `${Math.min(100, (wv / waveMax) * 100)}%` }} />
                    ) : (
                      <span className="zc-miss">—</span>
                    )}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
      <div className="zc-axis" aria-hidden>
        <span />
        <span className="zc-axis-span">
          <i>0</i>
          <b>100</b>
        </span>
        {hasWaves && (
          <span className="zc-axis-span wave">
            <i>0</i>
            <em style={{ left: `${(ROUGH_SEA_M / waveMax) * 100}%` }}>2.5 m</em>
            <b>{waveMax}</b>
          </span>
        )}
      </div>
    </div>
  );
}
