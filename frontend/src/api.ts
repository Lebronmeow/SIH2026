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
      // 150 s: covers a cold Render start (model load + first external fetches)
      // without hanging the UI forever.
      signal: signal ?? AbortSignal.timeout(150_000),
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
      // cold-started backends can take ~45 s; past 60 s treat as failed and
      // surface the route_failed note instead of an endless spinner.
      signal: AbortSignal.timeout(60_000),
    }).then(async (r) => {
      const out = await json<Omit<RouteOut, "notes"> & { notes?: string[] }>(r);
      return { ...out, notes: out.notes ?? [] } as RouteOut;
    }),

  transcribe: async (audioBlob: Blob, language: string): Promise<string> => {
    // The mic records whatever container the browser gives it (Chrome: webm/
    // opus, Firefox: ogg). The backend advertises wav/mp3/flac/ogg, so decode
    // here and re-encode as true 16 kHz mono WAV — the "encoding" label then
    // matches the bytes (and ASR engines get clean, unambiguous audio).
    const wav = await blobToWav(audioBlob);
    const b64 = await blobToBase64(wav);
    const r = await fetch(url("/api/voice/transcribe"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_base64: b64, language, encoding: "wav" }),
    });
    const body = await json<{ text: string }>(r);
    return body.text;
  },

  speak: (text: string, language: string, onEnd?: () => void, signal?: AbortSignal): Promise<void> =>
    fetch(url("/api/voice/speak"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
      signal,
    })
      .then((r) => json<{ audio_base64: string; format?: string }>(r))
      .then(({ audio_base64, format }) => {
        // stop pressed mid-fetch → never start playback
        if (signal?.aborted) return;
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
        audio.play().catch(() => {
          // autoplay policy or decode failure — never leave "speaking" stuck on
          if (currentAudio === audio) currentAudio = null;
          onEnd?.();
        });
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

/** Decode any browser-recorded audio (webm/opus, ogg, …) and re-encode it as
 * 16 kHz mono 16-bit PCM WAV — the format ASR backends expect, with an honest
 * `encoding: "wav"` label. Resampling uses OfflineAudioContext; WAV assembly
 * is the plain RIFF/PCM spec (44-byte header + little-endian samples). */
async function blobToWav(blob: Blob): Promise<Blob> {
  if (blob.type.includes("wav")) return blob;
  const buf = await blob.arrayBuffer();
  const decodeCtx = new AudioContext();
  const decoded = await decodeCtx.decodeAudioData(buf);
  void decodeCtx.close();
  const targetRate = 16000;
  const frames = Math.max(1, Math.ceil(decoded.duration * targetRate));
  const offline = new OfflineAudioContext(1, frames, targetRate);
  const src = offline.createBufferSource();
  src.buffer = decoded;
  src.connect(offline.destination);
  src.start();
  const rendered = await offline.startRendering();
  const samples = rendered.getChannelData(0);
  const pcm = new DataView(new ArrayBuffer(samples.length * 2));
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    pcm.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  const header = new ArrayBuffer(44);
  const h = new DataView(header);
  const ascii = (off: number, text: string) => {
    for (let i = 0; i < text.length; i++) h.setUint8(off + i, text.charCodeAt(i));
  };
  ascii(0, "RIFF");
  h.setUint32(4, 36 + pcm.byteLength, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  h.setUint32(16, 16, true);
  h.setUint16(20, 1, true); // PCM
  h.setUint16(22, 1, true); // mono
  h.setUint32(24, targetRate, true);
  h.setUint32(28, targetRate * 2, true); // byte rate
  h.setUint16(32, 2, true); // block align
  h.setUint16(34, 16, true); // bits per sample
  ascii(36, "data");
  h.setUint32(40, pcm.byteLength, true);
  return new Blob([header, pcm.buffer], { type: "audio/wav" });
}

export const EXAMPLE_QUERIES = [
  "Where is the safest and most productive fishing zone 20 km off Rameswaram tomorrow morning?",
  "Best fishing spot 15 km off Rameswaram today afternoon",
  "Is it safe to fish 25 km off Rameswaram tomorrow?",
  "Which zones should I avoid off Rameswaram because of high waves or boundary rules?",
  "Show me the safest route 30 km off Kilakarai for tomorrow morning",
  "Where are the highest chlorophyll and good sea temperature off Rameswaram today?",
  "Is it safe to venture into the sea tomorrow morning from Rameswaram?",
];
