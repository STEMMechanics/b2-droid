"""Environment-backed paths shared by the runtime and installer."""

from pathlib import Path
import os


APP_DIR = Path(os.environ.get("B2_APP_DIR", Path(__file__).resolve().parents[1]))
DATA_DIR = Path(os.environ.get("B2_DATA_DIR", APP_DIR / "data"))
CONFIG_DIR = Path(os.environ.get("B2_CONFIG_DIR", APP_DIR / "config"))
UPDATE_MEDIA_ROOT = Path(os.environ.get("B2_UPDATE_MEDIA_ROOT", "/media"))


def ensure_runtime_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
