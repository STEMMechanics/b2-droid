"""Composable context and feature descriptions for the local language model."""

import json
import threading
from pathlib import Path


class ContextRegistry:
    """Collect named context providers without coupling them to the LLM client."""

    def __init__(self):
        self._providers = {}
        self._lock = threading.RLock()

    def register(self, name, provider):
        """Register a callable returning text, a mapping, a sequence, or None."""
        with self._lock:
            self._providers[name] = provider

    def unregister(self, name):
        with self._lock:
            self._providers.pop(name, None)

    def snapshot(self):
        with self._lock:
            providers = list(self._providers.items())
        result = {}
        for name, provider in providers:
            try:
                value = provider()
                if value not in (None, "", [], {}):
                    result[name] = value
            except Exception as error:
                result[name] = {"status": "unavailable", "error": str(error)}
        return result

    def render(self):
        """Render stable, clearly delimited model context."""
        sections = []
        for name, value in self.snapshot().items():
            if isinstance(value, str):
                rendered = value
            else:
                rendered = json.dumps(value, ensure_ascii=True, sort_keys=True)
            sections.append(f"[{name}]\n{rendered}")
        return "\n\n".join(sections)


class FeatureCatalog:
    """Load declarative capabilities that are automatically shown to the LLM."""

    def __init__(self, path):
        self.path = Path(path)

    def snapshot(self):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"features": []}
        return payload if isinstance(payload, dict) else {"features": []}

    def render(self):
        payload = self.snapshot()
        lines = []
        for feature in payload.get("features", []):
            if not isinstance(feature, dict) or not feature.get("name"):
                continue
            line = f"- {feature['name']}: {feature.get('description', '')}".rstrip()
            actions = feature.get("actions", [])
            if actions:
                line += " Actions: " + ", ".join(str(item) for item in actions)
            lines.append(line)
        return "Available services and features:\n" + ("\n".join(lines) or "- none")


class ContextDirectory:
    """Load adult-managed context fragments from a persistent directory."""

    def __init__(self, path, maximum_file_bytes=32768):
        self.path = Path(path)
        self.maximum_file_bytes = maximum_file_bytes

    def snapshot(self):
        result = {}
        try:
            paths = sorted(self.path.iterdir())
        except OSError:
            return result
        for path in paths:
            if not path.is_file() or path.stat().st_size > self.maximum_file_bytes:
                continue
            try:
                if path.suffix.lower() == ".json":
                    result[path.stem] = json.loads(path.read_text(encoding="utf-8"))
                elif path.suffix.lower() in {".txt", ".md"}:
                    result[path.stem] = path.read_text(encoding="utf-8").strip()
            except (OSError, ValueError) as error:
                result[path.stem] = {"status": "invalid", "error": str(error)}
        return result
