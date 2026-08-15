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
import csv
import cv2
import torch
import numpy as np
import supervision as sv

from PIL import Image
from transformers import (
    RTDetrImageProcessor,
    RTDetrForObjectDetection
)

from trackers import ByteTrackTracker


# ==========================================
# 1. LOAD HUGGING FACE RT-DETR
# ==========================================

MODEL_NAME = "PekingU/rtdetr_r18vd_coco_o365"

print("Loading Hugging Face model...")

processor = RTDetrImageProcessor.from_pretrained(
    MODEL_NAME
)

model = RTDetrForObjectDetection.from_pretrained(
    MODEL_NAME
)

model.eval()

print("Model loaded successfully!")


# ==========================================
# 2. VIDEO SETTINGS
# ==========================================

# Optional override used by the API job runner; manual runs are unchanged.
OUTPUT_PATH = _out("crowd_tracked.mp4")
CSV_PATH = _out("tracks.csv")


# ==========================================
# 3. OPEN VIDEO
# ==========================================

cap = cv2.VideoCapture(VIDEO_PATH)

if not cap.isOpened():
    raise RuntimeError(
        f"Could not open video: {VIDEO_PATH}"
    )


# Read video information

fps = cap.get(cv2.CAP_PROP_FPS)

original_width = int(
    cap.get(cv2.CAP_PROP_FRAME_WIDTH)
)

original_height = int(
    cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
)

total_frames = int(
    cap.get(cv2.CAP_PROP_FRAME_COUNT)
)


# Validate video

if fps <= 0:
    raise RuntimeError(
        "Could not read video FPS."
    )

if original_width <= 0 or original_height <= 0:
    raise RuntimeError(
        "Could not read video dimensions."
    )

if total_frames <= 0:
    raise RuntimeError(
        "Could not read video frames."
    )


# ==========================================
# 4. AUTOMATIC RESOLUTION HANDLING
# ==========================================

# Maximum processing width
# This keeps 4K videos manageable while
# preserving their aspect ratio.

MAX_WIDTH = 1920

if original_width > MAX_WIDTH:

    scale = MAX_WIDTH / original_width

    width = MAX_WIDTH
    height = int(original_height * scale)

else:

    width = original_width
    height = original_height


print()
print("Video opened successfully!")

print(
    f"Original resolution: "
    f"{original_width} x {original_height}"
)

print(
    f"Processing resolution: "
    f"{width} x {height}"
)

print(f"FPS: {fps}")

print(
    f"Total frames: {total_frames}"
)


# ==========================================
# 4b. RECORD PROCESSED VIDEO METADATA
# ==========================================

# Written so downstream tooling (single-camera zone generation) knows the
# real processed frame size instead of guessing it.

import json as _json  # noqa: E402

with open(META_PATH, "w") as _meta_file:
    _json.dump(
        {
            "video_path": VIDEO_PATH,
            "original_width": original_width,
            "original_height": original_height,
            "width": width,
            "height": height,
            "fps": fps,
            "total_frames": total_frames,
        },
        _meta_file,
        indent=2,
    )




# ==========================================
# 5. CREATE OUTPUT VIDEO
# ==========================================

fourcc = cv2.VideoWriter_fourcc(
    *"mp4v"
)

out = cv2.VideoWriter(
    OUTPUT_PATH,
    fourcc,
    fps,
    (width, height)
)


if not out.isOpened():
    raise RuntimeError(
        "Could not create output video."
    )


# ==========================================
# 6. CREATE BYTETRACK TRACKER
# ==========================================

tracker = ByteTrackTracker()

print()
print("ByteTrackTracker initialized!")


# ==========================================
# 7. CREATE CSV FILE
# ==========================================

csv_file = open(
    CSV_PATH,
    "w",
    newline=""
)

csv_writer = csv.writer(csv_file)


# CSV header

csv_writer.writerow([
    "frame",
    "person_id",
    "center_x",
    "center_y"
])


# ==========================================
# 8. PROCESS VIDEO
# ==========================================

frame_number = 0


