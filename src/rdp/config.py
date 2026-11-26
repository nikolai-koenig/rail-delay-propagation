"""Environment and path configuration."""

from __future__ import annotations

import os
import re
import socket
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def load_env() -> None:
    """Load ``.env`` from the repo root without overriding real env vars."""
    load_dotenv(REPO_ROOT / ".env", override=False)


def env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        value = default
    if required and not value:
        raise SystemExit(f"Missing required environment variable {name} (see .env.example)")
    return value


def data_dir() -> Path:
    path = Path(env("RDP_DATA_DIR", "data/local"))
    return path if path.is_absolute() else REPO_ROOT / path


def host_tag() -> str:
    raw = env("RDP_HOST_TAG") or socket.gethostname()
    tag = re.sub(r"[^A-Za-z0-9-]+", "-", raw).strip("-").lower()
    return tag or "host"
