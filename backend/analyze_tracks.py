import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from paths import (  # noqa: E402
    VIDEO_PATH,
    CONFIG_PATH,
    ZONES_PATH,
    META_PATH,
    out as _out,
)

import os
import pandas as pd
import numpy as np
import cv2


# ==========================================
# 1. FILE SETTINGS
# ==========================================

CSV_PATH = _out("tracks.csv")

OUTPUT_VIDEO = _out("crowd_flow.mp4")

# Optional override used by the API job runner; manual runs are unchanged.



# ==========================================
# 2. LOAD TRACKING DATA
# ==========================================

print("Loading tracking data...")

df = pd.read_csv(CSV_PATH)

print(f"Tracking records: {len(df)}")

print(
    f"Unique people: "
    f"{df['person_id'].nunique()}"
)

print(
    f"Frames: "
    f"{df['frame'].min()} → {df['frame'].max()}"
)


# ==========================================
# 3. SORT DATA
# ==========================================

df = df.sort_values(
    ["person_id", "frame"]
).reset_index(drop=True)


# ==========================================
# 4. CALCULATE MOVEMENT
# ==========================================

df["previous_x"] = df.groupby(
    "person_id"
)["center_x"].shift(1)

df["previous_y"] = df.groupby(
    "person_id"
)["center_y"].shift(1)


# Distance travelled between frames

df["distance"] = np.sqrt(
    (df["center_x"] - df["previous_x"]) ** 2
    +
    (df["center_y"] - df["previous_y"]) ** 2
)


# ==========================================
# 5. CALCULATE SPEED
# ==========================================

# Pixel movement per frame

df["speed"] = (
    df["distance"]
    .fillna(0)
)


# ==========================================
# 6. CALCULATE DIRECTION
# ==========================================

df["dx"] = (
    df["center_x"]
    - df["previous_x"]
).fillna(0)

df["dy"] = (
    df["center_y"]
    - df["previous_y"]
).fillna(0)


def get_direction(row):

    dx = row["dx"]
    dy = row["dy"]

    threshold = 2

    if abs(dx) < threshold and abs(dy) < threshold:
        return "Stationary"

    if abs(dx) > abs(dy):

        if dx > 0:
            return "Right"

        return "Left"

    else:

        if dy > 0:
            return "Down"

        return "Up"


df["direction"] = df.apply(
    get_direction,
    axis=1
)


# ==========================================
# 7. DEFINE CROWD ZONES
# ==========================================

# Get video dimensions

cap = cv2.VideoCapture(
    VIDEO_PATH
)

if not cap.isOpened():

    raise RuntimeError(
        f"Could not open {VIDEO_PATH}"
    )


width = int(
    cap.get(cv2.CAP_PROP_FRAME_WIDTH)
)

height = int(
    cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
)

cap.release()


# Our analysis coordinates are from the
# processed 1920-wide video.

MAX_WIDTH = 1920

if width > MAX_WIDTH:

    scale = MAX_WIDTH / width

    width = MAX_WIDTH
    height = int(height * scale)


# Divide screen into a 4 × 3 grid

COLS = 4
ROWS = 3


zone_width = width / COLS
zone_height = height / ROWS


def get_zone(x, y):

    col = int(x / zone_width)
    row = int(y / zone_height)

    col = min(col, COLS - 1)
    row = min(row, ROWS - 1)

    zone_number = (
        row * COLS + col + 1
    )

    return f"Zone {zone_number}"


df["zone"] = df.apply(
    lambda row: get_zone(
        row["center_x"],
        row["center_y"]
    ),
    axis=1
)


# ==========================================
# 8. SAVE ENHANCED TRACKING DATA
# ==========================================

OUTPUT_CSV = _out("crowd_analysis.csv")

df.to_csv(
    OUTPUT_CSV,
    index=False
)


# ==========================================
# 9. CROWD DENSITY
# ==========================================

latest_frame = df["frame"].max()

latest_data = df[
    df["frame"] == latest_frame
]


density = (
    latest_data
    .groupby("zone")
    .size()
    .sort_values(
        ascending=False
    )
)


print()
print("--------------------------------")
print("CURRENT CROWD DENSITY")
print("--------------------------------")


for zone, count in density.items():

    print(
        f"{zone}: {count} people"
    )


# ==========================================
# 10. FIND MOST CROWDED ZONE
# ==========================================

if len(density) > 0:

    busiest_zone = density.index[0]

    busiest_count = density.iloc[0]

    print()
    print(
        f"BUSIEST ZONE: "
        f"{busiest_zone}"
    )

    print(
        f"PEOPLE: "
        f"{busiest_count}"
    )


# ==========================================
# 11. OVERALL MOVEMENT
# ==========================================

average_speed = df["speed"].mean()

moving_people = df[
    df["speed"] > 2
]


print()
print("--------------------------------")
print("CROWD FLOW")
print("--------------------------------")

print(
    f"Average movement: "
    f"{average_speed:.2f} pixels/frame"
)

print(
    f"Moving observations: "
    f"{len(moving_people)}"
)


# ==========================================
# 12. DIRECTION DISTRIBUTION
# ==========================================

direction_counts = (
    df["direction"]
    .value_counts()
)


print()
print("--------------------------------")
print("MOVEMENT DIRECTIONS")
print("--------------------------------")


for direction, count in (
    direction_counts.items()
):

    print(
        f"{direction}: {count}"
    )


# ==========================================
# 13. FINISHED
# ==========================================

print()
print("--------------------------------")
print("ANALYSIS COMPLETE")
print("--------------------------------")

print(
    f"Detailed data: {OUTPUT_CSV}"
)