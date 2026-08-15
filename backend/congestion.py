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
# 1. SETTINGS
# ==========================================

CSV_PATH = _out("crowd_analysis.csv")

OUTPUT_PATH = _out("congestion_analysis.csv")

# Analyze every N frames
WINDOW = 30


# ==========================================
# 2. LOAD DATA
# ==========================================

print("Loading crowd analysis...")

df = pd.read_csv(CSV_PATH)

print(f"Records: {len(df)}")


# ==========================================
# 3. COUNT PEOPLE BY FRAME + ZONE
# ==========================================

zone_counts = (
    df.groupby(["frame", "zone"])
    .size()
    .reset_index(name="people")
)


# ==========================================
# 4. SORT DATA
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
# 6. DENSITY CHANGE
# ==========================================

zone_counts["density_change"] = (
    zone_counts["people"]
    - zone_counts["previous_people"]
)


# ==========================================
# 7. RATE OF CHANGE
# ==========================================

zone_counts["growth_rate"] = (
    zone_counts["density_change"]
    / zone_counts["previous_people"]
    .replace(0, pd.NA)
)


zone_counts["growth_rate"] = (
    zone_counts["growth_rate"]
    .fillna(0)
)


# ==========================================
# 8. CONGESTION LEVEL
# ==========================================

def classify_congestion(row):

    people = row["people"]
    growth = row["growth_rate"]

    # Very high crowd
    if people >= 40:

        return "CRITICAL"

    # High crowd OR rapidly growing crowd
    if people >= 25 or growth >= 0.50:

        return "HIGH"

    # Moderate crowd
    if people >= 15 or growth >= 0.25:

        return "MEDIUM"

    return "LOW"


zone_counts["congestion"] = zone_counts.apply(
    classify_congestion,
    axis=1
)


# ==========================================
# 9. SAVE RESULTS
# ==========================================

zone_counts.to_csv(
    OUTPUT_PATH,
    index=False
)


# ==========================================
# 10. CURRENT STATUS
# ==========================================

latest_frame = zone_counts["frame"].max()

latest = zone_counts[
    zone_counts["frame"] == latest_frame
]


print()
print("--------------------------------")
print("CURRENT CROWD STATUS")
print("--------------------------------")

for _, row in latest.iterrows():

    print(
        f"{row['zone']}: "
        f"{int(row['people'])} people "
        f"| Change: {row['density_change']:.0f} "
        f"| Level: {row['congestion']}"
    )


# ==========================================
# 11. MOST DANGEROUS ZONE
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
        ["priority", "people"],
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
        f"People: {int(danger['people'])}"
    )

    print(
        f"Status: {danger['congestion']}"
    )


# ==========================================
# 12. COMPLETE
# ==========================================

print()
print("--------------------------------")
print("CONGESTION ANALYSIS COMPLETE")
print("--------------------------------")

print(
    f"Output: {OUTPUT_PATH}"
)