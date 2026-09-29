"""Read gateway operational metadata without exposing messages or recipients."""
from pathlib import Path
import sqlite3
import time


def gateway_diagnostics(path: Path, now: int | None = None) -> dict:
    now = int(time.time()) if now is None else now
    result = {"state": "not_initialized", "input": "filehelper", "reply_route": "unknown",
              "counts": {}, "latest_command_at": None, "last_cycle_ok": None,
              "last_error": None, "route_checked_at": None}
    if not path.is_file():
        return result
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as conn:
            meta = dict(conn.execute("SELECT key,value FROM gateway_meta"))
            counts = dict(conn.execute("SELECT status,COUNT(*) FROM commands GROUP BY status"))
            latest = conn.execute("SELECT MAX(created_at) FROM commands").fetchone()[0]
        last_ok = int(meta.get("last_cycle_ok") or 0)
        route_at = int(meta.get("route_checked_at") or 0)
        result.update(state="recently_polled" if 0 <= now-last_ok <= 90 else "stale",
                      counts=counts, latest_command_at=latest, last_cycle_ok=last_ok or None,
                      route_checked_at=route_at or None)
        if 0 <= now-route_at <= 90:
            route = meta.get("reply_route")
            if route in {"bound_test_private_chat", "filehelper", "unavailable"}:
                result["reply_route"] = route
        if meta.get("last_error"):
            result["state"] = "error"
            result["last_error"] = "最近轮询失败，请检查本机网关日志"
    except (sqlite3.Error, ValueError, OSError):
        result["state"] = "unavailable"
        result["last_error"] = "无法读取网关运行状态"
    return result
