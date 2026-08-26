"""Small generated sound effects, avoiding bundled binary assets."""

import math
import os
import struct
import subprocess
import wave
from pathlib import Path


def _tone(frequency, duration, rate=22050, volume=0.24):
    count = int(rate * duration)
    fade = max(1, int(rate * 0.015))
    samples = []
    for index in range(count):
        envelope = min(1.0, index / fade, (count - index) / fade)
        value = int(32767 * volume * envelope * math.sin(2 * math.pi * frequency * index / rate))
        samples.append(struct.pack("<h", value))
    return b"".join(samples)


def _play(target):
    command = ["aplay"]
    output_device = os.environ.get("B2_OUTPUT_DEVICE", "").strip()
    if output_device:
        command.extend(["-D", output_device])
    command.append(str(target))
    try:
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, check=False,
        )
    except OSError as error:
        print(f"Sound playback failed: {error}")
        return False
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        print(
            "Sound playback failed: "
            + (detail[-1] if detail else f"aplay exited {result.returncode}")
        )
        return False
    return True


def play_ready_sound(filename="/tmp/b2-ready.wav"):
    """Play a friendly rising droid chime through ALSA."""
    if os.environ.get("B2_READY_SOUND", "true").lower() in {"0", "false", "no"}:
        print("Ready sound disabled by B2_READY_SOUND.")
        return False
    rate = 22050
    silence = b"\x00\x00" * int(rate * 0.045)
    audio = (
        _tone(523.25, 0.15, rate, volume=0.42) + silence
        + _tone(659.25, 0.15, rate, volume=0.42) + silence
        + _tone(783.99, 0.24, rate, volume=0.42)
    )
    target = Path(filename)
    try:
        with wave.open(str(target), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(audio)
    except (OSError, wave.Error) as error:
        print(f"Ready sound generation failed: {error}")
        return False
    return _play(target)


_EMOTION_MOTIFS = {
    "idle": ((587.33, 0.08), (698.46, 0.10)),
    "curious": ((440.00, 0.08), (659.25, 0.11)),
    "lonely": ((493.88, 0.11), (369.99, 0.16)),
    "excited": ((523.25, 0.07), (659.25, 0.07), (880.00, 0.12)),
    "concerned": ((293.66, 0.12), (277.18, 0.12), (293.66, 0.14)),
}


def play_emotion_sound(emotion, filename="/tmp/b2-emotion.wav"):
    """Play a quiet, non-verbal motif for an emotional state change."""
    if os.environ.get("B2_EMOTION_SOUNDS", "true").lower() in {"0", "false", "no"}:
        return False
    notes = _EMOTION_MOTIFS.get(emotion)
    if not notes:
        return False
    rate = 22050
    gap = b"\x00\x00" * int(rate * 0.035)
    audio = gap.join(
        _tone(frequency, duration, rate, volume=0.14)
        for frequency, duration in notes
    )
    target = Path(filename)
    try:
        with wave.open(str(target), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(audio)
        return _play(target)
    except (OSError, wave.Error):
        return False
