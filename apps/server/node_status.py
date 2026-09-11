from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

import platform_config

router = APIRouter(prefix="/api/v1")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status(last_seen: str | None) -> str:
    parsed = _parse_time(last_seen)
    if parsed is None:
        return "unknown"
    age = (datetime.now(timezone.utc) - parsed).total_seconds()
    if age <= 30 * 60:
        return "online"
    if age <= 24 * 3600:
        return "stale"
    return "offline"


def list_nodes() -> list[dict[str, Any]]:
    platform_config.init_platform_db()
    with platform_config._db() as conn:
        try:
            rows = conn.execute(
                """
                SELECT s.project_id, s.project_name, s.user_id, s.device_id,
                       s.workspace_name, s.received_at, s.observed_at
                FROM snapshots s
                INNER JOIN (
                    SELECT project_id, user_id, device_id, workspace_name, MAX(id) AS latest_id
                    FROM snapshots
                    GROUP BY project_id, user_id, device_id, workspace_name
                ) latest ON latest.latest_id = s.id
                ORDER BY s.received_at DESC, s.id DESC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        key = (str(item.get("user_id") or ""), str(item.get("device_id") or ""))
        node = grouped.setdefault(
            key,
            {
                "user_id": key[0],
                "device_id": key[1],
                "last_seen_at": item.get("received_at"),
                "projects": {},
                "workspace_count": 0,
            },
        )
        if str(item.get("received_at") or "") > str(node.get("last_seen_at") or ""):
            node["last_seen_at"] = item.get("received_at")
        project_id = str(item.get("project_id") or "")
        project = node["projects"].setdefault(
            project_id,
            {
                "project_id": project_id,
                "project_name": item.get("project_name") or project_id,
                "workspaces": [],
                "last_seen_at": item.get("received_at"),
            },
        )
        workspace = str(item.get("workspace_name") or "")
        if workspace and workspace not in project["workspaces"]:
            project["workspaces"].append(workspace)
        if str(item.get("received_at") or "") > str(project.get("last_seen_at") or ""):
            project["last_seen_at"] = item.get("received_at")
        node["workspace_count"] += 1

    result: list[dict[str, Any]] = []
    for node in grouped.values():
        projects = sorted(node.pop("projects").values(), key=lambda item: str(item.get("project_name") or ""))
        node["projects"] = projects
        node["project_count"] = len(projects)
        node["status"] = _status(node.get("last_seen_at"))
        result.append(node)
    return sorted(result, key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)


@router.get("/platform/nodes")
def get_platform_nodes() -> dict[str, Any]:
    nodes = list_nodes()
    summary = {"online": 0, "stale": 0, "offline": 0, "unknown": 0}
    for node in nodes:
        summary[node.get("status") or "unknown"] = summary.get(node.get("status") or "unknown", 0) + 1
    return {"count": len(nodes), "summary": summary, "nodes": nodes}
