from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import model_config
import platform_config


def _client(tmp_path, monkeypatch):
    db_path = tmp_path / "project.db"
    key_path = tmp_path / "platform.key"
    monkeypatch.setattr(platform_config, "DB_PATH", db_path)
    monkeypatch.setattr(platform_config, "PLATFORM_KEY_PATH", key_path)
    model_config.platform_config.DB_PATH = db_path
    model_config.platform_config.PLATFORM_KEY_PATH = key_path
    app = FastAPI()
    app.include_router(model_config.router)
    return TestClient(app)


def test_model_api_key_is_encrypted_and_masked(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    saved = client.put(
        "/api/v1/platform/model",
        json={
            "base_url": "https://model.example.test/v1",
            "model": "fast-model",
            "api_key": "sk-secret-9876",
            "allow_remote_endpoint": True,
            "timeout_seconds": 45,
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["configured"] is True
    assert body["api_key_hint"] == "****9876"
    assert "sk-secret" not in str(body)
    with platform_config._db() as conn:
        row = conn.execute("SELECT api_key_cipher FROM model_connections WHERE connection_id='default'").fetchone()
    assert row["api_key_cipher"] != "sk-secret-9876"
    assert platform_config.decrypt_secret(row["api_key_cipher"]) == "sk-secret-9876"


def test_model_internal_runtime_requires_collector_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.put(
        "/api/v1/platform/model",
        json={
            "base_url": "http://host.docker.internal:8000/v1",
            "model": "local-model",
            "api_key": "secret-key",
            "allow_remote_endpoint": False,
            "timeout_seconds": 60,
        },
    )
    monkeypatch.setattr(platform_config, "COLLECTOR_TOKEN", "collector-secret")
    denied = client.get("/api/v1/internal/model/runtime-config")
    assert denied.status_code == 401
    allowed = client.get(
        "/api/v1/internal/model/runtime-config",
        headers={"X-Collector-Token": "collector-secret"},
    )
    assert allowed.status_code == 200
    runtime = allowed.json()
    assert runtime["api_key"] == "secret-key"
    assert runtime["model"] == "local-model"
