/**
 * Thin HTTP client for the FastAPI layer around the existing Python backend.
 * Base URL comes from VITE_API_URL — never hard-code it in components.
 */

export const API_BASE_URL: string =
  (import.meta.env["VITE_API_URL"] as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    signal: signal ?? null,
    headers: { Accept: "application/json" },
  });

  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json())?.detail;
    } catch {
      detail = undefined;
    }
    const message =
      typeof detail === "object" && detail && "message" in detail
        ? String((detail as { message: unknown }).message)
        : `Request failed: ${path} (${res.status})`;
    throw new ApiError(message, res.status, detail);
  }
  return (await res.json()) as T;
}

// ---- Raw backend payload shapes (mirror the FastAPI responses) ----

export interface ApiVenue {
  venue_name: string | null;
  zones: Record<string, { area_m2: number; capacity: number }>;
  density_thresholds: Record<string, number> | null;
}

export interface ApiCurrentZone {
  name: string;
  people: number;
  capacity: number | null;
  area_m2: number | null;
  occupancyPercent: number | null;
}

export interface ApiCurrent {
  latestFrame: number;
  zones: ApiCurrentZone[];
}

export interface ApiDensityZone {
  frame: number;
  zone: string;
  people: number;
  area_m2: number | null;
  capacity: number | null;
  density: number | null;
  capacity_usage: number | null;
  density_level: string | null;
  capacity_status: string | null;
}

export interface ApiFlowZone {
  zone: string;
  minute: number | null;
  entriesPerMinute: number | null;
  exitsPerMinute: number | null;
  netFlowPerMinute: number | null;
  flowStatus: string | null;
  directions: Record<string, unknown> | null;
}

export interface ApiCongestionZone {
  zone: string;
  frame: number | null;
  people: number | null;
  previous_people: number | null;
  density_change: number | null;
  growth_rate: number | null;
  congestion: string | null;
  trend?: string | null;
}

export interface ApiWarningZone {
  zone: string;
  people: number | null;
  area_m2: number | null;
  density_people_m2: number | null;
  capacity: number | null;
  capacity_usage: number | null;
  entries_per_minute: number | null;
  exits_per_minute: number | null;
  net_flow_per_minute: number | null;
  minutes_to_capacity: number | null;
  risk_score: number | null;
  risk_level: string | null;
  prediction: string | null;
  recommendation: string | null;
}

export interface ApiPredictionZone {
  zone: string;
  current_people: number | null;
  trend_people_per_minute: number | null;
  predicted_people_5_min: number | null;
  predicted_people_10_min: number | null;
  capacity: number | null;
  minutes_to_capacity: number | null;
  trend: string | null;
  prediction: string | null;
}

export interface ApiTimeline {
  density: Array<{
    frame: number;
    zone: string;
    people: number | null;
    density: number | null;
    capacity: number | null;
    capacityUsage: number | null;
    densityLevel: string | null;
    capacityStatus: string | null;
  }>;
  flow: Array<{
    minute: number | null;
    zone: string;
    entriesPerMinute: number | null;
    exitsPerMinute: number | null;
    netFlowPerMinute: number | null;
    flowStatus: string | null;
  }>;
}

export const api = {
  health: (signal?: AbortSignal) => apiGet<{ status: string }>("/api/health", signal),
  source: (signal?: AbortSignal) => apiGet<ApiSource>("/api/source", signal),
  venue: (signal?: AbortSignal) => apiGet<ApiVenue>("/api/venue", signal),
  current: (signal?: AbortSignal) => apiGet<ApiCurrent>("/api/crowd/current", signal),
  density: (signal?: AbortSignal) =>
    apiGet<{ latestFrame: number | null; zones: ApiDensityZone[] }>(
      "/api/crowd/density",
      signal,
    ),
  flow: (signal?: AbortSignal) =>
    apiGet<{ zones: ApiFlowZone[] }>("/api/crowd/flow", signal),
  congestion: (signal?: AbortSignal) =>
    apiGet<{ source: string; zones: ApiCongestionZone[] }>("/api/crowd/congestion", signal),
  warnings: (signal?: AbortSignal) =>
    apiGet<{ zones: ApiWarningZone[] }>("/api/warnings", signal),
  predictions: (signal?: AbortSignal) =>
    apiGet<{ zones: ApiPredictionZone[] }>("/api/predictions", signal),
  timeline: (signal?: AbortSignal) => apiGet<ApiTimeline>("/api/crowd/timeline", signal),
};

