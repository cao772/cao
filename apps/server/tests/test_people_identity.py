from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import people_identity
import people_store
import platform_config


def _prepare_db(tmp_path, monkeypatch):
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


def _snapshot(conn, *, project_id, project_name, user_id, device_id, workspace, when, version="1.2.3"):
    conn.execute(
        """
        INSERT INTO snapshots(
            project_id, project_name, user_id, device_id, workspace_name,
            observed_at, received_at, snapshot_type, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'workspace', ?)
        """,
        (
            project_id,
            project_name,
            user_id,
            device_id,
            workspace,
            when,
            when,
            json.dumps({"collector": {"version": version}}),
        ),
    )


def _agent(conn, *, project_id, user_id, when):
    conn.execute(
        "INSERT INTO agent_events(project_id, user_id, observed_at, received_at) VALUES (?, ?, ?, ?)",
        (project_id, user_id, when, when),
    )


def _remote(conn, *, project_id, provider, when, **data):
    conn.execute(
        "INSERT INTO remote_events(project_id, provider, observed_at, received_at, data_json) VALUES (?, ?, ?, ?, ?)",
        (project_id, provider, when, when, json.dumps(data)),
    )


def _person(payload, display_name):
    return next(item for item in payload["people"] if item.get("display_name") == display_name and item.get("person_id"))


def test_local_agent_one_person_multiple_devices_and_projects(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id="low-voltage", project_name="低电压", user_id="cyh", device_id="mac", workspace="web", when=now)
        _snapshot(conn, project_id="power-defect", project_name="缺陷处置", user_id="cyh", device_id="win", workspace="agent", when=now)
        _agent(conn, project_id="low-voltage", user_id="cyh", when=now)

    payload = people_store.list_people()
    assert payload["person_count"] == 1
    person = _person(payload, "cyh")
    assert {item["provider"] for item in person["identities"]} == {"local", "agent"}
    assert {item["device_id"] for item in person["devices"]} == {"mac", "win"}
    assert {item["project_id"] for item in person["projects"]} == {"low-voltage", "power-defect"}
    assert all(item["role"] == "participant" for item in person["projects"])
    assert "owner" not in person
    assert "contribution_score" not in person

    second = people_store.list_people()
    assert second["person_count"] == 1
    assert len(people_store.list_identities()) == 2


def test_different_local_users_are_not_automatically_merged(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id="demo", project_name="Demo", user_id="cyh", device_id="mac", workspace="a", when=now)
        _snapshot(conn, project_id="demo", project_name="Demo", user_id="caoyh", device_id="win", workspace="b", when=now)
    payload = people_store.list_people()
    assert payload["person_count"] == 2
    assert {item["display_name"] for item in payload["people"] if item.get("person_id")} == {"cyh", "caoyh"}


def test_same_gitlab_and_local_username_remains_unconfirmed(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id="demo", project_name="Demo", user_id="zhangsan", device_id="mac", workspace="a", when=now)
        _remote(conn, project_id="demo", provider="gitlab", when=now, author_username="zhangsan", author_name="张三")

    payload = people_store.list_people()
    assert payload["person_count"] == 1
    assert payload["unconfirmed_identity_count"] == 1
    unresolved = next(item for item in payload["people"] if item.get("person_id") is None)
    assert unresolved["identity_status"] == "unconfirmed"
    assert unresolved["identities"][0]["provider"] == "gitlab"


