"""Controlled Personal Agent execution; no terminal or model passthrough."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import execution_provider as ep
from p2_policy import P2_ARGS

router = APIRouter(prefix="/api/v1/personal/execution", tags=["personal-execution"])

POLICY = """P2 execution scope: work ONLY in this isolated worktree. Edit code and run tests.
Never commit, push, merge, force-push, deploy, delete repositories/branches, modify formal
main/cao or write business databases. Never read credentials. Do not bypass sandbox or
approval policy. If prohibited work is requested, stop and report blocked. Do not create agents.
Report real task.started/progress/test.result/task.finished events using cao-sentinel MCP,
with the supplied project_id/task_id; test counts must come from actual tests. Local finished
is not formal project completion. Do not include secrets or private context in summaries.
"""


def check_scope(text):
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise HTTPException(422, "不允许终端控制字符")
    lowered = text.lower()
    forbidden = r"push|merge|deploy|部署|强推|删除仓库|删除分支|写数据库|修改(?:正式)?(?:main|cao)|提交"
    # Negative instructions remain valid, e.g. 用户的“不要提交”。
    positive = re.sub(
        r"(?:不要|禁止|不得|不允许|never|do not)\s*(?:自动)?\s*(?:" + forbidden + r")",
        "",
        lowered,
    )
    if re.search(forbidden, positive):
        raise HTTPException(422, "P2 只允许隔离代码修改、测试与反馈，该请求超出范围")


def resolve_profile(config, profile, effort):
    mapping = config.get("model_profiles", {})
    model = mapping.get(profile)
    if not isinstance(model, str) or not model or len(model) > 80:
        raise HTTPException(503, "本机模型档位尚未验证配置")
    agent_id = config.get("p2_agent_id")
    configs = ep.call(config, "settings.agentConfigs.list")
    agent = next((a for a in configs if a.get("id") == agent_id), None)
    # A dedicated preset is required; never run a user's legacy --yolo config.
    required = P2_ARGS
    args = agent.get("args", []) if agent else []
    if (
        not agent
        or agent.get("presetId") != "codex"
        or args != required
        or agent.get("promptArgs") not in ([], ["--"])
        or agent.get("promptTransport") != "argv"
        or os.path.basename(agent.get("command", "")) != "codex"
    ):
        raise HTTPException(503, "P2 需要已验证的隔离 Codex 配置，拒绝宽权限启动")
    ep.require_compatible_host(ep.call(config, "health.check"))
    capability = ep.call(config, "terminal.p2Capabilities")
    if capability != {"guardedAgentSend": 2}:
        raise HTTPException(503, "Host 未安装 P2 会话绑定保护")
    return {
        "agent": agent_id,
        "launch": {"model": model, "effort": effort},
        "display": {
            "resolved_model": model,
            "model_profile": profile,
            "reasoning_effort": effort,
            "policy": "isolated-no-network-v1",
        },
    }


def observe(config, execution):
    bindings = ep.call(
        config,
        "terminalAgents.listByWorkspace",
        {"workspaceId": execution["workspace_id"]},
    )
    binding = next(
        (
            b
            for b in bindings
            if b.get("terminalId") == execution.get("session_id")
            and b.get("agentId") == "codex"
            and b.get("definitionId") in {None, execution.get("agent_definition_id")}
            and b.get("endedAt") is None
        ),
        None,
    )
    if (
        binding
        and execution.get("agent_session_id")
        and binding.get("agentSessionId") != execution["agent_session_id"]
    ):
        binding = None  # a replacement Codex in the same terminal is not this run
    if execution.get("runtime_status") != "running":
        binding = None  # stale hook records after a dead PTY are not a live agent
    execution["needs_user"] = False
    execution["status"] = "unknown"
    if binding:
        execution["agent_session_id"] = binding.get("agentSessionId")
        execution["bound_definition_id"] = binding.get("definitionId")
        event = binding.get("lastEventType")
        execution["status"] = (
            "waiting"
            if event in {"Stop", "PermissionRequest", "Notification"}
            else "failed"
            if event == "Failed"
            else "running"
        )
        execution["needs_user"] = execution["status"] == "waiting"
    elif any(
        b.get("terminalId") == execution.get("session_id")
        and b.get("endedAt") is not None
        for b in bindings
    ):
        execution["status"] = "finished"
    elif execution.get("runtime_status") == "exited":
        execution["status"] = "finished"  # runtime only, never formal completion
    execution["formal_completion"] = False
    execution["latest_progress"] = None
    execution["tests_passed"] = execution["tests_failed"] = None
    # Exact task AND session correlation. Historical/M9 events cannot leak into P2.
    if execution.get("agent_session_id"):
        events = [
            e
            for e in ep.main.recent_agent_events(execution["project_id"], 500)
            if e.get("task_id") == execution["task_id"]
            and e.get("session_id") == execution["id"]
        ]
        for event in events:
            data = event.get("data", {})
            if event.get("event_type") == "task.progress":
                execution["latest_progress"] = str(data.get("summary", ""))[:160]
            if event.get("event_type") == "test.result":
                for name, source in (
                    ("tests_passed", "passed"),
                    ("tests_failed", "failed"),
                ):
                    n = data.get(source)
                    if (
                        isinstance(n, int)
                        and not isinstance(n, bool)
                        and 0 <= n <= 100000
                    ):
                        execution[name] = n
    execution["safe_summary"] = {
        "running": "Codex 正在工作",
        "waiting": "Codex 等待下一步",
        "finished": "执行进程已结束，未代表正式交付",
        "failed": "Codex 执行失败",
        "unknown": "会话状态未确认",
    }[execution["status"]]


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    text: str = Field(min_length=1, max_length=2000)


def feedback(execution_id: UUID, payload: Feedback, token):
    ep.authorize(token)
    check_scope(payload.text)
    # Inspect validates current Host and fresh live binding before any write.
    execution = ep.inspect(execution_id, token)
    if (
        not execution.get("p2")
        or execution.get("status") not in {"running", "waiting"}
        or not execution.get("agent_session_id")
    ):
        raise HTTPException(409, "没有已确认的存活 Codex 会话，拒绝发送或重启")
    digest = hashlib.sha256(payload.text.encode()).hexdigest()
    key = str(payload.request_id)
    with ep.db() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS execution_feedback (id TEXT PRIMARY KEY, execution_id TEXT, digest TEXT, status TEXT, created_at TEXT)"
        )
        prior = connection.execute(
            "SELECT execution_id,digest,status FROM execution_feedback WHERE id=?",
            (key,),
        ).fetchone()
        if prior:
            if prior[0] != str(execution_id) or prior[1] != digest:
                raise HTTPException(409, "同一反馈 ID 不能用于不同内容")
            return {"request_id": key, "status": prior[2]}
        connection.execute(
            "INSERT INTO execution_feedback VALUES (?,?,?,?,?)",
            (key, str(execution_id), digest, "unknown", ep.main.now_utc()),
        )
        connection.commit()
        # Persist unknown BEFORE send; never replay after timeout/crash.
        send_config = ep.settings()
        if execution.get("provider_instance") != send_config.get(
            "organization_id", send_config["url"]
        ):
            raise HTTPException(409, "Host 在反馈前已切换，拒绝发送")
        ep.call(
            send_config,
            "terminal.sendAgent",
            {
                "workspaceId": execution["workspace_id"],
                "terminalId": execution["session_id"],
                "agentSessionId": execution["agent_session_id"],
                "definitionId": execution.get("bound_definition_id"),
                "text": POLICY + "\nUser feedback:\n" + payload.text,
            },
            mutation=True,
        )
        connection.execute(
            "UPDATE execution_feedback SET status='sent' WHERE id=?", (key,)
        )
        connection.commit()
    return {"request_id": key, "status": "sent"}


# Separate Muse capability. It never carries the collector/platform credential.
def personal_auth(request: Request, token):
    expected = os.getenv("CAO_MUSE_TOKEN", "")
    if (
        not expected
        or expected == ep.main.COLLECTOR_TOKEN
        or not token
        or not hmac.compare_digest(token, expected)
    ):
        raise HTTPException(401, "Muse capability required")
    allowed = {"127.0.0.1", "::1", "testclient"}
    # Only an explicitly configured Docker bridge peer, never all private clients.
    bridge = os.getenv("CAO_MUSE_BRIDGE_CLIENT", "")
    if bridge:
        allowed.add(bridge)
    if not request.client or request.client.host not in allowed:
        raise HTTPException(403, "Muse execution is loopback-only")


def personal_run(execution_id):
    with ep.db() as connection:
        row = connection.execute(
            "SELECT result_json FROM executions WHERE id=?", (str(execution_id),)
        ).fetchone()
    if not row:
        raise HTTPException(404, "执行不存在")
    value = json.loads(row[0])
    allowed = {
        b["project_id"]
        for b in ep.settings().get("bindings", [])
        if b.get("personal_enabled")
    }
    if not value.get("p2") or value["project_id"] not in allowed:
        raise HTTPException(403, "该执行不属于 Muse 授权项目")
    return value


def public(value):
    fields = {
        "id",
        "status",
        "task_title",
        "project_id",
        "repository_id",
        "workspace_id",
        "session_id",
        "branch",
        "model_profile",
        "reasoning_effort",
        "resolved_model",
        "runtime_status",
        "latest_progress",
        "tests_passed",
        "tests_failed",
        "needs_user",
        "safe_summary",
        "formal_completion",
    }
    value = {k: v for k, v in value.items() if k in fields}
    value["status"] = {
        "creating_workspace": "starting",
        "starting_agent": "starting",
        "agent_started": "starting",
        "blocked_compatibility": "failed",
    }.get(value.get("status"), value.get("status", "unknown"))
    return value


@router.get("/provider")
def personal_provider(
    request: Request, x_muse_token: str | None = Header(default=None)
):
    personal_auth(request, x_muse_token)
    config = ep.settings()
    health = ep.call(config, "health.check")
    ep.require_compatible_host(health)
    return {
        "bindings": [
            {"project_id": b["project_id"], "repository_id": b["repository_id"]}
            for b in config.get("bindings", [])
            if b.get("personal_enabled")
        ],
        "model_profiles": config.get("model_profiles", {}),
        "reasoning_efforts": ["low", "medium", "high"],
    }


@router.post("/runs")
def personal_launch(
    payload: ep.Launch,
    request: Request,
    x_muse_token: str | None = Header(default=None),
):
    personal_auth(request, x_muse_token)
    check_scope(payload.prompt)
    if not any(
        b.get("personal_enabled")
        and b["project_id"] == payload.project_id
        and b["repository_id"] == payload.repository_id
        for b in ep.settings().get("bindings", [])
    ):
        raise HTTPException(403, "项目仓库未授权 Muse 执行")
    if not payload.model_profile:
        raise HTTPException(422, "必须指定受控模型档位")
    # Task ID is generated from request ID, preventing collision with business tasks.
    payload = payload.model_copy(
        update={"task_id": "P2-" + str(payload.request_id), "prompt": payload.prompt}
    )
    return public(ep.launch(payload, ep.main.COLLECTOR_TOKEN))


@router.get("/runs/{execution_id}")
def personal_inspect(
    execution_id: UUID,
    request: Request,
    x_muse_token: str | None = Header(default=None),
):
    personal_auth(request, x_muse_token)
    personal_run(execution_id)
    return public(ep.inspect(execution_id, ep.main.COLLECTOR_TOKEN))


@router.post("/runs/{execution_id}/feedback")
def personal_feedback(
    execution_id: UUID,
    payload: Feedback,
    request: Request,
    x_muse_token: str | None = Header(default=None),
):
    personal_auth(request, x_muse_token)
    personal_run(execution_id)
    return feedback(execution_id, payload, ep.main.COLLECTOR_TOKEN)


@ep.router.post("/runs/{execution_id}/feedback")
def internal_feedback(
    execution_id: UUID,
    payload: Feedback,
    x_collector_token: str | None = Header(default=None),
):
    return feedback(execution_id, payload, x_collector_token)
