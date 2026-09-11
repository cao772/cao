from __future__ import annotations

import re
from collections import Counter
from typing import Any

CATEGORY_VALUES = {
    "task",
    "issue",
    "completion_record",
    "implementation_note",
    "test_evidence",
    "decision",
    "informational",
    "unknown",
}

INTERNAL_STATUS_LABELS = {
    "candidate": "候选",
    "planned": "待开发",
    "in_progress": "开发中",
    "blocked": "阻塞",
    "implementation_done": "实现完成，待验证",
    "testing": "验证中",
    "awaiting_merge": "待合并/远端确认",
    "completed": "已确认完成",
    "cancelled": "已取消",
    "unknown": "证据不足",
}

COMPLETION_MARKERS = (
    "已完成", "已实现", "已上线", "已部署", "已修复", "已解决", "完成开发", "开发完成",
    "实现完成", "修复完成", "完成了", "done", "completed", "implemented", "deployed", "fixed",
)
TEST_MARKERS = (
    "测试", "验证", "回归", "用例", "通过", "不通过", "未通过", "passed", "failed", "test", "ci",
)
DECISION_MARKERS = (
    "决定", "决策", "确定采用", "最终采用", "方案确定", "结论为", "同意采用", "不采用",
)
IMPLEMENTATION_NOTE_MARKERS = (
    "实现说明", "技术实现", "实现逻辑", "代码说明", "实现方式", "技术方案说明", "实现细节",
)
ISSUE_MARKERS = (
    "存在问题", "出现问题", "异常", "无法", "报错", "错误", "重复嵌入", "缺失", "失败",
    "bug", "issue", "error",
)
TASK_MARKERS = (
    "待开发", "待实现", "待修复", "待优化", "待调整", "待改造", "待完成", "计划",
    "需要", "需", "新增", "优化", "调整", "改造", "修复", "开发", "实现", "支持",
    "add", "fix", "implement", "optimize", "update", "refactor",
)
ACTIVE_MARKERS = ("正在", "开发中", "处理中", "进行中", "working", "in progress")
CANCEL_MARKERS = ("已取消", "取消任务", "不再实施", "终止", "cancelled", "canceled")
NEGATIVE_TEST_MARKERS = ("失败", "不通过", "未通过", "failed", "failure", "error")
POSITIVE_TEST_MARKERS = ("通过", "pass", "passed", "成功", "ok")

RELATION_BY_KIND = {
    "requirement": "requirement",
    "task": "requirement",
    "progress": "progress",
    "completion": "completion",
    "finished": "agent_finished",
    "started": "agent_started",
    "test": "test",
    "blocker": "blocker",
    "code_change": "implementation",
    "remote_commit": "commit",
    "review_open": "merge_request",
    "review_closed": "merge_request",
    "merged": "merge_request",
    "ci_passed": "ci",
    "ci_failed": "ci",
    "ci_running": "ci",
    "deployment": "deployment",
    "deployment_succeeded": "deployment",
    "deployment_failed": "deployment",
}

COMPAT_TO_INTERNAL = {
    "planned": "planned",
    "unknown": "unknown",
    "in_progress_agent": "in_progress",
    "in_progress_uncommitted": "in_progress",
    "implemented_local_commit_unpushed": "in_progress",
    "implementation_detected": "in_progress",
    "agent_claim_only": "implementation_done",
    "implementation_claimed_uncommitted": "implementation_done",
    "implementation_claimed_unverified": "implementation_done",
    "implementation_tested": "implementation_done",
    "locally_complete_uncommitted": "implementation_done",
    "locally_complete_unpushed": "implementation_done",
    "local_verified_pending_remote": "implementation_done",
    "review_in_progress": "awaiting_merge",
    "remote_commit_detected": "awaiting_merge",
    "ci_passed_pending_merge": "awaiting_merge",
    "merged_pending_deploy": "awaiting_merge",
    "test_failing": "blocked",
    "blocked": "blocked",
    "remote_ci_failed": "blocked",
    "deployment_failed": "blocked",
    "completed": "completed",
}

COMPAT_STATUS_PRIORITY = {
    "completed": 100,
    "deployment_failed": 95,
    "remote_ci_failed": 94,
    "blocked": 93,
    "test_failing": 92,
    "merged_pending_deploy": 82,
    "ci_passed_pending_merge": 80,
    "review_in_progress": 78,
    "remote_commit_detected": 76,
    "local_verified_pending_remote": 70,
    "locally_complete_unpushed": 68,
    "locally_complete_uncommitted": 66,
    "implementation_tested": 64,
    "implementation_claimed_unverified": 60,
    "implementation_claimed_uncommitted": 58,
    "agent_claim_only": 55,
    "implemented_local_commit_unpushed": 52,
    "implementation_detected": 50,
    "in_progress_agent": 45,
    "in_progress_uncommitted": 44,
    "planned": 20,
    "unknown": 0,
}


