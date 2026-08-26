"""Uniform, discoverable, explicitly registered B2 skills."""

import re
from dataclasses import dataclass
from importlib import metadata


@dataclass
class SkillResult:
    name: str
    content: str
    sources: list


class SkillRegistry:
    CALL_PATTERN = re.compile(
        r'<skill\s+name=["\']([a-z0-9_-]+)["\']>(.*?)</skill>',
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(self):
        self._skills = {}

    def register(self, skill):
        if (
            not getattr(skill, "name", None)
            or not getattr(skill, "description", None)
            or not callable(getattr(skill, "run", None))
        ):
            raise ValueError("a skill requires a name and run(request, context) entrypoint")
        if not callable(getattr(skill, "available", None)):
            raise ValueError("a skill requires available()")
        name = str(skill.name).lower()
        if not re.fullmatch(r"[a-z0-9_-]+", name):
            raise ValueError("skill names may contain only letters, numbers, _ and -")
        self._skills[name] = skill

    def discover(self, group="b2.skills"):
        """Load adult-installed Python entry points sharing the skill contract."""
        discovered = metadata.entry_points()
        entries = (
            discovered.select(group=group)
            if hasattr(discovered, "select")
            else discovered.get(group, [])
        )
        for entry in entries:
            try:
                factory = entry.load()
                skill = factory() if isinstance(factory, type) else factory
                self.register(skill)
            except Exception as error:
                print(f"Skill entry point {entry.name!r} unavailable: {error}")

    def extract(self, text):
        match = self.CALL_PATTERN.search(text or "")
        return (match.group(1).lower(), match.group(2).strip()) if match else None

    def run(self, name, request, context=None):
        skill = self._skills.get(name)
        if skill is None or not skill.available():
            raise ValueError(f"skill {name!r} is unavailable")
        return skill.run(request, context or {})

    def context(self):
        return {
            name: {
                "description": skill.description,
                "available": skill.available(),
                "entrypoint": f'<skill name="{name}">request</skill>',
            }
            for name, skill in sorted(self._skills.items())
        }


class WebSearchSkill:
    """SearXNG-compatible web search; disabled until an endpoint is configured."""

    name = "web_search"
    description = "Search the internet for current information and return cited results."

    def __init__(self, endpoint=None, timeout=12, maximum_results=5):
        self.endpoint = (endpoint or "").strip()
        self.timeout = timeout
        self.maximum_results = maximum_results

    def available(self):
        return self.endpoint.startswith(("http://", "https://"))

    def run(self, request, context=None):
        import requests

        response = requests.get(
            self.endpoint,
            params={"q": request, "format": "json"},
            headers={"User-Agent": "B2-Droid/0.12.4"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        if len(response.content) > 2 * 1024 * 1024:
            raise ValueError("search response exceeded 2 MiB")
        results = response.json().get("results", [])[:self.maximum_results]
        sources = [item.get("url") for item in results if item.get("url")]
        lines = [
            f"- {str(item.get('title', 'Result'))[:200]}: "
            f"{str(item.get('content', ''))[:700]} ({item.get('url', '')})"
            for item in results
        ]
        return SkillResult(self.name, "\n".join(lines) or "No results found.", sources)
