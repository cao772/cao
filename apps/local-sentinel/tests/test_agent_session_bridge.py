from datetime import datetime, timedelta, timezone

import agent_bridge
import agent_session_bridge


def _fake_build_agent_event(**kwargs):
    return {
        "event_type": kwargs["event_type"],
        "project_id": kwargs["project_id"],
        "user_id": agent_bridge.USER_ID,
        "agent": {"name": agent_bridge.AGENT_NAME, "vendor": agent_bridge.AGENT_VENDOR},
        "session_id": kwargs.get("session_id"),
        "task_id": kwargs.get("task_id"),
        "task_title": kwargs.get("task_title"),
        "data": dict(kwargs.get("data") or {}),
    }


def test_explicit_session_is_preserved():
    agent_session_bridge.reset_fallback_sessions()
    assert agent_session_bridge.resolve_session_id("p1", "session-explicit") == "session-explicit"


def test_fallback_session_reuses_until_inactivity_timeout(monkeypatch):
    agent_session_bridge.reset_fallback_sessions()
    current = datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(agent_session_bridge, "_clock", lambda: current)
    first = agent_session_bridge.resolve_session_id("p1")
    current = current + timedelta(minutes=30)
    second = agent_session_bridge.resolve_session_id("p1")
    current = current + timedelta(minutes=61)
    third = agent_session_bridge.resolve_session_id("p1")
    assert first == second
    assert third != first


def test_different_users_do_not_share_fallback_session(monkeypatch):
    agent_session_bridge.reset_fallback_sessions()
    monkeypatch.setattr(agent_session_bridge, "_clock", lambda: datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(agent_bridge, "USER_ID", "cyh")
    first = agent_session_bridge.resolve_session_id("p1")
    monkeypatch.setattr(agent_bridge, "USER_ID", "yj")
    second = agent_session_bridge.resolve_session_id("p1")
    assert first != second


def test_report_v2_adds_client_event_task_key_person_and_redacts_sensitive_data(monkeypatch):
    agent_session_bridge.reset_fallback_sessions()
    monkeypatch.setattr(agent_bridge, "USER_ID", "cyh")
    monkeypatch.setattr(agent_bridge, "CENTRAL_URL", "")
    monkeypatch.setattr(agent_bridge, "build_agent_event", _fake_build_agent_event)
    monkeypatch.setattr(agent_session_bridge, "_clock", lambda: datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc))
    result = agent_session_bridge.report_agent_event_v2(
        event_type="task.progress",
        project_id="p1",
        task_title="demo",
        task_key="LV-102",
        person_id="person-1",
        client_event_id="evt-1",
        data={
            "summary": "ok",
            "api_key": "secret",
            "nested": {"access_token": "abc"},
            "chain_of_thought": "private",
            "stdout": "huge output",
        },
    )
    event = result["event"]
    assert event["client_event_id"] == "evt-1"
    assert event["session_id"].startswith("fallback-")
    assert event["data"]["task_key"] == "LV-102"
    assert event["data"]["person_id"] == "person-1"
    assert event["data"]["api_key"] == "[REDACTED]"
    assert event["data"]["nested"]["access_token"] == "[REDACTED]"
    assert event["data"]["chain_of_thought"] == "[OMITTED]"
    assert event["data"]["stdout"] == "[OMITTED]"


def test_report_v2_posts_same_structured_event_when_central_available(monkeypatch):
    monkeypatch.setattr(agent_bridge, "CENTRAL_URL", "http://central")
    monkeypatch.setattr(agent_bridge, "build_agent_event", _fake_build_agent_event)
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update({"method": method, "path": path, "payload": payload})
        return {"accepted": True}

    monkeypatch.setattr(agent_bridge, "_central_request", fake_request)
    result = agent_session_bridge.report_agent_event_v2(
        event_type="test.result",
        project_id="p1",
        task_id="T1",
        session_id="s1",
        client_event_id="evt-2",
        data={"status": "passed"},
    )
    assert result["accepted"] is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/agent-events"
    assert captured["payload"]["client_event_id"] == "evt-2"
