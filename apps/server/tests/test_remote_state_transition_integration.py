from __future__ import annotations

from evidence_lifecycle import normalize_evidence
from remote_evidence import apply_remote_evidence


def _fusion():
    return {
        "version": 2,
        "scope": "cross_workspace_local_evidence",
        "project_state": "active",
        "project_state_label": "多人协作开发中",
        "formal_completion_supported": False,
        "summary": {"status_counts": {"local_verified_pending_remote": 1}},
        "work_items": [
            {
                "work_item_id": "LV-102",
                "task_id": "LV-102",
                "title": "资料上传更新左侧树状页面",
                "status": "local_verified_pending_remote",
                "status_label": "本地验证通过，待远端复核",
                "status_reasons": [],
                "evidence": [
                    {
                        "source": "git_local",
                        "kind": "code_change",
                        "text": "实现资料上传更新左侧树状页面",
                        "task_id": "LV-102",
                        "match_score": 1.0,
                    },
                    {
                        "source": "document",
                        "kind": "test",
                        "text": "测试通过",
                        "task_id": "LV-102",
                        "match_score": 1.0,
                    },
                ],
                "workspace_contributions": [{"git_dirty": False, "git_ahead": 0}],
            }
        ],
        "unlinked_evidence": {},
    }


def _event(event_type: str, at: str, **data):
    return {
        "event_type": event_type,
        "observed_at": at,
        "provider": "gitlab",
        "repository_id": "low-voltage",
        "repository_url": "http://git.example/low-voltage.git",
        "branch": "feature/tree-page",
        "commit_sha": "abc123",
        "task_id": "LV-102",
        "task_title": "资料上传更新左侧树状页面",
        "data": {"title": "资料上传更新左侧树状页面", **data},
    }


def test_same_pipeline_id_keeps_failed_to_passed_transition():
    result = apply_remote_evidence(
        _fusion(),
        [
            _event("git.push", "2026-09-11T08:00:00Z"),
            _event("merge_request.opened", "2026-09-11T08:05:00Z", iid=7),
            _event("ci.failed", "2026-09-11T08:10:00Z", pipeline_id=123),
            _event("ci.passed", "2026-09-11T08:20:00Z", pipeline_id=123),
        ],
    )
    item = result["work_items"][0]
    assert item["formal_status"] == "awaiting_merge"
    assert "ci_failed" not in item["flags"]


def test_same_deployment_id_keeps_success_to_failure_transition():
    result = apply_remote_evidence(
        _fusion(),
        [
            _event("ci.passed", "2026-09-11T08:00:00Z", pipeline_id=123),
            _event("merge_request.merged", "2026-09-11T08:10:00Z", iid=7),
            _event("deployment.succeeded", "2026-09-11T08:20:00Z", deployment_id=88),
            _event("deployment.failed", "2026-09-11T08:30:00Z", deployment_id=88),
        ],
    )
    item = result["work_items"][0]
    assert item["formal_status"] == "deployment_failed"
    assert item["formal_completion"] is False


def test_same_merge_request_iid_keeps_open_to_merged_transition():
    result = apply_remote_evidence(
        _fusion(),
        [
            _event("git.push", "2026-09-11T08:00:00Z"),
            _event("merge_request.opened", "2026-09-11T08:05:00Z", iid=7),
            _event("ci.passed", "2026-09-11T08:10:00Z", pipeline_id=123),
            _event("merge_request.merged", "2026-09-11T08:20:00Z", iid=7),
        ],
    )
    item = result["work_items"][0]
    assert item["formal_status"] == "completed"
    assert item["formal_completion"] is True


def test_same_provider_id_same_state_still_deduplicates():
    entries = [
        {
            "source": "remote_devops",
            "source_type": "remote_devops",
            "relation": "ci",
            "kind": "ci_passed",
            "text": "pipeline passed",
            "repository_id": "r1",
            "observed_at": "2026-09-11T08:10:00Z",
            "data": {"pipeline_id": 123},
        },
        {
            "source": "remote_devops",
            "source_type": "remote_devops",
            "relation": "ci",
            "kind": "ci_passed",
            "text": "pipeline passed retry webhook",
            "repository_id": "r1",
            "observed_at": "2026-09-11T08:11:00Z",
            "data": {"pipeline_id": 123},
        },
    ]
    assert len(normalize_evidence(entries)) == 1
