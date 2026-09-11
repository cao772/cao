from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import platform_config

router = APIRouter(prefix="/api/v1")
VALID_MODES = {"metadata_only", "local_analysis"}
VALID_INCLUDE = {"documents", "tests", "outputs"}


class ProjectRuntimeSettingsIn(BaseModel):
    enabled: bool = True
    security_mode: str = Field(default="metadata_only", pattern="^(metadata_only|local_analysis)$")
    analysis_enabled: bool = False
    use_llm: bool = False
    include: list[str] = Field(default_factory=lambda: ["documents", "tests", "outputs"], max_length=3)


def _defaults(project_id: str) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "enabled": True,
        "security_mode": "metadata_only",
        "analysis_enabled": False,
        "use_llm": False,
        "include": ["documents", "tests", "outputs"],
        "updated_at": None,
    }


def init_project_settings_db() -> None:
    platform_config.init_platform_db()
    with platform_config._db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_runtime_settings (
                project_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                security_mode TEXT NOT NULL DEFAULT 'metadata_only',
                analysis_enabled INTEGER NOT NULL DEFAULT 0,
                use_llm INTEGER NOT NULL DEFAULT 0,
                include_json TEXT NOT NULL DEFAULT '["documents","tests","outputs"]',
                updated_at TEXT NOT NULL
            );
            """
        )


def _normalize_settings(project_id: str, payload: ProjectRuntimeSettingsIn) -> dict[str, Any]:
    include = [item for item in payload.include if item in VALID_INCLUDE]
    include = list(dict.fromkeys(include)) or ["documents", "tests", "outputs"]
    security_mode = payload.security_mode if payload.security_mode in VALID_MODES else "metadata_only"
    analysis_enabled = bool(payload.analysis_enabled and security_mode == "local_analysis")
    use_llm = bool(payload.use_llm and analysis_enabled)
    return {
        "project_id": project_id,
        "enabled": bool(payload.enabled),
        "security_mode": security_mode,
        "analysis_enabled": analysis_enabled,
        "use_llm": use_llm,
        "include": include,
    }


def get_project_runtime_settings(project_id: str) -> dict[str, Any]:
    init_project_settings_db()
    with platform_config._db() as conn:
        row = conn.execute(
            "SELECT project_id, enabled, security_mode, analysis_enabled, use_llm, include_json, updated_at "
            "FROM project_runtime_settings WHERE project_id=?",
            (project_id,),
        ).fetchone()
    if row is None:
        return _defaults(project_id)
    item = dict(row)
    try:
        include = json.loads(item.pop("include_json") or "[]")
    except json.JSONDecodeError:
        include = []
    item["enabled"] = bool(item["enabled"])
    item["analysis_enabled"] = bool(item["analysis_enabled"])
    item["use_llm"] = bool(item["use_llm"])
    item["include"] = [value for value in include if value in VALID_INCLUDE] or ["documents", "tests", "outputs"]
    return item


def all_project_runtime_settings() -> dict[str, dict[str, Any]]:
    projects = platform_config._all_business_projects()
    return {str(item["project_id"]): get_project_runtime_settings(str(item["project_id"])) for item in projects}


@router.get("/platform/project-settings")
def list_project_runtime_settings() -> dict[str, Any]:
    settings = all_project_runtime_settings()
    return {"count": len(settings), "settings": settings}


@router.get("/platform/projects/{project_id}/settings")
def get_project_settings(project_id: str) -> dict[str, Any]:
    if not platform_config._project_exists(project_id):
        raise HTTPException(status_code=404, detail="业务项目不存在")
    return get_project_runtime_settings(project_id)


@router.put("/platform/projects/{project_id}/settings")
def put_project_settings(project_id: str, payload: ProjectRuntimeSettingsIn) -> dict[str, Any]:
    if not platform_config._project_exists(project_id):
        raise HTTPException(status_code=404, detail="业务项目不存在")
    normalized = _normalize_settings(project_id, payload)
    now = platform_config._now()
    init_project_settings_db()
    with platform_config._db() as conn:
        conn.execute(
            """
            INSERT INTO project_runtime_settings(
                project_id, enabled, security_mode, analysis_enabled, use_llm, include_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                enabled=excluded.enabled,
                security_mode=excluded.security_mode,
                analysis_enabled=excluded.analysis_enabled,
                use_llm=excluded.use_llm,
                include_json=excluded.include_json,
                updated_at=excluded.updated_at
            """,
            (
                project_id,
                int(normalized["enabled"]),
                normalized["security_mode"],
                int(normalized["analysis_enabled"]),
                int(normalized["use_llm"]),
                json.dumps(normalized["include"], ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )
    return get_project_runtime_settings(project_id)


@router.get("/internal/projects/runtime-settings")
def internal_project_runtime_settings(
    x_collector_token: str | None = Header(default=None),
) -> dict[str, Any]:
    if platform_config.COLLECTOR_TOKEN and x_collector_token != platform_config.COLLECTOR_TOKEN:
        raise HTTPException(status_code=401, detail="invalid collector token")
    settings = all_project_runtime_settings()
    return {"version": 1, "projects": settings}
