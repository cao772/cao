from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

FULL_DATE = re.compile(r"(?<!\d)(20\d{2})\s*[._/\-年]?\s*(1[0-2]|0?[1-9])\s*[._/\-月]?\s*(3[01]|[12]\d|0?[1-9])\s*日?(?!\d)")
MD_CHINESE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*月\s*(3[01]|[12]\d|0?[1-9])\s*日?")
MD_SEPARATED = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])[._/\-](3[01]|[12]\d|0?[1-9])(?!\d)")
MD_COMPACT = re.compile(r"(?<![A-Za-z0-9])(0?[1-9]|1[0-2])([0-3]\d)(?![A-Za-z0-9])")
VERSION = re.compile(r"(?i)(?<![a-z0-9])v\s*(\d+)(?:[._-](\d+))?")
ISSUE = re.compile(r"第\s*(\d+)\s*期")
COPY_MARKERS = re.compile(r"(?:副本|copy|备份|backup|归档|archive|historical|history)", re.IGNORECASE)
EDITION_MARKERS = re.compile(r"(?:最终版?|修订版?|新版|最新版|最新|正式版?|final|revised|revision)", re.IGNORECASE)
CURRENT_MARKERS = re.compile(r"(?:最终|final|最新|current|正式版)", re.IGNORECASE)
NON_DATE_COMPACT_PREFIX = re.compile(r"(?:版本|编号|序号|型号|批次|工单|id|no\.?)\s*$", re.IGNORECASE)
PARENT_SENSITIVE_STEMS = {"readme", "skill", "index", "config", "configuration", "requirements", "说明", "配置", "目录", "文档"}
STABLE_ROLES = {"requirement", "design", "interface", "decision"}


