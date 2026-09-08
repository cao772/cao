from project_memory import build_current_project_memory, infer_temporal_hints, series_key


def _item(path: str, role: str, fact_text: str):
    return {
        "path": path,
        "role": role,
        "status": "analyzed",
        "analysis": {
            "summary": fact_text,
            "facts": [{"type": "progress", "text": fact_text}],
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


def test_feature_list_versions_group_together():
    assert series_key("附件4：AI算法-需求功能清单V3_6.xlsx") == series_key("附件4：AI算法-需求功能清单V4_3.xlsx")


def test_absolute_date_hint_wins_over_month_day_hint():
    absolute = infer_temporal_hints("附件2-项目进度周报20260903.docx")
    short = infer_temporal_hints("生技域项目进度0904.xlsx")
    assert absolute["date_value"] == 20260903
    assert absolute["date_precision"] == "day"
    assert short["date_value"] == 904
    assert short["date_precision"] == "month_day"
