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
import cv2


# ==========================================
# FILE SETTINGS
# ==========================================

INPUT_PATH = _out("zone_tracking.csv")

# Optional override used by the API job runner; manual runs are unchanged.


OUTPUT_PATH = _out("zone_flow.csv")

EVENTS_OUTPUT_PATH = _out("zone_flow_events.csv")


# ==========================================
# STABILITY SETTINGS
# ==========================================

# A zone change must remain for this many
# observations before we accept it as real.

CONFIRM_OBSERVATIONS = 5


# If the tracker disappears for more than
# this many frames, don't assume the next
# observation is a genuine zone transition.

MAX_FRAME_GAP = 15


# ==========================================
# LOAD VIDEO FPS
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
# LOAD TRACKING DATA
# ==========================================

print()
print("Loading zone tracking data...")

df = pd.read_csv(
    INPUT_PATH
)

print(
    f"Tracking records: {len(df)}"
)


# ==========================================
# SORT
# ==========================================

df = df.sort_values(
    [
        "person_id",
        "frame"
    ]
).reset_index(
    drop=True
)


# ==========================================
# STABLE TRANSITION DETECTION
# ==========================================

events = []


for person_id, person_data in df.groupby(
    "person_id"
):

    person_data = person_data.sort_values(
        "frame"
    ).reset_index(
        drop=True
    )


    # --------------------------------------
    # Current confirmed zone
    # --------------------------------------

    confirmed_zone = None


    # --------------------------------------
    # Candidate new zone
    # --------------------------------------

    candidate_zone = None

    candidate_count = 0

    candidate_start_frame = None


    # --------------------------------------
    # Process observations
    # --------------------------------------

    previous_frame = None


    for _, row in person_data.iterrows():

        frame = int(
            row["frame"]
        )

        current_zone = row["zone"]


        # ==================================
        # CHECK FRAME GAP
        # ==================================

        if previous_frame is not None:

            frame_gap = (
                frame
                -
                previous_frame
            )

            if frame_gap > MAX_FRAME_GAP:

                # Tracking disappeared.
                #
                # We do NOT create an EXIT.
                #
                # Reset candidate because we
                # don't know what happened.

                candidate_zone = None

                candidate_count = 0

                candidate_start_frame = None


        previous_frame = frame


        # ==================================
        # FIRST OBSERVATION
        # ==================================

        if confirmed_zone is None:

            confirmed_zone = current_zone

            continue


        # ==================================
        # SAME AS CONFIRMED ZONE
        # ==================================

        if current_zone == confirmed_zone:

            candidate_zone = None

            candidate_count = 0

            candidate_start_frame = None

            continue


        # ==================================
        # NEW CANDIDATE ZONE
        # ==================================

        if current_zone != candidate_zone:

            candidate_zone = current_zone

            candidate_count = 1

            candidate_start_frame = frame

            continue


        # ==================================
        # SAME CANDIDATE CONTINUES
        # ==================================

        candidate_count += 1


        # ==================================
        # CONFIRM TRANSITION
        # ==================================

        if (
            candidate_count
            >= CONFIRM_OBSERVATIONS
        ):

            old_zone = confirmed_zone

            new_zone = candidate_zone


            # ==================================
            # EXIT OLD ZONE
            # ==================================

            if old_zone != "Outside":

                events.append({

                    "frame": candidate_start_frame,

                    "person_id": person_id,

                    "zone": old_zone,

                    "event": "EXIT",

                    "from_zone": old_zone,

                    "to_zone": new_zone

                })


            # ==================================
            # ENTER NEW ZONE
            # ==================================

            if new_zone != "Outside":

                events.append({

                    "frame": candidate_start_frame,

                    "person_id": person_id,

                    "zone": new_zone,

                    "event": "ENTER",

                    "from_zone": old_zone,

                    "to_zone": new_zone

                })


            # ==================================
            # UPDATE CONFIRMED ZONE
            # ==================================

            confirmed_zone = new_zone

            candidate_zone = None

            candidate_count = 0

            candidate_start_frame = None


# ==========================================
# CREATE EVENTS DATAFRAME
# ==========================================

events_df = pd.DataFrame(
    events
)


# ==========================================
# NO EVENTS
# ==========================================

