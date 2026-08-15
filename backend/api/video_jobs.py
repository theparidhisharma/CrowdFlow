"""Background job runner that feeds an uploaded video into the EXISTING pipeline.

No crowd-analysis logic lives here. This module only:
  * stores the uploaded video under videos/job_data/<job_id>/
  * generates a job-specific SINGLE CAMERA region (never touching the
    configured venue zones or backend/venue_config.json)
  * runs the original backend scripts (tracker.py, zone_analysis.py, ...) as
    subprocesses, in their real dependency order
  * tracks stage status so the frontend can show real progress

The scripts themselves are unchanged apart from resolving their paths through
backend/paths.py, which honours CROWDFLOW_VIDEO / CROWDFLOW_OUT_DIR /
CROWDFLOW_ZONES / CROWDFLOW_CONFIG and falls back to the original defaults.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import csv_utils
from .csv_utils import JOB_DATA_DIR, PROJECT_ROOT, VENUE_CONFIG_PATH, VIDEOS_DIR

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
ALLOWED_MIME_PREFIXES = ("video/", "application/octet-stream")
MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MB

VENUE_ZONES_PATH = os.path.join(VIDEOS_DIR, "zones.json")

CAMERA_ZONE_NAME = "Camera Region"


@dataclass(frozen=True)
class Step:
    script: str
    optional: bool = False


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    failure: str
    steps: List[Step]


# The existing scripts, in their real input/output dependency order.
#
#   tracker.py        video            -> tracks.csv (+ video_meta.json)
#   zone_analysis.py  tracks + zones   -> zone_tracking.csv
#   density_analysis  zone_tracking    -> density_analysis.csv
#   zone_flow.py      zone_tracking    -> zone_flow.csv (+ events)
#   flow_analysis.py  zone_tracking    -> flow_analysis.csv        (optional)
#   zone_congestion   zone_tracking    -> zone_congestion.csv
#   early_warning.py  zone_tracking + zone_flow + config -> early_warning.csv
#   crowd_prediction  zone_tracking + config             -> crowd_prediction.csv
#
# analyze_tracks.py / congestion.py / visualize_crowd.py / verify_zones.py are
# offline rendering utilities and are NOT part of the active API pipeline.
STAGES: List[Stage] = [
    Stage("UPLOAD", "Upload", "UPLOAD FAILED", []),
    Stage("TRACKING", "Tracking", "TRACKING FAILED", [Step("tracker.py")]),
    Stage(
        "CAMERA_REGION",
        "Camera Region Analysis",
        "CAMERA REGION ANALYSIS FAILED",
        [Step("zone_analysis.py")],
    ),
    Stage("DENSITY", "Density", "DENSITY ANALYSIS FAILED", [Step("density_analysis.py")]),
    Stage(
        "FLOW",
        "Flow",
        "FLOW ANALYSIS FAILED",
        [Step("zone_flow.py"), Step("flow_analysis.py", optional=True)],
    ),
    Stage(
        "CONGESTION",
        "Congestion",
        "CONGESTION ANALYSIS FAILED",
        [Step("zone_congestion.py")],
    ),
    Stage(
        "EARLY_WARNING",
        "Early Warning",
        "EARLY WARNING FAILED",
        [Step("early_warning.py")],
    ),
    Stage("PREDICTION", "Prediction", "PREDICTION FAILED", [Step("crowd_prediction.py")]),
    Stage("COMPLETE", "Complete", "ANALYSIS FAILED", []),
]


@dataclass
class Job:
    job_id: str
    filename: str
    mode: str = csv_utils.SINGLE_CAMERA
    status: str = "uploaded"  # uploaded | processing | completed | failed
    stage: Optional[str] = None
    stages: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    error_stage: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    video_path: str = ""
    job_dir: str = ""

    def public(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "mode": self.mode,
            "status": self.status,
            "stage": self.stage,
            "stages": [
                {"key": s.key, "label": s.label, "status": self.stages.get(s.key, "pending")}
                for s in STAGES
            ],
            "error": self.error,
            "errorStage": self.error_stage,
            "createdAt": self.created_at,
            "finishedAt": self.finished_at,
        }


_lock = threading.Lock()
_jobs: Dict[str, Job] = {}
_active_job_id: Optional[str] = None


class JobBusy(Exception):
    """Raised when another analysis is already running."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__("An analysis is already in progress.")


