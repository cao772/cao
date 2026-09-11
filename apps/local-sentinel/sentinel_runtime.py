from __future__ import annotations

import copy
import json
import os
import re
import time
import urllib.error
import urllib.request
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
VALID_ANALYSIS_INCLUDE = {"documents", "tests", "outputs"}


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


def _central_json(path: str, timeout: int = 8) -> dict[str, Any] | None:
    if not sentinel.CENTRAL_URL or not sentinel.COLLECTOR_TOKEN:
        return None
    request = urllib.request.Request(
        f"{sentinel.CENTRAL_URL}{path}",
        headers={
            "Accept": "application/json",
            "X-Collector-Token": sentinel.COLLECTOR_TOKEN,
            "User-Agent": "project-sentinel-runtime/0.7",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def load_central_project_settings() -> dict[str, dict[str, Any]]:
    payload = _central_json("/api/v1/internal/projects/runtime-settings") or {}
    projects = payload.get("projects")
    return projects if isinstance(projects, dict) else {}


def apply_central_model_config() -> dict[str, Any]:
    """Refresh model settings from Central, keeping existing env values as fallback."""
    payload = _central_json("/api/v1/internal/model/runtime-config")
    if not payload or not payload.get("configured"):
        return {"configured": False, "source": "environment"}
    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not base_url or not model:
        return {"configured": False, "source": "environment"}
    os.environ["LOCAL_LLM_BASE_URL"] = base_url
    os.environ["LOCAL_LLM_MODEL"] = model
    os.environ["LOCAL_LLM_API_KEY"] = str(payload.get("api_key") or "")
    os.environ["LOCAL_LLM_TIMEOUT"] = str(int(payload.get("timeout_seconds") or 60))
    os.environ["ALLOW_REMOTE_ANALYSIS_ENDPOINT"] = "true" if payload.get("allow_remote_endpoint") else "false"
    return {"configured": True, "source": "platform", "model": model}


def merged_runtime_bindings() -> dict[str, Any]:
    bindings = load_bindings()
    projects = bindings.setdefault("projects", {})
    for project_id, settings in load_central_project_settings().items():
        if not isinstance(settings, dict):
            continue
        project_cfg = projects.setdefault(str(project_id), {})
        project_cfg["policy"] = {
            "enabled": bool(settings.get("enabled", True)),
            "security_mode": settings.get("security_mode") or "metadata_only",
            "analysis_enabled": bool(settings.get("analysis_enabled", False)),
            "use_llm": bool(settings.get("use_llm", False)),
            "include": settings.get("include") or ["documents", "tests", "outputs"],
        }
    return bindings


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


def _runtime_policy(project_cfg: dict[str, Any]) -> dict[str, Any] | None:
    raw = project_cfg.get("policy")
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("security_mode") or "metadata_only")
    if mode not in {"metadata_only", "local_analysis"}:
        mode = "metadata_only"
    include = [str(item) for item in (raw.get("include") or []) if str(item) in VALID_ANALYSIS_INCLUDE]
    include = list(dict.fromkeys(include)) or ["documents", "tests", "outputs"]
    analysis_enabled = bool(raw.get("analysis_enabled") and mode == "local_analysis")
    return {
        "enabled": bool(raw.get("enabled", True)),
        "security_mode": mode,
        "analysis_enabled": analysis_enabled,
        "use_llm": bool(raw.get("use_llm") and analysis_enabled),
        "include": include,
    }


def _apply_policy(effective: dict[str, Any], policy: dict[str, Any] | None) -> None:
    if not policy:
        return
    security = effective.setdefault("security", {})
    security["mode"] = policy["security_mode"]
    security["scan_env_files"] = False
    security["upload_source_code"] = False
    security["upload_documents"] = False

    analysis = effective.setdefault("analysis", {})
    analysis["enabled"] = bool(policy["analysis_enabled"])
    analysis["use_llm"] = bool(policy["use_llm"])
    analysis["include"] = list(policy["include"])


def apply_runtime_bindings(project_root: Path, manifest: dict[str, Any], bindings: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    project_id = str((manifest.get("project") or {}).get("id") or "")
    project_cfg = (bindings.get("projects") or {}).get(project_id) or {}
    folders = project_cfg.get("folders") or []
    policy = _runtime_policy(project_cfg)
    if not folders and not policy:
        return manifest, {
            "applied": False,
            "selected": 0,
            "ignored_outside_project": [],
            "runtime_repositories": 0,
            "policy": None,
        }

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

    runtime_repositories = _runtime_repositories(project_root, selected["code"])
    if runtime_repositories:
        effective["repositories"] = runtime_repositories
        effective.pop("repository", None)
    _apply_policy(effective, policy)

    return effective, {
        "applied": bool(applied_count or policy),
        "selected": applied_count,
        "ignored_outside_project": outside,
        "runtime_repositories": len(runtime_repositories),
        "policy": policy,
    }


def build_managed_manifest(project_id: str, project_cfg: dict[str, Any]) -> dict[str, Any]:
    """Build a conservative manifest for a platform-created project without project.yaml."""
    folders = [item for item in (project_cfg.get("folders") or []) if isinstance(item, dict)]
    selected: dict[str, list[str]] = {value: [] for value in ROLE_TO_PATH_KEY.values()}
    for item in folders:
        role = str(item.get("role") or "")
        key = ROLE_TO_PATH_KEY.get(role)
        raw = str(item.get("path") or "").strip().replace("\\", "/").strip("/")
        if key and raw:
            selected[key].append(raw)

    repositories = _runtime_repositories(sentinel.PROJECTS_ROOT, list(dict.fromkeys(selected["code"])))
    manifest = {
        "version": 1,
        "project": {
            "id": project_id,
            "name": str(project_cfg.get("project_name") or project_id),
        },
        "repositories": repositories,
        "paths": {key: list(dict.fromkeys(values)) for key, values in selected.items()},
        "ignore": [
            "**/.git/**",
            "**/node_modules/**",
            "**/.venv/**",
            "**/__pycache__/**",
            "**/.DS_Store",
            "**/.env",
        ],
        "security": {
            "mode": "metadata_only",
            "scan_env_files": False,
            "upload_source_code": False,
            "upload_documents": False,
        },
        "analysis": {
            "enabled": False,
            "include": [key for key in ("documents", "tests", "outputs") if selected[key]],
            "use_llm": False,
        },
    }
    _apply_policy(manifest, _runtime_policy(project_cfg))
    return manifest


def scan_once(only_project_id: str | None = None) -> dict[str, Any]:
    model_runtime = apply_central_model_config()
    bindings = merged_runtime_bindings()
    binding_projects = bindings.get("projects") or {}
    matched = uploaded = skipped_disabled = 0
    projects = sentinel.discover_projects()
    discovered_ids: set[str] = set()

    for project_root, manifest in projects:
        project_id = str((manifest.get("project") or {}).get("id") or "")
        if not project_id:
            continue
        discovered_ids.add(project_id)
        if only_project_id and project_id != only_project_id:
            continue
        project_cfg = binding_projects.get(project_id) or {}
        policy = _runtime_policy(project_cfg) if isinstance(project_cfg, dict) else None
        if policy and not policy["enabled"]:
            skipped_disabled += 1
            continue
        matched += 1
        effective, overlay = apply_runtime_bindings(project_root, manifest, bindings)
        snapshot = sentinel.build_snapshot(project_root, effective)
        snapshot["local_binding_overlay"] = overlay
        snapshot["model_runtime"] = {"configured": bool(model_runtime.get("configured")), "source": model_runtime.get("source")}
        if sentinel.upload_snapshot(snapshot):
            uploaded += 1

    for raw_project_id, project_cfg in binding_projects.items():
        project_id = str(raw_project_id)
        if project_id in discovered_ids:
            continue
        if only_project_id and project_id != only_project_id:
            continue
        if not isinstance(project_cfg, dict) or not project_cfg.get("folders"):
            continue
        policy = _runtime_policy(project_cfg)
        if policy and not policy["enabled"]:
            skipped_disabled += 1
            continue
        matched += 1
        manifest = build_managed_manifest(project_id, project_cfg)
        snapshot = sentinel.build_snapshot(sentinel.PROJECTS_ROOT, manifest)
        snapshot["workspace_name"] = f"configured:{project_id}"
        snapshot["local_binding_overlay"] = {
            "applied": True,
            "selected": len(project_cfg.get("folders") or []),
            "ignored_outside_project": [],
            "runtime_repositories": len(manifest.get("repositories") or []),
            "managed_without_manifest": True,
            "policy": policy,
        }
        snapshot["model_runtime"] = {"configured": bool(model_runtime.get("configured")), "source": model_runtime.get("source")}
        if sentinel.upload_snapshot(snapshot):
            uploaded += 1

    return {
        "matched": matched,
        "uploaded": uploaded,
        "skipped_disabled": skipped_disabled,
        "model_configured": bool(model_runtime.get("configured")),
        "at": sentinel.utc_now(),
    }


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
