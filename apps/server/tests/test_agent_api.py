import agent_api


def _events():
    return [
        {
            "client_event_id": "e1",
            "project_id": "low-voltage",
            "user_id": "cyh",
            "event_type": "task.started",
            "observed_at": "2026-09-11T09:00:00+00:00",
            "agent": {"name": "Codex", "vendor": "OpenAI"},
            "session_id": "session-a",
            "task_id": "LV-102",
            "task_title": "树状改造",
            "data": {},
        }
    ]


def test_agent_api_routes_are_registered():
    paths = {route.path for route in agent_api.router.routes}
    assert "/api/v1/projects/{project_id}/agent-sessions" in paths
    assert "/api/v1/projects/{project_id}/agents" in paths
    assert "/api/v1/agent-sessions/{session_id}" in paths


def test_project_session_and_agent_api_use_projection(monkeypatch):
    monkeypatch.setattr(agent_api.main, "recent_agent_events", lambda project_id, limit: _events())
    monkeypatch.setattr(agent_api.main, "now_utc", lambda: "2026-09-11T09:01:00+00:00")
    sessions = agent_api.list_project_agent_sessions("low-voltage", 100)
    assert sessions["session_count"] == 1
    assert sessions["sessions"][0]["session_id"] == "session-a"
    agents = agent_api.list_project_agents("low-voltage", 100)
    assert agents["agent_count"] == 1
    assert agents["agents"][0]["name"] == "Codex"


def test_session_detail_returns_projection_evidence(monkeypatch):
    monkeypatch.setattr(agent_api, "_agent_event_project_ids", lambda: ["low-voltage"])
    monkeypatch.setattr(agent_api.main, "recent_agent_events", lambda project_id, limit: _events())
    monkeypatch.setattr(agent_api.main, "now_utc", lambda: "2026-09-11T09:01:00+00:00")
    detail = agent_api.get_agent_session_detail("session-a")
    assert detail["project_id"] == "low-voltage"
    assert detail["session"]["tasks"][0]["task_id"] == "LV-102"
    assert detail["evidence"][0]["relation"] == "agent_started"
    assert detail["formal_completion_supported"] is False
