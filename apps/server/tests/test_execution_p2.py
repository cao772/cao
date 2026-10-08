import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import execution_p2 as p2
import execution_provider as ep
from test_execution_provider import configured, request  # noqa: F401


def config_p2(path):
    config = json.loads(path.read_text())
    config.update(
        model_profiles={
            "fast": "verified-fast",
            "balanced": "verified-balanced",
            "strong": "verified-strong",
        },
        p2_agent_id="safe-agent",
        p2_guarded_command="/safe/codex",
    )
    config["bindings"][0]["personal_enabled"] = True
    path.write_text(json.dumps(config))
    return config


def host_calls(monkeypatch, *, mismatch=False, failed_send=False):
    calls = []

    def call(config, procedure, payload=None, **kwargs):
        calls.append((procedure, payload))
        if procedure == "health.check":
            return {"version": ep.SUPPORTED_HOST_VERSION}
        if procedure == "settings.agentConfigs.list":
            return [
                {
                    "id": "safe-agent",
                    "presetId": "codex",
                    "command": "/safe/codex",
                    "args": p2.P2_ARGS,
                    "promptArgs": [],
                    "promptTransport": "argv",
                }
            ]
        if procedure == "terminal.p2Capabilities":
            return {"guardedAgentSend": 2}
        if procedure == "workspaces.create":
            return {"workspace": {"id": payload["id"], "branch": payload["branch"]}}
        if procedure == "agents.run":
            return {"sessionId": "terminal-1"}
        if procedure == "workspace.get":
            return {"id": payload["id"]}
        if procedure == "terminal.list":
            return {"sessions": [{"terminalId": "terminal-1", "exited": False}]}
        if procedure == "terminalAgents.listByWorkspace":
            return [
                {
                    "terminalId": "terminal-1",
                    "workspaceId": payload["workspaceId"],
                    "agentId": "codex",
                    "definitionId": "wrong" if mismatch else "safe-agent",
                    "agentSessionId": "harness-1",
                    "lastEventType": "Stop",
                }
            ]
        if procedure == "terminal.sendAgent":
            if failed_send:
                raise ep.HTTPException(502, "unknown")
            return {"submitted": True}
        raise AssertionError(procedure)

    monkeypatch.setattr(ep, "call", call)
    monkeypatch.setattr(ep.main, "recent_agent_events", lambda *args: [])
    return calls


def launch_p2(configured, monkeypatch, **kwargs):
    config_p2(configured)
    calls = host_calls(monkeypatch, **kwargs)
    payload = request().model_copy(
        update={
            "model_profile": "strong",
            "reasoning_effort": "high",
            "prompt": "实现加法并运行测试",
        }
    )
    result = ep.launch(payload, "test-access")
    return payload, result, calls


@pytest.mark.parametrize("value", ["gpt-anything", "STRONG", "", "auto"])
def test_arbitrary_profiles_rejected(value):
    with pytest.raises(ValidationError):
        ep.Launch(**{**request().model_dump(), "model_profile": value})


def test_profile_resolves_and_preserves_idempotency(configured, monkeypatch):
    payload, result, calls = launch_p2(configured, monkeypatch)
    assert result["resolved_model"] == "verified-strong"
    agent = next(p for name, p in calls if name == "agents.run")
    assert agent["agent"] == "safe-agent" and agent["effort"] == "high"
    assert "Never commit" in agent["prompt"]
    assert ep.launch(payload, "test-access") == result
    assert len([name for name, _ in calls if name == "agents.run"]) == 1


def test_unsafe_preset_never_creates_worktree(configured, monkeypatch):
    config = config_p2(configured)
    calls = []

    def call(config, procedure, payload=None, **kwargs):
        calls.append(procedure)
        return [
            {
                "id": "safe-agent",
                "presetId": "codex",
                "command": "codex",
                "args": ["--yolo"],
            }
        ]

    monkeypatch.setattr(ep, "call", call)
    payload = request().model_copy(
        update={"model_profile": "fast", "prompt": "实现加法并运行测试"}
    )
    result = ep.launch(payload, "test-access")
    assert result["status"] == "blocked_compatibility"
    assert "workspaces.create" not in calls


def test_waiting_is_not_formal_finished_and_no_fake_counts(configured, monkeypatch):
    payload, _, _ = launch_p2(configured, monkeypatch)
    result = ep.inspect(payload.request_id, "test-access")
    assert result["status"] == "waiting" and result["needs_user"]
    assert not result["formal_completion"]
    assert result["tests_passed"] is None
    monkeypatch.setattr(
        ep.main,
        "recent_agent_events",
        lambda *args: [
            {
                "task_id": "other",
                "session_id": str(payload.request_id),
                "event_type": "test.result",
                "data": {"passed": 999, "failed": 0},
            },
            {
                "task_id": payload.task_id,
                "session_id": str(payload.request_id),
                "event_type": "test.result",
                "data": {"passed": 3, "failed": 1},
            },
        ],
    )
    result = ep.inspect(payload.request_id, "test-access")
    assert result["tests_passed"] == 3 and result["tests_failed"] == 1


