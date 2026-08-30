/** Thin typed client over the ORCA FastAPI backend (same-origin via Vite proxy,
 * or VITE_API_BASE when the backend is hosted separately, e.g. Render). */

import type { AdvisoryResponse, RouteOut, SystemStatus, VoiceStatus } from "./types";

// Deployed builds point VITE_API_BASE at the backend origin (no trailing
// slash); local dev uses the Vite proxy and leaves it empty.
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");
const url = (path: string) => `${API_BASE}${path}`;

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep status-only detail */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

let currentAudio: HTMLAudioElement | null = null;

/** Stop read-aloud audio started through this module (server TTS playback). */
export function stopSpeak(): void {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
}

export const api = {
  systemStatus: () =>
    fetch(url("/api/system/status")).then((r) => json<SystemStatus>(r)),

  voiceStatus: () =>
    fetch(url("/api/voice/status")).then((r) => json<VoiceStatus>(r)),

  query: (query: string, language: string, signal?: AbortSignal) =>
    fetch(url("/api/query"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, language }),
      signal,
    }).then((r) => json<AdvisoryResponse>(r)),

  recommendation: (requestId: string) =>
    fetch(url(`/api/recommendations/${requestId}`)).then((r) => json<AdvisoryResponse>(r)),

  /** Risk-aware route from the departure point to a hand-picked zone
   * (hard constraints absolute — the engine snaps to water on its own). */
  optimizeRoute: (fromLat: number, fromLon: number, toLat: number, toLon: number) =>
    fetch(url("/api/route/optimize"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        from_lat: fromLat,
        from_lon: fromLon,
        to_lat: toLat,
        to_lon: toLon,
        mode: "safe",
      }),
    }).then(async (r) => {
      const out = await json<Omit<RouteOut, "notes"> & { notes?: string[] }>(r);
      return { ...out, notes: out.notes ?? [] } as RouteOut;
    }),

  transcribe: async (audioBlob: Blob, language: string): Promise<string> => {
    const b64 = await blobToBase64(audioBlob);
    const r = await fetch(url("/api/voice/transcribe"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_base64: b64, language, encoding: "wav" }),
    });
    const body = await json<{ text: string }>(r);
    return body.text;
  },

  speak: (text: string, language: string, onEnd?: () => void): Promise<void> =>
    fetch(url("/api/voice/speak"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
    })
      .then((r) => json<{ audio_base64: string; format?: string }>(r))
      .then(({ audio_base64, format }) => {
        const bytes = Uint8Array.from(atob(audio_base64), (c) => c.charCodeAt(0));
        const blobUrl = URL.createObjectURL(new Blob([bytes], { type: format === "mp3" ? "audio/mpeg" : "audio/wav" }));
        const audio = new Audio(blobUrl);
        currentAudio = audio;
        audio.onended = () => {
          if (currentAudio === audio) currentAudio = null;
          onEnd?.();
        };
        audio.onerror = () => {
          if (currentAudio === audio) currentAudio = null;
          onEnd?.();
        };
        audio.play();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
      }),
};

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const s = String(reader.result);
      resolve(s.slice(s.indexOf(",") + 1));
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

export const EXAMPLE_QUERIES = [
  "Where is the safest and most productive fishing zone 20 km off Rameswaram tomorrow morning?",
  "Best fishing spot 15 km off Rameswaram today afternoon",
  "Is it safe to fish 25 km off Rameswaram tomorrow?",
];
