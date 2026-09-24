from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

DEFAULT_START = "09:00"
DEFAULT_END = "20:00"
DEFAULT_INTERVAL_MINUTES = 30

CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "requirement": ("需求", "需要", "新增", "增加", "支持", "要做", "希望"),
    "decision": ("决定", "确定", "确认", "就按", "按这个", "以", "为准"),
    "change": ("改成", "修改", "调整", "替换", "不要了", "版本", "变更"),
    "task": ("负责", "处理", "跟进", "完成", "你来", "麻烦"),
    "blocker": ("阻塞", "卡住", "失败", "报错", "连不上", "问题", "异常"),
    "confirmation": ("通过", "验收", "确认", "完成", "没问题", "可以了"),
}
DEADLINE_RE = re.compile(
    r"(今天|明天|后天|本周|下周|周[一二三四五六日天]|星期[一二三四五六日天]|"
    r"\d{1,2}[月/-]\d{1,2}[日号]?|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}).{0,12}(前|之前|完成|提交|给|交)"
)


def parse_clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":", 1))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("invalid clock")
    return time(hour=hour, minute=minute)


def normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(raw or {})
    start = str(raw.get("start_time") or DEFAULT_START)
    end = str(raw.get("end_time") or DEFAULT_END)
    interval = int(raw.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES)
    parse_clock(start)
    parse_clock(end)
    if interval < 5 or interval > 240:
        raise ValueError("interval_minutes must be between 5 and 240")
    if parse_clock(start) > parse_clock(end):
        raise ValueError("start_time must not be later than end_time")

    bindings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw.get("bindings") or []:
        if not isinstance(item, dict):
            continue
        project_id = str(item.get("project_id") or "").strip()
        group_name = str(item.get("group_name") or "").strip()
        if not project_id or not group_name:
            continue
        key = (project_id, group_name)
        if key in seen:
            continue
        seen.add(key)
        bindings.append(
            {
                "project_id": project_id,
                "project_name": str(item.get("project_name") or project_id).strip() or project_id,
                "group_name": group_name,
            }
        )
    return {
        "version": 1,
        "enabled": bool(raw.get("enabled", True)),
        "start_time": start,
        "end_time": end,
        "interval_minutes": interval,
        "bindings": bindings,
    }


def within_window(now: datetime, start: str, end: str) -> bool:
    start_t = parse_clock(start)
    end_t = parse_clock(end)
    current = now.timetz().replace(tzinfo=None)
    return start_t <= current <= end_t


def scheduled_slot(now: datetime, start: str, end: str, interval_minutes: int) -> datetime | None:
    if not within_window(now, start, end):
        return None
    start_t = parse_clock(start)
    anchor = now.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
    elapsed = int((now - anchor).total_seconds() // 60)
    if elapsed < 0 or elapsed % interval_minutes:
        return None
    return anchor + timedelta(minutes=elapsed)


def next_run_at(now: datetime, start: str, end: str, interval_minutes: int) -> datetime:
    start_t = parse_clock(start)
    end_t = parse_clock(end)
    start_today = now.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
    end_today = now.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
    if now < start_today:
        return start_today
    if now > end_today:
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)

    elapsed = max((now - start_today).total_seconds() / 60, 0)
    slots = int(elapsed // interval_minutes)
    exact = elapsed == slots * interval_minutes
    candidate = start_today + timedelta(minutes=(slots if exact else slots + 1) * interval_minutes)
    if candidate < now:
        candidate += timedelta(minutes=interval_minutes)
    if candidate > end_today:
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
    return candidate


def classify_message(text: str) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    categories: list[str] = []
    for category, terms in CATEGORY_PATTERNS.items():
        if any(term in normalized for term in terms):
            categories.append(category)
    if DEADLINE_RE.search(normalized):
        categories.append("deadline")
    return list(dict.fromkeys(categories))


def event_fingerprint(
    *,
    project_id: str,
    group_name: str,
    sender: str | None,
    text: str,
    observed_at: str | None,
    message_type: str = "text",
) -> str:
    minute = str(observed_at or "")[:16]
    canonical = json.dumps(
        {
            "project_id": project_id,
            "group_name": group_name,
            "sender": sender or "",
            "text": " ".join(text.split()),
            "observed_minute": minute,
            "message_type": message_type,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class SeenState:
    path: Path
    max_items: int = 20000

    def load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        return {str(item) for item in (data.get("fingerprints") or [])}

    def save(self, fingerprints: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        values = sorted(fingerprints)[-self.max_items :]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "fingerprints": values}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
