from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
from typing import Any

from task_identity import (
    clean_display_title,
    evidence_source_id,
    extract_task_id,
    identity_match,
    normalized_title,
    stable_task_key,
    title_similarity,
)
from task_lifecycle import (
    CATEGORY_VALUES,
    classify_candidate,
    choose_compat_status,
    derive_task_lifecycle,
    relation_for_evidence,
)

TASK_INTELLIGENCE_VERSION = 2
NON_TASK_CATEGORIES = {
    "completion_record",
    "implementation_note",
    "test_evidence",
    "decision",
    "informational",
}


def facts_from_memory(memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer Project Memory V2 current facts; retain backward compatibility.

    Historical facts are intentionally excluded. Undated facts are returned only as
    low-confidence context and are never promoted to current tasks by this adapter.
    """
    current = memory.get("current_facts")
    if isinstance(current, list):
        return [dict(fact) for fact in current if isinstance(fact, dict)]

    facts: list[dict[str, Any]] = []
    mapping = {
        "requirements": "requirement",
        "tasks": "task",
        "tests": "test",
        "blockers": "blocker",
        "decisions": "decision",
        "progress": "progress",
    }
    for key, fact_type in mapping.items():
        for fact in memory.get(key) or []:
            if not isinstance(fact, dict):
                continue
            item = dict(fact)
            item.setdefault("type", fact_type)
            facts.append(item)
    return facts


def memory_candidates(memory: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for fact in facts_from_memory(memory):
        text = str(fact.get("text") or "").strip()
        if not text:
            continue
        hint = str(fact.get("type") or "").strip()
        category = classify_candidate(text, hint=hint)
        confidence = "low" if fact.get("freshness") == "undated" else "medium"
        if fact.get("freshness") == "historical":
            continue
        result.append(
            {
                "category": category,
                "text": text,
                "task_id": extract_task_id(text),
                "freshness": fact.get("freshness"),
                "confidence": confidence,
                "fact": fact,
            }
        )
    return result


def _normalized_evidence(entry: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(entry)
    evidence.setdefault("source_type", evidence.get("source") or "unknown")
    evidence.setdefault("source_id", evidence_source_id(evidence))
    evidence.setdefault("relation", relation_for_evidence(evidence))
    evidence.setdefault("confidence", "high" if evidence.get("task_id") else "medium")
    return evidence


def _candidate_type(item: dict[str, Any]) -> str:
    hint = str(item.get("origin_type") or "").strip() or None
    category = classify_candidate(item.get("title"), hint=hint)
    if category == "unknown" and item.get("task_id"):
        return "task"
    return category


def _best_match(
    probe: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    threshold: float = 0.72,
) -> tuple[dict[str, Any] | None, float, str]:
    best: tuple[dict[str, Any] | None, float, str] = (None, 0.0, "none")
    for target in targets:
        matched, score, reason = identity_match(probe, target, threshold=threshold)
        if matched and score > best[1]:
            best = (target, score, reason)
    return best


def _merge_evidence(target: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    seen = {
        (
            entry.get("source_type") or entry.get("source"),
            entry.get("source_id") or evidence_source_id(entry),
            entry.get("relation") or entry.get("kind"),
            entry.get("text"),
        )
        for entry in target.get("evidence") or []
    }
    for raw in entries:
        entry = _normalized_evidence(raw)
        key = (
            entry.get("source_type"),
            entry.get("source_id"),
            entry.get("relation"),
            entry.get("text"),
        )
        if key in seen:
            continue
        seen.add(key)
        target.setdefault("evidence", []).append(entry)


def _merge_task(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    _merge_evidence(target, incoming.get("evidence") or [])

    task_id = extract_task_id(target.get("task_id"), incoming.get("task_id"), incoming.get("title"))
    if task_id:
        target["task_id"] = task_id

    target.setdefault("_statuses", []).append(incoming.get("status"))
    target.setdefault("_origins", set()).update(
        str(value)
        for value in (
            list(incoming.get("origins") or [])
            + ([incoming.get("origin")] if incoming.get("origin") else [])
        )
        if value
    )
    target.setdefault("_contributors", set()).update(str(value) for value in incoming.get("contributors") or [] if value)
    target.setdefault("_workspace_contributions", []).extend(incoming.get("workspace_contributions") or [])

    current_title = str(target.get("title") or "")
    incoming_title = str(incoming.get("title") or "")
    current_clean = clean_display_title(current_title)
    incoming_clean = clean_display_title(incoming_title)
    if incoming_clean and (
        not current_clean
        or (extract_task_id(incoming.get("task_id"), incoming_title) and not extract_task_id(target.get("task_id"), current_title))
        or len(incoming_clean) < len(current_clean)
    ):
        target["title"] = incoming_clean


def _new_canonical(item: dict[str, Any], category: str) -> dict[str, Any]:
    task_id = extract_task_id(item.get("task_id"), item.get("title"))
    title = clean_display_title(item.get("title")) or task_id or str(item.get("title") or "")
    evidence = [_normalized_evidence(entry) for entry in item.get("evidence") or []]
    canonical = {
        **{key: deepcopy(value) for key, value in item.items() if key not in {"evidence", "origins", "contributors", "workspace_contributions"}},
        "task_id": task_id,
        "title": title,
        "normalized_title": normalized_title(title),
        "item_type": category if category in {"task", "issue"} else "task",
        "evidence": evidence,
        "_statuses": [item.get("status")],
        "_origins": set(str(value) for value in (item.get("origins") or []) if value),
        "_contributors": set(str(value) for value in (item.get("contributors") or []) if value),
        "_workspace_contributions": list(item.get("workspace_contributions") or []),
    }
    if item.get("origin"):
        canonical["_origins"].add(str(item.get("origin")))
    return canonical


def _candidate_evidence(item: dict[str, Any], category: str) -> dict[str, Any]:
    relation = {
        "completion_record": "completion",
        "implementation_note": "implementation",
        "test_evidence": "test",
        "decision": "decision",
        "informational": "information",
        "unknown": "information",
    }.get(category, "information")
    return _normalized_evidence(
        {
            "source": item.get("origin") or "document",
            "kind": category,
            "text": item.get("title") or "",
            "task_id": item.get("task_id"),
            "relation": relation,
            "confidence": "medium",
        }
    )


def _evidence_probe(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": entry.get("task_id"),
        "title": entry.get("task_title") or entry.get("title") or entry.get("text") or "",
    }


def _attach_unlinked(
    tasks: list[dict[str, Any]],
    unlinked: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    result: dict[str, list[dict[str, Any]]] = {}
    attached = 0
    for bucket, entries in unlinked.items():
        remaining: list[dict[str, Any]] = []
        for raw in entries or []:
            entry = _normalized_evidence(raw)
            probe = _evidence_probe(entry)
            target, score, linked_by = _best_match(probe, tasks, threshold=0.74)
            if target is None:
                remaining.append(entry)
                continue
            entry["task_intelligence_match_score"] = round(score, 3)
            entry["task_intelligence_linked_by"] = linked_by
            _merge_evidence(target, [entry])
            attached += 1
        result[bucket] = remaining
    return result, attached


def _timestamps(evidence: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    values: list[str] = []
    for entry in evidence:
        raw = str(entry.get("observed_at") or "").strip()
        if not raw:
            continue
        try:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        values.append(raw)
    if not values:
        return None, None
    return min(values), max(values)


def _task_confidence(item: dict[str, Any]) -> str:
    if item.get("task_id"):
        return "high"
    sources = {entry.get("source_type") for entry in item.get("evidence") or [] if entry.get("source_type")}
    relations = {entry.get("relation") for entry in item.get("evidence") or [] if entry.get("relation")}
    if len(sources) >= 2 or {"requirement", "implementation"} <= relations:
        return "high"
    if item.get("evidence"):
        return "medium"
    return "low"


def _finalize(item: dict[str, Any]) -> dict[str, Any]:
    statuses = [status for status in item.pop("_statuses", []) if status]
    item["status"] = choose_compat_status(statuses + [item.get("status")])
    item["origins"] = sorted(item.pop("_origins", set()))
    item["contributors"] = sorted(item.pop("_contributors", set()))
    item["workspace_contributions"] = item.pop("_workspace_contributions", [])

    evidence = [_normalized_evidence(entry) for entry in item.get("evidence") or []]
    if not item.get("task_id"):
        for entry in evidence:
            recovered = extract_task_id(entry.get("task_id"), entry.get("text"))
            if recovered:
                item["task_id"] = recovered
                break
    item["evidence"] = evidence
    item["evidence_count"] = len(evidence)
    item["evidence_sources"] = sorted({str(entry.get("source_type") or "") for entry in evidence if entry.get("source_type")})
    item["repositories"] = sorted({str(entry.get("repository_id") or "") for entry in evidence if entry.get("repository_id")})
    item["branches"] = sorted({str(entry.get("branch") or "") for entry in evidence if entry.get("branch")})

    first_seen, last_seen = _timestamps(evidence)
    item["first_seen_at"] = first_seen
    item["last_seen_at"] = last_seen

    item["normalized_title"] = normalized_title(item.get("title"))
    item["task_key"] = stable_task_key(task_id=item.get("task_id"), title=item.get("title"))
    item["confidence"] = _task_confidence(item)

    lifecycle = derive_task_lifecycle(item)
    item.update(lifecycle)
    item["status_label"] = item.get("status_label") or lifecycle["task_status_label"]
    return item


def apply_task_intelligence(
    fusion: dict[str, Any],
    *,
    memories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize task identity/lifecycle after evidence fusion.

    This layer does not redefine formal completion. It keeps the compatibility
    `status` produced by Evidence Fusion/remote evidence and adds a finer
    `task_status`, stable `task_key`, normalized evidence relations and flags.
    """
    result = deepcopy(fusion)
    raw_items = [dict(item) for item in (fusion.get("work_items") or []) if isinstance(item, dict)]

    canonical: list[dict[str, Any]] = []
    deferred: list[tuple[dict[str, Any], str]] = []
    merged_count = 0

    # Strong current-task seeds first. This prevents completion/test/implementation
    # prose from becoming fresh planned tasks.
    for item in raw_items:
        category = _candidate_type(item)
        if category in {"task", "issue"}:
            probe = {
                "task_id": item.get("task_id"),
                "title": item.get("title"),
            }
            target, _, _ = _best_match(probe, canonical, threshold=0.74)
            if target is None:
                canonical.append(_new_canonical(item, category))
            else:
                _merge_task(target, item)
                merged_count += 1
        else:
            deferred.append((item, category))

    filtered_evidence: list[dict[str, Any]] = []
    for item, category in deferred:
        probe = {"task_id": item.get("task_id"), "title": item.get("title")}
        target, score, linked_by = _best_match(probe, canonical, threshold=0.74)
        evidence = list(item.get("evidence") or [])
        evidence.append(_candidate_evidence(item, category))
        if target is None:
            filtered_evidence.extend(evidence)
            continue
        normalized = []
        for entry in evidence:
            enriched = _normalized_evidence(entry)
            enriched["task_intelligence_match_score"] = round(score, 3)
            enriched["task_intelligence_linked_by"] = linked_by
            normalized.append(enriched)
        _merge_evidence(target, normalized)

    # Project Memory V2 adapter: if callers provide memories, current_facts can add
    # missing task/issue seeds. Historical/undated material is never promoted.
    memory_seed_count = 0
    for memory in memories or []:
        for candidate in memory_candidates(memory):
            if candidate["category"] not in {"task", "issue"}:
                continue
            if candidate.get("freshness") == "undated":
                continue
            probe = {"task_id": candidate.get("task_id"), "title": candidate.get("text")}
            target, _, _ = _best_match(probe, canonical, threshold=0.74)
            fact = candidate["fact"]
            evidence = _normalized_evidence(
                {
                    "source": "document",
                    "kind": str(fact.get("type") or "task"),
                    "text": candidate["text"],
                    "path": fact.get("path"),
                    "observed_at": fact.get("source_date"),
                    "task_id": candidate.get("task_id"),
                    "relation": relation_for_evidence({"kind": fact.get("type"), "text": candidate["text"]}),
                    "confidence": candidate.get("confidence"),
                }
            )
            if target is not None:
                _merge_evidence(target, [evidence])
                continue
            seed = {
                "task_id": candidate.get("task_id"),
                "title": candidate["text"],
                "status": "planned",
                "status_label": "待开发",
                "origin": "document",
                "origin_type": fact.get("type") or "task",
                "evidence": [evidence],
            }
            canonical.append(_new_canonical(seed, candidate["category"]))
            memory_seed_count += 1

    unlinked, attached_unlinked = _attach_unlinked(
        canonical,
        {
            key: list(value or [])
            for key, value in (fusion.get("unlinked_evidence") or {}).items()
        },
    )
    if filtered_evidence:
        unlinked.setdefault("task_intelligence", []).extend(_normalized_evidence(entry) for entry in filtered_evidence)

    work_items = [_finalize(item) for item in canonical]
    work_items.sort(key=lambda item: (item.get("task_status") == "completed", item.get("last_seen_at") or "", item.get("title") or ""), reverse=True)

    lifecycle_counts = Counter(str(item.get("task_status") or "unknown") for item in work_items)
    type_counts = Counter(str(item.get("item_type") or "task") for item in work_items)
    flags = Counter(flag for item in work_items for flag in item.get("flags") or [])

    summary = dict(fusion.get("summary") or {})
    summary["work_item_count"] = len(work_items)
    summary["task_intelligence"] = {
        "version": TASK_INTELLIGENCE_VERSION,
        "merged_duplicate_count": merged_count,
        "filtered_non_task_count": len(deferred),
        "memory_seed_count": memory_seed_count,
        "reattached_unlinked_evidence_count": attached_unlinked,
        "lifecycle_counts": dict(lifecycle_counts),
        "item_type_counts": dict(type_counts),
        "flag_counts": dict(flags),
    }

    result.update(
        {
            "work_items": work_items,
            "unlinked_evidence": unlinked,
            "summary": summary,
            "task_summary": {
                "total": len(work_items),
                "lifecycle_counts": dict(lifecycle_counts),
                "item_type_counts": dict(type_counts),
                "flag_counts": dict(flags),
            },
            "task_intelligence_version": TASK_INTELLIGENCE_VERSION,
            "diagnostics": {
                **dict(fusion.get("diagnostics") or {}),
                "task_intelligence": {
                    "input_work_item_count": len(raw_items),
                    "output_work_item_count": len(work_items),
                    "merged_duplicate_count": merged_count,
                    "filtered_non_task_count": len(deferred),
                    "reattached_unlinked_evidence_count": attached_unlinked,
                    "formal_completion_source": "evidence_fusion",
                    "progress_percentage_generated": False,
                },
            },
        }
    )
    return result
