"""Deterministic visible and behavioural effects of emotion scores."""


FACES = {"idle", "curious", "lonely", "excited", "concerned"}
FACE_THRESHOLDS = {
    "concerned": ("concern", 60),
    "lonely": ("loneliness", 65),
    "curious": ("curiosity", 62),
    "excited": ("happiness", 72),
}


class EmotionEffects:
    @staticmethod
    def face_for(scores, person_visible):
        if scores["concern"] >= FACE_THRESHOLDS["concerned"][1]:
            return "concerned"
        if scores["loneliness"] >= FACE_THRESHOLDS["lonely"][1] and not person_visible:
            return "lonely"
        if scores["curiosity"] >= FACE_THRESHOLDS["curious"][1]:
            return "curious"
        if scores["happiness"] >= FACE_THRESHOLDS["excited"][1]:
            return "excited"
        return "idle"

    @staticmethod
    def should_play_transition_sound(previous_face, next_face, elapsed, cooldown):
        return (
            previous_face is not None
            and previous_face != next_face
            and elapsed >= cooldown
        )

    @staticmethod
    def curiosity_cooldown(scores, normal_cooldown):
        return max(90.0, normal_cooldown / 2) if scores["curiosity"] >= 75 else normal_cooldown

    @staticmethod
    def describe(scores, last_cause):
        return {
            "scores": {name: round(value, 1) for name, value in scores.items()},
            "dominant_face": EmotionEffects.face_for(scores, False),
            "last_cause": last_cause,
            "effects": {
                "concerned_face_at": 60,
                "lonely_face_at": 65,
                "curious_face_at": 62,
                "excited_face_at": 72,
                "high_curiosity_shortens_check_in_cooldown": True,
            },
        }
