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

import pandas as pd
import numpy as np


# ==========================================
# FILE SETTINGS
# ==========================================

INPUT_PATH = _out("zone_tracking.csv")

OUTPUT_PATH = _out("flow_analysis.csv")


# ==========================================
# PARAMETERS
# ==========================================

# Number of frames between position comparisons.
# 5 is useful for smoother movement estimation.
FRAME_STEP = 5

# Minimum movement in pixels to consider
# someone actually moving.
MIN_MOVEMENT_PIXELS = 5


# ==========================================
# LOAD TRACKING DATA
# ==========================================

print("Loading zone tracking data...")

df = pd.read_csv(INPUT_PATH)

print(
    f"Tracking records: {len(df)}"
)

print(
    f"Unique people: "
    f"{df['person_id'].nunique()}"
)


# ==========================================
# SORT TRACK HISTORY
# ==========================================

df = df.sort_values(
    [
        "person_id",
        "frame"
    ]
).reset_index(drop=True)


# ==========================================
# CALCULATE POSITION CHANGE
# ==========================================

df["previous_x"] = (
    df.groupby("person_id")["center_x"]
    .shift(FRAME_STEP)
)

df["previous_y"] = (
    df.groupby("person_id")["center_y"]
    .shift(FRAME_STEP)
)


# ==========================================
# MOVEMENT VECTOR
# ==========================================

df["dx"] = (
    df["center_x"]
    - df["previous_x"]
)

df["dy"] = (
    df["center_y"]
    - df["previous_y"]
)


# ==========================================
# MOVEMENT DISTANCE
# ==========================================

df["movement_distance"] = np.sqrt(
    df["dx"] ** 2
    +
    df["dy"] ** 2
)


# ==========================================
# MOVEMENT DIRECTION
# ==========================================

def get_direction(row):

    dx = row["dx"]
    dy = row["dy"]

    if pd.isna(dx) or pd.isna(dy):

        return "UNKNOWN"


    distance = np.sqrt(
        dx ** 2 + dy ** 2
    )


    if distance < MIN_MOVEMENT_PIXELS:

        return "STATIONARY"


    # --------------------------------------
    # Determine dominant direction
    # --------------------------------------

    if abs(dx) > abs(dy):

        if dx > 0:
            return "RIGHT"

        return "LEFT"


    else:

        if dy > 0:
            return "DOWN"

        return "UP"


df["direction"] = df.apply(
    get_direction,
    axis=1
)


# ==========================================
# SPEED IN PIXELS / FRAME
# ==========================================

df["speed_pixels_per_frame"] = (
    df["movement_distance"]
    / FRAME_STEP
)


# ==========================================
# ZONE FLOW SUMMARY
# ==========================================

flow = (
    df[
        df["zone"] != "Outside"
    ]
    .groupby(
        [
            "frame",
            "zone",
            "direction"
        ]
    )
    .size()
    .reset_index(
        name="people"
    )
)


# ==========================================
# PIVOT DIRECTIONS
# ==========================================

direction_table = (
    flow.pivot_table(
        index=[
            "frame",
            "zone"
        ],
        columns="direction",
        values="people",
        fill_value=0
    )
    .reset_index()
)


# ==========================================
# ENSURE ALL DIRECTIONS EXIST
# ==========================================

for direction in [
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "STATIONARY",
    "UNKNOWN"
]:

    if direction not in direction_table.columns:

        direction_table[direction] = 0


# ==========================================
# TOTAL MOVING PEOPLE
# ==========================================

direction_table["moving_people"] = (
    direction_table["UP"]
    + direction_table["DOWN"]
    + direction_table["LEFT"]
    + direction_table["RIGHT"]
)


# ==========================================
# NET HORIZONTAL FLOW
# ==========================================

direction_table["horizontal_flow"] = (
    direction_table["RIGHT"]
    -
    direction_table["LEFT"]
)


# ==========================================
# NET VERTICAL FLOW
# ==========================================

direction_table["vertical_flow"] = (
    direction_table["DOWN"]
    -
    direction_table["UP"]
)


# ==========================================
# DOMINANT FLOW
# ==========================================

def dominant_flow(row):

    values = {
        "UP": row["UP"],
        "DOWN": row["DOWN"],
        "LEFT": row["LEFT"],
        "RIGHT": row["RIGHT"]
    }

    direction = max(
        values,
        key=values.get
    )

    if values[direction] == 0:

        return "NO CLEAR FLOW"

    return direction


direction_table["dominant_flow"] = (
    direction_table.apply(
        dominant_flow,
        axis=1
    )
)


# ==========================================
# SAVE
# ==========================================

direction_table.to_csv(
    OUTPUT_PATH,
    index=False
)


# ==========================================
# LATEST FRAME
# ==========================================

latest_frame = direction_table[
    "frame"
].max()


latest = direction_table[
    direction_table["frame"]
    == latest_frame
]


print()
print("--------------------------------")
print("CURRENT CROWD FLOW")
print("--------------------------------")


for _, row in latest.iterrows():

    print(
        f"{row['zone']}: "
        f"{int(row['moving_people'])} moving "
        f"| UP {int(row['UP'])} "
        f"| DOWN {int(row['DOWN'])} "
        f"| LEFT {int(row['LEFT'])} "
        f"| RIGHT {int(row['RIGHT'])} "
        f"| Dominant: "
        f"{row['dominant_flow']}"
    )


# ==========================================
# COMPLETE
# ==========================================

print()
print("--------------------------------")
print("FLOW ANALYSIS COMPLETE")
print("--------------------------------")

print(
    f"Output: {OUTPUT_PATH}"
)

print("--------------------------------")