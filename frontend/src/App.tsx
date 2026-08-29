/**
 * ORCA dashboard shell: demo banner (from /api/system/status, enforced by the
 * backend) + conversation panel | map | recommendation/evidence panel.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, stopSpeak } from "./api";
import { browserStop } from "./speech";
import * as i18n from "./i18n";
import type { AdvisoryResponse, SystemStatus, VoiceStatus, ZoneEvaluation } from "./types";
import MapPanel from "./components/MapPanel";
import QueryPanel from "./components/QueryPanel";
import RecommendationPanel from "./components/RecommendationPanel";

export default function App() {
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const [response, setResponse] = useState<AdvisoryResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState("en");
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);

  useEffect(() => {
    api.systemStatus().then(setSystem).catch(() => setSystem(null));
    api.voiceStatus().then(setVoice).catch(() => setVoice(null));
  }, []);

  const ask = useCallback(async (query: string, lang: string) => {
    if (!query) return;
    stopSpeak();
    browserStop();
    setBusy(true);
    setError(null);
    setSelectedZoneId(null);
    setLanguage(lang);
    try {
      const resp = await api.query(query, lang);
      setResponse(resp);
    } catch (e) {
      setError((e as Error).message || "query failed");
    } finally {
      setBusy(false);
    }
  }, []);

  const selectedZone: ZoneEvaluation | null = useMemo(() => {
    if (!response || !selectedZoneId) return null;
    return response.zones.find((z) => z.candidate.id === selectedZoneId) ?? null;
  }, [response, selectedZoneId]);

  const bannerRequired = response?.demo_banner_required || system?.demo_banner_required || false;
  const L = i18n.t(language);

  return (
    <div className="app-shell">
      {bannerRequired && (
        <div className="banner" role="alert">
          ⚠ {L.wt_DEMO_MODE}
        </div>
      )}
      <QueryPanel
        system={system}
        voice={voice}
        busy={busy}
        error={error}
        trace={response?.trace ?? null}
        language={language}
        onLanguage={setLanguage}
        onAsk={ask}
      />
      <MapPanel
        response={response}
        selectedZoneId={selectedZoneId}
        onPickZone={setSelectedZoneId}
        language={language}
      />
      <RecommendationPanel
        response={response}
        selectedZone={selectedZone}
        language={language}
        voice={voice}
        onPickZone={setSelectedZoneId}
      />
    </div>
  );
}
