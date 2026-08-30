/**
 * ORCA dashboard shell: demo banner (from /api/system/status, enforced by the
 * backend) + conversation panel | map | recommendation/evidence panel.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, stopSpeak } from "./api";
import { browserStop } from "./speech";
import * as i18n from "./i18n";
import type { AdvisoryResponse, RouteOut, SystemStatus, VoiceStatus, ZoneEvaluation } from "./types";
import { AlertTriangleIcon } from "./components/icons";
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
  // route to a hand-picked (non-recommended) zone, fetched on selection
  const [selectedRoute, setSelectedRoute] = useState<RouteOut | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);

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
    setSelectedRoute(null);
    setRouteLoading(false);
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

  // Clicking a non-recommended zone fetches a safe route to it (the routing
  // engine snaps land origins to water on its own). The recommended zone
  // keeps the advisory's own route — no refetch.
  useEffect(() => {
    if (!response || !selectedZoneId) {
      setSelectedRoute(null);
      setRouteLoading(false);
      return;
    }
    const zone = response.zones.find((z) => z.candidate.id === selectedZoneId);
    const origin = response.parsed_query.origin;
    // the recommended zone already carries the advisory's own route
    if (!zone || !origin || response.recommended?.candidate.id === zone.candidate.id) {
      setSelectedRoute(null);
      setRouteLoading(false);
      return;
    }
    let cancelled = false;
    setRouteLoading(true);
    api
      .optimizeRoute(origin.lat, origin.lon, zone.candidate.lat, zone.candidate.lon)
      .then((route) => {
        if (!cancelled) setSelectedRoute(route);
      })
      .catch(() => {
        if (!cancelled) setSelectedRoute(null);
      })
      .finally(() => {
        if (!cancelled) setRouteLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [response, selectedZoneId]);

  const bannerRequired = response?.demo_banner_required || system?.demo_banner_required || false;
  const L = i18n.t(language);

  return (
    <div className="app-shell">
      {bannerRequired && (
        <div className="banner" role="alert">
          <AlertTriangleIcon size={14} /> {L.wt_DEMO_MODE}
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
        routeOverride={selectedRoute}
        onPickZone={setSelectedZoneId}
        language={language}
      />
      <RecommendationPanel
        response={response}
        selectedZone={selectedZone}
        selectedRoute={selectedRoute}
        routeLoading={routeLoading}
        language={language}
        voice={voice}
        onPickZone={setSelectedZoneId}
      />
    </div>
  );
}
