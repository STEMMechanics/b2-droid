"""Load immutable project directives plus a persistent local override."""

from pathlib import Path

from .config import CONFIG_DIR, DATA_DIR

BASE_DIRECTIVES = CONFIG_DIR / "directives.txt"
OVERRIDE_DIRECTIVES = DATA_DIR / "directives.override.txt"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def load_directives() -> str:
    base = _read(BASE_DIRECTIVES)
    override = _read(OVERRIDE_DIRECTIVES)
    sections = [base]
    if override:
        sections.append(
            "Local directives (these override conflicting original directives):\n"
            + override
        )
    return "\n\n".join(filter(None, sections))


def save_override(text: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OVERRIDE_DIRECTIVES.with_suffix(".tmp")
    temporary.write_text(text.strip() + "\n", encoding="utf-8")
    temporary.replace(OVERRIDE_DIRECTIVES)
