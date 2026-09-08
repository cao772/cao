from __future__ import annotations

import re
from collections import Counter
from typing import Any

from evidence_fusion import similarity


REMOTE_STATUS_LABELS = {
    "remote_ci_failed": "远端CI未通过",
    "deployment_failed": "部署失败",
    "review_in_progress": "PR/MR审核中",
    "remote_commit_detected": "已提交远端",
    "ci_passed_pending_merge": "CI通过，待合并",
    "merged_pending_deploy": "已合并，待部署确认",
    "completed": "正式完成",
}

REMOTE_NOISE = (
    "merge request", "pull request", "merged", "opened", "closed", "pipeline", "deployment",
    "commit", "push", "branch", "ci", "mr", "pr",
    "合并请求", "代码审查", "流水线", "部署", "提交", "推送", "通过", "失败", "成功",
    "修复", "新增", "实现", "优化", "调整", "问题", "功能", "任务", "需求",
)


def _normalized(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "").lower())


def _semantic_core(value: Any) -> str:
    text = _normalized(value)
    for marker in REMOTE_NOISE:
        text = text.replace(_normalized(marker), "")
    return text


def _event_text(event: dict[str, Any]) -> str:
    data = event.get("data") or {}
    values = [
        event.get("task_title"),
        event.get("title"),
        data.get("title"),
        data.get("summary"),
        data.get("message"),
        data.get("ref"),
        data.get("source_branch"),
    ]
    return " ".join(str(value).strip() for value in values if value).strip()


