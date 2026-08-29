/**
 * Left panel: natural-language query input (text or mic), language picker,
 * example queries and the honest status readouts (mode, sources, trace).
 */

import { useRef, useState } from "react";
import { EXAMPLE_QUERIES, api } from "../api";
import { canListen, listenOnce } from "../speech";
import type { SystemStatus, VoiceStatus, WorkflowTrace } from "../types";

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ta", label: "தமிழ் (Tamil)" },
  { code: "te", label: "తెలుగు (Telugu)" },
  { code: "ml", label: "മലയാളം (Malayalam)" },
  { code: "hi", label: "हिन्दी (Hindi)" },
  { code: "bn", label: "বাংলা (Bengali)" },
  { code: "or", label: "ଓଡ଼ିଆ (Odia)" },
];

export default function QueryPanel(props: {
  system: SystemStatus | null;
  voice: VoiceStatus | null;
  busy: boolean;
  error: string | null;
  trace: WorkflowTrace | null;
  onAsk: (query: string, language: string) => void;
}) {
  const { system, voice, busy, error, trace } = props;
  const [text, setText] = useState(EXAMPLE_QUERIES[0]);
  const [language, setLanguage] = useState("en");
  const [recording, setRecording] = useState(false);
  const [listening, setListening] = useState(false);
  const [micNote, setMicNote] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const browserStt = canListen();
  const micEnabled = Boolean(voice?.transcribe) || browserStt;

  async function toggleMic() {
    setMicNote(null);
    // Bhashini/Dhruva ASR when configured — records audio and sends it to the backend.
    if (voice?.transcribe) {
      if (recording) {
        recorderRef.current?.stop();
        setRecording(false);
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mime = MediaRecorder.isTypeSupported("audio/wav") ? "audio/wav" : "";
        const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
        const chunks: Blob[] = [];
        rec.ondataavailable = (e) => chunks.push(e.data);
        rec.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          try {
            const heard = await api.transcribe(new Blob(chunks), language);
            setText(heard);
          } catch (e) {
            setMicNote(`Transcription unavailable: ${(e as Error).message}`);
          }
        };
        rec.start();
        recorderRef.current = rec;
        setRecording(true);
      } catch {
        setMicNote("Microphone unavailable in this browser.");
      }
      return;
    }
    // Browser fallback (Web Speech API) — one-shot, audio never leaves the device.
    if (listening) return;
    setListening(true);
    try {
      const heard = await listenOnce(language);
      if (heard) setText(heard);
    } catch (e) {
      setMicNote((e as Error).message);
    } finally {
      setListening(false);
    }
  }

  return (
    <aside className="panel left">
      <h1 className="brand">ORCA</h1>
      <p className="tagline">Marine ecosystem reasoning with collaborative agents</p>

      <label className="field-label" htmlFor="orca-query">Ask ORCA</label>
      <textarea
        id="orca-query"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder="e.g. safest and most productive zone 20 km off Rameswaram tomorrow morning"
      />
      <div className="row">
        <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Language">
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>{l.label}</option>
          ))}
        </select>
        <button
          className={`icon-btn ${recording || listening ? "recording" : ""}`}
          title={
            voice?.transcribe
              ? "Voice input (Bhashini ASR)"
              : browserStt
                ? "Voice input (this browser's speech — works best in Chrome/Edge)"
                : "Voice input not available in this browser"
          }
          disabled={!micEnabled}
          onClick={() => void toggleMic()}
        >
          {recording || listening ? "■" : "🎙"}
        </button>
        <button className="primary" disabled={busy || text.trim().length < 3} onClick={() => props.onAsk(text.trim(), language)}>
          {busy ? "Working…" : "Ask"}
        </button>
      </div>
      {micNote && <div className="error-box">{micNote}</div>}
      {voice?.english_only_fallback && (
        <p className="note dim">
          {browserStt
            ? "Bhashini voice not configured — using this browser's built-in voice (English works best)."
            : "Voice and translation services are not configured — English-only mode."}
        </p>
      )}

      <label className="field-label">Examples</label>
      <ul className="examples">
        {EXAMPLE_QUERIES.map((q) => (
          <li key={q}>
            <button className="link" onClick={() => setText(q)}>{q}</button>
          </li>
        ))}
      </ul>

      {error && <div className="error-box">{error}</div>}

      {trace && (
        <details className="trace">
          <summary>Workflow trace ({trace.steps?.length ?? 0} steps{trace.duration_seconds != null ? `, ${trace.duration_seconds}s` : ""})</summary>
          <ol>
            {(trace.steps ?? []).map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </details>
      )}

      {system && (
        <details className="expert">
          <summary>Data sources ({system.sources.length})</summary>
          <ul>
            {system.sources.map((s) => (
              <li key={s.id}>
                <strong>{s.name}</strong>
                <span className="dim"> — {s.authority}{s.license ? ` · ${s.license}` : ""}</span>
              </li>
            ))}
          </ul>
          <p className="note dim">
            LLM reasoning layer: {system.llm_reasoning_enabled ? `${system.llm_provider} (explanations/orchestration only)` : "off — deterministic pipeline"}
          </p>
        </details>
      )}
    </aside>
  );
}
