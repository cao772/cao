from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from typing import Any

CATEGORY_LABELS = {
    "requirement": "需求",
    "decision": "决定",
    "change": "变更",
    "task": "任务",
    "blocker": "问题/阻塞",
    "deadline": "时间节点",
    "confirmation": "确认",
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_fingerprint TEXT NOT NULL UNIQUE,
            project_id TEXT NOT NULL,
            project_name TEXT,
            source TEXT NOT NULL,
            conversation_name TEXT NOT NULL,
            sender TEXT,
            message_type TEXT NOT NULL,
            text TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            received_at TEXT NOT NULL,
            user_id TEXT,
            device_id TEXT,
            categories_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_conversation_project_id_id
            ON conversation_events(project_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_conversation_project_observed
            ON conversation_events(project_id, observed_at DESC);
        """
    )


def insert_event(conn: sqlite3.Connection, event: dict[str, Any], received_at: str) -> tuple[int, bool]:
    init_db(conn)
    fingerprint = str(event.get("event_fingerprint") or "").strip()
    existing = conn.execute(
        "SELECT id FROM conversation_events WHERE event_fingerprint = ?",
        (fingerprint,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"] if hasattr(existing, "keys") else existing[0]), True
    cursor = conn.execute(
        """
        INSERT INTO conversation_events (
            event_fingerprint, project_id, project_name, source, conversation_name,
            sender, message_type, text, observed_at, received_at, user_id, device_id,
            categories_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fingerprint,
            event["project_id"],
            event.get("project_name"),
            event.get("source") or "wechat_personal",
            event["conversation_name"],
            event.get("sender"),
            event.get("message_type") or "text",
            event["text"],
            event["observed_at"],
            received_at,
            event.get("user_id"),
            event.get("device_id"),
            json.dumps(event.get("categories") or [], ensure_ascii=False),
            json.dumps(event.get("metadata") or {}, ensure_ascii=False),
        ),
    )
    return int(cursor.lastrowid), False


def _row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["categories"] = json.loads(item.pop("categories_json") or "[]")
    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    item["category_labels"] = [CATEGORY_LABELS.get(cat, cat) for cat in item["categories"]]
    return item


def search_messages(
    conn: sqlite3.Connection,
    project_id: str,
    query: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    init_db(conn)
    terms = [term for term in re.split(r"\s+", query.strip()) if term]
    if not terms:
        return []
    clauses = []
    params: list[Any] = [project_id]
    for term in terms:
        pattern = f"%{term}%"
        clauses.append("(text LIKE ? OR conversation_name LIKE ? OR COALESCE(sender, '') LIKE ?)")
        params.extend([pattern, pattern, pattern])
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT *
        FROM conversation_events
        WHERE project_id = ? AND {' AND '.join(clauses)}
        ORDER BY observed_at DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_row(row) for row in rows]


def project_summary(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    init_db(conn)
    rows = conn.execute(
        """
        SELECT conversation_name, categories_json, observed_at
        FROM conversation_events
        WHERE project_id = ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 2000
        """,
        (project_id,),
    ).fetchall()
    categories: Counter[str] = Counter()
    groups: Counter[str] = Counter()
    latest = None
    for raw in rows:
        item = dict(raw)
        groups[str(item["conversation_name"])] += 1
        for category in json.loads(item["categories_json"] or "[]"):
            categories[str(category)] += 1
        latest = latest or item["observed_at"]
    return {
        "project_id": project_id,
        "message_count": len(rows),
        "group_count": len(groups),
        "groups": [{"name": name, "count": count} for name, count in groups.most_common()],
        "categories": [
            {"type": name, "label": CATEGORY_LABELS.get(name, name), "count": count}
            for name, count in categories.most_common()
        ],
        "latest_observed_at": latest,
    }
