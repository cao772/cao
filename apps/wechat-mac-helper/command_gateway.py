"""Receive owner-only WeChat commands through TraceMemo's local database reader.

The only input conversation is the current account's File Transfer Assistant.
Replies are held locally until the *personal* WeChat sender is ready; the
separate TraceMemo robot account is never used as a substitute.
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
import urllib.request
from pathlib import Path
from typing import Any

from tracememo_adapter import TraceMemoReader

STATE_ROOT = Path.home() / "Library/Application Support/AI Dev Management"
TOKEN_FILE = STATE_ROOT / "tracememo-api-token"
DATABASE = STATE_ROOT / "wechat-command-gateway.sqlite3"
DEEPSEEK_KEY_FILE = STATE_ROOT / "deepseek-api-key"
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
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS commands_status_idx ON commands(status, created_at);
        CREATE TABLE IF NOT EXISTS gateway_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
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
        and text.startswith(("/项目", "/问 ", "/执行 ", "/状态"))
        and len(text) <= 2000
    )


def ingest(conn: sqlite3.Connection, reader: TraceMemoReader, now: int | None = None) -> int:
    now = now or int(time.time())
    checkpoint = conn.execute("SELECT value FROM gateway_meta WHERE key='last_poll'").fetchone()
    start = int(checkpoint[0]) - 120 if checkpoint else now - 24 * 3600
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
            values.append(item.lstrip("- ").strip())
        elif isinstance(item, dict):
            values.append(str(item.get("title") or item.get("summary") or item.get("text") or "").strip())
    return [f"{label}：" + "；".join(x for x in values if x)] if any(values) else []


def project_command(command: str) -> str:
    parts = command.split(maxsplit=2)
    projects = _projects()
    if len(parts) == 1 or parts[1] in {"列表", "项目"}:
        return "已纳管项目：\n" + "\n".join(
            f"• {item.get('project_name') or item.get('project_id')} ({item.get('project_id')})"
            for item in projects
        )
    project_id = _project_id(parts[1], projects)
    name = next((str(p.get("project_name") or project_id) for p in projects if p.get("project_id") == project_id), project_id)
    action = parts[2].strip() if len(parts) > 2 else "概览"
    if action.startswith("搜索 "):
        from urllib.parse import urlencode

        result = _json_request(f"{CENTRAL}/api/v1/projects/{project_id}/search?" + urlencode({"q": action[3:].strip(), "limit": 5}))
        if not isinstance(result, dict):
            raise ValueError("搜索结果格式错误")
        return f"{name}：找到 {result.get('count', 0)} 条相关资料或沟通记录。请在研发平台打开项目搜索查看来源。"
    if action not in {"概览", "进度", "问题", "下一步", "任务"}:
        return "可用命令：/项目 列表；/项目 低电压；/项目 缺陷 问题；/项目 hy-claw 搜索 关键词"
    result = _json_request(f"{CENTRAL}/api/v1/projects/{project_id}/brief")
    if not isinstance(result, dict):
        raise ValueError("项目简报格式错误")
    lines = [name, f"阶段：{result.get('current_stage') or '待确认'}"]
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
    return "\n".join(lines)


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
            **{key: brief.get(key) for key in ("current_stage", "completed", "in_progress", "issues", "next_steps", "latest_metrics", "summary")},
        })
    key = DEEPSEEK_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError("DeepSeek API Key 未配置")
    payload = {
        "model": "deepseek-flash",
        "messages": [
            {"role": "system", "content": "你是用户的研发项目助手。只根据附带的本机项目事实回答；区分已完成、进行中、问题和推断。资料没有的信息明确说不知道。用简洁中文回答，不泄露密钥。"},
            {"role": "user", "content": "问题：" + question + "\n\n本机研发平台事实：" + json.dumps(facts, ensure_ascii=False)[:24000]},
        ],
        "max_tokens": 900,
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    result = _json_request("https://api.deepseek.com/chat/completions", token=key, body=payload)
    if not isinstance(result, dict) or not isinstance(result.get("choices"), list) or not result["choices"]:
        raise ValueError("DeepSeek 返回格式异常")
    reply = str((result["choices"][0].get("message") or {}).get("content") or "").strip()
    if not reply:
        raise ValueError("DeepSeek 未返回答案")
    return reply[:1800]


def execute(command: str) -> str:
    if command.startswith("/项目"):
        return project_command(command)
    if command.startswith("/问 "):
        return project_question(command)
    if command.startswith("/执行 "):
        return codex_command(command, readonly=False)
    if command == "/状态":
        return "项目助手已收到你的微信指令；项目数据来自本机研发平台。"
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
        ready = personal_sender_ready(token)
    except (OSError, urllib.error.URLError, ValueError):
        ready = False
    processed = process_pending(conn, sender_ready=ready)
    try:
        accepted = deliver_pending(conn, token)
    except (OSError, urllib.error.URLError, ValueError):
        accepted = 0
    sent = confirm_sent(conn, reader)
    waiting = conn.execute("SELECT COUNT(*) FROM commands WHERE status='awaiting_send'").fetchone()[0]
    return {"received": added, "processed": processed, "send_accepted": accepted, "sent": sent, "awaiting_personal_sender": waiting}


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
            if args.once:
                print(json.dumps(result, ensure_ascii=False))
                return 0
        except Exception as exc:
            if args.once:
                raise
            print(json.dumps({"error": type(exc).__name__}), flush=True)
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
