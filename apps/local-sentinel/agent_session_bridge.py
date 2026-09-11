from __future__ import annotations

import json
import re
import threading
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import agent_bridge

FALLBACK_SESSION_INACTIVITY_MINUTES = 60
_MAX_TEXT_LENGTH = 4000
_SENSITIVE_KEY = re.compile(
    r"(^|[._-])(api[_-]?key|token|password|passwd|secret|ssh[_-]?key|private[_-]?key|credential|authorization|cookie|env)([._-]|$)",
    re.IGNORECASE,
)
_OMITTED_KEY = re.compile(
    r"(^|[._-])(stdout|stderr|shell[_-]?output|command[_-]?output|raw[_-]?output|full[_-]?output|chain[_-]?of[_-]?thought|hidden[_-]?reasoning|private[_-]?reasoning|internal[_-]?reasoning|scratchpad)([._-]|$)",
    re.IGNORECASE,
)
_SESSION_LOCK = threading.Lock()
_FALLBACK_SESSIONS: dict[tuple[str, str, str], tuple[str, datetime]] = {}


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _agent_key() -> str:
    return ":".join(
        part
        for part in (
            str(agent_bridge.AGENT_VENDOR or "").strip(),
            str(agent_bridge.AGENT_NAME or "").strip(),
            str(agent_bridge.AGENT_INSTANCE_ID or "").strip(),
        )
        if part
    ) or "coding-agent"


def reset_fallback_sessions() -> None:
    with _SESSION_LOCK:
        _FALLBACK_SESSIONS.clear()


def resolve_session_id(project_id: str, explicit_session_id: str | None = None) -> str:
    explicit = str(explicit_session_id or "").strip()
    if explicit:
        return explicit
    now = _clock()
    key = (str(project_id).strip(), str(agent_bridge.USER_ID or "").strip(), _agent_key())
    timeout = timedelta(minutes=FALLBACK_SESSION_INACTIVITY_MINUTES)
    with _SESSION_LOCK:
        current = _FALLBACK_SESSIONS.get(key)
        if current is None or now - current[1] > timeout:
            session_id = f"fallback-{uuid.uuid4()}"
        else:
            session_id = current[0]
        _FALLBACK_SESSIONS[key] = (session_id, now)
    return session_id


def _sanitize(value: Any, key: str = "", depth: int = 0) -> Any:
    if _SENSITIVE_KEY.search(str(key or "")):
        return "[REDACTED]"
    if _OMITTED_KEY.search(str(key or "")):
        return "[OMITTED]"
    if depth >= 8:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, str(k), depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key, depth + 1) for item in list(value)[:200]]
    if isinstance(value, str):
        return value[:_MAX_TEXT_LENGTH]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_TEXT_LENGTH]


def report_agent_event_v2(
    *,
    event_type: str,
    project_id: str,
    task_title: str | None = None,
    task_id: str | None = None,
    task_key: str | None = None,
    person_id: str | None = None,
    session_id: str | None = None,
    client_event_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add session/idempotency metadata while preserving the old Agent Bridge contract."""
    resolved_session_id = resolve_session_id(project_id, session_id)
    payload_data = dict(data or {})
    if task_key:
        payload_data["task_key"] = str(task_key).strip()
    if person_id:
        payload_data["person_id"] = str(person_id).strip()
    payload_data = _sanitize(payload_data)

    event = agent_bridge.build_agent_event(
        event_type=event_type,
        project_id=project_id,
        task_title=task_title,
        task_id=task_id,
        session_id=resolved_session_id,
        data=payload_data,
    )
    event["client_event_id"] = str(client_event_id or uuid.uuid4())
    event["data"] = _sanitize(event.get("data") or {})

    if not agent_bridge.CENTRAL_URL:
        return {
            "accepted": False,
            "central_available": False,
            "event": event,
            "note": "CENTRAL_URL is not configured, so the event was not persisted centrally.",
        }

    try:
        response = agent_bridge._central_request("POST", "/api/v1/agent-events", event)
        return {"accepted": True, "central_available": True, "response": response, "event": event}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "accepted": False,
            "central_available": False,
            "error": str(exc),
            "event": event,
        }
