from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any


NEGATIVE_TEST_MARKERS = ("失败", "不通过", "未通过", "failed", "failure", "error", "异常")
POSITIVE_TEST_MARKERS = ("通过", "pass", "passed", "成功", "ok")
BLOCKER_MARKERS = ("阻塞", "blocker", "无法", "卡住", "失败", "异常")
GENERIC_TERMS = {
    "项目", "功能", "开发", "任务", "测试", "问题", "修改", "优化", "支持", "实现",
    "当前", "相关", "系统", "代码", "页面", "接口", "进行", "完成",
}

STATUS_LABELS = {
    "blocked": "阻塞",
    "test_failing": "测试未通过",
    "locally_complete_uncommitted": "本地验证通过，尚未提交",
    "locally_complete_unpushed": "本地验证通过，已有本地提交但尚未推送",
    "local_verified_pending_remote": "本地验证通过，待远端复核",
    "implementation_claimed_uncommitted": "Agent称已完成，本地仍有未提交修改",
    "implementation_claimed_unverified": "Agent称已完成，尚缺测试证据",
    "agent_claim_only": "仅有Agent完成声明",
    "implementation_tested": "已检测到实现及通过测试",
    "in_progress_uncommitted": "开发中，本地有未提交修改",
    "implemented_local_commit_unpushed": "已检测到本地提交，尚未推送",
    "implementation_detected": "已检测到代码实现证据",
    "in_progress_agent": "Agent正在执行",
    "planned": "待开发",
    "unknown": "证据不足",
}


def _compact(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _normalized(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "").lower())


def _terms(value: Any) -> set[str]:
    text = _compact(value, 2000).lower()
    result: set[str] = set()
    for token in re.findall(r"[a-z0-9_]{2,}", text):
        if token not in GENERIC_TERMS:
            result.add(token)
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if chunk not in GENERIC_TERMS:
            result.add(chunk)
        if len(chunk) >= 4:
            for size in (2, 3, 4):
                for index in range(0, len(chunk) - size + 1):
                    gram = chunk[index:index + size]
                    if gram not in GENERIC_TERMS:
                        result.add(gram)
    return result


def similarity(left: Any, right: Any) -> float:
    a = _normalized(left)
    b = _normalized(right)
    if not a or not b:
        return 0.0
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        shorter = min(len(a), len(b))
        longer = max(len(a), len(b))
        return max(0.72, shorter / longer)
    left_terms = _terms(left)
    right_terms = _terms(right)
    if not left_terms or not right_terms:
        return 0.0
    intersection = len(left_terms & right_terms)
    union = len(left_terms | right_terms)
    return intersection / union if union else 0.0


