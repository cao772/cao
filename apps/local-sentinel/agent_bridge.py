from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from multi_repository import inspect_repositories
from sentinel import COLLECTOR_TOKEN, CENTRAL_URL, DEVICE_ID, USER_ID, discover_projects, utc_now

AGENT_VENDOR = os.getenv("AGENT_VENDOR", "unknown").strip() or "unknown"
AGENT_NAME = os.getenv("AGENT_NAME", "coding-agent").strip() or "coding-agent"
AGENT_INSTANCE_ID = os.getenv("AGENT_INSTANCE_ID", "").strip() or None
HTTP_TIMEOUT_SECONDS = int(os.getenv("AGENT_BRIDGE_HTTP_TIMEOUT", "20"))


def _central_request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    if not CENTRAL_URL:
        raise RuntimeError("CENTRAL_URL is not configured")

    url = f"{CENTRAL_URL}{path}"
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "User-Agent": f"project-sentinel-agent-bridge/{AGENT_NAME}",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if COLLECTOR_TOKEN:
        headers["X-Collector-Token"] = COLLECTOR_TOKEN

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else None


def find_project(project_id: str) -> tuple[Path, dict[str, Any]]:
    wanted = str(project_id or "").strip()
    for project_root, manifest in discover_projects():
        project = manifest.get("project") or {}
        if str(project.get("id") or "").strip() == wanted:
            return project_root, manifest
    raise ValueError(f"managed project not found: {wanted}")


