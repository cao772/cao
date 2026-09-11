from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

FALLBACK_SESSION_INACTIVITY_MINUTES = 60
SESSION_IDLE_AFTER_MINUTES = 60
SUPPORTED_SESSION_STATES = {"active", "waiting", "blocked", "finished", "abandoned", "idle", "unknown"}


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _safe_text(value: Any, limit: int = 1000) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] if text else None


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode('utf-8', errors='ignore')).hexdigest()[:16]}"


def _agent_projection(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("agent") if isinstance(event.get("agent"), dict) else {}
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    name = _safe_text(raw.get("name") or event.get("agent_name") or data.get("agent_name"), 160) or "unknown"
    provider = _safe_text(raw.get("provider") or raw.get("vendor") or event.get("agent_provider") or data.get("agent_provider"), 160)
    version = _safe_text(raw.get("version") or data.get("agent_version"), 160)
    instance_id = _safe_text(raw.get("instance_id") or data.get("agent_instance_id"), 240)
    explicit_id = _safe_text(raw.get("agent_id") or event.get("agent_id") or data.get("agent_id"), 240)
    canonical = explicit_id or ":".join(part for part in (provider, name) if part) or name
    agent_id = re.sub(r"[^0-9a-zA-Z._:-]+", "-", canonical.lower()).strip("-") or "unknown"
    return {
        "agent_id": agent_id,
        "name": name,
        "provider": provider,
        "version": version,
        "instance_id": instance_id,
    }


def _task_identity(event: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    task_key = _safe_text(event.get("task_key") or data.get("task_key"), 300)
    task_id = _safe_text(event.get("task_id") or data.get("task_id"), 300)
    task_title = _safe_text(event.get("task_title") or data.get("task_title"), 1000)
    if task_key:
        return f"task_key:{task_key}", "task_key", task_key, task_title
    if task_id:
        return f"task_id:{task_id}", "task_id", task_id, task_title
    if task_title:
        return f"task_title:{task_title}", "task_title", task_title, task_title
    return None, None, None, None


def _event_summary(event: dict[str, Any]) -> str:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    return (
        _safe_text(data.get("summary") or data.get("message") or data.get("result") or event.get("task_title"), 1200)
        or str(event.get("event_type") or "agent event")
    )


def _normalize_test(data: dict[str, Any]) -> dict[str, Any]:
    def _count(name: str) -> int | None:
        value = data.get(name)
        if value is None or value == "":
            return None
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return None

    passed = _count("passed")
    failed = _count("failed")
    total = _count("total")
    if total is None and passed is not None and failed is not None:
        total = passed + failed
    status = _safe_text(data.get("status"), 40)
    if failed is not None and failed > 0:
        status = "failed"
    elif status is None and passed is not None and failed == 0:
        status = "passed"
    elif status is None:
        summary = str(data.get("summary") or data.get("result") or "").lower()
        if any(marker in summary for marker in ("failed", "failure", "失败", "未通过", "不通过")):
            status = "failed"
        elif any(marker in summary for marker in ("passed", "pass", "通过", "成功")):
            status = "passed"
        else:
            status = "unknown"
    command = _safe_text(data.get("command_summary") or data.get("command"), 500)
    return {"status": status, "passed": passed, "failed": failed, "total": total, "command_summary": command}


def _event_relation(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("event_type") or "").lower()
    if event_type == "task.started":
        return "agent_started"
    if event_type == "task.progress":
        return "agent_progress"
    if event_type == "task.finished":
        return "agent_finished"
    if event_type == "blocker.reported":
        return "agent_blocker"
    if event_type == "blocker.resolved":
        return "agent_blocker_resolved"
    if event_type == "test.result":
        test = _normalize_test(event.get("data") or {})
        if test["status"] == "passed":
            return "agent_test_pass"
        if test["status"] == "failed":
            return "agent_test_fail"
        return "agent_test_result"
    return None


def _normalize_events(events: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    normalized: list[dict[str, Any]] = []
    seen_client_ids: set[str] = set()
    duplicate_count = 0
    for order, raw in enumerate(events):
        event = dict(raw or {})
        client_event_id = _safe_text(event.get("client_event_id"), 300)
        if client_event_id and client_event_id in seen_client_ids:
            duplicate_count += 1
            continue
        if client_event_id:
            seen_client_ids.add(client_event_id)
        observed = _parse_time(event.get("observed_at"))
        if observed is None:
            observed = _parse_time(event.get("received_at")) or datetime.min.replace(tzinfo=timezone.utc)
        event["_observed_dt"] = observed
        event["_original_order"] = order
        event["_agent_projection"] = _agent_projection(event)
        task_ref, task_ref_kind, task_ref_value, task_title = _task_identity(event)
        event["_task_ref"] = task_ref
        event["_task_ref_kind"] = task_ref_kind
        event["_task_ref_value"] = task_ref_value
        event["_task_title"] = task_title
        normalized.append(event)
    normalized.sort(key=lambda item: (item["_observed_dt"], item["_original_order"]))
    return normalized, duplicate_count


def _assign_sessions(events: list[dict[str, Any]], inactivity_minutes: int) -> None:
    timeout = timedelta(minutes=max(int(inactivity_minutes), 1))
    fallback_state: dict[tuple[str, str, str], tuple[str, datetime]] = {}
    for event in events:
        explicit = _safe_text(event.get("session_id"), 300)
        if explicit:
            event["_session_id"] = explicit
            event["_session_source"] = "explicit"
            continue
        agent = event["_agent_projection"]
        key = (
            str(event.get("project_id") or ""),
            str(event.get("user_id") or ""),
            str(agent.get("agent_id") or "unknown"),
        )
        observed = event["_observed_dt"]
        current = fallback_state.get(key)
        if current is None or observed - current[1] > timeout:
            session_id = _stable_id("fallback-session", *key, observed.isoformat())
        else:
            session_id = current[0]
        fallback_state[key] = (session_id, observed)
        event["_session_id"] = session_id
        event["_session_source"] = "fallback"


def _new_task(ref: str, event: dict[str, Any]) -> dict[str, Any]:
    kind = event.get("_task_ref_kind")
    value = event.get("_task_ref_value")
    return {
        "task_ref": ref,
        "task_key": value if kind == "task_key" else None,
        "task_id": value if kind == "task_id" else _safe_text(event.get("task_id"), 300),
        "task_title": event.get("_task_title"),
        "agent_state": "unknown",
        "event_count": 0,
        "test_count": 0,
        "blocker_count": 0,
        "completion_claimed_by_agent": False,
        "formal_completion": None,
        "tests": [],
        "blockers": [],
        "first_activity_at": None,
        "last_activity_at": None,
    }


def _update_task(task: dict[str, Any], event: dict[str, Any], open_blockers: dict[str, dict[str, Any]]) -> None:
    event_type = str(event.get("event_type") or "").lower()
    observed_at = _iso(event["_observed_dt"])
    task["event_count"] += 1
    task["first_activity_at"] = task["first_activity_at"] or observed_at
    task["last_activity_at"] = observed_at
    if not task.get("task_title") and event.get("_task_title"):
        task["task_title"] = event["_task_title"]

    if event_type in {"task.started", "task.progress"}:
        task["agent_state"] = "active"
        blocker = open_blockers.pop(task["task_ref"], None)
        if blocker is not None:
            blocker["resolved_at"] = observed_at
            blocker["resolution"] = "progress_resumed"
    elif event_type == "task.finished":
        task["agent_state"] = "finished"
        task["completion_claimed_by_agent"] = True
    elif event_type == "blocker.reported":
        task["agent_state"] = "blocked"
        task["blocker_count"] += 1
        blocker = {
            "reported_at": observed_at,
            "summary": _event_summary(event),
            "resolved_at": None,
            "resolution": None,
        }
        task["blockers"].append(blocker)
        open_blockers[task["task_ref"]] = blocker
    elif event_type == "blocker.resolved":
        blocker = open_blockers.pop(task["task_ref"], None)
        if blocker is not None:
            blocker["resolved_at"] = observed_at
            blocker["resolution"] = _event_summary(event)
        if task["agent_state"] == "blocked":
            task["agent_state"] = "active"
    elif event_type == "test.result":
        task["test_count"] += 1
        test = _normalize_test(event.get("data") or {})
        test["observed_at"] = observed_at
        task["tests"].append(test)


def _collect_files(event: dict[str, Any]) -> list[str]:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    candidates: list[Any] = []
    for key in ("changed_files", "files"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, str):
            candidates.append(value)
    if str(event.get("event_type") or "").lower() == "file.changed" and data.get("path"):
        candidates.append(data.get("path"))
    result: list[str] = []
    for item in candidates:
        if isinstance(item, dict):
            item = item.get("path")
        path = _safe_text(item, 1000)
        if path and path not in result:
            result.append(path)
    return result


def _collect_git(event: dict[str, Any]) -> tuple[str | None, str | None]:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    return _safe_text(data.get("branch"), 500), _safe_text(data.get("commit_sha") or data.get("sha"), 200)


def build_agent_sessions(
    events: list[dict[str, Any]],
    *,
    project_id: str | None = None,
    now: str | datetime | None = None,
    inactivity_minutes: int = FALLBACK_SESSION_INACTIVITY_MINUTES,
    idle_after_minutes: int = SESSION_IDLE_AFTER_MINUTES,
) -> dict[str, Any]:
    """Project coding-agent events into conservative session/task/activity views."""
    normalized, duplicate_count = _normalize_events(events)
    if project_id is not None:
        normalized = [event for event in normalized if str(event.get("project_id") or "") == str(project_id)]
    _assign_sessions(normalized, inactivity_minutes)

    if isinstance(now, str):
        now_dt = _parse_time(now)
    elif isinstance(now, datetime):
        now_dt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        now_dt = now_dt.astimezone(timezone.utc)
    else:
        now_dt = datetime.now(timezone.utc)

    session_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in normalized:
        session_events[event["_session_id"]].append(event)

    sessions: list[dict[str, Any]] = []
    all_evidence: list[dict[str, Any]] = []
    global_flags: list[dict[str, Any]] = []
    if duplicate_count:
        global_flags.append({"flag": "duplicate_agent_event", "count": duplicate_count})

    for session_id, items in session_events.items():
        items.sort(key=lambda event: (event["_observed_dt"], event["_original_order"]))
        first, last = items[0], items[-1]
        agent = first["_agent_projection"]
        user_id = _safe_text(first.get("user_id"), 200)
        person_values = [
            _safe_text((event.get("data") or {}).get("person_id") or event.get("person_id"), 300)
            for event in items
        ]
        person_id = next((value for value in reversed(person_values) if value), None)
        tasks: dict[str, dict[str, Any]] = {}
        open_blockers: dict[str, dict[str, Any]] = {}
        unlinked_event_count = 0
        unlinked_test_count = 0
        unlinked_blocker_count = 0
        session_blocker_open = False
        timeline: list[dict[str, Any]] = []
        changed_files: list[str] = []
        branches: list[str] = []
        commits: list[str] = []
        session_ended_at: datetime | None = None
        session_abandoned = False
        session_started_at = first["_observed_dt"]

        for event in items:
            event_type = str(event.get("event_type") or "").lower()
            observed_at = _iso(event["_observed_dt"])
            if event_type == "session.started":
                session_started_at = min(session_started_at, event["_observed_dt"])
            if event_type == "session.ended":
                session_ended_at = event["_observed_dt"]
            elif event_type == "session.abandoned":
                session_ended_at = event["_observed_dt"]
                session_abandoned = True

            timeline.append(
                {
                    "event_id": _safe_text(event.get("client_event_id"), 300)
                    or (f"agent-event-{event.get('id')}" if event.get("id") is not None else None),
                    "event_type": event_type,
                    "observed_at": observed_at,
                    "task_key": event.get("_task_ref_value") if event.get("_task_ref_kind") == "task_key" else None,
                    "task_id": event.get("_task_ref_value") if event.get("_task_ref_kind") == "task_id" else _safe_text(event.get("task_id"), 300),
                    "task_title": event.get("_task_title"),
                    "summary": _event_summary(event),
                }
            )

            ref = event.get("_task_ref")
            if ref:
                task = tasks.setdefault(ref, _new_task(ref, event))
                _update_task(task, event, open_blockers)
            elif event_type.startswith("task.") or event_type in {"test.result", "blocker.reported", "blocker.resolved"}:
                unlinked_event_count += 1
                if event_type == "test.result":
                    unlinked_test_count += 1
                if event_type == "blocker.reported":
                    session_blocker_open = True
                    unlinked_blocker_count += 1
                elif event_type == "blocker.resolved":
                    session_blocker_open = False

            for path in _collect_files(event):
                if path not in changed_files:
                    changed_files.append(path)
            branch, commit = _collect_git(event)
            if branch and branch not in branches:
                branches.append(branch)
            if commit and commit not in commits:
                commits.append(commit)

            relation = _event_relation(event)
            if relation:
                all_evidence.append(
                    {
                        "source_type": "agent",
                        "relation": relation,
                        "task_key": event.get("_task_ref_value") if event.get("_task_ref_kind") == "task_key" else None,
                        "task_id": event.get("_task_ref_value") if event.get("_task_ref_kind") == "task_id" else _safe_text(event.get("task_id"), 300),
                        "session_id": session_id,
                        "observed_at": observed_at,
                        "summary": _event_summary(event),
                        "confidence": "high",
                    }
                )

        last_activity = last["_observed_dt"]
        flags: list[str] = []
        if session_abandoned:
            status = "abandoned"
        elif session_ended_at is not None:
            status = "finished"
        elif open_blockers or session_blocker_open:
            status = "blocked"
            flags.append("blocked_session")
        elif now_dt is not None and now_dt - last_activity > timedelta(minutes=max(int(idle_after_minutes), 1)):
            status = "idle"
            flags.append("long_idle_session")
        else:
            status = "active"
        if status not in SUPPORTED_SESSION_STATES:
            status = "unknown"

        if unlinked_event_count:
            flags.append("unlinked_task_event")
        for task in tasks.values():
            if task["completion_claimed_by_agent"] and task["test_count"] == 0:
                flags.append("agent_finished_without_test")
        if any(str(event.get("event_type") or "").lower() == "task.finished" and not event.get("_task_ref") for event in items):
            flags.append("agent_finished_without_task")
        flags = sorted(set(flags))

        task_values = list(tasks.values())
        for task in task_values:
            task["open_blocker_count"] = 1 if task["task_ref"] in open_blockers else 0

        duration_end = session_ended_at or last_activity
        duration_seconds = max(int((duration_end - session_started_at).total_seconds()), 0)
        sessions.append(
            {
                "session_id": session_id,
                "session_source": first.get("_session_source"),
                "project_id": first.get("project_id"),
                "user_id": user_id,
                "person_id": person_id,
                "agent": agent,
                "started_at": _iso(session_started_at),
                "last_activity_at": _iso(last_activity),
                "ended_at": _iso(session_ended_at),
                "duration_seconds": duration_seconds,
                "status": status,
                "agent_state": status,
                "engineering_state": None,
                "event_count": len(items),
                "task_count": len(task_values),
                "task_keys": [task["task_key"] for task in task_values if task.get("task_key")],
                "test_count": sum(task["test_count"] for task in task_values) + unlinked_test_count,
                "blocker_count": sum(task["blocker_count"] for task in task_values) + unlinked_blocker_count,
                "open_blocker_count": len(open_blockers) + (1 if session_blocker_open else 0),
                "unlinked_task_event_count": unlinked_event_count,
                "changed_files": changed_files,
                "changed_files_count": len(changed_files),
                "branches": branches,
                "commits": commits,
                "tasks": task_values,
                "timeline": timeline,
                "flags": flags,
                "last_activity_summary": _event_summary(last),
            }
        )

    sessions.sort(key=lambda item: item.get("last_activity_at") or "", reverse=True)

    explicit_task_sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        for task in session["tasks"]:
            if task.get("task_key"):
                explicit_task_sessions[f"task_key:{task['task_key']}"].append(session)
            elif task.get("task_id"):
                explicit_task_sessions[f"task_id:{task['task_id']}"].append(session)

    for task_ref, related in explicit_task_sessions.items():
        for index, left in enumerate(related):
            for right in related[index + 1 :]:
                if left["session_id"] == right["session_id"]:
                    continue
                if left["agent"]["agent_id"] == right["agent"]["agent_id"]:
                    continue
                left_start = _parse_time(left["started_at"])
                left_end = _parse_time(left["ended_at"] or left["last_activity_at"])
                right_start = _parse_time(right["started_at"])
                right_end = _parse_time(right["ended_at"] or right["last_activity_at"])
                if not all((left_start, left_end, right_start, right_end)):
                    continue
                if max(left_start, right_start) <= min(left_end, right_end):
                    flag = {
                        "flag": "concurrent_agents_same_task",
                        "task_ref": task_ref,
                        "sessions": [left["session_id"], right["session_id"]],
                        "agents": [left["agent"]["name"], right["agent"]["name"]],
                    }
                    if flag not in global_flags:
                        global_flags.append(flag)

    agents: dict[str, dict[str, Any]] = {}
    for session in sessions:
        agent = session["agent"]
        item = agents.setdefault(
            agent["agent_id"],
            {
                **agent,
                "active_sessions": 0,
                "blocked_sessions": 0,
                "last_activity_at": None,
                "users": [],
                "session_count": 0,
            },
        )
        item["session_count"] += 1
        if session["status"] in {"active", "blocked", "waiting"}:
            item["active_sessions"] += 1
        if session["status"] == "blocked":
            item["blocked_sessions"] += 1
        if session["user_id"] and session["user_id"] not in item["users"]:
            item["users"].append(session["user_id"])
        if not item["last_activity_at"] or (session["last_activity_at"] or "") > item["last_activity_at"]:
            item["last_activity_at"] = session["last_activity_at"]

    return {
        "project_id": project_id or (sessions[0]["project_id"] if sessions else None),
        "session_count": len(sessions),
        "active_session_count": sum(1 for item in sessions if item["status"] in {"active", "blocked", "waiting"}),
        "blocked_session_count": sum(1 for item in sessions if item["status"] == "blocked"),
        "agent_count": len(agents),
        "agents": sorted(agents.values(), key=lambda item: item.get("last_activity_at") or "", reverse=True),
        "sessions": sessions,
        "evidence": all_evidence,
        "flags": global_flags,
        "formal_completion_supported": False,
    }


def get_agent_session(projection: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    return next((session for session in projection.get("sessions") or [] if session.get("session_id") == session_id), None)
