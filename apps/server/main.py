from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("DB_PATH", "/data/project.db"))
COLLECTOR_TOKEN = os.getenv("COLLECTOR_TOKEN", "")

app = FastAPI(title="AI Dev Management API", version="0.1.0")


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
            """
        )


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def require_collector_token(x_collector_token: str | None) -> None:
    if COLLECTOR_TOKEN and x_collector_token != COLLECTOR_TOKEN:
        raise HTTPException(status_code=401, detail="invalid collector token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.post("/api/v1/snapshots")
def ingest_snapshot(
    snapshot: SnapshotIn,
    x_collector_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_collector_token(x_collector_token)
    received_at = now_utc()
    payload = snapshot.model_dump()

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


@app.get("/api/v1/projects")
def list_projects() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY last_seen_at DESC, project_id ASC"
        ).fetchall()
    return [dict(row) for row in rows]


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

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return result
