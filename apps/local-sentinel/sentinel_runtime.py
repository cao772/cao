from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Any

import sentinel

BINDINGS_PATH = sentinel.STATE_ROOT / "local-project-bindings.json"
ROLE_TO_PATH_KEY = {
    "code": "code",
    "documents": "documents",
    "tests": "tests",
    "outputs": "outputs",
}


def load_bindings() -> dict[str, Any]:
    if not BINDINGS_PATH.exists():
        return {"version": 1, "projects": {}}
    try:
        data = json.loads(BINDINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "projects": {}}
    if not isinstance(data, dict):
        return {"version": 1, "projects": {}}
    data.setdefault("projects", {})
    return data


def _runtime_repositories(project_root: Path, code_paths: list[str]) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    for index, relative in enumerate(code_paths):
        candidate = (project_root / relative).resolve()
        if not (candidate / ".git").exists():
            continue
        _, remote = sentinel.run_git(candidate, "remote", "get-url", "origin")
        provider = "other"
        lowered = remote.lower()
        if "gitlab" in lowered or "git.hyetec.com" in lowered:
            provider = "gitlab"
        elif "github.com" in lowered:
            provider = "github"
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(relative).name).strip("-") or f"repo-{index + 1}"
        repositories.append(
            {
                "id": f"local-{safe_name}",
                "role": "application",
                "provider": provider,
                "url": remote or f"local://{relative}",
                "local_path": relative,
                "primary": index == 0,
            }
        )
    return repositories


def apply_runtime_bindings(project_root: Path, manifest: dict[str, Any], bindings: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    project_id = str((manifest.get("project") or {}).get("id") or "")
    project_cfg = (bindings.get("projects") or {}).get(project_id) or {}
    folders = project_cfg.get("folders") or []
    if not folders:
        return manifest, {"applied": False, "selected": 0, "ignored_outside_project": [], "runtime_repositories": 0}

    root = project_root.resolve()
    selected: dict[str, list[str]] = {value: [] for value in ROLE_TO_PATH_KEY.values()}
    outside: list[str] = []
    for item in folders:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        key = ROLE_TO_PATH_KEY.get(role)
        raw = str(item.get("path") or "").strip().replace("\\", "/").strip("/")
        if not key or not raw:
            continue
        candidate = (sentinel.PROJECTS_ROOT / raw).resolve()
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            outside.append(raw)
            continue
        selected[key].append(relative or ".")

    effective = copy.deepcopy(manifest)
    paths = effective.setdefault("paths", {})
    applied_count = 0
    for key, values in selected.items():
        if values:
            paths[key] = list(dict.fromkeys(values))
            applied_count += len(values)

    # Selected document/test/output folders become the analysis scope. Code selection
    # affects repository inspection, but does not automatically enable source-body LLM analysis.
    analysis = effective.setdefault("analysis", {})
    include = set(analysis.get("include") or ["documents", "tests", "outputs"])
    for key in ("documents", "tests", "outputs"):
        if selected.get(key):
            include.add(key)
    analysis["include"] = [key for key in ("documents", "tests", "outputs", "code") if key in include]

    runtime_repositories = _runtime_repositories(project_root, selected["code"])
    if runtime_repositories:
        effective["repositories"] = runtime_repositories
        effective.pop("repository", None)

    return effective, {
        "applied": bool(applied_count),
        "selected": applied_count,
        "ignored_outside_project": outside,
        "runtime_repositories": len(runtime_repositories),
    }


def scan_once(only_project_id: str | None = None) -> dict[str, Any]:
    bindings = load_bindings()
    matched = uploaded = 0
    projects = sentinel.discover_projects()
    for project_root, manifest in projects:
        project_id = str((manifest.get("project") or {}).get("id") or "")
        if only_project_id and project_id != only_project_id:
            continue
        matched += 1
        effective, overlay = apply_runtime_bindings(project_root, manifest, bindings)
        snapshot = sentinel.build_snapshot(project_root, effective)
        snapshot["local_binding_overlay"] = overlay
        if sentinel.upload_snapshot(snapshot):
            uploaded += 1
    return {"matched": matched, "uploaded": uploaded, "at": sentinel.utc_now()}


def main() -> None:
    sentinel.STATE_ROOT.mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        "service": "project-sentinel-runtime",
        "version": sentinel.SENTINEL_VERSION,
        "projects_root": str(sentinel.PROJECTS_ROOT),
        "state_root": str(sentinel.STATE_ROOT),
        "interval_seconds": sentinel.INTERVAL_SECONDS,
    }, ensure_ascii=False))
    while True:
        try:
            result = scan_once()
            print(json.dumps({"level": "info", **result}, ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"level": "error", "error": str(exc), "at": sentinel.utc_now()}, ensure_ascii=False))
        time.sleep(max(sentinel.INTERVAL_SECONDS, 10))


if __name__ == "__main__":
    main()