def test_feedback_sends_once_and_only_metadata_is_saved(configured, monkeypatch):
    payload, _, calls = launch_p2(configured, monkeypatch)
    feedback = p2.Feedback(request_id=uuid4(), text="private feedback content")
    assert p2.feedback(payload.request_id, feedback, "test-access")["status"] == "sent"
    assert p2.feedback(payload.request_id, feedback, "test-access")["status"] == "sent"
    assert sum(name == "terminal.sendAgent" for name, _ in calls) == 1
    with ep.db() as connection:
        raw = str(
            tuple(connection.execute("SELECT * FROM execution_feedback").fetchone())
        )
    assert feedback.text not in raw
    with pytest.raises(ep.HTTPException):
        p2.feedback(
            payload.request_id,
            feedback.model_copy(update={"text": "different"}),
            "test-access",
        )


def test_unknown_feedback_never_replayed(configured, monkeypatch):
    payload, _, calls = launch_p2(configured, monkeypatch, failed_send=True)
    feedback = p2.Feedback(request_id=uuid4(), text="bounded feedback")
    with pytest.raises(ep.HTTPException):
        p2.feedback(payload.request_id, feedback, "test-access")
    assert (
        p2.feedback(payload.request_id, feedback, "test-access")["status"] == "unknown"
    )
    assert sum(name == "terminal.sendAgent" for name, _ in calls) == 1


def test_wrong_binding_or_host_blocks_feedback(configured, monkeypatch):
    payload, _, calls = launch_p2(configured, monkeypatch, mismatch=True)
    with pytest.raises(ep.HTTPException):
        p2.feedback(
            payload.request_id,
            p2.Feedback(request_id=uuid4(), text="test"),
            "test-access",
        )
    assert not any(name == "terminal.sendAgent" for name, _ in calls)
    config = json.loads(configured.read_text())
    config["organization_id"] = "different"
    configured.write_text(json.dumps(config))
    with pytest.raises(ep.HTTPException) as error:
        ep.inspect(payload.request_id, "test-access")
    assert error.value.status_code == 409


def test_muse_capability_is_separate_scoped_and_sanitized(configured, monkeypatch):
    config_p2(configured)
    host_calls(monkeypatch)
    monkeypatch.setenv("CAO_MUSE_TOKEN", "muse-only")
    app = FastAPI()
    app.include_router(p2.router)
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/personal/execution/provider",
                headers={"X-Muse-Token": "test-access"},
            ).status_code
            == 401
        )
        response = client.get(
            "/api/v1/personal/execution/provider", headers={"X-Muse-Token": "muse-only"}
        )
        assert response.status_code == 200 and "host-secret" not in response.text
        assert "superset_project_id" not in response.text
        body = request().model_dump(mode="json")
        body["model_profile"] = "balanced"
        body["prompt"] = "实现加法并运行测试"
        response = client.post(
            "/api/v1/personal/execution/runs",
            headers={"X-Muse-Token": "muse-only"},
            json=body,
        )
        assert response.status_code == 200 and "prompt" not in response.json()
        assert (
            client.get(
                "/api/v1/execution/provider", headers={"X-Muse-Token": "muse-only"}
            ).status_code
            == 404
        )


@pytest.mark.parametrize(
    "text", ["push origin main", "部署生产", "删除仓库", "写数据库", "escape\x1b[2J"]
)
def test_out_of_scope_request_rejected_before_mutation(text):
    with pytest.raises(ep.HTTPException):
        p2.check_scope(text)


def test_negative_scope_instruction_is_allowed():
    p2.check_scope("修复测试，不要提交，禁止部署，never push")


def test_builtin_hook_without_definition_pins_harness_and_rejects_replacement(
    configured, monkeypatch
):
    payload, _, calls = launch_p2(configured, monkeypatch)
    original = ep.call
    session = ["harness-1"]

    def host(config, procedure, data=None, **kwargs):
        if procedure == "terminalAgents.listByWorkspace":
            return [
                {
                    "terminalId": "terminal-1",
                    "workspaceId": data["workspaceId"],
                    "agentId": "codex",
                    "agentSessionId": session[0],
                    "lastEventType": "Stop",
                }
            ]
        return original(config, procedure, data, **kwargs)

    monkeypatch.setattr(ep, "call", host)
    assert ep.inspect(payload.request_id, "test-access")["status"] == "waiting"
    feedback = p2.Feedback(request_id=uuid4(), text="safe feedback")
    assert p2.feedback(payload.request_id, feedback, "test-access")["status"] == "sent"
    sent = next(data for name, data in calls if name == "terminal.sendAgent")
    assert sent["definitionId"] is None and sent["agentSessionId"] == "harness-1"
    session[0] = "replacement"
    assert ep.inspect(payload.request_id, "test-access")["status"] == "unknown"
    with pytest.raises(ep.HTTPException):
        p2.feedback(
            payload.request_id,
            p2.Feedback(request_id=uuid4(), text="do not replay"),
            "test-access",
        )


