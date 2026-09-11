from __future__ import annotations

from typing import Any

import evidence_lifecycle_v2_impl as _impl


# Integration adapter: explicit producer semantics win over legacy inference.
# The normalized/public evidence keeps those producer values unchanged.  A separate
# adjudication view translates only known compatibility relations so the formal M3
# judge can consume M2/M5 evidence without rewriting the evidence contract.
_original_relation = _impl._relation
_original_source_type = _impl._source_type
_original_formal_status = _impl._formal_status
_original_upgrade_fusion_result = _impl.upgrade_fusion_result

_AGENT_RELATION_ALIASES = {
    "agent_finished": "completion_claim",
    "agent_test_pass": "test_pass",
    "agent_test_fail": "test_fail",
    "agent_blocker": "blocker",
    "agent_started": "progress_claim",
    "agent_progress": "progress_claim",
}
_GENERIC_M2_RELATIONS = {
    "completion",
    "implementation",
    "test",
    "commit",
    "merge_request",
    "ci",
    "deployment",
    "progress",
}


def _preferred_relation(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("relation") or "").strip()
    if explicit:
        return explicit
    return _original_relation(entry)


def _preferred_source_type(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("source_type") or "").strip()
    if explicit:
        return explicit
    return _original_source_type(entry)


def _adjudication_relation(entry: dict[str, Any]) -> str:
    relation = str(entry.get("relation") or "")
    if relation in _AGENT_RELATION_ALIASES:
        return _AGENT_RELATION_ALIASES[relation]
    if relation not in _GENERIC_M2_RELATIONS:
        return relation

    raw = entry.get("raw") if isinstance(entry.get("raw"), dict) else {}
    inferred = _original_relation(raw)
    if inferred and inferred not in {"other", relation}:
        return inferred

    # Compatibility fallbacks for M2 evidence that intentionally exposes a generic
    # relation while keeping enough source/kind information for deterministic use.
    if relation == "implementation":
        return "local_change"
    if relation == "completion":
        return "completion_claim"
    return relation


def _adjudication_source_type(entry: dict[str, Any], relation: str) -> str:
    source_type = str(entry.get("source_type") or "")
    if source_type == "git_local":
        return "local_git"
    if source_type == "remote_devops":
        if relation.startswith("ci_"):
            return "ci"
        if relation.startswith("mr_"):
            return "merge_request"
        if relation.startswith("deployment_"):
            return "deployment"
        if relation == "push":
            return "git_remote"
    return source_type


def _adjudication_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adapted: list[dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        relation = _adjudication_relation(item)
        item["relation"] = relation
        item["source_type"] = _adjudication_source_type(item, relation)
        adapted.append(item)
    return adapted


def _formal_status_with_compatibility_view(item, entries, capabilities):
    return _original_formal_status(item, _adjudication_entries(entries), capabilities)


def upgrade_fusion_result(fusion, remote_events=None):
    result = _original_upgrade_fusion_result(fusion, remote_events)
    for item in result.get("work_items") or []:
        raw_evidence = item.get("evidence") or []
        relations = {
            str(entry.get("relation") or "")
            for entry in raw_evidence
            if isinstance(entry, dict)
        }
        if "agent_finished" in relations:
            item["completion_claimed"] = True
            if not item.get("formal_completion") and item.get("completion_level") == "none":
                item["completion_level"] = "claimed"
    return result


_impl._relation = _preferred_relation
_impl._source_type = _preferred_source_type
_impl._formal_status = _formal_status_with_compatibility_view
_impl.upgrade_fusion_result = upgrade_fusion_result

FORMAL_STATUS_LABELS = _impl.FORMAL_STATUS_LABELS
normalize_evidence = _impl.normalize_evidence
infer_project_capabilities = _impl.infer_project_capabilities
