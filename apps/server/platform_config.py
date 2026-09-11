from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("DB_PATH", "/data/project.db"))
PLATFORM_KEY_PATH = Path(os.getenv("PLATFORM_KEY_PATH", "/data/platform.key"))
COLLECTOR_TOKEN = os.getenv("COLLECTOR_TOKEN", "")
DEFAULT_GITLAB_URL = os.getenv("GITLAB_BASE_URL", "http://git.hyetec.com").rstrip("/")
HTTP_TIMEOUT_SECONDS = int(os.getenv("PLATFORM_HTTP_TIMEOUT", "20"))

router = APIRouter(prefix="/api/v1")


class GitLabConfigIn(BaseModel):
    base_url: str = Field(default=DEFAULT_GITLAB_URL, min_length=4, max_length=1000)
    token: str | None = Field(default=None, max_length=4000)


class GitLabDiscoverIn(BaseModel):
    search: str | None = Field(default=None, max_length=300)


class RepositoryBindingIn(BaseModel):
    repository_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    path_with_namespace: str = Field(min_length=1, max_length=1200)
    web_url: str = Field(min_length=1, max_length=2000)
    default_branch: str | None = Field(default=None, max_length=500)
    visibility: str | None = Field(default=None, max_length=80)
    last_activity_at: str | None = Field(default=None, max_length=100)


