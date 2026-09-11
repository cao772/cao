from project_memory import build_current_project_memory, infer_temporal_hints, series_key


def _item(path: str, role: str, text: str, fact_type: str = "progress", summary: str | None = None, **extra):
    item = {
        "path": path,
        "role": role,
        "status": "analyzed",
        "analysis": {
            "summary": summary if summary is not None else text,
            "facts": [{"type": fact_type, "text": text}],
        },
    }
    item.update(extra)
    return item


def test_same_series_latest_drives_current_and_old_versions_remain_history():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item("项目周报第4期0814.docx", "report", "第4期"),
                _item("项目周报第5期0821.docx", "report", "第5期"),
                _item("项目周报第6期0828.docx", "report", "第6期"),
                _item("项目周报第7期0904.docx", "report", "第7期"),
            ],
        },
        reference_year=2026,
    )
    assert memory["current_source_count"] == 1
    assert memory["historical_source_count"] == 3
    assert memory["latest_sources"][0]["path"].endswith("0904.docx")
    assert len(memory["historical_facts"]) == 3


def test_series_normalizes_copy_version_and_date_noise_without_merging_unrelated_files():
    assert series_key("需求说明.xlsx") == series_key("副本需求说明(1)最终版v2 0908.xlsx")
    assert series_key("问题反馈表.xlsx") == series_key("副本问题反馈表(5).xlsx")
    assert series_key("附件4：AI算法-需求功能清单V3_6.xlsx") == series_key("附件4：AI算法-需求功能清单V4_3.xlsx")
    assert "需求功能清单" in series_key("附件4：AI算法-需求功能清单V4_3.xlsx")
    assert series_key("需求说明.xlsx") != series_key("问题反馈表.xlsx")


def test_filename_date_patterns_and_issue_are_recognized_without_treating_obvious_ids_as_dates():
    cases = [
        ("2026-09-10周报.docx", 20260910),
        ("周报20260910.docx", 20260910),
        ("任务0908.xlsx", 908),
        ("任务9.8.xlsx", 908),
        ("任务9月8日.xlsx", 908),
        ("任务0821.xlsx", 821),
        ("任务6_11.xlsx", 611),
        ("任务6.18.xlsx", 618),
    ]
    for name, expected in cases:
        assert infer_temporal_hints(name)["date_value"] == expected
    assert infer_temporal_hints("项目周报第5期.docx")["issue"] == 5
    assert infer_temporal_hints("设备型号0908说明.xlsx")["date_value"] is None
    assert infer_temporal_hints("工单编号0821反馈.xlsx")["date_value"] is None


def test_issue_number_beats_file_mtime_when_no_higher_priority_date_exists():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item("项目周报第5期.docx", "report", "第5期", modified_at="2026-09-11T12:00:00"),
                _item("项目周报第6期.docx", "report", "第6期", modified_at="2026-09-01T12:00:00"),
            ],
        },
        reference_year=2026,
    )
    assert memory["version_families"][0]["current"].endswith("第6期.docx")


def test_body_date_has_priority_over_filename_and_file_mtime():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item(
                    "周报0908.docx",
                    "report",
                    "完成联调",
                    summary="报告日期：2026-09-10\n完成联调",
                    modified_at="2026-09-11T12:00:00",
                )
            ],
        },
        reference_year=2026,
    )
    source = memory["latest_sources"][0]
    assert source["document_date"] == "2026-09-10"
    assert source["date_source"] == "body"
    assert source["date_confidence"] == "high"


def test_unconfirmed_date_is_undated_instead_of_guessed():
    memory = build_current_project_memory(
        {"enabled": True, "items": [_item("正式需求规范.docx", "requirement", "必须支持历史追溯", "requirement")]},
        reference_year=2026,
    )
    assert memory["undated_facts"]
    assert not memory["current_facts"]


def test_old_but_latest_formal_requirement_is_not_expired_by_new_weekly_report():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item("正式需求规范2026-06-01.docx", "requirement", "必须保留历史资料", "requirement"),
                _item("项目周报2026-09-10.docx", "report", "本周完成联调", "progress"),
            ],
        },
        reference_year=2026,
    )
    assert any("必须保留历史资料" in fact["text"] for fact in memory["current_facts"])


def test_new_completed_fact_suppresses_older_recent_pending_fact():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item("工作任务2026-09-01.xlsx", "progress", "资料上传页待开发", "task"),
                _item("项目周报2026-09-10.docx", "report", "资料上传页已经完成", "progress"),
            ],
        },
        reference_year=2026,
    )
    assert all("待开发" not in fact["text"] for fact in memory["effective_facts"])
    assert any("已经完成" in fact["text"] for fact in memory["progress"])


def test_historical_problem_does_not_reenter_current_problem_bucket():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item("问题反馈2026-07-01.xlsx", "test_result", "旧问题仍待处理", "blocker"),
                _item("项目周报2026-09-10.docx", "report", "当前验证完成", "progress"),
            ],
        },
        reference_year=2026,
    )
    assert memory["blockers"] == []
    assert any("旧问题" in fact["text"] for fact in memory["historical_facts"])


def test_same_day_current_sources_with_obvious_contradiction_emit_conflict():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item("A测试结果2026-09-10.xlsx", "test_result", "测试已全部通过", "test"),
                _item("B验收记录2026-09-10.docx", "report", "仍有3项测试失败", "test"),
            ],
        },
        reference_year=2026,
    )
    assert len(memory["conflicts"]) == 1
    assert len(memory["conflicts"][0]["facts"]) == 2
    assert memory["conflicts"][0]["reason"] == "当前资料存在不一致"


def test_metric_with_denominator_keeps_it_and_missing_denominator_is_not_invented():
    memory = build_current_project_memory(
        {
            "enabled": True,
            "items": [
                _item("测试结果2026-09-10.xlsx", "test_result", "测试通过率 252/260（96.92%）", "test"),
                _item("前端测试2026-09-10.xlsx", "test_result", "前端 252项通过", "test"),
            ],
        },
        reference_year=2026,
    )
    assert any(item["numerator"] == 252 and item["denominator"] == 260 for item in memory["latest_metrics"])
    front = next(item for item in memory["latest_metrics"] if item["name"] == "前端测试通过")
    assert front["denominator"] is None
    assert "分母未识别" in front["display"]


def test_stage_evidence_keeps_source_path_date_and_text():
    memory = build_current_project_memory(
        {"enabled": True, "items": [_item("周报2026-09-10.docx", "report", "完成模型验证", "progress")]},
        reference_year=2026,
    )
    evidence = memory["stage_evidence"][0]
    assert evidence["path"].endswith(".docx")
    assert evidence["date"] == "2026-09-10"
    assert "模型验证" in evidence["text"]
