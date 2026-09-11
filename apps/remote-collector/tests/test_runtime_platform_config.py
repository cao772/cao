from __future__ import annotations

import json

import gitlab_collector


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_load_config_prefers_central_runtime_registry(monkeypatch, tmp_path):
    runtime = {
        "configured": True,
        "version": 1,
        "gitlab_base_url": "http://git.runtime.test",
        "gitlab_token": "runtime-token",
        "projects": [
            {
                "project_id": "p1",
                "project_name": "项目一",
                "repositories": [
                    {
                        "id": "gitlab-101",
                        "role": "application",
                        "provider": "gitlab",
                        "url": "http://git.runtime.test/group/repo",
                        "api_project_path": "group/repo",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(gitlab_collector, "CENTRAL_URL", "http://server:8080")
    monkeypatch.setattr(gitlab_collector, "COLLECTOR_TOKEN", "collector-secret")
    monkeypatch.setattr(gitlab_collector, "CONFIG_PATH", tmp_path / "missing.yaml")
    monkeypatch.setattr(gitlab_collector.urllib.request, "urlopen", lambda request, timeout: FakeResponse(runtime))

    config = gitlab_collector.load_config()

    assert config["projects"][0]["project_id"] == "p1"
    assert gitlab_collector.GITLAB_BASE_URL == "http://git.runtime.test"
    assert gitlab_collector.GITLAB_TOKEN == "runtime-token"


def test_load_config_falls_back_to_yaml_when_runtime_not_configured(monkeypatch, tmp_path):
    config_path = tmp_path / "gitlab-projects.yaml"
    config_path.write_text(
        "version: 1\nprojects:\n  - project_id: fallback\n    repositories: []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gitlab_collector, "CENTRAL_URL", "http://server:8080")
    monkeypatch.setattr(gitlab_collector, "COLLECTOR_TOKEN", "collector-secret")
    monkeypatch.setattr(gitlab_collector, "CONFIG_PATH", config_path)
    monkeypatch.setattr(
        gitlab_collector.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse({"configured": False, "version": 1, "projects": []}),
    )

    config = gitlab_collector.load_config()

    assert config["projects"][0]["project_id"] == "fallback"
