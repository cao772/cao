from project_rollup import build_project_rollup


def _snapshot(snapshot_id, user, device, workspace, branch, dirty, changed, *, blockers=None, tests=None):
    return {
        "id": snapshot_id,
        "project_id": "demo",
        "project_name": "Demo",
        "user_id": user,
        "device_id": device,
        "workspace_name": workspace,
        "observed_at": f"2026-09-08T0{snapshot_id}:00:00+00:00",
        "received_at": f"2026-09-08T0{snapshot_id}:00:05+00:00",
        "payload": {
            "git": {
                "is_git_repo": True,
                "repository_path": ".",
                "branch": branch,
                "head": f"sha-{snapshot_id}",
                "upstream": f"origin/{branch}",
                "dirty": dirty,
                "ahead": 0,
                "behind": 0,
                "changed_files": [
                    {"path": f"file-{index}.py", "kind": "modified"}
                    for index in range(changed)
                ],
                "change_counts": {"modified": changed},
                "diff_stat": {"added_lines": changed * 10, "deleted_lines": changed},
            },
            "analysis": {
                "enabled": True,
                "current_project_memory": {
                    "requirements": [],
                    "tasks": [],
                    "tests": tests or [],
                    "blockers": blockers or [],
                    "current_source_count": 2,
                    "historical_source_count": 1,
                },
            },
            "git_change_analysis": {
                "enabled": True,
                "changed_file_count": changed,
                "analyzed_file_count": changed,
            },
        },
    }


def test_rollup_keeps_multiple_developers_and_agents():
    snapshots = [
        _snapshot(1, "caoyh", "mac-1", "低电压", "cao", True, 3),
        _snapshot(2, "yujie", "win-1", "低电压", "ryj", False, 1),
    ]
    events = [
        {
            "user_id": "caoyh",
            "event_type": "task.progress",
            "observed_at": "2026-09-08T09:10:00+00:00",
            "agent": {"name": "Codex", "vendor": "OpenAI"},
        },
        {
            "user_id": "yujie",
            "event_type": "task.finished",
            "observed_at": "2026-09-08T09:20:00+00:00",
            "agent": {"name": "TRAE", "vendor": "ByteDance"},
        },
    ]

    result = build_project_rollup(snapshots, events)

    assert result["workspace_count"] == 2
    assert result["contributor_count"] == 2
    assert result["dirty_workspace_count"] == 1
    assert result["local_changed_file_count"] == 4
    assert result["branches"] == {"cao": 1, "ryj": 1}
    assert result["agents"] == ["Codex", "TRAE"]

    users = {item["user_id"]: item for item in result["contributors"]}
    assert users["caoyh"]["agents"] == ["Codex"]
    assert users["caoyh"]["dirty_workspace_count"] == 1
    assert users["yujie"]["agents"] == ["TRAE"]


def test_rollup_attention_if_any_workspace_has_failure_or_blocker():
    snapshots = [
        _snapshot(
            1,
            "caoyh",
            "mac-1",
            "低电压",
            "cao",
            False,
            0,
            tests=[{"text": "工程量回归测试：1失败"}],
        ),
        _snapshot(2, "yujie", "win-1", "低电压", "ryj", False, 0),
    ]

    result = build_project_rollup(snapshots, [])

    assert result["project_state"] == "attention"
    assert result["attention_workspace_count"] == 1


def test_remote_gitlab_authors_are_project_contributors():
    snapshots = [_snapshot(1, "caoyh", "mac-1", "缺陷", "cyh", False, 0)]
    remote_events = [
        {
            "event_type": "git.commit",
            "repository_id": "multimodal-agent",
            "branch": "cyh",
            "observed_at": "2026-09-08T10:00:00+00:00",
            "data": {"author_name": "zhangsan", "author_email": "zhangsan@example.com"},
        },
        {
            "event_type": "merge_request.opened",
            "repository_id": "multimodal-agent",
            "branch": "feature/x",
            "observed_at": "2026-09-08T11:00:00+00:00",
            "data": {"author": "lisi"},
        },
    ]

    result = build_project_rollup(snapshots, [], remote_events)
    names = {item["display_name"] for item in result["contributors"]}
    assert names == {"caoyh", "zhangsan", "lisi"}
    assert result["contributor_count"] == 3
    assert result["local_contributor_count"] == 1
    assert result["repository_contributor_count"] == 2
    zhang = next(item for item in result["contributors"] if item["display_name"] == "zhangsan")
    assert zhang["source_types"] == ["repository"]
    assert zhang["repositories"] == ["multimodal-agent"]


def test_exact_remote_actor_name_merges_with_local_user():
    snapshots = [_snapshot(1, "caoyh", "mac-1", "缺陷", "cyh", False, 0)]
    remote_events = [
        {
            "event_type": "git.push",
            "repository_id": "multimodal-agent",
            "observed_at": "2026-09-08T12:00:00+00:00",
            "data": {"author": "caoyh"},
        }
    ]
    result = build_project_rollup(snapshots, [], remote_events)
    assert result["contributor_count"] == 1
    assert result["contributors"][0]["source_types"] == ["local", "repository"]
