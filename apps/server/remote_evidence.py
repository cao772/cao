from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from evidence_fusion import similarity
from evidence_lifecycle import upgrade_fusion_result


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


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
        event.get("task_title"), event.get("title"), data.get("title"), data.get("summary"),
        data.get("message"), data.get("ref"), data.get("source_branch"),
    ]
    return " ".join(str(value).strip() for value in values if value).strip()


def _find_task(event: dict[str, Any], work_items: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    task_id = str(event.get("task_id") or event.get("task_key") or "").strip()
    if task_id:
        exact = next(
            (
                item for item in work_items
                if task_id in {str(item.get("task_id") or "").strip(), str(item.get("task_key") or "").strip()}
            ),
            None,
        )
        if exact is not None:
            return exact, 1.0

    text = _event_text(event)
    if not text:
        return None, 0.0
    best_score = 0.0; best_item = None
    for item in work_items:
        score = similarity(text, item.get("title"))
        if score > best_score:
            best_score = score; best_item = item
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
        if any(token in value for token in ("fail", "error", "cancel")): return "deployment_failed"
        if any(token in value for token in ("success", "succeed", "complete", "finished")): return "deployment_succeeded"
        return "deployment"
    if "pipeline" in value or value.startswith("ci.") or value.startswith("ci_"):
        if any(token in value for token in ("fail", "error", "cancel")): return "ci_failed"
        if any(token in value for token in ("success", "succeed", "pass", "complete")): return "ci_passed"
        return "ci_running"
    if "merge_request" in value or "pull_request" in value or value.startswith("mr.") or value.startswith("pr."):
        if "merged" in value: return "merged"
        if "closed" in value: return "review_closed"
        return "review_open"
    if "merge" in value and "merged" in value: return "merged"
    if "push" in value or "commit" in value: return "remote_commit"
    return "remote_other"


def _remote_evidence(event: dict[str, Any], score: float, *, linked_by: str = "semantic") -> dict[str, Any]:
    return {
        "source": "remote_devops", "kind": _kind(str(event.get("event_type") or "")),
        "text": _event_text(event) or str(event.get("event_type") or "remote event"),
        "event_type": event.get("event_type"), "observed_at": event.get("observed_at"),
        "provider": event.get("provider"), "repository_id": event.get("repository_id"),
        "repository_url": event.get("repository_url"), "branch": event.get("branch"),
        "commit_sha": event.get("commit_sha"), "remote_url": event.get("remote_url"),
        "task_id": event.get("task_id"), "task_key": event.get("task_key"),
        "match_score": round(score, 3), "linked_by": linked_by,
        "client_event_id": event.get("client_event_id"), "data": event.get("data") or {},
    }


def _association_keys(event: dict[str, Any]) -> list[tuple[str, str, str]]:
    repository_id = str(event.get("repository_id") or "").strip()
    if not repository_id: return []
    result: list[tuple[str, str, str]] = []
    sha = str(event.get("commit_sha") or "").strip(); branch = str(event.get("branch") or "").strip()
    data = event.get("data") or {}; source_branch = str(data.get("source_branch") or "").strip(); ref = str(data.get("ref") or "").strip()
    if sha: result.append((repository_id, "sha", sha))
    for value in (branch, source_branch, ref):
        if value: result.append((repository_id, "branch", value))
    return result


def _latest(remote: list[dict[str, Any]], kinds: set[str]) -> dict[str, Any] | None:
    candidates = [(index, entry) for index, entry in enumerate(remote) if str(entry.get("kind") or "") in kinds]
    if not candidates: return None
    return max(
        candidates,
        key=lambda pair: (_parse_time(pair[1].get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc), pair[0]),
    )[1]


def _derive_remote_status(item: dict[str, Any]) -> tuple[str | None, list[str]]:
    remote = [entry for entry in item.get("evidence") or [] if entry.get("source") == "remote_devops"]
    if not remote: return None, []

    latest_deploy = _latest(remote, {"deployment_failed", "deployment_succeeded", "deployment"})
    latest_ci = _latest(remote, {"ci_failed", "ci_passed", "ci_running"})
    latest_review = _latest(remote, {"review_open", "review_closed", "merged"})
    latest_commit = _latest(remote, {"remote_commit"})

    if latest_deploy and latest_deploy.get("kind") == "deployment_failed": return "deployment_failed", ["最新远端部署证据为失败"]
    if latest_ci and latest_ci.get("kind") == "ci_failed": return "remote_ci_failed", ["最新远端CI/Pipeline证据为失败"]

    deployment_succeeded = bool(latest_deploy and latest_deploy.get("kind") == "deployment_succeeded")
    merged = bool(latest_review and latest_review.get("kind") == "merged")
    ci_passed = bool(latest_ci and latest_ci.get("kind") == "ci_passed")
    review_open = bool(latest_review and latest_review.get("kind") == "review_open")

    if deployment_succeeded and merged and ci_passed: return "completed", ["最新CI通过、代码已合并和部署成功证据链闭合"]
    if merged: return "merged_pending_deploy", ["代码已合并，但尚缺当前部署成功证据"]
    if ci_passed: return "ci_passed_pending_merge", ["最新远端CI已通过，尚未确认合并"]
    if review_open: return "review_in_progress", ["已创建PR/MR，当前处于审核/合并流程"]
    if latest_commit: return "remote_commit_detected", ["已检测到远端Commit/Push证据"]
    return None, []


def apply_remote_evidence(local_fusion: dict[str, Any], remote_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Attach remote facts, then run the conservative Evidence Fusion V2 adjudicator."""
    remote_events = remote_events or []
    result = dict(local_fusion)
    work_items = [dict(item) for item in (local_fusion.get("work_items") or [])]
    for index, item in enumerate(work_items):
        item["evidence"] = [dict(entry) for entry in (item.get("evidence") or [])]; work_items[index] = item

    associations: dict[tuple[str, str, str], dict[str, Any]] = {}; pending: list[tuple[dict[str, Any], float]] = []
    for event in remote_events:
        target, score = _find_task(event, work_items)
        if target is None:
            pending.append((event, score)); continue
        target.setdefault("evidence", []).append(_remote_evidence(event, score, linked_by="task_or_semantic"))
        for key in _association_keys(event): associations[key] = target

    for item in work_items:
        for evidence in item.get("evidence") or []:
            if evidence.get("source") != "remote_devops": continue
            for key in _association_keys(evidence): associations[key] = item

    unlinked: list[dict[str, Any]] = []
    for event, score in pending:
        target = None; linked_by = "unlinked"
        for key in _association_keys(event):
            if key in associations:
                target = associations[key]; linked_by = key[1]; break
        evidence = _remote_evidence(event, 0.95 if target is not None else score, linked_by=linked_by)
        if target is None:
            unlinked.append(evidence); continue
        target.setdefault("evidence", []).append(evidence)
        for key in _association_keys(event): associations[key] = target

    status_counts: dict[str, int] = {}
    for item in work_items:
        remote_status, remote_reasons = _derive_remote_status(item)
        if remote_status is not None:
            local_status = item.get("status"); local_reasons = list(item.get("status_reasons") or [])
            if local_status in {"blocked", "test_failing"} and remote_status != "completed":
                status = str(local_status); reasons = local_reasons + remote_reasons
            else:
                status = remote_status; reasons = local_reasons + remote_reasons
            item["status"] = status
            item["status_label"] = REMOTE_STATUS_LABELS.get(status, item.get("status_label") or status)
            item["status_reasons"] = reasons
        key = str(item.get("status") or "unknown"); status_counts[key] = status_counts.get(key, 0) + 1

    existing_unlinked = dict(local_fusion.get("unlinked_evidence") or {}); existing_unlinked["remote_events"] = unlinked[:300]
    attention = any(status_counts.get(status, 0) for status in ("blocked", "test_failing", "remote_ci_failed", "deployment_failed"))
    active = any(
        status_counts.get(status, 0)
        for status in (
            "in_progress_agent", "in_progress_uncommitted", "implementation_detected", "implementation_tested",
            "implementation_claimed_uncommitted", "implementation_claimed_unverified", "locally_complete_uncommitted",
            "locally_complete_unpushed", "local_verified_pending_remote", "remote_commit_detected", "review_in_progress",
            "ci_passed_pending_merge", "merged_pending_deploy",
        )
    )
    project_state = "attention" if attention else ("active" if active else "quiet")

    summary = dict(local_fusion.get("summary") or {})
    summary["remote_event_count"] = len(remote_events); summary["unlinked_remote_event_count"] = len(unlinked)
    summary["remote_repository_count"] = len({str(event.get("repository_id")) for event in remote_events if event.get("repository_id")})
    summary["status_counts"] = dict(status_counts); summary["completed_work_item_count"] = status_counts.get("completed", 0)

    result.update({
        "version": 3, "scope": "cross_workspace_with_remote_devops", "project_state": project_state,
        "project_state_label": {"attention": "需要关注", "active": "多人协作开发中", "quiet": "暂无明显开发活动"}[project_state],
        "formal_completion_supported": True,
        "formal_completion_reason": "任务只有在关联到工程实现、验证和项目可见的远端稳定证据后才判定正式完成。",
        "summary": summary, "work_items": work_items, "unlinked_evidence": existing_unlinked,
    })
    return upgrade_fusion_result(result, remote_events)
