from __future__ import annotations

import json
import sqlite3

import agent_api
import people_store
import platform_config
from agent_sessions import build_agent_sessions
from evidence_fusion import fuse_evidence
from evidence_lifecycle import normalize_evidence
from remote_evidence import apply_remote_evidence


def _payload(current_facts, historical_facts=None):
    return {
        "git": {
            "is_git_repo": True,
            "dirty": False,
            "ahead": 0,
            "behind": 0,
            "upstream": "origin/cao",
        },
        "analysis": {
            "current_project_memory": {
                "current_facts": current_facts,
                "historical_facts": historical_facts or [],
                "requirements": [],
                "tasks": [],
                "tests": [],
                "blockers": [],
                "progress": [],
            }
        },
        "git_change_analysis": {"enabled": True, "items": []},
    }


def _fusion(evidence, *, status="planned", dirty=False):
    return {
        "version": 2,
        "scope": "cross_workspace_local_evidence",
        "project_state": "active",
        "project_state_label": "多人协作开发中",
        "formal_completion_supported": False,
        "summary": {"status_counts": {status: 1}},
        "work_items": [
            {
                "work_item_id": "LV-102",
                "task_id": "LV-102",
                "title": "资料上传更新左侧树状页面",
                "status": status,
                "status_label": status,
                "status_reasons": [],
                "evidence": evidence,
                "contributors": ["cyh"],
                "workspace_contributions": [
                    {"git_dirty": dirty, "git_ahead": 0}
                ],
            }
        ],
        "unlinked_evidence": {},
    }


def _remote(event_type, at):
    return {
        "event_type": event_type,
        "observed_at": at,
        "provider": "gitlab",
        "repository_id": "low-voltage",
        "repository_url": "http://git.example/low-voltage.git",
        "branch": "feature/tree-page",
        "commit_sha": "abc123",
        "task_id": "LV-102",
        "task_title": "资料上传更新左侧树状页面",
        "data": {"title": "资料上传更新左侧树状页面"},
    }


def _code_evidence():
    return {
        "source_type": "local_git",
        "relation": "local_change",
        "source": "git_local",
        "kind": "code_change",
        "text": "实现资料上传更新左侧树状页面",
        "task_id": "LV-102",
        "confidence": "high",
    }


