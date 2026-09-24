"""Read only explicitly bound group conversations from TraceMemo's loopback API."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


class TraceMemoError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_local_opener = urllib.request.build_opener(_NoRedirect)


def canonical_group_name(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def resolve_bound_group(binding: dict[str, str], chatrooms: list[dict[str, Any]]) -> dict[str, Any]:
    """Require one exact (apart from spacing/case) group match; never guess."""
    wanted = canonical_group_name(binding["group_name"])
    matches = [
        room
        for room in chatrooms
        if room.get("type") == "group"
        and str(room.get("m_nsUsrName") or "").endswith("@chatroom")
        and canonical_group_name(str(room.get("m_nsNickName") or "")) == wanted
    ]
    if len(matches) != 1:
        raise TraceMemoError(f"授权群匹配数量异常：{binding['group_name']}（{len(matches)}）")
    return matches[0]


class TraceMemoReader:
    def __init__(self, token_file: Path, base_url: str = "http://127.0.0.1:6131") -> None:
        url = urllib.parse.urlsplit(base_url)
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost")
                or url.username or url.password or url.path.rstrip("/") or url.query or url.fragment):
            raise TraceMemoError("TraceMemo API 只能使用本机 HTTP 地址")
        self.base_url = base_url.rstrip("/")
        self.token_file = token_file

    def _get(self, route: str, *, params: dict[str, str] | None = None, authenticated: bool = True) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if authenticated:
            try:
                token = self.token_file.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise TraceMemoError("TraceMemo API Token 文件不可读") from exc
            if not token:
                raise TraceMemoError("TraceMemo API Token 为空")
            headers["Authorization"] = f"Bearer {token}"
        query = urllib.parse.urlencode(params or {})
        url = self.base_url + route + (f"?{query}" if query else "")
        request = urllib.request.Request(url, headers=headers)
        try:
            with _local_opener.open(request, timeout=20) as response:
                raw = response.read(20_000_001)
        except urllib.error.HTTPError as exc:
            raise TraceMemoError(f"TraceMemo API 返回 HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TraceMemoError("TraceMemo 本地 API 不可访问") from exc
        if len(raw) > 20_000_000:
            raise TraceMemoError("TraceMemo 返回数据过大，已停止本次采集")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise TraceMemoError("TraceMemo 返回无效 JSON") from exc
        if not isinstance(result, dict):
            raise TraceMemoError("TraceMemo 返回格式异常")
        return result

    def is_ready(self) -> bool:
        health = self._get("/api/v1/health", authenticated=False)
        if not health.get("ready"):
            return False
        # A public health check does not prove that the saved token still works.
        self._get("/api/v1/chatroom", params={"keyword": "__aidev_auth_probe__"})
        return True

    def chatrooms(self) -> list[dict[str, Any]]:
        value = self._get("/api/v1/chatroom").get("chatrooms")
        if not isinstance(value, list):
            raise TraceMemoError("TraceMemo 群聊列表格式异常")
        return [item for item in value if isinstance(item, dict)]

    def messages(self, talker: str, start_epoch: int) -> list[dict[str, Any]]:
        if not talker.endswith("@chatroom"):
            raise TraceMemoError("拒绝读取非群聊会话")
        value = self._get(
            "/api/v1/chatlog",
            params={"talker": talker, "startTime": str(start_epoch)},
        ).get("messages")
        if not isinstance(value, list):
            raise TraceMemoError("TraceMemo 聊天记录格式异常")
        return [item for item in value if isinstance(item, dict)]


def extract_message(raw: dict[str, Any], talker: str) -> dict[str, Any] | None:
    """Extract text and file titles; never send images, media URLs, or raw metadata."""
    kind = str(raw.get("type") or "")
    data = raw.get("contentData") if isinstance(raw.get("contentData"), dict) else {}
    if kind == "普通文本":
        text = str(raw.get("content") or "").strip()
        message_type = "text"
    elif kind == "引用消息":
        text = str(data.get("content") or data.get("title") or "").strip()
        quoted = str(data.get("quotedContent") or "").strip()
        if text and quoted:
            text = f"{text}\n引用：{quoted[:500]}"
        message_type = "quote"
    elif kind == "文件":
        title = str(data.get("title") or "").strip()
        text = f"分享文件：{title}" if title else ""
        message_type = "file"
    else:
        return None
    if not text:
        return None
    try:
        created = int(raw["createTime"])
        observed_at = datetime.fromtimestamp(created).astimezone().isoformat()
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None
    source_id = str(raw.get("serverId") or "").strip()
    if not source_id or source_id == "0":
        fallback = hashlib.sha256(
            f"{raw.get('name') or raw.get('from') or ''}:{text}".encode("utf-8")
        ).hexdigest()
        source_id = f"{raw.get('sessionId') or talker}:{raw.get('localId') or ''}:{created}:{fallback}"
    identity = f"{talker}:{source_id}:{message_type}"
    return {
        "text": text[:20_000],
        "sender": str(raw.get("name") or raw.get("from") or "").strip() or None,
        "message_type": message_type,
        "observed_at": observed_at,
        "source_fingerprint": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "create_time": created,
    }
