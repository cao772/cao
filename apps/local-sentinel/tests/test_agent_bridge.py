from pathlib import Path

import agent_bridge


def _manifest():
    return {
        "project": {"id": "low-voltage", "name": "低电压项目", "owner": "u1", "team": "ai"},
        "repositories": [
            {
                "id": "low-voltage-algorithm",
                "role": "algorithm",
                "provider": "gitlab",
                "url": "http://git/algorithm.git",
                "local_path": "algorithm",
                "primary": True,
            },
            {
                "id": "low-voltage-frontend",
                "role": "frontend",
                "provider": "gitlab",
                "url": "http://git/frontend.git",
                "local_path": "frontend",
            },
        ],
        "security": {"mode": "local_analysis"},
    }


def test_list_managed_projects_keeps_multi_repo_identity(monkeypatch, tmp_path: Path):
    root = tmp_path / "algorithm版本管理"
    root.mkdir()
    monkeypatch.setattr(agent_bridge, "discover_projects", lambda: [(root, _manifest())])

    projects = agent_bridge.list_managed_projects()
    assert len(projects) == 1
    assert projects[0]["project_id"] == "low-voltage"
    assert [repo["role"] for repo in projects[0]["repositories"]] == ["algorithm", "frontend"]


def test_build_agent_event_is_structured_and_not_formal_completion(monkeypatch, tmp_path: Path):
    root = tmp_path / "low-voltage"
    root.mkdir()
    monkeypatch.setattr(agent_bridge, "discover_projects", lambda: [(root, _manifest())])
    monkeypatch.setattr(agent_bridge, "USER_ID", "caoyh")
    monkeypatch.setattr(agent_bridge, "DEVICE_ID", "mac")
    monkeypatch.setattr(agent_bridge, "AGENT_VENDOR", "OpenAI")
    monkeypatch.setattr(agent_bridge, "AGENT_NAME", "Codex")

    event = agent_bridge.build_agent_event(
        event_type="task.finished",
        project_id="low-voltage",
        task_id="LV-102",
        task_title="修复工程量提取问题",
        data={"summary": "本地代码与测试工作已结束"},
    )

    assert event["event_type"] == "task.finished"
    assert event["project_id"] == "low-voltage"
    assert event["user_id"] == "caoyh"
    assert event["agent"]["name"] == "Codex"
    assert event["data"]["workspace_name"] == "low-voltage"
    assert "completed" not in event["data"]


def test_compact_context_drops_raw_evidence():
    raw = {
        "evidence_fusion": {
            "project_state": "active",
            "formal_completion_supported": True,
            "summary": {"status_counts": {"review_in_progress": 1}},
            "work_items": [
                {
                    "task_id": "LV-102",
                    "title": "资料上传更新左侧树状页面",
                    "status": "review_in_progress",
                    "status_label": "PR/MR审核中",
                    "status_reasons": ["已创建MR"],
                    "contributors": ["u1", "u2"],
                    "evidence": [{"source": "git_local", "text": "raw detail"}],
                }
            ],
        },
        "project_rollup": {"contributors": [{"user_id": "u1"}], "agents": ["Codex"]},
        "current_project_memory": {"blockers": ["接口待联调"], "next_steps": ["完成联调"]},
    }

    compact = agent_bridge._compact_central_context(raw)
    assert compact["work_items"][0]["task_id"] == "LV-102"
    assert "evidence" not in compact["work_items"][0]
    assert compact["project_memory"]["blockers"] == ["接口待联调"]
