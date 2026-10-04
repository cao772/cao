"""Read published AIHOT content; never send project data or invoke a model."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter
import main as main_module

BASE_URL = "https://aihot.news"
PATHS = {"hot": "/api/v1/hot-topics", "selected": "/api/v1/items?mode=selected&window=7d&limit=80", "daily": "/api/v1/dailies/latest"}
router = APIRouter(prefix="/api/v1", tags=["industry-news"])


def safe_link(value):
    if not isinstance(value, str) or len(value) > 3000:
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def text(value, limit=2000):
    return str(value)[:limit] if isinstance(value, (str, int, float)) else ""


def normalize(payload, view):
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("unsupported upstream schema")
    report = payload.get("report", {}) if view == "daily" else {}
    if view == "daily":
        if not isinstance(report, dict) or not isinstance(report.get("sections"), list):
            raise ValueError("invalid report")
        rows = []
        for section in report["sections"]:
            if isinstance(section, dict):
                rows.extend((item, text(section.get("label"))) for item in section.get("items", []) if isinstance(item, dict))
        rows.extend((item, "快讯") for item in report.get("flashes", []) if isinstance(item, dict))
    else:
        if not isinstance(payload.get("items"), list):
            raise ValueError("invalid items")
        rows = [(item, "") for item in payload["items"] if isinstance(item, dict)]
    items, seen = [], set()
    for item, section in rows[:100]:
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        original = safe_link(links.get("original"))
        attribution = safe_link(links.get("aihot"))
        identity = original or attribution
        if not identity or identity in seen or not item.get("title"):
            continue
        seen.add(identity)
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        items.append({"id": text(item.get("id") or identity, 3000), "title": text(item.get("title"), 500),
                      "summary": text(item.get("summary")), "source": text(source.get("name"), 200),
                      "url": original, "attribution_url": attribution, "story_url": safe_link(links.get("story")),
                      "published_at": text(item.get("publishedAt"), 80), "discovered_at": text(item.get("discoveredAt"), 80),
                      "latest_at": text(item.get("latestAt"), 80), "category": text(item.get("category"), 100),
                      "section": section, "source_count": item.get("sourceCount") if type(item.get("sourceCount")) is int else None})
    page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
    return {"items": items, "has_more": bool(page.get("hasMore")), "report_date": text(report.get("date"), 40),
            "report_generated_at": text(report.get("generatedAt"), 80),
            "report_url": safe_link((report.get("links") or {}).get("aihot")), "provider": "AIHOT", "provider_url": BASE_URL}


def fetch_public(view):
    # Fixed paths only. No user queries, project identifiers, tokens or private material.
    with httpx.Client(timeout=8, follow_redirects=False, headers={"User-Agent": "cao-project-intelligence/1.0"}) as client:
        with client.stream("GET", BASE_URL + PATHS[view]) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise ValueError("upstream response too large")
            return json.loads(body)


class NewsReader:
    def __init__(self, directory, fetch=fetch_public, clock=time.time):
        self.directory = Path(directory)
        self.fetch, self.clock = fetch, clock
        self.lock = threading.Lock()
        self.cache, self.retry_at = {}, {}

    def read(self, view):
        with self.lock:
            now = self.clock()
            entry = self.cache.get(view)
            if entry is None:
                try:
                    entry = json.loads((self.directory / f"{view}.json").read_text())
                    if not isinstance(entry.get("data", {}).get("items"), list) or not isinstance(entry.get("fetched"), (int, float)):
                        entry = None
                except (OSError, ValueError, TypeError, AttributeError):
                    entry = None
            if entry and 0 <= now - entry["fetched"] < 300:
                self.cache[view] = entry
                return self._result(entry, False)
            if now >= self.retry_at.get(view, 0):
                try:
                    data = normalize(self.fetch(view), view)
                    entry = {"fetched": now, "data": data}
                    self.cache[view] = entry
                    self.retry_at.pop(view, None)
                    try:
                        self.directory.mkdir(parents=True, exist_ok=True)
                        target = self.directory / f"{view}.json"
                        temporary = target.with_suffix(".tmp")
                        temporary.write_text(json.dumps(entry, ensure_ascii=False))
                        temporary.replace(target)
                    except OSError:
                        pass  # Memory cache still works when the data volume is read-only.
                    return self._result(entry, False)
                except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
                    self.retry_at[view] = now + 60
            if entry:
                self.cache[view] = entry
                return self._result(entry, True)
            return {"items": [], "status": "unavailable", "fetched_at": None, "provider": "AIHOT", "provider_url": BASE_URL,
                    "message": "资讯来源暂不可用，稍后重试；这不代表没有资讯。"}

    def _result(self, entry, stale):
        return {**entry["data"], "status": "stale" if stale else "ready",
                "fetched_at": datetime.fromtimestamp(entry["fetched"], timezone.utc).isoformat()}


_reader = NewsReader(main_module.DB_PATH.parent / "industry-news")


@router.get("/industry-news")
def industry_news(view: Literal["hot", "selected", "daily"] = "hot"):
    return _reader.read(view)