def _lower(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def classify_candidate(text: Any, *, hint: str | None = None) -> str:
    value = _lower(text)
    if not value:
        return "unknown"

    if any(marker in value for marker in CANCEL_MARKERS):
        return "completion_record"

    # Test phrases are evidence even when they also contain "完成/通过".
    if any(marker in value for marker in TEST_MARKERS):
        if any(marker in value for marker in ("测试", "验证", "回归", "用例", "passed", "failed", "test", "ci")):
            return "test_evidence"

    if any(marker in value for marker in DECISION_MARKERS):
        return "decision"
    if any(marker in value for marker in IMPLEMENTATION_NOTE_MARKERS):
        return "implementation_note"
    if any(marker in value for marker in COMPLETION_MARKERS):
        return "completion_record"

    # Issue detection precedes generic task markers: "当前页面出现重复嵌入" is an issue.
    if any(marker in value for marker in ISSUE_MARKERS):
        if not value.startswith(("修复", "fix ", "解决", "处理")):
            return "issue"

    if any(marker in value for marker in ACTIVE_MARKERS):
        return "task"
    if any(marker in value for marker in TASK_MARKERS):
        return "task"

    if hint in {"requirement", "task"}:
        return "task"
    if hint == "blocker":
        return "issue"
    if hint == "test":
        return "test_evidence"
    if hint == "decision":
        return "decision"
    if hint == "progress":
        return "task"

    if any(marker in value for marker in ("说明", "背景", "现状", "情况", "备注", "参考")):
        return "informational"
    return "unknown"


def relation_for_evidence(entry: dict[str, Any]) -> str:
    relation = str(entry.get("relation") or "").strip()
    if relation:
        return relation
    kind = str(entry.get("kind") or "").strip()
    if kind in RELATION_BY_KIND:
        return RELATION_BY_KIND[kind]
    category = classify_candidate(entry.get("text"), hint=kind or None)
    return {
        "task": "requirement",
        "issue": "blocker",
        "completion_record": "completion",
        "implementation_note": "implementation",
        "test_evidence": "test",
        "decision": "decision",
        "informational": "information",
        "unknown": "information",
    }[category]


def test_outcome(text: Any) -> str | None:
    value = _lower(text)
    if any(marker in value for marker in NEGATIVE_TEST_MARKERS):
        return "failed"
    if any(marker in value for marker in POSITIVE_TEST_MARKERS):
        return "passed"
    return None


def choose_compat_status(statuses: list[Any]) -> str:
    values = [str(status or "unknown") for status in statuses]
    return max(values or ["unknown"], key=lambda status: COMPAT_STATUS_PRIORITY.get(status, 1))


def derive_task_lifecycle(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence") or []
    compat_status = str(item.get("status") or "unknown")
    internal = COMPAT_TO_INTERNAL.get(compat_status, "unknown")

    relations = Counter(relation_for_evidence(entry) for entry in evidence)
    texts = [str(entry.get("text") or "") for entry in evidence]
    cancelled = any(any(marker in _lower(text) for marker in CANCEL_MARKERS) for text in texts)
    completion_claimed = bool(
        relations["completion"]
        or relations["agent_finished"]
        or any(classify_candidate(text) == "completion_record" for text in texts)
    )
    formal_completion = compat_status == "completed"

    outcomes = [test_outcome(text) for text in texts if relation_for_evidence({"text": text}) == "test"]
    has_failed_test = "failed" in outcomes
    has_passed_test = "passed" in outcomes

    if cancelled and not formal_completion:
        internal = "cancelled"
    elif formal_completion:
        internal = "completed"
    elif compat_status in {"blocked", "test_failing", "remote_ci_failed", "deployment_failed"} or has_failed_test:
        internal = "blocked"
    elif compat_status in {"review_in_progress", "remote_commit_detected", "ci_passed_pending_merge", "merged_pending_deploy"}:
        internal = "awaiting_merge"
    elif compat_status in {
        "agent_claim_only", "implementation_claimed_uncommitted", "implementation_claimed_unverified",
        "implementation_tested", "locally_complete_uncommitted", "locally_complete_unpushed",
        "local_verified_pending_remote",
    }:
        internal = "implementation_done"
    elif has_passed_test and compat_status not in {"planned", "unknown"}:
        internal = "implementation_done"
    elif completion_claimed and internal in {"planned", "unknown"}:
        # A completion statement is a lifecycle signal, not formal completion.
        internal = "implementation_done"

    flags: list[str] = []
    engineering_relations = {"implementation", "commit", "merge_request", "ci", "deployment", "test"}
    has_engineering_evidence = any(relations[name] for name in engineering_relations)
    if completion_claimed and not has_engineering_evidence and not formal_completion:
        flags.append("completed_claim_without_evidence")
    if internal == "planned" and not any(
        relations[name]
        for name in ("progress", "implementation", "commit", "merge_request", "ci", "deployment", "agent_started", "agent_progress")
    ):
        flags.append("task_without_activity")
    if cancelled and any(
        relations[name]
        for name in ("progress", "implementation", "commit", "merge_request", "ci", "deployment")
    ):
        flags.append("conflicting_task_state")

    return {
        "task_status": internal,
        "task_status_label": INTERNAL_STATUS_LABELS.get(internal, internal),
        "completion_claimed": completion_claimed,
        "formal_completion": formal_completion,
        "flags": flags,
    }
