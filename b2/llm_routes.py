"""Validated, dashboard-managed LiteLLM connection priority."""

import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_CONNECTION = {
    "id": "local-ai",
    "label": "Local AI",
    "model": "openai/local-ai",
    "api_base": "http://127.0.0.1:8080/v1",
    "api_key": "local",
    "enabled": True,
    "priority": 0,
    "timeout": 60,
}


class LLMRouteStore:
    """Store a small ordered route list; secrets are never returned by snapshot."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    @staticmethod
    def _validate(connection, existing_key=None):
        if not isinstance(connection, dict):
            raise ValueError("each LLM connection must be an object")
        identifier = str(connection.get("id", "")).strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", identifier):
            raise ValueError("connection id must use lowercase letters, digits, dash, or underscore")
        label = str(connection.get("label", identifier)).strip()
        if not label or len(label) > 80:
            raise ValueError("connection label must be 1-80 characters")
        model = str(connection.get("model", "")).strip()
        if not model or len(model) > 160 or not re.fullmatch(r"[A-Za-z0-9._:/-]+", model):
            raise ValueError("invalid LiteLLM model name")
        api_base = str(connection.get("api_base") or "").strip().rstrip("/")
        if api_base:
            parsed = urlparse(api_base)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError("API base must be an HTTP(S) URL without embedded credentials")
        supplied_key = connection.get("api_key")
        api_key = existing_key if supplied_key in (None, "") else str(supplied_key).strip()
        if not api_key:
            raise ValueError("an API key is required")
        priority = int(connection.get("priority", 100))
        timeout = float(connection.get("timeout", 30))
        if not 0 <= priority <= 999:
            raise ValueError("priority must be between 0 and 999")
        if not 2 <= timeout <= 120:
            raise ValueError("timeout must be between 2 and 120 seconds")
        return {
            "id": identifier, "label": label, "model": model,
            "api_base": api_base or None, "api_key": api_key,
            "enabled": bool(connection.get("enabled", True)),
            "priority": priority, "timeout": timeout,
        }

    def _read_unlocked(self):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            raw = payload.get("connections", [])
            if not isinstance(raw, list):
                raise ValueError("connections must be a list")
            connections = [self._validate(item) for item in raw]
            if connections:
                return sorted(connections, key=lambda item: (item["priority"], item["id"]))
        except FileNotFoundError:
            pass
        except (OSError, TypeError, ValueError) as error:
            print(f"LLM route configuration unavailable: {error}; using local-ai.")
        return [dict(DEFAULT_CONNECTION)]

    def connections(self):
        with self._lock:
            return self._read_unlocked()

    def snapshot(self):
        return {
            "connections": [
                {key: value for key, value in item.items() if key != "api_key"}
                | {"has_api_key": bool(item.get("api_key"))}
                for item in self.connections()
            ],
            "default": "local-ai",
        }

    def replace(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("connections"), list):
            raise ValueError("connections must be supplied as a list")
        with self._lock:
            existing = {item["id"]: item for item in self._read_unlocked()}
            connections = []
            seen = set()
            for raw in payload["connections"]:
                identifier = str(raw.get("id", "")).strip().lower() if isinstance(raw, dict) else ""
                item = self._validate(raw, existing.get(identifier, {}).get("api_key"))
                if item["id"] in seen:
                    raise ValueError(f"duplicate connection id {item['id']}")
                seen.add(item["id"])
                connections.append(item)
            if not connections:
                raise ValueError("at least one LLM connection is required")
            if not any(item["enabled"] for item in connections):
                raise ValueError("at least one LLM connection must be enabled")
            connections.sort(key=lambda item: (item["priority"], item["id"]))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"connections": connections}, indent=2) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)
        return self.snapshot()
