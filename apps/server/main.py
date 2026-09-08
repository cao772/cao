from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from evidence_fusion import fuse_evidence
from project_memory import enrich_snapshot_payload
from project_rollup import build_project_rollup
from workspace_inventory import build_workspace_inventory

DB_PATH = Path(os.getenv("DB_PATH", "/data/project.db"))
COLLECTOR_TOKEN = os.getenv("COLLECTOR_TOKEN", "")

app = FastAPI(title="AI Dev Management API", version="0.7.0")


class SnapshotIn(BaseModel):
    schema_version: int = 1
    snapshot_type: str
    observed_at: str
    project_id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    workspace_name: str
    collector: dict[str, Any]
    security_mode: str
    git: dict[str, Any]
    files: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] = Field(default_factory=dict)
    git_change_analysis: dict[str, Any] = Field(default_factory=dict)


class AgentEventIn(BaseModel):
    schema_version: int = 1
    client_event_id: str | None = None
    event_type: str = Field(min_length=1, max_length=120)
    observed_at: str
    project_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    agent: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = Field(default=None, max_length=300)
    task_id: str | None = Field(default=None, max_length=300)
    task_title: str | None = Field(default=None, max_length=1000)
    data: dict[str, Any] = Field(default_factory=dict)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_user_id TEXT,
                last_device_id TEXT,
                last_workspace_name TEXT
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                workspace_name TEXT,
                observed_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                snapshot_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_project_id_id
                ON snapshots(project_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_snapshots_observed_at
                ON snapshots(observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_snapshots_workspace_latest
                ON snapshots(project_id, user_id, device_id, workspace_name, id DESC);

            CREATE TABLE IF NOT EXISTS agent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_event_id TEXT UNIQUE,
                project_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                agent_json TEXT NOT NULL,
                session_id TEXT,
                task_id TEXT,
                task_title TEXT,
                data_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_agent_events_project_id_id
                ON agent_events(project_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_events_project_task
                ON agent_events(project_id, task_id, id DESC);
            """
        )


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def require_collector_token(x_collector_token: str | None) -> None:
    if COLLECTOR_TOKEN and x_collector_token != COLLECTOR_TOKEN:
        raise HTTPException(status_code=401, detail="invalid collector token")


def _agent_event_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["agent"] = json.loads(item.pop("agent_json"))
    item["data"] = json.loads(item.pop("data_json"))
    return item


def _snapshot_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


def recent_agent_events(project_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, client_event_id, project_id, user_id, event_type,
                   observed_at, received_at, agent_json, session_id,
                   task_id, task_title, data_json
            FROM agent_events
            WHERE project_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
    return [_agent_event_row(row) for row in reversed(rows)]


def latest_snapshot(project_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, project_name, user_id, device_id, workspace_name,
                   observed_at, received_at, snapshot_type, payload_json
            FROM snapshots
            WHERE project_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="project snapshot not found")

    item = dict(row)
    payload = json.loads(item.pop("payload_json"))
    return item, payload


def latest_workspace_snapshots(project_id: str) -> list[dict[str, Any]]:
    """Return only the newest snapshot for each user/device/workspace tuple."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.project_id, s.project_name, s.user_id, s.device_id,
                   s.workspace_name, s.observed_at, s.received_at,
                   s.snapshot_type, s.payload_json
            FROM snapshots s
            INNER JOIN (
                SELECT user_id, device_id, workspace_name, MAX(id) AS latest_id
                FROM snapshots
                WHERE project_id = ?
                GROUP BY user_id, device_id, workspace_name
            ) latest ON latest.latest_id = s.id
            ORDER BY s.received_at DESC, s.id DESC
            """,
            (project_id,),
        ).fetchall()
    return [_snapshot_row(row) for row in rows]


def project_rollup(project_id: str) -> dict[str, Any]:
    snapshots = latest_workspace_snapshots(project_id)
    if not snapshots:
        raise HTTPException(status_code=404, detail="project snapshot not found")
    events = recent_agent_events(project_id, 500)
    return build_project_rollup(snapshots, events)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.7.0"}


@app.post("/api/v1/snapshots")
def ingest_snapshot(
    snapshot: SnapshotIn,
    x_collector_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_collector_token(x_collector_token)
    received_at = now_utc()
    payload = enrich_snapshot_payload(snapshot.model_dump())
    payload["workspace_inventory"] = build_workspace_inventory(
        list((payload.get("files") or {}).get("files") or [])
    )

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO snapshots (
                project_id, project_name, user_id, device_id, workspace_name,
                observed_at, received_at, snapshot_type, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.project_id,
                snapshot.project_name,
                snapshot.user_id,
                snapshot.device_id,
                snapshot.workspace_name,
                snapshot.observed_at,
                received_at,
                snapshot.snapshot_type,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            INSERT INTO projects (
                project_id, project_name, last_seen_at, last_user_id,
                last_device_id, last_workspace_name
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                project_name=excluded.project_name,
                last_seen_at=excluded.last_seen_at,
                last_user_id=excluded.last_user_id,
                last_device_id=excluded.last_device_id,
                last_workspace_name=excluded.last_workspace_name
            """,
            (
                snapshot.project_id,
                snapshot.project_name,
                received_at,
                snapshot.user_id,
                snapshot.device_id,
                snapshot.workspace_name,
            ),
        )

    return {"accepted": True, "snapshot_id": cursor.lastrowid, "received_at": received_at}


@app.post("/api/v1/agent-events")
def ingest_agent_event(
    event: AgentEventIn,
    x_collector_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Receive structured activity from Codex/TRAE/Hermes/other coding agents."""
    require_collector_token(x_collector_token)
    received_at = now_utc()
    client_event_id = event.client_event_id or str(uuid.uuid4())

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id, received_at FROM agent_events WHERE client_event_id = ?",
            (client_event_id,),
        ).fetchone()
        if existing is not None:
            return {
                "accepted": True,
                "duplicate": True,
                "event_id": existing["id"],
                "client_event_id": client_event_id,
                "received_at": existing["received_at"],
            }

        cursor = conn.execute(
            """
            INSERT INTO agent_events (
                client_event_id, project_id, user_id, event_type,
                observed_at, received_at, agent_json, session_id,
                task_id, task_title, data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_event_id,
                event.project_id,
                event.user_id,
                event.event_type,
                event.observed_at,
                received_at,
                json.dumps(event.agent, ensure_ascii=False),
                event.session_id,
                event.task_id,
                event.task_title,
                json.dumps(event.data, ensure_ascii=False),
            ),
        )

    return {
        "accepted": True,
        "duplicate": False,
        "event_id": cursor.lastrowid,
        "client_event_id": client_event_id,
        "received_at": received_at,
    }


@app.get("/api/v1/projects")
def list_projects() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY last_seen_at DESC, project_id ASC"
        ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        rollup = project_rollup(str(item["project_id"]))
        item.update(
            {
                "project_state": rollup.get("project_state"),
                "project_state_label": rollup.get("project_state_label"),
                "workspace_count": rollup.get("workspace_count", 0),
                "contributor_count": rollup.get("contributor_count", 0),
                "dirty_workspace_count": rollup.get("dirty_workspace_count", 0),
                "attention_workspace_count": rollup.get("attention_workspace_count", 0),
                "agents": rollup.get("agents", []),
                "branches": rollup.get("branches", {}),
            }
        )
        result.append(item)
    return result


@app.get("/api/v1/projects/{project_id}/snapshots")
def list_project_snapshots(
    project_id: str,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, project_name, user_id, device_id, workspace_name,
                   observed_at, received_at, snapshot_type, payload_json
            FROM snapshots
            WHERE project_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
    return [_snapshot_row(row) for row in rows]


@app.get("/api/v1/projects/{project_id}/workspaces")
def list_project_workspaces(project_id: str) -> dict[str, Any]:
    rollup = project_rollup(project_id)
    return {
        "project_id": project_id,
        "workspace_count": rollup["workspace_count"],
        "workspaces": rollup["workspaces"],
    }


@app.get("/api/v1/projects/{project_id}/contributors")
def list_project_contributors(project_id: str) -> dict[str, Any]:
    rollup = project_rollup(project_id)
    return {
        "project_id": project_id,
        "contributor_count": rollup["contributor_count"],
        "contributors": rollup["contributors"],
        "agents": rollup["agents"],
    }


@app.get("/api/v1/projects/{project_id}/agent-events")
def list_project_agent_events(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return recent_agent_events(project_id, limit)


@app.get("/api/v1/projects/{project_id}/evidence")
def get_project_evidence(project_id: str) -> dict[str, Any]:
    primary, payload = latest_snapshot(project_id)
    events = recent_agent_events(project_id, 300)
    fusion = fuse_evidence(payload, events)
    fusion["primary_workspace"] = {
        "user_id": primary.get("user_id"),
        "device_id": primary.get("device_id"),
        "workspace_name": primary.get("workspace_name"),
        "snapshot_id": primary.get("id"),
    }
    fusion["project_rollup"] = project_rollup(project_id)
    fusion["scope_note"] = (
        "任务级 Evidence Fusion 当前以最新工作区的项目资料/Git证据为主；"
        "project_rollup 已汇总所有开发人员最新工作区，后续将继续做跨工作区任务级融合。"
    )
    return fusion


@app.get("/api/v1/projects/{project_id}/current")
def get_current_project(project_id: str) -> dict[str, Any]:
    """Return project-level rollup plus the latest workspace's detailed evidence."""
    item, payload = latest_snapshot(project_id)
    memory = ((payload.get("analysis") or {}).get("current_project_memory") or {})
    events = recent_agent_events(project_id, 300)

    item["git"] = payload.get("git") or {}
    item["git_change_analysis"] = payload.get("git_change_analysis") or {}
    item["analysis_stats"] = (payload.get("analysis") or {}).get("stats") or {}
    item["workspace_inventory"] = payload.get("workspace_inventory") or {}
    item["current_project_memory"] = memory
    item["agent_events"] = events[-100:]
    item["evidence_fusion"] = fuse_evidence(payload, events)
    item["project_rollup"] = project_rollup(project_id)
    item["evidence_scope_note"] = (
        "当前任务级证据融合仍以最新工作区为锚点；多人工作区状态已在 project_rollup 中完整保留。"
    )
    return item
