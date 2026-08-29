/**
 * Map panel: MapLibre base + deck.gl overlay with ORCA's evidence layers.
 * Layers (all from the backend, nothing hand-drawn):
 *   - boundary GeoJSON (IMBL line / MPA polygons / land) with authority badges
 *   - candidate zones (Scatterplot), recommended zone highlighted
 *   - safe route (PathLayer)
 */

import { useEffect, useMemo, useRef } from "react";
import Map, { useControl, type MapRef } from "@vis.gl/react-maplibre";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// maplibre-gl v6 loads its tile/glyph worker relative to import.meta.url; under
// Vite's dep optimizer that sibling file is never emitted (404) and the map
// silently never renders — no tiles, no error. Point it at the real asset.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
maplibregl.setWorkerUrl(maplibreWorkerUrl);
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ScatterplotLayer, PathLayer, GeoJsonLayer, TextLayer } from "@deck.gl/layers";
import { PathStyleExtension } from "@deck.gl/extensions";
import type { PickingInfo } from "@deck.gl/core";
import type { AdvisoryResponse } from "../types";

const INITIAL_VIEW = {
  longitude: 79.31,
  latitude: 9.29,
  zoom: 8.6,
};

// colors
const ZONE_COLOR = [56, 189, 248, 220]; // sky
const RECOMMENDED_COLOR = [45, 212, 191, 255]; // teal accent
const ROUTE_COLOR = [45, 212, 191, 255];
const RING_COLOR = [45, 212, 191, 190]; // teal outline, dashed
const ORIGIN_COLOR = [250, 204, 21, 255]; // yellow
const LABEL_OUTLINE = [15, 23, 42, 255]; // slate-900

