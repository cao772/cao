from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any

from document_versioning import (
    classify_latest_freshness,
    document_temporal,
    freshness_sort_key,
    infer_temporal_hints,
    reference_year_for_items,
    series_id,
    series_key,
    series_title,
    source_quality,
)

CURRENT_WINDOW_DAYS = 14
RECENT_WINDOW_DAYS = 35

COMPLETE_RE = re.compile(r"已完成|已经完成|完成|已通过|验收通过|已上线|上线完成|已交付|done|completed|passed", re.IGNORECASE)
PENDING_RE = re.compile(r"尚未|未完成|未开始|待开发|待测试|待验证|待确认|待补齐|下一步|计划|进行中|todo|pending|in progress", re.IGNORECASE)
FAIL_RE = re.compile(r"失败|不通过|未通过|异常|错误|failed|failure|error", re.IGNORECASE)
PASS_RE = re.compile(r"全部通过|测试通过|验收通过|\b\d+\s+passed\b|passed", re.IGNORECASE)
STATUS_NOISE_RE = re.compile(
    r"已完成|已经完成|完成|已通过|通过|验收通过|已上线|上线完成|已交付|"
    r"尚未|未完成|未开始|待开发|待测试|待验证|待确认|待补齐|下一步|计划|进行中|"
    r"仍有|还有|失败|不通过|未通过|异常|错误|全部|当前|本周|状态|"
    r"done|completed|passed|failed|failure|error|todo|pending|in progress",
    re.IGNORECASE,
)
METRIC_LABELS = (
    "图像确认率", "定级覆盖率", "已定级准确率", "端到端准确率", "准确率", "覆盖率", "确认率",
    "通过率", "完成率", "成功率",
)


def _dedupe_facts(facts: list[dict[str, Any]], limit: int = 1000) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for fact in facts:
        fact_type = str(fact.get("type") or "note")
        text = re.sub(r"\s+", " ", str(fact.get("text") or "")).strip()
        path = str(fact.get("path") or "")
        if not text:
            continue
        key = (fact_type, text, path)
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


def _fact_state(text: str) -> str:
    lower = text.lower()
    if re.search(r"无失败|没有失败|0\s*(?:failed|errors?)", lower):
        return "pass"
    if FAIL_RE.search(text):
        return "fail"
    if PENDING_RE.search(text):
        return "pending"
    if COMPLETE_RE.search(text):
        return "done"
    if PASS_RE.search(text):
        return "pass"
    return "unknown"


