from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import platform_config
import project_settings


def _client(tmp_path, monkeypatch):
    db_path = tmp_path / "project.db"
    key_path = tmp_path / "platform.key"
    monkeypatch.setattr(platform_config, "DB_PATH", db_path)
    monkeypatch.setattr(platform_config, "PLATFORM_KEY_PATH", key_path)
    project_settings.platform_config.DB_PATH = db_path
    project_settings.platform_config.PLATFORM_KEY_PATH = key_path
    platform_config.init_platform_db()
    with platform_config._db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, project_name TEXT NOT NULL, last_seen_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO projects VALUES ('p1', '项目一', '2026-09-11T00:00:00Z')")
    app = FastAPI()
    app.include_router(project_settings.router)
    return TestClient(app)


def test_project_settings_default_and_local_analysis_normalization(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    default = client.get("/api/v1/platform/projects/p1/settings")
    assert default.status_code == 200
    assert default.json()["enabled"] is True
    assert default.json()["security_mode"] == "metadata_only"
    assert default.json()["analysis_enabled"] is False

    saved = client.put(
        "/api/v1/platform/projects/p1/settings",
        json={
            "enabled": True,
            "security_mode": "local_analysis",
            "analysis_enabled": True,
            "use_llm": True,
            "include": ["documents", "tests"],
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["analysis_enabled"] is True
    assert body["use_llm"] is True
    assert body["include"] == ["documents", "tests"]


def test_metadata_only_forces_content_analysis_off(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    saved = client.put(
        "/api/v1/platform/projects/p1/settings",
        json={
            "enabled": False,
            "security_mode": "metadata_only",
            "analysis_enabled": True,
            "use_llm": True,
            "include": ["documents"],
        },
    )
    body = saved.json()
    assert body["enabled"] is False
    assert body["analysis_enabled"] is False
    assert body["use_llm"] is False


def test_internal_runtime_settings_requires_collector_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(platform_config, "COLLECTOR_TOKEN", "secret")
    denied = client.get("/api/v1/internal/projects/runtime-settings")
    assert denied.status_code == 401
    allowed = client.get(
        "/api/v1/internal/projects/runtime-settings",
        headers={"X-Collector-Token": "secret"},
    )
    assert allowed.status_code == 200
    assert "p1" in allowed.json()["projects"]
