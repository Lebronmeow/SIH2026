/**
 * Basemap resolution with health probing.
 *
 * The map pane must never depend on the health of ONE free tile provider:
 * OpenFreeMap served HTTP-200 zero-byte vector tiles during a live outage
 * (2026-08-30), leaving only the style's background colour + relief raster —
 * a white, label-less map. resolveBasemapStyle() probes each candidate with
 * the same two requests the map will actually make (style JSON, then one
 * vector tile) and returns the first healthy style. Probes run once per
 * session and cost a few small requests.
 */

// Candidates in priority order. Dark Matter matches ORCA's dark instrument
// theme and is served by Carto's commercial infrastructure; Liberty keeps the
// detailed coastline look when OpenFreeMap recovers; Voyager is the light
// fallback of last resort.
export const PRIMARY_BASEMAP = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

const CANDIDATES = [
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  "https://tiles.openfreemap.org/styles/liberty",
  "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
] as const;

// A well-known ocean tile (8/184/121 = off Rameswaram) — content doesn't
// matter, a non-empty body does.
const PROBE_Z = 8;
const PROBE_X = 184;
const PROBE_Y = 121;

let resolved: string | null = null;
let resolvedHealthy = false;

async function firstTileUrl(style: unknown): Promise<string | null> {
  const sources = Object.values(
    (style as { sources?: Record<string, { url?: string; tiles?: string[] }> }).sources ?? {},
  );
  for (const s of sources) {
    if (s.tiles?.length) return s.tiles[0];
    if (s.url) {
      try {
        const tj = await fetch(s.url, { signal: AbortSignal.timeout(8000) });
        if (!tj.ok) continue;
        const meta = (await tj.json()) as { tiles?: string[] };
        if (meta.tiles?.length) return meta.tiles[0];
      } catch {
        continue;
      }
    }
  }
  return null;
}

async function healthy(styleUrl: string): Promise<boolean> {
  try {
    const res = await fetch(styleUrl, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) return false;
    const style = await res.json();
    const tmpl = await firstTileUrl(style);
    if (!tmpl) return false;
    const probe = tmpl
      .replace("{z}", String(PROBE_Z))
      .replace("{x}", String(PROBE_X))
      .replace("{y}", String(PROBE_Y));
    const tile = await fetch(probe, { signal: AbortSignal.timeout(8000) });
    // The outage mode to catch: HTTP 200 with an EMPTY body.
    if (!tile.ok) return false;
    const buf = await tile.arrayBuffer();
    return buf.byteLength > 0;
  } catch {
    return false;
  }
}

/** First healthy basemap style, or the last candidate so the map still
 *  mounts (better a degraded basemap than no map at all). `resolvedHealthy`
 *  records whether ANY candidate actually passed the probe — when nothing
 *  did, the map mounts anyway (still better than no map) but the UI must
 *  say so instead of showing a silent black canvas. */
export async function resolveBasemapStyle(): Promise<string> {
  if (resolved) return resolved;
  for (const styleUrl of CANDIDATES) {
    if (await healthy(styleUrl)) {
      resolved = styleUrl;
      resolvedHealthy = true;
      return resolved;
    }
    console.warn("basemap unhealthy, falling back:", styleUrl);
  }
  resolved = CANDIDATES[0];
  resolvedHealthy = false;
  return resolved;
}

/** True when the mounted style was verified healthy by the probe chain.
 *  False ⇒ every candidate failed (network-level tile block) and the map is
 *  running on an unverified style — the UI must surface that. */
export function basemapWasProbedHealthy(): boolean {
  return resolvedHealthy;
}
