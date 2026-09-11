from __future__ import annotations

from typing import Any

import evidence_lifecycle_v2_impl as _impl


# Integration adapter: explicit producer semantics win over legacy inference.
_original_relation = _impl._relation
_original_source_type = _impl._source_type
_original_formal_status = _impl._formal_status
_original_upgrade_fusion_result = _impl.upgrade_fusion_result

_AGENT_RELATION_ALIASES = {
    "agent_finished": "completion_claim",
    "agent_test_pass": "test_pass",
    "agent_test_fail": "test_fail",
    "agent_blocker": "blocker",
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


def _adjudication_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adapted: list[dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        relation = str(item.get("relation") or "")
        item["relation"] = _AGENT_RELATION_ALIASES.get(relation, relation)
        adapted.append(item)
    return adapted


def _formal_status_with_agent_aliases(item, entries, capabilities):
    return _original_formal_status(item, _adjudication_entries(entries), capabilities)


def upgrade_fusion_result(fusion, remote_events=None):
    result = _original_upgrade_fusion_result(fusion, remote_events)
    for item in result.get("work_items") or []:
        raw_evidence = item.get("evidence") or []
        relations = {str(entry.get("relation") or "") for entry in raw_evidence if isinstance(entry, dict)}
        if "agent_finished" in relations:
            item["completion_claimed"] = True
            if not item.get("formal_completion") and item.get("completion_level") == "none":
                item["completion_level"] = "claimed"
    return result


_impl._relation = _preferred_relation
_impl._source_type = _preferred_source_type
_impl._formal_status = _formal_status_with_agent_aliases
_impl.upgrade_fusion_result = upgrade_fusion_result

FORMAL_STATUS_LABELS = _impl.FORMAL_STATUS_LABELS
normalize_evidence = _impl.normalize_evidence
infer_project_capabilities = _impl.infer_project_capabilities
