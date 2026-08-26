"""Bounded motion execution and explicit-feedback calibration."""

import re
import time


class MotionController:
    """Execute known motor commands; never accepts arbitrary model output."""

    def __init__(self, send_state, lock, learning, defaults, minimum_turn,
                 maximum_turn=1.5, around_maximum=3.0, send_speed=None,
                 default_speed=110, minimum_speed=70, maximum_speed=200,
                 motion_probe=None, visual_stalls_required=2,
                 stall_cooldown=30.0):
        self.send_state = send_state
        self.lock = lock
        self.learning = learning
        self.defaults = dict(defaults)
        self.minimum_turn = minimum_turn
        self.maximum_turn = maximum_turn
        self.around_maximum = around_maximum
        self.send_speed = send_speed
        self.default_speed = default_speed
        self.minimum_speed = minimum_speed
        self.maximum_speed = maximum_speed
        self.motion_probe = motion_probe
        self.visual_stalls_required = max(2, int(visual_stalls_required))
        self.visual_stalls = 0
        self.stall_cooldown = max(1.0, float(stall_cooldown))
        self.automatic_disabled_until = 0.0
        self.last_verification_log = 0.0
        self.last_logged_verdict = None
        self.last_visual_verification = None
        self.pending_probe = None
        self.last_action = None

    def duration(self, command):
        default = self.defaults[command]
        return float(self.learning.get("motion", command, default))

    def speed(self):
        learned = float(self.learning.get(
            "motion", "motor_speed", self.default_speed
        ))
        return int(round(max(
            self.minimum_speed,
            min(self.maximum_speed, max(self.default_speed, learned)),
        )))

    def activate_speed(self):
        if self.send_speed:
            self.send_speed(self.speed())

    def start_probe(self):
        try:
            return self.motion_probe.begin() if self.motion_probe else None
        except Exception as error:
            print(f"Camera motion probe unavailable: {error}")
            return None

    def _increase_power(self, source):
        previous = self.speed()
        if previous >= self.maximum_speed:
            return previous, previous
        learned = int(round(self.learning.set_bounded(
            "motion", "motor_speed", previous + 20,
            self.minimum_speed, self.maximum_speed,
            metadata={"source": source},
        )))
        if self.send_speed:
            self.send_speed(learned)
        if learned != previous:
            print(f"Learned motor calibration: PWM {previous} -> {learned} ({source}).")
        return learned, previous

    def automatic_motion_allowed(self):
        return (
            time.monotonic() >= self.automatic_disabled_until
            and self.pending_probe is None
        )

    def _trip_stall_circuit(self):
        self.automatic_disabled_until = time.monotonic() + self.stall_cooldown
        self.visual_stalls = 0
        self.send_state("stop")
        print(
            "Automatic tracking paused after repeated camera-confirmed stalls "
            f"at maximum PWM; retrying in {self.stall_cooldown:.0f}s."
        )

    def _record_verification(self, result):
        self.last_visual_verification = result
        now = time.monotonic()
        verdict = result.get("verdict")
        if verdict != self.last_logged_verdict or now - self.last_verification_log >= 10:
            print(f"Camera movement verification: {result}")
            self.last_logged_verdict = verdict
            self.last_verification_log = now
        if result.get("verdict") == "stalled":
            self.visual_stalls += 1
            if self.visual_stalls >= self.visual_stalls_required:
                if self.speed() >= self.maximum_speed:
                    self._trip_stall_circuit()
                else:
                    self._increase_power("repeated_camera_stall")
                    self.visual_stalls = 0
        elif result.get("verdict") == "moved":
            self.visual_stalls = 0

    def finish_pending_probe(self, after_frame):
        # Camera probes are NumPy arrays, whose truth value is intentionally
        # undefined. Test identity rather than coercing a frame to bool.
        if self.pending_probe is None or self.motion_probe is None:
            return None
        pending = self.pending_probe
        if time.monotonic() < pending["ready_at"]:
            return None
        try:
            result = self.motion_probe.finish(
                pending["before"], after_frame=after_frame
            )
        except Exception as error:
            result = {"verdict": "uncertain", "reason": str(error)}
        pending["results"].append(result)
        if len(pending["results"]) < 3:
            return None
        self.pending_probe = None
        verdicts = [item.get("verdict") for item in pending["results"]]
        if verdicts.count("moved") >= 2:
            verdict = "moved"
        elif verdicts.count("stalled") == len(verdicts):
            verdict = "stalled"
        else:
            verdict = "uncertain"
        combined = {
            "verdict": verdict,
            "samples": verdicts,
            "reason": None if verdict != "uncertain" else "conflicting_frame_evidence",
            "latest": pending["results"][-1],
        }
        self._record_verification(combined)
        return combined

    def note_action(self, command, duration, source="automatic", probe=None,
                    defer_verification=False):
        self.last_action = {
            "command": command, "duration": duration,
            "at": time.monotonic(), "source": source,
        }
        if self.motion_probe and probe is not None and defer_verification:
            self.pending_probe = {
                "before": probe,
                "ready_at": time.monotonic() + float(
                    getattr(self.motion_probe, "settle_seconds", 0.0)
                ),
                "results": [],
            }
        elif self.motion_probe and probe is not None:
            try:
                result = self.motion_probe.finish(probe)
            except Exception as error:
                result = {"verdict": "uncertain", "reason": str(error)}
            self._record_verification(result)

    def execute(self, command):
        if command == "stop":
            self.send_state("stop")
            return "Stopped."
        duration = self.duration(command)
        probe = self.start_probe()
        motor_command = "right" if command == "turn_around" else command
        with self.lock:
            try:
                print(f"Drive command: {command} for {duration:.2f}s")
                self.send_state(motor_command)
                time.sleep(duration)
            finally:
                self.send_state("stop")
        self.note_action(command, duration, source="requested", probe=probe)
        return {
            "forward": "Moved forward.", "reverse": "Moved backward.",
            "left": "Turned left.", "right": "Turned right.",
            "turn_around": "Turned around.",
        }[command]

    def apply_feedback(self, text):
        """Adjust only a recent turn from unambiguous speaker feedback."""
        action = self.last_action
        if not action or time.monotonic() - action["at"] > 90:
            return None
        command = action["command"]
        if command not in {"left", "right", "turn_around"}:
            return None
        lowered = text.lower()
        if re.search(
            r"\b(?:not stuck|is not stuck|isn't stuck|did move|did turn|"
            r"moved fine|turned fine|worked fine)\b",
            lowered,
        ):
            # This confirms movement; it must never fall through to the broad
            # `stuck` match below and incorrectly increase motor power.
            return {
                "command": command,
                "motor_speed": self.speed(),
                "direction": "movement_confirmed",
            }
        if re.search(
            r"\b(?:did(?: not|n't) move|not moving|did(?: not|n't) turn|"
            r"not turning|stuck|motors? (?:are )?stalled|"
            r"wheels? (?:are )?stalled)\b",
            lowered,
        ):
            learned, previous = self._increase_power("explicit_stall_feedback")
            return {
                "command": command, "motor_speed": learned,
                "previous_motor_speed": previous, "direction": "more_power",
            }
        if re.search(r"\b(?:too far|too much|overshot|over-?turned)\b", lowered):
            factor, direction = 0.85, "shorter"
        elif re.search(
            r"\b(?:not far enough|barely moved|didn't turn enough|"
            r"did not turn enough|turn more)\b", lowered
        ):
            factor, direction = 1.15, "longer"
        else:
            return None
        maximum = self.around_maximum if command == "turn_around" else self.maximum_turn
        learned = self.learning.set_bounded(
            "motion", command, action["duration"] * factor,
            self.minimum_turn, maximum,
            metadata={"source": "explicit_feedback", "direction": direction},
        )
        print(
            f"Learned motion calibration: {command}={learned:.3f}s "
            f"({direction})."
        )
        return {"command": command, "duration": learned, "direction": direction}

    def context(self):
        return {
            "learned_turn_seconds": {
                command: round(self.duration(command), 3)
                for command in ("left", "right", "turn_around")
            },
            "last_action": self.last_action,
            "motor_pwm": self.speed(),
            "motor_pwm_bounds": [self.minimum_speed, self.maximum_speed],
            "camera_verification": self.last_visual_verification,
            "consecutive_visual_stalls": self.visual_stalls,
            "automatic_motion_available": self.automatic_motion_allowed(),
            "automatic_motion_cooldown_remaining": round(max(
                0.0, self.automatic_disabled_until - time.monotonic()
            ), 1),
            "safety": "All actions are bounded; no autonomous navigation.",
        }
