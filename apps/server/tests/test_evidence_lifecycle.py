from evidence_fusion import fuse_evidence
from evidence_lifecycle import normalize_evidence
from remote_evidence import apply_remote_evidence


def _fusion(status="local_verified_pending_remote", evidence=None):
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
                "evidence": evidence or [],
                "contributors": ["u1", "u2"],
            }
        ],
        "unlinked_evidence": {},
    }


def _event(event_type, *, task_id="LV-102", title="资料上传更新左侧树状页面", at="2026-09-08T11:00:00Z"):
    return {
        "event_type": event_type,
        "observed_at": at,
        "provider": "gitlab",
        "repository_id": "low-voltage-frontend",
        "repository_url": "http://git.example/repo.git",
        "branch": "feature/tree-page",
        "commit_sha": "abc123",
        "task_id": task_id,
        "task_title": title,
        "remote_url": "http://git.example/example",
        "data": {"title": title},
    }


def _code():
    return {"source": "git_local", "kind": "code_change", "text": "实现资料上传更新左侧树状页面", "match_score": 1.0}


def _agent_finished():
    return {
        "source": "agent",
        "kind": "finished",
        "text": "资料上传更新左侧树状页面 已完成",
        "task_id": "LV-102",
        "observed_at": "2026-09-08T10:00:00Z",
    }


def _test(text, at="2026-09-08T10:10:00Z", score=1.0):
    return {"source": "document", "kind": "test", "text": text, "observed_at": at, "match_score": score}


def _payload(*, current_facts=None, historical_facts=None, requirements=None, progress=None):
    memory = {
        "requirements": requirements or [],
        "tasks": [],
        "tests": [],
        "blockers": [],
        "progress": progress or [],
    }
    if current_facts is not None:
        memory["current_facts"] = current_facts
    if historical_facts is not None:
        memory["historical_facts"] = historical_facts
    return {
        "git": {"is_git_repo": True, "dirty": False, "ahead": 0, "behind": 0, "upstream": "origin/cao"},
        "analysis": {"current_project_memory": memory},
        "git_change_analysis": {"enabled": True, "items": []},
    }


def test_agent_finished_without_code_is_conflict_not_completed():
    result = apply_remote_evidence(_fusion(status="agent_claim_only", evidence=[_agent_finished()]), [])
    item = result["work_items"][0]
    assert item["formal_completion"] is False
    assert item["formal_status"] == "evidence_conflict"
    assert "agent_finished_without_code" in item["flags"]
    assert "completed_claim_without_engineering_evidence" in item["flags"]


def test_dirty_local_verified_is_not_completed_and_flags_uncommitted():
    fusion = _fusion(status="locally_complete_uncommitted", evidence=[_code(), _test("测试通过")])
    fusion["work_items"][0]["workspace_contributions"] = [{"git_dirty": True, "git_ahead": 0}]
    item = apply_remote_evidence(fusion, [])["work_items"][0]
    assert item["formal_status"] == "local_verified"
    assert item["formal_completion"] is False
    assert "local_verified_uncommitted" in item["flags"]


def test_local_commit_ahead_is_awaiting_push():
    fusion = _fusion(status="locally_complete_unpushed", evidence=[_code(), _test("测试通过")])
    fusion["work_items"][0]["workspace_contributions"] = [{"git_dirty": False, "git_ahead": 2}]
    item = apply_remote_evidence(fusion, [])["work_items"][0]
    assert item["formal_status"] == "awaiting_push"
    assert "committed_unpushed" in item["flags"]


def test_push_without_test_is_not_completed():
    result = apply_remote_evidence(_fusion(evidence=[_code()]), [_event("git.push")])
    item = result["work_items"][0]
    assert item["formal_status"] == "pushed"
    assert "pushed_without_test" in item["flags"]


def test_latest_ci_pass_overrides_older_failure():
    base = _fusion(evidence=[_code(), _test("测试通过")])
    result = apply_remote_evidence(
        base,
        [
            _event("git.push", at="2026-09-08T11:00:00Z"),
            _event("merge_request.opened", at="2026-09-08T11:05:00Z"),
            _event("ci.failed", at="2026-09-08T11:10:00Z"),
            _event("ci.passed", at="2026-09-08T11:20:00Z"),
        ],
    )
    item = result["work_items"][0]
    assert item["formal_status"] == "awaiting_merge"
    assert "ci_failed" not in item["flags"]
    assert result["project_state"] != "attention"


def test_latest_ci_fail_overrides_older_pass_and_claim_conflicts():
    base = _fusion(evidence=[_code(), _agent_finished(), _test("测试通过")])
    result = apply_remote_evidence(
        base,
        [
            _event("git.push", at="2026-09-08T11:00:00Z"),
            _event("merge_request.opened", at="2026-09-08T11:05:00Z"),
            _event("ci.passed", at="2026-09-08T11:10:00Z"),
            _event("ci.failed", at="2026-09-08T11:20:00Z"),
        ],
    )
    item = result["work_items"][0]
    assert item["formal_status"] == "ci_failed"
    assert "completion_claim_conflicts_with_ci" in item["flags"]
    assert "local_remote_verification_conflict" in item["flags"]
    assert result["project_state"] == "attention"


