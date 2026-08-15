import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { AppShell, PageHeader } from "@/components/layout/AppShell";
import { useDemo } from "@/state/demo-store";
import {
  ApiError,
  videoApi,
  type SourceMode,
  type VideoJob,
  type VideoResult,
} from "@/services/apiClient";
import { useBackendSource } from "@/hooks/use-backend-source";
import { cn } from "@/lib/utils";

const ACCEPT = ".mp4,.avi,.mov,.mkv";
const ALLOWED = [".mp4", ".avi", ".mov", ".mkv"];
const POLL_MS = 2000;

export const Route = createFileRoute("/video-analysis")({
  head: () => ({
    meta: [
      { title: "Video Analysis — CrowdFlow Intelligence" },
      {
        name: "description",
        content:
          "Upload a CCTV or crowd video and run it through the CrowdFlow Python analysis pipeline to drive the live command center.",
      },
      { property: "og:title", content: "Video Analysis — CrowdFlow Intelligence" },
      {
        property: "og:description",
        content:
          "Real video in, real pipeline outputs out — tracking, density, flow, congestion, warnings and predictions.",
      },
    ],
  }),
  component: VideoAnalysisPage,
});

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

function VideoAnalysisPage() {
  const navigate = useNavigate();
  const { dataSource, setDataSource, refreshBackend } = useDemo();
  const { source: backendSource, refresh: refreshSource } = useBackendSource();

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [job, setJob] = useState<VideoJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<VideoResult | null>(null);
  const [uploadMode, setUploadMode] = useState<SourceMode>("SINGLE_CAMERA");
  const [busyJobId, setBusyJobId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Local-only preview; nothing is uploaded until START ANALYSIS.
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Pick up an analysis that is already running (e.g. after a page reload).
  useEffect(() => {
    let cancelled = false;
    void videoApi
      .active()
      .then((res) => {
        if (cancelled || !res.active) return;
        setJob(res.active);
        setBusyJobId(res.active.job_id);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const selectFile = useCallback((next: File | null) => {
    setError(null);
    setResult(null);
    if (!next) {
      setFile(null);
      return;
    }
    const ext = next.name.slice(next.name.lastIndexOf(".")).toLowerCase();
    if (!ALLOWED.includes(ext)) {
      setFile(null);
      setError(`Unsupported file type "${ext}". Use MP4, AVI, MOV or MKV.`);
      return;
    }
    if (next.size === 0) {
      setFile(null);
      setError("That file is empty.");
      return;
    }
    setFile(next);
  }, []);

  /** Reads ONLY the real result endpoint for this job. Nothing is derived. */
  const loadResult = useCallback(async (jobId: string) => {
    const next = await videoApi.result(jobId);
    setResult(next);
  }, []);

  // Poll the real job status; no invented progress.
  useEffect(() => {
    if (!job || (job.status !== "uploaded" && job.status !== "processing")) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await videoApi.status(job.job_id);
        if (cancelled) return;
        setJob(next);
        if (next.status === "completed") {
          setBusyJobId(null);
          if (dataSource !== "BACKEND") setDataSource("BACKEND");
          refreshBackend();
          refreshSource();
          void loadResult(next.job_id).catch(() => undefined);
        } else if (next.status === "failed") {
          setBusyJobId(null);
        }
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Lost contact with the analysis backend.",
        );
      }
    };
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [job, dataSource, setDataSource, refreshBackend, refreshSource, loadResult]);

  const processing =
    job != null && (job.status === "uploaded" || job.status === "processing");
  const startDisabled = !file || uploading || processing || busyJobId != null;

  const startAnalysis = useCallback(async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const ack = await videoApi.upload(file, uploadMode);
      const status = await videoApi.status(ack.job_id).catch(() => null);
      setBusyJobId(ack.job_id);
      setJob(
        status ?? {
          job_id: ack.job_id,
          filename: ack.filename,
          status: ack.status,
          stage: null,
          stages: [],
          error: null,
          createdAt: Date.now() / 1000,
          finishedAt: null,
        },
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("An analysis is already in progress. Wait for it to finish.");
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(
          "Could not reach the CrowdFlow backend. Start FastAPI, or switch to Demo mode.",
        );
      }
    } finally {
      setUploading(false);
    }
  }, [file, uploadMode]);

  const completed = job?.status === "completed";
  const failed = job?.status === "failed";

  const stages = useMemo(() => job?.stages ?? [], [job]);

  return (
    <AppShell>
      <PageHeader
        title="Video Analysis"
        subtitle="Run a real CCTV clip through the CrowdFlow Python pipeline — outputs drive the command center."
        actions={
          <div className="hidden font-mono text-[10px] tracking-[0.18em] text-muted-foreground md:block">
            SOURCE · {dataSource}
          </div>
        }
      />

      <div className="grid gap-4 p-5 lg:grid-cols-2">
        {/* ---------------- INPUT ---------------- */}
        <section className="border border-border bg-panel">
          <h2 className="border-b border-border px-4 py-3 font-mono text-[11px] tracking-[0.18em] text-muted-foreground uppercase">
            Video Input
          </h2>

          <div className="space-y-4 p-4">
            <div>
              <p className="font-mono text-[10px] tracking-[0.22em] text-muted-foreground uppercase">
                Source
              </p>
              <div className="mt-2 inline-flex border border-border-strong bg-panel-raised">
                {(
                  [
                    ["SINGLE_CAMERA", "Single Camera"],
                    ["DIGITAL_TWIN", "Digital Twin"],
                  ] as Array<[SourceMode, string]>
                ).map(([value, label]) => {
                  const disabled =
                    value === "DIGITAL_TWIN" &&
                    backendSource !== null &&
                    !backendSource.digitalTwinZonesConfigured;
                  return (
                    <button
                      key={value}
                      type="button"
                      disabled={disabled}
                      aria-pressed={uploadMode === value}
                      onClick={() => setUploadMode(value)}
                      className={cn(
                        "px-3 py-1.5 font-mono text-[10px] tracking-[0.18em] uppercase transition-colors",
                        uploadMode === value
                          ? "bg-info/15 text-info"
                          : "text-muted-foreground hover:text-foreground",
                        disabled && "cursor-not-allowed opacity-40",
                      )}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {uploadMode === "SINGLE_CAMERA"
                  ? "Analyses the full camera frame as one region. No venue zones required."
                  : backendSource && !backendSource.digitalTwinZonesConfigured
                    ? "Unavailable — videos/zones.json is not configured. Run backend/define_zones.py."
                    : "Maps the footage onto the configured venue zones (videos/zones.json)."}
              </p>
            </div>

            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                selectFile(e.dataTransfer.files?.[0] ?? null);
              }}
              className={cn(
                "flex flex-col items-center justify-center border border-dashed px-6 py-10 text-center transition-colors",
                dragging ? "border-info bg-info/5" : "border-border-strong bg-panel-raised",
              )}
            >
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted-foreground uppercase">
                Drop CCTV video here
              </p>
              <p className="mt-2 text-xs text-muted-foreground">MP4 · AVI · MOV · MKV</p>
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="mt-4 border border-border-strong px-3 py-1.5 font-mono text-[10px] tracking-[0.18em] text-foreground uppercase hover:bg-panel"
              >
                Choose file
              </button>
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => selectFile(e.target.files?.[0] ?? null)}
              />
            </div>

            {file && (
              <div className="border border-border-strong bg-panel-raised p-3">
                <dl className="grid grid-cols-2 gap-y-1 text-xs">
                  <dt className="text-muted-foreground">Filename</dt>
                  <dd className="truncate text-right font-mono">{file.name}</dd>
                  <dt className="text-muted-foreground">Size</dt>
                  <dd className="text-right font-mono">{formatBytes(file.size)}</dd>
                  <dt className="text-muted-foreground">Type</dt>
                  <dd className="text-right font-mono">{file.type || "video"}</dd>
                  <dt className="text-muted-foreground">State</dt>
                  <dd className="text-right font-mono text-info">SELECTED</dd>
                </dl>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    className="border border-border-strong px-3 py-1.5 font-mono text-[10px] tracking-[0.18em] uppercase hover:bg-panel"
                  >
                    Change
                  </button>
                  <button
                    type="button"
                    onClick={() => selectFile(null)}
                    className="border border-border-strong px-3 py-1.5 font-mono text-[10px] tracking-[0.18em] text-muted-foreground uppercase hover:bg-panel"
                  >
                    Remove
                  </button>
                </div>
              </div>
            )}

            <button
              type="button"
              disabled={startDisabled}
              onClick={() => void startAnalysis()}
              className={cn(
                "w-full border px-4 py-3 font-mono text-[11px] tracking-[0.22em] uppercase transition-colors",
                startDisabled
                  ? "cursor-not-allowed border-border text-muted-foreground"
                  : "border-info bg-info/15 text-info hover:bg-info/25",
              )}
            >
              {uploading
                ? "Uploading…"
                : processing || busyJobId
                  ? "Analysis in progress"
                  : "Start analysis"}
            </button>

            {error && (
              <p className="border border-critical/40 bg-critical/10 px-3 py-2 text-xs text-critical">
                {error}
              </p>
            )}
          </div>
        </section>

        {/* ---------------- PREVIEW ---------------- */}
        <section className="border border-border bg-panel">
          <h2 className="border-b border-border px-4 py-3 font-mono text-[11px] tracking-[0.18em] text-muted-foreground uppercase">
            Preview
          </h2>
          <div className="p-4">
            {previewUrl ? (
              <video
                key={previewUrl}
                src={previewUrl}
                controls
                muted
                className="w-full border border-border-strong bg-black"
              />
            ) : (
              <p className="py-16 text-center text-xs text-muted-foreground">
                Select a video to preview it locally. Nothing is uploaded until you press
                START ANALYSIS.
              </p>
            )}
          </div>
        </section>

        {/* ---------------- STATUS ---------------- */}
        {job && (
          <section className="border border-border bg-panel lg:col-span-2">
            <h2 className="border-b border-border px-4 py-3 font-mono text-[11px] tracking-[0.18em] text-muted-foreground uppercase">
              {completed ? "Analysis complete" : failed ? "Analysis failed" : "Processing video"}
              <span className="ml-3 normal-case text-foreground">{job.filename}</span>
            </h2>

            <div className="space-y-4 p-4">
              {failed ? (
                <div className="border border-critical/40 bg-critical/10 p-3">
                  <p className="font-mono text-[11px] tracking-[0.18em] text-critical uppercase">
                    Analysis failed
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    The CrowdFlow analysis pipeline could not complete this video.
                  </p>
                  {job.error && (
                    <p className="mt-2 font-mono text-[11px] text-critical/90">{job.error}</p>
                  )}
                </div>
              ) : stages.length > 0 ? (
                <ul className="grid gap-1 sm:grid-cols-2">
                  {stages.map((stage) => (
                    <li
                      key={stage.key}
                      className="flex items-center justify-between border border-border-strong bg-panel-raised px-3 py-2"
                    >
                      <span className="font-mono text-[10px] tracking-[0.18em] uppercase">
                        {stage.label}
                      </span>
                      <span
                        className={cn(
                          "font-mono text-xs",
                          stage.status === "done" && "text-safe",
                          stage.status === "running" && "text-info",
                          stage.status === "failed" && "text-critical",
                          (stage.status === "pending" || stage.status === "skipped") &&
                            "text-muted-foreground",
                        )}
                      >
                        {stage.status === "done"
                          ? "✓"
                          : stage.status === "running"
                            ? "→"
                            : stage.status === "failed"
                              ? "✕"
                              : stage.status === "skipped"
                                ? "–"
                                : "○"}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="font-mono text-[11px] tracking-[0.18em] text-info uppercase">
                  Processing video…
                </p>
              )}

              {completed && (
                <>
                  {result ? (
                    <ResultPanel result={result} />
                  ) : (
                    <p className="text-xs text-muted-foreground">Loading analysis results…</p>
                  )}

                  <button
                    type="button"
                    onClick={() => {
                      refreshBackend();
                      void navigate({ to: "/command-center" });
                    }}
                    className="border border-info bg-info/15 px-4 py-2 font-mono text-[11px] tracking-[0.22em] text-info uppercase hover:bg-info/25"
                  >
                    Open command center
                  </button>
                </>
              )}
            </div>
          </section>
        )}
      </div>
    </AppShell>
  );
}

/**
 * Renders ONLY values returned by /api/video/result/{job_id}.
 * Missing values are shown as N/A; a missing forecast is shown as
 * "Insufficient history" — never a fabricated prediction.
 */
function ResultPanel({ result }: { result: VideoResult }) {
  const s = result.summary;
  const singleCamera = result.mode === "SINGLE_CAMERA";

  const cells: Array<[string, string]> = [
    ["Source", singleCamera ? "Single Camera" : "Digital Twin"],
    ["People tracked", s.peopleTracked !== null ? String(s.peopleTracked) : "N/A"],
    [
      "People (latest frame)",
      s.peopleLatestFrame !== null ? String(s.peopleLatestFrame) : "N/A",
    ],
    ["Frames analysed to", s.latestFrame !== null ? `F${s.latestFrame}` : "N/A"],
    [singleCamera ? "Active region" : "Active zones",
      s.activeZones !== null ? String(s.activeZones) : "N/A"],
    [
      singleCamera ? "Peak density (camera region)" : "Highest-density zone",
      s.highestDensityZone
        ? `${s.highestDensityZone}${s.highestDensity !== null ? ` — ${s.highestDensity}` : ""}${
            s.densityLevel ? ` (${s.densityLevel})` : ""
          }`
        : "N/A",
    ],
    [
      singleCamera ? "Risk (camera region)" : "Highest-risk zone",
      s.highestRiskZone
        ? `${s.highestRiskZone}${s.highestRiskLevel ? ` — ${s.highestRiskLevel}` : ""}${
            s.highestRiskScore !== null ? ` (${s.highestRiskScore})` : ""
          }`
        : "N/A",
    ],
  ];

  const p = result.prediction;
  const predictionText = !p.available
    ? (p.reason ?? "Insufficient history")
    : `${p.zone ?? "N/A"}${
        p.minutesToCapacity !== null
          ? ` — ${p.minutesToCapacity.toFixed(1)} min to capacity`
          : ""
      }${p.statement ? ` · ${p.statement}` : ""}`;

  return (
    <div className="space-y-3">
      <dl className="grid gap-2 sm:grid-cols-3">
        {cells.map(([label, value]) => (
          <div key={label} className="border border-border-strong bg-panel-raised px-3 py-2">
            <dt className="font-mono text-[9px] tracking-[0.18em] text-muted-foreground uppercase">
              {label}
            </dt>
            <dd
              className={cn(
                "mt-1 font-mono text-sm break-words",
                value === "N/A" ? "text-muted-foreground" : "text-foreground",
              )}
            >
              {value}
            </dd>
          </div>
        ))}
        <div className="border border-border-strong bg-panel-raised px-3 py-2 sm:col-span-3">
          <dt className="font-mono text-[9px] tracking-[0.18em] text-muted-foreground uppercase">
            Prediction
          </dt>
          <dd
            className={cn(
              "mt-1 font-mono text-sm break-words",
              p.available ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {predictionText}
          </dd>
        </div>
      </dl>

      {singleCamera && (
        <p className="border border-border-strong bg-panel-raised px-3 py-2 text-xs text-muted-foreground">
          Camera-level results only. Venue routing and intervention recommendations are N/A
          for arbitrary single-camera footage.
        </p>
      )}
    </div>
  );
}
