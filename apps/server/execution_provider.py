from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import main

router = APIRouter(prefix="/api/v1/execution", tags=["execution"])
# Internal tRPC contract verified against this source revision, not a public API.
SUPPORTED_HOST_VERSION = "1.36.0"
SUPPORTED_SOURCE_REVISION = "9a50076c324b3d2575762e5bdcba6838061c8be5"


class Launch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    project_id: str = Field(min_length=1, max_length=200)
    repository_id: str = Field(min_length=1, max_length=200)
    task_id: str = Field(min_length=1, max_length=200)
    task_title: str = Field(min_length=1, max_length=200)
    agent: str = Field(default="codex", pattern="^codex$")
    prompt: str = Field(default="", max_length=12000)
    model_profile: Literal["fast", "balanced", "strong"] | None = None
    reasoning_effort: Literal["low", "medium", "high"] = "medium"


def settings() -> dict:
    path = os.getenv("CAO_SUPERSET_CONFIG")
    if not path:
        raise HTTPException(503, "Superset 本地执行尚未配置")
    try:
        value = json.loads(Path(path).read_text())
        if value.get("manifest_path"):
            manifest = json.loads(Path(value["manifest_path"]).read_text())
            endpoint = urlparse(manifest["endpoint"])
            if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}:
                raise ValueError("manifest must describe a loopback host")
            host = value.get("connect_host", "127.0.0.1")
            if host not in {"127.0.0.1", "localhost", "host.docker.internal"}:
                raise ValueError("invalid host bridge")
            value["url"] = f"http://{host}:{endpoint.port}"
            value["token"] = manifest["authToken"]
            value["organization_id"] = manifest["organizationId"]
        parsed = urlparse(value["url"])
        if (parsed.scheme != "http" or parsed.hostname not in
                {"127.0.0.1", "localhost", "host.docker.internal"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or not parsed.port or not value["token"]):
            raise ValueError("invalid local endpoint")
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Superset 配置无效，请检查本机地址与令牌") from None


def authorize(token: str | None) -> None:
    if not main.COLLECTOR_TOKEN:
        raise HTTPException(503, "执行入口必须配置访问令牌")
    main.require_collector_token(token)


def call(config: dict, procedure: str, payload=None, *, mutation=False):
    # This query also seeds defaults on an empty Host and therefore can write.
    if mutation or procedure == "settings.agentConfigs.list":
        require_compatible_host(call(config, "health.check"))
    try:
        with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
            url = config["url"].rstrip("/") + "/trpc/" + procedure
            headers = {"Authorization": "Bearer " + config["token"]}
            if mutation:
                response = client.post(url, headers=headers, json={"json": payload})
            else:
                params = {"input": json.dumps({"json": payload})} if payload is not None else None
                response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()["result"]["data"]["json"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # A failed response does not prove a mutation failed on the host.
        raise HTTPException(502, "本地 Host 调用未确认；写操作不会自动重试，请先检查执行记录") from None


def require_compatible_host(health):
    if not isinstance(health, dict) or health.get("version") != SUPPORTED_HOST_VERSION:
        raise HTTPException(503, "Superset Host 版本不兼容，已拒绝写入；请恢复已验证版本")


def db():
    connection = main.get_db()
    connection.execute("""CREATE TABLE IF NOT EXISTS executions (
        id TEXT PRIMARY KEY, request_json TEXT NOT NULL, result_json TEXT NOT NULL)""")
    connection.commit()
    return connection


def save(connection, execution):
    connection.execute("UPDATE executions SET result_json=? WHERE id=?",
                       (json.dumps(execution), execution["id"]))
    connection.commit()


@router.get("/provider")
def provider(x_collector_token: str | None = Header(default=None)):
    authorize(x_collector_token)
    config = settings()
    health = call(config, "health.check")
    return {"provider": "superset", "health": health,
            "compatibility": {"expected_version": SUPPORTED_HOST_VERSION,
                              "verified_source_revision": SUPPORTED_SOURCE_REVISION,
                              "version_matches": isinstance(health, dict) and health.get("version") == SUPPORTED_HOST_VERSION,
                              "runtime_revision_attested": False},
            "bindings": config.get("bindings", []), "agents": ["codex"]}


@router.get("/runs")
def runs(x_collector_token: str | None = Header(default=None)):
    authorize(x_collector_token)
    with db() as connection:
        rows = connection.execute("SELECT result_json FROM executions ORDER BY rowid DESC LIMIT 100").fetchall()
    return {"executions": [json.loads(row[0]) for row in rows]}


@router.post("/runs")
def launch(payload: Launch, x_collector_token: str | None = Header(default=None)):
    authorize(x_collector_token)
    if payload.model_profile:
        from execution_p2 import check_scope
        check_scope(payload.prompt)
    config = settings()
    binding = next((item for item in config.get("bindings", [])
                    if item["project_id"] == payload.project_id
                    and item["repository_id"] == payload.repository_id), None)
    if not binding:
        raise HTTPException(422, "该业务项目尚未绑定此执行仓库")
    request = payload.model_dump(mode="json")
    execution = dict(request, id=str(payload.request_id), provider="superset",
                     provider_instance=config.get("organization_id", config["url"]),
                     workspace_id=str(payload.request_id), session_id=None,
                     status="creating_workspace", created_at=main.now_utc(),
                     updated_at=main.now_utc(), formal_completion=False, p2=bool(payload.model_profile))
    with db() as connection:
        try:
            connection.execute("INSERT INTO executions VALUES (?,?,?)",
                               (execution["id"], json.dumps(request), json.dumps(execution)))
            connection.commit()
        except sqlite3.IntegrityError:
            row = connection.execute("SELECT request_json,result_json FROM executions WHERE id=?",
                                     (execution["id"],)).fetchone()
            if json.loads(row[0]) != request:
                raise HTTPException(409, "同一请求 ID 不能用于不同任务") from None
            return json.loads(row[1])
        try:
            selection = {}
            if payload.model_profile:
                from execution_p2 import resolve_profile
                selection = resolve_profile(config, payload.model_profile, payload.reasoning_effort)
                execution.update(selection["display"])
                from execution_p2 import POLICY
                launch_prompt = POLICY + f"\nproject_id={payload.project_id}; task_id={payload.task_id}; report session_id={execution['id']}\n" + payload.prompt
            result = call(config, "workspaces.create", {
                "id": execution["id"], "projectId": binding["superset_project_id"],
                "checkout": "worktree", "branch": "codex/cao-" + execution["id"],
                "skipBranchPrefix": True, "baseBranch": binding["base_branch"],
                "name": payload.task_title, "runSetup": False,
            }, mutation=True)
            execution["workspace_id"] = result["workspace"]["id"]
            execution["branch"] = result["workspace"]["branch"]
            execution["status"] = "starting_agent"
            save(connection, execution)
            call(config, "settings.agentConfigs.list")
            result = call(config, "agents.run", {
                "workspaceId": execution["workspace_id"], "agent": selection.get("agent", payload.agent),
                "prompt": launch_prompt if payload.model_profile else payload.prompt, "surface": "terminal",
                **selection.get("launch", {}),
            }, mutation=True)
            execution["session_id"] = result["sessionId"]
            execution["status"] = "agent_started"
            if payload.model_profile:
                execution["p2"] = True
                execution["agent_definition_id"] = selection["agent"]
        except HTTPException as error:
            execution["status"] = "blocked_compatibility" if error.status_code == 503 else "unknown"
            execution["diagnostic"] = (error.detail if error.status_code == 503 else
                                       "Host 操作结果未确认；请检查 Workspace/Session，禁止自动重放")
        except (KeyError, TypeError):
            execution["status"] = "unknown"
            execution["diagnostic"] = "Host 操作结果未确认；请检查 Workspace/Session，禁止自动重放"
        execution["updated_at"] = main.now_utc()
        save(connection, execution)
    return execution


@router.get("/runs/{execution_id}")
def inspect(execution_id: UUID, x_collector_token: str | None = Header(default=None)):
    authorize(x_collector_token)
    with db() as connection:
        row = connection.execute("SELECT result_json FROM executions WHERE id=?",
                                 (str(execution_id),)).fetchone()
        if not row:
            raise HTTPException(404, "执行记录不存在")
        execution = json.loads(row[0])
        config = settings()
        if execution.get("provider_instance") != config.get("organization_id", config["url"]):
            raise HTTPException(409, "执行属于另一个 Host，请恢复原 Host 配置后检查")
        workspace = call(config, "workspace.get", {"id": execution["workspace_id"]})
        terminals = call(config, "terminal.list", {"workspaceId": execution["workspace_id"]})
        execution["workspace"] = workspace
        execution["terminals"] = terminals.get("sessions", [])
        session = next((item for item in execution["terminals"]
                        if item.get("terminalId") == execution.get("session_id")), None)
        execution["runtime_status"] = (
            "running" if session and not session.get("exited") else
            "exited" if session else "not_observed"
        )
        if execution.get("p2"):
            from execution_p2 import observe
            observe(config, execution)
        execution["updated_at"] = main.now_utc()
        save(connection, execution)
    return execution
