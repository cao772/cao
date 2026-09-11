from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

import main
from agent_sessions import build_agent_sessions, get_agent_session

router = APIRouter()


def agent_session_projection(project_id: str, limit: int = 5000) -> dict[str, Any]:
    return build_agent_sessions(
        main.recent_agent_events(project_id, limit),
        project_id=project_id,
        now=main.now_utc(),
    )


def _agent_event_project_ids() -> list[str]:
    with main.get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT project_id FROM agent_events ORDER BY project_id ASC"
        ).fetchall()
    return [str(row["project_id"]) for row in rows]


@router.get("/api/v1/projects/{project_id}/agent-sessions")
def list_project_agent_sessions(
    project_id: str,
    limit: int = Query(default=1000, ge=1, le=5000),
) -> dict[str, Any]:
    return agent_session_projection(project_id, limit)


@router.get("/api/v1/projects/{project_id}/agents")
def list_project_agents(
    project_id: str,
    limit: int = Query(default=1000, ge=1, le=5000),
) -> dict[str, Any]:
    projection = agent_session_projection(project_id, limit)
    return {
        "project_id": project_id,
        "agent_count": projection.get("agent_count", 0),
        "active_session_count": projection.get("active_session_count", 0),
        "blocked_session_count": projection.get("blocked_session_count", 0),
        "agents": projection.get("agents") or [],
        "flags": projection.get("flags") or [],
    }


@router.get("/api/v1/agent-sessions/{session_id}")
def get_agent_session_detail(session_id: str) -> dict[str, Any]:
    for project_id in _agent_event_project_ids():
        projection = agent_session_projection(project_id, 5000)
        session = get_agent_session(projection, session_id)
        if session is None:
            continue
        return {
            "project_id": project_id,
            "session": session,
            "evidence": [
                item
                for item in (projection.get("evidence") or [])
                if item.get("session_id") == session_id
            ],
            "flags": [
                item
                for item in (projection.get("flags") or [])
                if session_id in (item.get("sessions") or [])
            ],
            "formal_completion_supported": False,
        }
    raise HTTPException(status_code=404, detail="agent session not found")
