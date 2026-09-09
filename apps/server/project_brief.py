from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any


NEGATIVE_MARKERS = ("失败", "不通过", "未通过", "异常", "错误", "failed", "failure", "error")
COMPLETE_MARKERS = ("已完成", "完成", "已通过", "通过", "已上线", "上线完成", "已交付", "验收通过")
METRIC_MARKERS = ("准确率", "覆盖率", "确认率", "通过率", "完成率", "成功率", "样本", "指标", "%")
ACTIVE_STATUSES = {
    "in_progress_agent",
    "in_progress_uncommitted",
    "implementation_detected",
    "implementation_tested",
    "implementation_claimed_uncommitted",
    "implementation_claimed_unverified",
    "implemented_local_commit_unpushed",
    "locally_complete_uncommitted",
    "locally_complete_unpushed",
    "local_verified_pending_remote",
    "remote_submitted",
    "review_pending",
    "ci_passed_pending_merge",
    "merged_pending_deployment",
}
ATTENTION_STATUSES = {"blocked", "test_failing", "ci_failed", "deployment_failed"}
DONE_STATUSES = {"completed"}
METRIC_LABELS = (
    "图像确认率", "定级覆盖率", "已定级准确率", "端到端准确率", "准确率", "覆盖率", "确认率",
    "通过率", "完成率", "成功率", "运行台账", "后端", "前端",
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


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("text") or value.get("title") or value.get("content") or ""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dedupe(values: list[Any], limit: int = 20) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _memory_objects(workspace_snapshots: list[dict[str, Any]], key: str) -> list[Any]:
    values: list[Any] = []
    for snapshot in workspace_snapshots:
        payload = snapshot.get("payload") or {}
        memory = ((payload.get("analysis") or {}).get("current_project_memory") or {})
        values.extend(memory.get(key) or [])
    return values


def _contains_negative(text: str) -> bool:
    lower = text.lower()
    if re.search(r"待测试|待验证|未执行|测试点|预期结果", lower):
        return False
    if re.search(r"\b[1-9]\d*\s+(?:failed|errors?)\b", lower):
        return True
    if re.search(r"\b\d+\s+passed\b", lower) and not re.search(r"仍有|尚有", lower):
        return False
    lower = re.sub(r"无失败|无超时|没有失败|失败回滚|失败反馈|错误处理|异常处理|定额错误|定额套用错误", "", lower)
    return any(marker in lower for marker in NEGATIVE_MARKERS)


def _is_pending(text: str) -> bool:
    return bool(re.search(r"尚未|未完成|未开始|待开发|待测试|待验证|待确认|待补齐|下一步|计划|拟|建议|需.*(?:确认|验证|回归|开发)", text))


def _completed_progress(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _text(value)
        lower = text.lower()
        if not text or _contains_negative(text) or _is_pending(text) or "进行中" in text:
            continue
        if any(marker in lower for marker in COMPLETE_MARKERS):
            result.append(text)
    return _dedupe(result, 12)


def _source_date(value: Any) -> date | None:
    if not isinstance(value, dict):
        return None
    raw = str(value.get("source_date") or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _metric_family(text: str) -> str:
    labels = [label for label in METRIC_LABELS if label in text]
    if labels:
        if "后端" in labels and re.search(r"passed|通过|测试", text, re.IGNORECASE):
            return "后端测试"
        if "前端" in labels and re.search(r"passed|通过|测试", text, re.IGNORECASE):
            return "前端测试"
        return "|".join(labels)
    normalized = re.sub(r"\d+(?:\.\d+)?%?|passed|failed|条|项|次", "", text, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized[:60] or text[:60]


def _metric_details(values: list[Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        text = _text(value)
        if not text or _is_pending(text):
            continue
        if not (any(marker in text for marker in METRIC_MARKERS) or re.search(r"\d+(?:\.\d+)?\s*%|\d+\s*(?:passed|条|项)", text, re.IGNORECASE)):
            continue
        source_date = _source_date(value)
        candidates.append(
            {
                "text": text,
                "source_date": source_date.isoformat() if source_date else None,
                "family": _metric_family(text),
                "_date": source_date or date.min,
                "_index": index,
            }
        )
    candidates.sort(key=lambda item: (item["_date"], item["_index"]), reverse=True)
    seen_families: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in candidates:
        family = item["family"]
        if family in seen_families:
            continue
        seen_families.add(family)
        result.append({key: value for key, value in item.items() if not key.startswith("_")})
        if len(result) >= 10:
            break
    return result


def _next_lines(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _text(value)
        if text and _is_pending(text):
            result.append(text)
    return _dedupe(result, 12)


def _work_items(fusion: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (fusion.get("work_items") or []) if isinstance(item, dict)]


def _remote_counts(remote_events: list[dict[str, Any]], now: datetime) -> dict[str, int]:
    week_start = now - timedelta(days=7)
    today = now.date()
    weekly_commits: set[str] = set()
    weekly_pushes = 0
    weekly_merges = 0
    weekly_ci_failed = 0
    today_activity = 0

    for event in remote_events:
        observed = _parse_time(event.get("observed_at"))
        if observed is None:
            continue
        if observed.date() == today:
            today_activity += 1
        if observed < week_start:
            continue
        event_type = str(event.get("event_type") or "")
        if event_type == "git.commit":
            identity = str(event.get("commit_sha") or event.get("client_event_id") or "")
            if identity:
                weekly_commits.add(identity)
        elif event_type == "git.push":
            weekly_pushes += 1
        elif event_type == "merge_request.merged":
            weekly_merges += 1
        elif event_type == "ci.failed":
            weekly_ci_failed += 1

    return {
        "today_activity_count": today_activity,
        "weekly_commit_count": len(weekly_commits),
        "weekly_push_count": weekly_pushes,
        "weekly_merge_count": weekly_merges,
        "weekly_ci_failure_count": weekly_ci_failed,
    }


def _week_key_from_date(value: date) -> tuple[str, date, date]:
    year, week, _ = value.isocalendar()
    start = value - timedelta(days=value.weekday())
    return f"{year}-W{week:02d}", start, start + timedelta(days=6)


def _build_weekly_progress(
    workspace_snapshots: list[dict[str, Any]],
    remote_events: list[dict[str, Any]],
    agent_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}

    def ensure(day: date) -> dict[str, Any]:
        key, start, end = _week_key_from_date(day)
        return groups.setdefault(
            key,
            {
                "week_key": key,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "completed": [],
                "tasks": [],
                "issues": [],
                "metrics": [],
                "commit_count": 0,
                "push_count": 0,
                "merge_count": 0,
                "ci_failure_count": 0,
                "agent_activity_count": 0,
            },
        )

    for snapshot in workspace_snapshots:
        memory = ((((snapshot.get("payload") or {}).get("analysis") or {}).get("current_project_memory") or {}))
        for week in memory.get("weekly_facts") or []:
            try:
                start = date.fromisoformat(str(week.get("start")))
            except (ValueError, TypeError):
                continue
            group = ensure(start)
            for fact in week.get("facts") or []:
                text = _text(fact)
                fact_type = str(fact.get("type") or "") if isinstance(fact, dict) else ""
                if not text:
                    continue
                if fact_type == "blocker" or (fact_type == "test" and _contains_negative(text)):
                    group["issues"].append(text)
                if fact_type in {"task", "requirement"} and _is_pending(text):
                    group["tasks"].append(text)
                if fact_type == "progress" and not _is_pending(text) and not _contains_negative(text) and any(marker in text.lower() for marker in COMPLETE_MARKERS):
                    group["completed"].append(text)
                if fact_type in {"progress", "test"} and (any(marker in text for marker in METRIC_MARKERS) or "%" in text):
                    group["metrics"].append(text)

    seen_week_commits: dict[str, set[str]] = defaultdict(set)
    for event in remote_events:
        observed = _parse_time(event.get("observed_at"))
        if observed is None:
            continue
        group = ensure(observed.date())
        event_type = str(event.get("event_type") or "")
        if event_type == "git.commit":
            identity = str(event.get("commit_sha") or event.get("client_event_id") or "")
            if identity and identity not in seen_week_commits[group["week_key"]]:
                seen_week_commits[group["week_key"]].add(identity)
                group["commit_count"] += 1
        elif event_type == "git.push":
            group["push_count"] += 1
        elif event_type == "merge_request.merged":
            group["merge_count"] += 1
        elif event_type == "ci.failed":
            group["ci_failure_count"] += 1

    for event in agent_events:
        observed = _parse_time(event.get("observed_at"))
        if observed is not None:
            ensure(observed.date())["agent_activity_count"] += 1

    result = sorted(groups.values(), key=lambda item: item["start"], reverse=True)
    for group in result:
        group["completed"] = _dedupe(group["completed"], 8)
        group["tasks"] = _dedupe(group["tasks"], 8)
        group["issues"] = _dedupe(group["issues"], 8)
        group["metrics"] = _dedupe(group["metrics"], 6)
    return result[:26]


def _infer_stage(
    *,
    active_count: int,
    blocker_count: int,
    tests: list[str],
    requirements: list[str],
    remote_counts: dict[str, int],
) -> str:
    if blocker_count and active_count:
        return "问题处理与联调"
    if active_count and (tests or remote_counts.get("weekly_merge_count") or remote_counts.get("weekly_push_count")):
        return "开发联调与验证"
    if active_count:
        return "功能开发"
    if tests:
        return "测试与验证"
    if requirements:
        return "需求梳理"
    if remote_counts.get("weekly_commit_count") or remote_counts.get("weekly_push_count"):
        return "持续迭代"
    return "尚未形成明确阶段"


def build_project_brief(
    workspace_snapshots: list[dict[str, Any]],
    fusion: dict[str, Any],
    remote_events: list[dict[str, Any]] | None = None,
    agent_events: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a business-facing current summary plus week-by-week history."""
    remote_events = remote_events or []
    agent_events = agent_events or []
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    progress = _memory_objects(workspace_snapshots, "progress")
    tasks_from_docs = _memory_objects(workspace_snapshots, "tasks")
    tests_objects = _memory_objects(workspace_snapshots, "tests")
    requirements_objects = _memory_objects(workspace_snapshots, "requirements")
    blockers_objects = _memory_objects(workspace_snapshots, "blockers")
    decisions_objects = _memory_objects(workspace_snapshots, "decisions")
    tests = _dedupe(tests_objects, 30)
    requirements = _dedupe(requirements_objects, 30)
    blockers = _dedupe(blockers_objects, 20)
    decisions = _dedupe(decisions_objects, 20)

    work_items = _work_items(fusion)
    active_items = [item for item in work_items if str(item.get("status") or "") in ACTIVE_STATUSES]
    attention_items = [item for item in work_items if str(item.get("status") or "") in ATTENTION_STATUSES]
    done_items = [item for item in work_items if str(item.get("status") or "") in DONE_STATUSES]
    planned_items = [item for item in work_items if str(item.get("status") or "") == "planned"]
    confirmed_planned = [
        item for item in planned_items
        if item.get("task_id") or str(item.get("origin") or "") == "agent"
    ]

    completed = _completed_progress(progress)
    completed.extend(_text(item.get("title") or item.get("task_id")) for item in done_items)
    completed = _dedupe(completed, 12)

    in_progress = [_text(item.get("title") or item.get("task_id")) for item in active_items]
    if not in_progress:
        in_progress = [_text(value) for value in tasks_from_docs + progress if "进行中" in _text(value) and not _is_pending(_text(value))]
    in_progress = _dedupe(in_progress, 12)

    issue_lines = list(blockers)
    issue_lines.extend(_text(item.get("title") or item.get("task_id")) for item in attention_items)
    for test in tests:
        if _contains_negative(test):
            issue_lines.append(test)
    issues = _dedupe(issue_lines, 12)

    next_steps = _next_lines(tasks_from_docs + progress)
    next_steps.extend(_text(item.get("title") or item.get("task_id")) for item in confirmed_planned)
    next_steps = _dedupe(next_steps, 12)

    metric_details = _metric_details(progress + tests_objects)
    metrics = [item["text"] for item in metric_details]
    remote_counts = _remote_counts(remote_events, now)
    local_uncommitted_count = 0
    for snapshot in workspace_snapshots:
        git = ((snapshot.get("payload") or {}).get("git") or {})
        if git.get("dirty"):
            local_uncommitted_count += 1

    stage = _infer_stage(
        active_count=len(active_items),
        blocker_count=len(issues),
        tests=tests,
        requirements=requirements,
        remote_counts=remote_counts,
    )
    weekly_progress = _build_weekly_progress(workspace_snapshots, remote_events, agent_events)

    historical_count = 0
    recent_count = 0
    undated_count = 0
    reference_dates: list[str] = []
    for snapshot in workspace_snapshots:
        memory = ((((snapshot.get("payload") or {}).get("analysis") or {}).get("current_project_memory") or {}))
        historical_count += len(memory.get("historical_facts") or [])
        recent_count += len(memory.get("recent_facts") or [])
        undated_count += len(memory.get("undated_facts") or [])
        if memory.get("freshness_reference_date"):
            reference_dates.append(str(memory["freshness_reference_date"]))

    return {
        "version": 2,
        "current_stage": stage,
        "completed": completed,
        "in_progress": in_progress,
        "issues": issues,
        "next_steps": next_steps,
        "latest_metrics": metrics,
        "latest_metric_details": metric_details,
        "recent_decisions": decisions[:8],
        "weekly_progress": weekly_progress,
        "summary": {
            "in_progress_task_count": len(active_items),
            "completed_task_count": len(done_items),
            "attention_task_count": len(attention_items),
            "planned_task_count": len(confirmed_planned),
            "candidate_task_count": len(planned_items),
            "local_uncommitted_workspace_count": local_uncommitted_count,
            "agent_activity_count": len(agent_events),
            **remote_counts,
        },
        "source_status": {
            "workspace_count": len(workspace_snapshots),
            "document_fact_count": len(progress) + len(tasks_from_docs) + len(tests) + len(requirements) + len(blockers),
            "work_item_count": len(work_items),
            "remote_event_count": len(remote_events),
            "historical_fact_count": historical_count,
            "recent_fact_count": recent_count,
            "undated_fact_count": undated_count,
            "freshness_reference_date": max(reference_dates) if reference_dates else None,
        },
    }
