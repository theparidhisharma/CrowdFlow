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


# ==========================================
# FILE SETTINGS
# ==========================================

INPUT_PATH = _out("zone_tracking.csv")

OUTPUT_PATH = _out("zone_congestion.csv")

# Number of frames used for comparison
WINDOW = 30


# ==========================================
# 1. LOAD ZONE TRACKING DATA
# ==========================================

print("Loading zone tracking data...")

df = pd.read_csv(INPUT_PATH)

print(f"Tracking records: {len(df)}")


# ==========================================
# 2. IGNORE PEOPLE OUTSIDE DEFINED ZONES
# ==========================================

df = df[
    df["zone"] != "Outside"
].copy()


print(
    f"Records inside zones: {len(df)}"
)


# ==========================================
# 3. COUNT PEOPLE PER ZONE PER FRAME
# ==========================================

zone_counts = (
    df.groupby(
        ["frame", "zone"]
    )
    .size()
    .reset_index(
        name="people"
    )
)


# ==========================================
# 4. SORT
# ==========================================

zone_counts = zone_counts.sort_values(
    ["zone", "frame"]
).reset_index(drop=True)


# ==========================================
# 5. PREVIOUS CROWD SIZE
# ==========================================

zone_counts["previous_people"] = (
    zone_counts
    .groupby("zone")["people"]
    .shift(WINDOW)
)


# ==========================================
# 6. CHANGE IN CROWD SIZE
# ==========================================

zone_counts["density_change"] = (
    zone_counts["people"]
    - zone_counts["previous_people"]
)


# ==========================================
# 7. GROWTH RATE
# ==========================================

zone_counts["growth_rate"] = (
    zone_counts["density_change"]
    /
    zone_counts["previous_people"]
    .replace(0, pd.NA)
)

zone_counts["growth_rate"] = (
    zone_counts["growth_rate"]
    .fillna(0)
)


# ==========================================
# 8. ENTRY / EXIT TREND
# ==========================================

zone_counts["trend"] = "STABLE"

zone_counts.loc[
    zone_counts["density_change"] > 0,
    "trend"
] = "INCREASING"

zone_counts.loc[
    zone_counts["density_change"] < 0,
    "trend"
] = "DECREASING"


# ==========================================
# 9. CONGESTION CLASSIFICATION
# ==========================================

def classify_congestion(row):

    people = row["people"]
    growth = row["growth_rate"]

    # Prototype thresholds.
    # These will later be replaced with
    # venue-specific density limits.

    if people >= 40:

        return "CRITICAL"

    if people >= 25:

        return "HIGH"

    if people >= 15:

        return "MEDIUM"

    # Detect rapidly growing crowds

    if growth >= 0.50:

        return "HIGH"

    if growth >= 0.25:

        return "MEDIUM"

    return "LOW"


zone_counts["congestion"] = (
    zone_counts.apply(
        classify_congestion,
        axis=1
    )
)


# ==========================================
# 10. EARLY WARNING
# ==========================================

def calculate_warning(row):

    people = row["people"]
    growth = row["growth_rate"]

    if (
        people >= 20
        and growth >= 0.20
    ):

        return "WARNING"

    if growth >= 0.50:

        return "WARNING"

    return "NORMAL"


zone_counts["early_warning"] = (
    zone_counts.apply(
        calculate_warning,
        axis=1
    )
)


# ==========================================
# 11. SAVE RESULTS
# ==========================================

zone_counts.to_csv(
    OUTPUT_PATH,
    index=False
)


# ==========================================
# 12. LATEST FRAME
# ==========================================

latest_frame = zone_counts[
    "frame"
].max()

latest = zone_counts[
    zone_counts["frame"]
    == latest_frame
]


print()
print("--------------------------------")
print("CURRENT ZONE STATUS")
print("--------------------------------")


for _, row in latest.iterrows():

    previous = row[
        "previous_people"
    ]

    change = row[
        "density_change"
    ]

    growth = row[
        "growth_rate"
    ]


    if pd.isna(previous):

        previous_text = "N/A"

    else:

        previous_text = (
            f"{previous:.0f}"
        )


    print(
        f"{row['zone']}: "
        f"{int(row['people'])} people "
        f"| Previous: {previous_text} "
        f"| Change: "
        f"{change if not pd.isna(change) else 0:.0f} "
        f"| Growth: "
        f"{growth * 100:.1f}% "
        f"| {row['congestion']} "
        f"| {row['early_warning']}"
    )


# ==========================================
# 13. FIND HIGHEST PRIORITY ZONE
# ==========================================

priority = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4
}


latest = latest.copy()

latest["priority"] = (
    latest["congestion"]
    .map(priority)
)


if len(latest) > 0:

    danger = latest.sort_values(
        [
            "priority",
            "growth_rate",
            "people"
        ],
        ascending=False
    ).iloc[0]


    print()
    print("--------------------------------")
    print("HIGHEST PRIORITY ZONE")
    print("--------------------------------")


    print(
        f"Zone: {danger['zone']}"
    )

    print(
        f"People: "
        f"{int(danger['people'])}"
    )

    print(
        f"Congestion: "
        f"{danger['congestion']}"
    )

    print(
        f"Growth: "
        f"{danger['growth_rate'] * 100:.1f}%"
    )

    print(
        f"Warning: "
        f"{danger['early_warning']}"
    )


# ==========================================
# 14. COMPLETE
# ==========================================

print()
print("--------------------------------")
print("ZONE CONGESTION ANALYSIS COMPLETE")
print("--------------------------------")

print(
    f"Output: {OUTPUT_PATH}"
)

print("--------------------------------")