while True:

    # --------------------------------------
    # Read frame
    # --------------------------------------

    ret, frame = cap.read()

    if not ret:
        break

    frame_number += 1


    # --------------------------------------
    # Resize if necessary
    # --------------------------------------

    if (
        frame.shape[1] != width
        or frame.shape[0] != height
    ):

        frame = cv2.resize(
            frame,
            (width, height),
            interpolation=cv2.INTER_AREA
        )


    # --------------------------------------
    # Convert BGR → RGB
    # --------------------------------------

    rgb_frame = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2RGB
    )


    # --------------------------------------
    # Prepare image for Hugging Face
    # --------------------------------------

    image = Image.fromarray(
        rgb_frame
    )

    inputs = processor(
        images=image,
        return_tensors="pt"
    )


    # --------------------------------------
    # Run RT-DETR
    # --------------------------------------

    with torch.no_grad():

        outputs = model(**inputs)


    # --------------------------------------
    # Convert detections to image coords
    # --------------------------------------

    target_sizes = torch.tensor(
        [[height, width]]
    )


    results = processor.post_process_object_detection(
        outputs,
        target_sizes=target_sizes,
        threshold=0.30
    )[0]


    # ======================================
    # 9. KEEP ONLY PEOPLE
    # ======================================

    boxes = []
    scores = []


    for score, label, box in zip(
        results["scores"],
        results["labels"],
        results["boxes"]
    ):

        label_name = model.config.id2label[
            label.item()
        ]


        if label_name.lower() != "person":
            continue


        boxes.append(
            box.detach()
            .cpu()
            .numpy()
        )

        scores.append(
            score.item()
        )


    # ======================================
    # 10. CREATE SUPERVISION DETECTIONS
    # ======================================

    if len(boxes) > 0:

        boxes = np.asarray(
            boxes,
            dtype=np.float32
        )

        scores = np.asarray(
            scores,
            dtype=np.float32
        )

        detections = sv.Detections(
            xyxy=boxes,
            confidence=scores,
            class_id=np.zeros(
                len(boxes),
                dtype=int
            )
        )

    else:

        detections = sv.Detections.empty()


    # ======================================
    # 11. TRACK PEOPLE
    # ======================================

    tracked = tracker.update(
        detections
    )


    # ======================================
    # 12. DRAW TRACKING RESULTS
    # ======================================

    if tracked.tracker_id is not None:

        for xyxy, tracker_id in zip(
            tracked.xyxy,
            tracked.tracker_id
        ):

            # Bounding box coordinates

            x1, y1, x2, y2 = [
                int(value)
                for value in xyxy
            ]


            # Person ID

            tracker_id = int(
                tracker_id
            )


            # Center point

            center_x = int(
                (x1 + x2) / 2
            )

            center_y = int(
                (y1 + y2) / 2
            )


            # --------------------------------
            # Save valid tracking data
            # --------------------------------

            if tracker_id >= 0:

                csv_writer.writerow([
                    frame_number,
                    tracker_id,
                    center_x,
                    center_y
                ])


            # --------------------------------
            # Draw bounding box
            # --------------------------------

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                3
            )


            # --------------------------------
            # Draw Person ID
            # --------------------------------

            text = (
                f"Person ID: {tracker_id}"
            )


            cv2.putText(
                frame,
                text,
                (
                    x1,
                    max(y1 - 10, 25)
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )


    # ======================================
    # 13. CROWD COUNT
    # ======================================

    people_count = len(tracked)


    cv2.putText(
        frame,
        f"People: {people_count}",
        (30, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 255, 0),
        3
    )


    # ======================================
    # 14. SAVE PROCESSED FRAME
    # ======================================

    out.write(frame)


    # ======================================
    # 15. SHOW PROGRESS
    # ======================================

    if frame_number % 10 == 0:

        print(
            f"Processed "
            f"{frame_number}/{total_frames}"
            f" | People: {people_count}"
        )


# ==========================================
# 16. CLEANUP
# ==========================================

cap.release()

out.release()

csv_file.close()


# ==========================================
# 17. FINISHED
# ==========================================

print()

print("--------------------------------")

print("TRACKING COMPLETE")

print(
    f"Output video: {OUTPUT_PATH}"
)

print(
    f"Tracking data: {CSV_PATH}"
)
print("--------------------------------")