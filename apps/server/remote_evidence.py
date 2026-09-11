from __future__ import annotations

from task_intelligence import apply_task_intelligence
import remote_evidence_v2_impl as _impl


# M2 + M3 integration chain:
# Remote Evidence -> Task Intelligence -> Evidence Fusion V2.
_evidence_fusion_upgrade = _impl.upgrade_fusion_result


def _upgrade_after_task_intelligence(result, remote_events=None):
    task_result = apply_task_intelligence(result)
    return _evidence_fusion_upgrade(task_result, remote_events)


_impl.upgrade_fusion_result = _upgrade_after_task_intelligence

REMOTE_STATUS_LABELS = _impl.REMOTE_STATUS_LABELS
apply_remote_evidence = _impl.apply_remote_evidence
