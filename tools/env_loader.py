"""Small dependency-free env-file loader for local Astra tools."""

from __future__ import annotations

from pathlib import Path
import os


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILES = (REPO_ROOT / ".env", REPO_ROOT / ".secrets.env")


def load_env_files(paths: tuple[Path, ...] = DEFAULT_ENV_FILES) -> dict[str, str]:
    """Load env files into `os.environ` without overwriting existing values."""
    loaded: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(line)
            if parsed is None:
                continue
            key, value = parsed
            loaded[key] = value
            os.environ.setdefault(key, value)
    return loaded


def getenv(name: str, default: str | None = None) -> str | None:
    """Return one environment value after loading local env files."""
    load_env_files()
    return os.environ.get(name, default)


def _parse_env_line(line: str) -> tuple[str, str] | None:
    """Parse one simple KEY=VALUE env-file line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, _unquote(value.strip())


def _unquote(value: str) -> str:
    """Remove matching single or double quotes from an env value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