def test_merged_with_deployment_capability_but_no_success_waits_deploy():
    base = _fusion(evidence=[_code(), _test("测试通过")])
    result = apply_remote_evidence(
        base,
        [
            _event("git.push", at="2026-09-08T11:00:00Z"),
            _event("ci.passed", at="2026-09-08T11:10:00Z"),
            _event("merge_request.merged", at="2026-09-08T11:20:00Z"),
            _event("deployment.started", at="2026-09-08T11:30:00Z"),
        ],
    )
    assert result["work_items"][0]["formal_status"] == "awaiting_deployment"


def test_deployment_failure_overrides_merge_and_old_success():
    base = _fusion(evidence=[_code(), _test("测试通过")])
    result = apply_remote_evidence(
        base,
        [
            _event("ci.passed", at="2026-09-08T11:10:00Z"),
            _event("merge_request.merged", at="2026-09-08T11:20:00Z"),
            _event("deployment.succeeded", at="2026-09-08T11:30:00Z"),
            _event("deployment.failed", at="2026-09-08T11:40:00Z"),
        ],
    )
    item = result["work_items"][0]
    assert item["formal_status"] == "deployment_failed"
    assert item["formal_completion"] is False


def test_full_merge_ci_deploy_chain_reaches_completed():
    base = _fusion(evidence=[_code(), _test("测试通过")])
    result = apply_remote_evidence(
        base,
        [
            _event("git.push", at="2026-09-08T11:00:00Z"),
            _event("merge_request.opened", at="2026-09-08T11:10:00Z"),
            _event("ci.passed", at="2026-09-08T11:20:00Z"),
            _event("merge_request.merged", at="2026-09-08T11:30:00Z"),
            _event("deployment.succeeded", at="2026-09-08T11:40:00Z"),
        ],
    )
    item = result["work_items"][0]
    assert item["formal_status"] == "completed"
    assert item["formal_completion"] is True
    assert item["completion_level"] == "deployed"


def test_simple_repo_push_plus_test_can_complete_without_mr_or_deploy():
    base = _fusion(evidence=[_code(), _test("测试通过")])
    item = apply_remote_evidence(base, [_event("git.push")])["work_items"][0]
    assert item["formal_status"] == "completed"
    assert item["completion_level"] == "remotely_verified"


def test_low_confidence_success_cannot_prove_completion_but_failure_warns():
    base = _fusion(evidence=[_code(), _test("测试通过", score=0.2)])
    item = apply_remote_evidence(base, [_event("git.push")])["work_items"][0]
    assert item["formal_status"] == "pushed"

    base2 = _fusion(evidence=[_code(), _test("测试失败", score=0.2)])
    item2 = apply_remote_evidence(base2, [])["work_items"][0]
    assert "unlinked_failure" in item2["flags"]
    assert item2["formal_status"] == "local_implementation"


def test_same_sha_commit_and_push_normalize_once():
    entries = [
        {"source": "remote_devops", "kind": "remote_commit", "text": "commit", "repository_id": "r1", "commit_sha": "sha1", "event_type": "git.commit"},
        {"source": "remote_devops", "kind": "remote_commit", "text": "push", "repository_id": "r1", "commit_sha": "sha1", "event_type": "git.push"},
    ]
    assert len(normalize_evidence(entries)) == 1


def test_repeated_pipeline_same_id_does_not_gain_extra_strength():
    entries = [
        {"source": "remote_devops", "kind": "ci_passed", "text": "ci", "repository_id": "r1", "data": {"pipeline_id": 123}},
        {"source": "remote_devops", "kind": "ci_passed", "text": "ci again", "repository_id": "r1", "data": {"pipeline_id": 123}},
    ]
    assert len(normalize_evidence(entries)) == 1


def test_project_memory_v2_current_facts_take_priority_over_legacy_and_history():
    result = fuse_evidence(
        _payload(
            current_facts=[{"type": "task", "text": "当前任务A", "task_key": "A"}],
            historical_facts=[{"type": "task", "text": "历史任务B", "task_key": "B"}],
            requirements=[{"text": "旧兼容任务C"}],
        ),
        [],
    )
    assert result["memory_mode"] == "current_facts"
    assert [item["task_key"] for item in result["work_items"]] == ["A"]


def test_document_progress_completion_claim_is_preserved_for_fusion():
    title = "资料上传更新左侧树状页面"
    result = fuse_evidence(
        _payload(
            requirements=[{"text": title}],
            progress=[{"text": "资料上传更新左侧树状页面已完成", "source_date": "2026-09-10"}],
        ),
        [],
    )
    evidence = result["work_items"][0]["evidence"]
    assert any(entry.get("kind") == "progress_claim" for entry in evidence)