def active_job() -> Optional[Job]:
    with _lock:
        if _active_job_id is None:
            return None
        return _jobs.get(_active_job_id)


def get_job(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)


def safe_extension(filename: str) -> Optional[str]:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in ALLOWED_EXTENSIONS else None


def job_dir(job_id: str) -> str:
    return os.path.join(JOB_DATA_DIR, job_id)


def _write_status(job: Job) -> None:
    try:
        os.makedirs(job.job_dir, exist_ok=True)
        with open(os.path.join(job.job_dir, "status.json"), "w") as handle:
            json.dump(job.public(), handle, indent=2)
    except OSError:
        pass


def create_job(original_filename: str, data: bytes, mode: str = csv_utils.SINGLE_CAMERA) -> Job:
    """Persist the upload in its own job directory and queue the run."""
    global _active_job_id

    ext = safe_extension(original_filename)
    if ext is None:
        raise ValueError("Unsupported file type. Use .mp4, .avi, .mov or .mkv.")

    if mode == csv_utils.DIGITAL_TWIN and not os.path.isfile(VENUE_ZONES_PATH):
        raise ValueError(
            "Configured-venue mode requires videos/zones.json. "
            "Create it with `python backend/define_zones.py`, or upload as single camera."
        )

    with _lock:
        if _active_job_id is not None:
            running = _jobs.get(_active_job_id)
            if running and running.status in {"uploaded", "processing"}:
                raise JobBusy(_active_job_id)

        job_id = uuid.uuid4().hex
        directory = job_dir(job_id)
        os.makedirs(directory, exist_ok=True)
        # Server-generated name only — the client filename never touches the FS.
        path = os.path.join(directory, f"source{ext}")
        job = Job(
            job_id=job_id,
            filename=os.path.basename(original_filename),
            mode=mode,
            video_path=path,
            job_dir=directory,
        )
        _jobs[job_id] = job
        _active_job_id = job_id

    with open(path, "wb") as handle:
        handle.write(data)

    job.stages = {stage.key: "pending" for stage in STAGES}
    job.stages["UPLOAD"] = "done"
    _write_status(job)

    thread = threading.Thread(target=_run_job, args=(job.job_id,), daemon=True)
    thread.start()
    return job


# ------------------------------------------------------------------
# SINGLE CAMERA REGION
# ------------------------------------------------------------------
def _write_camera_zone(job: Job) -> None:
    """Create a job-specific full-frame camera region from the processed size.

    Never writes to videos/zones.json and never invents physical area.
    """
    meta_path = os.path.join(job.job_dir, "video_meta.json")
    if not os.path.isfile(meta_path):
        raise RuntimeError(
            "tracker.py did not report the processed video dimensions."
        )
    with open(meta_path, "r") as handle:
        meta = json.load(handle)

    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    if width <= 0 or height <= 0:
        raise RuntimeError("Processed video dimensions are unavailable.")

    zones = {
        "zones": [
            {
                "name": CAMERA_ZONE_NAME,
                "polygon": [[0, 0], [width, 0], [width, height], [0, height]],
            }
        ],
        "frame_width": width,
        "frame_height": height,
        "source": "single-camera job region (full processed frame)",
    }
    with open(os.path.join(job.job_dir, "camera_zone.json"), "w") as handle:
        json.dump(zones, handle, indent=2)

    # Density thresholds are reused from the venue configuration so the
    # classification logic is unchanged; no area_m2 / capacity is invented.
    thresholds = {"low": 0.10, "medium": 0.25, "high": 0.50, "critical": 0.75}
    try:
        with open(VENUE_CONFIG_PATH, "r") as handle:
            thresholds = json.load(handle).get("density_thresholds", thresholds)
    except (OSError, ValueError):
        pass

    config = {
        "venue_name": "Single Camera Analysis",
        "mode": "SINGLE_CAMERA",
        "zones": {CAMERA_ZONE_NAME: {}},
        "density_thresholds": thresholds,
    }
    with open(os.path.join(job.job_dir, "camera_config.json"), "w") as handle:
        json.dump(config, handle, indent=2)