def _prepare_people_db(tmp_path, monkeypatch):
    db_path = tmp_path / "project.db"
    monkeypatch.setattr(platform_config, "DB_PATH", db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE projects (
                project_id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_user_id TEXT,
                last_device_id TEXT,
                last_workspace_name TEXT
            );
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
            CREATE TABLE agent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE TABLE remote_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                data_json TEXT NOT NULL
            );
            """
        )
    return db_path


def test_case1_new_document_wins_old_history_and_claim_is_not_formal_completion():
    title = "资料上传更新左侧树状页面"
    local = fuse_evidence(
        _payload(
            current_facts=[
                {"type": "task", "text": title, "task_key": "LV-102"},
                {"type": "progress", "text": f"{title}已完成", "task_key": "LV-102"},
            ],
            historical_facts=[
                {"type": "task", "text": f"{title}待开发", "task_key": "LV-102"}
            ],
        ),
        [],
    )
    result = apply_remote_evidence(local, [])
    assert len(result["work_items"]) == 1
    item = result["work_items"][0]
    assert item["completion_claimed"] is True
    assert item["formal_completion"] is False
    assert all("待开发" not in (entry.get("text") or entry.get("summary") or "") for entry in item["evidence"])


def test_case2_agent_finished_test_pass_and_dirty_local_code_is_local_verified():
    evidence = [
        {"source_type": "document", "relation": "requirement", "text": "资料上传更新左侧树状页面", "task_id": "LV-102"},
        _code_evidence(),
        {"source_type": "agent", "relation": "agent_finished", "summary": "Agent finished", "task_id": "LV-102", "observed_at": "2026-09-11T08:00:00Z"},
        {"source_type": "agent", "relation": "agent_test_pass", "summary": "3/3 passed", "task_id": "LV-102", "observed_at": "2026-09-11T08:10:00Z"},
    ]
    normalized = normalize_evidence(evidence)
    assert {entry["relation"] for entry in normalized} >= {"agent_finished", "agent_test_pass"}
    assert all(entry["source_type"] in {"document", "local_git", "agent"} for entry in normalized)

    item = apply_remote_evidence(_fusion(evidence, status="locally_complete_uncommitted", dirty=True), [])["work_items"][0]
    assert item["completion_claimed"] is True
    assert item["formal_completion"] is False
    assert item["formal_status"] == "local_verified"
    assert "local_verified_uncommitted" in item["flags"]


def test_case3_document_completed_but_latest_ci_failed_blocks_completion():
    evidence = [
        _code_evidence(),
        {"source_type": "document", "relation": "completion_claim", "text": "资料显示已完成", "task_id": "LV-102"},
    ]
    result = apply_remote_evidence(
        _fusion(evidence),
        [
            _remote("git.push", "2026-09-11T08:00:00Z"),
            _remote("ci.failed", "2026-09-11T08:10:00Z"),
        ],
    )
    item = result["work_items"][0]
    assert item["formal_status"] == "ci_failed"
    assert item["formal_completion"] is False


def test_case4_ci_passed_and_merged_but_deployment_failed():
    result = apply_remote_evidence(
        _fusion([_code_evidence()]),
        [
            _remote("ci.passed", "2026-09-11T08:00:00Z"),
            _remote("merge_request.merged", "2026-09-11T08:10:00Z"),
            _remote("deployment.failed", "2026-09-11T08:20:00Z"),
        ],
    )
    item = result["work_items"][0]
    assert item["formal_status"] == "deployment_failed"
    assert item["formal_completion"] is False


def test_case5_local_and_agent_same_user_resolve_to_same_person_in_session(tmp_path, monkeypatch):
    db_path = _prepare_people_db(tmp_path, monkeypatch)
    when = "2026-09-11T08:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO snapshots(project_id, project_name, user_id, device_id, workspace_name, observed_at, received_at, snapshot_type, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, 'workspace', ?)",
            ("demo", "Demo", "cyh", "mac", "repo", when, when, json.dumps({"collector": {"version": "1"}})),
        )
        conn.execute(
            "INSERT INTO agent_events(project_id, user_id, observed_at, received_at) VALUES (?, ?, ?, ?)",
            ("demo", "cyh", when, when),
        )

    people = people_store.list_people()
    person = next(item for item in people["people"] if item.get("person_id"))
    assert {identity["provider"] for identity in person["identities"]} == {"local", "agent"}

    projection = build_agent_sessions(
        [
            {
                "client_event_id": "a1",
                "project_id": "demo",
                "user_id": "cyh",
                "event_type": "task.started",
                "observed_at": when,
                "session_id": "session-cyh",
                "task_id": "LV-102",
                "task_title": "资料上传更新左侧树状页面",
                "agent": {"name": "Codex"},
                "data": {},
            }
        ],
        project_id="demo",
        now="2026-09-11T08:01:00+00:00",
    )
    resolved = agent_api._resolve_projection_people(projection)
    session = resolved["sessions"][0]
    assert session["user_id"] == "cyh"
    assert session["person_id"] == person["person_id"]


def test_case6_gitlab_caoyh_and_local_cyh_are_not_guessed_as_same_person(tmp_path, monkeypatch):
    db_path = _prepare_people_db(tmp_path, monkeypatch)
    when = "2026-09-11T08:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO snapshots(project_id, project_name, user_id, device_id, workspace_name, observed_at, received_at, snapshot_type, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, 'workspace', ?)",
            ("demo", "Demo", "cyh", "mac", "repo", when, when, "{}"),
        )
        conn.execute(
            "INSERT INTO remote_events(project_id, provider, observed_at, received_at, data_json) VALUES (?, 'gitlab', ?, ?, ?)",
            ("demo", when, when, json.dumps({"author_username": "caoyh", "author_name": "炎浩"})),
        )

    payload = people_store.list_people()
    local_person = next(
        item
        for item in payload["people"]
        if item.get("person_id") and any(identity["provider"] == "local" and identity["external_id"] == "cyh" for identity in item["identities"])
    )
    remote_identity = next(
        identity
        for identity in people_store.list_identities(unassigned_only=True)
        if identity["provider"] == "gitlab" and identity["external_id"] == "caoyh"
    )
    assert local_person["person_id"] is not None
    assert remote_identity["person_id"] is None
    assert remote_identity["confirmed"] is False
