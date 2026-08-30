/**
 * Left panel: natural-language query input (text or mic), language picker,
 * example queries and the honest status readouts (mode, sources, trace).
 */

import { useEffect, useRef, useState } from "react";
import { EXAMPLE_QUERIES, api } from "../api";
import { canListen, listenOnce } from "../speech";
import * as i18n from "../i18n";
import { MicIcon, PinIcon, SpeakerIcon, StopIcon } from "./icons";
import type { SystemStatus, VoiceStatus, WorkflowTrace } from "../types";

const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ta", label: "தமிழ் (Tamil)" },
  { code: "te", label: "తెలుగు (Telugu)" },
  { code: "ml", label: "മലയാളം (Malayalam)" },
  { code: "hi", label: "हिन्दी (Hindi)" },
  { code: "bn", label: "বাংলা (Bengali)" },
  { code: "or", label: "ଓଡ଼ିଆ (Odia)" },
  { code: "gu", label: "ગુજરાતી (Gujarati)" },
];

export default function QueryPanel(props: {
  system: SystemStatus | null;
  voice: VoiceStatus | null;
  busy: boolean;
  error: string | null;
  trace: WorkflowTrace | null;
  language: string;
  onLanguage: (lang: string) => void;
  onAsk: (query: string, language: string) => void;
}) {
  const { system, voice, busy, error, trace, language } = props;
  const L = i18n.t(language);
  const [text, setText] = useState(EXAMPLE_QUERIES[0]);
  const [recording, setRecording] = useState(false);
  const [listening, setListening] = useState(false);
  const [micNote, setMicNote] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const browserStt = canListen();
  const micEnabled = Boolean(voice?.transcribe) || browserStt;

  // Mission-control loading readout: while the advisory pipeline runs, cycle
  // through its three phases so the wait is legible (not a bare spinner).
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    if (!busy) {
      setPhase(0);
      return;
    }
    const id = window.setInterval(() => setPhase((p) => (p + 1) % 3), 2600);
    return () => window.clearInterval(id);
  }, [busy]);
  const phaseText = [L.load_data, L.load_safety, L.load_rank][phase];

  const micTitle =
    voice?.engine === "bhashini"
      ? L.micServerBhashini
      : voice?.engine === "local"
        ? L.micServerLocal
        : browserStt
          ? L.micBrowser
          : L.micNone;

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
      <p className="tagline">{L.tagline}</p>

      {system?.supported_region && (
        <p className="region-chip" title={`${system.supported_region.south}–${system.supported_region.north}°N, ${system.supported_region.west}–${system.supported_region.east}°E`}>
          <PinIcon size={12} />
          {L.pilotRegion}: {system.supported_region.name}
        </p>
      )}

      <label className="field-label" htmlFor="orca-query">{L.askOrca}</label>
      <textarea
        id="orca-query"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder={L.placeholder}
      />
      <div className="row">
        <select value={language} onChange={(e) => props.onLanguage(e.target.value)} aria-label="Language">
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>{l.label}</option>
          ))}
        </select>
        <button
          className={`icon-btn ${recording || listening ? "recording" : ""}`}
          title={micTitle}
          aria-label={micTitle}
          disabled={!micEnabled}
          onClick={() => void toggleMic()}
        >
          {recording || listening ? <StopIcon size={15} /> : <MicIcon size={15} />}
        </button>
        <button className="primary" disabled={busy || text.trim().length < 3} onClick={() => props.onAsk(text.trim(), language)}>
          {busy ? L.working : L.ask}
        </button>
      </div>
      {busy && (
        <div className="sonar-status" role="status" aria-live="polite">
          <span className="sonar" aria-hidden>
            <i /><i /><i />
          </span>
          <span className="sonar-phase">{phaseText}</span>
        </div>
      )}
      {micNote && <div className="error-box">{micNote}</div>}
      {voice?.message && (
        <p className="note dim voice-note"><SpeakerIcon size={13} /> {voice.message}</p>
      )}

      <label className="field-label">{L.examples}</label>
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
          <summary>{L.traceTitle} ({trace.steps?.length ?? 0}{trace.duration_seconds != null ? `, ${trace.duration_seconds}s` : ""})</summary>
          <ol>
            {(trace.steps ?? []).map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </details>
      )}

      {system && (
        <details className="expert">
          <summary>{L.sourcesTitle} ({system.sources.length})</summary>
          <ul>
            {system.sources.map((s) => (
              <li key={s.id}>
                <strong>{s.name}</strong>
                <span className="dim"> — {s.authority}{s.license ? ` · ${s.license}` : ""}</span>
              </li>
            ))}
          </ul>
          <p className="note dim">
            {system.llm_reasoning_enabled
              ? i18n.fmt(L.llmOn, { p: system.llm_provider })
              : L.llmOff}
          </p>
        </details>
      )}
    </aside>
  );
}