if len(events_df) == 0:

    print()
    print(
        "No stable zone transitions detected."
    )

    events_df = pd.DataFrame(
        columns=[
            "frame",
            "person_id",
            "zone",
            "event",
            "from_zone",
            "to_zone"
        ]
    )


# ==========================================
# SAVE EVENT LOG
# ==========================================

events_df.to_csv(
    EVENTS_OUTPUT_PATH,
    index=False
)


# ==========================================
# FLOW RATE
# ==========================================

if len(events_df) > 0:

    # Convert frame number to seconds

    events_df["time_seconds"] = (
        events_df["frame"]
        / fps
    )


    # --------------------------------------
    # One-minute buckets
    # --------------------------------------

    events_df["minute"] = (
        events_df["time_seconds"]
        // 60
    ).astype(int)


    # --------------------------------------
    # Count entries/exits
    # --------------------------------------

    flow = (
        events_df
        .groupby(
            [
                "minute",
                "zone",
                "event"
            ]
        )
        .size()
        .reset_index(
            name="people"
        )
    )


    # --------------------------------------
    # Pivot
    # --------------------------------------

    flow = (
        flow
        .pivot_table(
            index=[
                "minute",
                "zone"
            ],
            columns="event",
            values="people",
            fill_value=0
        )
        .reset_index()
    )


    # --------------------------------------
    # Ensure columns
    # --------------------------------------

    if "ENTER" not in flow.columns:

        flow["ENTER"] = 0


    if "EXIT" not in flow.columns:

        flow["EXIT"] = 0


    # --------------------------------------
    # Rename
    # --------------------------------------

    flow = flow.rename(
        columns={
            "ENTER": "entries_per_minute",
            "EXIT": "exits_per_minute"
        }
    )


    # --------------------------------------
    # Net flow
    # --------------------------------------

    flow["net_flow_per_minute"] = (
        flow["entries_per_minute"]
        -
        flow["exits_per_minute"]
    )


    # --------------------------------------
    # Flow status
    # --------------------------------------

    def get_status(net):

        if net >= 5:

            return "STRONG ACCUMULATION"

        if net >= 2:

            return "ACCUMULATING"

        if net <= -5:

            return "STRONG CLEARING"

        if net <= -2:

            return "CLEARING"

        return "STABLE"


    flow["flow_status"] = (
        flow["net_flow_per_minute"]
        .apply(get_status)
    )


else:

    flow = pd.DataFrame(
        columns=[
            "minute",
            "zone",
            "entries_per_minute",
            "exits_per_minute",
            "net_flow_per_minute",
            "flow_status"
        ]
    )


# ==========================================
# SAVE FLOW ANALYSIS
# ==========================================

flow.to_csv(
    OUTPUT_PATH,
    index=False
)


# ==========================================
# PRINT SUMMARY
# ==========================================

print()
print("--------------------------------")
print("STABLE ZONE FLOW SUMMARY")
print("--------------------------------")


if len(events_df) > 0:

    print(
        f"Stable transitions detected: "
        f"{len(events_df)}"
    )


    print()
    print(
        "Events:"
    )


    for zone in sorted(
        events_df["zone"].unique()
    ):

        zone_events = events_df[
            events_df["zone"] == zone
        ]


        entries = len(
            zone_events[
                zone_events["event"]
                == "ENTER"
            ]
        )


        exits = len(
            zone_events[
                zone_events["event"]
                == "EXIT"
            ]
        )


        print(
            f"{zone}: "
            f"IN={entries} "
            f"| OUT={exits} "
            f"| NET={entries - exits}"
        )


    print()
    print(
        "FLOW PER MINUTE:"
    )


    for _, row in flow.iterrows():

        print(
            f"Minute {int(row['minute'])} "
            f"| {row['zone']} "
            f"| IN="
            f"{int(row['entries_per_minute'])} "
            f"| OUT="
            f"{int(row['exits_per_minute'])} "
            f"| NET="
            f"{int(row['net_flow_per_minute'])} "
            f"| {row['flow_status']}"
        )


else:

    print(
        "No stable transitions detected."
    )


# ==========================================
# COMPLETE
# ==========================================

print()
print("--------------------------------")
print("ZONE FLOW ANALYSIS COMPLETE")
print("--------------------------------")

print(
    f"Event log: "
    f"{EVENTS_OUTPUT_PATH}"
)

print(
    f"Flow analysis: "
    f"{OUTPUT_PATH}"
)

print("--------------------------------")