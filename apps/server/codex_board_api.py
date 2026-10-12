"""Scoped read-only execution board. Never enumerate private workspaces or mutate Host."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

import execution_provider as ep
from execution_p2 import muse_capability, personal_auth, require_muse_run

router = APIRouter(prefix="/api/v1/personal-agent", tags=["codex-board"])


def safe_text(value, limit=80):
    if not isinstance(value, str):
        return None
    # Omit unsafe text rather than attempt to reconstruct private context.
    if re.search(
        r"sk-|bearer|token|password|api.?key|secret|cookie|authorization|密码|授权头|(?:/Users/|/home/|[A-Za-z]:\\)|https?://",
        value,
        re.I,
    ):
        return None
    return " ".join(value.split())[:limit] or None


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None or result > datetime.now(timezone.utc):
            return None
        return result
    except ValueError:
        return None


def read_host(config, workspace):
    """Only two non-mutating reads, bounded per registered workspace."""
    try:
        with httpx.Client(timeout=1.5, trust_env=False, follow_redirects=False) as client:
            result = []
            for procedure in ("terminal.list", "terminalAgents.listByWorkspace"):
                response = client.get(
                    config["url"] + "/trpc/" + procedure,
                    headers={"Authorization": "Bearer " + config["token"]},
                    params={"input": json.dumps({"json": {"workspaceId": workspace}})},
                )
                response.raise_for_status()
                result.append(response.json()["result"]["data"]["json"])
            return result
    except Exception:
        return None


def records(config, capability):
    allowed = {
        (b.get("project_id"), b.get("repository_id")): b
        for b in config.get("bindings", [])
        if b.get("personal_enabled") or b.get("board_enabled")
    }
    candidates = []
    with ep.main.get_db() as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='executions'").fetchone()
        if exists:
            for row in conn.execute(
                "SELECT result_json FROM executions ORDER BY rowid DESC LIMIT 1000"
            ):
                try:
                    value = json.loads(row[0])
                    if not isinstance(value, dict):
                        continue
                    require_muse_run(value, config, capability)
                    candidates.append(value)
                except (ValueError, TypeError, HTTPException):
                    continue
    # Explicitly registered foreign sessions are read-only, never execution-authorized.
    candidates.extend(
        v
        for v in config.get("codex_board_sessions", [])[:250]
        if isinstance(v, dict)
        and hmac.compare_digest(str(v.get("muse_capability", "")), muse_capability(capability))
    )
    selected, seen, seen_ids, counts = [], set(), set(), {}
    for value in candidates:
        pair = (value.get("project_id"), value.get("repository_id"))
        key = (value.get("workspace_id"), value.get("session_id"), value.get("agent_session_id"))
        if (
            pair not in allowed
            or key in seen
            or value.get("id") in seen_ids
            or not all(isinstance(x, str) and x for x in key)
        ):
            continue
        try:
            UUID(str(value["id"]))
        except (ValueError, KeyError):
            continue
        if value.get("provider_instance") != config.get("organization_id", config["url"]):
            continue
        pid = pair[0]
        if counts.get(pid, 0) >= 5 or (pid not in counts and len(counts) >= 50):
            continue
        selected.append((value, allowed[pair]))
        seen.add(key)
        seen_ids.add(value["id"])
        counts[pid] = counts.get(pid, 0) + 1
    return selected, len({pair[0] for pair in allowed})


def details(value, binding, live):
    state, phase = "unknown", None
    if live and (len(live) != 2 or not isinstance(live[0], dict) or not isinstance(live[1], list)):
        live = None
    if live:
        terminals, agents = live
        terminal = next(
            (
                v
                for v in terminals.get("sessions", [])
                if v.get("terminalId") == value["session_id"]
            ),
            None,
        )
        agent = next(
            (
                v
                for v in agents
                if v.get("terminalId") == value["session_id"]
                and v.get("agentSessionId") == value["agent_session_id"]
                and v.get("agentId") == "codex"
                and v.get("definitionId") in {None, value.get("agent_definition_id")}
            ),
            None,
        )
        if terminal and terminal.get("exited"):
            state = "ended_unverified"
        elif agent and agent.get("endedAt"):
            state = "ended_unverified"
        elif terminal and agent:
            state = {
                "Stop": "needs_input",
                "PermissionRequest": "needs_input",
                "Notification": "needs_input",
                "Failed": "failed",
            }.get(agent.get("lastEventType"), "running")
    event_user = binding.get("board_event_user_id") or value.get("event_user_id")
    events = [
        e
        for e in ep.main.recent_agent_events(value["project_id"], 500)
        if event_user
        and e.get("user_id") == event_user
        and e.get("task_id") == value.get("task_id")
        and e.get("session_id") == value["id"]
    ]
    progress = last_at = passed = failed = test_at = files = None
    for e in events:
        at = timestamp(e.get("observed_at"))
        if not at:
            continue
        last_at = at.isoformat()
        data = e.get("data") or {}
        if e.get("event_type") == "task.progress":
            progress = safe_text(data.get("summary"))
            phase = (
                data.get("phase")
                if data.get("phase") in {"analysis", "planning", "editing", "testing", "waiting"}
                else None
            )
            raw = data.get("files")
            if binding.get("board_file_details_enabled") is True and isinstance(raw, list):
                files = [
                    p
                    for p in raw[:3]
                    if isinstance(p, str)
                    and len(p) <= 64
                    and not PurePosixPath(p).is_absolute()
                    and ".." not in PurePosixPath(p).parts
                    and re.fullmatch(r"[A-Za-z0-9_./-]+", p)
                    and safe_text(p)
                ]
        if e.get("event_type") == "test.result":
            p, f = data.get("passed"), data.get("failed")
            if type(p) is int and type(f) is int and 0 <= p <= 100000 and 0 <= f <= 100000:
                passed, failed, test_at = p, f, last_at
    if not live:
        state, phase = "stale", None
    return {
        "execution_id": value["id"],
        "repository_id": value["repository_id"],
        "title": safe_text(value.get("display_title"))
        or (safe_text(value.get("task_title")) if value.get("p2") else None)
        or "Codex",
        "state": state,
        "phase": phase,
        "progress": progress,
        "files": files,
        "tests_passed": passed,
        "tests_failed": failed,
        "test_observed_at": test_at,
        "last_event_at": last_at,
        "model_profile": value.get("model_profile")
        if value.get("model_profile") in {"fast", "balanced", "strong"}
        else None,
        "reasoning_effort": value.get("reasoning_effort")
        if value.get("reasoning_effort") in {"low", "medium", "high"}
        else None,
        "source": "cao_p2" if value.get("p2") else "registered_host",
        "feedback_allowed": bool(
            value.get("p2")
            and value.get("tool_policy_version") == 2
            and state in {"running", "needs_input"}
        ),
        "formal_completion": False,
    }


TASK_FIELDS = {
    "execution_id",
    "repository_id",
    "title",
    "state",
    "phase",
    "progress",
    "files",
    "tests_passed",
    "tests_failed",
    "test_observed_at",
    "last_event_at",
    "model_profile",
    "reasoning_effort",
    "source",
    "feedback_allowed",
    "formal_completion",
}


def desktop_snapshot(config, capability):
    allowed = set(config.get("desktop_board_project_ids", []))
    if not allowed:
        return [], True, allowed
    try:
        path = Path(config["desktop_board_snapshot_path"])
        if path.is_symlink() or path.stat().st_size > 512 * 1024:
            raise ValueError("Invalid projection")
        data = json.loads(path.read_text())
        at = timestamp(data.get("observed_at"))
        if (
            not at
            or (datetime.now(timezone.utc) - at).total_seconds() > 45
            or data.get("schema_version") != 1
            or data.get("muse_capability") != muse_capability(capability)
            or set(data.get("registered_project_ids", [])) != allowed
            or set(data)
            != {
                "schema_version",
                "observed_at",
                "muse_capability",
                "registered_project_ids",
                "projects",
            }
            or not isinstance(data["projects"], list)
            or len(data["projects"]) > 50
        ):
            raise ValueError("Wrong source/scope/freshness")
        output, seen = [], set()
        for project in data["projects"]:
            if (
                set(project) != {"project_id", "alias", "tasks"}
                or project["project_id"] not in allowed
                or not isinstance(project["tasks"], list)
                or len(project["tasks"]) > 5
                or not safe_text(project["alias"], 24)
            ):
                raise ValueError("Invalid project")
            tasks = []
            for task in project["tasks"]:
                if (
                    set(task) != TASK_FIELDS
                    or task["source"] != "codex_desktop"
                    or task["feedback_allowed"] is not False
                    or task["formal_completion"] is not False
                    or task["state"]
                    not in {
                        "running",
                        "needs_input",
                        "ended_unverified",
                        "failed",
                        "unknown",
                        "stale",
                    }
                    or task["repository_id"] != "desktop:" + project["project_id"]
                ):
                    raise ValueError("Invalid task")
                UUID(task["execution_id"])
                if task["execution_id"] in seen:
                    raise ValueError("Duplicate task")
                seen.add(task["execution_id"])
                task = dict(task)
                task["title"] = safe_text(task["title"]) or "Codex"
                task["progress"] = safe_text(task["progress"])
                if task["files"] is not None:
                    if not isinstance(task["files"], list):
                        raise ValueError("Invalid files")
                    task["files"] = [
                        p
                        for p in task["files"][:3]
                        if isinstance(p, str)
                        and re.fullmatch(r"[A-Za-z0-9_./-]{1,64}", p)
                        and not PurePosixPath(p).is_absolute()
                        and ".." not in PurePosixPath(p).parts
                        and safe_text(p)
                    ]
                for field in ("tests_passed", "tests_failed"):
                    if task[field] is not None and (
                        type(task[field]) is not int or not 0 <= task[field] <= 100000
                    ):
                        raise ValueError("Invalid test count")
                for field in ("test_observed_at", "last_event_at"):
                    if task[field] is not None and not timestamp(task[field]):
                        raise ValueError("Invalid event timestamp")
                if task["state"] == "running" and (
                    not timestamp(task["last_event_at"])
                    or (
                        datetime.now(timezone.utc) - timestamp(task["last_event_at"])
                    ).total_seconds()
                    > 90
                ):
                    task["state"] = "stale"
                tasks.append(task)
            if tasks:
                output.append(
                    {
                        "project_id": project["project_id"],
                        "alias": safe_text(project["alias"], 24),
                        "tasks": tasks,
                    }
                )
        return output, True, allowed
    except (OSError, ValueError, KeyError, TypeError):
        return [], False, allowed


@router.get("/codex-board")
def board(request: Request, x_muse_token: str | None = Header(default=None)):
    # Separate read credential cannot call the P2 mutation endpoints.
    token = os.getenv("CAO_MUSE_BOARD_TOKEN", "")
    execution_token = os.getenv("CAO_MUSE_TOKEN", "")
    if (
        len(token) < 32
        or token in {execution_token, ep.main.COLLECTOR_TOKEN}
        or not token.isascii()
        or not x_muse_token
        or not x_muse_token.isascii()
        or not hmac.compare_digest(token, x_muse_token)
    ):
        raise HTTPException(401, "Board read capability required")
    personal_auth(request, execution_token)
    config = ep.settings()
    selected, registered = records(config, execution_token)
    workspaces = list(dict.fromkeys(v["workspace_id"] for v, _ in selected))[:50]
    with ThreadPoolExecutor(max_workers=10) as pool:
        live = dict(zip(workspaces, pool.map(lambda w: read_host(config, w), workspaces)))
    projects = {}
    for v, b in selected:
        pid = v["project_id"]
        project = projects.setdefault(
            pid,
            {
                "project_id": pid,
                "alias": safe_text(b.get("display_alias"), 24) or "Authorized project",
                "tasks": [],
            },
        )
        project["tasks"].append(details(v, b, live.get(v["workspace_id"])))
    desktop, desktop_ready, desktop_registered = desktop_snapshot(config, execution_token)
    for project in desktop:
        if project["project_id"] not in projects and len(projects) < 50:
            projects[project["project_id"]] = project
    registered += len(
        desktop_registered
        - {
            b.get("project_id")
            for b in config.get("bindings", [])
            if b.get("personal_enabled") or b.get("board_enabled")
        }
    )
    rank = {
        "needs_input": 0,
        "failed": 1,
        "running": 2,
        "ended_unverified": 3,
        "unknown": 3,
        "stale": 4,
    }
    for project in projects.values():
        project["tasks"].sort(
            key=lambda t: (
                rank[t["state"]],
                -(
                    timestamp(t["last_event_at"]).timestamp()
                    if timestamp(t["last_event_at"])
                    else 0
                ),
            )
        )
    items = sorted(
        projects.values(),
        key=lambda p: (
            rank[p["tasks"][0]["state"]],
            -(
                timestamp(p["tasks"][0]["last_event_at"]).timestamp()
                if timestamp(p["tasks"][0]["last_event_at"])
                else 0
            ),
        ),
    )
    return {
        "schema_version": 1,
        "status": "unavailable"
        if not desktop_ready
        else "available"
        if not workspaces or all(live.values())
        else "stale",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "projects": items,
        "coverage": {
            "registered_project_count": registered,
            "observed_codex_project_count": len(items),
            "untracked_count": None,
        },
        "scope_id": hashlib.sha256(
            (
                muse_capability(execution_token)
                + json.dumps(
                    sorted(
                        (b["project_id"], b["repository_id"])
                        for b in config.get("bindings", [])
                        if b.get("personal_enabled") or b.get("board_enabled")
                    )
                )
            ).encode()
        ).hexdigest(),
    }
