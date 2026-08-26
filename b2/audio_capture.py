"""Persistent ALSA microphone transport and PCM helpers.

The reader always drains ``arecord`` so the OS pipe cannot block, but it queues
samples only inside an explicit capture window. This prevents audio recorded
during inference or playback from becoming a later user utterance.
"""

import queue
import subprocess
import threading
import wave

import numpy as np


class Microphone:
    """Read fixed-size PCM chunks from one long-running ``arecord`` process."""

    def __init__(self, device, rate, channels, chunk_bytes, chunk_ms):
        self.chunk_bytes = chunk_bytes
        self.process = subprocess.Popen(
            [
                "arecord", "-D", device, "-f", "S16_LE", "-r", str(rate),
                "-c", str(channels), "-t", "raw", "-q",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )
        self.chunks = queue.Queue(maxsize=max(8, int(2 * 1000 / chunk_ms)))
        self.closed = threading.Event()
        self.accepting_audio = threading.Event()
        self.dropped_chunks = 0
        self.reader = threading.Thread(target=self._reader, daemon=True)
        self.reader.start()

    def _reader(self):
        while not self.closed.is_set():
            data = bytearray()
            while len(data) < self.chunk_bytes and not self.closed.is_set():
                chunk = self.process.stdout.read(self.chunk_bytes - len(data))
                if not chunk:
                    return
                data.extend(chunk)
            if not data:
                return
            if not self.accepting_audio.is_set():
                continue
            try:
                self.chunks.put_nowait(bytes(data))
            except queue.Full:
                try:
                    self.chunks.get_nowait()
                except queue.Empty:
                    pass
                self.chunks.put_nowait(bytes(data))
                self.dropped_chunks += 1
                if self.dropped_chunks == 1 or self.dropped_chunks % 500 == 0:
                    print(
                        "Microphone backlog full; dropped oldest audio chunk "
                        f"({self.dropped_chunks} total)."
                    )

    def start_capture(self):
        """Start a fresh capture window, discarding anything older."""
        self.drain()
        self.accepting_audio.set()

    def stop_capture(self):
        """Stop retaining samples while continuing to drain ALSA."""
        self.accepting_audio.clear()
        self.drain()

    def read(self, size):
        if size != self.chunk_bytes:
            raise ValueError("Microphone reads must use one audio chunk")
        while True:
            try:
                return self.chunks.get(timeout=1)
            except queue.Empty:
                if self.process.poll() is not None:
                    raise RuntimeError("Microphone capture process stopped")

    def drain(self):
        while True:
            try:
                self.chunks.get_nowait()
            except queue.Empty:
                return

    def close(self):
        self.closed.set()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=1)


def rms(data):
    """Return root-mean-square amplitude for signed 16-bit PCM bytes."""
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    if not len(samples):
        return 0.0
    return float(np.sqrt(np.mean(samples * samples)))


def save_wav(filename, frames, channels, sample_width, rate):
    """Persist PCM frames as a standard WAV file."""
    with wave.open(filename, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(sample_width)
        output.setframerate(rate)
        output.writeframes(b"".join(frames))
