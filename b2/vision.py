"""Camera and YOLO object-detection service.

Identity policy is intentionally not included: the service publishes frames and
object geometry, while the coordinator/repository decides whose face it is.
"""

import collections
import time

import cv2
from ultralytics import YOLO


class VisionService:
    def __init__(self, camera_device, model_path, interval=0.15, confidence=0.4,
                 history_size=5, visibility_hold=2.5):
        self.interval = interval
        self.confidence = confidence
        self.visibility_hold = visibility_hold
        self.history = collections.deque(maxlen=history_size)
        self.last_person_detection = 0.0
        self.model = YOLO(model_path)
        self.camera = cv2.VideoCapture(camera_device, cv2.CAP_V4L2)
        if not self.camera.isOpened():
            raise RuntimeError("Vision camera unavailable")
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def read(self):
        ok, frame = self.camera.read()
        if not ok:
            return None
        results = self.model.predict(
            frame, imgsz=320, conf=self.confidence, verbose=False,
        )
        detected = []
        person_candidates = []
        for result in results:
            for box in result.boxes:
                name = result.names[int(box.cls[0])]
                detected.append(name)
                if name == "person":
                    person_candidates.append(tuple(float(v) for v in box.xyxy[0]))
        self.history.append(detected)
        recent = [item for items in self.history for item in items]
        person_frames = sum(1 for items in self.history if "person" in items)
        raw_visible = person_frames >= 2
        if raw_visible:
            self.last_person_detection = time.monotonic()
        visible = raw_visible or (
            self.last_person_detection > 0
            and time.monotonic() - self.last_person_detection <= self.visibility_hold
        )
        offset = None
        if person_candidates:
            target = max(
                person_candidates,
                key=lambda item: (item[2] - item[0]) * (item[3] - item[1]),
            )
            centre_x = (target[0] + target[2]) / 2.0
            offset = (centre_x - frame.shape[1] / 2.0) / (frame.shape[1] / 2.0)
        return {
            "frame": frame,
            "person_visible": visible,
            "person_visible_raw": raw_visible,
            "person_last_seen_age_seconds": (
                round(time.monotonic() - self.last_person_detection, 1)
                if self.last_person_detection else None
            ),
            "objects": sorted({item for item in recent if item != "person"}),
            "person_offset_x": offset,
            "updated": time.monotonic(),
        }

    def close(self):
        self.camera.release()
