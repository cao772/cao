from __future__ import annotations

from main import SnapshotIn


def test_project_intelligence_survives_v1_snapshot_contract_inside_files():
    payload = SnapshotIn(
        schema_version=1,
        snapshot_type="local.workspace",
        observed_at="2026-09-15T08:00:00+00:00",
        project_id="demo",
        project_name="Demo",
        user_id="cyh",
        device_id="mac-1",
        workspace_name="demo",
        collector={"name": "project-sentinel", "version": "0.6.0"},
        security_mode="local_analysis",
        git={},
        files={
            "files": [],
            "project_intelligence": {
                "schema_version": 1,
                "context": {"present": True, "valid": True, "data": {"schema_version": 1}},
                "search_index": {"enabled": True, "items": []},
            },
        },
        analysis={},
        git_change_analysis={},
    ).model_dump()

    intelligence = payload["files"]["project_intelligence"]
    assert intelligence["schema_version"] == 1
    assert intelligence["context"]["present"] is True
    assert intelligence["search_index"]["enabled"] is True
