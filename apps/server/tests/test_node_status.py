from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import node_status
import platform_config


def _insert_snapshot(conn, *, project_id, project_name, user_id, device_id, workspace_name, received_at):
    conn.execute(
        """
        INSERT INTO snapshots(
            project_id, project_name, user_id, device_id, workspace_name,
            observed_at, received_at, snapshot_type, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'workspace', '{}')
        """,
        (
            project_id,
            project_name,
            user_id,
            device_id,
            workspace_name,
            received_at,
            received_at,
        ),
    )


def test_list_nodes_groups_projects_and_uses_latest_workspace_snapshot(tmp_path, monkeypatch):
    db_path = tmp_path / "project.db"
    monkeypatch.setattr(platform_config, "DB_PATH", db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE snapshots (
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
            """
        )
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=2)).isoformat()
        recent = (now - timedelta(minutes=5)).isoformat()
        _insert_snapshot(
            conn,
            project_id="low-voltage",
            project_name="低电压",
            user_id="caoyh",
            device_id="macbook",
            workspace_name="algorithm",
            received_at=old,
        )
        _insert_snapshot(
            conn,
            project_id="low-voltage",
            project_name="低电压",
            user_id="caoyh",
            device_id="macbook",
            workspace_name="algorithm",
            received_at=recent,
        )
        _insert_snapshot(
            conn,
            project_id="power-defect-agent",
            project_name="缺陷处置",
            user_id="caoyh",
            device_id="macbook",
            workspace_name="multimodal-agent",
            received_at=recent,
        )

    nodes = node_status.list_nodes()

    assert len(nodes) == 1
    assert nodes[0]["user_id"] == "caoyh"
    assert nodes[0]["device_id"] == "macbook"
    assert nodes[0]["status"] == "online"
    assert nodes[0]["project_count"] == 2
    assert nodes[0]["workspace_count"] == 2
    assert {item["project_id"] for item in nodes[0]["projects"]} == {"low-voltage", "power-defect-agent"}


def test_status_thresholds():
    now = datetime.now(timezone.utc)
    assert node_status._status((now - timedelta(minutes=10)).isoformat()) == "online"
    assert node_status._status((now - timedelta(hours=2)).isoformat()) == "stale"
    assert node_status._status((now - timedelta(days=2)).isoformat()) == "offline"
    assert node_status._status(None) == "unknown"
