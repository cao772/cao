from project_memory import build_current_project_memory, infer_temporal_hints, series_key


def _item(path: str, role: str, fact_text: str, fact_type: str = "progress"):
    return {
        "path": path,
        "role": role,
        "status": "analyzed",
        "analysis": {
            "summary": fact_text,
            "facts": [{"type": fact_type, "text": fact_text}],
        },
    }


def test_weekly_reports_keep_latest_and_history():
    analysis = {
        "enabled": True,
        "items": [
            _item("基于多模态大模型及智能体的电力设备缺陷处置_项目周报（第4期）0814.docx", "report", "第4期"),
            _item("基于多模态大模型及智能体的电力设备缺陷处置_项目周报（第5期）0821.docx", "report", "第5期"),
            _item("基于多模态大模型及智能体的电力设备缺陷处置_项目周报（第6期）0828.docx", "report", "第6期"),
            _item("基于多模态大模型及智能体的电力设备缺陷处置_项目周报（第7期）0904.docx", "report", "第7期"),
        ],
    }

    memory = build_current_project_memory(analysis)
    assert memory["current_source_count"] == 1
    assert memory["historical_source_count"] == 3
    assert memory["latest_sources"][0]["path"].endswith("第7期）0904.docx")
    assert memory["freshness_reference_date"].endswith("09-04")


def test_feature_list_versions_group_together():
    assert series_key("附件4：AI算法-需求功能清单V3_6.xlsx") == series_key("附件4：AI算法-需求功能清单V4_3.xlsx")


def test_absolute_date_hint_wins_over_month_day_hint():
    absolute = infer_temporal_hints("附件2-项目进度周报20260903.docx")
    short = infer_temporal_hints("生技域项目进度0904.xlsx")
    assert absolute["date_value"] == 20260903
    assert absolute["date_precision"] == "day"
    assert short["date_value"] == 904
    assert short["date_precision"] == "month_day"


def test_low_voltage_real_world_date_patterns():
    assert infer_temporal_hints("6_4 上线版本测试表.xlsx")["date_value"] == 604
    assert infer_temporal_hints("6.18 工作任务对应测试表.xlsx")["date_value"] == 618
    assert infer_temporal_hints("6.22-6.26 任务测试.xlsx")["date_value"] == 626
    assert infer_temporal_hints("6.30-7.9 开发任务.xlsx")["date_value"] == 709
    assert infer_temporal_hints("629-7.9 任务测试.xlsx")["date_value"] == 709
    assert infer_temporal_hints("一般低电压台区通过项目明细表 2026_6_17.xlsx")["date_value"] == 20260617


def test_low_voltage_task_series_group_across_dates():
    assert series_key("6.22-6.26 任务测试.xlsx") == series_key("629-7.9 任务测试.xlsx")


def test_copy_marker_does_not_create_separate_series():
    current = "低电压项目 8.12问题反馈表.xlsx"
    copy = "副本低电压项目 8.12问题反馈表(5).xlsx"
    assert series_key(current) == series_key(copy)


def test_same_logical_document_groups_across_handoff_folders():
    assert series_key("management/生技域项目进度0904.xlsx") == series_key("handoff/latest/生技域项目进度0906.xlsx")


def test_old_progress_is_history_not_current_task_state():
    analysis = {
        "enabled": True,
        "items": [
            _item("documents/7.7工作任务.xlsx", "progress", "旧任务状态：进行中", "task"),
            _item("documents/低电压项目8.12问题反馈表.xlsx", "test_result", "估算书工程量匹配问题待核实", "blocker"),
        ],
    }
    memory = build_current_project_memory(analysis)
    assert memory["freshness_reference_date"].endswith("08-12")
    assert memory["tasks"] == []
    assert any("旧任务状态" in fact["text"] for fact in memory["historical_facts"])
    assert any("估算书工程量" in fact["text"] for fact in memory["blockers"])


def test_facts_carry_source_time_and_week_history():
    analysis = {
        "enabled": True,
        "items": [
            _item("management/项目周报0904.docx", "report", "完成第一轮验证"),
            _item("management/SYSTEM_AUDIT_20260906.md", "report", "后端252项通过", "test"),
        ],
    }
    memory = build_current_project_memory(analysis)
    assert all("source_date" in fact and "freshness" in fact for fact in memory["facts"])
    assert memory["weekly_facts"]
    assert memory["weekly_facts"][0]["week_key"].startswith("2026-W")


def test_missing_year_uses_snapshot_year_and_parent_date_is_recognized():
    memory = build_current_project_memory({"enabled": True, "items": [
        _item("documents/7.7工作任务.xlsx", "progress", "旧任务进行中", "task"),
        _item("documents/8.12问题反馈表.xlsx", "test_result", "待核实", "blocker"),
    ]}, reference_year=2026)
    assert memory["freshness_reference_date"] == "2026-08-12"
    assert memory["historical_facts"][0]["source_date"] == "2026-07-07"
    hints = infer_temporal_hints("outputs/20260908_feature_list/需求功能清单V6.xlsx")
    assert hints["date_text"] == "2026-09-08"
    assert infer_temporal_hints("outputs/20260908/周报20260904.docx")["date_text"] == "2026-09-04"
