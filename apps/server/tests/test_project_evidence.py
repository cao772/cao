from project_evidence import fuse_project_evidence


def _payload(title: str, *, dirty: bool, code_summary: str | None = None, test_text: str | None = None):
    memory = {
        "requirements": [{"text": title, "path": "需求.xlsx", "role": "requirement"}],
        "tasks": [],
        "tests": ([{"text": test_text, "path": "测试.xlsx", "role": "test_result"}] if test_text else []),
        "blockers": [],
    }
    items = []
    if code_summary:
        items.append(
            {
                "path": "app/demo.py",
                "status": "analyzed",
                "kind": "modified",
                "additions": 20,
                "deletions": 3,
                "analysis": {
                    "summary": code_summary,
                    "change_area": "backend",
                    "business_capabilities": [code_summary],
                    "risks": [],
                },
            }
        )
    return {
        "git": {
            "is_git_repo": True,
            "dirty": dirty,
            "ahead": 0,
            "behind": 0,
            "branch": "cao",
            "head": "abc",
            "upstream": "origin/cao",
        },
        "analysis": {"current_project_memory": memory},
        "git_change_analysis": {"enabled": True, "items": items},
    }


def _snapshot(user: str, payload: dict, snapshot_id: int):
    return {
        "id": snapshot_id,
        "project_id": "low-voltage",
        "project_name": "低电压项目",
        "user_id": user,
        "device_id": f"{user}-device",
        "workspace_name": "algorithm版本管理",
        "observed_at": f"2026-09-08T10:0{snapshot_id}:00Z",
        "received_at": f"2026-09-08T10:0{snapshot_id}:10Z",
        "payload": payload,
    }


def _event(user: str, event_type: str, title: str):
    return {
        "event_type": event_type,
        "observed_at": "2026-09-08T10:10:00Z",
        "project_id": "low-voltage",
        "user_id": user,
        "agent": {"vendor": "OpenAI", "name": "Codex" if user == "u1" else "TRAE"},
        "session_id": f"{user}-session",
        "task_id": "LV-102",
        "task_title": title,
        "data": {"summary": title},
    }


def test_merges_same_task_across_two_developers():
    title = "资料上传更新左侧树状页面"
    snapshots = [
        _snapshot("u1", _payload(title, dirty=False, code_summary="实现资料上传更新左侧树状页面后端逻辑"), 1),
        _snapshot("u2", _payload(title, dirty=False, code_summary="实现资料上传更新左侧树状页面前端", test_text="资料上传更新左侧树状页面测试通过"), 2),
    ]
    result = fuse_project_evidence(
        snapshots,
        [_event("u1", "task.finished", title), _event("u2", "task.finished", title)],
    )
    assert result["summary"]["workspace_count"] == 2
    assert result["summary"]["contributor_count"] == 2
    assert len(result["work_items"]) == 1
    item = result["work_items"][0]
    assert item["task_id"] == "LV-102"
    assert item["contributors"] == ["u1", "u2"]
    assert item["workspace_count"] == 2
    assert item["status"] == "local_verified_pending_remote"


def test_one_dirty_workspace_prevents_local_verified_status():
    title = "修复工程量提取问题"
    snapshots = [
        _snapshot("u1", _payload(title, dirty=True, code_summary="修复工程量提取逻辑"), 1),
        _snapshot("u2", _payload(title, dirty=False, test_text="工程量提取回归测试通过"), 2),
    ]
    result = fuse_project_evidence(snapshots, [_event("u1", "task.finished", title)])
    item = result["work_items"][0]
    assert item["status"] == "locally_complete_uncommitted"
    assert result["formal_completion_supported"] is False


def test_failed_test_in_any_workspace_has_priority():
    title = "模型切换接口"
    snapshots = [
        _snapshot("u1", _payload(title, dirty=False, code_summary="新增模型切换接口"), 1),
        _snapshot("u2", _payload(title, dirty=False, test_text="模型切换接口测试失败"), 2),
    ]
    result = fuse_project_evidence(snapshots, [_event("u1", "task.finished", title)])
    assert result["work_items"][0]["status"] == "test_failing"
    assert result["project_state"] == "attention"


def test_agent_event_is_not_duplicated_into_other_users_workspace():
    title = "新增模型切换接口"
    snapshots = [
        _snapshot("u1", _payload(title, dirty=False), 1),
        _snapshot("u2", _payload(title, dirty=False), 2),
    ]
    result = fuse_project_evidence(snapshots, [_event("u1", "task.finished", title)])
    item = result["work_items"][0]
    finished = [entry for entry in item["evidence"] if entry.get("kind") == "finished"]
    assert len(finished) == 1
    assert finished[0]["user_id"] == "u1"
