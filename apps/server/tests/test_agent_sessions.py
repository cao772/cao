from agent_sessions import build_agent_sessions, get_agent_session


def event(ts, event_type, *, session_id=None, user="cyh", agent="Codex", task_id=None, task_key=None, title=None, data=None, client=None, person=None):
    payload = dict(data or {})
    if task_key:
        payload["task_key"] = task_key
    if person:
        payload["person_id"] = person
    return {
        "client_event_id": client,
        "project_id": "low-voltage",
        "user_id": user,
        "event_type": event_type,
        "observed_at": ts,
        "agent": {"name": agent, "vendor": "openai" if agent == "Codex" else "other"},
        "session_id": session_id,
        "task_id": task_id,
        "task_title": title,
        "data": payload,
    }


def project(events, now="2026-09-11T12:00:00+00:00"):
    return build_agent_sessions(events, project_id="low-voltage", now=now)


def test_explicit_session_aggregates_events_and_task_finished_is_not_formal_completion():
    result = project([
        event("2026-09-11T10:00:00+00:00", "task.started", session_id="s1", task_key="LV-102", title="树状改造"),
        event("2026-09-11T10:10:00+00:00", "task.progress", session_id="s1", task_key="LV-102", title="树状改造"),
        event("2026-09-11T10:25:00+00:00", "test.result", session_id="s1", task_key="LV-102", data={"passed": 3, "failed": 0}),
        event("2026-09-11T10:30:00+00:00", "task.finished", session_id="s1", task_key="LV-102", title="树状改造"),
    ], now="2026-09-11T10:31:00+00:00")
    session = result["sessions"][0]
    assert session["session_id"] == "s1"
    assert session["event_count"] == 4
    assert session["task_count"] == 1
    assert session["status"] == "active"
    assert session["tasks"][0]["agent_state"] == "finished"
    assert session["tasks"][0]["completion_claimed_by_agent"] is True
    assert session["tasks"][0]["formal_completion"] is None
    assert result["formal_completion_supported"] is False


def test_fallback_continuous_events_share_session_and_timeout_creates_new_one():
    result = project([
        event("2026-09-11T08:00:00+00:00", "task.started", task_id="A"),
        event("2026-09-11T08:30:00+00:00", "task.progress", task_id="A"),
        event("2026-09-11T10:01:00+00:00", "task.started", task_id="B"),
    ])
    assert result["session_count"] == 2
    early = sorted(result["sessions"], key=lambda item: item["started_at"])[0]
    assert early["event_count"] == 2
    assert early["session_source"] == "fallback"


def test_same_agent_different_users_do_not_merge_fallback_sessions():
    result = project([
        event("2026-09-11T09:00:00+00:00", "task.started", user="cyh", task_id="A"),
        event("2026-09-11T09:01:00+00:00", "task.started", user="yj", task_id="B"),
    ])
    assert result["session_count"] == 2
    assert {item["user_id"] for item in result["sessions"]} == {"cyh", "yj"}


def test_one_session_can_hold_multiple_tasks_and_one_task_multiple_sessions():
    result = project([
        event("2026-09-11T09:00:00+00:00", "task.started", session_id="s1", task_key="A"),
        event("2026-09-11T09:10:00+00:00", "task.started", session_id="s1", task_key="B"),
        event("2026-09-11T09:20:00+00:00", "task.progress", session_id="s2", task_key="A"),
    ], now="2026-09-11T09:21:00+00:00")
    s1 = get_agent_session(result, "s1")
    s2 = get_agent_session(result, "s2")
    assert s1["task_count"] == 2
    assert {task["task_key"] for task in s1["tasks"]} == {"A", "B"}
    assert s2["tasks"][0]["task_key"] == "A"


def test_test_result_preserves_unknown_counts_without_invention():
    result = project([
        event("2026-09-11T09:00:00+00:00", "test.result", session_id="s1", task_id="A", data={"summary": "tests passed"})
    ], now="2026-09-11T09:01:00+00:00")
    test = result["sessions"][0]["tasks"][0]["tests"][0]
    assert test["status"] == "passed"
    assert test["passed"] is None
    assert test["failed"] is None
    assert test["total"] is None


def test_blocker_is_cleared_by_later_progress_and_does_not_lock_session_forever():
    result = project([
        event("2026-09-11T09:00:00+00:00", "blocker.reported", session_id="s1", task_id="A", data={"summary": "接口不可用"}),
        event("2026-09-11T09:10:00+00:00", "task.progress", session_id="s1", task_id="A", data={"summary": "接口恢复，继续"}),
    ], now="2026-09-11T09:11:00+00:00")
    session = result["sessions"][0]
    assert session["status"] == "active"
    assert session["open_blocker_count"] == 0
    assert session["tasks"][0]["blockers"][0]["resolution"] == "progress_resumed"


