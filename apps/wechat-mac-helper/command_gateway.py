"""Receive owner-only WeChat commands and return results to a bound test chat.

The only input conversation is the current account's File Transfer Assistant.
Replies go to the explicitly bound Agent Hub private chat when its connector is
online, or to the personal sender when it becomes available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from tracememo_adapter import TraceMemoError, TraceMemoReader

STATE_ROOT = Path.home() / "Library/Application Support/AI Dev Management"
TOKEN_FILE = STATE_ROOT / "tracememo-api-token"
DATABASE = STATE_ROOT / "wechat-command-gateway.sqlite3"
DEEPSEEK_KEY_FILE = STATE_ROOT / "deepseek-api-key"
BOT_RECIPIENT_FILE = STATE_ROOT / "wechat-command-recipient.json"
TRACE_MEMO = "http://127.0.0.1:6131"
CENTRAL = "http://127.0.0.1:8080"
ONEBOT = "http://127.0.0.1:58080"
REPO_ROOT = Path(__file__).resolve().parents[2]
TALKER = "filehelper"
PREFIX = "【项目助手】"


def _json_request(url: str, *, token: str | None = None, body: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def open_database(path: Path = DATABASE) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    if path.exists():
        os.chmod(path, 0o600)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS commands (
            message_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            command TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reply TEXT,
            delivered_at INTEGER,
            error TEXT,
            attempts INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS commands_status_idx ON commands(status, created_at);
        CREATE TABLE IF NOT EXISTS gateway_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    if "attempts" not in {row[1] for row in conn.execute("PRAGMA table_info(commands)")}:
        conn.execute("ALTER TABLE commands ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    return conn


def message_identity(message: dict[str, Any]) -> str:
    identity = str(message.get("serverId") or "").strip()
    if identity and identity != "0":
        return f"server:{identity}"
    fallback = json.dumps(
        [TALKER, message.get("localId"), message.get("createTime"), message.get("content")],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "hash:" + hashlib.sha256(fallback.encode()).hexdigest()


def accept_message(message: dict[str, Any]) -> bool:
    text = str(message.get("content") or "").strip()
    return (
        message.get("isSender") is True
        and message.get("type") == "普通文本"
        and (text == "/项目" or text.startswith("/项目 ")
             or text.startswith(("/问 ", "/执行 ", "/搜索 "))
             or text in {"/状态", "/帮助"})
        and len(text) <= 2000
    )


def ingest(conn: sqlite3.Connection, reader: TraceMemoReader, now: int | None = None) -> int:
    now = now or int(time.time())
    checkpoint = conn.execute("SELECT value FROM gateway_meta WHERE key='last_poll'").fetchone()
    # WeChat can sync a message well after its original timestamp (for example
    # after the Mac account logs back in). Re-scan a bounded window; the message
    # ID primary key prevents a delayed sync from executing the command twice.
    start = min(int(checkpoint[0]) - 120, now - 24 * 3600) if checkpoint else now - 24 * 3600
    messages = reader._get("/api/v1/chatlog", params={"talker": TALKER, "startTime": str(start)}).get("messages")
    if not isinstance(messages, list):
        raise ValueError("TraceMemo returned an invalid chatlog")
    added = 0
    for message in messages:
        if not isinstance(message, dict) or not accept_message(message):
            continue
        created = int(message.get("createTime") or 0)
        if not (start <= created <= now + 60):
            continue
        cursor = conn.execute(
            "INSERT OR IGNORE INTO commands(message_id,created_at,command) VALUES(?,?,?)",
            (message_identity(message), created, str(message["content"]).strip()),
        )
        added += cursor.rowcount
    conn.execute(
        "INSERT INTO gateway_meta(key,value) VALUES('last_poll',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(now),),
    )
    conn.commit()
    return added


def _projects() -> list[dict[str, Any]]:
    result = _json_request(f"{CENTRAL}/api/v1/projects")
    if not isinstance(result, list):
        raise ValueError("Central returned an invalid project list")
    return [item for item in result if isinstance(item, dict)]


def _project_id(query: str, projects: list[dict[str, Any]]) -> str:
    aliases = {
        "缺陷": "power-defect-agent",
        "低电压": "low-voltage",
        "hyclaw": "hy-claw",
        "hy claw": "hy-claw",
        "本地部署": "hyclaw-local-agent",
    }
    needle = query.strip().casefold()
    if needle in aliases:
        return aliases[needle]
    exact = [p for p in projects if needle in {str(p.get("project_id") or "").casefold(), str(p.get("project_name") or "").casefold()}]
    if len(exact) == 1:
        return str(exact[0]["project_id"])
    partial = [p for p in projects if needle and needle in str(p.get("project_name") or "").casefold()]
    if len(partial) == 1:
        return str(partial[0]["project_id"])
    raise ValueError("项目不唯一或不存在；请先发送 /项目 列表")


def _lines(label: str, items: Any, limit: int = 3) -> list[str]:
    if not isinstance(items, list) or not items:
        return []
    values = []
    for item in items[:limit]:
        if isinstance(item, str):
            values.append(_short(item.lstrip("- ").strip(), 200))
        elif isinstance(item, dict):
            values.append(_short(item.get("title") or item.get("summary") or item.get("text"), 200))
    return [f"{label}：" + "；".join(x for x in values if x)] if any(values) else []


def _short(value: Any, limit: int = 110) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _mobile_reply(value: str, limit: int = 1450) -> str:
    if len(value) <= limit:
        return value
    notice = "\n（回答较长，已截取；可缩小问题范围继续问）"
    budget = max(0, limit - len(notice))
    if not budget:
        return value[:max(0, limit)]
    break_at = value.rfind("\n", budget // 2, budget)
    if break_at < 0:
        break_at = budget
    return value[:break_at].rstrip() + notice


def _safe_repo_url(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        parts = urllib.parse.urlsplit(raw)
        if parts.scheme not in {"http", "https", "ssh"} or not parts.hostname:
            return ""
        host = parts.hostname + (f":{parts.port}" if parts.port else "")
    except ValueError:
        return ""
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, "", ""))


def _project_action(command: str, projects: list[dict[str, Any]]) -> tuple[str, str]:
    """Resolve full project names and aliases before splitting off the action."""
    remaining = command[len("/项目"):].strip()
    aliases = {"缺陷": "power-defect-agent", "低电压": "low-voltage",
               "HY CLAW": "hy-claw", "HyClaw": "hy-claw", "本地部署": "hyclaw-local-agent"}
    candidates = [(str(p.get("project_id") or ""), str(p.get("project_id") or "")) for p in projects]
    candidates += [(str(p.get("project_name") or ""), str(p.get("project_id") or "")) for p in projects]
    candidates += list(aliases.items())
    for label, project_id in sorted(candidates, key=lambda pair: len(pair[0]), reverse=True):
        if label and remaining.casefold().startswith(label.casefold()):
            tail = remaining[len(label):]
            if not tail or tail[0].isspace():
                return project_id, tail.strip() or "概览"
    first, _, action = remaining.partition(" ")
    return _project_id(first, projects), action.strip() or "概览"


def _code_repositories(repositories):
    return [repo for repo in repositories or [] if isinstance(repo, dict)
            and repo.get("role") != "materials" and not str(repo.get("url") or "").lower().startswith("file:")]


def _stage_lines(brief):
    record = brief.get("recorded_stage") or {}
    inferred = brief.get("current_stage")
    if isinstance(record, dict) and record.get("stage"):
        lines = ["记录阶段：" + _short(record["stage"], 120)]
        if record.get("modified_at"):
            lines.append("认知记录更新：" + str(record["modified_at"])[:10])
        if inferred and inferred != record["stage"]:
            lines.append("材料推断另为：" + _short(inferred, 100) + "（尚待核对）")
        return lines
    return ["资料推断阶段：" + _short(inferred or "待确认", 120) + "（不代表最新验收）"]


def _search_reply(name: str, result: dict[str, Any]) -> str:
    materials = result.get("results") or []
    conversations = result.get("communications") or []
    if not isinstance(materials, list) or not isinstance(conversations, list):
        raise ValueError("搜索结果格式错误")
    lines = [f"{name}：找到 {result.get('count', 0)} 条（材料 {result.get('material_count', 0)}，沟通 {result.get('communication_count', 0)}）"]
    for item in materials[:3]:
        if not isinstance(item, dict):
            continue
        material = item.get("material") or {}
        if not isinstance(material, dict):
            continue
        title = _short(material.get("name") or material.get("path") or "未命名材料", 85)
        kind = "目录元数据，未读取正文" if material.get("metadata_only") else _short(material.get("material_type_label") or "资料", 20)
        location = _short(item.get("locator"), 35)
        lines.append(f"资料｜{title}（{kind}{' · ' + location if location else ''}）")
        snippet = _short(item.get("snippet"), 130)
        if snippet:
            lines.append(f"  {snippet}")
        path = _short(material.get("path"), 150)
        if path:
            lines.append(f"  来源：{path}")
    for item in conversations[:2]:
        if not isinstance(item, dict):
            continue
        origin = _short(item.get("conversation_name") or "项目沟通", 35)
        date = str(item.get("observed_at") or "")[:16].replace("T", " ")
        lines.append(f"沟通｜{origin}{' · ' + date if date else ''}")
        lines.append("  " + _short(item.get("text"), 130))
    if len(lines) == 1:
        lines.append("暂无匹配资料或沟通记录。")
    return "\n".join(lines)[:1700]


def global_search_command(command: str) -> str:
    query = command[len("/搜索 "):].strip()
    if not query:
        return "请在 /搜索 后输入关键词。"
    result = _json_request(f"{CENTRAL}/api/v1/search?" + urllib.parse.urlencode({"q": query, "limit": 6}))
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        raise ValueError("跨项目搜索结果格式错误")
    lines = [f"跨项目搜索“{_short(query, 50)}”：找到 {result.get('count', 0)} 项"]
    for item in result["results"][:6]:
        if not isinstance(item, dict):
            continue
        name = _short(item.get("project_name") or item.get("project_id"), 35)
        kind = "沟通" if item.get("source_type") == "conversation" else "目录元数据，未读取正文" if item.get("metadata_only") else "资料"
        origin = _short(item.get("source_name") or item.get("source_path"), 60)
        date = str(item.get("source_time") or "")[:10]
        lines.append(f"• {name}｜{kind}｜{origin}{' · ' + date if date else ''}")
        snippet = _short(item.get("snippet"), 95)
        if snippet:
            lines.append("  " + snippet)
        path = _short(item.get("source_path"), 110)
        if path:
            lines.append("  来源：" + path)
    if len(lines) == 1:
        lines.append("没有匹配内容。")
    if result.get("conversation_available") is False:
        lines.append("此部署尚未接入授权沟通记录。")
    return _mobile_reply("\n".join(lines), 1700)


def _intelligence_reply(name: str, action: str, result: dict[str, Any]) -> str:
    profile = result.get("profile") or {}
    context = result.get("context") or {}
    summary = result.get("summary") or {}
    if not all(isinstance(value, dict) for value in (profile, context, summary)):
        raise ValueError("项目认知格式错误")
    if action == "背景":
        project = context.get("project") or {}
        if not isinstance(project, dict):
            project = {}
        purpose = project.get("purpose") or project.get("description") or profile.get("description")
        lines = [name, "背景：" + _short(purpose or "尚未录入可确认的项目背景。", 350)]
        stage = project.get("current_stage") or (result.get("progress") or {}).get("current_stage")
        if stage:
            lines.append("阶段：" + _short(stage, 100))
        repositories = _code_repositories(profile.get("repositories"))
        for repo in repositories[:3]:
            if isinstance(repo, dict):
                lines.append("代码：" + _short(_safe_repo_url(repo.get("url")) or repo.get("id"), 160))
        lines.append("资料：" + str(summary.get("material_count") or 0) + " 份")
        if profile.get("observed_at"):
            lines.append("本机采集：" + str(profile["observed_at"])[:16].replace("T", " "))
        return "\n".join(lines)[:1700]
    if action in {"代码", "仓库"}:
        repositories = _code_repositories(profile.get("repositories"))
        lines = [name + "：代码仓库"]
        for repo in repositories[:6]:
            if not isinstance(repo, dict):
                continue
            label = _short(repo.get("id") or "未命名仓库", 60)
            provider = _short(repo.get("provider") or "本机", 30)
            branch = _short(repo.get("branch") or "分支未识别", 50)
            head = str(repo.get("head") or "")[:12]
            lines.append(f"• {label}（{provider} · {branch}{' · ' + head if head else ''}）")
            url = _safe_repo_url(repo.get("url"))
            if url:
                lines.append("  " + _short(url, 180))
            if repo.get("dirty"):
                lines.append("  本地工作区有未提交修改")
        if len(lines) == 1:
            lines.append("尚未采集到代码仓库。")
        if profile.get("observed_at"):
            lines.append("本机采集：" + str(profile["observed_at"])[:16].replace("T", " "))
        return "\n".join(lines)[:1700]
    materials = result.get("materials") or []
    if not isinstance(materials, list):
        raise ValueError("项目材料格式错误")
    current = [m for m in materials if isinstance(m, dict) and m.get("version_status") in
               {"current", "latest_period", "primary", "active_related", "single"}]
    listed = sorted(current or [m for m in materials if isinstance(m, dict)],
                    key=lambda m: str(m.get("modified_at") or ""), reverse=True)[:5]
    lines = [f"{name}：已识别 {summary.get('material_count', len(materials))} 份资料，以下为当前/最新材料："]
    for material in listed:
        modified = str(material.get("modified_at") or "")[:10]
        lines.append(f"• {_short(material.get('name') or material.get('path'), 95)}"
                     f"（{'目录元数据，未读取正文' if material.get('metadata_only') else _short(material.get('material_type_label') or '资料', 20)}"
                     f"{' · ' + modified if modified else ''}）")
        if material.get("summary"):
            lines.append("  " + _short(material["summary"], 110))
        if material.get("path"):
            lines.append("  来源：" + _short(material["path"], 150))
    if not listed:
        lines.append("尚未识别到项目材料。")
    return "\n".join(lines)[:1700]


def project_command(command: str) -> str:
    projects = _projects()
    if command.strip() in {"/项目", "/项目 列表", "/项目 项目"}:
        return "已纳管项目：\n" + "\n".join(
            f"• {item.get('project_name') or item.get('project_id')} ({item.get('project_id')})"
            for item in projects
        )
    project_id, action = _project_action(command, projects)
    name = next((str(p.get("project_name") or project_id) for p in projects if p.get("project_id") == project_id), project_id)
    if action.startswith("搜索 "):
        from urllib.parse import urlencode

        result = _json_request(f"{CENTRAL}/api/v1/projects/{project_id}/search?" + urlencode({"q": action[3:].strip(), "limit": 5}))
        if not isinstance(result, dict):
            raise ValueError("搜索结果格式错误")
        return _search_reply(name, result)
    if action in {"背景", "材料", "代码", "仓库"}:
        intelligence = _json_request(f"{CENTRAL}/api/v1/projects/{project_id}/intelligence")
        if not isinstance(intelligence, dict):
            raise ValueError("项目认知格式错误")
        return _intelligence_reply(name, action, intelligence)
    if action not in {"概览", "进度", "问题", "下一步", "任务", "指标"}:
        return "可用命令：/项目 列表；/项目 缺陷 背景；/项目 低电压 材料；/项目 hy-claw 仓库；/项目 hy-claw 搜索 关键词；/帮助"
    result = _json_request(f"{CENTRAL}/api/v1/projects/{project_id}/brief")
    if not isinstance(result, dict):
        raise ValueError("项目简报格式错误")
    lines = [name] + _stage_lines(result)
    source = result.get("source_status") or {}
    if isinstance(source, dict) and source.get("freshness_reference_date"):
        lines.append("资料基准：" + str(source["freshness_reference_date"])[:10] + "；以下为资料摘录，需核对现状")
    if action in {"概览", "进度"}:
        lines += _lines("已完成", result.get("completed"))
        lines += _lines("进行中", result.get("in_progress"))
    if action in {"概览", "进度", "问题"}:
        lines += _lines("问题", result.get("issues"))
    if action in {"概览", "进度", "下一步"}:
        lines += _lines("下一步", result.get("next_steps"))
    if action == "任务":
        summary = result.get("summary") or {}
        lines.append(f"任务：进行中 {summary.get('in_progress_task_count', 0)}，已完成 {summary.get('completed_task_count', 0)}，待处理 {summary.get('attention_task_count', 0)}")
    if action in {"概览", "进度", "指标"}:
        lines += _lines("指标", result.get("latest_metrics"))
    if action == "指标" and not result.get("latest_metrics"):
        lines.append("暂无可确认的最新指标。")
    return _mobile_reply("\n".join(lines), 1700)


def codex_command(command: str, *, readonly: bool) -> str:
    instruction = command.partition(" ")[2].strip()
    if not instruction:
        return "请在命令后写具体任务。"
    codex_home = STATE_ROOT / "codex-wechat-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    os.chmod(codex_home, 0o700)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    env["DEEPSEEK_API_KEY"] = DEEPSEEK_KEY_FILE.read_text(encoding="utf-8").strip()
    if not env["DEEPSEEK_API_KEY"]:
        raise ValueError("DeepSeek API Key 未配置")
    with tempfile.TemporaryDirectory(prefix="wechat-codex-", dir=STATE_ROOT) as temp:
        output = Path(temp) / "answer.txt"
        args = [
            "codex", "exec", "--ephemeral", "--ignore-user-config",
            "-m", "deepseek-flash", "-C", str(REPO_ROOT), "-o", str(output),
            "-c", 'model_provider="deepseek"',
            "-c", 'model_providers.deepseek.name="DeepSeek"',
            "-c", 'model_providers.deepseek.base_url="https://api.deepseek.com"',
            "-c", 'model_providers.deepseek.env_key="DEEPSEEK_API_KEY"',
            "-c", 'model_providers.deepseek.wire_api="responses"',
            "-c", "model_providers.deepseek.supports_websockets=false",
        ]
        if readonly:
            args += ["-s", "read-only"]
        else:
            args += ["--dangerously-bypass-approvals-and-sandbox"]
        prompt = (
            "这条指令来自本机个人微信账号的文件传输助手。请按用户意图完成，"
            "核对真实项目和证据；不要把令牌或无关私密资料写入回复。"
            + ("本次只读，不修改文件或外部状态。" if readonly else "在用户已授权范围内实际执行，并核验结果。")
            + "\n\n用户指令：\n" + instruction
        )
        try:
            run = subprocess.run(args + [prompt], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900, check=False)
        except subprocess.TimeoutExpired:
            return "Codex 执行超过 15 分钟，已停止；请在本机查看具体状态。"
        answer = output.read_text(encoding="utf-8").strip() if output.exists() else ""
        if run.returncode:
            return "Codex 执行失败；本机已保留任务状态，请在 Codex 中检查。"
    return answer[:1800] or "Codex 已执行，但没有返回文字结果。"


def _intelligence_facts(project_id: str) -> dict[str, Any]:
    """Send only selected project metadata and short material summaries to the model."""
    data = _json_request(f"{CENTRAL}/api/v1/projects/{project_id}/intelligence")
    if not isinstance(data, dict):
        raise ValueError("项目认知格式错误")
    profile = data.get("profile") or {}
    context = data.get("context") or {}
    if not isinstance(profile, dict) or not isinstance(context, dict):
        raise ValueError("项目认知格式错误")
    project = context.get("project") or {}
    if not isinstance(project, dict):
        project = {}
    repositories = []
    for raw in _code_repositories(profile.get("repositories"))[:6]:
        if isinstance(raw, dict):
            repositories.append({**{key: raw.get(key) for key in ("id", "role", "provider", "branch", "head")},
                                 "url": _safe_repo_url(raw.get("url"))})
    current_statuses = {"current", "latest_period", "primary", "active_related", "single"}
    materials = [item for item in data.get("materials") or [] if isinstance(item, dict)]
    materials.sort(key=lambda item: (item.get("version_status") in current_statuses,
                                     str(item.get("modified_at") or "")), reverse=True)
    selected_materials = [
        {"name": item.get("name"), "path": item.get("path"),
         "type": item.get("material_type_label"), "summary": _short(item.get("summary"), 350),
         "modified_at": item.get("modified_at"), "version_status": item.get("version_status"),
         "metadata_only": bool(item.get("metadata_only"))}
        for item in materials[:8]
    ]
    known_facts = []
    for item in (context.get("known_facts") or [])[:8]:
        if isinstance(item, dict):
            known_facts.append({"fact": _short(item.get("fact"), 350), "source": _short(item.get("source"), 120)})
        elif isinstance(item, str):
            known_facts.append(_short(item, 350))
    return {
        "description": _short(project.get("purpose") or project.get("description") or profile.get("description"), 500),
        "context_updated_at": context.get("generated_at") or context.get("modified_at"),
        "context_available": bool(context.get("available")),
        "current_work": [_short(item, 300) for item in (context.get("current_work") or [])[:8]],
        "known_issues": [_short(item, 300) for item in (context.get("known_issues") or [])[:8]],
        "known_facts": known_facts,
        "repositories": repositories,
        "materials": selected_materials,
    }


def project_question(command: str) -> str:
    """Answer from selected Central facts with the user-approved DeepSeek model."""
    question = command.partition(" ")[2].strip()
    if not question:
        return "请在 /问 后写具体问题。"
    projects = _projects()
    selected = []
    for project in projects:
        project_id = str(project.get("project_id") or "")
        name = str(project.get("project_name") or "")
        aliases = {
            "power-defect-agent": ("缺陷",),
            "low-voltage": ("低电压",),
            "hy-claw": ("hy claw", "hyclaw"),
            "hyclaw-local-agent": ("本地部署",),
        }.get(project_id, ())
        if project_id.casefold() in question.casefold() or name in question or any(alias in question.casefold() for alias in aliases):
            selected.append(project)
    explicitly_selected = bool(selected)
    if not selected:
        selected = projects[:8]
    facts = []
    for project in selected[:8]:
        project_id = str(project.get("project_id") or "")
        brief = _json_request(f"{CENTRAL}/api/v1/projects/{project_id}/brief")
        if not isinstance(brief, dict):
            continue
        facts.append({
            "project_id": project_id,
            "project_name": project.get("project_name"),
            **{key: brief.get(key) for key in ("current_stage", "recorded_stage", "current_stage_basis", "completed", "in_progress", "issues", "issue_evidence", "next_steps", "next_step_evidence", "latest_metrics", "summary", "source_status", "statistics_period")},
        })
        if explicitly_selected:
            try:
                facts[-1]["intelligence"] = _intelligence_facts(project_id)
            except (OSError, urllib.error.URLError, ValueError):
                facts[-1]["intelligence_status"] = "unavailable"
    if not facts:
        return "本机研发平台尚无可核对的项目简报，暂时无法回答。"
    key = DEEPSEEK_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError("DeepSeek API Key 未配置")
    payload = {
        "model": "deepseek-flash",
        "messages": [
            {"role": "system", "content": "你是用户的研发项目助手，回复会作为微信纯文本发送。只根据附带的本机项目事实回答；区分已完成、进行中、问题和推断。intelligence.materials 是材料索引和短摘要，不代表已读全文；引用材料时写出文件名。留意 source_status.freshness_reference_date 和 intelligence.context_updated_at，不能把旧资料冒充今天进度。每个项目的事实写出对应 project_id。资料没有的信息明确说不知道。不使用 Markdown 表格，每段简短，尽量不超过 700 个汉字；只列最关键的材料和仓库。不要泄露密钥。"},
            {"role": "user", "content": "问题：" + question + "\n\n本机研发平台事实：" + json.dumps(facts, ensure_ascii=False)[:24000]},
        ],
        "max_tokens": 700,
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    result = _json_request("https://api.deepseek.com/chat/completions", token=key, body=payload)
    if not isinstance(result, dict) or not isinstance(result.get("choices"), list) or not result["choices"]:
        raise ValueError("DeepSeek 返回格式异常")
    reply = str((result["choices"][0].get("message") or {}).get("content") or "").strip()
    if not reply:
        raise ValueError("DeepSeek 未返回答案")
    sources = "、".join(
        str(fact["project_id"]) + (
            "（资料基准 " + str((fact.get("source_status") or {}).get("freshness_reference_date"))[:10] + "）"
            if (fact.get("source_status") or {}).get("freshness_reference_date") else ""
        ) for fact in facts
    )
    source_kind = "项目简报与项目认知" if explicitly_selected else "项目简报"
    return _mobile_reply(reply) + "\n依据：本机研发平台" + source_kind + " " + sources[:280]


def status_command() -> str:
    try:
        central = _json_request(f"{CENTRAL}/health")
        central_status = "正常" if isinstance(central, dict) and central.get("status") == "ok" else "异常"
    except (OSError, urllib.error.URLError, ValueError):
        central_status = "未连接"
    try:
        reader_status = "已连接" if TraceMemoReader(TOKEN_FILE).is_ready() else "未就绪"
    except (OSError, urllib.error.URLError, ValueError, TraceMemoError):
        reader_status = "未连接"
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        sender_status = "已连接" if bot_recipient(token) else "未连接"
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        sender_status = "未连接"
    return (f"本机研发平台：{central_status}\n本地聊天库：{reader_status}"
            f"（不代表 Mac 微信已登录）\n测试私聊回复：{sender_status}")


def execute(command: str) -> str:
    if command.startswith("/项目"):
        return project_command(command)
    if command.startswith("/搜索 "):
        return global_search_command(command)
    if command.startswith("/问 "):
        return project_question(command)
    if command.startswith("/执行 "):
        return codex_command(command, readonly=False)
    if command == "/状态":
        return status_command()
    if command == "/帮助":
        return ("请在你自己微信的「文件传输助手」发送指令，结果会回到当前测试私聊：\n"
                "/项目 列表\n/项目 缺陷 背景\n/项目 低电压 材料\n"
                "/项目 HY CLAW 进度\n/项目 hy-claw 仓库\n/项目 缺陷 搜索 关键词\n"
                "/搜索 框架\n/问 HY CLAW 现在做到哪了？\n/状态\n/执行 具体任务\n"
                "当前这个 TraceMemo 机器人自身的聊天问答与项目指令入口尚未打通。")
    return "未识别命令。"


def process_pending(conn: sqlite3.Connection, *, sender_ready: bool = False, now: int | None = None) -> int:
    now = now or int(time.time())
    rows = conn.execute("SELECT message_id,created_at,command FROM commands WHERE status='pending' ORDER BY created_at,message_id").fetchall()
    processed = 0
    for row in rows:
        command = str(row["command"])
        if command.startswith("/执行 ") and not sender_ready:
            continue
        if command.startswith("/执行 ") and now - int(row["created_at"]) > 600:
            conn.execute(
                "UPDATE commands SET status='awaiting_send',reply=? WHERE message_id=?",
                ("这条执行指令已超过 10 分钟，为避免延迟误执行，请重新发送。", row["message_id"]),
            )
            conn.commit()
            processed += 1
            continue
        # A process crash during a Codex action must never execute it again.
        claimed = conn.execute(
            "UPDATE commands SET status='running' WHERE message_id=? AND status='pending'",
            (row["message_id"],),
        )
        conn.commit()
        if claimed.rowcount != 1:
            continue
        try:
            reply = execute(command)
            conn.execute("UPDATE commands SET status='awaiting_send',reply=?,error=NULL WHERE message_id=?", (reply, row["message_id"]))
        except Exception as exc:
            conn.execute("UPDATE commands SET status='awaiting_send',reply=?,error=? WHERE message_id=?", ("处理失败，已在本机记录错误。", type(exc).__name__, row["message_id"]))
        conn.commit()
        processed += 1
    return processed


def personal_sender_ready(token: str) -> bool:
    result = _json_request(f"{TRACE_MEMO}/api/v1/wechat-personal/send-capability", token=token)
    return isinstance(result, dict) and bool((result.get("capability") or {}).get("ready")) and bool(((result.get("capability") or {}).get("capabilities") or {}).get("text"))


def bot_recipient(token: str) -> str | None:
    """Use only the owner chat bound after a verified inbound test."""
    if not BOT_RECIPIENT_FILE.is_file():
        return None
    binding = json.loads(BOT_RECIPIENT_FILE.read_text(encoding="utf-8"))
    if not isinstance(binding, dict):
        return None
    user_id = str(binding.get("userId") or "")
    account_id = str(binding.get("accountId") or "")
    if not user_id.endswith("@im.wechat") or not account_id.endswith("@im.bot"):
        return None
    status = _json_request(f"{TRACE_MEMO}/api/v1/agent/status", token=token)
    if not isinstance(status, dict) or status.get("hub") != "online" or status.get("connector") != "online" or status.get("accountId") != account_id:
        return None
    return user_id


def deliver_pending_bot(conn: sqlite3.Connection, token: str, recipient: str) -> int:
    now = int(time.time())
    rows = conn.execute(
        "SELECT message_id,reply FROM commands WHERE status='awaiting_send' "
        "OR (status='bot_failed' AND attempts<3 AND delivered_at<=?) "
        "ORDER BY created_at,message_id",
        (now - 60,),
    ).fetchall()
    sent = 0
    for row in rows:
        claimed = conn.execute(
            "UPDATE commands SET status='bot_requested',delivered_at=?,attempts=attempts+1 "
            "WHERE message_id=? AND (status='awaiting_send' OR "
            "(status='bot_failed' AND attempts<3 AND delivered_at<=?))",
            (now, row["message_id"], now - 60),
        )
        conn.commit()
        if claimed.rowcount != 1:
            continue
        try:
            result = _json_request(
                f"{TRACE_MEMO}/api/v1/agent/send",
                token=token,
                body={"to": recipient, "text": PREFIX + "\n" + str(row["reply"] or "")[:1800]},
            )
        except urllib.error.HTTPError as exc:
            if not 400 <= exc.code < 500:
                raise  # Server/network failure may have sent the message; do not retry blindly.
            conn.execute(
                "UPDATE commands SET status='bot_failed',error=? WHERE message_id=?",
                (f"agent_hub_http_{exc.code}", row["message_id"]),
            )
            conn.commit()
            break
        if not isinstance(result, dict) or result.get("success") is not True or result.get("status") != "sent":
            conn.execute(
                "UPDATE commands SET status='bot_failed',error='agent_hub_rejected' WHERE message_id=?",
                (row["message_id"],),
            )
            conn.commit()
            break
        conn.execute("UPDATE commands SET status='sent_bot',delivered_at=? WHERE message_id=?", (int(time.time()), row["message_id"]))
        conn.commit()
        sent += 1
    return sent


def deliver_pending(conn: sqlite3.Connection, token: str) -> int:
    rows = conn.execute("SELECT message_id,reply FROM commands WHERE status='awaiting_send' ORDER BY created_at,message_id").fetchall()
    if not rows or not personal_sender_ready(token):
        return 0
    sent = 0
    for row in rows:
        message = PREFIX + "\n" + str(row["reply"] or "")[:1800]
        requested_at = int(time.time())
        claimed = conn.execute(
            "UPDATE commands SET status='send_requested',delivered_at=? "
            "WHERE message_id=? AND status='awaiting_send'",
            (requested_at, row["message_id"]),
        )
        conn.commit()
        if claimed.rowcount != 1:
            continue
        response = _json_request(
            f"{ONEBOT}/send_private_msg",
            body={"user_id": TALKER, "message": [{"type": "text", "data": {"text": message}}]},
        )
        if not isinstance(response, dict) or response.get("status") != "ok":
            conn.execute(
                "UPDATE commands SET status='send_failed',error='onebot_rejected' WHERE message_id=?",
                (row["message_id"],),
            )
            conn.commit()
            break
        # HTTP success only proves OneBot accepted it; chatlog confirms delivery.
        sent += 1
    return sent


def confirm_sent(conn: sqlite3.Connection, reader: TraceMemoReader) -> int:
    rows = conn.execute(
        "SELECT message_id,reply,delivered_at FROM commands WHERE status='send_requested' ORDER BY delivered_at"
    ).fetchall()
    if not rows:
        return 0
    start = min(int(row["delivered_at"] or 0) for row in rows) - 30
    messages = reader._get("/api/v1/chatlog", params={"talker": TALKER, "startTime": str(start)}).get("messages")
    if not isinstance(messages, list):
        return 0
    confirmed = 0
    for row in rows:
        expected = PREFIX + "\n" + str(row["reply"] or "")[:1800]
        match = next((m for m in messages if isinstance(m, dict)
                      and m.get("isSender") is True and m.get("content") == expected
                      and int(m.get("createTime") or 0) >= int(row["delivered_at"] or 0) - 30), None)
        if match:
            conn.execute("UPDATE commands SET status='sent',delivered_at=? WHERE message_id=?", (int(match["createTime"]), row["message_id"]))
            confirmed += 1
    conn.commit()
    return confirmed


def run_once(conn: sqlite3.Connection) -> dict[str, int]:
    reader = TraceMemoReader(TOKEN_FILE)
    added = ingest(conn, reader)
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    try:
        personal_ready = personal_sender_ready(token)
    except (OSError, urllib.error.URLError, ValueError):
        personal_ready = False
    try:
        recipient = bot_recipient(token)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        recipient = None
    for key, value in {"reply_route": "bound_test_private_chat" if recipient else ("filehelper" if personal_ready else "unavailable"),
                       "route_checked_at": str(int(time.time()))}.items():
        conn.execute("INSERT INTO gateway_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
    processed = process_pending(conn, sender_ready=bool(recipient) or personal_ready)
    try:
        if recipient:
            bot_sent = deliver_pending_bot(conn, token, recipient)
            accepted = 0
        else:
            bot_sent = 0
            accepted = deliver_pending(conn, token) if personal_ready else 0
    except (OSError, urllib.error.URLError, ValueError):
        bot_sent = 0
        accepted = 0
    sent = confirm_sent(conn, reader)
    waiting = conn.execute("SELECT COUNT(*) FROM commands WHERE status='awaiting_send'").fetchone()[0]
    return {"received": added, "processed": processed, "bot_sent": bot_sent, "send_accepted": accepted, "sent": sent, "awaiting_sender": waiting}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    conn = open_database()
    if args.status:
        counts = {row["status"]: row["count"] for row in conn.execute("SELECT status,COUNT(*) AS count FROM commands GROUP BY status")}
        print(json.dumps(counts, ensure_ascii=False))
        return 0
    while True:
        try:
            result = run_once(conn)
            for key, value in {"last_cycle_ok": str(int(time.time())), "last_error": ""}.items():
                conn.execute("INSERT INTO gateway_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            conn.commit()
            if args.once:
                print(json.dumps(result, ensure_ascii=False))
                return 0
        except Exception as exc:
            for key, value in {"last_error": type(exc).__name__, "last_error_at": str(int(time.time()))}.items():
                conn.execute("INSERT INTO gateway_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            conn.commit()
            if args.once:
                raise
            print(json.dumps({"error": type(exc).__name__}), flush=True)
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
