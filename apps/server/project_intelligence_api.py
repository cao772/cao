from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

import main as main_module
from project_intelligence import build_project_intelligence, search_project_intelligence

router = APIRouter(prefix="/api/v1/projects", tags=["project-intelligence"])


def _normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(snapshot)
    payload = dict(normalized.get("payload") or {})
    files = payload.get("files") or {}
    intelligence = files.get("project_intelligence") if isinstance(files, dict) else None
    if isinstance(intelligence, dict):
        payload["project_intelligence"] = intelligence
    normalized["payload"] = payload
    return normalized


def _normalize_public_material_semantics(intelligence: dict[str, Any]) -> dict[str, Any]:
    """Keep additive contract materials visibly distinct from the primary contract.

    Contract supplements and attachments remain active evidence even when their own
    automatically detected series contains only one file. They must never be rendered
    as the primary contract merely because that local series has one member.
    """
    for material in intelligence.get("materials") or []:
        material_type = material.get("material_type")
        if material_type == "contract":
            material["version_status"] = "primary"
        elif material_type in {"contract_supplement", "contract_attachment"}:
            material["version_status"] = "active_related"
    return intelligence


def _latest_snapshots(project_id: str) -> list[dict[str, Any]]:
    snapshots = main_module.latest_workspace_snapshots(project_id)
    if not snapshots:
        raise HTTPException(status_code=404, detail="project snapshot not found")
    return [_normalize_snapshot(snapshot) for snapshot in snapshots]


def _history_snapshots(project_id: str, limit: int = 160) -> list[dict[str, Any]]:
    with main_module.get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, project_name, user_id, device_id, workspace_name,
                   observed_at, received_at, snapshot_type, payload_json
            FROM snapshots
            WHERE project_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
    return [_normalize_snapshot(main_module._snapshot_row(row)) for row in rows]


@router.get("/{project_id}/intelligence")
def get_project_intelligence(project_id: str) -> dict[str, Any]:
    intelligence = build_project_intelligence(
        _latest_snapshots(project_id),
        _history_snapshots(project_id),
        include_search_index=False,
    )
    intelligence["progress"] = dict(main_module.project_brief(project_id) or {})
    return _normalize_public_material_semantics(intelligence)


@router.get("/{project_id}/search")
def search_project_materials(
    project_id: str,
    q: str = Query(min_length=1, max_length=500),
    material_type: str | None = Query(default=None, max_length=80),
    current_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    intelligence = build_project_intelligence(
        _latest_snapshots(project_id),
        _history_snapshots(project_id, 80),
        include_search_index=True,
    )
    _normalize_public_material_semantics(intelligence)
    result = search_project_intelligence(
        intelligence,
        q,
        material_type=material_type,
        current_only=current_only,
        limit=limit,
    )
    result["project_id"] = project_id
    result["search_indexed_file_count"] = (intelligence.get("summary") or {}).get("search_indexed_file_count", 0)
    result["content_search_available"] = bool(result["search_indexed_file_count"])
    return result
