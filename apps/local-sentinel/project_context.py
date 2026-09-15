from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

CONTEXT_DIR = ".project-intelligence"
CONTEXT_FILE = "project_context.yaml"
CONTEXT_SCHEMA_VERSION = 1
MAX_LIST_ITEMS = 500
MAX_STRING_LENGTH = 4000
SENSITIVE_KEYS = {
    "api_key",
    "access_token",
    "token",
    "password",
    "secret",
    "private_key",
    "client_secret",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def context_path(project_root: Path) -> Path:
    return project_root / CONTEXT_DIR / CONTEXT_FILE


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return None
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:MAX_LIST_ITEMS]:
            key = str(raw_key)[:200]
            if key.lower() in SENSITIVE_KEYS:
                result[key] = "<redacted>"
                continue
            cleaned = _sanitize(raw_value, depth=depth + 1)
            if cleaned is not None:
                result[key] = cleaned
        return result
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value[:MAX_LIST_ITEMS]]
    if isinstance(value, tuple):
        return [_sanitize(item, depth=depth + 1) for item in value[:MAX_LIST_ITEMS]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return value[:MAX_STRING_LENGTH]
        return value
    return str(value)[:MAX_STRING_LENGTH]


def _load_raw(project_root: Path) -> tuple[Path, dict[str, Any] | None, str | None]:
    path = context_path(project_root)
    if not path.is_file():
        return path, None, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # malformed YAML must never stop Sentinel scans
        return path, None, f"{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return path, None, "project_context.yaml must contain a mapping"
    return path, data, None


def load_project_context(project_root: Path) -> dict[str, Any]:
    path, data, error = _load_raw(project_root)
    if data is None:
        return {
            "present": path.is_file(),
            "path": f"{CONTEXT_DIR}/{CONTEXT_FILE}",
            "valid": False if path.is_file() else None,
            "error": error,
            "data": None,
        }

    schema_version = int(data.get("schema_version") or 0)
    valid = schema_version == CONTEXT_SCHEMA_VERSION
    try:
        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    except OSError:
        modified_at = None

    return {
        "present": True,
        "path": f"{CONTEXT_DIR}/{CONTEXT_FILE}",
        "valid": valid,
        "error": None if valid else f"unsupported schema_version: {schema_version}",
        "modified_at": modified_at,
        "data": _sanitize(data),
    }


def write_project_context(
    project_root: Path,
    updates: dict[str, Any],
    *,
    generator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(updates, dict):
        raise ValueError("context updates must be an object")

    path, existing, _error = _load_raw(project_root)
    current = dict(existing or {})
    current["schema_version"] = CONTEXT_SCHEMA_VERSION

    for key, value in updates.items():
        if key in {"schema_version", "generated_at", "generator"}:
            continue
        current[str(key)] = _sanitize(value)

    current["generated_at"] = utc_now()
    if generator:
        current["generator"] = _sanitize(generator)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump(current, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    temporary.replace(path)
    return load_project_context(project_root)
