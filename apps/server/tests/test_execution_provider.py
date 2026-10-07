import json
from uuid import uuid4

import pytest
import httpx
from fastapi import HTTPException

import execution_provider as execution


@pytest.mark.parametrize("procedure", ["workspaces.create", "agents.run", "settings.agentConfigs.list"])
@pytest.mark.parametrize("health", [{"version": "1.37.0"}, {}, None])
def test_incompatible_host_never_receives_mutation(monkeypatch, health, procedure):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"result": {"data": {"json": health}}})

    real_client = httpx.Client
    monkeypatch.setattr(execution.httpx, "Client", lambda **kwargs:
                        real_client(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(HTTPException) as error:
        execution.call({"url": "http://127.0.0.1:4879", "token": "test"},
                       procedure, {}, mutation=procedure != "settings.agentConfigs.list")
    assert error.value.status_code == 503
    assert [request.method for request in requests] == ["GET"]
    assert requests[0].url.path == "/trpc/health.check"


def test_version_is_rechecked_for_each_mutation(monkeypatch):
    writes = []
    versions = iter([execution.SUPPORTED_HOST_VERSION, "changed"])

    def respond(request):
        if request.method == "GET":
            result = {"version": next(versions)}
        else:
            writes.append(request.url.path)
            result = {"ok": True}
        return httpx.Response(200, json={"result": {"data": {"json": result}}})

    real_client = httpx.Client
    monkeypatch.setattr(execution.httpx, "Client", lambda **kwargs:
                        real_client(transport=httpx.MockTransport(respond), **kwargs))
    config = {"url": "http://127.0.0.1:4879", "token": "test"}
    execution.call(config, "workspaces.create", {}, mutation=True)
    with pytest.raises(HTTPException):
        execution.call(config, "agents.run", {}, mutation=True)
    assert writes == ["/trpc/workspaces.create"]


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(execution.main, "DB_PATH", tmp_path / "cao.db")
    monkeypatch.setattr(execution.main, "COLLECTOR_TOKEN", "test-access")
    config = {"url": "http://127.0.0.1:4879", "token": "host-secret",
              "bindings": [{"project_id": "business", "repository_id": "repo-a",
                            "superset_project_id": str(uuid4()), "base_branch": "cao"}]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("CAO_SUPERSET_CONFIG", str(path))
    return path


def request():
    return execution.Launch(request_id=uuid4(), project_id="business", repository_id="repo-a",
                            task_id="TASK-1", task_title="验证本地执行")


def test_requires_explicit_access_token(configured):
    with pytest.raises(HTTPException) as error:
        execution.launch(request(), None)
    assert error.value.status_code == 401


def test_rejects_external_host(configured):
    config = json.loads(configured.read_text())
    config["url"] = "http://example.com:4879"
    configured.write_text(json.dumps(config))
    with pytest.raises(HTTPException) as error:
        execution.settings()
    assert error.value.status_code == 503


def test_desktop_manifest_rotation_is_read_fresh(configured, tmp_path):
    manifest = tmp_path / "manifest.json"
    data = {"endpoint": "http://127.0.0.1:49000", "authToken": "first", "organizationId": "local-org"}
    manifest.write_text(json.dumps(data))
    config = json.loads(configured.read_text())
    config.update(manifest_path=str(manifest), connect_host="host.docker.internal")
    configured.write_text(json.dumps(config))
    assert execution.settings()["url"] == "http://host.docker.internal:49000"
    data.update(endpoint="http://127.0.0.1:49001", authToken="rotated")
    manifest.write_text(json.dumps(data))
    assert execution.settings()["token"] == "rotated"
    data["endpoint"] = "http://external.example:49001"
    manifest.write_text(json.dumps(data))
    with pytest.raises(HTTPException):
        execution.settings()


def test_repository_must_belong_to_project(configured):
    payload = request().model_copy(update={"repository_id": "another-repo"})
    with pytest.raises(HTTPException) as error:
        execution.launch(payload, "test-access")
    assert error.value.status_code == 422


def test_launch_uses_worktree_and_does_not_duplicate_agent_on_retry(configured, monkeypatch):
    calls = []

    def host(config, procedure, payload=None, **kwargs):
        calls.append((procedure, payload))
        if procedure == "workspaces.create":
            assert payload["checkout"] == "worktree"
            assert payload["runSetup"] is False
            return {"workspace": {"id": payload["id"], "branch": payload["branch"]}}
        if procedure == "agents.run":
            return {"sessionId": "terminal-1"}
        return []

    monkeypatch.setattr(execution, "call", host)
    payload = request()
    result = execution.launch(payload, "test-access")
    assert execution.launch(payload, "test-access") == result
    assert result["session_id"] == "terminal-1"
    assert result["formal_completion"] is False
    assert sum(name == "agents.run" for name, _ in calls) == 1
    with pytest.raises(HTTPException) as error:
        execution.launch(payload.model_copy(update={"task_title": "different"}), "test-access")
    assert error.value.status_code == 409


def test_uncertain_agent_launch_is_persisted_without_replay(configured, monkeypatch):
    calls = []

    def host(config, procedure, payload=None, **kwargs):
        calls.append(procedure)
        if procedure == "workspaces.create":
            return {"workspace": {"id": payload["id"], "branch": payload["branch"]}}
        if procedure == "agents.run":
            raise HTTPException(502, "timeout after host may have accepted")
        return []

    monkeypatch.setattr(execution, "call", host)
    payload = request()
    assert execution.launch(payload, "test-access")["status"] == "unknown"
    execution.launch(payload, "test-access")
    assert calls.count("agents.run") == 1


def test_version_block_is_saved_without_replaying_request(configured, monkeypatch):
    calls = []

    def incompatible(config, procedure, payload=None, **kwargs):
        calls.append(procedure)
        raise HTTPException(503, "Host version mismatch")

    monkeypatch.setattr(execution, "call", incompatible)
    payload = request()
    result = execution.launch(payload, "test-access")
    assert result["status"] == "blocked_compatibility"
    assert result["session_id"] is None
    assert result["formal_completion"] is False
    assert execution.launch(payload, "test-access") == result
    assert calls == ["workspaces.create"]


def test_read_status_never_promotes_formal_completion(configured, monkeypatch):
    payload = request()

    def host(config, procedure, data=None, **kwargs):
        if procedure == "workspaces.create":
            return {"workspace": {"id": data["id"], "branch": data["branch"]}}
        if procedure == "agents.run":
            return {"sessionId": "terminal-1"}
        if procedure == "workspace.get":
            return {"id": str(payload.request_id), "worktreePath": "/isolated/worktree"}
        if procedure == "terminal.list":
            return {"sessions": []}
        return []

    monkeypatch.setattr(execution, "call", host)
    execution.launch(payload, "test-access")
    result = execution.inspect(payload.request_id, "test-access")
    assert result["terminals"] == []
    assert result["formal_completion"] is False
