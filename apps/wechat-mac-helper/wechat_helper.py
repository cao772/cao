from __future__ import annotations

import json
import hashlib
import os
import platform
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from wechat_core import SeenState, classify_message, event_fingerprint, next_run_at, normalize_config, scheduled_slot
from tracememo_adapter import TraceMemoError, TraceMemoReader, extract_message, resolve_bound_group

STATE_ROOT = Path(
    os.getenv(
        "WECHAT_STATE_ROOT",
        str(Path.home() / "Library" / "Application Support" / "AI Dev Management"),
    )
)
CONFIG_PATH = STATE_ROOT / "wechat-config.json"
SEEN_PATH = STATE_ROOT / "wechat-seen.json"
CURSOR_PATH = STATE_ROOT / "wechat-tracememo-cursors.json"
TRACEMEMO_TOKEN_FILE = Path(os.getenv("TRACEMEMO_TOKEN_FILE", str(STATE_ROOT / "tracememo-api-token")))
TRACEMEMO_API_URL = os.getenv("TRACEMEMO_API_URL", "http://127.0.0.1:6131")
INITIAL_LOOKBACK_DAYS = max(1, min(int(os.getenv("WECHAT_INITIAL_LOOKBACK_DAYS", "30")), 90))
CURSOR_OVERLAP_SECONDS = 24 * 3600
CENTRAL_URL = os.getenv("CENTRAL_URL", "").rstrip("/")
COLLECTOR_TOKEN = os.getenv("COLLECTOR_TOKEN", "")
USER_ID = os.getenv("USER_ID", os.getenv("USER", "developer"))
DEVICE_ID = os.getenv("DEVICE_ID", platform.node() or "mac")
POLL_SECONDS = int(os.getenv("WECHAT_HELPER_POLL_SECONDS", "20"))

