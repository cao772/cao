from evidence_fusion import fuse_evidence, similarity


def _payload(*, dirty=True, ahead=0, requirements=None, tasks=None, tests=None, blockers=None, git_changes=None):
    return {
        "git": {
            "is_git_repo": True,
            "dirty": dirty,
            "ahead": ahead,
            "behind": 0,
            "upstream": "origin/cao",
        },
        "analysis": {
            "current_project_memory": {
                "requirements": requirements or [],
                "tasks": tasks or [],
                "tests": tests or [],
                "blockers": blockers or [],
            }
        },
        "git_change_analysis": {
            "enabled": True,
            "items": git_changes or [],
        },
    }


def _code(summary, path="app/demo.py"):
    return {
        "path": path,
        "status": "analyzed",
        "kind": "modified",
        "additions": 10,
        "deletions": 2,
        "analysis": {
            "summary": summary,
            "change_area": "backend",
            "business_capabilities": [summary],
            "risks": [],
        },
    }


def _agent(event_type, title, task_id="TASK-1", result=None):
    data = {}
    if result is not None:
        data["result"] = result
    return {
        "event_type": event_type,
        "observed_at": "2026-09-08T10:00:00Z",
        "project_id": "demo",
        "user_id": "u1",
        "agent": {"name": "Codex", "vendor": "OpenAI"},
        "session_id": "s1",
        "task_id": task_id,
        "task_title": title,
        "data": data,
    }


def test_similarity_handles_chinese_task_and_change_text():
    score = similarity("资料上传更新改为左侧树状选择", "实现资料上传更新左侧树状材料选择页面")
    assert score >= 0.28


def test_agent_finished_code_and_failed_test_is_not_complete():
    title = "修复工程量提取问题"
    payload = _payload(
        requirements=[{"text": title, "path": "需求.xlsx", "role": "requirement"}],
        tests=[{"text": "工程量提取回归测试：2通过1失败", "path": "测试.xlsx", "role": "test_result"}],
        git_changes=[_code("修复工程量提取逻辑")],
    )
    result = fuse_evidence(payload, [_agent("task.finished", title)])
    item = result["work_items"][0]
    assert item["status"] == "test_failing"
    assert result["formal_completion_supported"] is False


def test_agent_finished_code_passed_test_dirty_is_locally_complete_uncommitted():
    title = "资料上传更新左侧树状页面"
    payload = _payload(
        requirements=[{"text": title, "path": "需求.docx", "role": "requirement"}],
        tests=[{"text": "资料上传更新左侧树状页面测试通过", "path": "测试.xlsx", "role": "test_result"}],
        git_changes=[_code("实现资料上传更新左侧树状页面", "frontend/UploadUpdate.vue")],
        dirty=True,
    )
    result = fuse_evidence(payload, [_agent("task.finished", title)])
    assert result["work_items"][0]["status"] == "locally_complete_uncommitted"


def test_agent_claim_without_code_stays_claim_only():
    title = "新增模型切换接口"
    payload = _payload(tasks=[{"text": title, "path": "任务.md", "role": "task"}], dirty=False)
    result = fuse_evidence(payload, [_agent("task.finished", title)])
    assert result["work_items"][0]["status"] == "agent_claim_only"


def test_unlinked_code_changes_are_preserved_not_forced_to_task():
    payload = _payload(
        requirements=[{"text": "资料上传更新页面", "path": "需求.docx", "role": "requirement"}],
        git_changes=[_code("调整数据库迁移脚本", "migrations/001.sql")],
    )
    result = fuse_evidence(payload, [])
    assert result["summary"]["unlinked_code_change_count"] == 1
    assert result["work_items"][0]["status"] == "planned"
