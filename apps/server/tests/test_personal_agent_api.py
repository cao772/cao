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

    result = personal.summary()
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