def _job_env(job: Job) -> Dict[str, str]:
    env = dict(os.environ)
    env["CROWDFLOW_VIDEO"] = job.video_path
    env["CROWDFLOW_OUT_DIR"] = job.job_dir
    if job.mode == csv_utils.SINGLE_CAMERA:
        env["CROWDFLOW_ZONES"] = os.path.join(job.job_dir, "camera_zone.json")
        env["CROWDFLOW_CONFIG"] = os.path.join(job.job_dir, "camera_config.json")
    else:
        env["CROWDFLOW_ZONES"] = VENUE_ZONES_PATH
        env["CROWDFLOW_CONFIG"] = VENUE_CONFIG_PATH
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("MPLBACKEND", "Agg")
    return env


def _run_script(script: str, job: Job) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, os.path.join("backend", script)],
        cwd=PROJECT_ROOT,
        env=_job_env(job),
        capture_output=True,
        text=True,
        timeout=60 * 60,
    )


def _tail(text: str, lines: int = 3) -> str:
    parts = [line for line in (text or "").strip().splitlines() if line.strip()]
    return " / ".join(parts[-lines:])[:400]


def config_path_for(job: Job) -> str:
    if job.mode == csv_utils.SINGLE_CAMERA:
        return os.path.join(job.job_dir, "camera_config.json")
    return VENUE_CONFIG_PATH


def _run_job(job_id: str) -> None:
    global _active_job_id

    job = get_job(job_id)
    if job is None:
        return

    job.status = "processing"
    _write_status(job)

    try:
        for stage in STAGES:
            if stage.key in {"UPLOAD", "COMPLETE"}:
                continue
            job.stage = stage.key
            job.stages[stage.key] = "running"
            _write_status(job)

            # The camera region must exist before zone analysis runs, and it
            # can only be built once tracker.py has reported the real frame size.
            if stage.key == "CAMERA_REGION" and job.mode == csv_utils.SINGLE_CAMERA:
                _write_camera_zone(job)

            stage_ok = True
            for step in stage.steps:
                try:
                    result = _run_script(step.script, job)
                except subprocess.TimeoutExpired:
                    if step.optional:
                        stage_ok = False
                        continue
                    raise RuntimeError(f"{step.script} timed out while processing this video.")
                if result.returncode != 0:
                    detail = _tail(result.stderr) or _tail(result.stdout)
                    if step.optional:
                        stage_ok = False
                        continue
                    raise RuntimeError(f"{step.script}: {detail or 'no output'}")
            job.stages[stage.key] = "done" if stage_ok else "skipped"
            _write_status(job)

        required = ("zone_tracking.csv", "density_analysis.csv", "crowd_prediction.csv")
        missing = [n for n in required if not os.path.isfile(os.path.join(job.job_dir, n))]
        if missing:
            raise RuntimeError("Expected pipeline outputs are missing: " + ", ".join(missing))

        job.status = "completed"
        job.stage = "COMPLETE"
        job.stages["COMPLETE"] = "done"

        # Point the read-only data endpoints at this job's artifacts. The
        # configured venue artifacts in videos/ are untouched.
        csv_utils.set_source(job.mode, job.job_dir, job.job_id, config_path_for(job))
    except Exception as exc:  # noqa: BLE001 - surfaced as a stage-labelled message
        failed_stage = next((s for s in STAGES if s.key == job.stage), None)
        if job.stage:
            job.stages[job.stage] = "failed"
        job.status = "failed"
        job.error_stage = failed_stage.failure if failed_stage else "ANALYSIS FAILED"
        job.error = str(exc)[:500]
    finally:
        job.finished_at = time.time()
        _write_status(job)
        with _lock:
            if _active_job_id == job.job_id:
                _active_job_id = None
