"""Conservative camera evidence for whether a requested turn changed the view."""

import time

import cv2
import numpy as np


class CameraMotionVerifier:
    """Classify movement as moved, stalled, or uncertain from two camera frames."""

    def __init__(self, snapshot, settle_seconds=0.18, difference_threshold=4.0,
                 texture_threshold=8.0, shift_threshold=1.5,
                 phase_response_threshold=0.12):
        self.snapshot = snapshot
        self.settle_seconds = settle_seconds
        self.difference_threshold = difference_threshold
        self.texture_threshold = texture_threshold
        self.shift_threshold = shift_threshold
        self.phase_response_threshold = phase_response_threshold

    @staticmethod
    def _prepare(frame):
        if frame is None:
            return None
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(grey, (160, 120), interpolation=cv2.INTER_AREA)

    def begin(self):
        return self._prepare(self.snapshot())

    def finish(self, before, after_frame=None):
        if before is None:
            return {"verdict": "uncertain", "reason": "no_before_frame"}
        if after_frame is None:
            time.sleep(self.settle_seconds)
            after_frame = self.snapshot()
        after = self._prepare(after_frame)
        if after is None or after.shape != before.shape:
            return {"verdict": "uncertain", "reason": "no_after_frame"}
        if np.array_equal(before, after):
            return {"verdict": "uncertain", "reason": "stale_camera_frame"}
        texture = float(np.std(before))
        if texture < self.texture_threshold:
            return {
                "verdict": "uncertain", "reason": "insufficient_texture",
                "texture": round(texture, 2),
            }
        score = float(np.mean(cv2.absdiff(before, after)))
        (shift_x, shift_y), response = cv2.phaseCorrelate(
            before.astype(np.float32), after.astype(np.float32)
        )
        # A chassis turn shifts most of the scene coherently. Raw pixel change
        # alone is easily fooled by the tracked person moving in place.
        coherent_shift = max(abs(shift_x), abs(shift_y))
        if not np.isfinite(response) or not np.isfinite(coherent_shift):
            verdict = "uncertain"
            reason = "invalid_global_motion_estimate"
        elif response < self.phase_response_threshold:
            verdict = "uncertain"
            reason = "localized_or_incoherent_change"
        else:
            verdict = "moved" if coherent_shift >= self.shift_threshold else "stalled"
            reason = None
        return {
            "verdict": verdict,
            "difference": round(score, 2), "texture": round(texture, 2),
            "global_shift": round(coherent_shift, 2),
            "phase_response": round(float(response), 3),
            "reason": reason,
        }
