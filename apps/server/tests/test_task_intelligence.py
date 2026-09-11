from task_identity import identity_match, normalized_title, stable_task_key
from task_intelligence import apply_task_intelligence, facts_from_memory, memory_candidates
from task_lifecycle import classify_candidate


def _item(title, *, status="planned", task_id=None, kind="task", origin_type="task", source="document", extra_evidence=None):
    evidence = [{"source": source, "kind": kind, "text": title, "task_id": task_id}]
    evidence.extend(extra_evidence or [])
    return {
        "title": title,
        "task_id": task_id,
        "status": status,
        "status_label": status,
        "origin": source,
        "origin_type": origin_type,
        "evidence": evidence,
    }


def _fusion(items, *, unlinked=None):
    return {"summary": {}, "work_items": items, "unlinked_evidence": unlinked or {}}


def test_01_classifies_planned_task():
    assert classify_candidate("待开发资料上传树状页面") == "task"


def test_02_completion_record_is_not_task():
    assert classify_candidate("已完成资料上传树状页面") == "completion_record"


def test_03_test_evidence():
    assert classify_candidate("树状页面测试3/3通过") == "test_evidence"


def test_04_issue():
    assert classify_candidate("当前页面出现重复嵌入") == "issue"


def test_05_implementation_note():
    assert classify_candidate("资料上传更新功能实现说明") == "implementation_note"


def test_06_same_task_id_merges():
    result = apply_task_intelligence(_fusion([
        _item("资料上传树状改造", task_id="LV-102"),
        _item("上传更新页左侧树", task_id="LV-102"),
    ]))
    assert len(result["work_items"]) == 1
    assert result["work_items"][0]["task_id"] == "LV-102"


def test_07_status_variants_merge_one_task():
    result = apply_task_intelligence(_fusion([
        _item("待开发资料上传树状页面"),
        _item("正在开发资料上传树状页面", status="in_progress_agent"),
        _item("已完成资料上传树状页面"),
    ]))
    assert len(result["work_items"]) == 1
    assert result["work_items"][0]["completion_claimed"] is True


def test_08_git_commit_attaches_without_new_task():
    result = apply_task_intelligence(_fusion(
        [_item("资料上传更新树状改造")],
        unlinked={"code_changes": [{
            "source": "git_local",
            "kind": "code_change",
            "text": "修复资料上传更新树状交互",
            "path": "Upload.vue",
        }]},
    ))
    assert len(result["work_items"]) == 1
    assert any(e["relation"] == "implementation" for e in result["work_items"][0]["evidence"])
    assert result["summary"]["task_intelligence"]["reattached_unlinked_evidence_count"] == 1


def test_09_similar_but_distinct_engineering_tasks_do_not_merge():
    matched, score, _ = identity_match({"title": "工程量提取"}, {"title": "工程量铁塔修复"})
    assert matched is False
    result = apply_task_intelligence(_fusion([
        _item("工程量提取"),
        _item("工程量铁塔修复"),
    ]))
    assert len(result["work_items"]) == 2


def test_10_tree_aliases_merge_conservatively():
    matched, _, _ = identity_match(
        {"title": "资料上传更新树状改造"},
        {"title": "上传更新页左侧树"},
    )
    assert matched is True


def test_11_completion_overrides_planned_lifecycle_but_not_formal_completion():
    result = apply_task_intelligence(_fusion([
        _item("待开发资料上传树状页面"),
        _item("已完成资料上传树状页面"),
    ]))
    item = result["work_items"][0]
    assert item["task_status"] == "implementation_done"
    assert item["formal_completion"] is False


def test_12_agent_finished_is_not_formal_completed():
    result = apply_task_intelligence(_fusion([
        _item(
            "资料上传树状页面",
            status="agent_claim_only",
            source="agent",
            kind="finished",
            origin_type="task",
        )
    ]))
    item = result["work_items"][0]
    assert item["task_status"] == "implementation_done"
    assert item["formal_completion"] is False
    assert item["status"] != "completed"


def test_13_failed_test_blocks():
    result = apply_task_intelligence(_fusion([
        _item(
            "资料上传树状页面",
            status="test_failing",
            extra_evidence=[{"source": "document", "kind": "test", "text": "树状页面测试失败"}],
        )
    ]))
    assert result["work_items"][0]["task_status"] == "blocked"


def test_14_cancelled_does_not_stay_planned():
    result = apply_task_intelligence(_fusion([
        _item("待开发资料上传树状页面"),
        _item("已取消资料上传树状页面"),
    ]))
    assert len(result["work_items"]) == 1
    assert result["work_items"][0]["task_status"] == "cancelled"


def test_15_completed_remote_status_wins_old_planned():
    result = apply_task_intelligence(_fusion([
        _item("待开发资料上传树状页面", status="planned"),
        _item("资料上传树状页面", status="completed"),
    ]))
    item = result["work_items"][0]
    assert item["status"] == "completed"
    assert item["task_status"] == "completed"
    assert item["formal_completion"] is True