def _find_task(event: dict[str, Any], work_items: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    task_id = str(event.get("task_id") or "").strip()
    if task_id:
        exact = next((item for item in work_items if str(item.get("task_id") or "").strip() == task_id), None)
        if exact is not None:
            return exact, 1.0

    text = _event_text(event)
    if not text:
        return None, 0.0

    best_score = 0.0
    best_item = None
    for item in work_items:
        score = similarity(text, item.get("title"))
        if score > best_score:
            best_score = score
            best_item = item
    if best_item is not None and best_score >= 0.42:
        return best_item, best_score

    core = _semantic_core(text)
    if len(core) >= 4:
        for item in work_items:
            title_core = _semantic_core(item.get("title"))
            if len(title_core) >= 4 and (core in title_core or title_core in core):
                return item, 0.72
    return None, best_score


def _kind(event_type: str) -> str:
    value = str(event_type or "").lower().replace("-", "_")
    if "deployment" in value or "deploy" in value:
        if any(token in value for token in ("fail", "error", "cancel")):
            return "deployment_failed"
        if any(token in value for token in ("success", "succeed", "complete", "finished")):
            return "deployment_succeeded"
        return "deployment"
    if "pipeline" in value or value.startswith("ci.") or value.startswith("ci_"):
        if any(token in value for token in ("fail", "error", "cancel")):
            return "ci_failed"
        if any(token in value for token in ("success", "succeed", "pass", "complete")):
            return "ci_passed"
        return "ci_running"
    if "merge_request" in value or "pull_request" in value or value.startswith("mr.") or value.startswith("pr."):
        if "merged" in value:
            return "merged"
        if "closed" in value:
            return "review_closed"
        return "review_open"
    if "merge" in value and "merged" in value:
        return "merged"
    if "push" in value or "commit" in value:
        return "remote_commit"
    return "remote_other"


def _remote_evidence(event: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "source": "remote_devops",
        "kind": _kind(str(event.get("event_type") or "")),
        "text": _event_text(event) or str(event.get("event_type") or "remote event"),
        "event_type": event.get("event_type"),
        "observed_at": event.get("observed_at"),
        "provider": event.get("provider"),
        "repository_id": event.get("repository_id"),
        "repository_url": event.get("repository_url"),
        "branch": event.get("branch"),
        "commit_sha": event.get("commit_sha"),
        "remote_url": event.get("remote_url"),
        "task_id": event.get("task_id"),
        "match_score": round(score, 3),
        "data": event.get("data") or {},
    }


def _derive_remote_status(item: dict[str, Any]) -> tuple[str | None, list[str]]:
    remote = [entry for entry in item.get("evidence") or [] if entry.get("source") == "remote_devops"]
    kinds = Counter(str(entry.get("kind") or "") for entry in remote)
    if not remote:
        return None, []

    if kinds["deployment_failed"]:
        return "deployment_failed", ["远端存在部署失败证据"]
    if kinds["ci_failed"]:
        return "remote_ci_failed", ["远端CI/Pipeline存在失败证据"]

    deployment_succeeded = kinds["deployment_succeeded"] > 0
    merged = kinds["merged"] > 0
    ci_passed = kinds["ci_passed"] > 0
    review_open = kinds["review_open"] > 0
    remote_commit = kinds["remote_commit"] > 0

    if deployment_succeeded and merged and ci_passed:
        return "completed", ["存在CI通过、代码已合并和部署成功三类远端证据"]
    if merged:
        return "merged_pending_deploy", ["代码已合并，但尚缺部署成功证据"]
    if ci_passed:
        return "ci_passed_pending_merge", ["远端CI已通过，尚未确认合并"]
    if review_open:
        return "review_in_progress", ["已创建PR/MR，当前处于审核/合并流程"]
    if remote_commit:
        return "remote_commit_detected", ["已检测到远端Commit/Push证据"]
    return None, []


def apply_remote_evidence(
    local_fusion: dict[str, Any],
    remote_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach GitHub/GitLab/DevLake facts to project-level tasks.

    Remote evidence never replaces local evidence. It advances a task beyond the
    local verification boundary only when explicit remote facts exist. Formal
    `completed` requires CI pass + merge + deployment success.
    """
    remote_events = remote_events or []
    result = dict(local_fusion)
    work_items = [dict(item) for item in (local_fusion.get("work_items") or [])]
    for index, item in enumerate(work_items):
        item["evidence"] = [dict(entry) for entry in (item.get("evidence") or [])]
        work_items[index] = item

    unlinked: list[dict[str, Any]] = []
    for event in remote_events:
        target, score = _find_task(event, work_items)
        evidence = _remote_evidence(event, score)
        if target is None:
            unlinked.append(evidence)
            continue
        target.setdefault("evidence", []).append(evidence)

    status_counts: Counter[str] = Counter()
    for item in work_items:
        remote_status, remote_reasons = _derive_remote_status(item)
        if remote_status is not None:
            local_status = item.get("status")
            local_reasons = list(item.get("status_reasons") or [])
            # Local blockers/test failures remain authoritative unless the remote
            # evidence itself proves a later successful deployment lifecycle.
            if local_status in {"blocked", "test_failing"} and remote_status != "completed":
                status = str(local_status)
                reasons = local_reasons + remote_reasons
            else:
                status = remote_status
                reasons = local_reasons + remote_reasons
            item["status"] = status
            item["status_label"] = REMOTE_STATUS_LABELS.get(status, item.get("status_label") or status)
            item["status_reasons"] = reasons
        status_counts[str(item.get("status") or "unknown")] += 1

    existing_unlinked = dict(local_fusion.get("unlinked_evidence") or {})
    existing_unlinked["remote_events"] = unlinked[:300]

    attention = any(
        status_counts[status]
        for status in ("blocked", "test_failing", "remote_ci_failed", "deployment_failed")
    )
    active = any(
        status_counts[status]
        for status in (
            "in_progress_agent", "in_progress_uncommitted", "implementation_detected",
            "implementation_tested", "implementation_claimed_uncommitted",
            "implementation_claimed_unverified", "locally_complete_uncommitted",
            "locally_complete_unpushed", "local_verified_pending_remote",
            "remote_commit_detected", "review_in_progress", "ci_passed_pending_merge",
            "merged_pending_deploy",
        )
    )
    project_state = "attention" if attention else ("active" if active else "quiet")

    summary = dict(local_fusion.get("summary") or {})
    summary["remote_event_count"] = len(remote_events)
    summary["unlinked_remote_event_count"] = len(unlinked)
    summary["status_counts"] = dict(status_counts)
    summary["completed_work_item_count"] = status_counts["completed"]

    result.update(
        {
            "version": 3,
            "scope": "cross_workspace_with_remote_devops",
            "project_state": project_state,
            "project_state_label": {
                "attention": "需要关注",
                "active": "多人协作开发中",
                "quiet": "暂无明显开发活动",
            }[project_state],
            "formal_completion_supported": True,
            "formal_completion_reason": "任务只有在关联到CI通过、代码合并和部署成功远端证据后才判定正式完成。",
            "summary": summary,
            "work_items": work_items,
            "unlinked_evidence": existing_unlinked,
        }
    )
    return result
