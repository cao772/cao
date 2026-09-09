from datetime import datetime, timezone

from project_brief import build_project_brief


def snapshot(memory, dirty=False):
    return {
        "payload": {
            "git": {"dirty": dirty},
            "analysis": {"current_project_memory": memory},
        }
    }


def test_business_brief_uses_real_project_facts_and_remote_activity():
    snapshots = [
        snapshot(
            {
                "progress": [
                    {"text": "本周完成1431条样本验证"},
                    {"text": "图像确认率81.4%，定级覆盖率81.2%"},
                ],
                "tasks": [{"text": "下一步完成3~5个薄弱类别优化"}],
                "tests": [{"text": "新一轮回归测试通过率86.7%"}],
                "requirements": [{"text": "正式生产输入字段及接口待确认"}],
                "blockers": [{"text": "部分细粒度缺陷仍受ROI质量影响"}],
                "decisions": [],
                "weekly_facts": [],
            },
            dirty=True,
        )
    ]
    fusion = {
        "work_items": [
            {"title": "薄弱类别优化", "status": "in_progress_uncommitted"},
            {"title": "生产接口确认", "status": "planned", "task_id": "DEF-102"},
        ]
    }
    remote = [
        {
            "event_type": "git.commit",
            "observed_at": "2026-09-08T10:00:00+00:00",
            "commit_sha": "abc",
        },
        {
            "event_type": "git.push",
            "observed_at": "2026-09-08T10:05:00+00:00",
            "commit_sha": "abc",
        },
    ]

    brief = build_project_brief(
        snapshots,
        fusion,
        remote,
        [],
        now=datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc),
    )

    assert brief["current_stage"] == "问题处理与联调"
    assert "薄弱类别优化" in brief["in_progress"]
    assert "生产接口确认" in brief["next_steps"]
    assert any("81.4%" in item for item in brief["latest_metrics"])
    assert brief["summary"]["weekly_commit_count"] == 1
    assert brief["summary"]["local_uncommitted_workspace_count"] == 1


def test_failed_line_is_not_reported_as_completed():
    snapshots = [
        snapshot(
            {
                "progress": [
                    {"text": "工程量提取修复失败，仍需处理"},
                    {"text": "模型切换后端已完成"},
                ],
                "tasks": [],
                "tests": [],
                "requirements": [],
                "blockers": [],
                "decisions": [],
            }
        )
    ]
    brief = build_project_brief(snapshots, {"work_items": []}, [], [])
    assert "模型切换后端已完成" in brief["completed"]
    assert all("失败" not in item for item in brief["completed"])


def test_formal_completed_task_enters_completed_list():
    brief = build_project_brief(
        [snapshot({"progress": [], "tasks": [], "tests": [], "requirements": [], "blockers": [], "decisions": []})],
        {"work_items": [{"title": "资料更新树状页面", "status": "completed"}]},
        [],
        [],
    )
    assert brief["completed"] == ["资料更新树状页面"]
    assert brief["summary"]["completed_task_count"] == 1


def test_negation_test_subjects_and_plans_do_not_reverse_status():
    brief = build_project_brief([snapshot({
        "progress": [{"text": "状态：进行中；缺少技术方案时仿真报告判定也通过"},
                     {"text": "上线验收尚未完成"}],
        "tasks": [{"text": "T01 未开始"}],
        "tests": [{"text": "前端测试：7 passed；覆盖分析失败反馈"},
                  {"text": "定额错误抽取链路，当前状态待测试"},
                  {"text": "完成1431条验证，无失败无超时，准确率86.7%"}],
    })], {"work_items": []})
    assert brief["completed"] == []
    assert brief["issues"] == []
    assert "T01 未开始" not in brief["in_progress"]
    assert "T01 未开始" in brief["next_steps"]
    assert any("86.7%" in x for x in brief["latest_metrics"])


def test_unconfirmed_document_candidates_do_not_flood_next_steps():
    fusion = {
        "work_items": [
            {"title": "功能清单共253条", "status": "planned", "origin": "document", "task_id": None},
            {"title": "真实待办任务", "status": "planned", "origin": "agent", "task_id": "T-1"},
        ]
    }
    brief = build_project_brief([snapshot({"progress": [], "tasks": [], "tests": [], "requirements": [], "blockers": [], "decisions": []})], fusion)
    assert "功能清单共253条" not in brief["next_steps"]
    assert "真实待办任务" in brief["next_steps"]
    assert brief["summary"]["planned_task_count"] == 1
    assert brief["summary"]["candidate_task_count"] == 2


def test_newer_metric_family_wins_and_weekly_progress_is_grouped():
    memory = {
        "progress": [],
        "tasks": [],
        "requirements": [],
        "blockers": [],
        "decisions": [],
        "tests": [
            {"text": "后端227项通过、3项跳过", "source_date": "2026-09-04"},
            {"text": "后端252项通过、3项跳过", "source_date": "2026-09-06"},
        ],
        "weekly_facts": [
            {
                "week_key": "2026-W36",
                "start": "2026-08-31",
                "end": "2026-09-06",
                "facts": [
                    {"type": "progress", "text": "完成1431条样本验证", "source_date": "2026-09-04"},
                    {"type": "blocker", "text": "正式生产接口待确认", "source_date": "2026-09-04"},
                ],
            }
        ],
    }
    brief = build_project_brief(
        [snapshot(memory)],
        {"work_items": []},
        remote_events=[{"event_type": "git.commit", "observed_at": "2026-09-04T10:00:00Z", "commit_sha": "a"}],
        now=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )
    assert any("252项" in item for item in brief["latest_metrics"])
    assert all("227项" not in item for item in brief["latest_metrics"])
    assert brief["weekly_progress"][0]["week_key"] == "2026-W36"
    assert "完成1431条样本验证" in brief["weekly_progress"][0]["completed"]
