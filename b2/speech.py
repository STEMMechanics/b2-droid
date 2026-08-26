"""Local Whisper transcription and Piper/ALSA speech output service."""

import os
import subprocess
import sys
import time


class SpeechService:
    def __init__(self, whisper_executable, piper_model, speech_wav, microphone,
                 set_state, apply_volume, post_speech_settle=0.25):
        self.whisper_executable = whisper_executable
        self.piper_model = piper_model
        self.speech_wav = speech_wav
        self.microphone = microphone
        self.set_state = set_state
        self.apply_volume = apply_volume
        self.post_speech_settle = post_speech_settle

    def transcribe(self, filename, model):
        if not os.path.isfile(self.whisper_executable):
            raise RuntimeError(f"Whisper executable is missing: {self.whisper_executable}")
        if not os.path.isfile(model):
            raise RuntimeError(f"Whisper model is missing: {model}")
        result = subprocess.run(
            [
                self.whisper_executable, "-m", model, "-f", filename,
                "-l", "en", "--no-timestamps",
            ],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def speak(self, text):
        text = (text or "").strip()
        if not text:
            return False
        try:
            subprocess.run(
                [
                    sys.executable, "-m", "piper", "--model", self.piper_model,
                    "-f", self.speech_wav,
                ],
                input=(text + "\n").encode(), check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            print(f"Speech synthesis failed without stopping B2: {error}")
            self.set_state("error")
            time.sleep(0.4)
            self.set_state("idle")
            return False
        played = True
        try:
            self.set_state("talking")
            self.apply_volume()
            playback_command = ["aplay"]
            output_device = os.environ.get("B2_OUTPUT_DEVICE", "").strip()
            if output_device:
                playback_command.extend(["-D", output_device])
            playback_command.append(self.speech_wav)
            subprocess.run(
                playback_command, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True, check=True,
            )
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or "").strip().splitlines()
            reason = detail[-1] if detail else str(error)
            print(f"Audio playback failed without stopping B2: {reason}")
            played = False
        except OSError as error:
            print(f"Audio playback failed without stopping B2: {error}")
            played = False
        finally:
            self.set_state("idle")
            self.microphone.drain()
            time.sleep(self.post_speech_settle)
            self.microphone.drain()
        return played

    def context(self):
        return {
            "transcription": "local whisper.cpp",
            "speech": "local Piper voice through ALSA",
            "output_device": os.environ.get("B2_OUTPUT_DEVICE", "default"),
            "microphone_running": self.microphone.process.poll() is None,
        }
