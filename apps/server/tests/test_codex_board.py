import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import codex_board_api as board
import execution_p2 as p2
import execution_provider as ep
from test_execution_provider import configured  # noqa: F401


@pytest.fixture
def setup(configured, monkeypatch):
    monkeypatch.setenv("CAO_MUSE_TOKEN", "execution-test-token")
    monkeypatch.setenv("CAO_MUSE_BOARD_TOKEN", "b" * 32)
    config = json.loads(configured.read_text())
    config["bindings"][0].update(
        personal_enabled=True,
        display_alias="P09",
        board_file_details_enabled=True,
        board_event_user_id="authorized-user",
    )
    config["url"] = "http://127.0.0.1:4879"
    configured.write_text(json.dumps(config))
    record = dict(
        id=str(uuid4()),
        project_id="business",
        repository_id="repo-a",
        workspace_id="workspace",
        session_id="terminal",
        agent_session_id="harness",
        task_id="task",
        task_title="属性解析",
        p2=True,
        tool_policy_version=2,
        muse_capability=p2.muse_capability("execution-test-token"),
        provider_instance=config["url"],
        model_profile="balanced",
    )
    with ep.db() as conn:
        conn.execute(
            "INSERT INTO executions VALUES (?,?,?)", (record["id"], "{}", json.dumps(record))
        )
        conn.commit()
    monkeypatch.setattr(ep.main, "recent_agent_events", lambda *args: [])
    monkeypatch.setattr(
        board,
        "read_host",
        lambda *args: [
            {"sessions": [{"terminalId": "terminal", "exited": False}]},
            [
                dict(
                    terminalId="terminal",
                    agentSessionId="harness",
                    agentId="codex",
                    lastEventType="Stop",
                )
            ],
        ],
    )
    app = FastAPI()
    app.include_router(board.router)
    app.include_router(p2.router)
    return TestClient(app), configured, record


def get(client, token="b" * 32):
    return client.get("/api/v1/personal-agent/codex-board", headers={"X-Muse-Token": token})


@pytest.mark.parametrize("token", ["", "execution-test-token", "test-access", "wrong"])
def test_requires_separate_read_capability(setup, token):
    assert get(setup[0], token).status_code == 401


def test_board_token_cannot_execute(setup):
    response = setup[0].get(
        "/api/v1/personal/execution/provider", headers={"X-Muse-Token": "b" * 32}
    )
    assert response.status_code == 401


def test_bound_summary_no_mutation_or_private_fields(setup, monkeypatch):
    monkeypatch.setattr(ep, "call", lambda *a, **k: pytest.fail("No mutating inspect/Host helper"))
    data = get(setup[0]).json()
    task = data["projects"][0]["tasks"][0]
    assert task["state"] == "needs_input" and task["feedback_allowed"]
    assert task["progress"] is None and task["tests_passed"] is None
    assert not task["formal_completion"]
    assert not any(
        x in json.dumps(data)
        for x in ("harness", "terminal", "muse_capability", "workspace", "prompt")
    )
    assert data["coverage"]["untracked_count"] is None


@pytest.mark.parametrize("change", ["repository", "capability", "disabled"])
def test_reauthorization_filters(setup, change):
    client, path, record = setup
    cfg = json.loads(path.read_text())
    if change == "disabled":
        cfg["bindings"][0]["personal_enabled"] = False
    else:
        record["repository_id" if change == "repository" else "muse_capability"] = "wrong"
        with ep.db() as conn:
            conn.execute("UPDATE executions SET result_json=?", (json.dumps(record),))
            conn.commit()
    path.write_text(json.dumps(cfg))
    assert get(client).json()["projects"] == []


def test_host_offline_cannot_report_running(setup, monkeypatch):
    monkeypatch.setattr(board, "read_host", lambda *args: None)
    data = get(setup[0]).json()
    assert data["status"] == "stale"
    assert data["projects"][0]["tasks"][0]["state"] == "stale"
    assert not data["projects"][0]["tasks"][0]["feedback_allowed"]


def test_replaced_harness_is_unknown(setup, monkeypatch):
    monkeypatch.setattr(
        board,
        "read_host",
        lambda *args: [
            {"sessions": [{"terminalId": "terminal"}]},
            [dict(terminalId="terminal", agentSessionId="replacement", agentId="codex")],
        ],
    )
    assert get(setup[0]).json()["projects"][0]["tasks"][0]["state"] == "unknown"


