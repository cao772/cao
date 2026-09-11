from __future__ import annotations

import hashlib
import re
from typing import Any

TASK_ID_RE = re.compile(r"\b([A-Z][A-Z0-9_]{1,20}-\d+)\b", re.IGNORECASE)

LEADING_NOISE = re.compile(
    r"^(?:"
    r"已完成|已实现|已上线|已部署|已修复|已解决|已取消|完成|实现|开发|修复|新增|优化|调整|改造|"
    r"待开发|待实现|待修复|待优化|待调整|待改造|待完成|计划|需要|需|正在|进行中|"
    r"完成了|实现了|fixed|fix|feat|feature|add|added|implement|implemented|"
    r"optimize|optimized|update|updated|refactor|refactored|done|completed"
    r")[:：\s\-_/]*",
    re.IGNORECASE,
)
TRAILING_NOISE = re.compile(
    r"(?:功能|任务|需求|事项|开发任务|开发工作|实现说明|技术实现说明|测试完成|已完成)$",
    re.IGNORECASE,
)
SEPARATOR_RE = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff]+")
GENERIC_WORDS = {
    "项目", "当前", "相关", "功能", "任务", "需求", "事项", "页面", "接口", "模块", "系统",
    "开发", "实现", "修复", "优化", "调整", "改造", "新增", "完成", "进行", "说明",
    "test", "tests", "task", "feature", "fix", "done",
}


def extract_task_id(*values: Any) -> str | None:
    for value in values:
        match = TASK_ID_RE.search(str(value or ""))
        if match:
            return match.group(1).upper()
    return None


def clean_display_title(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    task_id = extract_task_id(text)
    text = TASK_ID_RE.sub("", text).strip(" :-_/\t")
    text = re.sub(r"^(?:本周|本月|本阶段|今日|今天|昨日|昨天|近期)[:：\s\-_/]*", "", text, flags=re.IGNORECASE)
    previous = None
    while text and text != previous:
        previous = text
        text = LEADING_NOISE.sub("", text).strip(" :-_/\t")
    text = TRAILING_NOISE.sub("", text).strip(" :-_/\t")
    if not text:
        return task_id or str(value or "").strip()
    return text


def normalized_title(value: Any) -> str:
    text = clean_display_title(value).lower()
    # Small deterministic aliases cover common UI/task wording without turning
    # identity into unrestricted semantic guessing.
    text = text.replace("资料上传更新页面", "资料上传更新").replace("资料上传更新页", "资料上传更新")
    text = text.replace("上传更新页", "上传更新").replace("资料更新页", "资料更新").replace("资料上传页", "资料上传")
    text = re.sub(r"左侧树状|左侧树形|左侧树|树状结构|树状页面|树形菜单|树状|树形", "树", text)
    text = re.sub(r"(?:页面|页)?改为", "", text)
    text = re.sub(r"(?:选择材料|交互|结构开发|页面开发|开发)$", "", text)
    text = re.sub(r"(?:测试)?\d+\s*/\s*\d+\s*(?:通过|pass(?:ed)?)$", "", text, flags=re.IGNORECASE)
    text = text.replace("资料更新", "资料上传更新").replace("上传更新", "资料上传更新")
    text = text.replace("资料资料上传更新", "资料上传更新")
    text = text.replace("资料上传更新", "资料上传")
    text = re.sub(r"(?:菜单|页面|页)$", "", text)
    text = re.sub(r"(?:改造|调整|修复)$", "", text)
    text = SEPARATOR_RE.sub("", text)
    return text


def _terms(value: Any) -> set[str]:
    text = clean_display_title(value).lower()
    result: set[str] = set()
    for token in re.findall(r"[a-z0-9_]{2,}", text):
        if token not in GENERIC_WORDS:
            result.add(token)
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if chunk not in GENERIC_WORDS:
            result.add(chunk)
        if len(chunk) >= 4:
            for size in (2, 3, 4):
                for index in range(len(chunk) - size + 1):
                    gram = chunk[index:index + size]
                    if gram not in GENERIC_WORDS:
                        result.add(gram)
    return result


def title_similarity(left: Any, right: Any) -> float:
    a = normalized_title(left)
    b = normalized_title(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
        shorter, longer = sorted((len(a), len(b)))
        ratio = shorter / longer
        if ratio >= 0.58:
            return max(0.82, ratio)
    left_terms = _terms(left)
    right_terms = _terms(right)
    if not left_terms or not right_terms:
        return 0.0
    intersection = len(left_terms & right_terms)
    union = len(left_terms | right_terms)
    jaccard = intersection / union if union else 0.0
    containment = intersection / min(len(left_terms), len(right_terms))
    return max(jaccard, containment * 0.86)


def identity_match(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    threshold: float = 0.72,
) -> tuple[bool, float, str]:
    left_id = extract_task_id(left.get("task_id"), left.get("title"), left.get("text"))
    right_id = extract_task_id(right.get("task_id"), right.get("title"), right.get("text"))
    if left_id and right_id:
        return (left_id == right_id, 1.0 if left_id == right_id else 0.0, "task_id")

    left_title = left.get("title") or left.get("text") or ""
    right_title = right.get("title") or right.get("text") or ""
    score = title_similarity(left_title, right_title)

    # When only one side has a formal ID, semantic fallback is deliberately stricter.
    effective = max(threshold, 0.82) if bool(left_id) ^ bool(right_id) else threshold
    if score >= effective:
        return True, score, "title"
    return False, score, "none"


def stable_task_key(*, task_id: Any = None, title: Any = None) -> str:
    explicit = extract_task_id(task_id, title)
    if explicit:
        return f"id:{explicit}"
    normalized = normalized_title(title)
    if not normalized:
        normalized = "unknown"
    digest = hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:14]
    return f"auto:{digest}"


def evidence_source_id(entry: dict[str, Any]) -> str:
    for key in ("source_id", "client_event_id", "commit_sha", "snapshot_id", "path", "remote_url", "session_id"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    raw = "|".join(
        str(entry.get(key) or "")
        for key in ("source", "kind", "text", "observed_at", "task_id", "repository_id", "branch")
    )
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