def test_16_historical_fact_not_returned_as_memory_candidate():
    memory = {
        "current_facts": [
            {"type": "task", "text": "当前任务A", "freshness": "current"},
            {"type": "task", "text": "历史任务B", "freshness": "historical"},
        ]
    }
    candidates = memory_candidates(memory)
    assert [c["text"] for c in candidates] == ["当前任务A"]


def test_17_undated_fact_is_not_promoted_to_task():
    memory = {
        "current_facts": [
            {"type": "task", "text": "待开发未知日期事项", "freshness": "undated", "path": "说明.md"},
        ]
    }
    result = apply_task_intelligence(_fusion([]), memories=[memory])
    assert result["work_items"] == []


def test_18_current_facts_take_priority_over_legacy_buckets():
    memory = {
        "current_facts": [{"type": "task", "text": "当前任务A", "freshness": "current"}],
        "tasks": [{"text": "旧任务B"}],
    }
    facts = facts_from_memory(memory)
    assert [f["text"] for f in facts] == ["当前任务A"]


def test_19_legacy_memory_buckets_still_supported():
    memory = {
        "requirements": [{"text": "资料上传树状改造"}],
        "tasks": [{"text": "模型切换"}],
        "tests": [{"text": "模型切换测试通过"}],
    }
    facts = facts_from_memory(memory)
    assert {f["type"] for f in facts} == {"requirement", "task", "test"}


def test_20_output_preserves_work_items_and_adds_task_summary():
    result = apply_task_intelligence(_fusion([_item("资料上传树状改造")]))
    assert "work_items" in result
    assert "task_summary" in result
    assert result["task_summary"]["total"] == 1


def test_21_same_task_has_multiple_evidence_sources():
    result = apply_task_intelligence(_fusion([
        _item(
            "资料上传树状改造",
            extra_evidence=[
                {"source": "agent", "kind": "progress", "text": "正在开发资料上传树状改造"},
                {"source": "git_local", "kind": "code_change", "text": "实现资料上传树状改造"},
            ],
        )
    ]))
    item = result["work_items"][0]
    assert {"document", "agent", "git_local"} <= set(item["evidence_sources"])


def test_22_task_key_is_stable_across_status_wording():
    key1 = stable_task_key(title="待开发资料上传树状页面")
    key2 = stable_task_key(title="已完成资料上传树状页面")
    assert key1 == key2


def test_23_no_progress_percentage_is_generated():
    result = apply_task_intelligence(_fusion([_item("资料上传树状改造")]))
    assert result["diagnostics"]["task_intelligence"]["progress_percentage_generated"] is False
    assert "progress_percent" not in result["work_items"][0]


def test_24_completion_record_alone_does_not_create_planned_task():
    result = apply_task_intelligence(_fusion([
        _item("已完成资料上传树状页面"),
    ]))
    assert result["work_items"] == []
    assert result["unlinked_evidence"]["task_intelligence"]


def test_25_remote_commit_does_not_create_task_by_itself():
    result = apply_task_intelligence(_fusion(
        [],
        unlinked={"remote_events": [{
            "source": "remote_devops",
            "kind": "remote_commit",
            "text": "fix estimate quantity extraction",
            "commit_sha": "abc123",
        }]},
    ))
    assert result["work_items"] == []
    assert len(result["unlinked_evidence"]["remote_events"]) == 1


def test_26_issue_is_preserved_as_issue_not_forced_to_task():
    result = apply_task_intelligence(_fusion([
        _item("当前页面出现重复嵌入", origin_type="blocker", kind="blocker"),
    ]))
    assert len(result["work_items"]) == 1
    assert result["work_items"][0]["item_type"] == "issue"


def test_27_explicit_task_id_stabilizes_task_key():
    assert stable_task_key(task_id="lv-102", title="whatever") == "id:LV-102"


def test_28_evidence_gets_relation_and_source_id():
    result = apply_task_intelligence(_fusion([_item("资料上传树状改造")]))
    evidence = result["work_items"][0]["evidence"][0]
    assert evidence["relation"] == "requirement"
    assert evidence["source_id"]


def test_29_formal_completion_requires_existing_completed_status():
    result = apply_task_intelligence(_fusion([
        _item(
            "资料上传树状改造",
            status="local_verified_pending_remote",
            extra_evidence=[{"source": "remote_devops", "kind": "ci_passed", "text": "CI passed"}],
        )
    ]))
    assert result["work_items"][0]["formal_completion"] is False


def test_30_memory_current_task_can_seed_when_fusion_has_none():
    memory = {
        "current_facts": [{
            "type": "task",
            "text": "资料上传页面改为左侧树状选择材料",
            "freshness": "current",
            "path": "需求_20260911.xlsx",
            "source_date": "2026-09-11",
        }]
    }
    result = apply_task_intelligence(_fusion([]), memories=[memory])
    assert len(result["work_items"]) == 1
    assert result["work_items"][0]["status"] == "planned"
