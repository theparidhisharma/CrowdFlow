"""Thin helpers to read the CSV outputs produced by the existing pipeline.

No analysis happens here. Values are read as-is from the CSVs written by
tracker.py / zone_analysis.py / density_analysis.py / zone_flow.py /
congestion.py / zone_congestion.py / early_warning.py / crowd_prediction.py.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List, Optional

# Project root = two levels above backend/api/
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

VIDEOS_DIR = os.path.join(PROJECT_ROOT, "videos")
JOB_DATA_DIR = os.path.join(VIDEOS_DIR, "job_data")
VENUE_CONFIG_PATH = os.path.join(PROJECT_ROOT, "backend", "venue_config.json")

# ------------------------------------------------------------------
# ACTIVE DATA SOURCE
#
# DIGITAL_TWIN  -> configured venue artifacts in videos/
# SINGLE_CAMERA -> artifacts of one completed video job in
#                  videos/job_data/<job_id>/
#
# Switching the source never moves or overwrites files: the data endpoints
# simply read from a different directory.
# ------------------------------------------------------------------

DIGITAL_TWIN = "DIGITAL_TWIN"
SINGLE_CAMERA = "SINGLE_CAMERA"

_source: Dict[str, Any] = {
    "mode": DIGITAL_TWIN,
    "dir": VIDEOS_DIR,
    "job_id": None,
    "label": "Digital Twin",
    "config": VENUE_CONFIG_PATH,
}


def set_source(
    mode: str,
    directory: str,
    job_id: Optional[str] = None,
    config_path: Optional[str] = None,
) -> None:
    _source.update(
        {
            "mode": mode,
            "dir": directory,
            "job_id": job_id,
            "label": "Single Camera" if mode == SINGLE_CAMERA else "Digital Twin",
            "config": config_path or VENUE_CONFIG_PATH,
        }
    )


def reset_source() -> None:
    set_source(DIGITAL_TWIN, VIDEOS_DIR, None, VENUE_CONFIG_PATH)


def source() -> Dict[str, Any]:
    return dict(_source)


def data_dir() -> str:
    return str(_source["dir"])


class PipelineNotRun(Exception):
    """Raised when an expected pipeline output CSV does not exist."""

    def __init__(self, filename: str, stage: str):
        self.filename = filename
        self.stage = stage
        super().__init__(
            f"{filename} not found. Run the existing pipeline stage first: {stage}"
        )


def video_path(filename: str) -> str:
    return os.path.join(data_dir(), filename)



def exists(filename: str) -> bool:
    return os.path.isfile(video_path(filename))


def coerce(value: str) -> Any:
    """Convert a CSV cell into int / float / bool / None where obvious."""
    if value is None:
        return None
    text = value.strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    if text in {"True", "False"}:
        return text == "True"
    return text


def read_csv(filename: str, stage: str) -> List[Dict[str, Any]]:
    path = video_path(filename)
    if not os.path.isfile(path):
        rel = os.path.relpath(path, PROJECT_ROOT).replace(os.sep, "/")
        raise PipelineNotRun(rel, stage)

    with open(path, "r", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: coerce(v) for k, v in row.items() if k is not None} for row in reader]


def read_csv_optional(filename: str) -> Optional[List[Dict[str, Any]]]:
    try:
        return read_csv(filename, stage="")
    except PipelineNotRun:
        return None


def read_csv_in(directory: str, filename: str) -> Optional[List[Dict[str, Any]]]:
    """Read a pipeline CSV from an explicit directory (e.g. a job directory).

    Returns None when the file was never produced — callers surface that as
    "N/A" instead of substituting a value.
    """
    path = os.path.join(directory, filename)
    if not os.path.isfile(path):
        return None
    with open(path, "r", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: coerce(v) for k, v in row.items() if k is not None} for row in reader]


def latest_per_zone(
    rows: List[Dict[str, Any]],
    order_key: str,
    zone_key: str = "zone",
) -> List[Dict[str, Any]]:
    """Last row for each zone, ordered by `order_key` (frame / minute)."""
    latest: Dict[Any, Dict[str, Any]] = {}
    for row in rows:
        zone = row.get(zone_key)
        if zone is None:
            continue
        current = latest.get(zone)
        if current is None:
            latest[zone] = row
            continue
        new_order = row.get(order_key)
        old_order = current.get(order_key)
        if new_order is None or old_order is None:
            latest[zone] = row
        elif new_order >= old_order:
            latest[zone] = row
    return list(latest.values())


def load_venue_config() -> Dict[str, Any]:
    """Configuration of the ACTIVE source.

    Digital Twin  -> backend/venue_config.json (physical area + capacity).
    Single Camera -> the job's camera configuration (no invented physical area).
    """
    path = str(_source.get("config") or VENUE_CONFIG_PATH)
    if not os.path.isfile(path):
        path = VENUE_CONFIG_PATH
    with open(path, "r") as handle:
        return json.load(handle)

