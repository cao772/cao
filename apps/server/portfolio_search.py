from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

import main as main_module
from evidence_retrieval import evidence_excerpt, fuse_candidate_ranks, literal_like
from project_intelligence import build_project_intelligence, search_project_intelligence
from project_intelligence_api import _history_snapshots, _latest_snapshots

router = APIRouter(prefix="/api/v1", tags=["portfolio-search"])


def _time_key(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def rank_search_results(results: list[dict[str, Any]], limit: int, query: str | None = None) -> list[dict[str, Any]]:
    """Keep one hit per material/message and rank evidence before recency."""
    if limit <= 0:
        return []
    seen: set[tuple[str, str, str]] = set()
    ranked: list[dict[str, Any]] = []
    for item in sorted(results, key=lambda row: (int(row.get("score") or 0), _time_key(row.get("source_time"))), reverse=True):
        identity = str(item.get("source_path") or item.get("source_id") or "")
        key = (str(item.get("project_id") or ""), str(item.get("source_type") or ""), identity)
        if not identity or key in seen:
            continue
        seen.add(key)
        ranked.append(item)
    if query:
        ranked = fuse_candidate_ranks(ranked, query)
    return ranked[:limit]


def _search_conversations(project_id: str, query: str) -> list[dict[str, Any]]:
    """Read the optional M7 table only when it exists in this deployment."""
    terms = query.split()
    if not terms:
        return []
    with main_module.get_db() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_events'").fetchone():
            return []
        clauses = []
        params: list[Any] = [project_id]
        for term in terms:
            clauses.append("(text LIKE ? ESCAPE '\\' OR conversation_name LIKE ? ESCAPE '\\' OR COALESCE(sender, '') LIKE ? ESCAPE '\\')")
            params.extend([literal_like(term)] * 3)
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
                        "locator": hit.get("locator"), "location_type": hit.get("location_type"),
                        "snippet": evidence_excerpt(hit.get("snippet") or "", query), "score": hit.get("score") or 0,
                    })
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            unavailable.append(pid)
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
                    "matched_fields": [label for label, key in (("正文", "text"), ("会话名称", "conversation_name"), ("发送人", "sender")) if any(term.lower() in str(message.get(key) or "").lower() for term in query.split())],
                    "snippet": evidence_excerpt(str(message.get("text") or ""), query), "score": 55,
                })
    ranked = rank_search_results(found, len(found), query=query)
    return {
        "query": query,
        "ranking_method": "field_bm25_rrf",
        "candidate_scope": "已召回候选内排序；每项目各来源最多100项",
        "project_id": project_id,
        "source": source,
        "conversation_available": conversation_available,
        "count": len(ranked),
        "results": ranked[:limit],
        "unavailable_projects": unavailable,
    }
