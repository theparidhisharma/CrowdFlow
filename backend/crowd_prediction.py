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
import json
import math
import cv2
import pandas as pd
import numpy as np


# ==========================================
# FILES
# ==========================================

# Optional override used by the API job runner; manual runs are unchanged.


TRACKING_PATH = _out("zone_tracking.csv")



OUTPUT_PATH = _out("crowd_prediction.csv")


# ==========================================
# SETTINGS
# ==========================================

WINDOW_SECONDS = 5

SMOOTHING_WINDOWS = 3

MIN_WINDOWS_FOR_PREDICTION = 6

MAX_REASONABLE_CHANGE_PER_MINUTE = 20


# ==========================================
# GET ACTUAL FPS
# ==========================================

cap = cv2.VideoCapture(VIDEO_PATH)

if not cap.isOpened():

    raise RuntimeError(
        f"Could not open video: {VIDEO_PATH}"
    )


fps = cap.get(
    cv2.CAP_PROP_FPS
)

cap.release()


if fps <= 0:

    raise RuntimeError(
        "Could not read video FPS."
    )


print(
    f"Video FPS: {fps:.2f}"
)


# ==========================================
# LOAD CONFIG
# ==========================================

print("Loading venue configuration...")

with open(CONFIG_PATH, "r") as file:

    config = json.load(file)


zones_config = config["zones"]


# ==========================================
# LOAD TRACKING
# ==========================================

print("Loading tracking data...")

df = pd.read_csv(
    TRACKING_PATH
)


# Ignore outside zone

df = df[
    df["zone"] != "Outside"
].copy()


# ==========================================
# FRAME → TIME
# ==========================================

df["time_seconds"] = (
    df["frame"] / fps
)


# ==========================================
# TIME WINDOWS
# ==========================================

df["time_window"] = (
    df["time_seconds"]
    // WINDOW_SECONDS
).astype(int)


# ==========================================
# OCCUPANCY
# ==========================================

occupancy = (
    df.groupby(
        [
            "time_window",
            "zone"
        ]
    )["person_id"]
    .nunique()
    .reset_index(
        name="people"
    )
)


occupancy["time_seconds"] = (
    occupancy["time_window"]
    * WINDOW_SECONDS
)


# ==========================================
# RESULTS
# ==========================================

results = []


# ==========================================
# EACH ZONE
# ==========================================

