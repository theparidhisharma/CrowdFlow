"""Shared path resolution for the existing CrowdFlow pipeline scripts.

Nothing about the analysis changes here. This module only decides *where* the
existing scripts read and write, so that:

  * a manual run (`python backend/tracker.py`) behaves exactly as before —
    inputs and outputs live in `videos/`, zones in `videos/zones.json`,
    configuration in `backend/venue_config.json`;
  * an API video job can point the same scripts at a per-job directory
    (`videos/job_data/<job_id>/`) without ever overwriting the configured
    venue zones, the venue configuration, or the shipped demo CSVs.

Environment overrides (all optional):

  CROWDFLOW_VIDEO    input video path        (default videos/crowd.mp4)
  CROWDFLOW_OUT_DIR  artifact directory      (default videos)
  CROWDFLOW_ZONES    zone polygons json      (default <OUT_DIR>/zones.json)
  CROWDFLOW_CONFIG   venue configuration     (default backend/venue_config.json)
"""

from __future__ import annotations

import os

VIDEO_PATH = os.environ.get("CROWDFLOW_VIDEO") or "videos/crowd.mp4"

OUT_DIR = os.environ.get("CROWDFLOW_OUT_DIR") or "videos"

CONFIG_PATH = os.environ.get("CROWDFLOW_CONFIG") or "backend/venue_config.json"


def out(name: str) -> str:
    """Path of a pipeline artifact inside the active output directory."""
    os.makedirs(OUT_DIR, exist_ok=True)
    return os.path.join(OUT_DIR, name)


ZONES_PATH = os.environ.get("CROWDFLOW_ZONES") or os.path.join(OUT_DIR, "zones.json")

# Written by tracker.py so downstream job tooling knows the real processed
# frame size / fps without re-opening the video.
META_PATH = os.path.join(OUT_DIR, "video_meta.json")
