from remote_evidence import apply_remote_evidence


def _fusion(status="local_verified_pending_remote"):
    return {
        "version": 2,
        "scope": "cross_workspace_local_evidence",
        "project_state": "active",
        "project_state_label": "多人协作开发中",
        "formal_completion_supported": False,
        "summary": {"status_counts": {status: 1}},
        "work_items": [
            {
                "work_item_id": "LV-102",
                "task_id": "LV-102",
                "title": "资料上传更新左侧树状页面",
                "status": status,
                "status_label": "本地验证通过，待远端复核",
                "status_reasons": ["本地证据已验证"],
                "evidence": [],
                "contributors": ["u1", "u2"],
            }
        ],
        "unlinked_evidence": {},
    }


def _event(event_type, *, task_id="LV-102", title="资料上传更新左侧树状页面"):
    return {
        "event_type": event_type,
        "observed_at": "2026-09-08T11:00:00Z",
        "provider": "gitlab",
        "repository_id": "low-voltage-frontend",
        "repository_url": "http://git.hyetec.com/hyetec/rj26nw011/Front-end/voltage-management.git",
        "branch": "cao",
        "commit_sha": "abc123",
        "task_id": task_id,
        "task_title": title,
        "remote_url": "http://git.hyetec.com/example",
        "data": {"title": title},
    }


def test_remote_lifecycle_reaches_completed_only_with_merge_ci_and_deploy():
    result = apply_remote_evidence(
        _fusion(),
        [
            _event("git.push"),
            _event("merge_request.opened"),
            _event("ci.passed"),
            _event("merge_request.merged"),
            _event("deployment.succeeded"),
        ],
    )
    item = result["work_items"][0]
    assert item["status"] == "completed"
    assert item["status_label"] == "正式完成"
    assert result["formal_completion_supported"] is True
    assert result["summary"]["completed_work_item_count"] == 1


def test_ci_failure_has_priority_before_merge():
    result = apply_remote_evidence(
        _fusion(),
        [_event("git.push"), _event("merge_request.opened"), _event("ci.failed")],
    )
    assert result["work_items"][0]["status"] == "remote_ci_failed"
    assert result["project_state"] == "attention"


def test_unmatched_remote_event_is_kept_unlinked():
    result = apply_remote_evidence(
        _fusion(),
        [_event("git.push", task_id="OTHER-1", title="完全不同事项")],
    )
    assert result["work_items"][0]["status"] == "local_verified_pending_remote"
    assert len(result["unlinked_evidence"]["remote_events"]) == 1


def test_pipeline_and_deploy_inherit_task_from_merge_request_sha_and_branch():
    mr = _event("merge_request.merged")
    mr["branch"] = "feature/tree-page"
    mr["commit_sha"] = "merge-sha-1"
    mr["data"]["source_branch"] = "feature/tree-page"

    # Real GitLab pipeline/deployment rows often contain only ref/SHA and no task title.
    pipeline = _event("ci.passed", task_id=None, title="")
    pipeline["branch"] = "feature/tree-page"
    pipeline["commit_sha"] = "merge-sha-1"
    pipeline["data"] = {"ref": "feature/tree-page"}

    deployment = _event("deployment.succeeded", task_id=None, title="")
    deployment["branch"] = "feature/tree-page"
    deployment["commit_sha"] = "merge-sha-1"
    deployment["data"] = {"ref": "feature/tree-page", "environment": "test"}

    result = apply_remote_evidence(_fusion(), [mr, pipeline, deployment])
    item = result["work_items"][0]
    assert item["status"] == "completed"
    remote = [entry for entry in item["evidence"] if entry.get("source") == "remote_devops"]
    assert len(remote) == 3
    assert any(entry.get("linked_by") in {"sha", "branch"} for entry in remote)
