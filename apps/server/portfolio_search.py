from __future__ import annotations

from datetime import datetime
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

import main as main_module
from material_search_cache import material_search_cache
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
        params.append(101)
        return [dict(row) for row in conn.execute(
            f"SELECT id, conversation_name, sender, text, observed_at, received_at FROM conversation_events "
            f"WHERE project_id = ? AND {' AND '.join(clauses)} ORDER BY observed_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()]


def _material_intelligence(project_id: str) -> dict[str, Any]:
    def build():
        return build_project_intelligence(_latest_snapshots(project_id), _history_snapshots(project_id, 80), include_search_index=True)
    with main_module.get_db() as conn:
        # Snapshot ingestion is append-only. Include count to notice deletion of older evidence.
        try:
            row = conn.execute("SELECT MAX(id), COUNT(*) FROM snapshots WHERE project_id = ?", (project_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            if 'no such table' not in str(exc):
                raise
            return build()
    return material_search_cache.get(str(main_module.DB_PATH), project_id, tuple(row), build)


@router.get("/search")
def search_portfolio(
    q: str = Query(min_length=1, max_length=200),
    project_id: str | None = Query(default=None, max_length=120),
    source: Literal["all", "material", "conversation"] = "all",
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    order: Literal["relevance", "recent"] = "relevance",
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
    truncated: list[dict[str, str]] = []
    for project in projects:
        pid = str(project["project_id"])
        name = str(project["project_name"] or pid)
        try:
            if source in {"all", "material"}:
                intelligence = _material_intelligence(pid)
                material_payload = search_project_intelligence(intelligence, query, limit=100)
                material_results = material_payload["results"]
                if material_payload["count"] > 100:
                    truncated.append({"project_id": pid, "source": "material"})
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
            if len(messages) > 100:
                truncated.append({"project_id": pid, "source": "conversation"})
            for message in messages[:100]:
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
    if order == "recent":
        ranked.sort(key=lambda row: _time_key(row.get("source_time")), reverse=True)
    return {
        "query": query,
        "ranking_method": "field_bm25_rrf",
        "candidate_scope": "已召回候选内排序；每项目各来源最多100项",
        "project_id": project_id,
        "source": source,
        "offset": offset,
        "order": order,
        "has_more": offset + limit < len(ranked),
        "truncated_sources": truncated,
        "conversation_available": conversation_available,
        "count": len(ranked),
        "results": ranked[offset:offset + limit],
        "unavailable_projects": unavailable,
    }
