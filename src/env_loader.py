from __future__ import annotations

import os
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]


def _parse_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_env_file(path: Path, protected_keys: set[str], *, override: bool = False) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key.startswith("#") or key in protected_keys:
            continue
        value = _parse_env_value(value)
        if value == "":
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def load_env_files(repo_dir: Path = REPO_DIR) -> None:
    protected_keys = set(os.environ)
    _load_env_file(repo_dir / ".env", protected_keys)
    _load_env_file(repo_dir / ".env.local", protected_keys, override=True)
