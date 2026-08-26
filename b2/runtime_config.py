"""Allow-listed runtime configuration requests shared with the root watcher."""

import json
import os
import re
from pathlib import Path

from .config import DATA_DIR


REQUEST_FILE = DATA_DIR / "runtime-config-request.json"
RESULT_FILE = DATA_DIR / "runtime-config-result.json"
ENV_FILE = Path("/etc/b2-droid.env")

SCHEMA = {
    "B2_AUDIO_DEVICE": ("device", "plughw:1,0"),
    "B2_OUTPUT_DEVICE": ("device", "plughw:1,0"),
    "B2_CAMERA": ("camera", "/dev/video0"),
    "B2_MIN_SPEECH_THRESHOLD": ("float", 100, 20, 5000),
    "B2_VOLUME": ("int", 100, 0, 100),
    "B2_STARTUP_VOLUME_FLOOR": ("int", 100, 0, 100),
    "B2_AUTO_VOLUME": ("bool", True),
    "B2_MOTOR_STARTUP_FLOOR": ("int", 220, 0, 255),
    "B2_MOTOR_SPEED_MAX": ("int", 240, 0, 255),
    "B2_MOTOR_STALL_COOLDOWN": ("float", 30, 1, 600),
}


def _validate(key, value):
    specification = SCHEMA[key]
    kind = specification[0]
    if kind == "device":
        value = str(value).strip()
        if not re.fullmatch(
            r"(?:default|(?:plug)?hw:(?:\d+,\d+|CARD=[A-Za-z0-9_]+,DEV=\d+))",
            value,
        ):
            raise ValueError(f"invalid ALSA device for {key}")
        return value
    if kind == "camera":
        value = str(value).strip()
        if not re.fullmatch(r"/dev/video\d+", value):
            raise ValueError("camera must be a /dev/videoN device")
        return value
    if kind == "bool":
        if isinstance(value, bool):
            return "true" if value else "false"
        if str(value).lower() in {"true", "1", "yes", "on"}:
            return "true"
        if str(value).lower() in {"false", "0", "no", "off"}:
            return "false"
        raise ValueError(f"invalid Boolean for {key}")
    number = float(value)
    minimum, maximum = specification[2:4]
    if not minimum <= number <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return str(int(number)) if kind == "int" else str(number)


def visible_config():
    values = {}
    for key, specification in SCHEMA.items():
        default = specification[1]
        raw = os.environ.get(key, str(default).lower() if isinstance(default, bool) else str(default))
        if specification[0] == "bool":
            values[key] = raw.lower() in {"true", "1", "yes", "on"}
        elif specification[0] == "int":
            values[key] = int(float(raw))
        elif specification[0] == "float":
            values[key] = float(raw)
        else:
            values[key] = raw
    result = None
    try:
        result = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"settings": values, "last_result": result, "restart_required": True}


def request_config(changes):
    if not isinstance(changes, dict):
        raise ValueError("settings must be an object")
    unknown = sorted(set(changes) - set(SCHEMA))
    if unknown:
        raise ValueError("unsupported settings: " + ", ".join(unknown))
    validated = {key: _validate(key, value) for key, value in changes.items()}
    if not validated:
        raise ValueError("no settings supplied")
    temporary = REQUEST_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"settings": validated}) + "\n", encoding="utf-8")
    temporary.replace(REQUEST_FILE)
    return {"accepted": True, "settings": validated, "message": "Saved; B2 will restart shortly."}


def apply_pending_request():
    """Root-only watcher entrypoint. Return True when B2 must restart."""
    if not REQUEST_FILE.is_file():
        return False
    try:
        payload = json.loads(REQUEST_FILE.read_text(encoding="utf-8"))
        settings = payload.get("settings", {})
        validated = {key: _validate(key, value) for key, value in settings.items() if key in SCHEMA}
        if set(validated) != set(settings) or not validated:
            raise ValueError("request contains unsupported or empty settings")
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
        remaining = dict(validated)
        output = []
        for line in lines:
            key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
            else:
                output.append(line)
        output.extend(f"{key}={value}" for key, value in remaining.items())
        temporary = ENV_FILE.with_suffix(".tmp")
        temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(ENV_FILE)
        result = {"ok": True, "applied": validated}
    except Exception as error:
        result = {"ok": False, "error": str(error)}
    RESULT_FILE.write_text(json.dumps(result) + "\n", encoding="utf-8")
    REQUEST_FILE.unlink(missing_ok=True)
    return bool(result.get("ok"))