def test_blocked_session_and_finished_without_test_flags_are_conservative():
    blocked = project([
        event("2026-09-11T09:00:00+00:00", "blocker.reported", session_id="s1", task_id="A")
    ], now="2026-09-11T09:01:00+00:00")
    assert blocked["sessions"][0]["status"] == "blocked"
    assert "blocked_session" in blocked["sessions"][0]["flags"]

    finished = project([
        event("2026-09-11T09:00:00+00:00", "task.finished", session_id="s2", task_id="A")
    ], now="2026-09-11T09:01:00+00:00")
    assert "agent_finished_without_test" in finished["sessions"][0]["flags"]


def test_session_ended_controls_session_finished_not_task_finished():
    result = project([
        event("2026-09-11T09:00:00+00:00", "task.finished", session_id="s1", task_id="A"),
        event("2026-09-11T09:10:00+00:00", "session.ended", session_id="s1"),
    ], now="2026-09-11T09:11:00+00:00")
    session = result["sessions"][0]
    assert session["status"] == "finished"
    assert session["ended_at"] == "2026-09-11T09:10:00+00:00"
    assert session["duration_seconds"] == 600


def test_client_event_id_is_idempotent_in_projection():
    duplicate = event("2026-09-11T09:00:00+00:00", "task.progress", session_id="s1", task_id="A", client="evt-1")
    result = project([duplicate, dict(duplicate)], now="2026-09-11T09:01:00+00:00")
    assert result["sessions"][0]["event_count"] == 1
    assert result["flags"] == [{"flag": "duplicate_agent_event", "count": 1}]


def test_unlinked_event_is_preserved_without_forced_task_binding():
    result = project([
        event("2026-09-11T09:00:00+00:00", "task.progress", session_id="s1", data={"summary": "继续处理"})
    ], now="2026-09-11T09:01:00+00:00")
    session = result["sessions"][0]
    assert session["task_count"] == 0
    assert session["unlinked_task_event_count"] == 1
    assert "unlinked_task_event" in session["flags"]


def test_people_compatibility_keeps_raw_user_and_optional_person_id():
    result = project([
        event("2026-09-11T09:00:00+00:00", "task.started", session_id="s1", user="raw-user", task_id="A", person="person-9")
    ], now="2026-09-11T09:01:00+00:00")
    session = result["sessions"][0]
    assert session["user_id"] == "raw-user"
    assert session["person_id"] == "person-9"


def test_agent_evidence_is_stable_for_evidence_fusion():
    result = project([
        event("2026-09-11T09:00:00+00:00", "task.started", session_id="s1", task_key="LV-102"),
        event("2026-09-11T09:05:00+00:00", "test.result", session_id="s1", task_key="LV-102", data={"passed": 2, "failed": 0}),
        event("2026-09-11T09:10:00+00:00", "task.finished", session_id="s1", task_key="LV-102"),
    ], now="2026-09-11T09:11:00+00:00")
    relations = [item["relation"] for item in result["evidence"]]
    assert relations == ["agent_started", "agent_test_pass", "agent_finished"]
    assert all(item["source_type"] == "agent" and item["confidence"] == "high" for item in result["evidence"])


def test_concurrent_different_agents_same_explicit_task_get_flag_but_title_only_does_not():
    result = project([
        event("2026-09-11T09:00:00+00:00", "task.started", session_id="c1", agent="Codex", task_key="LV-102"),
        event("2026-09-11T09:20:00+00:00", "task.progress", session_id="c1", agent="Codex", task_key="LV-102"),
        event("2026-09-11T09:10:00+00:00", "task.started", session_id="t1", agent="TRAE", task_key="LV-102"),
        event("2026-09-11T09:30:00+00:00", "task.progress", session_id="t1", agent="TRAE", task_key="LV-102"),
    ], now="2026-09-11T09:31:00+00:00")
    assert any(flag["flag"] == "concurrent_agents_same_task" for flag in result["flags"])

    title_only = project([
        event("2026-09-11T09:00:00+00:00", "task.started", session_id="c2", agent="Codex", title="相似标题"),
        event("2026-09-11T09:01:00+00:00", "task.started", session_id="t2", agent="TRAE", title="相似标题"),
    ], now="2026-09-11T09:02:00+00:00")
    assert not any(flag["flag"] == "concurrent_agents_same_task" for flag in title_only["flags"])


def test_changed_files_and_git_are_only_taken_from_explicit_event_data():
    result = project([
        event("2026-09-11T09:00:00+00:00", "file.changed", session_id="s1", task_id="A", data={"path": "apps/a.py"}),
        event("2026-09-11T09:01:00+00:00", "git.commit", session_id="s1", task_id="A", data={"commit_sha": "abc", "branch": "feat/x"}),
    ], now="2026-09-11T09:02:00+00:00")
    session = result["sessions"][0]
    assert session["changed_files"] == ["apps/a.py"]
    assert session["commits"] == ["abc"]
    assert session["branches"] == ["feat/x"]


def test_idle_is_elapsed_session_time_not_work_hours():
    result = project([
        event("2026-09-11T08:00:00+00:00", "task.started", session_id="s1", task_id="A")
    ], now="2026-09-11T12:00:00+00:00")
    session = result["sessions"][0]
    assert session["status"] == "idle"
    assert session["duration_seconds"] == 0
    assert "work_hours" not in session
    assert "efficiency" not in session
