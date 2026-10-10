"""Muse-only summaries from the live, explicitly bound Mac collector scope."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request

import main

router = APIRouter(prefix="/api/v1/personal-agent", tags=["personal-agent"])


def scope_digest(user, device, bindings):
    pairs = sorted({(b["project_id"], b["group_name"]) for b in bindings})
    return hashlib.sha256(json.dumps([user, device, pairs], ensure_ascii=False).encode()).hexdigest()


def read_scope():
    root = os.getenv("CAO_WECHAT_STATE_ROOT", "")
    user = os.getenv("CAO_WECHAT_USER_ID", "")
    device = os.getenv("CAO_WECHAT_DEVICE_ID", "")
    if not root or not user or not device:
        raise HTTPException(503, "Authorized WeChat source not configured")
    try:
        config = json.loads((Path(root) / "wechat-config.json").read_text())
        generated = datetime.fromisoformat(config["generated_at"].replace("Z", "+00:00"))
        if generated.tzinfo is None or not -60 <= (datetime.now(timezone.utc) - generated).total_seconds() <= 60:
            raise ValueError
        bindings = config["bindings"]
        if config.get("enabled") is not True or not isinstance(bindings, list) or not 0 < len(bindings) <= 100:
            raise ValueError
        if any(not isinstance(b, dict) or not isinstance(b.get("project_id"), str)
               or not b["project_id"] or not isinstance(b.get("group_name"), str)
               or not b["group_name"] for b in bindings):
            raise ValueError
        return user, device, bindings, scope_digest(user, device, bindings)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(503, "Authorized WeChat scope unavailable") from None


def summarize(conn, user, device, bindings, scope, health, now):
    result = {"schema_version": 1, "scope_id": scope, "authorized": True,
              "status": "unavailable", "last_success_at": None, "complete": True, "events": []}
    if health.get("scope_id") != scope or health.get("status") != "available":
        return result
    try:
        stamp = datetime.fromisoformat(health["last_success_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or (now - stamp).total_seconds() < -60:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        return result
    result["last_success_at"] = stamp.isoformat()
    if (now - stamp).total_seconds() > 5400:
        result["status"] = "stale"
        return result
    table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_events'").fetchone()
    if not table:
        return result
    clauses = " OR ".join("(project_id=? AND conversation_name=?)" for _ in bindings)
    pairs = [v for b in bindings for v in (b['project_id'], b['group_name'])]
    # Fetch only anonymized metadata. Never select sender, text, or chat attachments.
    rows = conn.execute(
        "SELECT event_fingerprint,categories_json FROM conversation_events "
        "WHERE user_id=? AND device_id=? AND source='wechat_personal' "
        f"AND ({clauses}) AND julianday(received_at)>=julianday(?) "
        "ORDER BY id DESC LIMIT 1001",
        [user, device, *pairs, (now - timedelta(days=30)).isoformat()],
    ).fetchall()
    if len(rows) > 1000:
        # Do not turn a partial snapshot into a complete baseline.
        return result
    events = []
    for row in rows:
        fingerprint = row[0]
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in '0123456789abcdef' for c in fingerprint):
            return result
        try:
            cats = json.loads(row[1])
            if not isinstance(cats, list):
                return result
        except (TypeError, ValueError):
            return result
        category = next((c for c in ('mention','blocker','task','decision') if c in cats), 'other')
        events.append({"event_id": hashlib.sha256(f"{scope}:{fingerprint}".encode()).hexdigest(), "category": category})
    result.update(status="available", events=events)
    return result


@router.get("/wechat-notifications")
def wechat_notifications(request: Request, x_muse_token: str | None = Header(default=None)):
    expected = os.getenv("CAO_MUSE_WECHAT_TOKEN", "")
    if (len(expected) < 32 or expected in {main.COLLECTOR_TOKEN, os.getenv("CAO_MUSE_TOKEN", "")}
            or not expected.isascii() or not x_muse_token or not x_muse_token.isascii()
            or not hmac.compare_digest(expected, x_muse_token)):
        raise HTTPException(401, "Read-only Muse WeChat capability required")
    allowed = {"127.0.0.1", "::1", "testclient"}
    bridge = os.getenv("CAO_MUSE_BRIDGE_CLIENT", "")
    if bridge:
        allowed.add(bridge)
    if not request.client or request.client.host not in allowed:
        raise HTTPException(403, "Muse WeChat is loopback-only")
    user, device, bindings, scope = read_scope()
    try:
        health = json.loads((Path(os.environ['CAO_WECHAT_STATE_ROOT']) / 'wechat-muse-health.json').read_text())
        if not isinstance(health, dict):
            health = {}
    except (OSError, ValueError):
        health = {}
    with main.get_db() as conn:
        return summarize(conn, user, device, bindings, scope, health, datetime.now(timezone.utc))
