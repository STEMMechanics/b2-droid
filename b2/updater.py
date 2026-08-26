"""Safe, signed-offline-friendly removable-media update support."""

import hashlib
import json
import shutil
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Optional

from .config import APP_DIR, DATA_DIR, UPDATE_MEDIA_ROOT

MANIFEST_NAME = "b2-update.json"
SOURCE_MANIFEST_NAME = "b2-source-update.json"
PAYLOAD_NAME = "b2-update.tar.gz"
STATE_FILE = DATA_DIR / "update-state.json"
DATABASE_FILE = DATA_DIR / "b2.sqlite3"
BACKUP_DIR = DATA_DIR / "update-backups"
SEARCH_ROOTS = (
    UPDATE_MEDIA_ROOT, Path("/run/media"), Path("/mnt"),
    Path("/run/b2-update-media"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_update() -> Optional[Path]:
    candidates = []
    for root in SEARCH_ROOTS:
        if root.exists():
            for name in (MANIFEST_NAME, SOURCE_MANIFEST_NAME):
                candidates.extend(root.glob(name))
                candidates.extend(root.glob("*/" + name))
                candidates.extend(root.glob("*/*/" + name))
    installed_version = None
    if STATE_FILE.exists():
        try:
            installed_version = json.loads(
                STATE_FILE.read_text(encoding="utf-8")
            ).get("version")
        except (OSError, ValueError):
            pass
    for manifest in candidates:
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            continue
        if version and version != installed_version:
            return manifest
    return None


def _database_contract() -> int:
    if not DATABASE_FILE.exists():
        return 0
    try:
        with sqlite3.connect(str(DATABASE_FILE)) as database:
            row = database.execute(
                "SELECT version FROM schema_contracts WHERE name='entities'"
            ).fetchone()
            return int(row[0]) if row else 0
    except (sqlite3.Error, TypeError, ValueError):
        return 0


def _check_database_compatibility(manifest):
    compatibility = manifest.get("database_compatibility")
    if not compatibility:
        # Legacy packages pre-date the extensible entity contract. They do not
        # know the new tables, but SQLite preserves tables they never touch.
        return
    current = _database_contract()
    minimum = int(compatibility.get("min", 0))
    maximum = int(compatibility.get("max", minimum))
    if not minimum <= current <= maximum:
        raise ValueError(
            f"database contract {current} is outside package range "
            f"{minimum}..{maximum}"
        )


def _backup_database(version):
    if not DATABASE_FILE.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    safe_version = "".join(
        character for character in str(version) if character.isalnum() or character in ".-_"
    ) or "unknown"
    destination = BACKUP_DIR / f"before-{safe_version}-{int(time.time())}.sqlite3"
    with sqlite3.connect(str(DATABASE_FILE)) as source:
        with sqlite3.connect(str(destination)) as target:
            source.backup(target)
    return destination


def _stage_source_tree(manifest_path, staging):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if int(manifest.get("source_update_format", 0)) != 1:
        raise ValueError("unsupported source update marker")
    source = manifest_path.parent.resolve()
    required = (
        source / "scripts" / "install.sh", source / "pyproject.toml",
        source / "droid.py", source / "b2",
    )
    if not all(path.exists() for path in required):
        raise ValueError("marked source tree is incomplete")
    ignored_names = {
        ".git", ".venv", "data", "__pycache__", "whisper.cpp",
        "llama.cpp", "voices",
    }
    total = 0
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in ignored_names for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("source updates may not contain symbolic links")
        if path.is_file():
            total += path.stat().st_size
            if total > 2 * 1024 * 1024 * 1024:
                raise ValueError("source update exceeds 2 GiB")
        elif not path.is_dir():
            raise ValueError("source update contains an unsupported special file")
    shutil.copytree(
        source, staging,
        ignore=shutil.ignore_patterns(
            *ignored_names, "yolo11n.onnx", "yolo11n.pt",
        ),
    )


def _stage_archive(manifest_path, staging, manifest):
    payload = manifest_path.parent / PAYLOAD_NAME
    if not payload.is_file():
        raise ValueError("update payload is missing")
    expected = str(manifest.get("sha256", "")).lower()
    if not expected or _sha256(payload) != expected:
        raise ValueError("update checksum does not match")
    staging.mkdir()
    with tarfile.open(payload, "r:gz") as archive:
        for member in archive.getmembers():
            target = (staging / member.name).resolve()
            if staging.resolve() not in target.parents and target != staging.resolve():
                raise ValueError("update contains an unsafe path")
            if member.issym() or member.islnk():
                raise ValueError("update links are not allowed")
            if not (member.isdir() or member.isreg()):
                raise ValueError("update contains an unsupported special file")
        archive.extractall(staging)


def apply_update(manifest_path: Path) -> bool:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        raise ValueError("update version is missing")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current = {}
    if STATE_FILE.exists():
        current = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if current.get("version") == manifest.get("version"):
        return False
    _check_database_compatibility(manifest)

    staging = DATA_DIR / "update-staging"
    if staging.exists():
        shutil.rmtree(staging)
    if manifest_path.name == SOURCE_MANIFEST_NAME:
        _stage_source_tree(manifest_path, staging)
        update_format = "source-tree"
    else:
        _stage_archive(manifest_path, staging, manifest)
        update_format = "checksummed-archive"
    backup = _backup_database(manifest.get("version"))
    installer = staging / "scripts" / "install.sh"
    if not installer.is_file():
        raise ValueError("update installer is missing")
    subprocess.run([str(installer), "--update", str(staging)], check=True)
    history = current.get("history", [])
    history.append({
        "from": current.get("version"), "to": manifest["version"],
        "database_backup": str(backup) if backup else None,
        "format": update_format,
        "at": int(time.time()),
    })
    STATE_FILE.write_text(
        json.dumps({"version": manifest["version"], "history": history[-50:]}) + "\n",
        encoding="utf-8",
    )
    shutil.rmtree(staging)
    return True
