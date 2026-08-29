/** Thin typed client over the ORCA FastAPI backend (same-origin via Vite proxy). */

import type { AdvisoryResponse, SystemStatus, VoiceStatus } from "./types";

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

export const api = {
  systemStatus: () =>
    fetch("/api/system/status").then((r) => json<SystemStatus>(r)),

  voiceStatus: () =>
    fetch("/api/voice/status").then((r) => json<VoiceStatus>(r)),

  query: (query: string, language: string, signal?: AbortSignal) =>
    fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, language }),
      signal,
    }).then((r) => json<AdvisoryResponse>(r)),

  recommendation: (requestId: string) =>
    fetch(`/api/recommendations/${requestId}`).then((r) => json<AdvisoryResponse>(r)),

  transcribe: async (audioBlob: Blob, language: string): Promise<string> => {
    const b64 = await blobToBase64(audioBlob);
    const r = await fetch("/api/voice/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_base64: b64, language, encoding: "wav" }),
    });
    const body = await json<{ text: string }>(r);
    return body.text;
  },

  speak: (text: string, language: string): Promise<void> =>
    fetch("/api/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
    })
      .then((r) => json<{ audio_base64: string }>(r))
      .then(({ audio_base64 }) => {
        const bytes = Uint8Array.from(atob(audio_base64), (c) => c.charCodeAt(0));
        const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
        new Audio(url).play();
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
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
