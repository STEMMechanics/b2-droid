"""Emotion score definitions, event causes, and passive evolution."""

import threading


DEFAULT_SCORES = {
    "happiness": 55.0,
    "curiosity": 50.0,
    "loneliness": 5.0,
    "concern": 0.0,
}

# Named causes keep behavioural code from scattering unexplained score deltas.
EVENT_CHANGES = {
    "user_interaction": {
        "happiness": 8, "curiosity": -12, "loneliness": -25, "concern": -8,
    },
    "person_found": {
        "happiness": 8, "curiosity": 10, "loneliness": -20,
    },
    "exploration_satisfied": {"curiosity": -8},
    "inference_failure": {"concern": 15},
}


class EmotionScorer:
    """Own bounded scores and explain every named transition."""

    def __init__(self, initial=None):
        self.lock = threading.RLock()
        self.scores = dict(DEFAULT_SCORES if initial is None else initial)
        self.last_cause = "startup"

    @staticmethod
    def _bounded(value):
        return max(0.0, min(100.0, float(value)))

    def adjust(self, name, amount, cause="direct_adjustment"):
        with self.lock:
            if name not in self.scores:
                raise KeyError(f"Unknown emotion: {name}")
            self.scores[name] = self._bounded(self.scores[name] + amount)
            self.last_cause = cause
            return self.scores[name]

    def apply(self, changes, cause="explicit_direction"):
        with self.lock:
            for name, amount in dict(changes).items():
                if name not in self.scores:
                    raise KeyError(f"Unknown emotion: {name}")
                self.scores[name] = self._bounded(self.scores[name] + amount)
            self.last_cause = cause
            return dict(self.scores)

    def event(self, name):
        if name not in EVENT_CHANGES:
            raise KeyError(f"Unknown emotion event: {name}")
        return self.apply(EVENT_CHANGES[name], cause=name)

    def advance(self, elapsed, person_visible, person_identified, inactive_seconds,
                exploration_idle_seconds):
        """Apply passive per-second rates from real observable conditions."""
        elapsed = max(0.0, min(5.0, float(elapsed)))
        with self.lock:
            if person_visible:
                changes = {
                    "loneliness": -0.20 * elapsed,
                    "happiness": (0.05 if person_identified else 0.01) * elapsed,
                }
                if inactive_seconds >= exploration_idle_seconds:
                    changes["curiosity"] = 0.10 * elapsed
                cause = "person_visible_idle" if "curiosity" in changes else "person_visible"
            else:
                changes = {
                    "loneliness": 0.035 * elapsed,
                    "curiosity": 0.025 * elapsed,
                    "happiness": -0.015 * elapsed,
                }
                cause = "person_absent"
            for name, amount in changes.items():
                self.scores[name] = self._bounded(self.scores[name] + amount)
            self.last_cause = cause
            return dict(self.scores)

    def snapshot(self, rounded=False):
        with self.lock:
            scores = dict(self.scores)
            if rounded:
                scores = {name: round(score, 1) for name, score in scores.items()}
            return scores
