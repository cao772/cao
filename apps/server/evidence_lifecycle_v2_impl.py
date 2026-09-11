from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from typing import Any


FORMAL_STATUS_LABELS = {
    "unknown": "证据不足",
    "planned": "待开发",
    "in_progress": "开发中",
    "blocked": "阻塞",
    "local_implementation": "待验证",
    "local_verified": "待提交",
    "awaiting_push": "待推送",
    "pushed": "已推送",
    "awaiting_review": "待评审",
    "ci_failed": "自动检查失败",
    "ci_passed": "自动检查通过",
    "awaiting_merge": "待合并",
    "merged": "已合并",
    "awaiting_deployment": "待部署",
    "deployment_failed": "部署失败",
    "completed": "已完成",
    "cancelled": "已取消",
    "evidence_conflict": "证据冲突",
}

COMPLETION_MARKERS = ("已完成", "完成", "finished", "completed", "done", "已交付", "已上线", "验收通过")
PENDING_MARKERS = ("未开始", "待开发", "planned", "todo", "尚未开始")
CANCELLED_MARKERS = ("已取消", "取消", "cancelled", "canceled")

NEGATIVE_RELATIONS = {"test_fail", "ci_failed", "deployment_failed", "blocker"}
REMOTE_RELATIONS = {
    "push", "mr_opened", "mr_closed", "mr_merged", "ci_passed", "ci_failed", "ci_running",
    "deployment_succeeded", "deployment_failed", "deployment_running",
}


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text}T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(entry: dict[str, Any]) -> str:
    return str(entry.get("text") or entry.get("summary") or "").strip()


