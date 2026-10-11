"""Configuration loading and small file helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


def load_config(path: str | Path) -> dict:
    """Read config.yaml. All relative paths inside it are resolved against its folder."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = str(path.parent)
    cfg["_config_path"] = str(path)
    return cfg


def resolve(cfg: dict, relative: str | Path) -> Path:
    """Turn a path from the config into an absolute path."""
    return (Path(cfg["_root"]) / relative).resolve()


def sha256_file(path: str | Path) -> str:
    """SHA-256 of a file, used to log exactly which inputs a run used."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