export default function MapPanel(props: {
  response: AdvisoryResponse | null;
  onPickZone: (id: string | null) => void;
  selectedZoneId: string | null;
}) {
  const { response, selectedZoneId } = props;
  const mapRef = useRef<MapRef>(null);

  // Frame the whole search area (ring + zones + route) whenever a new
  // response arrives, so users always see the full picture.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !response) return;
    const pts: [number, number][] = response.zones
      .filter((z) => !z.excluded)
      .map((z) => [z.candidate.lon, z.candidate.lat] as [number, number]);
    for (const c of response.route?.coords ?? []) pts.push([c[0], c[1]]);
    const ring = response.map_layers.find((f) => f.properties?.kind === "search_ring");
    if (ring?.geometry.type === "Polygon") {
      for (const [lon, lat] of (ring.geometry.coordinates as [number, number][][])[0]) pts.push([lon, lat]);
    }
    if (pts.length < 2) return;
    const lngs = pts.map((p) => p[0]);
    const lats = pts.map((p) => p[1]);
    map.fitBounds(
      [
        [Math.min(...lngs), Math.min(...lats)],
        [Math.max(...lngs), Math.max(...lats)],
      ],
      { padding: 56, maxZoom: 11.5, duration: 700 },
    );
  }, [response]);

  const scatters = useMemo(() => {
    const zones = response?.zones.filter((z) => !z.excluded) ?? [];
    const recommendedId = response?.recommended?.candidate.id;
    return zones.map((z) => ({
      position: [z.candidate.lon, z.candidate.lat] as [number, number],
      radius: z.candidate.id === recommendedId ? 1100 : 650,
      color:
        z.candidate.id === recommendedId
          ? RECOMMENDED_COLOR
          : z.candidate.id === selectedZoneId
            ? [250, 204, 21, 255]
            : ZONE_COLOR,
      zone: z,
    }));
  }, [response, selectedZoneId]);

  // Rank numbers drawn inside each dot (backend `rank` is 1 = best).
  const rankLabels = useMemo(() => {
    const zones = response?.zones.filter((z) => !z.excluded) ?? [];
    const recommendedId = response?.recommended?.candidate.id;
    return zones.map((z) => ({
      position: [z.candidate.lon, z.candidate.lat] as [number, number],
      text: z.candidate.id === recommendedId ? `★${z.rank ?? ""}` : `${z.rank ?? ""}`,
      recommended: z.candidate.id === recommendedId,
    }));
  }, [response]);

  // Harbour / starting point: from the search ring when present, else route start.
  const originPos = useMemo<[number, number] | null>(() => {
    if (!response) return null;
    const ring = response.map_layers.find((f) => f.properties?.kind === "search_ring");
    const o = ring?.properties?.origin;
    if (Array.isArray(o) && o.length === 2) return [o[0] as number, o[1] as number];
    return response.route?.coords?.[0] ?? null;
  }, [response]);

  const routePath = useMemo(() => {
    const r = response?.route;
    if (!r || r.coords.length < 2) return [];
    return [{ path: r.coords, mode: r.mode, dist: r.distance_km }];
  }, [response]);

  const boundaries = useMemo(() => response?.map_layers ?? [], [response]);

  const layers = useMemo(
    () => [
      // land polygons first (below everything)
      new GeoJsonLayer({
        id: "land",
        data: boundaries.filter((f) => f.properties?.kind === "land") as never,
        filled: true,
        stroked: true,
        getFillColor: [148, 163, 184, 60] as never,
        getLineColor: [148, 163, 184, 140] as never,
        lineWidthMinPixels: 1,
        pickable: false,
      }),
      new GeoJsonLayer({
        id: "mpa",
        data: boundaries.filter((f) => f.properties?.kind === "mpa" || f.properties?.kind === "restricted") as never,
        filled: true,
        stroked: true,
        getFillColor: [239, 68, 68, 40] as never,
        getLineColor: [239, 68, 68, 220] as never,
        lineWidthMinPixels: 2,
        pickable: true,
      }),
      new GeoJsonLayer({
        id: "imbl",
        data: boundaries.filter((f) => f.properties?.kind === "imbl") as never,
        filled: false,
        stroked: true,
        getLineColor: [239, 68, 68, 255] as never,
        getLineWidth: 3,
        lineWidthMinPixels: 3,
        pickable: true,
      }),
      new GeoJsonLayer({
        id: "search-ring",
        data: boundaries.filter((f) => f.properties?.kind === "search_ring") as never,
        stroked: true,
        filled: true,
        getFillColor: [45, 212, 191, 10] as never,
        getLineColor: RING_COLOR as never,
        getLineWidth: 2,
        lineWidthMinPixels: 2,
        extensions: [new PathStyleExtension({ dash: true })] as never,
        getDashArray: [7, 4] as never,
        dashJustified: true,
        pickable: false,
      }),
      new PathLayer({
        id: "route",
        data: routePath as never,
        getPath: (d: { path: [number, number][] }) => d.path,
        getColor: ROUTE_COLOR as never,
        getWidth: 4,
        widthMinPixels: 3,
        pickable: false,
      }),
      new ScatterplotLayer({
        id: "zones",
        data: scatters as never,
        getPosition: (d: { position: [number, number] }) => d.position,
        getRadius: (d: { radius: number }) => d.radius,
        getFillColor: (d: { color: number[] }) => d.color as never,
        radiusUnits: "meters" as never,
        radiusMinPixels: 7,
        stroked: true,
        getLineColor: [230, 239, 247, 220] as never,
        lineWidthMinPixels: 1,
        pickable: true,
        onClick: (info: PickingInfo) => {
          const zone = (info.object as { zone?: { candidate: { id: string } } } | null)?.zone;
          props.onPickZone(zone?.candidate.id ?? null);
          return true;
        },
      }),
      // starting point marker
      new ScatterplotLayer({
        id: "origin",
        data: originPos ? [{ position: originPos }] : [] as never,
        getPosition: (d: { position: [number, number] }) => d.position,
        getRadius: 600,
        radiusUnits: "meters" as never,
        radiusMinPixels: 8,
        getFillColor: ORIGIN_COLOR as never,
        stroked: true,
        getLineColor: [67, 45, 5, 255] as never,
        lineWidthMinPixels: 2,
        pickable: false,
      }),
      // rank numbers + start label (always pixel-sized, readable at any zoom)
      new TextLayer({
        id: "zone-ranks",
        data: rankLabels as never,
        getPosition: (d: { position: [number, number] }) => d.position,
        getText: (d: { text: string }) => d.text,
        getSize: (d: { recommended: boolean }) => (d.recommended ? 17 : 13),
        getColor: [255, 255, 255, 255] as never,
        fontWeight: 800,
        characterSet: "auto",
        fontSettings: { sdf: true, buffer: 6 },
        outlineWidth: 3,
        outlineColor: LABEL_OUTLINE as never,
        pickable: false,
      }),
      new TextLayer({
        id: "origin-label",
        data: originPos ? [{ position: originPos, text: "Start" }] : [] as never,
        getPosition: (d: { position: [number, number] }) => d.position,
        getText: (d: { text: string }) => d.text,
        getSize: 13,
        getColor: [250, 204, 21, 255] as never,
        getPixelOffset: [0, -18],
        fontWeight: 700,
        characterSet: "auto",
        fontSettings: { sdf: true, buffer: 6 },
        outlineWidth: 3,
        outlineColor: LABEL_OUTLINE as never,
        pickable: false,
      }),
    ],
    [boundaries, routePath, scatters, rankLabels, originPos, props],
  );

  return (
    <main className="map-container">
      <Map
        ref={mapRef}
        initialViewState={INITIAL_VIEW}
        mapStyle="https://tiles.openfreemap.org/styles/liberty"
      >
        <DeckGLBridge layers={layers} />
      </Map>
      <div className="map-legend">
        <span><i className="dot recommended" /> best zone (★1)</span>
        <span><i className="dot zone" /> other zones — number = rank (tap)</span>
        <span><i className="dot origin" /> start</span>
        <span><i className="dot route" /> safe route</span>
        <span><i className="poly ring" /> search area from shore</span>
        <span><i className="line imbl" /> India–Sri Lanka boundary</span>
        <span><i className="poly mpa" /> protected area</span>
      </div>
      {response?.insufficient && (
        <div className="map-overlay-error">
          Unable to make a reliable recommendation with the currently available data.
        </div>
      )}
    </main>
  );
}

/** Bridge: deck.gl layers rendered into the MapLibre WebGL context. */
function DeckGLBridge(props: { layers: unknown[] }) {
  const overlay = useControl<MapboxOverlay>(
    () => new MapboxOverlay({ layers: props.layers as never }),
  );
  // keep the overlay's layers in sync across renders (useControl builds once)
  overlay?.setProps({ layers: props.layers as never });
  return null;
}