for zone_name, zone_info in zones_config.items():

    zone_data = occupancy[
        occupancy["zone"] == zone_name
    ].copy()


    # --------------------------------------
    # No data
    # --------------------------------------

    if len(zone_data) == 0:

        results.append({

            "zone": zone_name,

            "current_people": 0,

            "trend_people_per_minute": 0,

            "predicted_people_5_min": None,

            "predicted_people_10_min": None,

            "capacity": zone_info.get(
                "capacity",
                0
            ),

            "prediction": "NO DATA"

        })

        continue


    # ======================================
    # CURRENT OCCUPANCY
    # ======================================

    current_people = int(
        zone_data.iloc[-1]["people"]
    )


    # ======================================
    # SMOOTH OCCUPANCY
    # ======================================

    zone_data["smoothed_people"] = (
        zone_data["people"]
        .rolling(
            window=SMOOTHING_WINDOWS,
            min_periods=1
        )
        .mean()
    )


    # ======================================
    # CHECK HISTORY
    # ======================================

    enough_history = (
        len(zone_data)
        >= MIN_WINDOWS_FOR_PREDICTION
    )


    # ======================================
    # TREND
    # ======================================

    if enough_history:

        x = zone_data[
            "time_seconds"
        ].to_numpy()

        y = zone_data[
            "smoothed_people"
        ].to_numpy()


        slope, intercept = np.polyfit(
            x,
            y,
            1
        )


        people_per_minute = (
            slope * 60
        )


        # ----------------------------------
        # Prevent extreme unstable slopes
        # ----------------------------------

        people_per_minute = max(
            -MAX_REASONABLE_CHANGE_PER_MINUTE,
            min(
                people_per_minute,
                MAX_REASONABLE_CHANGE_PER_MINUTE
            )
        )


    else:

        people_per_minute = 0


    # ======================================
    # CAPACITY
    # ======================================

    capacity = float(
        zone_info.get(
            "capacity",
            0
        )
    )


    # ======================================
    # PREDICTION
    # ======================================

    if enough_history:

        predicted_5 = (
            current_people
            +
            people_per_minute * 5
        )


        predicted_10 = (
            current_people
            +
            people_per_minute * 10
        )


        predicted_5 = max(
            0,
            predicted_5
        )


        predicted_10 = max(
            0,
            predicted_10
        )


    else:

        predicted_5 = None

        predicted_10 = None


    # ======================================
    # TIME TO CAPACITY
    # ======================================

    if (
        enough_history
        and people_per_minute > 0
        and current_people < capacity
    ):

        remaining = (
            capacity
            -
            current_people
        )


        minutes_to_capacity = (
            remaining
            /
            people_per_minute
        )


    elif (
        current_people >= capacity
        and capacity > 0
    ):

        minutes_to_capacity = 0


    else:

        minutes_to_capacity = math.inf


    # ======================================
    # TREND CLASSIFICATION
    # ======================================

    if not enough_history:

        trend = "INSUFFICIENT HISTORY"

    elif people_per_minute >= 5:

        trend = "STRONGLY INCREASING"

    elif people_per_minute >= 1:

        trend = "INCREASING"

    elif people_per_minute <= -5:

        trend = "STRONGLY DECREASING"

    elif people_per_minute <= -1:

        trend = "DECREASING"

    else:

        trend = "STABLE"


    # ======================================
    # PREDICTION LABEL
    # ======================================

    if not enough_history:

        prediction = (
            "INSUFFICIENT HISTORY"
        )


    elif capacity > 0 and current_people >= capacity:

        prediction = (
            "CAPACITY REACHED"
        )



    elif (
        minutes_to_capacity != math.inf
        and minutes_to_capacity <= 5
    ):

        prediction = (
            "CONGESTION EXPECTED "
            "WITHIN 5 MINUTES"
        )


    elif (
        minutes_to_capacity != math.inf
        and minutes_to_capacity <= 10
    ):

        prediction = (
            "CONGESTION DEVELOPING"
        )


    elif people_per_minute >= 2:

        prediction = (
            "CROWD ACCUMULATING"
        )


    elif people_per_minute <= -2:

        prediction = (
            "ZONE CLEARING"
        )


    else:

        prediction = (
            "NO IMMEDIATE RISK"
        )


    # ======================================
    # SAVE
    # ======================================

    results.append({

        "zone": zone_name,

        "current_people": current_people,

        "trend_people_per_minute":
            people_per_minute,

        "predicted_people_5_min":
            predicted_5,

        "predicted_people_10_min":
            predicted_10,

        "capacity":
            capacity,

        "minutes_to_capacity":
            (
                None
                if minutes_to_capacity == math.inf
                else minutes_to_capacity
            ),

        "trend":
            trend,

        "prediction":
            prediction

    })


# ==========================================
# DATAFRAME
# ==========================================

results_df = pd.DataFrame(
    results
)


# ==========================================
# SAVE
# ==========================================

results_df.to_csv(
    OUTPUT_PATH,
    index=False
)


# ==========================================
# PRINT
# ==========================================

print()
print("--------------------------------")
print("CROWDFLOW TREND PREDICTION")
print("--------------------------------")


for _, row in results_df.iterrows():

    print()

    print(
        f"ZONE: {row['zone']}"
    )

    print(
        f"Current people: "
        f"{int(row['current_people'])}"
    )

    print(
        f"Trend: "
        f"{row['trend']}"
    )

    print(
        f"Rate: "
        f"{row['trend_people_per_minute']:+.2f} "
        f"people/min"
    )


    if pd.isna(
        row["predicted_people_5_min"]
    ):

        print(
            "Predicted in 5 min: "
            "N/A"
        )

        print(
            "Predicted in 10 min: "
            "N/A"
        )

    else:

        print(
            f"Predicted in 5 min: "
            f"{row['predicted_people_5_min']:.1f}"
        )

        print(
            f"Predicted in 10 min: "
            f"{row['predicted_people_10_min']:.1f}"
        )


    if pd.isna(
        row["minutes_to_capacity"]
    ):

        print(
            "Time to capacity: N/A"
        )

    else:

        print(
            f"Time to capacity: "
            f"{row['minutes_to_capacity']:.1f} min"
        )


    print(
        f"Prediction: "
        f"{row['prediction']}"
    )


# ==========================================
# COMPLETE
# ==========================================

print()
print("--------------------------------")
print("TREND PREDICTION COMPLETE")
print("--------------------------------")

print(
    f"Output: {OUTPUT_PATH}"
)

print("--------------------------------")