def _contains(text: str, markers: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(marker.lower() in lower for marker in markers)


def _confidence(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("task_id") or entry.get("task_key") or "").strip()
    linked_by = str(entry.get("linked_by") or "").strip()
    if explicit or linked_by in {"task_or_semantic", "sha", "branch"}:
        return "high"
    score = entry.get("match_score")
    try:
        value = float(score)
    except (TypeError, ValueError):
        if entry.get("source") in {"document", "git_local"} and score is None:
            return "high"
        return "medium"
    if value >= 0.80:
        return "high"
    if value >= 0.55:
        return "medium"
    return "low"


def _relation(entry: dict[str, Any]) -> str:
    source = str(entry.get("source") or "").lower()
    kind = str(entry.get("kind") or "").lower()
    text = _text(entry).lower()

    if source == "remote_devops":
        return {
            "remote_commit": "push",
            "review_open": "mr_opened",
            "review_closed": "mr_closed",
            "merged": "mr_merged",
            "ci_passed": "ci_passed",
            "ci_failed": "ci_failed",
            "ci_running": "ci_running",
            "deployment_succeeded": "deployment_succeeded",
            "deployment_failed": "deployment_failed",
            "deployment": "deployment_running",
        }.get(kind, "remote_other")

    if source == "git_local" or kind == "code_change":
        return "local_change"
    if source == "agent":
        if kind == "finished":
            return "completion_claim"
        if kind in {"started", "progress"}:
            return "progress_claim"
        if kind == "blocker":
            return "blocker"
        if kind == "test":
            if any(marker in text for marker in ("失败", "不通过", "failed", "failure", "error", "异常")):
                return "test_fail"
            if any(marker in text for marker in ("通过", "passed", "pass", "success", "成功", "ok")):
                return "test_pass"
            return "test_unknown"

    if source == "document":
        if kind == "blocker":
            return "blocker"
        if kind == "test":
            if any(marker in text for marker in ("失败", "不通过", "failed", "failure", "error", "异常")):
                return "test_fail"
            if any(marker in text for marker in ("通过", "passed", "pass", "success", "成功", "ok")):
                return "test_pass"
            return "test_unknown"
        if kind in {"progress", "progress_claim", "completion_claim"}:
            if _contains(text, CANCELLED_MARKERS):
                return "cancelled"
            if _contains(text, COMPLETION_MARKERS):
                return "completion_claim"
            return "progress_claim"
        if _contains(text, CANCELLED_MARKERS):
            return "cancelled"
        if _contains(text, COMPLETION_MARKERS):
            return "completion_claim"
        if _contains(text, PENDING_MARKERS):
            return "planned_claim"
        if kind == "requirement":
            return "requirement"
        if kind == "task":
            return "task_definition"

    return kind or "other"


def _source_type(entry: dict[str, Any]) -> str:
    source = str(entry.get("source") or "").lower()
    relation = _relation(entry)
    if source == "remote_devops":
        if relation.startswith("ci_"):
            return "ci"
        if relation.startswith("mr_"):
            return "merge_request"
        if relation.startswith("deployment_"):
            return "deployment"
        return "git_remote"
    if source == "git_local":
        return "local_git"
    if source == "agent":
        return "agent"
    if source == "document":
        return "test" if relation.startswith("test_") else "document"
    return source or "unknown"


def _raw_identity(entry: dict[str, Any], relation: str) -> str:
    data = entry.get("data") or {}
    for key in ("pipeline_id", "deployment_id", "id", "iid"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return f"{key}:{value}"
    sha = str(entry.get("commit_sha") or "").strip()
    repo = str(entry.get("repository_id") or "").strip()
    branch = str(entry.get("branch") or data.get("ref") or data.get("source_branch") or "").strip()
    if sha:
        normalized_relation = "remote_update" if relation == "push" else relation
        return f"{repo}:{normalized_relation}:{sha}"
    if branch and relation in REMOTE_RELATIONS:
        return f"{repo}:{relation}:{branch}:{entry.get('observed_at') or ''}"
    basis = "|".join(
        [
            _source_type(entry),
            relation,
            _text(entry),
            str(entry.get("path") or ""),
            str(entry.get("task_id") or entry.get("task_key") or ""),
            str(entry.get("observed_at") or ""),
        ]
    )
    return hashlib.sha1(basis.encode("utf-8", errors="ignore")).hexdigest()


def normalize_evidence(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize evidence for adjudication without deleting collector history."""
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            continue
        relation = _relation(raw)
        source_type = _source_type(raw)
        identity = _raw_identity(raw, relation)
        key = (source_type, identity)
        if key in seen:
            continue
        seen.add(key)
        observed_at = raw.get("observed_at") or raw.get("source_date") or raw.get("document_date")
        normalized.append(
            {
                "evidence_id": raw.get("evidence_id") or f"ev-{hashlib.sha1((identity + str(index)).encode()).hexdigest()[:12]}",
                "source_type": source_type,
                "relation": relation,
                "observed_at": observed_at,
                "source_id": raw.get("source_id") or raw.get("client_event_id") or raw.get("snapshot_id"),
                "summary": _text(raw)[:800],
                "confidence": _confidence(raw),
                "positive": relation not in NEGATIVE_RELATIONS,
                "commit_sha": raw.get("commit_sha"),
                "branch": raw.get("branch"),
                "repository_id": raw.get("repository_id"),
                "actor": raw.get("user_id") or raw.get("actor"),
                "raw": raw,
                "_index": index,
                "_time": _parse_time(observed_at),
            }
        )
    return normalized


def _latest(entries: list[dict[str, Any]], relations: set[str]) -> dict[str, Any] | None:
    selected = [entry for entry in entries if entry.get("relation") in relations]
    if not selected:
        return None
    return max(selected, key=lambda entry: (entry.get("_time") or datetime.min.replace(tzinfo=timezone.utc), entry.get("_index", 0)))


def _latest_success_failure(
    entries: list[dict[str, Any]], success: str, failure: str, running: str | None = None,
) -> tuple[str, dict[str, Any] | None]:
    relations = {success, failure}
    if running:
        relations.add(running)
    latest = _latest(entries, relations)
    if latest is None:
        return "unknown", None
    relation = str(latest.get("relation") or "")
    if relation == success:
        return "passed", latest
    if relation == failure:
        return "failed", latest
    return "running", latest


def _document_status(entries: list[dict[str, Any]]) -> tuple[str, bool, bool]:
    document_entries = [entry for entry in entries if entry.get("source_type") == "document"]
    completion = any(entry.get("relation") == "completion_claim" for entry in document_entries)
    planned = any(entry.get("relation") in {"planned_claim", "requirement", "task_definition"} for entry in document_entries)
    cancelled = any(entry.get("relation") == "cancelled" for entry in document_entries)
    if cancelled:
        return "cancelled", completion, planned
    if completion:
        return "claimed_completed", completion, planned
    if planned:
        return "planned", completion, planned
    return "unknown", completion, planned


def _workspace_flags(item: dict[str, Any]) -> tuple[bool, bool]:
    contributions = item.get("workspace_contributions") or []
    dirty = any(bool(c.get("git_dirty")) for c in contributions if isinstance(c, dict))
    ahead = any(isinstance(c.get("git_ahead"), int) and int(c.get("git_ahead")) > 0 for c in contributions if isinstance(c, dict))
    status = str(item.get("status") or "")
    dirty = dirty or status in {"locally_complete_uncommitted", "in_progress_uncommitted", "implementation_claimed_uncommitted"}
    ahead = ahead or status in {"locally_complete_unpushed", "implemented_local_commit_unpushed"}
    return dirty, ahead


def _task_capabilities(entries: list[dict[str, Any]], project_capabilities: dict[str, bool]) -> dict[str, bool]:
    task_relations = {str(entry.get("relation") or "") for entry in entries}
    return {
        "remote_git": project_capabilities.get("remote_git", False) or "push" in task_relations,
        "review": project_capabilities.get("review", False) or bool({"mr_opened", "mr_closed", "mr_merged"} & task_relations),
        "ci": project_capabilities.get("ci", False) or bool({"ci_passed", "ci_failed", "ci_running"} & task_relations),
        "deployment": project_capabilities.get("deployment", False) or bool({"deployment_succeeded", "deployment_failed", "deployment_running"} & task_relations),
    }


def _formal_status(
    item: dict[str, Any], entries: list[dict[str, Any]], capabilities: dict[str, bool],
) -> tuple[str, str, str, list[str], list[str], list[dict[str, Any]]]:
    reasons: list[str] = []
    flags: list[str] = []
    conflicts: list[dict[str, Any]] = []

    business_status, document_completion, document_planned = _document_status(entries)
    agent_finished = any(e.get("source_type") == "agent" and e.get("relation") == "completion_claim" for e in entries)
    completion_claimed = document_completion or agent_finished
    code_present = any(e.get("relation") == "local_change" for e in entries)
    remote_update = _latest(entries, {"push"})
    implementation_present = code_present or remote_update is not None
    agent_active = any(e.get("source_type") == "agent" and e.get("relation") == "progress_claim" for e in entries)
    blocker = _latest(entries, {"blocker"})
    cancelled = any(e.get("relation") == "cancelled" for e in entries)
    dirty, ahead = _workspace_flags(item)

    test_state, latest_test = _latest_success_failure(entries, "test_pass", "test_fail")
    ci_state, latest_ci = _latest_success_failure(entries, "ci_passed", "ci_failed", "ci_running")
    deploy_state, latest_deploy = _latest_success_failure(entries, "deployment_succeeded", "deployment_failed", "deployment_running")
    latest_review = _latest(entries, {"mr_opened", "mr_closed", "mr_merged"})
    merged = latest_review is not None and latest_review.get("relation") == "mr_merged"
    review_open = latest_review is not None and latest_review.get("relation") == "mr_opened"

    high_medium_test_pass = test_state == "passed" and latest_test is not None and latest_test.get("confidence") in {"high", "medium"}
    low_test_fail = test_state == "failed" and latest_test is not None and latest_test.get("confidence") == "low"
    validation_passed = ci_state == "passed" or high_medium_test_pass

    if agent_finished and not implementation_present:
        flags.append("agent_finished_without_code")
    if completion_claimed and not implementation_present:
        flags.append("completed_claim_without_engineering_evidence")
        conflicts.append({
            "type": "completion_claim_without_engineering_evidence", "severity": "medium",
            "message": "存在完成声明，但尚未发现关联实现证据。",
            "evidence_ids": [e["evidence_id"] for e in entries if e.get("relation") == "completion_claim"],
        })
    if document_planned and implementation_present:
        flags.append("document_may_be_outdated")
    if ci_state == "failed":
        flags.append("ci_failed")
        if completion_claimed:
            flags.append("completion_claim_conflicts_with_ci")
            conflicts.append({
                "type": "completion_claim_conflicts_with_ci", "severity": "high",
                "message": "完成声明与当前最新 CI 失败证据冲突。",
                "evidence_ids": [e["evidence_id"] for e in (latest_ci,) if e],
            })
        if test_state == "passed":
            flags.append("local_remote_verification_conflict")
            conflicts.append({
                "type": "local_remote_verification_conflict", "severity": "high",
                "message": "本地测试通过，但当前最新远端 CI 失败。",
                "evidence_ids": [e["evidence_id"] for e in (latest_test, latest_ci) if e],
            })
    if deploy_state == "failed":
        flags.append("deployment_failed")
    if low_test_fail:
        flags.append("unlinked_failure")
    if dirty and validation_passed:
        flags.append("local_verified_uncommitted")
    if ahead:
        flags.append("committed_unpushed")
    if remote_update is not None and not validation_passed:
        flags.append("pushed_without_test")
    if conflicts:
        flags.append("conflicting_evidence")

    if cancelled:
        formal_status = "cancelled"; engineering_status = "cancelled"; reasons.append("当前资料证据显示任务已取消")
    elif blocker is not None and blocker.get("confidence") in {"high", "medium"}:
        formal_status = "blocked"; engineering_status = "blocked"; reasons.append("存在当前关联阻塞证据")
    elif deploy_state == "failed":
        formal_status = "deployment_failed"; engineering_status = "deployment_failed"; reasons.append("最新部署证据为失败")
    elif ci_state == "failed":
        formal_status = "ci_failed"; engineering_status = "ci_failed"; reasons.append("最新远端 CI 证据为失败")
    elif test_state == "failed" and latest_test is not None and latest_test.get("confidence") in {"high", "medium"}:
        formal_status = "blocked"; engineering_status = "test_failed"; reasons.append("最新高/中置信测试证据为失败")
    elif capabilities.get("deployment") and merged and deploy_state != "passed":
        formal_status = "awaiting_deployment"; engineering_status = "merged"; reasons.append("代码已合并，项目存在部署链路，但尚未出现最新部署成功证据")
    elif capabilities.get("deployment") and deploy_state == "passed" and implementation_present and validation_passed:
        formal_status = "completed"; engineering_status = "deployed"; reasons.append("实现、验证和部署成功证据链已闭合")
    elif capabilities.get("review") and merged:
        if validation_passed:
            formal_status = "completed" if not capabilities.get("deployment") else "awaiting_deployment"
            engineering_status = "merged"; reasons.append("代码已合并且验证通过")
        else:
            formal_status = "merged"; engineering_status = "merged"; reasons.append("代码已合并，但尚缺当前成功验证证据")
    elif capabilities.get("review") and ci_state == "passed":
        formal_status = "awaiting_merge"; engineering_status = "ci_passed"; reasons.append("远端 CI 已通过，尚未发现合并证据")
    elif review_open:
        formal_status = "awaiting_review"; engineering_status = "awaiting_review"; reasons.append("PR/MR 已打开，等待评审/合并")
    elif remote_update is not None:
        if validation_passed and not capabilities.get("review") and not capabilities.get("deployment"):
            formal_status = "completed"; engineering_status = "remotely_verified"; reasons.append("该项目未发现 MR/部署能力，推送与成功验证证据满足工程完成条件")
        else:
            formal_status = "pushed"; engineering_status = "pushed"; reasons.append("已发现远端提交/推送证据")
    elif ahead:
        formal_status = "awaiting_push"; engineering_status = "committed_unpushed"; reasons.append("存在本地提交领先上游，待推送")
    elif validation_passed and implementation_present:
        formal_status = "local_verified"; engineering_status = "local_verified"; reasons.append("实现与成功验证证据已存在，但尚无远端稳定证据")
    elif implementation_present:
        formal_status = "local_implementation"; engineering_status = "implementation_detected"; reasons.append("已发现实现证据，尚待验证")
    elif agent_active:
        formal_status = "in_progress"; engineering_status = "in_progress"; reasons.append("Agent 存在当前开发进度证据")
    elif completion_claimed:
        formal_status = "evidence_conflict" if conflicts else "planned"; engineering_status = "no_implementation_evidence"; reasons.append("仅存在完成声明，尚不能确认工程完成")
    elif business_status == "planned" or item.get("origin") in {"document", "agent"}:
        formal_status = "planned"; engineering_status = "planned"; reasons.append("任务已定义，但尚未发现实现证据")
    else:
        formal_status = "unknown"; engineering_status = "unknown"; reasons.append("当前证据不足")

    if formal_status not in {"ci_failed", "deployment_failed", "blocked"} and conflicts and not implementation_present:
        formal_status = "evidence_conflict"
    return formal_status, business_status, engineering_status, reasons, sorted(set(flags)), conflicts


def _completion_level(formal_status: str, entries: list[dict[str, Any]], completion_claimed: bool) -> str:
    if formal_status == "completed":
        if _latest(entries, {"deployment_succeeded"}) is not None:
            return "deployed"
        if _latest(entries, {"mr_merged"}) is not None:
            return "merged"
        return "remotely_verified"
    if formal_status in {"merged", "awaiting_deployment"}:
        return "merged"
    if formal_status in {"pushed", "awaiting_review", "ci_passed", "awaiting_merge"}:
        return "remotely_verified"
    if formal_status in {"local_verified", "awaiting_push"}:
        return "locally_verified"
    if completion_claimed:
        return "claimed"
    return "none"


def _trace(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(entries, key=lambda entry: (entry.get("_time") or datetime.min.replace(tzinfo=timezone.utc), entry.get("_index", 0)))
    return [{
        "evidence_id": entry.get("evidence_id"), "observed_at": entry.get("observed_at"),
        "source_type": entry.get("source_type"), "relation": entry.get("relation"),
        "summary": entry.get("summary"), "confidence": entry.get("confidence"),
        "positive": entry.get("positive"), "commit_sha": entry.get("commit_sha"),
        "branch": entry.get("branch"), "actor": entry.get("actor"),
    } for entry in ordered]


def infer_project_capabilities(remote_events: list[dict[str, Any]]) -> dict[str, bool]:
    event_types = [str(event.get("event_type") or "").lower().replace("-", "_") for event in remote_events]
    return {
        "remote_git": any("push" in value or "commit" in value for value in event_types),
        "review": any("merge_request" in value or "pull_request" in value or value.startswith("mr.") or value.startswith("pr.") for value in event_types),
        "ci": any("pipeline" in value or value.startswith("ci.") or value.startswith("ci_") for value in event_types),
        "deployment": any("deploy" in value for value in event_types),
    }


def upgrade_fusion_result(fusion: dict[str, Any], remote_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Add the V2 adjudication layer while keeping legacy status fields intact."""
    remote_events = remote_events or []
    result = dict(fusion)
    work_items = [dict(item) for item in (fusion.get("work_items") or [])]
    project_capabilities = infer_project_capabilities(remote_events)
    formal_counts: Counter[str] = Counter()
    all_conflicts: list[dict[str, Any]] = []
    attention_messages: list[str] = []

    for item in work_items:
        raw_evidence = [dict(entry) for entry in (item.get("evidence") or []) if isinstance(entry, dict)]
        normalized = normalize_evidence(raw_evidence)
        capabilities = _task_capabilities(normalized, project_capabilities)
        formal_status, business_status, engineering_status, reasons, flags, conflicts = _formal_status(item, normalized, capabilities)
        completion_claimed = business_status == "claimed_completed" or any(entry.get("relation") == "completion_claim" for entry in normalized)
        latest_at_entry = _latest(normalized, {str(entry.get("relation") or "") for entry in normalized}) if normalized else None
        task_key = item.get("task_key") or item.get("task_id") or item.get("work_item_id")
        item.update({
            "task_key": task_key,
            "formal_status": formal_status,
            "formal_status_label": FORMAL_STATUS_LABELS.get(formal_status, formal_status),
            "business_status": business_status,
            "engineering_status": engineering_status,
            "completion_claimed": bool(completion_claimed),
            "formal_completion": formal_status == "completed",
            "completion_level": _completion_level(formal_status, normalized, bool(completion_claimed)),
            "confidence": "high" if any(e.get("confidence") == "high" for e in normalized) else ("medium" if normalized else "low"),
            "reasons": reasons, "flags": flags, "conflicts": conflicts,
            "evidence_summary": {
                "raw_count": len(raw_evidence), "normalized_count": len(normalized),
                "source_counts": dict(Counter(str(e.get("source_type") or "unknown") for e in normalized)),
                "relation_counts": dict(Counter(str(e.get("relation") or "unknown") for e in normalized)),
                "capabilities": capabilities,
            },
            "evidence_ids": [e.get("evidence_id") for e in normalized],
            "evidence_trace": _trace(normalized),
            "latest_evidence_at": latest_at_entry.get("observed_at") if latest_at_entry else None,
        })
        formal_counts[formal_status] += 1
        for conflict in conflicts:
            enriched = dict(conflict); enriched.setdefault("task_key", task_key); all_conflicts.append(enriched)

    high_conflicts = sum(1 for conflict in all_conflicts if conflict.get("severity") == "high")
    failure_count = sum(formal_counts[status] for status in ("ci_failed", "deployment_failed", "blocked"))
    if formal_counts["ci_failed"]: attention_messages.append(f"{formal_counts['ci_failed']}个任务自动检查失败")
    if formal_counts["deployment_failed"]: attention_messages.append(f"{formal_counts['deployment_failed']}个任务部署失败")
    if formal_counts["blocked"]: attention_messages.append(f"{formal_counts['blocked']}个任务阻塞")
    claim_without_engineering = sum(1 for item in work_items if "completed_claim_without_engineering_evidence" in (item.get("flags") or []))
    if claim_without_engineering: attention_messages.append(f"{claim_without_engineering}个任务声称完成但缺少工程实现证据")
    if high_conflicts: attention_messages.append(f"{high_conflicts}个高严重度证据冲突")

    if failure_count or high_conflicts:
        project_state = "attention"; project_state_label = "需要关注"
    elif work_items and all(item.get("formal_completion") for item in work_items):
        project_state = "release_ready"; project_state_label = "工程状态已闭合"
    elif any(item.get("formal_status") not in {"planned", "unknown", "cancelled", "completed"} for item in work_items):
        project_state = "active"; project_state_label = "协作开发中"
    else:
        project_state = "normal"; project_state_label = "状态正常"

    summary = dict(fusion.get("summary") or {})
    summary["formal_status_counts"] = dict(formal_counts)
    summary["formal_completed_count"] = formal_counts["completed"]
    summary["evidence_conflict_count"] = len(all_conflicts)
    summary["high_conflict_count"] = high_conflicts
    summary["project_attention_required"] = bool(attention_messages)

    unlinked = dict(fusion.get("unlinked_evidence") or {})
    unlinked_failures = []
    for group in unlinked.values():
        if not isinstance(group, list):
            continue
        for entry in group:
            if isinstance(entry, dict) and _relation(entry) in NEGATIVE_RELATIONS:
                flagged = dict(entry); flagged["flag"] = "unlinked_failure"; unlinked_failures.append(flagged)
    if unlinked_failures:
        unlinked["failures"] = unlinked_failures[:200]
        attention_messages.append(f"{len(unlinked_failures)}条失败证据尚未可靠关联任务")
        summary["project_attention_required"] = True
        if project_state == "normal":
            project_state = "attention"; project_state_label = "需要关注"

    result.update({
        "version": max(int(fusion.get("version") or 0), 4),
        "fusion_version": "evidence-fusion-v2",
        "project_state": project_state,
        "project_state_label": project_state_label,
        "project_attention_required": bool(summary.get("project_attention_required")),
        "project_state_reasons": attention_messages,
        "capabilities": project_capabilities,
        "summary": summary, "work_items": work_items, "conflicts": all_conflicts,
        "unlinked_evidence": unlinked,
        "formal_completion_supported": True,
        "formal_completion_reason": "正式状态由实现、验证、远端稳定状态以及项目可见的MR/CI/部署能力共同判定；文档或Agent完成声明不能单独形成正式完成。",
    })
    return result
