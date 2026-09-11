from agent_sessions import build_agent_sessions


def _event(ts, event_type, **extra):
    data = dict(extra.pop("data", {}) or {})
    return {
        "project_id": "p1",
        "user_id": extra.pop("user_id", "u1"),
        "event_type": event_type,
        "observed_at": ts,
        "agent": extra.pop("agent", {"name": "Codex", "vendor": "OpenAI"}),
        "session_id": extra.pop("session_id", "s1"),
        "task_id": extra.pop("task_id", None),
        "task_title": extra.pop("task_title", None),
        "data": data,
        **extra,
    }


def test_timeline_uses_observed_at_not_input_order():
    result = build_agent_sessions(
        [
            _event("2026-09-11T10:20:00+00:00", "task.progress", task_id="A"),
            _event("2026-09-11T10:00:00+00:00", "task.started", task_id="A"),
            _event("2026-09-11T10:10:00+00:00", "test.result", task_id="A", data={"status": "passed"}),
        ],
        project_id="p1",
        now="2026-09-11T10:21:00+00:00",
    )
    assert [item["event_type"] for item in result["sessions"][0]["timeline"]] == [
        "task.started", "test.result", "task.progress"
    ]


def test_task_key_has_priority_over_task_id():
    result = build_agent_sessions(
        [_event("2026-09-11T10:00:00+00:00", "task.started", task_id="legacy", data={"task_key": "LV-1"})],
        project_id="p1",
        now="2026-09-11T10:01:00+00:00",
    )
    task = result["sessions"][0]["tasks"][0]
    assert task["task_ref"] == "task_key:LV-1"
    assert task["task_key"] == "LV-1"
    assert task["task_id"] == "legacy"


def test_failed_test_is_normalized_without_completion_claim():
    result = build_agent_sessions(
        [_event("2026-09-11T10:00:00+00:00", "test.result", task_id="A", data={"passed": 4, "failed": 1})],
        project_id="p1",
        now="2026-09-11T10:01:00+00:00",
    )
    task = result["sessions"][0]["tasks"][0]
    assert task["tests"][0] == {
        "status": "failed",
        "passed": 4,
        "failed": 1,
        "total": 5,
        "command_summary": None,
        "observed_at": "2026-09-11T10:00:00+00:00",
    }
    assert task["completion_claimed_by_agent"] is False


def test_title_only_overlap_never_generates_concurrent_agent_flag():
    result = build_agent_sessions(
        [
            _event("2026-09-11T10:00:00+00:00", "task.started", session_id="a", task_title="同名任务"),
            _event(
                "2026-09-11T10:01:00+00:00",
                "task.started",
                session_id="b",
                task_title="同名任务",
                agent={"name": "TRAE", "vendor": "other"},
            ),
        ],
        project_id="p1",
        now="2026-09-11T10:02:00+00:00",
    )
    assert not any(item.get("flag") == "concurrent_agents_same_task" for item in result["flags"])


def test_unlinked_finish_keeps_event_and_flags_missing_task_without_fake_engineering_state():
    result = build_agent_sessions(
        [_event("2026-09-11T10:00:00+00:00", "task.finished")],
        project_id="p1",
        now="2026-09-11T10:01:00+00:00",
    )
    session = result["sessions"][0]
    assert session["task_count"] == 0
    assert "agent_finished_without_task" in session["flags"]
    assert session["engineering_state"] is None
    assert "work_hours" not in session
    assert "efficiency" not in session
