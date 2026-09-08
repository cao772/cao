from gitlab_collector import (
    normalize_commit,
    normalize_deployment,
    normalize_merge_request,
    normalize_pipeline,
)


PROJECT = {"project_id": "low-voltage", "project_name": "低电压项目"}
REPO = {
    "id": "low-voltage-algorithm",
    "provider": "gitlab",
    "url": "http://git.hyetec.com/hyetec/rj26nw011/algorithm.git",
}


def test_commit_extracts_task_id():
    event = normalize_commit(
        PROJECT,
        REPO,
        {
            "id": "abc123",
            "title": "LV-102 修复工程量提取",
            "message": "LV-102 修复工程量提取\n",
            "committed_date": "2026-09-08T10:00:00+00:00",
            "web_url": "http://git/commit/abc123",
        },
    )
    assert event["event_type"] == "git.commit"
    assert event["task_id"] == "LV-102"
    assert event["repository_id"] == "low-voltage-algorithm"


def test_merge_request_merged_is_normalized():
    event = normalize_merge_request(
        PROJECT,
        REPO,
        {
            "iid": 12,
            "state": "merged",
            "title": "LV-102 资料上传更新左侧树状页面",
            "source_branch": "cao",
            "target_branch": "main",
            "merged_at": "2026-09-08T10:10:00+00:00",
            "updated_at": "2026-09-08T10:10:00+00:00",
            "web_url": "http://git/mr/12",
        },
    )
    assert event["event_type"] == "merge_request.merged"
    assert event["task_id"] == "LV-102"
    assert event["branch"] == "cao"


def test_pipeline_success_is_ci_passed():
    event = normalize_pipeline(
        PROJECT,
        REPO,
        {
            "id": 33,
            "status": "success",
            "ref": "LV-102-tree-page",
            "sha": "abc123",
            "updated_at": "2026-09-08T10:20:00+00:00",
        },
    )
    assert event["event_type"] == "ci.passed"
    assert event["task_id"] == "LV-102"


def test_deployment_success_is_normalized():
    event = normalize_deployment(
        PROJECT,
        REPO,
        {
            "id": 44,
            "status": "success",
            "ref": "LV-102-tree-page",
            "updated_at": "2026-09-08T10:30:00+00:00",
            "environment": {"name": "test"},
            "deployable": {"commit": {"id": "abc123"}},
        },
    )
    assert event["event_type"] == "deployment.succeeded"
    assert event["data"]["environment"] == "test"
    assert event["commit_sha"] == "abc123"
