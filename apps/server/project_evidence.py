from __future__ import annotations

from collections import Counter
from typing import Any

from evidence_fusion import STATUS_LABELS, fuse_evidence, similarity


NEGATIVE_TEST_MARKERS = ("失败", "不通过", "未通过", "failed", "failure", "error", "异常")
POSITIVE_TEST_MARKERS = ("通过", "pass", "passed", "成功", "ok")


def _test_outcome(text: str) -> str | None:
    lower = str(text or "").lower()
    if any(marker in lower for marker in NEGATIVE_TEST_MARKERS):
        return "failed"
    if any(marker in lower for marker in POSITIVE_TEST_MARKERS):
        return "passed"
    return None


def _event_for_workspace(event: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    """Keep agent events attached to the developer who owns the workspace.

    Project-wide events without user_id are allowed, but normal Codex/TRAE/Hermes
    reporters are expected to include user_id so that events are not duplicated into
    every developer's local evidence set.
    """
    event_user = str(event.get("user_id") or "").strip()
    snapshot_user = str(snapshot.get("user_id") or "").strip()
    return not event_user or event_user == snapshot_user


def _workspace_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = snapshot.get("payload") or {}
    git = payload.get("git") or {}
    return {
        "snapshot_id": snapshot.get("id"),
        "user_id": snapshot.get("user_id"),
        "device_id": snapshot.get("device_id"),
        "workspace_name": snapshot.get("workspace_name"),
        "observed_at": snapshot.get("observed_at"),
        "received_at": snapshot.get("received_at"),
        "branch": git.get("branch"),
        "head": git.get("head"),
        "dirty": bool(git.get("dirty")),
        "ahead": git.get("ahead"),
        "behind": git.get("behind"),
    }


def _evidence_key(entry: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(entry.get("source") or ""),
        str(entry.get("kind") or ""),
        str(entry.get("text") or ""),
        str(entry.get("path") or ""),
        str(entry.get("user_id") or ""),
        str(entry.get("task_id") or ""),
        str(entry.get("workspace_name") or ""),
    )


def _find_global_item(local_item: dict[str, Any], global_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    task_id = str(local_item.get("task_id") or "").strip()
    if task_id:
        exact = next((item for item in global_items if str(item.get("task_id") or "").strip() == task_id), None)
        if exact is not None:
            return exact

    title = str(local_item.get("title") or "").strip()
    if not title:
        return None
    best_score = 0.0
    best_item = None
    for item in global_items:
        score = similarity(title, item.get("title"))
        if score > best_score:
            best_score = score
            best_item = item
    return best_item if best_score >= 0.62 else None


def _derive_global_status(item: dict[str, Any]) -> tuple[str, list[str]]:
    evidence = item.get("evidence") or []
    contributions = item.get("workspace_contributions") or []
    kinds = Counter(str(entry.get("kind") or "") for entry in evidence)

    blocker = kinds["blocker"] > 0
    agent_finished = kinds["finished"] > 0
    agent_active = kinds["started"] > 0 or kinds["progress"] > 0
    code_present = kinds["code_change"] > 0

    test_outcomes = [
        _test_outcome(str(entry.get("text") or ""))
        for entry in evidence
        if entry.get("kind") == "test"
    ]
    test_failed = "failed" in test_outcomes
    test_passed = "passed" in test_outcomes and not test_failed

    code_contributions = [
        contribution
        for contribution in contributions
        if "git_local" in (contribution.get("evidence_sources") or [])
        or contribution.get("local_status")
        in {
            "locally_complete_uncommitted",
            "locally_complete_unpushed",
            "local_verified_pending_remote",
            "implementation_claimed_uncommitted",
            "implementation_claimed_unverified",
            "implementation_tested",
            "in_progress_uncommitted",
            "implemented_local_commit_unpushed",
            "implementation_detected",
        }
    ]
    relevant = code_contributions or contributions
    dirty = any(bool(contribution.get("git_dirty")) for contribution in relevant)
    ahead = any(
        isinstance(contribution.get("git_ahead"), int) and int(contribution.get("git_ahead")) > 0
        for contribution in relevant
    )

    reasons: list[str] = []
    if blocker:
        return "blocked", ["至少一个工作区存在与该事项关联的阻塞证据"]
    if test_failed:
        return "test_failing", ["跨工作区证据中存在失败/不通过测试"]

    contributor_count = len({str(item.get("user_id") or "") for item in contributions if item.get("user_id")})
    if contributor_count > 1:
        reasons.append(f"该事项由{contributor_count}名开发人员提供证据")

    if agent_finished and code_present and test_passed:
        reasons.extend(["存在Agent完成声明", "检测到实现代码", "存在通过测试证据"])
        if dirty:
            reasons.append("至少一个相关工作区仍有未提交修改")
            return "locally_complete_uncommitted", reasons
        if ahead:
            reasons.append("至少一个相关工作区存在未推送本地提交")
            return "locally_complete_unpushed", reasons
        reasons.append("尚未接入PR/MR、CI和部署远端证据，不判定正式完成")
        return "local_verified_pending_remote", reasons

    if agent_finished and code_present:
        reasons.extend(["存在Agent完成声明", "检测到实现代码"])
        if dirty:
            reasons.append("至少一个相关工作区仍有未提交修改")
            return "implementation_claimed_uncommitted", reasons
        reasons.append("尚缺明确通过测试证据")
        return "implementation_claimed_unverified", reasons

    if agent_finished and not code_present:
        return "agent_claim_only", reasons + ["只有Agent完成声明，尚未关联实现代码"]

    if code_present and test_passed:
        reasons.extend(["检测到实现代码", "存在通过测试证据"])
        if dirty:
            reasons.append("至少一个相关工作区仍有未提交修改")
            return "in_progress_uncommitted", reasons
        if ahead:
            reasons.append("至少一个相关工作区存在未推送本地提交")
            return "implemented_local_commit_unpushed", reasons
        return "implementation_tested", reasons

    if code_present:
        reasons.append("检测到实现代码")
        if dirty:
            reasons.append("至少一个相关工作区有未提交修改")
            return "in_progress_uncommitted", reasons
        if ahead:
            reasons.append("至少一个相关工作区存在未推送本地提交")
            return "implemented_local_commit_unpushed", reasons
        return "implementation_detected", reasons

    if agent_active:
        return "in_progress_agent", reasons + ["至少一个Agent存在启动或进度事件"]

    return "planned", reasons + ["已有需求/任务定义，但尚未关联实现证据"]


def fuse_project_evidence(
    workspace_snapshots: list[dict[str, Any]],
    agent_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fuse task evidence across every developer's latest workspace for a project.

    Local evidence is first interpreted per workspace with the existing conservative
    evidence engine. Equivalent work items are then merged by explicit task_id or a
    high-confidence title match. This keeps attribution to each person/device while
    producing one project-level task state.
    """
    agent_events = agent_events or []
    global_items: list[dict[str, Any]] = []
    unlinked: dict[str, list[dict[str, Any]]] = {
        "code_changes": [],
        "agent_events": [],
        "tests": [],
        "blockers": [],
    }
    workspace_results: list[dict[str, Any]] = []
    global_blockers: list[dict[str, Any]] = []
    global_test_failures: list[dict[str, Any]] = []

    for snapshot in workspace_snapshots:
        payload = snapshot.get("payload") or {}
        workspace = _workspace_identity(snapshot)
        events = [event for event in agent_events if _event_for_workspace(event, snapshot)]
        local = fuse_evidence(payload, events)
        workspace_results.append(
            {
                "workspace": workspace,
                "project_state": local.get("project_state"),
                "summary": local.get("summary") or {},
            }
        )

        for local_item in local.get("work_items") or []:
            target = _find_global_item(local_item, global_items)
            if target is None:
                target = {
                    "work_item_id": local_item.get("task_id") or local_item.get("work_item_id"),
                    "task_id": local_item.get("task_id"),
                    "title": local_item.get("title"),
                    "origins": set(),
                    "evidence": [],
                    "workspace_contributions": [],
                    "_evidence_keys": set(),
                }
                global_items.append(target)
            elif not target.get("task_id") and local_item.get("task_id"):
                target["task_id"] = local_item.get("task_id")
                target["work_item_id"] = local_item.get("task_id")

            target["origins"].add(str(local_item.get("origin") or "unknown"))
            evidence_sources = sorted(
                {
                    str(entry.get("source") or "")
                    for entry in (local_item.get("evidence") or [])
                    if entry.get("source")
                }
            )
            target["workspace_contributions"].append(
                {
                    **workspace,
                    "local_status": local_item.get("status"),
                    "local_status_label": local_item.get("status_label"),
                    "evidence_count": local_item.get("evidence_count", 0),
                    "evidence_sources": evidence_sources,
                    "git_dirty": workspace.get("dirty"),
                    "git_ahead": workspace.get("ahead"),
                }
            )

            for entry in local_item.get("evidence") or []:
                enriched = dict(entry)
                enriched.setdefault("user_id", workspace.get("user_id"))
                enriched["device_id"] = workspace.get("device_id")
                enriched["workspace_name"] = workspace.get("workspace_name")
                enriched["snapshot_id"] = workspace.get("snapshot_id")
                key = _evidence_key(enriched)
                if key in target["_evidence_keys"]:
                    continue
                target["_evidence_keys"].add(key)
                target["evidence"].append(enriched)

        for kind in unlinked:
            for entry in ((local.get("unlinked_evidence") or {}).get(kind) or []):
                enriched = dict(entry)
                enriched.setdefault("user_id", workspace.get("user_id"))
                enriched["device_id"] = workspace.get("device_id")
                enriched["workspace_name"] = workspace.get("workspace_name")
                enriched["snapshot_id"] = workspace.get("snapshot_id")
                unlinked[kind].append(enriched)

        for entry in local.get("global_blockers") or []:
            enriched = dict(entry)
            enriched["user_id"] = workspace.get("user_id")
            enriched["workspace_name"] = workspace.get("workspace_name")
            global_blockers.append(enriched)
        for entry in local.get("global_test_failures") or []:
            enriched = dict(entry)
            enriched["user_id"] = workspace.get("user_id")
            enriched["workspace_name"] = workspace.get("workspace_name")
            global_test_failures.append(enriched)

    status_counts: Counter[str] = Counter()
    for item in global_items:
        item.pop("_evidence_keys", None)
        item["origins"] = sorted(item.get("origins") or [])
        status, reasons = _derive_global_status(item)
        item["status"] = status
        item["status_label"] = STATUS_LABELS.get(status, status)
        item["status_reasons"] = reasons
        item["evidence_count"] = len(item.get("evidence") or [])
        item["contributors"] = sorted(
            {
                str(contribution.get("user_id"))
                for contribution in item.get("workspace_contributions") or []
                if contribution.get("user_id")
            }
        )
        item["workspace_count"] = len(
            {
                (
                    contribution.get("user_id"),
                    contribution.get("device_id"),
                    contribution.get("workspace_name"),
                )
                for contribution in item.get("workspace_contributions") or []
            }
        )
        status_counts[status] += 1

    attention = bool(
        global_blockers
        or global_test_failures
        or status_counts["blocked"]
        or status_counts["test_failing"]
    )
    active_statuses = {
        "locally_complete_uncommitted",
        "locally_complete_unpushed",
        "local_verified_pending_remote",
        "implementation_claimed_uncommitted",
        "implementation_claimed_unverified",
        "implementation_tested",
        "in_progress_uncommitted",
        "implemented_local_commit_unpushed",
        "implementation_detected",
        "in_progress_agent",
    }
    active = any(status_counts[status] for status in active_statuses)
    project_state = "attention" if attention else ("active" if active else "quiet")

    return {
        "version": 2,
        "scope": "cross_workspace_local_evidence",
        "project_state": project_state,
        "project_state_label": {
            "attention": "需要关注",
            "active": "多人协作开发中",
            "quiet": "暂无明显开发活动",
        }[project_state],
        "formal_completion_supported": False,
        "formal_completion_reason": "已完成多人工作区本地证据融合，但尚未接入PR/MR、CI、Merge和部署证据。",
        "summary": {
            "workspace_count": len(workspace_snapshots),
            "contributor_count": len({str(item.get("user_id") or "") for item in workspace_snapshots if item.get("user_id")}),
            "work_item_count": len(global_items),
            "status_counts": dict(status_counts),
            "agent_event_count": len(agent_events),
            "unlinked_code_change_count": len(unlinked["code_changes"]),
            "unlinked_agent_event_count": len(unlinked["agent_events"]),
            "unlinked_test_count": len(unlinked["tests"]),
            "unlinked_blocker_count": len(unlinked["blockers"]),
            "global_test_failure_count": len(global_test_failures),
            "global_blocker_count": len(global_blockers),
        },
        "work_items": global_items,
        "workspace_results": workspace_results,
        "unlinked_evidence": {key: value[:200] for key, value in unlinked.items()},
        "global_blockers": global_blockers[:100],
        "global_test_failures": global_test_failures[:100],
    }
