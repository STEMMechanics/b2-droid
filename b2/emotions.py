"""Facade for emotion scoring, causes, and deterministic effects."""

from .emotion_effects import EmotionEffects, FACES
from .emotion_model import EmotionScorer


class EmotionController:
    FACES = FACES

    def __init__(self):
        self.scorer = EmotionScorer()
        self.effects = EmotionEffects()
        # Compatibility attributes for callers that coordinate using the lock.
        self.lock = self.scorer.lock
        self.scores = self.scorer.scores

    def adjust(self, name, amount):
        return self.scorer.adjust(name, amount)

    def apply(self, changes):
        return self.scorer.apply(dict(changes))

    def event(self, name):
        return self.scorer.event(name)

    def advance(self, **conditions):
        return self.scorer.advance(**conditions)

    def snapshot(self, rounded=False):
        return self.scorer.snapshot(rounded=rounded)

    @staticmethod
    def face_for(scores, visible):
        return EmotionEffects.face_for(scores, visible)

    def face(self, visible):
        return self.effects.face_for(self.snapshot(), visible)

    def should_play_transition_sound(self, previous, next_face, elapsed, cooldown):
        return self.effects.should_play_transition_sound(previous, next_face, elapsed, cooldown)

    def curiosity_cooldown(self, normal_cooldown):
        return self.effects.curiosity_cooldown(self.snapshot(), normal_cooldown)

    def context(self):
        return self.effects.describe(self.snapshot(), self.scorer.last_cause)
