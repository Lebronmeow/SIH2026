/** API types mirroring backend/app/schemas/recommendation.py (Pydantic). */

export interface Provenance {
  source_id: string | null;
  source_name: string | null;
  dataset: string | null;
  retrieved_at: string | null;
  valid_time: string | null;
  spatial_resolution: string | null;
  unit: string | null;
  mode: string;
  authority?: string | null;
  notes?: string | null;
}

export interface Warning {
  severity: "info" | "caution" | "warning" | "critical";
  message: string;
  code: string | null;
  source: string | null;
}

export interface Measurement {
  variable: string;
  value: number | null;
  unit: string;
  provenance: Provenance | null;
  quality: string;
  notes?: string | null;
}

export interface ZoneCandidate {
  id: string;
  lat: number;
  lon: number;
  bearing_deg: number;
  distance_from_origin_km: number;
}

export interface ZoneScore {
  productivity_score: number | null;
  risk_score: number | null;
  overall_score: number | null;
  components?: Record<string, number | null>;
}

export interface ZoneEvaluation {
  candidate: ZoneCandidate;
  score: ZoneScore;
  measurements: Measurement[];
  front_strength?: { sst_front_c_per_km?: number | null; chl_gradient_log_per_km?: number | null } | null;
  geofence?: { ok?: boolean; distance_to_imbl_m?: number | null } | null;
  distance_to_boundary_km?: number | null;
  excluded: boolean;
  exclusion_reason: string | null;
  rank: number | null;
}

export interface RouteOut {
  mode: string;
  coords: [number, number][];
  distance_km: number;
  estimated_time_h: number;
  hazard_stats: Record<string, number | null>;
  blocked_by_constraints: boolean;
  notes: string[];
}

export interface Evidence {
  claim: string;
  basis: string;
  measurement_variable?: string | null;
  value?: number | null;
  unit?: string | null;
  provenance?: Provenance | null;
  computation?: string | null;
}

export interface InsufficiencyReason {
  code: string;
  detail: string;
  missing_variables?: string[];
}

export interface ParsedQuery {
  raw_text?: string;
  origin?: { place: string; lat: number; lon: number } | null;
  distance_km?: number | null;
  time_window?: { start: string; end: string } | null;
  objective?: string | null;
}

export interface WorkflowTrace {
  steps: string[];
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
}

export interface GeoJSONFeature {
  type: "Feature";
  geometry: { type: string; coordinates: unknown };
  properties: Record<string, unknown>;
}

export interface AdvisoryResponse {
  request_id: string;
  parsed_query: ParsedQuery;
  mode: string;
  demo_banner_required: boolean;
  generated_at: string;
  valid_time: string | null;
  data_available: Record<string, boolean>;
  zones: ZoneEvaluation[];
  recommended: ZoneEvaluation | null;
  route: RouteOut | null;
  map_layers: GeoJSONFeature[];
  warnings: Warning[];
  evidence: Evidence[];
  sources: Provenance[];
  insufficient: InsufficiencyReason | null;
  explanation: string | null;
  trace: WorkflowTrace | null;
}

export interface SystemStatus {
  mode: string;
  demo_banner_required: boolean;
  banner_text: string;
  llm_reasoning_enabled: boolean;
  llm_provider: string;
  sources: { id: string; name: string; organization: string; authority: string; license: string | null }[];
}

export interface VoiceStatus {
  configured: boolean;
  engine: "bhashini" | "local" | "none";
  transcribe: boolean;
  translate: boolean;
  speak: boolean;
  english_only_fallback: boolean;
  message: string;
}
