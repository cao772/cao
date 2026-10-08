from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

import main

router = APIRouter(prefix="/api/v1/personal-agent", tags=["personal-agent"])

ATTENTION_STATUSES = {
    "blocked",
    "test_failing",
    "remote_ci_failed",
    "deployment_failed",
}
ACTIVE_STATUSES = {
    "creating_workspace",
    "starting_agent",
    "agent_started",
}
NEEDS_USER_EXECUTION_STATUSES = {
    "blocked_compatibility",
    "unknown",
}


def _compact(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def _projects() -> list[dict[str, Any]]:
    with main.get_db() as conn:
        rows = conn.execute(
            "SELECT project_id, project_name, last_seen_at "
            "FROM projects ORDER BY last_seen_at DESC, project_id ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def _execution_rows(limit: int = 100) -> list[dict[str, Any]]:
    with main.get_db() as conn:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='executions'"
        ).fetchone()
        if table is None:
            return []
        rows = conn.execute(
            "SELECT result_json FROM executions ORDER BY rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()

    executions: list[dict[str, Any]] = []
    for row in rows:
        try:
            item = json.loads(row[0])
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict):
            executions.append(item)
    return executions


def _safe_execution(item: dict[str, Any]) -> dict[str, Any]:
    status = _compact(item.get("status"), 40) or "unknown"
    runtime = _compact(item.get("runtime_status"), 40) or None
    return {
        "execution_id": _compact(item.get("id"), 80) or None,
        "project_id": _compact(item.get("project_id"), 200) or None,
        "repository_id": _compact(item.get("repository_id"), 200) or None,
        "task_id": _compact(item.get("task_id"), 200) or None,
        "task_title": _compact(item.get("task_title"), 160) or None,
        "status": status,
        "runtime_status": runtime,
        "formal_completion": bool(item.get("formal_completion", False)),
        "needs_user": status in NEEDS_USER_EXECUTION_STATUSES,
        "updated_at": _compact(item.get("updated_at"), 80) or None,
    }


def _loop(
    project: dict[str, Any],
    *,
    loop_type: str,
    text: Any,
    priority: int,
    needs_user: bool,
    source: str,
) -> dict[str, Any] | None:
    compact = _compact(text)
    if not compact:
        return None
    return {
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "type": loop_type,
        "text": compact,
        "priority": priority,
        "needs_user": needs_user,
        "source": source,
    }


def collect_open_loops() -> list[dict[str, Any]]:
    projects = _projects()
    by_id = {str(item["project_id"]): item for item in projects}
    loops: list[dict[str, Any]] = []

    for project in projects:
        project_id = str(project["project_id"])
        try:
            brief = main.project_brief(project_id)
        except HTTPException:
            continue
        for issue in list(brief.get("issues") or [])[:3]:
            item = _loop(
                project,
                loop_type="blocker",
                text=issue,
                priority=100,
                needs_user=True,
                source="project_brief",
            )
            if item:
                loops.append(item)
        for step in list(brief.get("next_steps") or [])[:3]:
            item = _loop(
                project,
                loop_type="next_step",
                text=step,
                priority=60,
                needs_user=False,
                source="project_brief",
            )
            if item:
                loops.append(item)

    for raw in _execution_rows():
        execution = _safe_execution(raw)
        project = by_id.get(str(execution.get("project_id") or ""))
        if project is None:
            continue
        status = str(execution["status"])
        if status not in ACTIVE_STATUSES | NEEDS_USER_EXECUTION_STATUSES:
            continue
        if status in NEEDS_USER_EXECUTION_STATUSES:
            priority = 95
            loop_type = "execution_needs_attention"
        else:
            priority = 70
            loop_type = "execution_running"
        item = _loop(
            project,
            loop_type=loop_type,
            text=execution.get("task_title") or execution.get("task_id") or "Codex execution",
            priority=priority,
            needs_user=bool(execution["needs_user"]),
            source="execution",
        )
        if item:
            item["execution_id"] = execution["execution_id"]
            item["execution_status"] = status
            loops.append(item)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in sorted(
        loops,
        key=lambda value: (-int(value["priority"]), str(value["project_name"]), str(value["text"])),
    ):
        key = (str(item["project_id"]), str(item["type"]), str(item["text"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def completion_judgement(project_id: str) -> dict[str, Any]:
    try:
        evidence = main.project_evidence(project_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "项目完成判定暂时不可用") from None

    work_items = [
        item for item in (evidence.get("work_items") or []) if isinstance(item, dict)
    ]
    status_counts: dict[str, int] = {}
    safe_items: list[dict[str, Any]] = []
    for item in work_items:
        status = _compact(item.get("status"), 80) or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        safe_items.append(
            {
                "title": _compact(item.get("title"), 180),
                "status": status,
                "status_label": _compact(item.get("status_label"), 80) or status,
                "evidence_count": int(item.get("evidence_count") or len(item.get("evidence") or [])),
            }
        )

    formal_supported = bool(evidence.get("formal_completion_supported"))
    completed = status_counts.get("completed", 0)
    attention = sum(status_counts.get(status, 0) for status in ATTENTION_STATUSES)
    unresolved = len(work_items) - completed

    if attention:
        verdict = "attention"
        reason = "存在失败或阻塞证据，不能判定完成。"
    elif work_items and formal_supported and unresolved == 0:
        verdict = "tracked_scope_complete"
        reason = "当前已跟踪事项均具备正式完成证据；这不等于整个项目永久完成。"
    elif work_items:
        verdict = "not_complete"
        reason = "仍有已跟踪事项缺少正式完成证据。"
    else:
        verdict = "insufficient_evidence"
        reason = "当前没有足够的已跟踪事项证据，不能判定完成。"

    return {
        "project_id": project_id,
        "verdict": verdict,
        "reason": reason,
        "formal_completion_supported": formal_supported,
        "tracked_work_item_count": len(work_items),
        "completed_work_item_count": completed,
        "unresolved_work_item_count": unresolved,
        "attention_work_item_count": attention,
        "status_counts": status_counts,
        "work_items": safe_items[:50],
    }


@router.get("/open-loops")
def open_loops(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    loops = collect_open_loops()
    selected = loops[:limit]
    return {
        "count": len(loops),
        "needs_user_count": sum(1 for item in loops if item["needs_user"]),
        "items": selected,
        "truncated": len(loops) > len(selected),
    }


@router.get("/completion/{project_id}")
def completion(project_id: str) -> dict[str, Any]:
    if not project_id or len(project_id) > 200 or "/" in project_id:
        raise HTTPException(422, "项目标识无效")
    return completion_judgement(project_id)


@router.get("/summary")
def summary(limit: int = Query(default=8, ge=1, le=30)) -> dict[str, Any]:
    loops = collect_open_loops()
    executions = [_safe_execution(item) for item in _execution_rows(30)]
    needs_user = [item for item in loops if item["needs_user"]]
    active = [
        item
        for item in executions
        if item["status"] in ACTIVE_STATUSES
        or item.get("runtime_status") == "running"
    ]
    selected = (needs_user + [item for item in loops if not item["needs_user"]])[:limit]
    return {
        "attention_required": bool(needs_user),
        "needs_user_count": len(needs_user),
        "open_loop_count": len(loops),
        "active_execution_count": len(active),
        "headline": (
            f"有{len(needs_user)}项需要你处理"
            if needs_user
            else (
                f"有{len(active)}个开发任务正在运行"
                if active
                else "当前没有需要立即打断你的事项"
            )
        ),
        "items": selected,
        "active_executions": active[:5],
        "policy": {
            "interrupt_for": [
                "project_blocker",
                "execution_unknown",
                "execution_compatibility_block",
            ],
            "silent_for": [
                "normal_progress",
                "successful_background_update",
            ],
        },
    }
