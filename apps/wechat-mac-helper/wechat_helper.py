from __future__ import annotations

import json
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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from wechat_core import SeenState, classify_message, event_fingerprint, next_run_at, normalize_config, scheduled_slot

STATE_ROOT = Path(
    os.getenv(
        "WECHAT_STATE_ROOT",
        str(Path.home() / "Library" / "Application Support" / "AI Dev Management"),
    )
)
CONFIG_PATH = STATE_ROOT / "wechat-config.json"
SEEN_PATH = STATE_ROOT / "wechat-seen.json"
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
    code, output = _run_osascript(
        'tell application "System Events" to return (exists process "WeChat") or (exists process "微信")'
    )
    if code != 0:
        return {
            "available": False,
            "reason": "无法访问 macOS 辅助功能；请给宿主机微信助手授予“辅助功能”权限",
        }
    if output.lower() != "true":
        return {"available": False, "reason": "个人微信客户端未运行"}
    return {
        "available": True,
        "reason": None,
        "capture_mode": "safe_adapter_required",
        "note": "已完成授权、调度、去重和上传闭环；群聊控件树需在目标 Mac 上校准后启用只读自动采集。",
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
        "metadata": {"collector": "wechat-mac-helper", "collector_version": "0.1.0"},
    }


def collect_authorized_groups(config: dict[str, Any]) -> dict[str, Any]:
    status = probe_wechat()
    return {
        "attempted": len(config.get("bindings") or []),
        "captured": 0,
        "uploaded": 0,
        "wechat": status,
        "requires_calibration": bool((config.get("bindings") or []) and status.get("available")),
    }


def ingest_captured_messages(binding: dict[str, str], messages: list[dict[str, Any]]) -> dict[str, int]:
    seen_state = SeenState(SEEN_PATH)
    seen = seen_state.load()
    captured = uploaded = duplicates = 0
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
    seen_state.save(seen)
    return {"captured": captured, "uploaded": uploaded, "duplicates": duplicates}


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


@app.post("/api/v1/wechat/scan")
def scan_now() -> dict[str, Any]:
    return collect_authorized_groups(load_config())
