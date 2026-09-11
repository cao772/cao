from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import platform_config


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_config, "DB_PATH", tmp_path / "project.db")
    monkeypatch.setattr(platform_config, "PLATFORM_KEY_PATH", tmp_path / "platform.key")
    platform_config.init_platform_db()
    with platform_config._db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, project_name TEXT NOT NULL, last_seen_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO projects VALUES ('p1', '项目一', '2026-09-11T00:00:00Z')")
        conn.execute("INSERT INTO projects VALUES ('p2', '项目二', '2026-09-11T00:00:00Z')")
    app = FastAPI()
    app.include_router(platform_config.router)
    return TestClient(app)


def test_token_is_encrypted_and_get_is_masked(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.put(
        "/api/v1/platform/gitlab",
        json={"base_url": "http://git.example.test", "token": "glpat-secret-1234"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["token_hint"] == "****1234"
    assert "glpat-secret" not in str(body)
    with platform_config._db() as conn:
        row = conn.execute("SELECT token_cipher FROM source_connections WHERE provider='gitlab'").fetchone()
    assert row["token_cipher"] != "glpat-secret-1234"
    assert platform_config.decrypt_secret(row["token_cipher"]) == "glpat-secret-1234"


def test_discover_returns_binding_state(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.put("/api/v1/platform/gitlab", json={"base_url": "http://git.test", "token": "token-1234"})
    monkeypatch.setattr(
        platform_config,
        "_discover_projects",
        lambda base_url, token, search=None: [{
            "id": "101",
            "name": "algorithm",
            "path_with_namespace": "group/algorithm",
            "web_url": "http://git.test/group/algorithm",
            "default_branch": "main",
            "visibility": "private",
            "last_activity_at": "2026-09-11T00:00:00Z",
        }],
    )
    discovered = client.post("/api/v1/platform/gitlab/discover", json={}).json()
    assert discovered["count"] == 1
    assert discovered["projects"][0]["bound_project_id"] is None


def test_repository_cannot_bind_to_two_business_projects(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    repo = {
        "repository_id": "101",
        "name": "algorithm",
        "path_with_namespace": "group/algorithm",
        "web_url": "http://git.test/group/algorithm",
        "default_branch": "main",
        "visibility": "private",
    }
    first = client.put("/api/v1/platform/projects/p1/repositories", json={"repositories": [repo]})
    assert first.status_code == 200
    conflict = client.put("/api/v1/platform/projects/p2/repositories", json={"repositories": [repo]})
    assert conflict.status_code == 409
    assert "p1" in conflict.json()["detail"]


def test_managed_project_can_be_created_and_bound_before_first_snapshot(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post(
        "/api/v1/platform/projects",
        json={
            "project_id": "new-project",
            "project_name": "新业务项目",
            "description": "尚未完成本机采集",
        },
    )
    assert created.status_code == 200
    assert created.json()["project"]["sampled"] is False

    catalog = client.get("/api/v1/platform/projects").json()
    item = next(project for project in catalog["projects"] if project["project_id"] == "new-project")
    assert item["managed"] is True
    assert item["project_name"] == "新业务项目"

    repo = {
        "repository_id": "202",
        "name": "frontend",
        "path_with_namespace": "group/frontend",
        "web_url": "http://git.test/group/frontend",
        "default_branch": "main",
        "visibility": "private",
    }
    bound = client.put("/api/v1/platform/projects/new-project/repositories", json={"repositories": [repo]})
    assert bound.status_code == 200
    assert bound.json()["repositories"][0]["repository_id"] == "202"


def test_invalid_managed_project_id_is_rejected(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/platform/projects",
        json={"project_id": "../secret", "project_name": "错误项目"},
    )
    assert response.status_code == 422
