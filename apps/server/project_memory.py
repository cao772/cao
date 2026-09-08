from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any


DATE_8 = re.compile(r"(?<!\d)(20\d{2})[-_.年]?(0[1-9]|1[0-2])[-_.月]?(0[1-9]|[12]\d|3[01])(?:日)?(?!\d)")
DATE_4 = re.compile(r"(?<!\d)(0[1-9]|1[0-2])([0-2]\d|3[01])(?!\d)")
VERSION = re.compile(r"(?i)(?:^|[^a-z0-9])v(\d+)(?:[._-](\d+))?")
ISSUE = re.compile(r"第\s*(\d+)\s*期")
COPY_MARKERS = re.compile(r"(?:副本|copy|备份|backup|归档|archive|historical|history)", re.IGNORECASE)
CURRENT_MARKERS = re.compile(r"(?:最终|final|最新|current|正式版)", re.IGNORECASE)


def _clean_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def infer_temporal_hints(path: str) -> dict[str, Any]:
    name = PurePosixPath(_clean_path(path)).stem
    date_value: int | None = None
    date_precision: str | None = None
    date_text: str | None = None

    absolute = list(DATE_8.finditer(name))
    if absolute:
        match = absolute[-1]
        year, month, day = map(int, match.groups())
        date_value = year * 10000 + month * 100 + day
        date_precision = "day"
        date_text = f"{year:04d}-{month:02d}-{day:02d}"
    else:
        short_dates = list(DATE_4.finditer(name))
        if short_dates:
            match = short_dates[-1]
            month, day = map(int, match.groups())
            date_value = month * 100 + day
            date_precision = "month_day"
            date_text = f"{month:02d}-{day:02d}"

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
    """Collapse obvious filename versions into one document series.

    This is deliberately conservative: it keeps the full parent path so files in
    unrelated directories do not become one series merely because their names match.
    """
    clean = _clean_path(path)
    pure = PurePosixPath(clean)
    stem = pure.stem.lower()
    stem = DATE_8.sub("", stem)
    stem = DATE_4.sub("", stem)
    stem = VERSION.sub(" ", stem)
    stem = ISSUE.sub("", stem)
    stem = re.sub(r"\((?:\d+|副本|copy)\)", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"(?:[_\-\s]+)(?:final|最终|最新版|最新)$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[_\-.\s（）()]+", " ", stem).strip()
    return f"{pure.parent.as_posix().lower()}::{stem}::{pure.suffix.lower()}"


def source_quality(path: str, role: str) -> int:
    clean = _clean_path(path)
    name = PurePosixPath(clean).name
    depth = len(PurePosixPath(clean).parts)
    score = 50

    # Root-level project control/progress documents are usually more intentional
    # than copies buried inside handoff/history folders.
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


def build_current_project_memory(analysis: dict[str, Any]) -> dict[str, Any]:
    """Build a current-view memory without deleting historical source material.

    The local collector keeps every analyzed item. The central fusion layer groups
    obvious filename versions and selects the newest representative for the current
    view. Older versions remain visible as history and can still be audited.
    """
    raw_items = analysis.get("items") or []
    items = [item for item in raw_items if isinstance(item, dict) and item.get("status") == "analyzed"]

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[series_key(str(item.get("path") or ""))].append(item)

    current_items: list[dict[str, Any]] = []
    historical_items: list[dict[str, Any]] = []
    version_families: list[dict[str, Any]] = []

    for key, group in groups.items():
        ordered = sorted(group, key=freshness_sort_key, reverse=True)
        latest = ordered[0]
        current_items.append(latest)
        if len(ordered) > 1:
            historical_items.extend(ordered[1:])
            version_families.append(
                {
                    "series_key": key,
                    "current": latest.get("path"),
                    "historical": [item.get("path") for item in ordered[1:20]],
                    "count": len(ordered),
                }
            )

    current_items.sort(key=freshness_sort_key, reverse=True)

    facts: list[dict[str, Any]] = []
    for item in current_items:
        path = str(item.get("path") or "")
        role = str(item.get("role") or "document")
        analysis_result = item.get("analysis") or {}
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
                }
            )

    facts = _dedupe_facts(facts)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        buckets[str(fact.get("type") or "note")].append(fact)

    latest_sources = []
    for item in current_items[:80]:
        path = str(item.get("path") or "")
        role = str(item.get("role") or "document")
        latest_sources.append(
            {
                "path": path,
                "role": role,
                "source_quality": source_quality(path, role),
                "temporal": infer_temporal_hints(path),
                "summary": str((item.get("analysis") or {}).get("summary") or "")[:500],
            }
        )

    warnings: list[str] = []
    if version_families:
        warnings.append(
            f"检测到 {len(version_families)} 组多版本资料；当前视图只采用每组最新代表，历史版本未删除。"
        )
    if not current_items and analysis.get("enabled"):
        warnings.append("资料分析已启用，但没有可用于当前视图的已解析文件。")

    return {
        "current_source_count": len(current_items),
        "historical_source_count": len(historical_items),
        "version_family_count": len(version_families),
        "version_families": version_families[:100],
        "latest_sources": latest_sources,
        "facts": facts,
        "by_type": {key: value[:100] for key, value in buckets.items()},
        "blockers": buckets.get("blocker", [])[:50],
        "progress": buckets.get("progress", [])[:80],
        "tasks": buckets.get("task", [])[:80],
        "tests": buckets.get("test", [])[:80],
        "requirements": buckets.get("requirement", [])[:80],
        "decisions": buckets.get("decision", [])[:80],
        "milestones": buckets.get("milestone", [])[:80],
        "warnings": warnings,
    }


def enrich_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    analysis = result.get("analysis") or {}
    if analysis.get("enabled"):
        enriched_analysis = dict(analysis)
        enriched_analysis["current_project_memory"] = build_current_project_memory(analysis)
        result["analysis"] = enriched_analysis
    return result
