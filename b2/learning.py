"""Persistent, bounded calibration learned from explicit adult feedback."""

import json
import threading
from pathlib import Path


class LearningStore:
    """Store learned values separately from factory and adult configuration."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._values = self._load()

    def _load(self):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._values, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def get(self, namespace, key, default=None):
        with self._lock:
            return self._values.get(namespace, {}).get(key, default)

    def set_bounded(self, namespace, key, value, minimum, maximum, metadata=None):
        bounded = max(minimum, min(maximum, float(value)))
        with self._lock:
            bucket = self._values.setdefault(namespace, {})
            bucket[key] = bounded
            if metadata:
                bucket.setdefault("_metadata", {})[key] = metadata
            self._save()
        return bounded

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self._values))
