from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

MATERIAL_LABELS = {
    "feature_list": "功能清单",
    "requirement": "需求与需求说明",
    "weekly_report": "项目周报",
    "monthly_report": "月报",
    "daily_report": "日报",
    "contract": "合同",
    "contract_supplement": "补充协议",
    "contract_attachment": "合同附件",
    "meeting": "会议纪要",
    "test": "测试与验证",
    "standard": "标准规范",
    "design": "设计与方案",
    "deployment": "部署与交付",
    "handoff": "交接材料",
    "output": "输出成果",
    "data": "数据材料",
    "document": "其他资料",
}

PERIODIC_TYPES = {"weekly_report", "monthly_report", "daily_report"}
CONTRACT_TYPES = {"contract", "contract_supplement", "contract_attachment"}
CURRENT_STATUSES = {"current", "latest_period", "primary", "active_related", "single"}


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _dt_key(value: Any) -> float:
    parsed = _parse_dt(value)
    return parsed.timestamp() if parsed else 0.0


def _name(path: str) -> str:
    return PurePosixPath(path).name


def _parent(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return "" if parent == "." else parent


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").lstrip("./").strip()


def _material_type(path: str, role: str = "") -> str:
    text = f"{path} {role}".lower()
    name = _name(path).lower()
    if "补充协议" in text or "补充合同" in text:
        return "contract_supplement"
    if "合同" in text and any(word in text for word in ("附件", "清单", "技术协议附件")):
        return "contract_attachment"
    if "合同" in text or "contract" in text:
        return "contract"
    if "周报" in text or "weekly" in text:
        return "weekly_report"
    if "月报" in text or "monthly" in text:
        return "monthly_report"
    if "日报" in text or "daily" in text:
        return "daily_report"
    if any(word in text for word in ("功能清单", "功能列表", "功能表", "feature list", "feature_list")):
        return "feature_list"
    if any(word in text for word in ("需求", "requirement", "prd")):
        return "requirement"
    if any(word in text for word in ("会议纪要", "会议记录", "meeting")):
        return "meeting"
    if any(word in text for word in ("测试", "验证", "评测", "验收", "test", "qa")):
        return "test"
    if any(word in text for word in ("标准", "规范", "规程", "导则", "standard")):
        return "standard"
    if any(word in text for word in ("部署", "上线", "交付", "docker", "deploy")):
        return "deployment"
    if any(word in text for word in ("交接", "移交", "handoff")):
        return "handoff"
    if any(word in text for word in ("设计", "方案", "架构", "architecture", "design")):
        return "design"
    if role == "output" or any(word in text for word in ("输出", "成果", "result")):
        return "output"
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in {".csv", ".json", ".jsonl", ".parquet"}:
        return "data"
    if role in {"test_result"}:
        return "test"
    if role in {"requirement"}:
        return "requirement"
    if role in {"report"}:
        return "document"
    if role in {"design", "interface"}:
        return "design"
    if role in {"deployment"}:
        return "deployment"
    if role in {"handoff"}:
        return "handoff"
    return "document"


def _series_stem(path: str, material_type: str) -> str:
    stem = PurePosixPath(path).stem.lower().strip()
    stem = re.sub(r"\s+", "", stem)
    stem = re.sub(r"(?:副本|复制|copy)(?:\(\d+\)|\d+)?$", "", stem, flags=re.IGNORECASE)
    if material_type in PERIODIC_TYPES:
        stem = re.sub(r"第?\d+期", "", stem)
        stem = re.sub(r"20\d{2}[-_.年]?\d{1,2}[-_.月]?\d{1,2}日?", "", stem)
        stem = re.sub(r"\d{4}[-_.]\d{1,2}[-_.]\d{1,2}", "", stem)
    else:
        stem = re.sub(r"(?:最终修改|最终版|最新版|正式版|修订版|修改版|最终|final)$", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"(?:[_\-. ]?(?:v|ver|version)?\d+(?:[._-]\d+)+)$", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"(?:[_\-. ]?\d{4}[_\-.]\d{1,2}(?:[_\-.]\d{1,2})?)$", "", stem)
        stem = re.sub(r"\(\d+\)$", "", stem)
    stem = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", stem)
    return stem or PurePosixPath(path).stem.lower()


def _auto_series_id(path: str, material_type: str) -> str:
    parent = _parent(path).lower()
    stem = _series_stem(path, material_type)
    return f"auto:{material_type}:{parent}:{stem}"[:500]


def _context_sources(latest_snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for snapshot in latest_snapshots:
        payload = snapshot.get("payload") or {}
        context = ((payload.get("project_intelligence") or {}).get("context") or {})
        data = context.get("data")
        if not context.get("present") or not context.get("valid") or not isinstance(data, dict):
            continue
        generated_at = data.get("generated_at") or context.get("modified_at") or snapshot.get("observed_at")
        sources.append(
            {
                "workspace_name": snapshot.get("workspace_name"),
                "user_id": snapshot.get("user_id"),
                "device_id": snapshot.get("device_id"),
                "observed_at": snapshot.get("observed_at"),
                "generated_at": generated_at,
                "modified_at": context.get("modified_at"),
                "data": data,
            }
        )
    sources.sort(key=lambda item: _dt_key(item.get("generated_at") or item.get("observed_at")), reverse=True)
    return sources


def _context_maps(context: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    important: dict[str, dict[str, Any]] = {}
    for raw in context.get("important_files") or []:
        if not isinstance(raw, dict):
            continue
        path = _normalize_path(raw.get("path"))
        if path:
            important[path] = raw

    series_defs: list[dict[str, Any]] = []
    for index, raw in enumerate(context.get("document_series") or [], start=1):
        if not isinstance(raw, dict):
            continue
        known = raw.get("known_files") or raw.get("files") or []
        paths: list[str] = []
        for item in known:
            path = _normalize_path(item.get("path") if isinstance(item, dict) else item)
            if path:
                paths.append(path)
        current = _normalize_path(raw.get("current_file"))
        if current and current not in paths:
            paths.append(current)
        if not paths:
            continue
        series_defs.append(
            {
                "series_id": str(raw.get("series_id") or f"context-series-{index}"),
                "name": str(raw.get("name") or raw.get("title") or PurePosixPath(paths[0]).stem),
                "current_file": current or None,
                "paths": paths,
                "purpose": raw.get("purpose"),
                "relationship": raw.get("relationship"),
            }
        )

    folders: list[dict[str, Any]] = []
    for raw in context.get("folders") or []:
        if not isinstance(raw, dict):
            continue
        path = _normalize_path(raw.get("path")).rstrip("/")
        if path:
            folders.append({**raw, "path": path})
    folders.sort(key=lambda item: len(str(item.get("path") or "")), reverse=True)
    return important, series_defs, folders


def _context_series_for(path: str, series_defs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for definition in series_defs:
        if path in definition.get("paths", []):
            return definition
    return None


def _folder_info(path: str, folders: list[dict[str, Any]]) -> dict[str, Any] | None:
    for folder in folders:
        prefix = str(folder.get("path") or "")
        if path == prefix or path.startswith(prefix + "/"):
            return folder
    return None


def _snapshot_file_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    payload = snapshot.get("payload") or {}
    for raw in (payload.get("files") or {}).get("files") or []:
        if not isinstance(raw, dict) or raw.get("sensitive"):
            continue
        path = _normalize_path(raw.get("path"))
        if path:
            result[path] = raw
    return result


def _analysis_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in ((snapshot.get("payload") or {}).get("analysis") or {}).get("items") or []:
        if not isinstance(raw, dict):
            continue
        path = _normalize_path(raw.get("path"))
        if path:
            result[path] = raw
    return result


def _search_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    index = (((snapshot.get("payload") or {}).get("project_intelligence") or {}).get("search_index") or {})
    for raw in index.get("items") or []:
        if not isinstance(raw, dict):
            continue
        path = _normalize_path(raw.get("path"))
        if path:
            result[path] = raw
    return result


def _m1_series_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    memory = (((snapshot.get("payload") or {}).get("analysis") or {}).get("current_project_memory") or {})
    for series in memory.get("document_series") or []:
        if not isinstance(series, dict):
            continue
        current = _normalize_path(series.get("current_path"))
        if current:
            result[current] = {**series, "m1_state": "current"}
        for path in series.get("historical_paths") or []:
            normalized = _normalize_path(path)
            if normalized:
                result[normalized] = {**series, "m1_state": "historical"}
    return result


def _context_age_days(context_source: dict[str, Any] | None) -> int | None:
    if not context_source:
        return None
    generated = _parse_dt(context_source.get("generated_at"))
    if not generated:
        return None
    return max((datetime.now(timezone.utc) - generated.astimezone(timezone.utc)).days, 0)


def _build_recent_changes(history_snapshots: list[dict[str, Any]], material_types: dict[str, str]) -> list[dict[str, Any]]:
    by_workspace: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for snapshot in history_snapshots:
        key = (
            str(snapshot.get("user_id") or ""),
            str(snapshot.get("device_id") or ""),
            str(snapshot.get("workspace_name") or ""),
        )
        by_workspace[key].append(snapshot)

    changes: list[dict[str, Any]] = []
    for key, snapshots in by_workspace.items():
        snapshots.sort(key=lambda item: int(item.get("id") or 0), reverse=True)
        if len(snapshots) < 2:
            continue
        latest, previous = snapshots[0], snapshots[1]
        latest_files = _snapshot_file_map(latest)
        previous_files = _snapshot_file_map(previous)
        observed_at = latest.get("observed_at")
        for path in sorted(set(latest_files) | set(previous_files)):
            before = previous_files.get(path)
            after = latest_files.get(path)
            if before is None and after is not None:
                change_type = "added"
            elif before is not None and after is None:
                change_type = "removed"
            elif str((before or {}).get("sha256") or "") != str((after or {}).get("sha256") or ""):
                change_type = "modified"
            else:
                continue
            changes.append(
                {
                    "change_type": change_type,
                    "path": path,
                    "name": _name(path),
                    "material_type": material_types.get(path) or _material_type(path),
                    "material_type_label": MATERIAL_LABELS.get(material_types.get(path) or _material_type(path), "其他资料"),
                    "observed_at": observed_at,
                    "workspace_name": key[2],
                    "user_id": key[0],
                    "modified_at": (after or before or {}).get("modified_at"),
                }
            )

        latest_context = (((latest.get("payload") or {}).get("project_intelligence") or {}).get("context") or {}).get("data")
        previous_context = (((previous.get("payload") or {}).get("project_intelligence") or {}).get("context") or {}).get("data")
        if isinstance(latest_context, dict) and isinstance(previous_context, dict):
            if json.dumps(latest_context, ensure_ascii=False, sort_keys=True) != json.dumps(previous_context, ensure_ascii=False, sort_keys=True):
                changes.append(
                    {
                        "change_type": "context_updated",
                        "path": ".project-intelligence/project_context.yaml",
                        "name": "项目认知",
                        "material_type": "document",
                        "material_type_label": "项目认知",
                        "observed_at": observed_at,
                        "workspace_name": key[2],
                        "user_id": key[0],
                        "modified_at": (((latest.get("payload") or {}).get("project_intelligence") or {}).get("context") or {}).get("modified_at"),
                    }
                )

    changes.sort(key=lambda item: _dt_key(item.get("observed_at") or item.get("modified_at")), reverse=True)
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in changes:
        key = (str(item.get("change_type")), str(item.get("path")), str(item.get("workspace_name")))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= 80:
            break
    return result


def build_project_intelligence(
    latest_snapshots: list[dict[str, Any]],
    history_snapshots: list[dict[str, Any]] | None = None,
    *,
    include_search_index: bool = False,
) -> dict[str, Any]:
    if not latest_snapshots:
        return {
            "version": 1,
            "context": {"available": False},
            "summary": {},
            "materials": [],
            "series": [],
            "relations": [],
            "recent_changes": [],
            "health": {"status": "empty", "issues": []},
        }

    context_sources = _context_sources(latest_snapshots)
    context_source = context_sources[0] if context_sources else None
    context = dict((context_source or {}).get("data") or {})
    important, series_defs, folders = _context_maps(context)

    variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_m1: dict[str, dict[str, Any]] = {}
    for snapshot in latest_snapshots:
        file_map = _snapshot_file_map(snapshot)
        analysis_map = _analysis_map(snapshot)
        search_map = _search_map(snapshot)
        m1_map = _m1_series_map(snapshot)
        all_m1.update(m1_map)
        all_paths = set(file_map) | set(analysis_map) | set(search_map)
        for path in all_paths:
            metadata = file_map.get(path) or {}
            analysis_item = analysis_map.get(path) or {}
            search_item = search_map.get(path) or {}
            analysis = analysis_item.get("analysis") or {}
            role = str(analysis_item.get("role") or "document")
            material_type = _material_type(path, role)
            context_series = _context_series_for(path, series_defs)
            folder = _folder_info(path, folders)
            important_info = important.get(path) or {}
            variant = {
                "path": path,
                "name": _name(path),
                "parent": _parent(path),
                "suffix": metadata.get("suffix") or PurePosixPath(path).suffix.lower(),
                "size": metadata.get("size"),
                "sha256": metadata.get("sha256") or analysis_item.get("sha256"),
                "modified_at": metadata.get("modified_at"),
                "system_changed_at": metadata.get("system_changed_at"),
                "role": role,
                "analysis_status": analysis_item.get("status"),
                "summary": str(analysis.get("summary") or "")[:1000],
                "facts": [fact for fact in (analysis.get("facts") or []) if isinstance(fact, dict)][:60],
                "material_type": material_type,
                "material_type_label": MATERIAL_LABELS.get(material_type, "其他资料"),
                "purpose": important_info.get("purpose") or (folder or {}).get("description") or (context_series or {}).get("purpose"),
                "importance": important_info.get("importance"),
                "folder_role": (folder or {}).get("role"),
                "workspace_name": snapshot.get("workspace_name"),
                "user_id": snapshot.get("user_id"),
                "device_id": snapshot.get("device_id"),
                "observed_at": snapshot.get("observed_at"),
                "context_series_id": (context_series or {}).get("series_id"),
                "context_series_name": (context_series or {}).get("name"),
                "context_current": bool(context_series and context_series.get("current_file") == path),
                "m1_series": m1_map.get(path),
                "search_index_enabled": bool(search_item),
            }
            if include_search_index:
                variant["_search_segments"] = list(search_item.get("segments") or [])[:120]
            variants[path].append(variant)

    materials: list[dict[str, Any]] = []
    workspace_conflicts: list[dict[str, Any]] = []
    for path, path_variants in variants.items():
        path_variants.sort(
            key=lambda item: (
                _dt_key(item.get("observed_at")),
                _dt_key(item.get("modified_at")),
            ),
            reverse=True,
        )
        selected = dict(path_variants[0])
        hashes = {str(item.get("sha256")) for item in path_variants if item.get("sha256")}
        selected["workspace_variant_count"] = len(path_variants)
        selected["workspace_hash_count"] = len(hashes)
        if len(hashes) > 1:
            selected["workspace_divergent"] = True
            workspace_conflicts.append(
                {
                    "type": "workspace_divergence",
                    "path": path,
                    "message": "不同开发工作区中的同路径文件内容不一致",
                    "workspace_count": len(path_variants),
                }
            )
        else:
            selected["workspace_divergent"] = False
        materials.append(selected)

    material_by_path = {item["path"]: item for item in materials}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for material in materials:
        context_series_id = material.get("context_series_id")
        m1_series = material.get("m1_series") or all_m1.get(material["path"]) or {}
        if context_series_id:
            series_id = f"context:{context_series_id}"
            series_title = material.get("context_series_name") or PurePosixPath(material["path"]).stem
            series_source = "agent_context"
        elif m1_series.get("series_id"):
            series_id = f"m1:{m1_series.get('series_id')}"
            series_title = m1_series.get("series_title") or PurePosixPath(material["path"]).stem
            series_source = "project_memory"
        else:
            series_id = _auto_series_id(material["path"], str(material.get("material_type") or "document"))
            series_title = _series_stem(material["path"], str(material.get("material_type") or "document"))
            series_source = "automatic"
        material["series_id"] = series_id
        material["series_title"] = series_title
        material["series_source"] = series_source
        groups[series_id].append(material)

    relations: list[dict[str, Any]] = []
    series_result: list[dict[str, Any]] = []
    for series_id, members in groups.items():
        members.sort(key=lambda item: (_dt_key(item.get("modified_at")), _dt_key(item.get("observed_at"))), reverse=True)
        material_type = str(members[0].get("material_type") or "document")
        current_path: str | None = None
        evidence: list[str] = []
        if material_type in PERIODIC_TYPES:
            current_path = members[0]["path"]
            for index, member in enumerate(members):
                member["version_status"] = "latest_period" if index == 0 else "period_history"
                if index > 0:
                    relations.append({"from": member["path"], "to": current_path, "relation": "periodic_snapshot"})
            evidence.append("周期型材料按时间保留全部期次，不把旧期次判为失效")
        elif material_type in CONTRACT_TYPES:
            main_candidates = [item for item in members if item.get("material_type") == "contract"]
            current_path = (main_candidates[0] if main_candidates else members[0])["path"]
            for member in members:
                if member["path"] == current_path:
                    member["version_status"] = "primary"
                else:
                    member["version_status"] = "active_related"
            evidence.append("合同类材料按主合同/补充协议/附件关系保留，不按更新时间互相替代")
        elif len(members) == 1:
            current_path = members[0]["path"]
            members[0]["version_status"] = "single"
        else:
            def current_score(item: dict[str, Any]) -> tuple[int, float, float]:
                score = 0
                if item.get("context_current"):
                    score += 1000
                m1 = item.get("m1_series") or all_m1.get(item["path"]) or {}
                if m1.get("m1_state") == "current":
                    score += 150
                elif m1.get("m1_state") == "historical":
                    score -= 50
                if re.search(r"最终版|最新版|正式版|final", item.get("name") or "", re.IGNORECASE):
                    score += 10
                return score, _dt_key(item.get("modified_at")), _dt_key(item.get("observed_at"))

            chosen = max(members, key=current_score)
            current_path = chosen["path"]
            if chosen.get("context_current"):
                evidence.append("开发侧 AI 明确认知指定当前文件")
            if (chosen.get("m1_series") or {}).get("m1_state") == "current":
                evidence.append("Project Memory V2 将其识别为当前版本")
            if not evidence:
                evidence.append("未发现更强版本证据，暂以系统修改时间与采集时间排序")
            for member in members:
                member["version_status"] = "current" if member["path"] == current_path else "historical"
                if member["path"] != current_path:
                    relations.append({"from": current_path, "to": member["path"], "relation": "supersedes"})

        series_result.append(
            {
                "series_id": series_id,
                "title": members[0].get("context_series_name") or members[0].get("series_title"),
                "material_type": material_type,
                "material_type_label": MATERIAL_LABELS.get(material_type, "其他资料"),
                "source": members[0].get("series_source"),
                "count": len(members),
                "current_path": current_path,
                "paths": [member["path"] for member in members],
                "evidence": evidence,
            }
        )

    # Contract relationships are additive rather than version replacement.
    contracts = [item for item in materials if item.get("material_type") == "contract"]
    for item in materials:
        if item.get("material_type") == "contract_supplement" and contracts:
            same_parent = [candidate for candidate in contracts if candidate.get("parent") == item.get("parent")]
            target = (same_parent or contracts)[0]
            relations.append({"from": item["path"], "to": target["path"], "relation": "supplements"})
        if item.get("material_type") == "contract" and re.search(r"盖章|签署|signed", item.get("name") or "", re.IGNORECASE):
            candidates = [candidate for candidate in contracts if candidate["path"] != item["path"] and candidate.get("parent") == item.get("parent")]
            if candidates:
                relations.append({"from": item["path"], "to": candidates[0]["path"], "relation": "signed_copy_of"})

    # Exact hash duplicates are retained but marked, never deleted automatically.
    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for material in materials:
        if material.get("sha256"):
            by_hash[str(material["sha256"])].append(material)
    duplicate_issues: list[dict[str, Any]] = []
    for same_hash in by_hash.values():
        unique_paths = sorted({item["path"] for item in same_hash})
        if len(unique_paths) < 2:
            continue
        canonical = unique_paths[0]
        duplicate_issues.append(
            {
                "type": "duplicate_content",
                "paths": unique_paths,
                "message": "检测到内容完全相同但路径不同的文件",
            }
        )
        for path in unique_paths[1:]:
            relations.append({"from": path, "to": canonical, "relation": "duplicate_of"})

    category_counts = Counter(str(item.get("material_type") or "document") for item in materials)
    materials.sort(
        key=lambda item: (
            0 if item.get("version_status") in CURRENT_STATUSES else 1,
            -_dt_key(item.get("modified_at")),
            item.get("path") or "",
        )
    )
    series_result.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("title") or "")))

    context_issues: list[dict[str, Any]] = []
    for definition in series_defs:
        current = definition.get("current_file")
        if current and current not in material_by_path:
            context_issues.append(
                {
                    "type": "context_file_missing",
                    "path": current,
                    "message": "开发侧 AI 认知指定的当前文件在本次采集材料中未找到",
                }
            )
    context_age = _context_age_days(context_source)
    if context_source and context_age is not None and context_age > 7:
        context_issues.append(
            {
                "type": "context_stale",
                "message": f"项目认知文件已有 {context_age} 天未更新",
                "age_days": context_age,
            }
        )

    search_enabled_count = sum(1 for item in materials if item.get("search_index_enabled"))
    health_issues = context_issues + workspace_conflicts + duplicate_issues
    health_status = "attention" if any(item.get("type") in {"context_file_missing", "workspace_divergence"} for item in health_issues) else "ok"
    if not context_source:
        health_issues.insert(0, {"type": "context_missing", "message": "尚未收到开发侧 AI 项目认知文件，当前仅根据真实材料自动理解"})
        health_status = "attention"

    project_info = context.get("project") if isinstance(context.get("project"), dict) else {}
    important_files = []
    for path, item in important.items():
        material = material_by_path.get(path)
        important_files.append(
            {
                "path": path,
                "purpose": item.get("purpose"),
                "importance": item.get("importance"),
                "available": material is not None,
                "version_status": (material or {}).get("version_status"),
            }
        )
    important_files.sort(key=lambda item: (0 if item.get("available") else 1, str(item.get("importance") or "")), reverse=False)

    material_types = {item["path"]: str(item.get("material_type") or "document") for item in materials}
    recent_changes = _build_recent_changes(history_snapshots or [], material_types)
    if not recent_changes:
        recent_changes = [
            {
                "change_type": "recently_modified",
                "path": item["path"],
                "name": item["name"],
                "material_type": item["material_type"],
                "material_type_label": item["material_type_label"],
                "modified_at": item.get("modified_at"),
                "observed_at": item.get("observed_at"),
                "workspace_name": item.get("workspace_name"),
            }
            for item in sorted(materials, key=lambda entry: _dt_key(entry.get("modified_at")), reverse=True)[:20]
            if item.get("modified_at")
        ]

    public_materials: list[dict[str, Any]] = []
    for material in materials:
        if include_search_index:
            public_materials.append(material)
        else:
            public_materials.append({key: value for key, value in material.items() if key != "_search_segments"})

    return {
        "version": 1,
        "context": {
            "available": bool(context_source),
            "generated_at": (context_source or {}).get("generated_at"),
            "modified_at": (context_source or {}).get("modified_at"),
            "source_count": len(context_sources),
            "age_days": context_age,
            "generator": context.get("generator") if context_source else None,
            "project": project_info,
            "folders": folders[:100],
            "known_facts": list(context.get("known_facts") or [])[:100],
            "current_work": list(context.get("current_work") or [])[:100],
            "known_issues": list(context.get("known_issues") or [])[:100],
            "workflows": list(context.get("workflows") or [])[:100],
            "important_files": important_files[:100],
        },
        "summary": {
            "material_count": len(materials),
            "series_count": len(series_result),
            "multi_version_series_count": sum(1 for item in series_result if int(item.get("count") or 0) > 1),
            "search_indexed_file_count": search_enabled_count,
            "recent_change_count": len(recent_changes),
            "health_issue_count": len(health_issues),
            "category_counts": dict(category_counts),
        },
        "material_categories": [
            {
                "type": material_type,
                "label": MATERIAL_LABELS.get(material_type, "其他资料"),
                "count": count,
            }
            for material_type, count in category_counts.most_common()
        ],
        "materials": public_materials[:2000],
        "series": series_result[:500],
        "relations": relations[:2000],
        "recent_changes": recent_changes[:80],
        "health": {
            "status": health_status,
            "issues": health_issues[:200],
            "duplicate_group_count": len(duplicate_issues),
            "workspace_divergence_count": len(workspace_conflicts),
        },
    }


def _normalized_search_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _match_score(query: str, text: str, weight: int) -> int:
    if not query or not text:
        return 0
    if query in text:
        return weight
    tokens = [token for token in re.split(r"\s+", query) if token]
    if len(tokens) > 1 and all(token in text for token in tokens):
        return max(weight // 2, 1)
    return 0


def search_project_intelligence(
    intelligence: dict[str, Any],
    query: str,
    *,
    material_type: str | None = None,
    current_only: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    q = _normalized_search_text(query)
    if not q:
        return {"query": query, "count": 0, "results": []}

    results: list[dict[str, Any]] = []
    for material in intelligence.get("materials") or []:
        if material_type and material.get("material_type") != material_type:
            continue
        if current_only and material.get("version_status") not in CURRENT_STATUSES:
            continue

        fields = {
            "文件名": _normalized_search_text(material.get("name")),
            "路径": _normalized_search_text(material.get("path")),
            "材料类型": _normalized_search_text(material.get("material_type_label")),
            "用途": _normalized_search_text(material.get("purpose")),
            "摘要": _normalized_search_text(material.get("summary")),
            "系列": _normalized_search_text(material.get("series_title")),
        }
        fact_text = "\n".join(str(item.get("text") or "") for item in material.get("facts") or [] if isinstance(item, dict))
        fields["关键信息"] = _normalized_search_text(fact_text)

        score = 0
        matched_fields: list[str] = []
        weights = {"文件名": 100, "路径": 70, "用途": 65, "关键信息": 55, "摘要": 45, "系列": 35, "材料类型": 25}
        for label, text in fields.items():
            matched = _match_score(q, text, weights[label])
            if matched:
                score += matched
                matched_fields.append(label)

        snippet = ""
        locator = None
        location_type = None
        for segment in material.get("_search_segments") or []:
            segment_text = _normalized_search_text(segment.get("text"))
            matched = _match_score(q, segment_text, 50)
            if not matched:
                continue
            score += matched
            matched_fields.append("正文")
            snippet = str(segment.get("text") or "")[:900]
            locator = segment.get("locator")
            location_type = segment.get("location_type")
            break

        if score <= 0:
            continue
        if not snippet:
            snippet = str(material.get("summary") or "")[:900]
            if not snippet:
                first_fact = next((item for item in material.get("facts") or [] if isinstance(item, dict) and item.get("text")), None)
                snippet = str((first_fact or {}).get("text") or "")[:900]

        result_material = {key: value for key, value in material.items() if key != "_search_segments"}
        results.append(
            {
                "score": score,
                "matched_fields": list(dict.fromkeys(matched_fields)),
                "snippet": snippet,
                "locator": locator,
                "location_type": location_type,
                "material": result_material,
            }
        )

    results.sort(
        key=lambda item: (
            int(item.get("score") or 0),
            _dt_key((item.get("material") or {}).get("modified_at")),
        ),
        reverse=True,
    )
    return {
        "query": query,
        "material_type": material_type,
        "current_only": current_only,
        "count": len(results),
        "results": results[: max(1, min(int(limit), 100))],
    }
