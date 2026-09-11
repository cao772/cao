from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from agent_bridge import (
    AGENT_NAME,
    AGENT_VENDOR,
    get_project_context,
    get_project_tasks,
    list_managed_projects,
)
from agent_session_bridge import report_agent_event_v2

MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "6410"))

mcp = FastMCP(
    "AI Dev Project Sentinel",
    instructions=(
        "Use this server to read shared project context and report structured coding-agent activity. "
        "Do not treat task.finished as formal delivery; the central evidence engine independently verifies "
        "local Git, tests, GitLab/GitHub, CI, merge and deployment facts."
    ),
    host=MCP_HOST,
    port=MCP_PORT,
)


@mcp.tool()
def list_projects() -> list[dict[str, Any]]:
    """List project.yaml-managed projects visible on this developer machine."""
    return list_managed_projects()


@mcp.tool()
def get_context(project_id: str) -> dict[str, Any]:
    """Get fresh local Git state plus compact shared project memory and task state."""
    return get_project_context(project_id)


@mcp.tool()
def get_tasks(project_id: str) -> dict[str, Any]:
    """Get the central task/evidence view for one project without returning source code or document bodies."""
    return get_project_tasks(project_id)


def _report(
    event_type: str,
    project_id: str,
    task_title: str | None = None,
    task_id: str = "",
    session_id: str = "",
    summary: str = "",
    task_key: str = "",
    person_id: str = "",
    client_event_id: str = "",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(data or {})
    if summary:
        payload.setdefault("summary", summary)
    return report_agent_event_v2(
        event_type=event_type,
        project_id=project_id,
        task_title=task_title,
        task_id=task_id or None,
        task_key=task_key or None,
        person_id=person_id or None,
        session_id=session_id or None,
        client_event_id=client_event_id or None,
        data=payload,
    )


@mcp.tool()
def report_task_started(
    project_id: str,
    task_title: str,
    task_id: str = "",
    session_id: str = "",
    summary: str = "",
    task_key: str = "",
    person_id: str = "",
    client_event_id: str = "",
) -> dict[str, Any]:
    """Report that this coding agent started a task."""
    return _report("task.started", project_id, task_title, task_id, session_id, summary, task_key, person_id, client_event_id)


@mcp.tool()
def report_task_progress(
    project_id: str,
    task_title: str,
    summary: str,
    task_id: str = "",
    session_id: str = "",
    task_key: str = "",
    person_id: str = "",
    client_event_id: str = "",
) -> dict[str, Any]:
    """Report a factual task progress update. Prefer concrete changes/blockers over guessed percentages."""
    return _report("task.progress", project_id, task_title, task_id, session_id, summary, task_key, person_id, client_event_id)


@mcp.tool()
def report_task_finished(
    project_id: str,
    task_title: str,
    summary: str = "",
    task_id: str = "",
    session_id: str = "",
    task_key: str = "",
    person_id: str = "",
    client_event_id: str = "",
) -> dict[str, Any]:
    """Report that this agent's local work is finished; this does not mark the project task formally complete."""
    return _report("task.finished", project_id, task_title, task_id, session_id, summary, task_key, person_id, client_event_id)


@mcp.tool()
def report_test_result(
    project_id: str,
    task_title: str,
    passed: int,
    failed: int,
    task_id: str = "",
    session_id: str = "",
    summary: str = "",
    task_key: str = "",
    person_id: str = "",
    client_event_id: str = "",
) -> dict[str, Any]:
    """Report structured local test counts for a task."""
    passed = max(int(passed), 0)
    failed = max(int(failed), 0)
    data = {
        "status": "failed" if failed else "passed",
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "summary": summary or f"tests: {passed} passed, {failed} failed",
    }
    return _report("test.result", project_id, task_title, task_id, session_id, "", task_key, person_id, client_event_id, data)


@mcp.tool()
def report_blocker(
    project_id: str,
    task_title: str,
    blocker: str,
    task_id: str = "",
    session_id: str = "",
    task_key: str = "",
    person_id: str = "",
    client_event_id: str = "",
) -> dict[str, Any]:
    """Report a concrete blocker that prevents or delays a task."""
    return _report(
        "blocker.reported",
        project_id,
        task_title,
        task_id,
        session_id,
        blocker,
        task_key,
        person_id,
        client_event_id,
        {"blocker": blocker},
    )


@mcp.tool()
def report_session_started(
    project_id: str,
    session_id: str = "",
    summary: str = "",
    person_id: str = "",
    client_event_id: str = "",
) -> dict[str, Any]:
    """Optionally report an explicit coding-agent session start. Old clients do not need to call this."""
    return _report("session.started", project_id, None, "", session_id, summary, "", person_id, client_event_id)


@mcp.tool()
def report_session_finished(
    project_id: str,
    session_id: str = "",
    summary: str = "",
    person_id: str = "",
    client_event_id: str = "",
) -> dict[str, Any]:
    """Optionally report an explicit coding-agent session end. Task completion remains separate."""
    return _report("session.ended", project_id, None, "", session_id, summary, "", person_id, client_event_id)


@mcp.tool()
def report_files_changed(
    project_id: str,
    task_title: str,
    files: list[str],
    task_id: str = "",
    session_id: str = "",
    summary: str = "",
    task_key: str = "",
    person_id: str = "",
    client_event_id: str = "",
) -> dict[str, Any]:
    """Report file paths explicitly changed by this agent; file contents are not uploaded."""
    cleaned = [str(path).strip() for path in files if str(path).strip()][:200]
    return _report(
        "file.changed",
        project_id,
        task_title,
        task_id,
        session_id,
        summary,
        task_key,
        person_id,
        client_event_id,
        {"changed_files": cleaned},
    )


@mcp.tool()
def report_commit(
    project_id: str,
    task_title: str,
    commit_sha: str,
    branch: str = "",
    task_id: str = "",
    session_id: str = "",
    summary: str = "",
    task_key: str = "",
    person_id: str = "",
    client_event_id: str = "",
) -> dict[str, Any]:
    """Report an explicit Git commit reference produced in this agent session."""
    return _report(
        "git.commit",
        project_id,
        task_title,
        task_id,
        session_id,
        summary,
        task_key,
        person_id,
        client_event_id,
        {"commit_sha": commit_sha, "branch": branch or None},
    )


if __name__ == "__main__":
    print(
        f"Starting AI Dev Project Sentinel MCP for {AGENT_VENDOR}/{AGENT_NAME} "
        f"on {MCP_HOST}:{MCP_PORT}"
    )
    mcp.run(transport="streamable-http")
