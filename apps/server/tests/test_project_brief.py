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


def test_inferred_stage_exposes_dated_source_without_claiming_test_passed():
    recorded = snapshot({
        "tests": [
            {"text": "问题：总费用取错", "path": "documents/8月问题反馈表.xlsx", "source_date": "2026-08-12"},
            {"text": "问题：总费用取错", "path": "documents/8月问题反馈表.xlsx", "source_date": "2026-08-12"},
        ],
        "progress": [], "tasks": [], "requirements": [], "blockers": [], "decisions": [],
    })
    recorded["observed_at"] = "2026-09-28T03:00:00+00:00"
    brief = build_project_brief([recorded], {"work_items": []})

    assert brief["current_stage"] == "测试与验证"
    basis = brief["current_stage_basis"]
    assert basis["method"] == "heuristic"
    assert len(basis["evidence"]) == 1
    assert basis["evidence"][0]["path"] == "documents/8月问题反馈表.xlsx"
    assert basis["evidence"][0]["source_date"] == "2026-08-12"
    assert basis["evidence"][0]["observed_at"] == recorded["observed_at"]


def test_next_step_and_decision_keep_original_material_date():
    recorded = snapshot({
        "tests": [], "progress": [], "requirements": [], "blockers": [],
        "tasks": [{"text": "计划完成回归", "path": "reports/old-weekly.md", "source_date": "2026-08-12"}],
        "decisions": [{"text": "决定先验证接口", "path": "minutes/meeting.md", "source_date": "2026-09-01"}],
    })
    brief = build_project_brief([recorded], {"work_items": []})
    assert brief["next_step_evidence"][0]["path"] == "reports/old-weekly.md"
    assert brief["next_step_evidence"][0]["source_date"] == "2026-08-12"
    assert brief["decision_evidence"][0]["path"] == "minutes/meeting.md"


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


def test_issue_records_reject_headers_and_success_negation_but_keep_real_failures():
    record = snapshot({
        "blockers": [
            {"text": "存在问题"}, {"text": "问题清单："},
            {"text": "验证批次无失败、无异常"},
            {"text": "回归 272 passed, 0 failed, 0 errors"},
            {"text": "正式接口仍待确认", "path": "minutes.md", "source_date": "2026-10-01"},
        ],
        "tests": [{"text": "272 passed，但上线失败"},
                  {"text": "0 passed, 3 failed"},
                  {"text": "272 passed，异常处理功能覆盖通过"}],
    })
    brief = build_project_brief([record], {"work_items": []})
    assert brief["issues"] == ["正式接口仍待确认", "272 passed，但上线失败", "0 passed, 3 failed"]
    assert brief["issue_evidence"][0]["path"] == "minutes.md"
    assert brief["issue_evidence"][0]["source_date"] == "2026-10-01"
    assert brief["issue_evidence"][1]["source_date"] is None


def test_next_steps_do_not_promote_template_headers_or_ui_behavior_to_todos():
    template = "需求编号 业务架构 （依据 BA-01填写） 应用架构 功能清单"
    behavior = "输入：选择中断批次。操作与处理：确认继续执行未完成验证。"
    brief = build_project_brief([snapshot({"tasks":[{"text":"下一步工作计划"}, {"text":behavior}, {"text":"下一步完成接口回归"}]})],
        {"work_items":[{"title":template,"task_id":"BA-02","status":"planned"}]})
    assert brief["next_steps"] == ["下一步完成接口回归"]
    assert brief["summary"]["planned_task_count"] == 0


def test_this_week_uses_calendar_boundary_and_rejects_future_events():
    now = datetime(2026,10,6,6,0,tzinfo=timezone.utc)
    events = [{"event_type":"git.commit", "commit_sha":sha,"observed_at":stamp}
              for sha,stamp in [("last-week","2026-10-04T23:59:59Z"),
                                ("boundary","2026-10-05T00:00:00Z"),
                                ("today","2026-10-06T05:00:00Z"),
                                ("future","2026-10-06T07:00:00Z")]]
    brief = build_project_brief([], {"work_items":[]}, events, now=now)
    assert brief["summary"]["weekly_commit_count"] == 2
    assert brief["summary"]["today_activity_count"] == 1
    assert brief["statistics_period"]["week_start"] == "2026-10-05"
    assert brief["statistics_period"]["timezone"] == "UTC"


def test_recorded_stage_preserves_context_and_does_not_overwrite_inference():
    def context(stage, stamp, valid=True):
        return {"observed_at":"2026-10-06T06:00:00Z", "payload":{"project_intelligence":{"context":{
            "valid":valid,"modified_at":stamp,"path":".project-intelligence/project_context.yaml",
            "data":{"project":{"current_stage":stage}}}}}}
    brief = build_project_brief([context("旧阶段","2026-09-01T00:00:00Z"),
                                 context("业务阶段待核实","2026-10-01T00:00:00Z"),
                                 context("错误配置","2026-10-06T00:00:00Z",False)], {"work_items":[]})
    assert brief["recorded_stage"]["stage"] == "业务阶段待核实"
    assert brief["current_stage"] == "尚未形成明确阶段"
    assert build_project_brief([], {"work_items":[]})["recorded_stage"] is None


def test_recorded_stage_reads_central_v1_files_envelope():
    record = {"payload":{"files":{"project_intelligence":{"context":{
        "valid":True,"data":{"project":{"current_stage":"业务阶段待核实"}}}}}}}
    assert build_project_brief([record], {"work_items":[]})["recorded_stage"]["stage"] == "业务阶段待核实"
