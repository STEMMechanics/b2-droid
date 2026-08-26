"""Discover ALSA capture and playback endpoints without binding to card order."""

import re
import subprocess


DEVICE_LINE = re.compile(
    r"^card\s+(\d+):\s*([^\[]+)\[[^]]*\],\s*device\s+(\d+):\s*([^\[]+)"
)


def _list(command):
    try:
        result = subprocess.run(
            [command, "-l"], capture_output=True, text=True, check=False,
        )
    except OSError as error:
        return [], str(error)
    devices = []
    for line in result.stdout.splitlines():
        match = DEVICE_LINE.match(line.strip())
        if not match:
            continue
        card, card_name, device, device_name = match.groups()
        card_id = card_name.strip()
        devices.append({
            "device": f"plughw:CARD={card_id},DEV={device}",
            "numeric_device": f"plughw:{card},{device}",
            "card": int(card),
            "card_name": card_id,
            "device_number": int(device),
            "name": device_name.strip(),
            "label": f"{card_name.strip()} — {device_name.strip()} (card {card}, device {device})",
        })
    error = None if devices else (result.stderr.strip() or "No ALSA devices found")
    return devices, error


def discover_audio_devices():
    capture, capture_error = _list("arecord")
    playback, playback_error = _list("aplay")

    def capture_rank(item):
        text = (item["card_name"] + " " + item["name"]).lower()
        return (0 if any(word in text for word in ("usb", "webcam", "camera")) else 1,
                item["card"], item["device_number"])

    def playback_rank(item):
        text = (item["card_name"] + " " + item["name"]).lower()
        return (0 if "analog" in text else 1, 1 if "hdmi" in text else 0,
                item["card"], item["device_number"])

    return {
        "capture": capture,
        "playback": playback,
        "recommended_capture": min(capture, key=capture_rank)["device"] if capture else None,
        "recommended_playback": min(playback, key=playback_rank)["device"] if playback else None,
        "capture_error": capture_error,
        "playback_error": playback_error,
    }
