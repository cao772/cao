from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import platform_config

router = APIRouter(prefix="/api/v1")


class ModelConfigIn(BaseModel):
    base_url: str = Field(min_length=4, max_length=1200)
    model: str = Field(min_length=1, max_length=300)
    api_key: str | None = Field(default=None, max_length=4000)
    allow_remote_endpoint: bool = True
    timeout_seconds: int = Field(default=60, ge=5, le=300)


def init_model_db() -> None:
    platform_config.init_platform_db()
    with platform_config._db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS model_connections (
                connection_id TEXT PRIMARY KEY,
                base_url TEXT NOT NULL,
                model TEXT NOT NULL,
                api_key_cipher TEXT,
                api_key_last4 TEXT,
                allow_remote_endpoint INTEGER NOT NULL DEFAULT 1,
                timeout_seconds INTEGER NOT NULL DEFAULT 60,
                verified_at TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )


def _normalize_base_url(value: str) -> str:
    text = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="模型接口地址必须是 http/https URL")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="模型接口地址不能包含账号或密码")
    return text


def _row() -> dict[str, Any] | None:
    init_model_db()
    with platform_config._db() as conn:
        row = conn.execute(
            "SELECT connection_id, base_url, model, api_key_cipher, api_key_last4, "
            "allow_remote_endpoint, timeout_seconds, verified_at, updated_at "
            "FROM model_connections WHERE connection_id='default'"
        ).fetchone()
    return dict(row) if row else None


def _resolved(payload: ModelConfigIn | None = None) -> tuple[str, str, str, bool, int]:
    existing = _row() or {}
    base_url = _normalize_base_url(payload.base_url if payload else str(existing.get("base_url") or ""))
    model = (payload.model if payload else str(existing.get("model") or "")).strip()
    api_key = (payload.api_key or "").strip() if payload else ""
    if not api_key:
        try:
            api_key = platform_config.decrypt_secret(existing.get("api_key_cipher"))
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not model:
        raise HTTPException(status_code=400, detail="请输入模型名称")
    allow_remote = bool(payload.allow_remote_endpoint) if payload else bool(existing.get("allow_remote_endpoint", 1))
    timeout = int(payload.timeout_seconds) if payload else int(existing.get("timeout_seconds") or 60)
    return base_url, model, api_key, allow_remote, timeout


def _chat_url(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _probe(base_url: str, model: str, api_key: str, timeout: int) -> dict[str, Any]:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "仅回复 OK"}],
            "temperature": 0,
            "max_tokens": 8,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(_chat_url(base_url), data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise HTTPException(status_code=400, detail="模型接口密钥无效或权限不足") from exc
        raise HTTPException(status_code=502, detail=f"模型接口返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="无法连接模型接口，请检查地址和网络") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="模型接口返回的不是有效 JSON") from exc
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise HTTPException(status_code=502, detail="模型接口响应格式不符合 OpenAI 兼容协议")
    return {"response_model": payload.get("model") if isinstance(payload, dict) else None}


@router.get("/platform/model")
def get_model_config() -> dict[str, Any]:
    row = _row()
    if not row:
        return {
            "configured": False,
            "base_url": "",
            "model": "",
            "api_key_hint": None,
            "allow_remote_endpoint": True,
            "timeout_seconds": 60,
            "verified_at": None,
        }
    return {
        "configured": bool(row.get("base_url") and row.get("model")),
        "base_url": row.get("base_url") or "",
        "model": row.get("model") or "",
        "api_key_hint": f"****{row.get('api_key_last4')}" if row.get("api_key_last4") else None,
        "allow_remote_endpoint": bool(row.get("allow_remote_endpoint")),
        "timeout_seconds": int(row.get("timeout_seconds") or 60),
        "verified_at": row.get("verified_at"),
        "updated_at": row.get("updated_at"),
    }


@router.put("/platform/model")
def put_model_config(payload: ModelConfigIn) -> dict[str, Any]:
    init_model_db()
    existing = _row() or {}
    base_url = _normalize_base_url(payload.base_url)
    model = payload.model.strip()
    api_key = (payload.api_key or "").strip()
    cipher = existing.get("api_key_cipher")
    last4 = existing.get("api_key_last4")
    if api_key:
        cipher = platform_config.encrypt_secret(api_key)
        last4 = api_key[-4:]
    now = platform_config._now()
    with platform_config._db() as conn:
        conn.execute(
            """
            INSERT INTO model_connections(
                connection_id, base_url, model, api_key_cipher, api_key_last4,
                allow_remote_endpoint, timeout_seconds, verified_at, updated_at
            ) VALUES ('default', ?, ?, ?, ?, ?, ?, NULL, ?)
            ON CONFLICT(connection_id) DO UPDATE SET
                base_url=excluded.base_url,
                model=excluded.model,
                api_key_cipher=excluded.api_key_cipher,
                api_key_last4=excluded.api_key_last4,
                allow_remote_endpoint=excluded.allow_remote_endpoint,
                timeout_seconds=excluded.timeout_seconds,
                verified_at=NULL,
                updated_at=excluded.updated_at
            """,
            (base_url, model, cipher, last4, int(payload.allow_remote_endpoint), payload.timeout_seconds, now),
        )
    return get_model_config()


@router.post("/platform/model/test")
def test_model_config(payload: ModelConfigIn) -> dict[str, Any]:
    base_url, model, api_key, _allow_remote, timeout = _resolved(payload)
    result = _probe(base_url, model, api_key, timeout)
    now = platform_config._now()
    row = _row()
    if row and not (payload.api_key or "").strip():
        with platform_config._db() as conn:
            conn.execute("UPDATE model_connections SET verified_at=? WHERE connection_id='default'", (now,))
    return {"ok": True, "verified_at": now, "model": model, **result}


@router.get("/internal/model/runtime-config")
def internal_model_runtime_config(
    x_collector_token: str | None = Header(default=None),
) -> dict[str, Any]:
    if platform_config.COLLECTOR_TOKEN and x_collector_token != platform_config.COLLECTOR_TOKEN:
        raise HTTPException(status_code=401, detail="invalid collector token")
    row = _row()
    if not row or not row.get("base_url") or not row.get("model"):
        return {"configured": False}
    try:
        api_key = platform_config.decrypt_secret(row.get("api_key_cipher"))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "configured": True,
        "base_url": row["base_url"],
        "model": row["model"],
        "api_key": api_key,
        "allow_remote_endpoint": bool(row.get("allow_remote_endpoint")),
        "timeout_seconds": int(row.get("timeout_seconds") or 60),
    }
