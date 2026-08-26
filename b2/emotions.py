"""Thread-safe bounded emotional state and face selection."""

import threading


class EmotionController:
    FACES = {"idle", "curious", "lonely", "excited", "concerned"}

    def __init__(self):
        self.lock = threading.RLock()
        self.scores = {
            "happiness": 55.0, "curiosity": 50.0,
            "loneliness": 5.0, "concern": 0.0,
        }

    def adjust(self, name, amount):
        with self.lock:
            if name not in self.scores:
                raise KeyError(f"Unknown emotion: {name}")
            self.scores[name] = max(0.0, min(100.0, self.scores[name] + amount))
            return self.scores[name]

    def apply(self, changes):
        return {name: self.adjust(name, amount) for name, amount in changes}

    def snapshot(self, rounded=False):
        with self.lock:
            if rounded:
                return {name: round(score, 1) for name, score in self.scores.items()}
            return dict(self.scores)

    @staticmethod
    def face_for(scores, visible):
        if scores["concern"] >= 60:
            return "concerned"
        if scores["loneliness"] >= 65 and not visible:
            return "lonely"
        if scores["curiosity"] >= 62:
            return "curious"
        if scores["happiness"] >= 72:
            return "excited"
        return "idle"