app = FastAPI(title="Personal WeChat Project Collector", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8088", "http://localhost:8088"],
    allow_credentials=False,
    allow_methods=["GET", "PUT", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class GroupBinding(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    project_name: str | None = Field(default=None, max_length=500)
    group_name: str = Field(min_length=1, max_length=500)


class WeChatConfigIn(BaseModel):
    enabled: bool = True
    start_time: str = "09:00"
    end_time: str = "20:00"
    interval_minutes: int = Field(default=30, ge=5, le=240)
    bindings: list[GroupBinding] = Field(default_factory=list, max_length=100)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return normalize_config({})
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return normalize_config({})
    return normalize_config(raw)


def save_config(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_config(raw)
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    return normalized


def _run_osascript(script: str, timeout: int = 8) -> tuple[int, str]:
    if platform.system() != "Darwin" or not shutil.which("osascript"):
        return 1, ""
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def probe_wechat() -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"available": False, "reason": "macOS host helper required"}
    try:
        ready = TraceMemoReader(TRACEMEMO_TOKEN_FILE, TRACEMEMO_API_URL).is_ready()
    except TraceMemoError as exc:
        return {"available": False, "reason": str(exc)}
    if not ready:
        return {"available": False, "reason": "TraceMemo 本地数据库尚未连接"}
    return {
        "available": True,
        "reason": None,
        "capture_mode": "tracememo_local_api",
        "note": "仅按项目绑定读取授权群的文本与文件标题；不读取其他聊天或媒体内容。",
    }


def _parse_accessibility_rows(output: str, include_text: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("__"):
            continue
        parts = line.split("\t")
        while len(parts) < 5:
            parts.append("")
        item: dict[str, Any] = {
            "role": parts[0],
            "subrole": parts[1] or None,
            "description": parts[2] or None,
        }
        if include_text:
            item["name"] = parts[3] or None
            item["value"] = parts[4] or None
        items.append(item)
    return items


def accessibility_snapshot(include_text: bool = False, max_items: int = 600) -> dict[str, Any]:
    """Read only the current WeChat front-window Accessibility tree.

    This diagnostic never clicks, focuses, types, scrolls or changes WeChat state.
    Text-bearing fields are excluded by default and must be explicitly requested.
    """
    if platform.system() != "Darwin":
        return {"available": False, "reason": "macOS host helper required", "items": []}

    include_flag = "true" if include_text else "false"
    script = f"""
on cleanField(v)
    try
        set t to v as text
    on error
        set t to ""
    end try
    set AppleScript's text item delimiters to tab
    set pieces to text items of t
    set AppleScript's text item delimiters to " "
    set t to pieces as text
    set AppleScript's text item delimiters to linefeed
    set pieces to text items of t
    set AppleScript's text item delimiters to " "
    set t to pieces as text
    set AppleScript's text item delimiters to return
    set pieces to text items of t
    set AppleScript's text item delimiters to " "
    set t to pieces as text
    set AppleScript's text item delimiters to ""
    return t
end cleanField

tell application "System Events"
    if exists process "WeChat" then
        set p to process "WeChat"
    else if exists process "微信" then
        set p to process "微信"
    else
        return "__NO_PROCESS__"
    end if
    tell p
        if (count of windows) is 0 then return "__NO_WINDOW__"
        set allItems to entire contents of front window
        set rows to {{}}
        set itemCount to 0
        repeat with uiItem in allItems
            set itemCount to itemCount + 1
            if itemCount > {int(max_items)} then exit repeat
            set roleText to ""
            set subroleText to ""
            set descText to ""
            set nameText to ""
            set valueText to ""
            try
                set roleText to my cleanField(role of uiItem)
            end try
            try
                set subroleText to my cleanField(subrole of uiItem)
            end try
            try
                set descText to my cleanField(description of uiItem)
            end try
            if {include_flag} then
                try
                    set nameText to my cleanField(name of uiItem)
                end try
                try
                    set valueText to my cleanField(value of uiItem)
                end try
            end if
            set end of rows to roleText & tab & subroleText & tab & descText & tab & nameText & tab & valueText
        end repeat
        set AppleScript's text item delimiters to linefeed
        set resultText to rows as text
        set AppleScript's text item delimiters to ""
        return resultText
    end tell
end tell
"""
    code, output = _run_osascript(script, timeout=15)
    if code != 0:
        return {
            "available": False,
            "reason": output or "无法读取微信 Accessibility 控件树",
            "items": [],
        }
    if output == "__NO_PROCESS__":
        return {"available": False, "reason": "个人微信客户端未运行", "items": []}
    if output == "__NO_WINDOW__":
        return {"available": False, "reason": "微信没有可读取的前台窗口", "items": []}

    items = _parse_accessibility_rows(output, include_text)
    return {
        "available": True,
        "read_only": True,
        "include_text": include_text,
        "item_count": len(items),
        "truncated": len(items) >= max_items,
        "items": items,
        "note": "这是手动校准快照；定时采集器不会自动调用该接口。",
    }


def upload_event(event: dict[str, Any]) -> bool:
    if not CENTRAL_URL:
        return False
    body = json.dumps(event, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "wechat-mac-helper/0.1"}
    if COLLECTOR_TOKEN:
        headers["X-Collector-Token"] = COLLECTOR_TOKEN
    request = urllib.request.Request(
        f"{CENTRAL_URL}/api/v1/conversation-events",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def normalize_message(binding: dict[str, str], raw: dict[str, Any]) -> dict[str, Any] | None:
    text = " ".join(str(raw.get("text") or "").split())
    if not text:
        return None
    observed_at = str(raw.get("observed_at") or datetime.now().astimezone().isoformat())
    sender = str(raw.get("sender") or "").strip() or None
    message_type = str(raw.get("message_type") or "text")
    source_fingerprint = str(raw.get("source_fingerprint") or "")
    if len(source_fingerprint) == 64 and all(c in "0123456789abcdef" for c in source_fingerprint):
        fingerprint = hashlib.sha256(f"{binding['project_id']}:{source_fingerprint}".encode()).hexdigest()
    else:
        fingerprint = event_fingerprint(
            project_id=binding["project_id"],
            group_name=binding["group_name"],
            sender=sender,
            text=text,
            observed_at=observed_at,
            message_type=message_type,
        )
    return {
        "schema_version": 1,
        "event_fingerprint": fingerprint,
        "project_id": binding["project_id"],
        "project_name": binding.get("project_name") or binding["project_id"],
        "source": "wechat_personal",
        "conversation_name": binding["group_name"],
        "sender": sender,
        "message_type": message_type,
        "text": text,
        "observed_at": observed_at,
        "user_id": USER_ID,
        "device_id": DEVICE_ID,
        "categories": classify_message(text),
        "metadata": {"collector": "wechat-mac-helper", "adapter": "tracememo-local-api"},
    }


def _load_cursors() -> dict[str, int]:
    try:
        data = json.loads(CURSOR_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): int(value) for key, value in data.items() if str(value).isdigit()}


def _save_cursors(cursors: dict[str, int]) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = CURSOR_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cursors, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CURSOR_PATH)


_collection_lock = threading.Lock()


def collect_authorized_groups(config: dict[str, Any]) -> dict[str, Any]:
    # The scheduler and manual scan share cursor/seen files in this process.
    with _collection_lock:
        return _collect_authorized_groups(config)


def _collect_authorized_groups(config: dict[str, Any]) -> dict[str, Any]:
    status = probe_wechat()
    result = {
        "attempted": len(config.get("bindings") or []),
        "captured": 0,
        "uploaded": 0,
        "duplicates": 0,
        "failed": 0,
        "wechat": status,
        "requires_calibration": False,
        "groups": [],
    }
    if not config.get("enabled", True):
        result["disabled"] = True
        return result
    if not status.get("available"):
        return result
    reader = TraceMemoReader(TRACEMEMO_TOKEN_FILE, TRACEMEMO_API_URL)
    try:
        chatrooms = reader.chatrooms()
    except TraceMemoError as exc:
        result["error"] = str(exc)
        result["failed"] = result["attempted"]
        return result
    cursors = _load_cursors()
    changed = False
    initial_start = int(time.time()) - INITIAL_LOOKBACK_DAYS * 86400
    for binding in config.get("bindings") or []:
        group_result: dict[str, Any] = {"project_id": binding["project_id"], "group_name": binding["group_name"]}
        result["groups"].append(group_result)
        try:
            room = resolve_bound_group(binding, chatrooms)
            talker = str(room["m_nsUsrName"])
            cursor_key = f"{binding['project_id']}:{talker}"
            start = max(initial_start, cursors.get(cursor_key, initial_start) - CURSOR_OVERLAP_SECONDS)
            messages = reader.messages(talker, start)
            extracted = [item for raw in messages if (item := extract_message(raw, talker)) is not None]
            extracted.sort(key=lambda item: item["create_time"])
            counts = ingest_captured_messages(binding, extracted)
            group_result.update(counts)
            for key in ("captured", "uploaded", "duplicates", "failed"):
                result[key] += counts[key]
            if counts["failed"] == 0 and messages:
                newest = max(int(raw.get("createTime") or 0) for raw in messages)
                if newest > cursors.get(cursor_key, 0):
                    cursors[cursor_key] = newest
                    changed = True
        except (TraceMemoError, ValueError, TypeError) as exc:
            group_result["error"] = str(exc)
            result["failed"] += 1
    if changed:
        _save_cursors(cursors)
    return result


def ingest_captured_messages(binding: dict[str, str], messages: list[dict[str, Any]]) -> dict[str, int]:
    seen_state = SeenState(SEEN_PATH)
    seen = seen_state.load()
    captured = uploaded = duplicates = failed = 0
    for raw in messages:
        event = normalize_message(binding, raw)
        if event is None:
            continue
        captured += 1
        fingerprint = event["event_fingerprint"]
        if fingerprint in seen:
            duplicates += 1
            continue
        if upload_event(event):
            uploaded += 1
            seen.add(fingerprint)
        else:
            failed += 1
    seen_state.save(seen)
    return {"captured": captured, "uploaded": uploaded, "duplicates": duplicates, "failed": failed}


_last_slot: str | None = None


def scheduler_tick(now: datetime | None = None) -> dict[str, Any]:
    global _last_slot
    now = now or datetime.now().astimezone()
    config = load_config()
    if not config.get("enabled"):
        return {"ran": False, "reason": "disabled"}
    slot = scheduled_slot(now, config["start_time"], config["end_time"], config["interval_minutes"])
    if slot is None:
        return {
            "ran": False,
            "reason": "outside_slot",
            "next_run_at": next_run_at(
                now, config["start_time"], config["end_time"], config["interval_minutes"]
            ).isoformat(),
        }
    slot_key = slot.isoformat()
    if _last_slot == slot_key:
        return {"ran": False, "reason": "already_ran", "slot": slot_key}
    _last_slot = slot_key
    result = collect_authorized_groups(config)
    return {"ran": True, "slot": slot_key, **result}


def _scheduler_loop() -> None:
    while True:
        try:
            scheduler_tick()
        except Exception as exc:
            print(json.dumps({"level": "error", "service": "wechat-helper", "error": str(exc)}, ensure_ascii=False))
        time.sleep(max(POLL_SECONDS, 5))


@app.on_event("startup")
def startup() -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_scheduler_loop, name="wechat-scheduler", daemon=True).start()


@app.get("/health")
def health() -> dict[str, Any]:
    config = load_config()
    now = datetime.now().astimezone()
    return {
        "status": "ok",
        "service": "wechat-mac-helper",
        "wechat": probe_wechat(),
        "schedule": {
            "start_time": config["start_time"],
            "end_time": config["end_time"],
            "interval_minutes": config["interval_minutes"],
            "next_run_at": next_run_at(
                now, config["start_time"], config["end_time"], config["interval_minutes"]
            ).isoformat(),
        },
    }


@app.get("/api/v1/wechat/config")
def get_config() -> dict[str, Any]:
    return load_config()


@app.put("/api/v1/wechat/config")
def put_config(payload: WeChatConfigIn) -> dict[str, Any]:
    try:
        return save_config(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc




@app.get("/api/v1/wechat/accessibility-snapshot")
def get_accessibility_snapshot(
    include_text: bool = Query(default=False),
    max_items: int = Query(default=600, ge=20, le=1500),
) -> dict[str, Any]:
    return accessibility_snapshot(include_text=include_text, max_items=max_items)


@app.post("/api/v1/wechat/scan")
def scan_now() -> dict[str, Any]:
    return collect_authorized_groups(load_config())