def test_only_explicit_bridge_client_is_allowed(configured, monkeypatch):
    from starlette.requests import Request

    monkeypatch.setenv("CAO_MUSE_TOKEN", "muse-only")
    request = Request({"type": "http", "client": ("172.22.0.1", 1234), "headers": []})
    with pytest.raises(ep.HTTPException):
        p2.personal_auth(request, "muse-only")
    monkeypatch.setenv("CAO_MUSE_BRIDGE_CLIENT", "172.22.0.1")
    p2.personal_auth(request, "muse-only")
    request = Request({"type": "http", "client": ("172.22.0.99", 1234), "headers": []})
    with pytest.raises(ep.HTTPException):
        p2.personal_auth(request, "muse-only")


@pytest.mark.parametrize("prompt", ["", "   ", "开始开发", "启动 Codex", "测试项目"])
def test_blank_or_operationless_task_rejected_before_host(
    configured, monkeypatch, prompt
):
    config_p2(configured)
    calls = host_calls(monkeypatch)
    payload = request().model_copy(update={"model_profile": "fast", "prompt": prompt})
    with pytest.raises(ep.HTTPException) as exc:
        ep.launch(payload, "test-access")
    assert exc.value.status_code == 422 and not calls


def muse_client(monkeypatch):
    monkeypatch.setenv("CAO_MUSE_TOKEN", "muse-only")
    app = FastAPI()
    app.include_router(p2.router)
    return TestClient(app)


@pytest.mark.parametrize(
    "change", ["different_repo", "revoked", "internal_origin", "rotated_capability"]
)
def test_muse_inspect_and_feedback_recheck_pair_and_origin(
    configured, monkeypatch, change
):
    config_p2(configured)
    calls = host_calls(monkeypatch)
    payload = request().model_copy(
        update={"model_profile": "fast", "prompt": "实现加法并运行测试"}
    )
    headers = {"X-Muse-Token": "muse-only"}
    with muse_client(monkeypatch) as client:
        if change == "internal_origin":
            ep.launch(payload, "test-access")
        else:
            assert (
                client.post(
                    "/api/v1/personal/execution/runs",
                    headers=headers,
                    json=payload.model_dump(mode="json"),
                ).status_code
                == 200
            )
        config = json.loads(configured.read_text())
        if change == "different_repo":
            config["bindings"][0]["personal_enabled"] = False
            config["bindings"].append(
                {
                    **config["bindings"][0],
                    "repository_id": "repo-b",
                    "personal_enabled": True,
                }
            )
        if change == "revoked":
            config["bindings"][0]["personal_enabled"] = False
        if change == "rotated_capability":
            monkeypatch.setenv("CAO_MUSE_TOKEN", "replacement")
            headers = {"X-Muse-Token": "replacement"}
        configured.write_text(json.dumps(config))
        calls.clear()
        url = "/api/v1/personal/execution/runs/" + str(payload.request_id)
        assert client.get(url, headers=headers).status_code == 403
        assert (
            client.post(
                url + "/feedback",
                headers=headers,
                json={"request_id": str(uuid4()), "text": "修复测试"},
            ).status_code
            == 403
        )
        assert not calls


def test_internal_id_cannot_be_reclaimed_as_muse_origin(configured, monkeypatch):
    payload, _, _ = launch_p2(configured, monkeypatch)
    with muse_client(monkeypatch) as client:
        response = client.post(
            "/api/v1/personal/execution/runs",
            headers={"X-Muse-Token": "muse-only"},
            json=payload.model_dump(mode="json"),
        )
    assert response.status_code == 409


def test_internal_http_cannot_set_muse_origin_via_query_parameter(
    configured, monkeypatch
):
    config_p2(configured)
    host_calls(monkeypatch)
    monkeypatch.setenv("CAO_MUSE_TOKEN", "muse-only")
    app = FastAPI()
    app.include_router(ep.router)
    app.include_router(p2.router)
    payload = request().model_copy(
        update={"model_profile": "fast", "prompt": "实现加法并运行测试"}
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/execution/runs",
            params={"muse_capability": p2.muse_capability("muse-only")},
            headers={"X-Collector-Token": "test-access"},
            json=payload.model_dump(mode="json"),
        )
        assert response.status_code == 200
        response = client.get(
            "/api/v1/personal/execution/runs/" + str(payload.request_id),
            headers={"X-Muse-Token": "muse-only"},
        )
        assert response.status_code == 403