def test_manual_gitlab_binding_merges_contributor_projection(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id="demo", project_name="Demo", user_id="cyh", device_id="mac", workspace="a", when=now)
        _remote(conn, project_id="demo", provider="gitlab", when=now, author_username="caoyh", author_name="炎浩")

    payload = people_store.list_people()
    person = _person(payload, "cyh")
    bound = people_store.bind_identity(person["person_id"], provider="gitlab", external_id="caoyh")
    assert bound["person_id"] == person["person_id"]
    assert bound["confirmed"] is True

    contributors = people_store.resolve_contributors(
        [
            {
                "user_id": "cyh",
                "display_name": "cyh",
                "workspaces": ["a"],
                "workspace_count": 1,
                "devices": ["mac"],
                "branches": [],
                "repositories": [],
                "agents": [],
                "source_types": ["local"],
                "identity_refs": [{"provider": "local", "external_id": "cyh"}],
                "latest_activity_at": now,
            },
            {
                "user_id": "caoyh",
                "display_name": "炎浩",
                "workspaces": [],
                "workspace_count": 0,
                "devices": [],
                "branches": ["cao"],
                "repositories": ["repo"],
                "agents": [],
                "source_types": ["repository"],
                "identity_refs": [{"provider": "gitlab", "external_id": "caoyh"}],
                "latest_activity_at": now,
            },
        ]
    )
    assert len(contributors) == 1
    assert contributors[0]["person_id"] == person["person_id"]
    assert set(contributors[0]["source_types"]) == {"local", "repository"}


def test_identity_cannot_belong_to_two_people(tmp_path, monkeypatch):
    _prepare_db(tmp_path, monkeypatch)
    first = people_store.create_person("炎浩")
    second = people_store.create_person("宇杰")
    people_store.bind_identity(first["person_id"], provider="gitlab", external_id="caoyh")
    with pytest.raises(people_store.PeopleConflict):
        people_store.bind_identity(second["person_id"], provider="gitlab", external_id="caoyh")


def test_unbind_keeps_raw_event_and_blocks_silent_relink(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id="demo", project_name="Demo", user_id="cyh", device_id="mac", workspace="a", when=now)
        _remote(conn, project_id="demo", provider="gitlab", when=now, author_username="caoyh")
    person = _person(people_store.list_people(), "cyh")
    identity = people_store.bind_identity(person["person_id"], provider="gitlab", external_id="caoyh")
    unbound = people_store.unbind_identity(person["person_id"], identity["identity_id"])
    assert unbound["person_id"] is None
    assert unbound["blocked_auto_link"] is True
    assert next(item for item in people_store.list_identities() if item["identity_id"] == identity["identity_id"])["person_id"] is None
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM remote_events").fetchone()[0] == 1


def test_same_device_conflict_is_explicit(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id="a", project_name="A", user_id="cyh", device_id="shared", workspace="one", when=now)
        _snapshot(conn, project_id="b", project_name="B", user_id="yujie", device_id="shared", workspace="two", when=now)
    devices = people_store.list_devices()
    assert len(devices) == 1
    assert devices[0]["person_id"] is None
    assert devices[0]["identity_conflict"] is True
    assert devices[0]["conflict_code"] == "device_identity_conflict"
    assert {item["external_id"] for item in devices[0]["conflict_identities"]} == {"cyh", "yujie"}


def test_device_online_stale_offline_statuses(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id="a", project_name="A", user_id="u1", device_id="online", workspace="a", when=(now - timedelta(minutes=5)).isoformat())
        _snapshot(conn, project_id="a", project_name="A", user_id="u2", device_id="stale", workspace="b", when=(now - timedelta(hours=2)).isoformat())
        _snapshot(conn, project_id="a", project_name="A", user_id="u3", device_id="offline", workspace="c", when=(now - timedelta(days=2)).isoformat())
    statuses = {item["device_id"]: item["status"] for item in people_store.list_devices()}
    assert statuses == {"online": "online", "stale": "stale", "offline": "offline"}


def test_current_and_historical_project_participation(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id="current", project_name="当前项目", user_id="cyh", device_id="mac", workspace="a", when=(now - timedelta(days=2)).isoformat())
        _snapshot(conn, project_id="history", project_name="历史项目", user_id="cyh", device_id="mac", workspace="b", when=(now - timedelta(days=60)).isoformat())
    person = _person(people_store.list_people(), "cyh")
    states = {item["project_id"]: item["participation"] for item in person["projects"]}
    assert states == {"current": "current", "history": "historical"}
    assert {item["project_id"] for item in person["current_projects"]} == {"current"}


