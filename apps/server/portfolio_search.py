from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

import main as main_module
from project_intelligence import build_project_intelligence, search_project_intelligence
from project_intelligence_api import _history_snapshots, _latest_snapshots

router = APIRouter(prefix="/api/v1", tags=["portfolio-search"])


def _time_key(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def rank_search_results(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Keep one hit per material/message and rank evidence before recency."""
    seen: set[tuple[str, str, str]] = set()
    ranked: list[dict[str, Any]] = []
    for item in sorted(results, key=lambda row: (int(row.get("score") or 0), _time_key(row.get("source_time"))), reverse=True):
        identity = str(item.get("source_path") or item.get("source_id") or "")
        key = (str(item.get("project_id") or ""), str(item.get("source_type") or ""), identity)
        if not identity or key in seen:
            continue
        seen.add(key)
        ranked.append(item)
        if len(ranked) >= limit:
            break
    return ranked


def _search_conversations(project_id: str, query: str) -> list[dict[str, Any]]:
    """Read the optional M7 table only when it exists in this deployment."""
    terms = query.split()
    with main_module.get_db() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_events'").fetchone():
            return []
        clauses = []
        params: list[Any] = [project_id]
        for term in terms:
            clauses.append("(text LIKE ? OR conversation_name LIKE ? OR COALESCE(sender, '') LIKE ?)")
            params.extend([f"%{term}%"] * 3)
        params.append(100)
        return [dict(row) for row in conn.execute(
            f"SELECT id, conversation_name, sender, text, observed_at, received_at FROM conversation_events "
            f"WHERE project_id = ? AND {' AND '.join(clauses)} ORDER BY observed_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()]


@router.get("/search")
def search_portfolio(
    q: str = Query(min_length=1, max_length=200),
    project_id: str | None = Query(default=None, max_length=120),
    source: Literal["all", "material", "conversation"] = "all",
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="query must not be blank")
    with main_module.get_db() as conn:
        rows = conn.execute("SELECT project_id, project_name FROM projects ORDER BY project_name, project_id").fetchall()
        conversation_available = bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_events'").fetchone())
    projects = [dict(row) for row in rows]
    if project_id:
        projects = [item for item in projects if item["project_id"] == project_id]
        if not projects:
            raise HTTPException(status_code=404, detail="project not found")

    found: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for project in projects:
        pid = str(project["project_id"])
        name = str(project["project_name"] or pid)
        try:
            if source in {"all", "material"}:
                intelligence = build_project_intelligence(
                    _latest_snapshots(pid), _history_snapshots(pid, 80), include_search_index=True,
                )
                material_results = search_project_intelligence(intelligence, query, limit=100)["results"]
                for hit in material_results:
                    material = hit["material"]
                    found.append({
                        "project_id": pid, "project_name": name, "source_type": "material",
                        "source_id": material.get("sha256") or material.get("path"),
                        "source_name": material.get("name") or material.get("path"),
                        "source_path": material.get("path"),
                        "source_time": material.get("modified_at"),
                        "observed_at": material.get("observed_at"),
                        "version_status": material.get("version_status"),
                        "matched_fields": hit.get("matched_fields") or [],
                        "snippet": hit.get("snippet") or "", "score": hit.get("score") or 0,
                    })
            if conversation_available and source in {"all", "conversation"}:
                messages = _search_conversations(pid, query)
                for message in messages:
                    found.append({
                        "project_id": pid, "project_name": name, "source_type": "conversation",
                        "source_id": message.get("id"),
                        "source_name": message.get("conversation_name") or "授权会话",
                        "source_path": None, "source_time": message.get("observed_at"),
                        "observed_at": message.get("received_at"),
                        "sender": message.get("sender"),
                        "snippet": str(message.get("text") or "")[:500], "score": 55,
                    })
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            unavailable.append(pid)
    ranked = rank_search_results(found, len(found))
    return {
        "query": query,
        "project_id": project_id,
        "source": source,
        "conversation_available": conversation_available,
        "count": len(ranked),
        "results": ranked[:limit],
        "unavailable_projects": unavailable,
    }