def _topic_key(text: str) -> str:
    value = STATUS_NOISE_RE.sub(" ", text)
    value = re.sub(r"20\d{2}[年./_-]?\d{1,2}[月./_-]?\d{1,2}日?", " ", value)
    value = re.sub(r"\b\d+(?:\.\d+)?\s*%", " ", value)
    value = re.sub(r"\b\d+\s*/\s*\d+\b", " ", value)
    value = re.sub(r"\b\d+\s*(?:项|条|个|次|例|passed|failed)\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value).lower()
    return value[:100]


def _source_date_value(fact: dict[str, Any]) -> date:
    try:
        return date.fromisoformat(str(fact.get("document_date") or fact.get("source_date") or ""))
    except ValueError:
        return date.min


def _contradictory(a: str, b: str) -> bool:
    pair = {a, b}
    return pair in ({"done", "pending"}, {"done", "fail"}, {"pass", "fail"}, {"pending", "pass"})


def _suppress_older_status(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        topic = _topic_key(str(fact.get("text") or ""))
        if len(topic) >= 4 and _fact_state(str(fact.get("text") or "")) != "unknown":
            groups[topic].append(fact)

    suppressed: set[int] = set()
    for values in groups.values():
        dated = sorted(values, key=lambda item: (_source_date_value(item), int(item.get("source_quality") or 0)), reverse=True)
        if len(dated) < 2:
            continue
        newest = dated[0]
        newest_date = _source_date_value(newest)
        newest_state = _fact_state(str(newest.get("text") or ""))
        if newest_date == date.min:
            continue
        for older in dated[1:]:
            older_date = _source_date_value(older)
            if older_date == date.min or older_date >= newest_date:
                continue
            if _contradictory(newest_state, _fact_state(str(older.get("text") or ""))):
                suppressed.add(id(older))
    return [fact for fact in facts if id(fact) not in suppressed]


def _conflict_topic(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    a_text = str(a.get("text") or "")
    b_text = str(b.get("text") or "")
    a_key, b_key = _topic_key(a_text), _topic_key(b_text)
    if a_key and a_key == b_key and len(a_key) >= 4:
        return a_key
    if str(a.get("type")) == str(b.get("type")) == "test":
        qualifiers = ("后端", "前端", "接口", "模型", "部署", "验收")
        a_specific = {word for word in qualifiers if word in a_text}
        b_specific = {word for word in qualifiers if word in b_text}
        if a_specific != b_specific:
            return None
        if "测试" in a_text and "测试" in b_text:
            return "测试" + ("/" + "/".join(sorted(a_specific)) if a_specific else "")
    return None


def _detect_conflicts(current_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, left in enumerate(current_facts):
        left_state = _fact_state(str(left.get("text") or ""))
        if left_state == "unknown" or int(left.get("source_quality") or 0) < 45:
            continue
        for right in current_facts[index + 1:]:
            if left.get("path") == right.get("path"):
                continue
            right_state = _fact_state(str(right.get("text") or ""))
            if not _contradictory(left_state, right_state):
                continue
            left_date, right_date = _source_date_value(left), _source_date_value(right)
            if left_date != date.min and right_date != date.min and abs((left_date - right_date).days) > 7:
                continue
            topic = _conflict_topic(left, right)
            if not topic:
                continue
            key = (topic, str(left.get("path")), str(right.get("path")))
            if key in seen:
                continue
            seen.add(key)
            conflicts.append(
                {
                    "topic": topic,
                    "facts": [left, right],
                    "sources": [left.get("path"), right.get("path")],
                    "reason": "当前资料存在不一致",
                }
            )
            if len(conflicts) >= 50:
                return conflicts
    return conflicts


def _metric_name(text: str) -> str:
    for label in METRIC_LABELS:
        if label in text:
            return label
    if "后端" in text and re.search(r"通过|passed", text, re.IGNORECASE):
        return "后端测试通过"
    if "前端" in text and re.search(r"通过|passed", text, re.IGNORECASE):
        return "前端测试通过"
    if re.search(r"通过|passed", text, re.IGNORECASE):
        return "测试通过数"
    return "指标"


def _extract_metrics(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for fact in facts:
        text = str(fact.get("text") or "")
        if not text:
            continue
        source_date = fact.get("document_date") or fact.get("source_date")
        path = fact.get("path")
        matched_any = False
        for label in METRIC_LABELS:
            match = re.search(re.escape(label) + r"\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%", text)
            if not match:
                continue
            pct = float(match.group(1))
            candidates.append({
                "name": label,
                "numerator": None,
                "denominator": None,
                "value": pct / 100,
                "unit": "%",
                "display": f"{label}{pct:g}%",
                "date": source_date,
                "source": path,
                "text": text,
            })
            matched_any = True

        ratio = re.search(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)", text)
        percent = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if ratio:
            numerator, denominator = map(int, ratio.groups())
            if denominator > 0:
                value = numerator / denominator
                name = _metric_name(text)
                candidates.append({
                    "name": name,
                    "numerator": numerator,
                    "denominator": denominator,
                    "value": value,
                    "unit": "%",
                    "display": f"{numerator}/{denominator}（{value * 100:.2f}%）",
                    "date": source_date,
                    "source": path,
                    "text": text,
                })
                matched_any = True
        if not ratio:
            passed = re.search(r"(?<!\d)(\d+)\s*(?:项|条|个|次|例)?\s*(?:测试)?\s*(?:通过|passed)", text, re.IGNORECASE)
            total = re.search(r"(?:共|总计|总数)\s*(\d+)\s*(?:项|条|个|次|例)?", text)
            if passed:
                numerator = int(passed.group(1))
                denominator = int(total.group(1)) if total else None
                name = _metric_name(text)
                if denominator and denominator > 0:
                    value = numerator / denominator
                    display = f"{numerator}/{denominator}（{value * 100:.2f}%）"
                else:
                    value = None
                    display = f"{numerator}项通过（分母未识别）"
                candidates.append({
                    "name": name,
                    "numerator": numerator,
                    "denominator": denominator,
                    "value": value,
                    "unit": "项" if denominator is None else "%",
                    "display": display,
                    "date": source_date,
                    "source": path,
                    "text": text,
                })
                matched_any = True
        if percent and not matched_any:
            pct = float(percent.group(1))
            candidates.append({
                "name": _metric_name(text),
                "numerator": None,
                "denominator": None,
                "value": pct / 100,
                "unit": "%",
                "display": f"{pct:g}%",
                "date": source_date,
                "source": path,
                "text": text,
            })

    candidates.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("source") or "")), reverse=True)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        name = str(item.get("name") or "指标")
        if name in seen:
            continue
        seen.add(name)
        result.append(item)
        if len(result) >= 20:
            break
    return result


def _week_info(value: date) -> dict[str, str]:
    iso_year, iso_week, _ = value.isocalendar()
    start = date.fromordinal(value.toordinal() - value.weekday())
    end = date.fromordinal(start.toordinal() + 6)
    return {"week_key": f"{iso_year}-W{iso_week:02d}", "start": start.isoformat(), "end": end.isoformat()}


def build_current_project_memory(analysis: dict[str, Any], *, reference_year: int | None = None) -> dict[str, Any]:
    raw_items = analysis.get("items") or []
    items = [item for item in raw_items if isinstance(item, dict) and item.get("status") == "analyzed"]
    reference_year = reference_year_for_items(items, reference_year)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[series_key(str(item.get("path") or ""))].append(item)

    latest_items: list[dict[str, Any]] = []
    historical_versions: list[dict[str, Any]] = []
    document_series: list[dict[str, Any]] = []
    current_paths: set[str] = set()

    for key, group in groups.items():
        ordered = sorted(group, key=lambda item: freshness_sort_key(item, reference_year=reference_year), reverse=True)
        latest = ordered[0]
        latest_items.append(latest)
        current_path = str(latest.get("path") or "")
        current_paths.add(current_path)
        historical_versions.extend(ordered[1:])
        document_series.append({
            "series_id": series_id(current_path),
            "series_key": key,
            "series_title": series_title(current_path),
            "role": latest.get("role") or "document",
            "current_path": current_path,
            "historical_paths": [str(item.get("path") or "") for item in ordered[1:20]],
            "count": len(ordered),
        })

    latest_items.sort(key=lambda item: freshness_sort_key(item, reference_year=reference_year), reverse=True)
    latest_temporal = {str(item.get("path") or ""): document_temporal(item, reference_year=reference_year) for item in latest_items}
    latest_dates = []
    for temporal in latest_temporal.values():
        try:
            latest_dates.append(date.fromisoformat(str(temporal.get("document_date") or "")))
        except ValueError:
            pass
    reference_date = max(latest_dates, default=None)

    item_meta: dict[str, dict[str, Any]] = {}
    for item in items:
        path = str(item.get("path") or "")
        role = str(item.get("role") or "document")
        temporal = document_temporal(item, reference_year=reference_year)
        try:
            parsed_date = date.fromisoformat(str(temporal.get("document_date") or ""))
        except ValueError:
            parsed_date = None
        current_version = path in current_paths
        freshness = classify_latest_freshness(role, parsed_date, reference_date) if current_version else "historical"
        item_meta[path] = {
            **temporal,
            "source_date": temporal.get("document_date"),
            "freshness": freshness,
            "series_id": series_id(path),
            "series_key": series_key(path),
            "series_title": series_title(path),
            "current_version": current_version,
            "superseded": not current_version,
        }

    facts: list[dict[str, Any]] = []
    for item in items:
        path = str(item.get("path") or "")
        role = str(item.get("role") or "document")
        meta = item_meta[path]
        for raw_fact in (item.get("analysis") or {}).get("facts") or []:
            if not isinstance(raw_fact, dict):
                continue
            facts.append({
                "type": raw_fact.get("type") or "note",
                "text": raw_fact.get("text"),
                "path": path,
                "role": role,
                "source_quality": source_quality(path, role),
                **meta,
            })
    facts = _dedupe_facts(facts)

    current_facts = [fact for fact in facts if fact.get("freshness") == "current"]
    recent_facts = [fact for fact in facts if fact.get("freshness") == "recent"]
    historical_facts = [fact for fact in facts if fact.get("freshness") == "historical"]
    undated_facts = [fact for fact in facts if fact.get("freshness") == "undated"]

    current_types = {str(fact.get("type") or "note") for fact in current_facts}
    effective_facts = list(current_facts)
    effective_facts.extend(fact for fact in recent_facts if str(fact.get("type") or "note") not in current_types)
    effective_facts = _suppress_older_status(effective_facts)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in effective_facts:
        buckets[str(fact.get("type") or "note")].append(fact)
    for fact in facts:
        all_buckets[str(fact.get("type") or "note")].append(fact)

    week_map: dict[str, dict[str, Any]] = {}
    for fact in facts:
        try:
            source_date = date.fromisoformat(str(fact.get("document_date") or ""))
        except ValueError:
            continue
        info = _week_info(source_date)
        group = week_map.setdefault(info["week_key"], {**info, "facts": [], "fact_count": 0})
        group["facts"].append(fact)
        group["fact_count"] += 1
    weekly_facts = sorted(week_map.values(), key=lambda item: item["start"], reverse=True)
    for group in weekly_facts:
        group["facts"] = group["facts"][:100]

    latest_sources: list[dict[str, Any]] = []
    for item in latest_items[:100]:
        path = str(item.get("path") or "")
        role = str(item.get("role") or "document")
        latest_sources.append({
            "path": path,
            "role": role,
            "source_quality": source_quality(path, role),
            **item_meta[path],
            "summary": str((item.get("analysis") or {}).get("summary") or "")[:500],
        })

    conflicts = _detect_conflicts(current_facts)
    latest_metrics = _extract_metrics(effective_facts)
    stage_evidence = [
        {"path": fact.get("path"), "date": fact.get("document_date"), "text": fact.get("text"), "type": fact.get("type")}
        for fact in sorted(
            [fact for fact in effective_facts if fact.get("type") in {"progress", "milestone", "test", "deployment", "decision"}],
            key=lambda item: (_source_date_value(item), int(item.get("source_quality") or 0)),
            reverse=True,
        )[:8]
    ]

    warnings: list[str] = []
    version_families = [series for series in document_series if series["count"] > 1]
    if version_families:
        warnings.append(f"检测到 {len(version_families)} 组多版本资料；当前视图采用每组最新版本，旧版本保留追溯。")
    if historical_facts:
        warnings.append(f"有 {len(historical_facts)} 条历史事实不再自动参与当前任务/阶段判断。")
    if undated_facts:
        warnings.append(f"有 {len(undated_facts)} 条未确认日期事实保留在 undated，不自动视为当前事实。")
    if conflicts:
        warnings.append(f"检测到 {len(conflicts)} 组当前资料冲突，已保留双方证据而未静默覆盖。")
    if not latest_items and analysis.get("enabled"):
        warnings.append("资料分析已启用，但没有可用于当前视图的已解析文件。")

    local_memory = analysis.get("project_memory") or {}
    diagnostics = list(local_memory.get("diagnostics") or [])
    if diagnostics:
        warnings.append(f"有 {len(diagnostics)} 个文件未进入正文事实提取，详见 diagnostics。")

    return {
        "version": 2,
        "current_source_count": len(latest_items),
        "historical_source_count": len(historical_versions),
        "version_family_count": len(version_families),
        "version_families": [
            {
                "series_key": item["series_key"],
                "series_id": item["series_id"],
                "series_title": item["series_title"],
                "current": item["current_path"],
                "historical": item["historical_paths"],
                "count": item["count"],
            }
            for item in version_families[:100]
        ],
        "document_series": document_series[:200],
        "freshness_reference_date": reference_date.isoformat() if reference_date else None,
        "freshness_windows": {"current_days": CURRENT_WINDOW_DAYS, "recent_days": RECENT_WINDOW_DAYS},
        "latest_sources": latest_sources,
        "facts": facts,
        "current_facts": current_facts[:500],
        "recent_facts": recent_facts[:500],
        "historical_facts": historical_facts[:1000],
        "undated_facts": undated_facts[:500],
        "effective_facts": effective_facts[:500],
        "conflicts": conflicts,
        "latest_metrics": latest_metrics,
        "stage_evidence": stage_evidence,
        "weekly_facts": weekly_facts[:52],
        "by_type": {key: value[:150] for key, value in buckets.items()},
        "all_by_type": {key: value[:200] for key, value in all_buckets.items()},
        "blockers": buckets.get("blocker", [])[:80],
        "progress": buckets.get("progress", [])[:120],
        "tasks": buckets.get("task", [])[:120],
        "tests": buckets.get("test", [])[:120],
        "requirements": buckets.get("requirement", [])[:120],
        "decisions": buckets.get("decision", [])[:120],
        "milestones": buckets.get("milestone", [])[:120],
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
