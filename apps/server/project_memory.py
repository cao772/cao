from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import PurePosixPath
from typing import Any


FULL_DATE = re.compile(
    r"(?<!\d)(20\d{2})[._/\-年]?(1[0-2]|0?[1-9])[._/\-月]?(3[01]|[12]\d|0?[1-9])(?:日)?(?!\d)"
)
MD_SEPARATED = re.compile(
    r"(?<!\d)(1[0-2]|0?[1-9])[._/\-](3[01]|[12]\d|0?[1-9])(?!\d)"
)
MD_COMPACT = re.compile(
    r"(?<!\d)(1[0-2]|0?[1-9])([0-3]\d)(?!\d)"
)
VERSION = re.compile(r"(?i)(?:^|[^a-z0-9])v(\d+)(?:[._-](\d+))?")
ISSUE = re.compile(r"第\s*(\d+)\s*期")
COPY_MARKERS = re.compile(r"(?:副本|copy|备份|backup|归档|archive|historical|history)", re.IGNORECASE)
CURRENT_MARKERS = re.compile(r"(?:最终|final|最新|current|正式版)", re.IGNORECASE)
PARENT_SENSITIVE_STEMS = {
    "readme", "skill", "index", "config", "configuration", "requirements",
    "说明", "配置", "目录", "文档",
}
CURRENT_WINDOW_DAYS = 14
RECENT_WINDOW_DAYS = 35


def _clean_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def infer_temporal_hints(path: str) -> dict[str, Any]:
    name = PurePosixPath(_clean_path(path)).stem
    date_value: int | None = None
    date_precision: str | None = None
    date_text: str | None = None

    absolute = list(FULL_DATE.finditer(name))
    if not absolute:
        absolute = list(FULL_DATE.finditer(PurePosixPath(_clean_path(path)).parent.as_posix()))
    if absolute:
        match = absolute[-1]
        year, month, day = map(int, match.groups())
        date_value = year * 10000 + month * 100 + day
        date_precision = "day"
        date_text = f"{year:04d}-{month:02d}-{day:02d}"
    else:
        candidates: list[tuple[int, int, str]] = []
        for match in MD_SEPARATED.finditer(name):
            month, day = map(int, match.groups())
            candidates.append((match.start(), month * 100 + day, f"{month:02d}-{day:02d}"))
        for match in MD_COMPACT.finditer(name):
            month, day = map(int, match.groups())
            if 1 <= month <= 12 and 1 <= day <= 31:
                candidates.append((match.start(), month * 100 + day, f"{month:02d}-{day:02d}"))
        if candidates:
            _, date_value, date_text = sorted(candidates, key=lambda item: item[0])[-1]
            date_precision = "month_day"

    version_matches = list(VERSION.finditer(name))
    version: tuple[int, int] | None = None
    if version_matches:
        match = version_matches[-1]
        version = (int(match.group(1)), int(match.group(2) or 0))

    issue_matches = list(ISSUE.finditer(name))
    issue = int(issue_matches[-1].group(1)) if issue_matches else None

    return {
        "date_value": date_value,
        "date_precision": date_precision,
        "date_text": date_text,
        "version_major": version[0] if version else None,
        "version_minor": version[1] if version else None,
        "issue": issue,
    }


def series_key(path: str) -> str:
    """Collapse obvious versions/copies into one logical document series.

    A document can move between folders during handoff without becoming a new series.
    Very generic names (README/config/etc.) remain parent-sensitive to avoid merging
    unrelated files from different modules.
    """
    clean = _clean_path(path)
    pure = PurePosixPath(clean)
    stem = pure.stem.lower()
    stem = FULL_DATE.sub("", stem)
    stem = MD_SEPARATED.sub("", stem)
    stem = MD_COMPACT.sub("", stem)
    stem = VERSION.sub(" ", stem)
    stem = ISSUE.sub("", stem)
    stem = COPY_MARKERS.sub("", stem)
    stem = re.sub(r"\((?:\d+|副本|copy)\)", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"(?:[_\-\s]+)(?:final|最终|最新版|最新)$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[_\-.\s（）()]+", " ", stem).strip()
    parent = pure.parent.as_posix().lower()
    scope = parent if stem in PARENT_SENSITIVE_STEMS or len(stem) < 4 else "*"
    return f"{scope}::{stem}::{pure.suffix.lower()}"


def source_quality(path: str, role: str) -> int:
    clean = _clean_path(path)
    name = PurePosixPath(clean).name
    depth = len(PurePosixPath(clean).parts)
    score = 50
    score += max(0, 12 - max(depth - 1, 0) * 3)
    if CURRENT_MARKERS.search(name):
        score += 12
    if COPY_MARKERS.search(clean):
        score -= 20
    if "__macosx" in clean.lower() or ".ds_store" in clean.lower():
        score -= 50

    role_bonus = {
        "progress": 14,
        "report": 12,
        "decision": 10,
        "requirement": 9,
        "test_result": 9,
        "handoff": 7,
        "design": 5,
        "interface": 5,
        "deployment": 4,
        "document": 2,
        "output": 1,
        "code": 0,
    }
    score += role_bonus.get(role, 0)
    return score


