/**
 * Browser voice fallback (Web Speech API) — used when Bhashini/Dhruva is not
 * configured, so voice input and read-aloud WORK without any API key. When
 * Bhashini is configured, callers prefer it and ignore this module.
 *
 * Honesty rules preserved: if the browser has no Indian-language voice we
 * still set utterance.lang (browsers fall back to a default voice) and the
 * UI says the voice is the browser's, never Bhashini's.
 */

const BCP47: Record<string, string> = {
  en: "en-IN",
  ta: "ta-IN",
  te: "te-IN",
  ml: "ml-IN",
  hi: "hi-IN",
  bn: "bn-IN",
  or: "or-IN",
  gu: "gu-IN",
};

export function langCode(lang: string): string {
  const base = lang.split("-")[0];
  return BCP47[base] ?? base;
}

export function canSpeak(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** Speak text with the browser's built-in TTS. Returns false when unsupported. */
export function browserSpeak(text: string, lang: string, onEnd?: () => void): boolean {
  if (!canSpeak() || !text) return false;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = langCode(lang);
  const voices = window.speechSynthesis.getVoices();
  const match =
    voices.find((v) => v.lang.toLowerCase() === utterance.lang) ??
    voices.find((v) => v.lang.startsWith(lang));
  if (match) utterance.voice = match;
  utterance.rate = 0.95;
  utterance.onend = () => onEnd?.();
  utterance.onerror = () => onEnd?.();
  window.speechSynthesis.speak(utterance);
  return true;
}

/** Stop browser TTS playback immediately. */
export function browserStop(): void {
  if (canSpeak()) window.speechSynthesis.cancel();
}

type RecognitionCtor = new () => {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

export function canListen(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as Record<string, unknown>;
  return Boolean(w.SpeechRecognition ?? w.webkitSpeechRecognition);
}

/** One-shot speech → text via the browser (Chrome/Edge). No audio leaves the device. */
export function listenOnce(lang: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const w = window as unknown as Record<string, unknown>;
    const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition) as RecognitionCtor | undefined;
    if (!Ctor) {
      reject(new Error("Voice input needs Chrome or Edge (or a Bhashini API key)."));
      return;
    }
    const rec = new Ctor();
    rec.lang = langCode(lang);
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    let done = false;
    rec.onresult = (event) => {
      const last = event.results[event.results.length - 1];
      if (last?.isFinal) {
        done = true;
        resolve(last[0].transcript.trim());
      }
    };
    rec.onerror = (event) => {
      const friendly: Record<string, string> = {
        "no-speech": "Didn't hear anything — try again.",
        "not-allowed": "Microphone permission denied — allow mic access in the browser.",
        "audio-capture": "No microphone found.",
        network: "Browser voice needs a network connection.",
      };
      reject(new Error(friendly[event.error] ?? `Voice input failed (${event.error}).`));
    };
    rec.onend = () => {
      if (!done) reject(new Error("Voice input stopped before hearing a query — try again."));
    };
    rec.start();
  });
}