class RepositoryBindingSet(BaseModel):
    repositories: list[RepositoryBindingIn] = Field(default_factory=list, max_length=100)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_platform_db() -> None:
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS source_connections (
                provider TEXT PRIMARY KEY,
                base_url TEXT NOT NULL,
                token_cipher TEXT,
                token_last4 TEXT,
                verified_at TEXT,
                account_json TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_repository_bindings (
                project_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                repository_id TEXT NOT NULL,
                repository_name TEXT NOT NULL,
                path_with_namespace TEXT NOT NULL,
                web_url TEXT NOT NULL,
                default_branch TEXT,
                visibility TEXT,
                last_activity_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (provider, repository_id),
                UNIQUE (project_id, provider, repository_id)
            );

            CREATE INDEX IF NOT EXISTS idx_project_repository_bindings_project
                ON project_repository_bindings(project_id, provider);
            """
        )


def _fernet() -> Fernet:
    PLATFORM_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PLATFORM_KEY_PATH.exists():
        key = PLATFORM_KEY_PATH.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        PLATFORM_KEY_PATH.write_bytes(key + b"\n")
        try:
            PLATFORM_KEY_PATH.chmod(0o600)
        except OSError:
            pass
    try:
        return Fernet(key)
    except ValueError as exc:
        raise RuntimeError("invalid platform encryption key") from exc


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError("cannot decrypt stored platform secret") from exc


def _normalize_base_url(value: str) -> str:
    text = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="GitLab 地址必须是 http/https URL")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="GitLab 地址不能包含账号或密码")
    return text


def _connection_row() -> dict[str, Any] | None:
    init_platform_db()
    with _db() as conn:
        row = conn.execute(
            "SELECT provider, base_url, token_cipher, token_last4, verified_at, account_json, updated_at "
            "FROM source_connections WHERE provider = 'gitlab'"
        ).fetchone()
    return dict(row) if row else None


def _resolved_connection(base_url: str | None = None, token: str | None = None) -> tuple[str, str]:
    row = _connection_row() or {}
    resolved_url = _normalize_base_url(base_url or str(row.get("base_url") or DEFAULT_GITLAB_URL))
    resolved_token = (token or "").strip()
    if not resolved_token:
        try:
            resolved_token = decrypt_secret(row.get("token_cipher"))
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not resolved_token:
        raise HTTPException(status_code=400, detail="尚未配置 GitLab Token")
    return resolved_url, resolved_token


def _gitlab_get(base_url: str, token: str, path: str, params: dict[str, Any] | None = None) -> Any:
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{base_url}/api/v4/{path.lstrip('/')}"
    if query:
        url += "?" + query
    request = urllib.request.Request(
        url,
        headers={
            "PRIVATE-TOKEN": token,
            "Accept": "application/json",
            "User-Agent": "ai-dev-management-platform-config/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise HTTPException(status_code=400, detail="GitLab Token 无效或权限不足") from exc
        raise HTTPException(status_code=502, detail=f"GitLab 接口返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="无法连接 GitLab，请检查地址和网络") from exc


def _discover_projects(base_url: str, token: str, search: str | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in range(1, 101):
        params: dict[str, Any] = {
            "simple": "true",
            "order_by": "last_activity_at",
            "sort": "desc",
            "per_page": 100,
            "page": page,
        }
        if search:
            params["search"] = search
        rows = _gitlab_get(base_url, token, "projects", params)
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            result.append(
                {
                    "id": str(row.get("id") or ""),
                    "name": row.get("name"),
                    "name_with_namespace": row.get("name_with_namespace"),
                    "path_with_namespace": row.get("path_with_namespace"),
                    "web_url": row.get("web_url"),
                    "default_branch": row.get("default_branch"),
                    "visibility": row.get("visibility"),
                    "last_activity_at": row.get("last_activity_at"),
                }
            )
        if len(rows) < 100:
            break
    return result


def _binding_rows(project_id: str | None = None) -> list[dict[str, Any]]:
    init_platform_db()
    sql = (
        "SELECT project_id, provider, repository_id, repository_name, path_with_namespace, web_url, "
        "default_branch, visibility, last_activity_at, updated_at FROM project_repository_bindings"
    )
    params: tuple[Any, ...] = ()
    if project_id is not None:
        sql += " WHERE project_id = ?"
        params = (project_id,)
    sql += " ORDER BY project_id, path_with_namespace"
    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


@router.get("/platform/gitlab")
def get_gitlab_config() -> dict[str, Any]:
    row = _connection_row()
    if not row:
        return {
            "configured": False,
            "base_url": DEFAULT_GITLAB_URL,
            "token_hint": None,
            "verified_at": None,
            "account": None,
        }
    account = json.loads(row.get("account_json") or "null")
    return {
        "configured": bool(row.get("token_cipher")),
        "base_url": row.get("base_url") or DEFAULT_GITLAB_URL,
        "token_hint": f"****{row.get('token_last4')}" if row.get("token_last4") else None,
        "verified_at": row.get("verified_at"),
        "updated_at": row.get("updated_at"),
        "account": account,
    }


@router.put("/platform/gitlab")
def put_gitlab_config(payload: GitLabConfigIn) -> dict[str, Any]:
    init_platform_db()
    base_url = _normalize_base_url(payload.base_url)
    existing = _connection_row() or {}
    token = (payload.token or "").strip()
    token_cipher = existing.get("token_cipher")
    token_last4 = existing.get("token_last4")
    if token:
        token_cipher = encrypt_secret(token)
        token_last4 = token[-4:]
    if not token_cipher:
        raise HTTPException(status_code=400, detail="请输入 GitLab Token")
    now = _now()
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO source_connections(provider, base_url, token_cipher, token_last4, verified_at, account_json, updated_at)
            VALUES('gitlab', ?, ?, ?, NULL, NULL, ?)
            ON CONFLICT(provider) DO UPDATE SET
              base_url=excluded.base_url,
              token_cipher=excluded.token_cipher,
              token_last4=excluded.token_last4,
              updated_at=excluded.updated_at
            """,
            (base_url, token_cipher, token_last4, now),
        )
    return get_gitlab_config()


@router.post("/platform/gitlab/test")
def test_gitlab_config(payload: GitLabConfigIn) -> dict[str, Any]:
    base_url, token = _resolved_connection(payload.base_url, payload.token)
    user = _gitlab_get(base_url, token, "user")
    account = {
        "id": user.get("id"),
        "username": user.get("username"),
        "name": user.get("name"),
    }
    now = _now()
    row = _connection_row()
    if row and not (payload.token or "").strip():
        with _db() as conn:
            conn.execute(
                "UPDATE source_connections SET verified_at=?, account_json=? WHERE provider='gitlab'",
                (now, json.dumps(account, ensure_ascii=False)),
            )
    return {"ok": True, "base_url": base_url, "verified_at": now, "account": account}


@router.post("/platform/gitlab/discover")
def discover_gitlab_projects(payload: GitLabDiscoverIn) -> dict[str, Any]:
    base_url, token = _resolved_connection()
    projects = _discover_projects(base_url, token, payload.search)
    binding_map = {
        (row["provider"], str(row["repository_id"])): row["project_id"]
        for row in _binding_rows()
    }
    for project in projects:
        project["bound_project_id"] = binding_map.get(("gitlab", str(project.get("id") or "")))
    return {"count": len(projects), "projects": projects}


