from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

CONFIG_PATH = Path(os.getenv("GITLAB_PROJECTS_CONFIG", "/config/gitlab-projects.yaml"))
STATE_PATH = Path(os.getenv("REMOTE_COLLECTOR_STATE", "/state/gitlab-state.json"))
GITLAB_BASE_URL = os.getenv("GITLAB_BASE_URL", "http://git.hyetec.com").rstrip("/")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
CENTRAL_URL = os.getenv("CENTRAL_URL", "").rstrip("/")
COLLECTOR_TOKEN = os.getenv("COLLECTOR_TOKEN", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
INITIAL_LOOKBACK_HOURS = int(os.getenv("INITIAL_LOOKBACK_HOURS", "24"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
MAX_PAGES = int(os.getenv("GITLAB_MAX_PAGES", "20"))
COLLECTOR_VERSION = "0.4.1"
TASK_ID_RE = re.compile(r"\b([A-Z][A-Z0-9_]{1,20}-\d+)\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _central_get(path: str) -> dict[str, Any] | None:
    if not CENTRAL_URL or not COLLECTOR_TOKEN:
        return None
    request = urllib.request.Request(
        f"{CENTRAL_URL}{path}",
        headers={
            "Accept": "application/json",
            "X-Collector-Token": COLLECTOR_TOKEN,
            "User-Agent": f"ai-dev-management-gitlab-collector/{COLLECTOR_VERSION}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        print(json.dumps({"level": "warning", "stage": "central_config", "path": path, "error": type(exc).__name__}, ensure_ascii=False))
        return None
    return payload if isinstance(payload, dict) else None


def _central_runtime_config() -> dict[str, Any] | None:
    """Read decrypted runtime configuration from Central without exposing it to the browser."""
    global GITLAB_BASE_URL, GITLAB_TOKEN
    data = _central_get("/api/v1/internal/gitlab/runtime-config")
    if not data or not data.get("configured") or not data.get("projects"):
        return None
    base_url = str(data.get("gitlab_base_url") or "").strip().rstrip("/")
    token = str(data.get("gitlab_token") or "").strip()
    if not base_url or not token:
        return None

    settings_payload = _central_get("/api/v1/internal/projects/runtime-settings") or {}
    project_settings = settings_payload.get("projects") or {}
    projects = []
    for project in data.get("projects") or []:
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("project_id") or "")
        setting = project_settings.get(project_id) if isinstance(project_settings, dict) else None
        if isinstance(setting, dict) and setting.get("enabled") is False:
            continue
        projects.append(project)

    # Central configuration remains authoritative even when every managed project is
    # disabled. Returning an empty registry prevents the collector from falling back to
    # the bootstrap YAML and accidentally resuming collection for disabled projects.
    GITLAB_BASE_URL = base_url
    GITLAB_TOKEN = token
    return {"version": 1, "projects": projects}


def load_config() -> dict[str, Any]:
    runtime = _central_runtime_config()
    if runtime is not None:
        return runtime
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if data.get("version") != 1:
        raise ValueError("unsupported GitLab registry version")
    return data


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"version": 1, "repositories": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "repositories": {}}
    if not isinstance(data, dict):
        return {"version": 1, "repositories": {}}
    data.setdefault("version", 1)
    data.setdefault("repositories", {})
    return data


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def gitlab_get(path: str, params: dict[str, Any] | None = None) -> Any:
    if not GITLAB_TOKEN:
        raise RuntimeError("GITLAB_TOKEN is required")
    query = urllib.parse.urlencode({key: value for key, value in (params or {}).items() if value is not None})
    url = f"{GITLAB_BASE_URL}/api/v4/{path.lstrip('/')}"
    if query:
        url += "?" + query
    request = urllib.request.Request(
        url,
        headers={
            "PRIVATE-TOKEN": GITLAB_TOKEN,
            "Accept": "application/json",
            "User-Agent": f"ai-dev-management-gitlab-collector/{COLLECTOR_VERSION}",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def gitlab_get_all(path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    base = dict(params or {})
    per_page = min(int(base.get("per_page") or 100), 100)
    base["per_page"] = per_page
    result: list[dict[str, Any]] = []
    for page in range(1, max(MAX_PAGES, 1) + 1):
        rows = gitlab_get(path, {**base, "page": page})
        if not isinstance(rows, list) or not rows:
            break
        result.extend(item for item in rows if isinstance(item, dict))
        if len(rows) < per_page:
            break
    return result


def central_post(event: dict[str, Any]) -> bool:
    if not CENTRAL_URL:
        print(json.dumps(event, ensure_ascii=False))
        return True
    body = json.dumps(event, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"ai-dev-management-gitlab-collector/{COLLECTOR_VERSION}",
    }
    if COLLECTOR_TOKEN:
        headers["X-Collector-Token"] = COLLECTOR_TOKEN
    request = urllib.request.Request(
        f"{CENTRAL_URL}/api/v1/remote-events",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError) as exc:
        print(json.dumps({"level": "error", "stage": "central_post", "error": str(exc)}, ensure_ascii=False))
        return False


def _task_id(*values: Any) -> str | None:
    for value in values:
        match = TASK_ID_RE.search(str(value or ""))
        if match:
            return match.group(1)
    return None


def _event_id(repository_id: str, kind: str, identity: str) -> str:
    raw = f"gitlab:{repository_id}:{kind}:{identity}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]
    return f"gitlab-{digest}"


def _base_event(project: dict[str, Any], repository: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": project["project_id"],
        "provider": "gitlab",
        "repository_id": repository["id"],
        "repository_url": repository.get("url"),
    }


def normalize_commit(project: dict[str, Any], repository: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or item.get("message") or "").strip()
    sha = str(item.get("id") or item.get("short_id") or "").strip()
    observed = item.get("committed_date") or item.get("created_at") or utc_now()
    base = _base_event(project, repository)
    base.update({
        "client_event_id": _event_id(repository["id"], "commit", sha),
        "event_type": "git.commit",
        "observed_at": observed,
        "branch": None,
        "commit_sha": sha or None,
        "remote_url": item.get("web_url"),
        "task_id": _task_id(title, item.get("message")),
        "task_title": title or None,
        "data": {
            "title": title,
            "message": str(item.get("message") or "").strip()[:3000],
            "author_name": item.get("author_name"),
            "author_email": item.get("author_email"),
        },
    })
    return base


def normalize_push_event(project: dict[str, Any], repository: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    push = item.get("push_data") or {}
    title = str(push.get("commit_title") or "").strip()
    ref = str(push.get("ref") or "").strip()
    commit_to = str(push.get("commit_to") or "").strip()
    source_id = str(item.get("id") or "")
    observed = item.get("created_at") or utc_now()
    author = item.get("author") or {}
    base = _base_event(project, repository)
    base.update({
        "client_event_id": _event_id(repository["id"], "push", source_id or f"{commit_to}:{ref}:{observed}"),
        "event_type": "git.push",
        "observed_at": observed,
        "branch": ref or None,
        "commit_sha": commit_to or None,
        "remote_url": None,
        "task_id": _task_id(title, ref),
        "task_title": title or ref or None,
        "data": {
            "title": title,
            "ref": ref,
            "ref_type": push.get("ref_type"),
            "commit_from": push.get("commit_from"),
            "commit_to": push.get("commit_to"),
            "commit_count": push.get("commit_count"),
            "author": item.get("author_username") or (author.get("username") if isinstance(author, dict) else None),
        },
    })
    return base


def normalize_merge_request(project: dict[str, Any], repository: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    state = str(item.get("state") or "opened").lower()
    merged_at = item.get("merged_at")
    event_type = "merge_request.merged" if merged_at or state == "merged" else (
        "merge_request.closed" if state == "closed" else "merge_request.opened"
    )
    title = str(item.get("title") or "").strip()
    iid = str(item.get("iid") or item.get("id") or "")
    updated = str(item.get("updated_at") or item.get("created_at") or utc_now())
    base = _base_event(project, repository)
    base.update({
        "client_event_id": _event_id(repository["id"], "mr", f"{iid}:{state}:{updated}"),
        "event_type": event_type,
        "observed_at": merged_at or updated,
        "branch": item.get("source_branch"),
        "commit_sha": item.get("merge_commit_sha") or item.get("sha"),
        "remote_url": item.get("web_url"),
        "task_id": _task_id(title, item.get("description"), item.get("source_branch")),
        "task_title": title or None,
        "data": {
            "title": title,
            "iid": item.get("iid"),
            "state": state,
            "source_branch": item.get("source_branch"),
            "target_branch": item.get("target_branch"),
            "author": (item.get("author") or {}).get("username"),
        },
    })
    return base


def normalize_pipeline(project: dict[str, Any], repository: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or "").lower()
    if status == "success":
        event_type = "ci.passed"
    elif status == "failed":
        event_type = "ci.failed"
    elif status in {"canceled", "skipped", "manual"}:
        event_type = "ci.finished"
    else:
        event_type = "ci.running"
    pipeline_id = str(item.get("id") or "")
    updated = str(item.get("updated_at") or item.get("created_at") or utc_now())
    ref = str(item.get("ref") or "").strip()
    base = _base_event(project, repository)
    base.update({
        "client_event_id": _event_id(repository["id"], "pipeline", f"{pipeline_id}:{status}:{updated}"),
        "event_type": event_type,
        "observed_at": updated,
        "branch": ref or None,
        "commit_sha": item.get("sha"),
        "remote_url": item.get("web_url"),
        "task_id": _task_id(ref),
        "task_title": ref or None,
        "data": {
            "pipeline_id": item.get("id"),
            "status": status,
            "ref": ref,
            "source": item.get("source"),
        },
    })
    return base


def normalize_deployment(project: dict[str, Any], repository: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or "").lower()
    event_type = (
        "deployment.succeeded" if status == "success" else
        "deployment.failed" if status in {"failed", "canceled"} else
        "deployment.running"
    )
    deployment_id = str(item.get("id") or "")
    updated = str(item.get("updated_at") or item.get("created_at") or utc_now())
    ref = str(item.get("ref") or "").strip()
    deployable = item.get("deployable") or {}
    base = _base_event(project, repository)
    base.update({
        "client_event_id": _event_id(repository["id"], "deployment", f"{deployment_id}:{status}:{updated}"),
        "event_type": event_type,
        "observed_at": updated,
        "branch": ref or None,
        "commit_sha": deployable.get("commit", {}).get("id") if isinstance(deployable, dict) else None,
        "remote_url": None,
        "task_id": _task_id(ref),
        "task_title": ref or None,
        "data": {
            "deployment_id": item.get("id"),
            "status": status,
            "ref": ref,
            "environment": (item.get("environment") or {}).get("name"),
        },
    })
    return base


def _encoded_project(repository: dict[str, Any]) -> str:
    path = str(repository.get("api_project_path") or "").strip()
    if not path:
        parsed = urllib.parse.urlparse(str(repository.get("url") or ""))
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
    if not path:
        raise ValueError(f"missing api_project_path for {repository.get('id')}")
    return urllib.parse.quote(path, safe="")


def _collect_endpoint(
    *, project: dict[str, Any], repository: dict[str, Any], path: str,
    params: dict[str, Any], normalizer: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]],
    newest: datetime,
) -> tuple[int, datetime]:
    emitted = 0
    try:
        rows = gitlab_get_all(path, params)
    except urllib.error.HTTPError as exc:
        print(json.dumps({"level": "warning", "repository": repository.get("id"), "path": path, "status": exc.code}, ensure_ascii=False))
        raise RuntimeError(f"GitLab endpoint {path} failed with HTTP {exc.code}") from exc
    for row in rows:
        event = normalizer(project, repository, row)
        observed = _parse_time(str(event.get("observed_at") or ""))
        if observed and observed > newest:
            newest = observed
        if central_post(event):
            emitted += 1
        else:
            raise RuntimeError(f"Central rejected event from {path}; retry without advancing checkpoint")
    return emitted, newest


def collect_repository(project: dict[str, Any], repository: dict[str, Any], since: datetime) -> tuple[int, datetime]:
    encoded = _encoded_project(repository)
    since_iso = since.astimezone(timezone.utc).isoformat()
    emitted = 0
    newest = since
    endpoints = [
        (f"projects/{encoded}/events", {"action": "pushed", "after": since.date().isoformat(), "per_page": 100}, normalize_push_event),
        (f"projects/{encoded}/repository/commits", {"since": since_iso, "all": "true", "per_page": 100}, normalize_commit),
        (f"projects/{encoded}/merge_requests", {"scope": "all", "updated_after": since_iso, "per_page": 100}, normalize_merge_request),
        (f"projects/{encoded}/pipelines", {"updated_after": since_iso, "per_page": 100}, normalize_pipeline),
        (f"projects/{encoded}/deployments", {"updated_after": since_iso, "order_by": "updated_at", "per_page": 100}, normalize_deployment),
    ]
    for path, params, normalizer in endpoints:
        count, newest = _collect_endpoint(
            project=project,
            repository=repository,
            path=path,
            params=params,
            normalizer=normalizer,
            newest=newest,
        )
        emitted += count
    return emitted, newest


def scan_once() -> dict[str, Any]:
    config = load_config()
    state = load_state()
    repo_state = state.setdefault("repositories", {})
    total = 0
    failures: list[dict[str, Any]] = []
    for project in config.get("projects") or []:
        if not isinstance(project, dict):
            continue
        for repository in project.get("repositories") or []:
            if not isinstance(repository, dict) or repository.get("provider") != "gitlab":
                continue
            repository_id = str(repository.get("id") or "").strip()
            if not repository_id:
                continue
            previous = _parse_time((repo_state.get(repository_id) or {}).get("last_successful_at"))
            since = previous or (datetime.now(timezone.utc) - timedelta(hours=INITIAL_LOOKBACK_HOURS))
            since -= timedelta(minutes=2)
            try:
                emitted, newest = collect_repository(project, repository, since)
                total += emitted
                repo_state[repository_id] = {
                    "last_successful_at": max(newest, datetime.now(timezone.utc)).isoformat(),
                    "last_emitted": emitted,
                    "project_id": project.get("project_id"),
                }
            except Exception as exc:
                failures.append({"repository_id": repository_id, "error": str(exc)})
                print(json.dumps({"level": "error", "repository": repository_id, "error": str(exc)}, ensure_ascii=False))
    state["last_scan_at"] = utc_now()
    save_state(state)
    return {"emitted": total, "failures": failures, "at": state["last_scan_at"]}


def main() -> None:
    print(json.dumps({
        "service": "gitlab-remote-collector",
        "version": COLLECTOR_VERSION,
        "central_enabled": bool(CENTRAL_URL),
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "config": str(CONFIG_PATH),
    }, ensure_ascii=False))
    while True:
        try:
            result = scan_once()
            print(json.dumps({"level": "info", **result}, ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"level": "error", "error": str(exc), "at": utc_now()}, ensure_ascii=False))
        time.sleep(max(POLL_INTERVAL_SECONDS, 60))


if __name__ == "__main__":
    main()