// ---- Active analysis source (/api/source) ----

export type SourceMode = "DIGITAL_TWIN" | "SINGLE_CAMERA";

export interface ApiSource {
  mode: SourceMode;
  label: string;
  jobId: string | null;
  modes: SourceMode[];
  digitalTwinAvailable: boolean;
  digitalTwinZonesConfigured: boolean;
}

export async function setSource(
  mode: SourceMode,
  jobId?: string | null,
  signal?: AbortSignal,
): Promise<ApiSource> {
  const res = await fetch(`${API_BASE_URL}/api/source`, {
    method: "POST",
    signal: signal ?? null,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ mode, job_id: jobId ?? null }),
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json())?.detail;
    } catch {
      detail = undefined;
    }
    const message =
      typeof detail === "object" && detail && "message" in detail
        ? String((detail as { message: unknown }).message)
        : `Could not switch source (${res.status})`;
    throw new ApiError(message, res.status, detail);
  }
  return (await res.json()) as ApiSource;
}

// ---- Video analysis (upload -> existing Python pipeline) ----

export type VideoJobStatus = "uploaded" | "processing" | "completed" | "failed";

export interface VideoJobStage {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "skipped" | "failed";
}

export interface VideoJob {
  job_id: string;
  filename: string;
  mode?: SourceMode;
  status: VideoJobStatus;
  stage: string | null;
  stages: VideoJobStage[];
  error: string | null;
  createdAt: number;
  finishedAt: number | null;
}

export interface VideoUploadAck {
  job_id: string;
  filename: string;
  status: VideoJobStatus;
  mode?: SourceMode;
}

/** Result of one completed job — every field is a real pipeline output or null. */
export interface VideoResultSummary {
  peopleTracked: number | null;
  peopleLatestFrame: number | null;
  latestFrame: number | null;
  activeZones: number | null;
  highestDensityZone: string | null;
  highestDensity: number | null;
  densityLevel: string | null;
  highestRiskZone: string | null;
  highestRiskScore: number | null;
  highestRiskLevel: string | null;
}

export interface VideoResultPrediction {
  available: boolean;
  reason: string | null;
  zone: string | null;
  minutesToCapacity: number | null;
  trend: string | null;
  statement: string | null;
}

export interface VideoResult {
  job_id: string;
  filename: string;
  mode: SourceMode;
  status: VideoJobStatus;
  isActiveSource: boolean;
  summary: VideoResultSummary;
  prediction: VideoResultPrediction;
  artifacts: Record<string, boolean>;
  zones: {
    density: ApiDensityZone[];
    flow: Array<Record<string, unknown>>;
    congestion: ApiCongestionZone[];
    warnings: ApiWarningZone[];
    predictions: ApiPredictionZone[];
  };
}

async function apiPostFile<T>(
  path: string,
  file: File,
  fields: Record<string, string> = {},
  signal?: AbortSignal,
): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  Object.entries(fields).forEach(([key, value]) => body.append(key, value));
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    body,
    signal: signal ?? null,
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json())?.detail;
    } catch {
      detail = undefined;
    }
    const message =
      typeof detail === "object" && detail && "message" in detail
        ? String((detail as { message: unknown }).message)
        : `Upload failed (${res.status})`;
    throw new ApiError(message, res.status, detail);
  }
  return (await res.json()) as T;
}

export const videoApi = {
  upload: (file: File, mode: SourceMode = "SINGLE_CAMERA", signal?: AbortSignal) =>
    apiPostFile<VideoUploadAck>("/api/video/upload", file, { mode }, signal),
  status: (jobId: string, signal?: AbortSignal) =>
    apiGet<VideoJob>(`/api/video/status/${encodeURIComponent(jobId)}`, signal),
  result: (jobId: string, signal?: AbortSignal) =>
    apiGet<VideoResult>(`/api/video/result/${encodeURIComponent(jobId)}`, signal),
  active: (signal?: AbortSignal) =>
    apiGet<{ active: VideoJob | null }>("/api/video/active", signal),
};