@router.get("/platform/project-bindings")
def get_all_project_bindings() -> dict[str, Any]:
    rows = _binding_rows()
    return {"count": len(rows), "bindings": rows}


@router.get("/platform/projects/{project_id}/repositories")
def get_project_bindings(project_id: str) -> dict[str, Any]:
    return {"project_id": project_id, "repositories": _binding_rows(project_id)}


@router.put("/platform/projects/{project_id}/repositories")
def put_project_bindings(project_id: str, payload: RepositoryBindingSet) -> dict[str, Any]:
    init_platform_db()
    requested_ids = {str(item.repository_id) for item in payload.repositories}
    with _db() as conn:
        project = conn.execute("SELECT project_id FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="业务项目不存在，请先完成一次本地采集")

        for item in payload.repositories:
            conflict = conn.execute(
                "SELECT project_id FROM project_repository_bindings WHERE provider='gitlab' AND repository_id=?",
                (str(item.repository_id),),
            ).fetchone()
            if conflict and conflict["project_id"] != project_id:
                raise HTTPException(
                    status_code=409,
                    detail=f"仓库 {item.path_with_namespace} 已绑定到项目 {conflict['project_id']}",
                )

        existing = conn.execute(
            "SELECT repository_id FROM project_repository_bindings WHERE project_id=? AND provider='gitlab'",
            (project_id,),
        ).fetchall()
        for row in existing:
            if str(row["repository_id"]) not in requested_ids:
                conn.execute(
                    "DELETE FROM project_repository_bindings WHERE project_id=? AND provider='gitlab' AND repository_id=?",
                    (project_id, str(row["repository_id"])),
                )

        now = _now()
        for item in payload.repositories:
            conn.execute(
                """
                INSERT INTO project_repository_bindings(
                    project_id, provider, repository_id, repository_name, path_with_namespace,
                    web_url, default_branch, visibility, last_activity_at, created_at, updated_at
                ) VALUES (?, 'gitlab', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, repository_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    repository_name=excluded.repository_name,
                    path_with_namespace=excluded.path_with_namespace,
                    web_url=excluded.web_url,
                    default_branch=excluded.default_branch,
                    visibility=excluded.visibility,
                    last_activity_at=excluded.last_activity_at,
                    updated_at=excluded.updated_at
                """,
                (
                    project_id,
                    str(item.repository_id),
                    item.name,
                    item.path_with_namespace,
                    item.web_url,
                    item.default_branch,
                    item.visibility,
                    item.last_activity_at,
                    now,
                    now,
                ),
            )
    return get_project_bindings(project_id)


@router.get("/internal/gitlab/runtime-config")
def internal_gitlab_runtime_config(
    x_collector_token: str | None = Header(default=None),
) -> dict[str, Any]:
    if COLLECTOR_TOKEN and x_collector_token != COLLECTOR_TOKEN:
        raise HTTPException(status_code=401, detail="invalid collector token")
    row = _connection_row()
    if not row or not row.get("token_cipher"):
        return {"configured": False, "version": 1, "projects": []}
    try:
        token = decrypt_secret(row.get("token_cipher"))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    bindings = _binding_rows()
    if not bindings:
        return {"configured": False, "version": 1, "projects": []}

    with _db() as conn:
        names = {
            str(item["project_id"]): str(item["project_name"])
            for item in conn.execute("SELECT project_id, project_name FROM projects").fetchall()
        }

    grouped: dict[str, dict[str, Any]] = {}
    for item in bindings:
        project_id = str(item["project_id"])
        group = grouped.setdefault(
            project_id,
            {"project_id": project_id, "project_name": names.get(project_id, project_id), "repositories": []},
        )
        group["repositories"].append(
            {
                "id": f"gitlab-{item['repository_id']}",
                "role": "application",
                "provider": "gitlab",
                "url": item["web_url"],
                "api_project_path": item["path_with_namespace"],
            }
        )
    return {
        "configured": True,
        "version": 1,
        "gitlab_base_url": row.get("base_url") or DEFAULT_GITLAB_URL,
        "gitlab_token": token,
        "projects": list(grouped.values()),
    }