def test_exact_events_and_relative_file_evidence(setup, monkeypatch):
    record = setup[2]
    base = dict(
        user_id="authorized-user",
        task_id="task",
        session_id=record["id"],
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    monkeypatch.setattr(
        ep.main,
        "recent_agent_events",
        lambda *a: [
            {
                **base,
                "session_id": "other",
                "event_type": "task.progress",
                "data": {"summary": "wrong"},
            },
            {
                **base,
                "event_type": "task.progress",
                "data": {
                    "summary": "正在测试",
                    "phase": "testing",
                    "files": ["src/main.py", "/Users/private", "../secret"],
                },
            },
            {**base, "event_type": "test.result", "data": {"passed": 12, "failed": 0}},
        ],
    )
    task = get(setup[0]).json()["projects"][0]["tasks"][0]
    assert task["progress"] == "正在测试" and task["files"] == ["src/main.py"]
    assert task["tests_passed"] == 12 and task["tests_failed"] == 0


@pytest.mark.parametrize(
    "text", ["sk-private", "/Users/private/x", "Bearer secret", "https://private"]
)
def test_private_event_text_omitted(setup, monkeypatch, text):
    r = setup[2]
    monkeypatch.setattr(
        ep.main,
        "recent_agent_events",
        lambda *a: [
            dict(
                user_id="authorized-user",
                task_id=r["task_id"],
                session_id=r["id"],
                observed_at=datetime.now(timezone.utc).isoformat(),
                event_type="task.progress",
                data={"summary": text},
            )
        ],
    )
    assert get(setup[0]).json()["projects"][0]["tasks"][0]["progress"] is None


def test_registered_external_sessions_only_read(setup):
    client, path, record = setup
    cfg = json.loads(path.read_text())
    foreign = {**record, "id": str(uuid4()), "p2": False, "session_id": "other"}
    cfg["codex_board_sessions"] = [foreign, {**foreign, "repository_id": "private"}]
    path.write_text(json.dumps(cfg))
    tasks = get(client).json()["projects"][0]["tasks"]
    assert len(tasks) == 2
    external = next(t for t in tasks if t["source"] == "registered_host")
    assert not external["feedback_allowed"]


def test_fifty_projects_five_tasks_and_duplicate_session_bound(setup, monkeypatch):
    client, path, record = setup
    cfg = json.loads(path.read_text())
    cfg["bindings"] = [
        dict(
            project_id=f"p{i}",
            repository_id=f"r{i}",
            personal_enabled=True,
            display_alias=f"P{i:02}",
        )
        for i in range(50)
    ]
    sessions = [
        {
            **record,
            "id": str(uuid4()),
            "p2": False,
            "project_id": f"p{i}",
            "repository_id": f"r{i}",
            "workspace_id": f"w{i}",
            "session_id": f"t{j}",
            "task_id": f"task{j}",
        }
        for i in range(50)
        for j in range(5)
    ]
    cfg["codex_board_sessions"] = sessions + [sessions[0]]
    path.write_text(json.dumps(cfg))
    data = get(client).json()
    assert len(data["projects"]) == 50
    assert sum(len(p["tasks"]) for p in data["projects"]) == 250
    assert data["coverage"]["registered_project_count"] == 50


def test_file_detail_requires_explicit_binding_flag(setup, monkeypatch):
    client, path, record = setup
    cfg = json.loads(path.read_text())
    cfg["bindings"][0].pop("board_file_details_enabled")
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(
        ep.main,
        "recent_agent_events",
        lambda *a: [
            dict(
                user_id="authorized-user",
                task_id=record["task_id"],
                session_id=record["id"],
                observed_at=datetime.now(timezone.utc).isoformat(),
                event_type="task.progress",
                data={"files": ["src/private.py"]},
            )
        ],
    )
    assert get(client).json()["projects"][0]["tasks"][0]["files"] is None


def test_readonly_project_binding_does_not_grant_execution(setup):
    client, path, record = setup
    cfg = json.loads(path.read_text())
    cfg["bindings"][0].update(personal_enabled=False, board_enabled=True)
    cfg["codex_board_sessions"] = [
        {**record, "id": str(uuid4()), "p2": False, "display_title": "Read only"}
    ]
    path.write_text(json.dumps(cfg))
    data = get(client).json()
    assert len(data["projects"]) == 1 and not data["projects"][0]["tasks"][0]["feedback_allowed"]
    with pytest.raises(ep.HTTPException) as error:
        p2.require_muse_run(record, cfg, "execution-test-token")
    assert error.value.status_code == 403


def test_other_user_same_task_and_session_cannot_leak(setup, monkeypatch):
    record = setup[2]
    monkeypatch.setattr(
        ep.main,
        "recent_agent_events",
        lambda *a: [
            dict(
                user_id="other-user",
                task_id=record["task_id"],
                session_id=record["id"],
                observed_at=datetime.now(timezone.utc).isoformat(),
                event_type="task.progress",
                data={"summary": "private summary"},
            )
        ],
    )
    assert get(setup[0]).json()["projects"][0]["tasks"][0]["progress"] is None
