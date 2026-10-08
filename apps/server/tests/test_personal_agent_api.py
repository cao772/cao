import personal_agent_api as personal


def test_open_loops_prioritize_blockers_and_unknown_execution(monkeypatch):
    monkeypatch.setattr(
        personal,
        "_projects",
        lambda: [
            {
                "project_id": "kb",
                "project_name": "法规知识库",
                "last_seen_at": "2026-10-07T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        personal.main,
        "project_brief",
        lambda project_id: {
            "issues": ["受限站点仍需授权"],
            "next_steps": ["扩大真实新站迁移样本"],
        },
    )
    monkeypatch.setattr(
        personal,
        "_execution_rows",
        lambda limit=100: [
            {
                "id": "run-1",
                "project_id": "kb",
                "task_id": "TASK-1",
                "task_title": "采集适配器优化",
                "status": "unknown",
                "formal_completion": False,
            }
        ],
    )

    loops = personal.collect_open_loops()
    assert [item["type"] for item in loops] == [
        "blocker",
        "execution_needs_attention",
        "next_step",
    ]
    assert loops[0]["needs_user"] is True
    assert loops[1]["needs_user"] is True
    assert loops[1]["execution_id"] == "run-1"


def test_summary_stays_quiet_for_normal_next_steps(monkeypatch):
    monkeypatch.setattr(
        personal,
        "_projects",
        lambda: [
            {
                "project_id": "muse",
                "project_name": "Muse",
                "last_seen_at": "2026-10-07T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        personal.main,
        "project_brief",
        lambda project_id: {"issues": [], "next_steps": ["继续端到端验收"]},
    )
    monkeypatch.setattr(personal, "_execution_rows", lambda limit=100: [])

    result = personal.summary(limit=8)
    assert result["attention_required"] is False
    assert result["needs_user_count"] == 0
    assert result["headline"] == "当前没有需要立即打断你的事项"
    assert result["items"][0]["type"] == "next_step"


def test_completion_judge_never_treats_agent_claim_as_formal_completion(monkeypatch):
    monkeypatch.setattr(
        personal.main,
        "project_evidence",
        lambda project_id: {
            "formal_completion_supported": True,
            "work_items": [
                {
                    "title": "实现项目提醒",
                    "status": "agent_claim_only",
                    "status_label": "仅有 Agent 完成声明",
                    "evidence": [{"kind": "finished"}],
                }
            ],
        },
    )

    result = personal.completion_judgement("muse")
    assert result["verdict"] == "not_complete"
    assert result["completed_work_item_count"] == 0
    assert result["unresolved_work_item_count"] == 1


def test_completion_judge_reports_only_tracked_scope_complete(monkeypatch):
    monkeypatch.setattr(
        personal.main,
        "project_evidence",
        lambda project_id: {
            "formal_completion_supported": True,
            "work_items": [
                {
                    "title": "P2",
                    "status": "completed",
                    "status_label": "正式完成",
                    "evidence_count": 5,
                }
            ],
        },
    )

    result = personal.completion_judgement("muse")
    assert result["verdict"] == "tracked_scope_complete"
    assert "不等于整个项目" in result["reason"]


def test_completion_judge_surfaces_failed_evidence(monkeypatch):
    monkeypatch.setattr(
        personal.main,
        "project_evidence",
        lambda project_id: {
            "formal_completion_supported": True,
            "work_items": [
                {
                    "title": "CI",
                    "status": "remote_ci_failed",
                    "status_label": "远端CI未通过",
                    "evidence_count": 2,
                }
            ],
        },
    )

    result = personal.completion_judgement("muse")
    assert result["verdict"] == "attention"
    assert result["attention_work_item_count"] == 1


def test_p3_attention_understands_live_p2_statuses(monkeypatch):
    monkeypatch.setattr(
        personal,
        "_projects",
        lambda: [{"project_id": "muse", "project_name": "Muse", "last_seen_at": "today"}],
    )
    monkeypatch.setattr(
        personal.main,
        "project_brief",
        lambda project_id: {"issues": [], "next_steps": []},
    )
    runs = [
        {"id": "run-wait", "project_id": "muse", "task_title": "待反馈任务", "status": "waiting"},
        {"id": "run-active", "project_id": "muse", "task_title": "后台工作", "status": "running"},
        {"id": "run-done", "project_id": "muse", "task_title": "已退出进程", "status": "finished"},
    ]
    monkeypatch.setattr(personal, "_execution_rows", lambda limit=100: runs)
    loops = personal.collect_open_loops()
    assert [(x["execution_id"], x["needs_user"]) for x in loops] == [
        ("run-wait", True),
        ("run-active", False),
    ]
    result = personal.summary(limit=8)
    assert result["attention_required"] is True
    assert result["needs_user_count"] == 1
    assert result["active_execution_count"] == 1
    assert result["headline"] == "有1项需要你处理"

    first = personal.attention_snapshot(limit=20)
    second = personal.attention_snapshot(limit=20)
    assert first == second
    assert first["count"] == 1
    assert first["items"][0]["execution_id"] == "run-wait"
    assert len(first["items"][0]["item_id"]) == 24
    assert first["snapshot_only"] is True
    assert first["auto_interrupt"] is False


def test_p3_distinct_executions_same_title_not_deduplicated(monkeypatch):
    monkeypatch.setattr(
        personal,
        "_projects",
        lambda: [{"project_id": "p", "project_name": "P", "last_seen_at": "today"}],
    )
    monkeypatch.setattr(
        personal.main,
        "project_brief",
        lambda project_id: {"issues": [], "next_steps": []},
    )
    monkeypatch.setattr(
        personal,
        "_execution_rows",
        lambda limit=100: [
            {"id": "a", "project_id": "p", "task_title": "重复任务", "status": "failed"},
            {"id": "b", "project_id": "p", "task_title": "重复任务", "status": "failed"},
        ],
    )
    result = personal.attention_snapshot(limit=20)
    assert result["count"] == 2
    assert len({row["item_id"] for row in result["items"]}) == 2
    assert all(row["severity"] == "critical" for row in result["items"])


def test_p3_attention_feed_stays_quiet_for_noncritical_progress(monkeypatch):
    monkeypatch.setattr(
        personal,
        "_projects",
        lambda: [{"project_id": "p", "project_name": "P", "last_seen_at": "today"}],
    )
    monkeypatch.setattr(
        personal.main,
        "project_brief",
        lambda project_id: {"issues": [], "next_steps": ["下周开发新功能"]},
    )
    monkeypatch.setattr(
        personal,
        "_execution_rows",
        lambda limit=100: [
            {"id": "a", "project_id": "p", "task_title": "正常运行", "status": "running"}
        ],
    )
    result = personal.attention_snapshot(limit=20)
    assert result["count"] == 0
    assert not result["items"]


def test_p3_attention_http_requires_scoped_muse_capability(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(personal.router)
    monkeypatch.setenv("CAO_MUSE_TOKEN", "private-muse-test-token")
    monkeypatch.setattr(
        personal,
        "_projects",
        lambda: [{"project_id": "p", "project_name": "P", "last_seen_at": "today"}],
    )
    monkeypatch.setattr(
        personal.main,
        "project_brief",
        lambda project_id: {"issues": ["有待处理问题"], "next_steps": []},
    )
    monkeypatch.setattr(personal, "_execution_rows", lambda limit=100: [])
    with TestClient(app) as client:
        assert client.get("/api/v1/personal-agent/attention").status_code == 401
        assert (
            client.get(
                "/api/v1/personal-agent/attention",
                headers={"X-Muse-Token": "incorrect"},
            ).status_code
            == 401
        )
        allowed = client.get(
            "/api/v1/personal-agent/attention",
            headers={"X-Muse-Token": "private-muse-test-token"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["count"] == 1


def test_p4_work_brief_prioritizes_human_actions_and_not_agent_done(monkeypatch):
    monkeypatch.setattr(
        personal,
        "_projects",
        lambda: [
            {"project_id": "kb", "project_name": "法规知识库", "last_seen_at": "today"},
            {"project_id": "muse", "project_name": "Muse", "last_seen_at": "today"},
        ],
    )
    monkeypatch.setattr(
        personal.main,
        "project_brief",
        lambda project_id: {
            "issues": ["剩余站点仍需授权"] if project_id == "kb" else [],
            "next_steps": ["继续核对站点", "验证新来源"] if project_id == "kb" else [],
        },
    )
    monkeypatch.setattr(
        personal,
        "_execution_rows",
        lambda limit=100: [
            {"id": "waiting-1", "project_id": "muse", "task_title": "需要补充确认", "status": "waiting"},
            {"id": "working-1", "project_id": "muse", "task_title": "正常运行", "status": "running"},
            {"id": "ended-1", "project_id": "muse", "task_title": "结束不等于完成", "status": "finished"},
        ],
    )
    back = personal.build_work_brief(mode="return", limit=4)
    assert back["needs_user_count"] == 2
    assert back["next_step_count"] == 2
    assert back["running_count"] == 1
    assert [item["classification"] for item in back["items"]] == [
        "needs_user", "needs_user", "suggested", "suggested"
    ]
    assert "结束不等于完成" not in str(back["items"])
    assert all(item["source"] in {"execution", "project_brief"} for item in back["items"])
    assert back["snapshot_only"] is True
    assert back["comparison_available"] is False
    assert back["changes_since_last_visit"] is None
    assert back["freshness_verified"] is False
    assert back["formal_completion_inferred"] is False
    assert back["auto_execute"] is False
    priority = personal.build_work_brief(mode="priority", limit=1)
    assert priority["items"][0]["type"] == "blocker"
    assert priority["items"][0]["project_id"] == "kb"
    assert priority["truncated"] is True


def test_p4_empty_brief_does_not_claim_all_done_or_yesterday_changes(monkeypatch):
    monkeypatch.setattr(personal, "_projects", lambda: [])
    monkeypatch.setattr(personal, "_execution_rows", lambda limit=100: [])
    result = personal.build_work_brief(mode="return")
    assert result["items"] == []
    assert "不能据此认定所有项目完成" in result["headline"]
    assert result["changes_since_last_visit"] is None
    for bad in ("yesterday", "restart"):
        import pytest

        with pytest.raises(ValueError):
            personal.build_work_brief(mode=bad)


def test_p4_brief_api_uses_muse_only_auth(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CAO_MUSE_TOKEN", "p4-test-private-token")
    monkeypatch.setattr(personal, "collect_open_loops", lambda: [])
    app = FastAPI()
    app.include_router(personal.router)
    with TestClient(app) as client:
        route = "/api/v1/personal-agent/work-brief"
        assert client.get(route).status_code == 401
        assert client.get(route, headers={"X-Muse-Token": "bad"}).status_code == 401
        headers = {"X-Muse-Token": "p4-test-private-token"}
        back = client.get(route, headers=headers, params={"mode": "return"})
        assert back.status_code == 200
        assert back.json()["snapshot_only"] is True
        today = client.get(route, headers=headers, params={"mode": "priority"})
        assert today.status_code == 200
        assert today.json()["mode"] == "priority"
        assert client.get(route, headers=headers, params={"mode": "other"}).status_code == 422
        assert client.get(route, headers=headers, params={"limit": 100}).status_code == 422
