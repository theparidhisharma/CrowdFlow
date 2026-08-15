"""API routes exposing the existing CrowdFlow pipeline outputs.

Every endpoint reads an artifact that the original Python scripts already
produce. No new crowd-analysis logic lives here.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import video_jobs
from .csv_utils import (
    PipelineNotRun,
    exists,
    latest_per_zone,
    load_venue_config,
    read_csv,
)
from . import csv_utils

router = APIRouter(prefix="/api")

VALID_MODES = (csv_utils.DIGITAL_TWIN, csv_utils.SINGLE_CAMERA)


def _pipeline_error(exc: PipelineNotRun) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": "PIPELINE_NOT_RUN",
            "missing": exc.filename,
            "message": str(exc),
        },
    )


# ------------------------------------------------------------------
# HEALTH
# ------------------------------------------------------------------
@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "artifacts": {
            "zone_tracking.csv": exists("zone_tracking.csv"),
            "density_analysis.csv": exists("density_analysis.csv"),
            "zone_flow.csv": exists("zone_flow.csv"),
            "flow_analysis.csv": exists("flow_analysis.csv"),
            "congestion_analysis.csv": exists("congestion_analysis.csv"),
            "zone_congestion.csv": exists("zone_congestion.csv"),
            "early_warning.csv": exists("early_warning.csv"),
            "crowd_prediction.csv": exists("crowd_prediction.csv"),
        },
    }


# ------------------------------------------------------------------
# VENUE  (backend/venue_config.json)
# ------------------------------------------------------------------
@router.get("/venue")
def venue() -> Dict[str, Any]:
    config = load_venue_config()
    return {
        "venue_name": config.get("venue_name"),
        "zones": config.get("zones", {}),
        "density_thresholds": config.get("density_thresholds"),
    }


# ------------------------------------------------------------------
# CURRENT  (videos/zone_tracking.csv from zone_analysis.py)
# ------------------------------------------------------------------
@router.get("/crowd/current")
def crowd_current() -> Dict[str, Any]:
    try:
        rows = read_csv(
            "zone_tracking.csv",
            stage="python backend/tracker.py -> python backend/zone_analysis.py",
        )
    except PipelineNotRun as exc:
        raise _pipeline_error(exc)

    rows = [r for r in rows if r.get("zone") not in (None, "Outside")]
    if not rows:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "NO_DATA",
                "message": "videos/zone_tracking.csv contains no in-zone observations.",
            },
        )

    latest_frame = max(int(r["frame"]) for r in rows if r.get("frame") is not None)
    config_zones = load_venue_config().get("zones", {})

    counts: Dict[str, int] = {}
    for row in rows:
        if row.get("frame") == latest_frame:
            counts[str(row["zone"])] = counts.get(str(row["zone"]), 0) + 1

    zones: List[Dict[str, Any]] = []
    for name, cfg in config_zones.items():
        people = counts.get(name, 0)
        capacity = cfg.get("capacity") or 0
        zones.append(
            {
                "name": name,
                "people": people,
                "capacity": capacity,
                "area_m2": cfg.get("area_m2"),
                "occupancyPercent": (people / capacity * 100) if capacity else None,
            }
        )
    # zones present in tracking but not in venue_config
    for name, people in counts.items():
        if name not in config_zones:
            zones.append(
                {
                    "name": name,
                    "people": people,
                    "capacity": None,
                    "area_m2": None,
                    "occupancyPercent": None,
                }
            )

    return {"latestFrame": latest_frame, "zones": zones}


# ------------------------------------------------------------------
# DENSITY  (videos/density_analysis.csv from density_analysis.py)
# ------------------------------------------------------------------
@router.get("/crowd/density")
def crowd_density() -> Dict[str, Any]:
    try:
        rows = read_csv(
            "density_analysis.csv", stage="python backend/density_analysis.py"
        )
    except PipelineNotRun as exc:
        raise _pipeline_error(exc)

    latest = latest_per_zone(rows, order_key="frame")
    latest_frame = max((r.get("frame") or 0) for r in latest) if latest else None
    return {"latestFrame": latest_frame, "zones": latest}


# ------------------------------------------------------------------
# FLOW  (videos/zone_flow.csv from zone_flow.py, flow_analysis.py extra)
# ------------------------------------------------------------------
@router.get("/crowd/flow")
def crowd_flow() -> Dict[str, Any]:
    try:
        rows = read_csv("zone_flow.csv", stage="python backend/zone_flow.py")
    except PipelineNotRun as exc:
        raise _pipeline_error(exc)

    latest = latest_per_zone(rows, order_key="minute")

    directions: Dict[str, Dict[str, Any]] = {}
    try:
        for row in read_csv("flow_analysis.csv", stage="python backend/flow_analysis.py"):
            zone = row.get("zone")
            if zone is not None:
                directions[str(zone)] = {
                    k: v for k, v in row.items() if k != "zone"
                }
    except PipelineNotRun:
        directions = {}

    zones = []
    for row in latest:
        zone = str(row.get("zone"))
        zones.append(
            {
                "zone": zone,
                "minute": row.get("minute"),
                "entriesPerMinute": row.get("entries_per_minute"),
                "exitsPerMinute": row.get("exits_per_minute"),
                "netFlowPerMinute": row.get("net_flow_per_minute"),
                "flowStatus": row.get("flow_status"),
                # only present when flow_analysis.py has been run
                "directions": directions.get(zone),
            }
        )
    return {"zones": zones}


# ------------------------------------------------------------------
# CONGESTION  (videos/congestion_analysis.csv, videos/zone_congestion.csv)
# ------------------------------------------------------------------
@router.get("/crowd/congestion")
def crowd_congestion() -> Dict[str, Any]:
    try:
        rows = read_csv(
            "congestion_analysis.csv", stage="python backend/congestion.py"
        )
        source = "videos/congestion_analysis.csv"
    except PipelineNotRun as primary:
        try:
            rows = read_csv(
                "zone_congestion.csv", stage="python backend/zone_congestion.py"
            )
            source = "videos/zone_congestion.csv"
        except PipelineNotRun:
            raise _pipeline_error(primary)

    latest = latest_per_zone(rows, order_key="frame")
    return {"source": source, "zones": latest}


# ------------------------------------------------------------------
# EARLY WARNING  (videos/early_warning.csv from early_warning.py)
# ------------------------------------------------------------------
@router.get("/warnings")
def warnings() -> Dict[str, Any]:
    try:
        rows = read_csv("early_warning.csv", stage="python backend/early_warning.py")
    except PipelineNotRun as exc:
        raise _pipeline_error(exc)
    return {"zones": rows}


# ------------------------------------------------------------------
# PREDICTIONS  (videos/crowd_prediction.csv from crowd_prediction.py)
# ------------------------------------------------------------------
@router.get("/predictions")
def predictions() -> Dict[str, Any]:
    try:
        rows = read_csv(
            "crowd_prediction.csv", stage="python backend/crowd_prediction.py"
        )
    except PipelineNotRun as exc:
        raise _pipeline_error(exc)
    return {"zones": rows}


# ------------------------------------------------------------------
# TIMELINE  (time-series from density_analysis.csv + zone_flow.csv)
# ------------------------------------------------------------------
@router.get("/crowd/timeline")
def timeline(limit: int = 240) -> Dict[str, Any]:
    try:
        density_rows = read_csv(
            "density_analysis.csv", stage="python backend/density_analysis.py"
        )
    except PipelineNotRun as exc:
        raise _pipeline_error(exc)

    frames = sorted({r.get("frame") for r in density_rows if r.get("frame") is not None})
    frames = frames[-limit:]
    frame_set = set(frames)

    points = [
        {
            "frame": r.get("frame"),
            "zone": r.get("zone"),
            "people": r.get("people"),
            "density": r.get("density"),
            "capacity": r.get("capacity"),
            "capacityUsage": r.get("capacity_usage"),
            "densityLevel": r.get("density_level"),
            "capacityStatus": r.get("capacity_status"),
        }
        for r in density_rows
        if r.get("frame") in frame_set
    ]

    flow_points: List[Dict[str, Any]] = []
    try:
        for r in read_csv("zone_flow.csv", stage="python backend/zone_flow.py"):
            flow_points.append(
                {
                    "minute": r.get("minute"),
                    "zone": r.get("zone"),
                    "entriesPerMinute": r.get("entries_per_minute"),
                    "exitsPerMinute": r.get("exits_per_minute"),
                    "netFlowPerMinute": r.get("net_flow_per_minute"),
                    "flowStatus": r.get("flow_status"),
                }
            )
    except PipelineNotRun:
        flow_points = []

    return {"density": points, "flow": flow_points}


# ------------------------------------------------------------------
# VIDEO ANALYSIS  (upload -> existing Python pipeline -> existing CSVs)
# ------------------------------------------------------------------
@router.post("/video/upload")
async def video_upload(
    file: UploadFile = File(...),
    mode: str = Form(csv_utils.SINGLE_CAMERA),
) -> Dict[str, Any]:
    selected_mode = (mode or csv_utils.SINGLE_CAMERA).upper()
    if selected_mode not in VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_MODE",
                "message": f"mode must be one of {', '.join(VALID_MODES)}.",
            },
        )

    if video_jobs.safe_extension(file.filename or "") is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "UNSUPPORTED_FILE",
                "message": "Unsupported file type. Use .mp4, .avi, .mov or .mkv.",
            },
        )

    content_type = (file.content_type or "").lower()
    if content_type and not content_type.startswith(video_jobs.ALLOWED_MIME_PREFIXES):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "UNSUPPORTED_MIME",
                "message": f"Unsupported content type: {content_type}",
            },
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=400,
            detail={"error": "EMPTY_FILE", "message": "The selected file is empty."},
        )
    if len(data) > video_jobs.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "FILE_TOO_LARGE",
                "message": "Video exceeds the 512 MB upload limit.",
            },
        )

    try:
        job = video_jobs.create_job(file.filename or "video.mp4", data, selected_mode)
    except video_jobs.JobBusy as busy:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ANALYSIS_IN_PROGRESS",
                "job_id": busy.job_id,
                "message": "An analysis is already in progress. Wait for it to finish.",
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "UNSUPPORTED_FILE", "message": str(exc)},
        )

    return {
        "job_id": job.job_id,
        "filename": job.filename,
        "status": job.status,
        "mode": job.mode,
    }


@router.get("/video/status/{job_id}")
def video_status(job_id: str) -> Dict[str, Any]:
    job = video_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "JOB_NOT_FOUND", "message": "Unknown analysis job."},
        )
    return job.public()


@router.get("/video/active")
def video_active() -> Dict[str, Any]:
    job = video_jobs.active_job()
    return {"active": job.public() if job else None}


# ------------------------------------------------------------------
# SOURCE  (which artifacts the read-only endpoints are serving)
# ------------------------------------------------------------------
def _source_payload() -> Dict[str, Any]:
    src = csv_utils.source()
    digital_twin_available = os.path.isfile(video_jobs.VENUE_ZONES_PATH) or os.path.isfile(
        os.path.join(csv_utils.VIDEOS_DIR, "zone_tracking.csv")
    )
    return {
        "mode": src["mode"],
        "label": src["label"],
        "jobId": src["job_id"],
        "modes": list(VALID_MODES),
        "digitalTwinAvailable": digital_twin_available,
        # Uploading a new video always requires videos/zones.json in
        # DIGITAL_TWIN mode; SINGLE_CAMERA builds its own job region.
        "digitalTwinZonesConfigured": os.path.isfile(video_jobs.VENUE_ZONES_PATH),
    }


@router.get("/source")
def get_source() -> Dict[str, Any]:
    return _source_payload()


class SourceSelection(BaseModel):
    mode: str
    job_id: Optional[str] = None


@router.post("/source")
def select_source(selection: SourceSelection) -> Dict[str, Any]:
    """Point the read-only endpoints at the configured venue or at a job."""
    mode = (selection.mode or "").upper()
    if mode not in VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_MODE",
                "message": f"mode must be one of {', '.join(VALID_MODES)}.",
            },
        )

    if mode == csv_utils.DIGITAL_TWIN:
        csv_utils.reset_source()
        return _source_payload()

    job_id = selection.job_id or csv_utils.source().get("job_id")
    job = video_jobs.get_job(str(job_id)) if job_id else None
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "JOB_NOT_FOUND",
                "message": "Single camera mode needs a completed analysis job.",
            },
        )
    if job.status != "completed":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "JOB_NOT_COMPLETED",
                "message": "That analysis has not completed yet.",
            },
        )
    csv_utils.set_source(
        csv_utils.SINGLE_CAMERA, job.job_dir, job.job_id, video_jobs.config_path_for(job)
    )
    return _source_payload()


# ------------------------------------------------------------------
# VIDEO RESULT  (only values the pipeline actually produced for this job)
# ------------------------------------------------------------------
def _first(rows: Optional[List[Dict[str, Any]]], key: str, reverse: bool) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    scored = [r for r in rows if isinstance(r.get(key), (int, float))]
    if not scored:
        return None
    return sorted(scored, key=lambda r: r[key], reverse=reverse)[0]


@router.get("/video/result/{job_id}")
def video_result(job_id: str) -> Dict[str, Any]:
    job = video_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "JOB_NOT_FOUND", "message": "Unknown analysis job."},
        )
    if job.status != "completed":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "JOB_NOT_COMPLETED",
                "message": "Results are available once the analysis completes.",
                "status": job.status,
                "error_detail": job.error,
            },
        )

    directory = job.job_dir
    tracking = csv_utils.read_csv_in(directory, "zone_tracking.csv")
    density = csv_utils.read_csv_in(directory, "density_analysis.csv")
    flow = csv_utils.read_csv_in(directory, "zone_flow.csv")
    congestion = csv_utils.read_csv_in(directory, "zone_congestion.csv")
    warnings_rows = csv_utils.read_csv_in(directory, "early_warning.csv")
    predictions_rows = csv_utils.read_csv_in(directory, "crowd_prediction.csv")

    in_zone = [r for r in (tracking or []) if r.get("zone") not in (None, "Outside")]

    unique_tracks: Optional[int] = None
    latest_frame: Optional[int] = None
    people_latest_frame: Optional[int] = None
    if in_zone:
        ids = {r.get("track_id") for r in in_zone if r.get("track_id") is not None}
        unique_tracks = len(ids) or None
        frames = [r.get("frame") for r in in_zone if isinstance(r.get("frame"), int)]
        if frames:
            latest_frame = max(frames)
            people_latest_frame = sum(1 for r in in_zone if r.get("frame") == latest_frame)

    latest_density = latest_per_zone(density, order_key="frame") if density else []
    active_zones: Optional[int] = None
    if latest_density:
        active_zones = sum(1 for r in latest_density if (r.get("people") or 0) > 0)
    elif in_zone and latest_frame is not None:
        active_zones = len({r.get("zone") for r in in_zone if r.get("frame") == latest_frame})

    top_density = _first(latest_density, "density", reverse=True)
    top_risk = _first(warnings_rows, "risk_score", reverse=True)
    soonest = _first(predictions_rows, "minutes_to_capacity", reverse=False)

    # A prediction is reported only when crowd_prediction.py actually produced
    # one. Otherwise the frontend shows "Insufficient history" — never a guess.
    prediction: Dict[str, Any] = {
        "available": False,
        "reason": "Insufficient history",
        "zone": None,
        "minutesToCapacity": None,
        "trend": None,
        "statement": None,
    }
    if soonest is not None:
        prediction = {
            "available": True,
            "reason": None,
            "zone": soonest.get("zone"),
            "minutesToCapacity": soonest.get("minutes_to_capacity"),
            "trend": soonest.get("trend"),
            "statement": soonest.get("prediction"),
        }
    elif predictions_rows:
        row = predictions_rows[0]
        prediction.update(
            {
                "zone": row.get("zone"),
                "trend": row.get("trend"),
                "statement": row.get("prediction"),
                "reason": row.get("prediction") or "Insufficient history",
            }
        )

    return {
        "job_id": job.job_id,
        "filename": job.filename,
        "mode": job.mode,
        "status": job.status,
        "isActiveSource": csv_utils.source().get("job_id") == job.job_id,
        "summary": {
            "peopleTracked": unique_tracks,
            "peopleLatestFrame": people_latest_frame,
            "latestFrame": latest_frame,
            "activeZones": active_zones,
            "highestDensityZone": top_density.get("zone") if top_density else None,
            "highestDensity": top_density.get("density") if top_density else None,
            "densityLevel": top_density.get("density_level") if top_density else None,
            "highestRiskZone": top_risk.get("zone") if top_risk else None,
            "highestRiskScore": top_risk.get("risk_score") if top_risk else None,
            "highestRiskLevel": top_risk.get("risk_level") if top_risk else None,
        },
        "prediction": prediction,
        "artifacts": {
            "zone_tracking.csv": tracking is not None,
            "density_analysis.csv": density is not None,
            "zone_flow.csv": flow is not None,
            "zone_congestion.csv": congestion is not None,
            "early_warning.csv": warnings_rows is not None,
            "crowd_prediction.csv": predictions_rows is not None,
        },
        "zones": {
            "density": latest_density,
            "flow": latest_per_zone(flow, order_key="minute") if flow else [],
            "congestion": latest_per_zone(congestion, order_key="frame") if congestion else [],
            "warnings": warnings_rows or [],
            "predictions": predictions_rows or [],
        },
    }