def _clean_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _valid_ymd(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _compact_is_date_context(text: str, match: re.Match[str]) -> bool:
    prefix = text[max(0, match.start() - 8):match.start()]
    return not bool(NON_DATE_COMPACT_PREFIX.search(prefix))


def _compact_matches(text: str) -> list[re.Match[str]]:
    return [match for match in MD_COMPACT.finditer(text) if _compact_is_date_context(text, match)]


def _extract_date(text: str, *, reference_year: int, allow_compact: bool) -> tuple[date | None, str | None]:
    absolute = list(FULL_DATE.finditer(text))
    if absolute:
        match = absolute[-1]
        value = _valid_ymd(*map(int, match.groups()))
        if value:
            return value, "day"

    candidates: list[tuple[int, int, int]] = []
    for pattern in (MD_CHINESE, MD_SEPARATED):
        for match in pattern.finditer(text):
            month, day = map(int, match.groups())
            if _valid_ymd(reference_year, month, day):
                candidates.append((match.start(), month, day))
    if allow_compact:
        for match in _compact_matches(text):
            month, day = map(int, match.groups())
            if _valid_ymd(reference_year, month, day):
                candidates.append((match.start(), month, day))
    if candidates:
        _, month, day = sorted(candidates, key=lambda item: item[0])[-1]
        return date(reference_year, month, day), "month_day"
    return None, None


def infer_temporal_hints(path: str) -> dict[str, Any]:
    clean = _clean_path(path)
    pure = PurePosixPath(clean)
    name = pure.stem
    absolute = list(FULL_DATE.finditer(name)) or list(FULL_DATE.finditer(pure.parent.as_posix()))
    date_value: int | None = None
    date_precision: str | None = None
    date_text: str | None = None
    if absolute:
        match = absolute[-1]
        year, month, day = map(int, match.groups())
        parsed = _valid_ymd(year, month, day)
        if parsed:
            date_value = year * 10000 + month * 100 + day
            date_precision = "day"
            date_text = parsed.isoformat()
    else:
        candidates: list[tuple[int, int, int]] = []
        for pattern in (MD_CHINESE, MD_SEPARATED):
            for match in pattern.finditer(name):
                month, day = map(int, match.groups())
                if _valid_ymd(2000, month, day):
                    candidates.append((match.start(), month, day))
        for match in _compact_matches(name):
            month, day = map(int, match.groups())
            if _valid_ymd(2000, month, day):
                candidates.append((match.start(), month, day))
        if candidates:
            _, month, day = sorted(candidates, key=lambda item: item[0])[-1]
            date_value = month * 100 + day
            date_precision = "month_day"
            date_text = f"{month:02d}-{day:02d}"

    versions = list(VERSION.finditer(name))
    version = None
    if versions:
        match = versions[-1]
        version = (int(match.group(1)), int(match.group(2) or 0))
    issues = list(ISSUE.finditer(name))
    issue = int(issues[-1].group(1)) if issues else None
    return {
        "date_value": date_value,
        "date_precision": date_precision,
        "date_text": date_text,
        "version_major": version[0] if version else None,
        "version_minor": version[1] if version else None,
        "issue": issue,
    }


def _strip_temporal_noise(stem: str) -> str:
    value = stem.lower()
    for pattern in (FULL_DATE, MD_CHINESE, MD_SEPARATED):
        value = pattern.sub(" ", value)
    value = MD_COMPACT.sub(lambda match: " " if _compact_is_date_context(value, match) else match.group(0), value)
    value = VERSION.sub(" ", value)
    value = ISSUE.sub(" ", value)
    value = COPY_MARKERS.sub(" ", value)
    value = EDITION_MARKERS.sub(" ", value)
    value = re.sub(r"\((?:\d+|副本|copy)\)", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[\[\]【】（）()]+", " ", value)
    value = re.sub(r"[_\-.—–\s]+", " ", value).strip()
    return value


def series_title(path: str) -> str:
    pure = PurePosixPath(_clean_path(path))
    title = _strip_temporal_noise(pure.stem)
    aliases = {"开发任务": "工作任务", "工作任务": "工作任务"}
    return aliases.get(title, title or pure.stem.lower())


def series_key(path: str) -> str:
    clean = _clean_path(path)
    pure = PurePosixPath(clean)
    title = series_title(path)
    parent = pure.parent.as_posix().lower()
    scope = parent if title in PARENT_SENSITIVE_STEMS or len(title) < 4 else "*"
    return f"{scope}::{title}"


def series_id(path: str) -> str:
    return "series-" + hashlib.sha1(series_key(path).encode("utf-8")).hexdigest()[:16]


def source_quality(path: str, role: str) -> int:
    clean = _clean_path(path)
    name = PurePosixPath(clean).name
    depth = len(PurePosixPath(clean).parts)
    score = 50 + max(0, 12 - max(depth - 1, 0) * 3)
    if CURRENT_MARKERS.search(name):
        score += 12
    if COPY_MARKERS.search(clean):
        score -= 20
    if "__macosx" in clean.lower() or ".ds_store" in clean.lower():
        score -= 50
    score += {
        "progress": 14, "report": 12, "decision": 10, "requirement": 9,
        "test_result": 9, "handoff": 7, "design": 5, "interface": 5,
        "deployment": 4, "document": 2, "output": 1, "code": 0,
    }.get(role, 0)
    return score


def _analysis_text(item: dict[str, Any]) -> str:
    analysis = item.get("analysis") or {}
    chunks = [str(analysis.get("summary") or "")]
    for fact in analysis.get("facts") or []:
        if isinstance(fact, dict):
            chunks.append(str(fact.get("text") or ""))
    return "\n".join(chunk for chunk in chunks if chunk)


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _metadata_date(item: dict[str, Any]) -> date | None:
    parser = item.get("parser") or {}
    for value in (
        item.get("document_modified_at"), item.get("document_created_at"),
        parser.get("document_modified_at"), parser.get("document_created_at"),
    ):
        parsed = _parse_iso_date(value)
        if parsed:
            return parsed
    return None


def _mtime_date(item: dict[str, Any]) -> date | None:
    parser = item.get("parser") or {}
    for value in (item.get("modified_at"), item.get("mtime"), parser.get("modified_at"), parser.get("mtime")):
        parsed = _parse_iso_date(value)
        if parsed:
            return parsed
    return None


def document_temporal(item: dict[str, Any], *, reference_year: int) -> dict[str, Any]:
    path = str(item.get("path") or "")
    body = _analysis_text(item)
    body_date, precision = _extract_date(body, reference_year=reference_year, allow_compact=False)
    if body_date:
        return {"document_date": body_date.isoformat(), "date_source": "body", "date_confidence": "high", "date_precision": precision}

    hints = infer_temporal_hints(path)
    if hints.get("date_value"):
        value = int(hints["date_value"])
        if hints.get("date_precision") == "day":
            parsed = _valid_ymd(value // 10000, (value // 100) % 100, value % 100)
        else:
            parsed = _valid_ymd(reference_year, value // 100, value % 100)
        if parsed:
            confidence = "high" if hints.get("date_precision") == "day" else "medium"
            return {"document_date": parsed.isoformat(), "date_source": "filename", "date_confidence": confidence, "date_precision": hints.get("date_precision")}

    metadata = _metadata_date(item)
    if metadata:
        return {"document_date": metadata.isoformat(), "date_source": "metadata", "date_confidence": "low", "date_precision": "day"}
    modified = _mtime_date(item)
    if modified:
        return {"document_date": modified.isoformat(), "date_source": "mtime", "date_confidence": "low", "date_precision": "day"}
    return {"document_date": None, "date_source": "undated", "date_confidence": "none", "date_precision": None}


def reference_year_for_items(items: list[dict[str, Any]], fallback_year: int | None = None) -> int:
    years: list[int] = []
    for item in items:
        body_match = list(FULL_DATE.finditer(_analysis_text(item)))
        if body_match:
            years.extend(int(match.group(1)) for match in body_match)
        hint = infer_temporal_hints(str(item.get("path") or ""))
        value = int(hint.get("date_value") or 0)
        if value >= 10_000_00:
            years.append(value // 10000)
        for candidate in (_metadata_date(item), _mtime_date(item)):
            if candidate:
                years.append(candidate.year)
    return max(years) if years else (fallback_year or date.today().year)


def freshness_sort_key(item: dict[str, Any], *, reference_year: int) -> tuple[int, int, int, int, int, str]:
    path = str(item.get("path") or "")
    role = str(item.get("role") or "document")
    temporal = document_temporal(item, reference_year=reference_year)
    parsed = _parse_iso_date(temporal.get("document_date"))
    hints = infer_temporal_hints(path)
    issue = int(hints.get("issue") or 0)
    version = int(hints.get("version_major") or 0) * 1000 + int(hints.get("version_minor") or 0)
    date_source = str(temporal.get("date_source") or "undated")
    if date_source == "body":
        source_rank = 5
        primary = parsed.toordinal() if parsed else 0
    elif date_source == "filename":
        source_rank = 4
        primary = parsed.toordinal() if parsed else 0
    elif issue or version:
        source_rank = 3
        primary = issue * 1_000_000 + version
    elif date_source == "metadata":
        source_rank = 2
        primary = parsed.toordinal() if parsed else 0
    elif date_source == "mtime":
        source_rank = 1
        primary = parsed.toordinal() if parsed else 0
    else:
        source_rank = 0
        primary = 0
    return source_rank, primary, issue, version, source_quality(path, role), path


def classify_latest_freshness(role: str, document_date: date | None, reference_date: date | None) -> str:
    if document_date is None:
        return "undated"
    if role in STABLE_ROLES:
        return "current"
    if reference_date is None:
        return "current"
    age = max(0, (reference_date - document_date).days)
    if age <= 14:
        return "current"
    if age <= 35:
        return "recent"
    return "historical"


def resolve_month_day_year(value: date, absolute_reference: date | None) -> date:
    if absolute_reference and value > absolute_reference + timedelta(days=45):
        try:
            return value.replace(year=value.year - 1)
        except ValueError:
            return value
    return value