def test_unbound_gitlab_and_unbound_local_remain_visible(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id="demo", project_name="Demo", user_id="cyh", device_id="mac", workspace="a", when=now)
        _remote(conn, project_id="demo", provider="gitlab", when=now, author_username="orphan")
    person = _person(people_store.list_people(), "cyh")
    local_identity = next(item for item in person["identities"] if item["provider"] == "local")
    people_store.unbind_identity(person["person_id"], local_identity["identity_id"])
    payload = people_store.list_people()
    unresolved = {(item["identities"][0]["provider"], item["identities"][0]["external_id"]) for item in payload["people"] if item.get("person_id") is None}
    assert ("local", "cyh") in unresolved
    assert ("gitlab", "orphan") in unresolved


def test_public_identity_output_hides_email_and_secrets(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        _remote(conn, project_id="demo", provider="gitlab", when=now, author_username="caoyh", author_email="private@example.com")
    identity = people_store.list_identities()[0]
    assert "email" not in identity
    assert identity["has_email"] is True
    serialized = json.dumps(identity)
    assert "private@example.com" not in serialized
    assert "token" not in serialized.lower()
    assert "api_key" not in serialized.lower()


def test_people_api_create_update_list_and_devices(tmp_path, monkeypatch):
    _prepare_db(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(people_identity.router)
    client = TestClient(app)

    created = client.post("/api/v1/platform/people", json={"display_name": "炎浩", "status": "active"})
    assert created.status_code == 200
    person_id = created.json()["person"]["person_id"]
    updated = client.put(f"/api/v1/platform/people/{person_id}", json={"display_name": "炎浩", "status": "inactive"})
    assert updated.status_code == 200
    assert updated.json()["person"]["status"] == "inactive"
    assert client.get("/api/v1/platform/people").status_code == 200
    assert client.get("/api/v1/platform/identities").status_code == 200
    assert client.get("/api/v1/platform/devices").status_code == 200


def test_projection_reuses_history_and_invalidates_on_new_snapshot(tmp_path, monkeypatch):
    db_path = _prepare_db(tmp_path, monkeypatch)
    original = people_store._rebuild_identity_projection
    calls = []
    def rebuild():
        calls.append(1)
        original()
    monkeypatch.setattr(people_store, '_rebuild_identity_projection', rebuild)
    people_store.refresh_identity_projection()
    people_store.refresh_identity_projection()
    assert len(calls) == 1
    when = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        _snapshot(conn, project_id='new-project', project_name='New project', user_id='new-user', device_id='new-device', workspace='new-workspace', when=when)
    people_store.refresh_identity_projection()
    assert len(calls) == 2
    assert people_store.device_by_id('new-device')['device_id'] == 'new-device'
    assert len(calls) == 2


def test_concurrent_projection_requests_share_one_rebuild(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    _prepare_db(tmp_path, monkeypatch)
    original = people_store._rebuild_identity_projection
    calls = []
    def rebuild():
        calls.append(1)
        original()
    monkeypatch.setattr(people_store, '_rebuild_identity_projection', rebuild)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: people_store.refresh_identity_projection(), range(24)))
    assert len(calls) == 1
    people_store.refresh_identity_projection(force=True)
    assert len(calls) == 2


def test_failed_projection_is_retried_and_expired_projection_refreshes(tmp_path, monkeypatch):
    _prepare_db(tmp_path, monkeypatch)
    original = people_store._rebuild_identity_projection
    calls = []
    def rebuild():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('temporary projection failure')
        original()
    monkeypatch.setattr(people_store, '_rebuild_identity_projection', rebuild)
    with pytest.raises(RuntimeError):
        people_store.refresh_identity_projection()
    people_store.refresh_identity_projection()
    assert len(calls) == 2
    monkeypatch.setattr(people_store, '_projection_refreshed_at', people_store._projection_refreshed_at - 16)
    people_store.refresh_identity_projection()
    assert len(calls) == 3