def _manifest_repositories(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    repositories = list(manifest.get("repositories") or [])
    if not repositories and manifest.get("repository"):
        repositories = [dict(manifest.get("repository") or {})]

    result: list[dict[str, Any]] = []
    for index, repository in enumerate(repositories, start=1):
        if not isinstance(repository, dict):
            continue
        result.append(
            {
                "id": repository.get("id") or f"repository-{index}",
                "role": repository.get("role") or ("primary" if index == 1 else "code"),
                "provider": repository.get("provider"),
                "url": repository.get("url"),
                "local_path": repository.get("local_path") or ".",
                "primary": bool(repository.get("primary", index == 1)),
            }
        )
    return result


def list_managed_projects() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for project_root, manifest in discover_projects():
        project = manifest.get("project") or {}
        result.append(
            {
                "project_id": project.get("id"),
                "project_name": project.get("name"),
                "owner": project.get("owner"),
                "team": project.get("team"),
                "workspace_name": project_root.name,
                "repositories": _manifest_repositories(manifest),
            }
        )
    return result


def _fresh_local_git(project_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    git_state, _runtime = inspect_repositories(project_root, manifest)
    return git_state


def _compact_central_context(raw: dict[str, Any]) -> dict[str, Any]:
    fusion = raw.get("evidence_fusion") or {}
    rollup = raw.get("project_rollup") or {}
    memory = raw.get("current_project_memory") or {}

    work_items: list[dict[str, Any]] = []
    for item in (fusion.get("work_items") or [])[:80]:
        work_items.append(
            {
                "task_id": item.get("task_id") or item.get("work_item_id"),
                "title": item.get("title"),
                "status": item.get("status"),
                "status_label": item.get("status_label"),
                "status_reasons": list(item.get("status_reasons") or [])[:8],
                "contributors": list(item.get("contributors") or [])[:20],
            }
        )

    return {
        "project_state": fusion.get("project_state") or rollup.get("project_state"),
        "project_state_label": fusion.get("project_state_label") or rollup.get("project_state_label"),
        "formal_completion_supported": fusion.get("formal_completion_supported", False),
        "summary": fusion.get("summary") or {},
        "work_items": work_items,
        "project_memory": {
            "current_stage": memory.get("current_stage"),
            "completed": list(memory.get("completed") or [])[:30],
            "in_progress": list(memory.get("in_progress") or [])[:30],
            "blockers": list(memory.get("blockers") or [])[:30],
            "risks": list(memory.get("risks") or [])[:30],
            "next_steps": list(memory.get("next_steps") or [])[:30],
            "milestones": list(memory.get("milestones") or [])[:30],
            "requirements": list(memory.get("requirements") or [])[:50],
            "tasks": list(memory.get("tasks") or [])[:50],
            "tests": list(memory.get("tests") or [])[:50],
        },
        "contributors": rollup.get("contributors") or [],
        "agents": rollup.get("agents") or [],
    }


def get_project_context(project_id: str) -> dict[str, Any]:
    project_root, manifest = find_project(project_id)
    project = manifest.get("project") or {}
    local_git = _fresh_local_git(project_root, manifest)

    central_context: dict[str, Any] | None = None
    central_error: str | None = None
    if CENTRAL_URL:
        encoded = urllib.parse.quote(str(project_id), safe="")
        try:
            raw = _central_request("GET", f"/api/v1/projects/{encoded}/current")
            if isinstance(raw, dict):
                central_context = _compact_central_context(raw)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            central_error = str(exc)

    return {
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
            "owner": project.get("owner"),
            "team": project.get("team"),
            "workspace_name": project_root.name,
            "repositories": _manifest_repositories(manifest),
        },
        "developer": {"user_id": USER_ID, "device_id": DEVICE_ID},
        "agent": {
            "vendor": AGENT_VENDOR,
            "name": AGENT_NAME,
            "instance_id": AGENT_INSTANCE_ID,
        },
        "local": {
            "observed_at": utc_now(),
            "git": local_git,
            "security_mode": (manifest.get("security") or {}).get("mode", "metadata_only"),
        },
        "central": central_context,
        "central_error": central_error,
        "note": (
            "local.git is refreshed when this tool is called; project documents and task memory come from the latest "
            "Sentinel snapshot already stored by the central service."
        ),
    }


def get_project_tasks(project_id: str) -> dict[str, Any]:
    if not CENTRAL_URL:
        return {
            "project_id": project_id,
            "central_available": False,
            "work_items": [],
            "note": "CENTRAL_URL is not configured; use get_project_context for local Git state.",
        }

    encoded = urllib.parse.quote(str(project_id), safe="")
    try:
        raw = _central_request("GET", f"/api/v1/projects/{encoded}/tasks")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {"project_id": project_id, "central_available": False, "error": str(exc), "work_items": []}

    if not isinstance(raw, dict):
        return {"project_id": project_id, "central_available": False, "work_items": []}
    return {
        "project_id": project_id,
        "central_available": True,
        "scope": raw.get("scope"),
        "summary": raw.get("summary") or {},
        "formal_completion_supported": raw.get("formal_completion_supported", False),
        "work_items": [
            {
                "task_id": item.get("task_id") or item.get("work_item_id"),
                "title": item.get("title"),
                "status": item.get("status"),
                "status_label": item.get("status_label"),
                "status_reasons": list(item.get("status_reasons") or [])[:8],
                "contributors": list(item.get("contributors") or [])[:20],
            }
            for item in (raw.get("work_items") or [])[:100]
        ],
    }


def build_agent_event(
    *,
    event_type: str,
    project_id: str,
    task_title: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_root, _manifest = find_project(project_id)
    payload_data = dict(data or {})
    payload_data.setdefault("workspace_name", project_root.name)
    payload_data.setdefault("device_id", DEVICE_ID)
    if AGENT_INSTANCE_ID:
        payload_data.setdefault("agent_instance_id", AGENT_INSTANCE_ID)

    return {
        "schema_version": 1,
        "event_type": str(event_type).strip(),
        "observed_at": utc_now(),
        "project_id": str(project_id).strip(),
        "user_id": USER_ID,
        "agent": {
            "vendor": AGENT_VENDOR,
            "name": AGENT_NAME,
            "instance_id": AGENT_INSTANCE_ID,
        },
        "session_id": str(session_id).strip() if session_id else None,
        "task_id": str(task_id).strip() if task_id else None,
        "task_title": str(task_title).strip() if task_title else None,
        "data": payload_data,
    }


def report_agent_event(
    *,
    event_type: str,
    project_id: str,
    task_title: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_agent_event(
        event_type=event_type,
        project_id=project_id,
        task_title=task_title,
        task_id=task_id,
        session_id=session_id,
        data=data,
    )
    if not CENTRAL_URL:
        return {
            "accepted": False,
            "central_available": False,
            "event": event,
            "note": "CENTRAL_URL is not configured, so the event was not persisted centrally.",
        }

    try:
        response = _central_request("POST", "/api/v1/agent-events", event)
        return {"accepted": True, "central_available": True, "response": response, "event": event}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "accepted": False,
            "central_available": False,
            "error": str(exc),
            "event": event,
        }