def freshness_sort_key(item: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
    path = str(item.get("path") or "")
    role = str(item.get("role") or "document")
    hints = infer_temporal_hints(path)
    date_value = int(hints.get("date_value") or 0)
    date_precision = 2 if hints.get("date_precision") == "day" else (1 if date_value else 0)
    version_major = int(hints.get("version_major") or 0)
    version_minor = int(hints.get("version_minor") or 0)
    issue = int(hints.get("issue") or 0)
    return (
        date_precision,
        date_value,
        version_major * 1000 + version_minor,
        issue,
        source_quality(path, role),
        path,
    )


def _dedupe_facts(facts: list[dict[str, Any]], limit: int = 300) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for fact in facts:
        fact_type = str(fact.get("type") or "note")
        text = re.sub(r"\s+", " ", str(fact.get("text") or "")).strip()
        if not text:
            continue
        key = (fact_type, text)
        if key in seen:
            continue
        seen.add(key)
        item = dict(fact)
        item["type"] = fact_type
        item["text"] = text
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _reference_year(items: list[dict[str, Any]], fallback_year: int | None = None) -> int:
    years: list[int] = []
    for item in items:
        value = int(infer_temporal_hints(str(item.get("path") or "")).get("date_value") or 0)
        if value >= 10_000_00:
            years.append(value // 10000)
    return max(years) if years else (fallback_year or date.today().year)


def _source_date(path: str, reference_year: int, absolute_reference: date | None = None) -> date | None:
    hints = infer_temporal_hints(path)
    value = int(hints.get("date_value") or 0)
    if not value:
        return None
    try:
        if hints.get("date_precision") == "day":
            return date(value // 10000, (value // 100) % 100, value % 100)
        month, day = value // 100, value % 100
        candidate = date(reference_year, month, day)
        if absolute_reference and candidate > absolute_reference + timedelta(days=45):
            candidate = date(reference_year - 1, month, day)
        return candidate
    except ValueError:
        return None


def _week_info(value: date) -> dict[str, str]:
    iso_year, iso_week, _ = value.isocalendar()
    start = value - timedelta(days=value.weekday())
    end = start + timedelta(days=6)
    return {
        "week_key": f"{iso_year}-W{iso_week:02d}",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def build_current_project_memory(analysis: dict[str, Any], *, reference_year: int | None = None) -> dict[str, Any]:
    """Build a current view while retaining old material as history.

    Newest file in each logical series wins. On top of version selection, dated
    source files are classified relative to the newest project-management source:
    current (<=14d), recent (<=35d), historical (>35d). Historical/undated facts
    remain queryable but no longer automatically drive current task/project state.
    """
    raw_items = analysis.get("items") or []
    items = [item for item in raw_items if isinstance(item, dict) and item.get("status") == "analyzed"]

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[series_key(str(item.get("path") or ""))].append(item)

    current_items: list[dict[str, Any]] = []
    historical_versions: list[dict[str, Any]] = []
    version_families: list[dict[str, Any]] = []

    for key, group in groups.items():
        ordered = sorted(group, key=freshness_sort_key, reverse=True)
        latest = ordered[0]
        current_items.append(latest)
        if len(ordered) > 1:
            historical_versions.extend(ordered[1:])
            version_families.append(
                {
                    "series_key": key,
                    "current": latest.get("path"),
                    "historical": [item.get("path") for item in ordered[1:20]],
                    "count": len(ordered),
                }
            )

    current_items.sort(key=freshness_sort_key, reverse=True)
    reference_year = _reference_year(current_items, reference_year)
    absolute_dates = [
        _source_date(str(item.get("path") or ""), reference_year)
        for item in current_items
        if infer_temporal_hints(str(item.get("path") or "")).get("date_precision") == "day"
    ]
    absolute_reference = max((d for d in absolute_dates if d), default=None)
    dated_sources = [
        _source_date(str(item.get("path") or ""), reference_year, absolute_reference)
        for item in current_items
    ]
    reference_date = max((d for d in dated_sources if d), default=None)

    item_meta: dict[str, dict[str, Any]] = {}
    for item in current_items:
        path = str(item.get("path") or "")
        source_date = _source_date(path, reference_year, absolute_reference)
        if reference_date is None:
            freshness = "current"
        elif source_date is None:
            freshness = "undated"
        else:
            age = max(0, (reference_date - source_date).days)
            if age <= CURRENT_WINDOW_DAYS:
                freshness = "current"
            elif age <= RECENT_WINDOW_DAYS:
                freshness = "recent"
            else:
                freshness = "historical"
        item_meta[path] = {
            "source_date": source_date.isoformat() if source_date else None,
            "freshness": freshness,
            "temporal": infer_temporal_hints(path),
            "series_key": series_key(path),
        }

    facts: list[dict[str, Any]] = []
    for item in current_items:
        path = str(item.get("path") or "")
        role = str(item.get("role") or "document")
        analysis_result = item.get("analysis") or {}
        meta = item_meta[path]
        for fact in analysis_result.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            facts.append(
                {
                    "type": fact.get("type") or "note",
                    "text": fact.get("text"),
                    "path": path,
                    "role": role,
                    "source_quality": source_quality(path, role),
                    "source_date": meta["source_date"],
                    "freshness": meta["freshness"],
                    "series_key": meta["series_key"],
                }
            )

    facts = _dedupe_facts(facts)
    active_facts = [fact for fact in facts if fact.get("freshness") == "current"]
    recent_facts = [fact for fact in facts if fact.get("freshness") == "recent"]
    historical_facts = [fact for fact in facts if fact.get("freshness") == "historical"]
    undated_facts = [fact for fact in facts if fact.get("freshness") == "undated"]
    if reference_date is None:
        active_facts = facts

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in active_facts:
        buckets[str(fact.get("type") or "note")].append(fact)
    for fact in facts:
        all_buckets[str(fact.get("type") or "note")].append(fact)

    week_map: dict[str, dict[str, Any]] = {}
    for fact in facts:
        source_date_text = fact.get("source_date")
        if not source_date_text:
            continue
        try:
            source_date = date.fromisoformat(str(source_date_text))
        except ValueError:
            continue
        info = _week_info(source_date)
        group = week_map.setdefault(
            info["week_key"],
            {**info, "facts": [], "fact_count": 0},
        )
        group["facts"].append(fact)
        group["fact_count"] += 1
    weekly_facts = sorted(week_map.values(), key=lambda item: item["start"], reverse=True)
    for group in weekly_facts:
        group["facts"] = group["facts"][:100]

    latest_sources = []
    for item in current_items[:80]:
        path = str(item.get("path") or "")
        role = str(item.get("role") or "document")
        latest_sources.append(
            {
                "path": path,
                "role": role,
                "source_quality": source_quality(path, role),
                **item_meta[path],
                "summary": str((item.get("analysis") or {}).get("summary") or "")[:500],
            }
        )

    warnings: list[str] = []
    if version_families:
        warnings.append(f"检测到 {len(version_families)} 组多版本资料；当前视图采用每组最新版本，旧版本保留追溯。")
    if historical_facts:
        warnings.append(f"有 {len(historical_facts)} 条历史事实不再自动参与当前任务/阶段判断。")
    if undated_facts and reference_date:
        warnings.append(f"有 {len(undated_facts)} 条未标日期事实作为参考保留，不自动视为当前进展。")
    if not current_items and analysis.get("enabled"):
        warnings.append("资料分析已启用，但没有可用于当前视图的已解析文件。")

    local_memory = analysis.get("project_memory") or {}
    diagnostics = list(local_memory.get("diagnostics") or [])
    if diagnostics:
        warnings.append(f"有 {len(diagnostics)} 个文件未进入正文事实提取，详见 diagnostics。")

    return {
        "current_source_count": len(current_items),
        "historical_source_count": len(historical_versions),
        "version_family_count": len(version_families),
        "version_families": version_families[:100],
        "freshness_reference_date": reference_date.isoformat() if reference_date else None,
        "freshness_windows": {"current_days": CURRENT_WINDOW_DAYS, "recent_days": RECENT_WINDOW_DAYS},
        "latest_sources": latest_sources,
        "facts": facts,
        "current_facts": active_facts[:300],
        "recent_facts": recent_facts[:300],
        "historical_facts": historical_facts[:300],
        "undated_facts": undated_facts[:300],
        "weekly_facts": weekly_facts[:26],
        "by_type": {key: value[:100] for key, value in buckets.items()},
        "all_by_type": {key: value[:100] for key, value in all_buckets.items()},
        "blockers": buckets.get("blocker", [])[:50],
        "progress": buckets.get("progress", [])[:80],
        "tasks": buckets.get("task", [])[:80],
        "tests": buckets.get("test", [])[:80],
        "requirements": buckets.get("requirement", [])[:80],
        "decisions": buckets.get("decision", [])[:80],
        "milestones": buckets.get("milestone", [])[:80],
        "diagnostics": diagnostics[:200],
        "warnings": warnings,
    }


def enrich_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    analysis = result.get("analysis") or {}
    if analysis.get("enabled"):
        enriched_analysis = dict(analysis)
        observed = str(result.get("observed_at") or "")
        try:
            snapshot_year = date.fromisoformat(observed[:10]).year
        except ValueError:
            snapshot_year = date.today().year
        enriched_analysis["current_project_memory"] = build_current_project_memory(analysis, reference_year=snapshot_year)
        result["analysis"] = enriched_analysis
    return result
