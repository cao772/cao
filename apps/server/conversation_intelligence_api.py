from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

import main as main_module
from conversation_intelligence import insert_event, project_summary, search_messages

router = APIRouter(tags=["conversation-intelligence"])


class ConversationEventIn(BaseModel):
    schema_version: int = 1
    event_fingerprint: str = Field(min_length=16, max_length=128)
    project_id: str = Field(min_length=1, max_length=200)
    project_name: str | None = Field(default=None, max_length=500)
    source: str = Field(default="wechat_personal", max_length=80)
    conversation_name: str = Field(min_length=1, max_length=500)
    sender: str | None = Field(default=None, max_length=500)
    message_type: str = Field(default="text", max_length=80)
    text: str = Field(min_length=1, max_length=20000)
    observed_at: str
    user_id: str | None = Field(default=None, max_length=200)
    device_id: str | None = Field(default=None, max_length=300)
    categories: list[str] = Field(default_factory=list, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/v1/conversation-events")
def ingest_conversation_event(
    event: ConversationEventIn,
    x_collector_token: str | None = Header(default=None),
) -> dict[str, Any]:
    main_module.require_collector_token(x_collector_token)
    received_at = main_module.now_utc()
    with main_module.get_db() as conn:
        event_id, duplicate = insert_event(conn, event.model_dump(), received_at)
    return {
        "accepted": True,
        "duplicate": duplicate,
        "event_id": event_id,
        "received_at": received_at,
    }


@router.get("/api/v1/projects/{project_id}/communications/search")
def search_project_communications(
    project_id: str,
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    with main_module.get_db() as conn:
        results = search_messages(conn, project_id, q, limit=limit)
    return {"project_id": project_id, "query": q, "count": len(results), "results": results}


@router.get("/api/v1/projects/{project_id}/communications/summary")
def get_project_communications_summary(project_id: str) -> dict[str, Any]:
    with main_module.get_db() as conn:
        return project_summary(conn, project_id)