def _stable_id(prefix: str, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _test_outcome(text: str) -> str | None:
    lower = text.lower()
    if any(marker in lower for marker in NEGATIVE_TEST_MARKERS):
        return "failed"
    if any(marker in lower for marker in POSITIVE_TEST_MARKERS):
        return "passed"
    return None


def _event_kind(event_type: str) -> str:
    lower = event_type.lower()
    if "finished" in lower or "completed" in lower or lower.endswith(".done"):
        return "finished"
    if "started" in lower or "start" in lower:
        return "started"
    if "progress" in lower or "working" in lower:
        return "progress"
    if "test" in lower:
        return "test"
    if "block" in lower or "error" in lower or "fail" in lower:
        return "blocker"
    return "other"


def _agent_event_text(event: dict[str, Any]) -> str:
    data = event.get("data") or {}
    values = [
        event.get("task_title"),
        data.get("summary"),
        data.get("message"),
        data.get("result"),
        data.get("status"),
        data.get("blocker"),
    ]
    return " ".join(_compact(value, 300) for value in values if value)


def _make_evidence(source: str, kind: str, text: str, **extra: Any) -> dict[str, Any]:
    result = {
        "source": source,
        "kind": kind,
        "text": _compact(text, 800),
    }
    result.update({key: value for key, value in extra.items() if value is not None})
    return result


def _candidate_work_items(memory: dict[str, Any], agent_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for fact_type, key in (("requirement", "requirements"), ("task", "tasks")):
        for fact in memory.get(key) or []:
            text = _compact(fact.get("text"), 700)
            if not text:
                continue
            normalized = _normalized(text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(
                {
                    "work_item_id": _stable_id("DOC", f"{fact_type}:{text}"),
                    "title": text,
                    "origin": "document",
                    "origin_type": fact_type,
                    "task_id": None,
                    "evidence": [
                        _make_evidence(
                            "document",
                            fact_type,
                            text,
                            path=fact.get("path"),
                            role=fact.get("role"),
                        )
                    ],
                }
            )

    for event in agent_events:
        task_id = _compact(event.get("task_id"), 120)
        title = _compact(event.get("task_title"), 700)
        if not task_id and not title:
            continue
        existing = None
        if task_id:
            existing = next((item for item in candidates if item.get("task_id") == task_id), None)
        if existing is None and title:
            best = max(
                ((similarity(title, item["title"]), item) for item in candidates),
                key=lambda pair: pair[0],
                default=(0.0, None),
            )
            if best[0] >= 0.62:
                existing = best[1]
        if existing is not None:
            if task_id and not existing.get("task_id"):
                existing["task_id"] = task_id
            continue

        identity = task_id or title
        normalized = _normalized(identity)
        if normalized and normalized in seen:
            continue
        if normalized:
            seen.add(normalized)
        candidates.append(
            {
                "work_item_id": task_id or _stable_id("AGENT", title),
                "title": title or task_id,
                "origin": "agent",
                "origin_type": "task",
                "task_id": task_id or None,
                "evidence": [],
            }
        )

    return candidates[:300]


def _best_work_item(text: str, work_items: list[dict[str, Any]], threshold: float) -> tuple[dict[str, Any] | None, float]:
    if not text or not work_items:
        return None, 0.0
    best_score = 0.0
    best_item = None
    for item in work_items:
        score = similarity(text, item.get("title"))
        if score > best_score:
            best_score = score
            best_item = item
    return (best_item, best_score) if best_score >= threshold else (None, best_score)


def _attach_agent_events(work_items: list[dict[str, Any]], agent_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unlinked: list[dict[str, Any]] = []
    for event in agent_events:
        task_id = _compact(event.get("task_id"), 120)
        target = next((item for item in work_items if task_id and item.get("task_id") == task_id), None)
        score = 1.0 if target is not None else 0.0
        if target is None:
            target, score = _best_work_item(_agent_event_text(event), work_items, 0.48)
        evidence = _make_evidence(
            "agent",
            _event_kind(str(event.get("event_type") or "")),
            _agent_event_text(event) or str(event.get("event_type") or "agent event"),
            event_type=event.get("event_type"),
            observed_at=event.get("observed_at"),
            user_id=event.get("user_id"),
            agent=event.get("agent"),
            session_id=event.get("session_id"),
            task_id=task_id or None,
            match_score=round(score, 3),
        )
        if target is None:
            unlinked.append(evidence)
        else:
            target["evidence"].append(evidence)
    return unlinked


def _attach_code_changes(work_items: list[dict[str, Any]], git_change_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    unlinked: list[dict[str, Any]] = []
    for item in git_change_analysis.get("items") or []:
        if not isinstance(item, dict) or item.get("status") != "analyzed":
            continue
        analysis = item.get("analysis") or {}
        text_parts = [
            analysis.get("summary"),
            " ".join(str(value) for value in (analysis.get("business_capabilities") or [])),
            item.get("path"),
        ]
        candidate_text = " ".join(_compact(value, 800) for value in text_parts if value)
        target, score = _best_work_item(candidate_text, work_items, 0.36)
        evidence = _make_evidence(
            "git_local",
            "code_change",
            analysis.get("summary") or item.get("path") or "code change",
            path=item.get("path"),
            additions=item.get("additions"),
            deletions=item.get("deletions"),
            change_area=analysis.get("change_area"),
            risks=analysis.get("risks") or [],
            match_score=round(score, 3),
        )
        if target is None:
            unlinked.append(evidence)
        else:
            target["evidence"].append(evidence)
    return unlinked


def _attach_memory_facts(
    work_items: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    source_kind: str,
    threshold: float,
) -> list[dict[str, Any]]:
    unlinked: list[dict[str, Any]] = []
    for fact in facts:
        text = _compact(fact.get("text"), 700)
        if not text:
            continue
        target, score = _best_work_item(text, work_items, threshold)
        evidence = _make_evidence(
            "document",
            source_kind,
            text,
            path=fact.get("path"),
            role=fact.get("role"),
            match_score=round(score, 3),
        )
        if target is None:
            unlinked.append(evidence)
        else:
            target["evidence"].append(evidence)
    return unlinked


def _derive_status(item: dict[str, Any], git_state: dict[str, Any]) -> tuple[str, list[str]]:
    evidence = item.get("evidence") or []
    kinds = Counter(str(entry.get("kind") or "") for entry in evidence)
    agent_finished = kinds["finished"] > 0
    agent_active = kinds["started"] > 0 or kinds["progress"] > 0
    code_present = kinds["code_change"] > 0
    blocker_present = kinds["blocker"] > 0

    test_outcomes = [_test_outcome(str(entry.get("text") or "")) for entry in evidence if entry.get("kind") == "test"]
    test_failed = "failed" in test_outcomes
    test_passed = "passed" in test_outcomes and not test_failed

    dirty = bool(git_state.get("dirty"))
    ahead = git_state.get("ahead")
    upstream = git_state.get("upstream")

    reasons: list[str] = []
    if blocker_present:
        reasons.append("存在与该事项关联的阻塞证据")
        return "blocked", reasons
    if test_failed:
        reasons.append("存在失败/不通过测试证据")
        return "test_failing", reasons

    if agent_finished and code_present and test_passed:
        reasons.extend(["Agent已声明完成", "检测到代码变更", "存在通过测试证据"])
        if dirty:
            reasons.append("当前工作区仍有未提交修改")
            return "locally_complete_uncommitted", reasons
        if isinstance(ahead, int) and ahead > 0:
            reasons.append("本地分支领先上游，尚有未推送提交")
            return "locally_complete_unpushed", reasons
        reasons.append("尚未接入PR/MR/CI远端证据，不判定正式完成")
        return "local_verified_pending_remote", reasons

    if agent_finished and code_present:
        reasons.extend(["Agent已声明完成", "检测到代码变更"])
        if dirty:
            reasons.append("工作区仍有未提交修改")
            return "implementation_claimed_uncommitted", reasons
        reasons.append("缺少明确通过测试证据")
        return "implementation_claimed_unverified", reasons

    if agent_finished and not code_present:
        reasons.append("只有Agent完成声明，未关联到代码实现证据")
        return "agent_claim_only", reasons

    if code_present and test_passed:
        reasons.extend(["检测到代码变更", "存在通过测试证据"])
        return "implementation_tested", reasons

    if code_present:
        reasons.append("检测到代码变更")
        if dirty:
            reasons.append("当前工作区有未提交修改")
            return "in_progress_uncommitted", reasons
        if isinstance(ahead, int) and ahead > 0:
            reasons.append("本地分支领先上游")
            return "implemented_local_commit_unpushed", reasons
        return "implementation_detected", reasons

    if agent_active:
        reasons.append("Agent存在启动或进度事件")
        return "in_progress_agent", reasons

    if item.get("origin") in {"document", "agent"}:
        reasons.append("已有需求/任务定义，但未关联到实现证据")
        return "planned", reasons

    return "unknown", ["当前证据不足"]


def fuse_evidence(payload: dict[str, Any], agent_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Conservatively fuse local project evidence without inventing completion.

    This MVP intentionally treats local documents, local Git state, local tests and
    agent claims as separate evidence classes. A task is never marked formally
    completed because remote PR/MR/CI/deployment evidence is not connected yet.
    """
    agent_events = agent_events or []
    memory = ((payload.get("analysis") or {}).get("current_project_memory") or {})
    git_state = payload.get("git") or {}
    git_changes = payload.get("git_change_analysis") or {}

    work_items = _candidate_work_items(memory, agent_events)
    unlinked_agent = _attach_agent_events(work_items, agent_events)
    unlinked_code = _attach_code_changes(work_items, git_changes)
    unlinked_tests = _attach_memory_facts(work_items, memory.get("tests") or [], "test", 0.34)
    unlinked_blockers = _attach_memory_facts(work_items, memory.get("blockers") or [], "blocker", 0.34)

    status_counts: Counter[str] = Counter()
    for item in work_items:
        status, reasons = _derive_status(item, git_state)
        item["status"] = status
        item["status_label"] = STATUS_LABELS.get(status, status)
        item["status_reasons"] = reasons
        item["evidence_count"] = len(item.get("evidence") or [])
        item["evidence_sources"] = sorted({str(entry.get("source") or "") for entry in item.get("evidence") or [] if entry.get("source")})
        status_counts[status] += 1

    global_test_failures = [fact for fact in (memory.get("tests") or []) if _test_outcome(str(fact.get("text") or "")) == "failed"]
    global_blockers = list(memory.get("blockers") or [])

    active_statuses = {
        "blocked", "test_failing", "locally_complete_uncommitted", "locally_complete_unpushed",
        "implementation_claimed_uncommitted", "implementation_claimed_unverified",
        "implementation_tested", "in_progress_uncommitted", "implemented_local_commit_unpushed",
        "implementation_detected", "in_progress_agent",
    }
    attention = bool(global_blockers or global_test_failures or status_counts["blocked"] or status_counts["test_failing"])
    active = bool(git_state.get("dirty") or any(status_counts[status] for status in active_statuses))

    project_state = "attention" if attention else ("active" if active else "quiet")
    project_state_label = {
        "attention": "需要关注",
        "active": "开发活跃",
        "quiet": "暂无明显开发活动",
    }[project_state]

    return {
        "version": 1,
        "scope": "local_evidence_only",
        "project_state": project_state,
        "project_state_label": project_state_label,
        "formal_completion_supported": False,
        "formal_completion_reason": "尚未接入远端PR/MR、CI和部署证据，当前只判断本地开发状态。",
        "summary": {
            "work_item_count": len(work_items),
            "status_counts": dict(status_counts),
            "git_dirty": bool(git_state.get("dirty")),
            "git_ahead": git_state.get("ahead"),
            "git_behind": git_state.get("behind"),
            "agent_event_count": len(agent_events),
            "unlinked_code_change_count": len(unlinked_code),
            "unlinked_agent_event_count": len(unlinked_agent),
            "unlinked_test_count": len(unlinked_tests),
            "unlinked_blocker_count": len(unlinked_blockers),
            "global_test_failure_count": len(global_test_failures),
            "global_blocker_count": len(global_blockers),
        },
        "work_items": work_items,
        "unlinked_evidence": {
            "code_changes": unlinked_code[:100],
            "agent_events": unlinked_agent[:100],
            "tests": unlinked_tests[:100],
            "blockers": unlinked_blockers[:100],
        },
        "global_blockers": global_blockers[:50],
        "global_test_failures": global_test_failures[:50],
    }
