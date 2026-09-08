from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from document_pipeline import analyze_project_files, is_sensitive_path

PROJECTS_ROOT = Path(os.getenv("PROJECTS_ROOT", "/projects"))
STATE_ROOT = Path(os.getenv("SENTINEL_STATE_ROOT", "/state"))
CENTRAL_URL = os.getenv("CENTRAL_URL", "").rstrip("/")
COLLECTOR_TOKEN = os.getenv("COLLECTOR_TOKEN", "")
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "900"))
USER_ID = os.getenv("USER_ID", os.getenv("USER", "unknown"))
DEVICE_ID = os.getenv("DEVICE_ID", socket.gethostname())
SENTINEL_VERSION = "0.2.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_git(repo: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def git_snapshot(repo: Path) -> dict[str, Any]:
    if not (repo / ".git").exists():
        return {"is_git_repo": False}

    _, branch = run_git(repo, "branch", "--show-current")
    _, head = run_git(repo, "rev-parse", "HEAD")
    upstream_code, upstream = run_git(repo, "rev-parse", "--abbrev-ref", "@{upstream}")

    ahead = behind = None
    if upstream_code == 0 and upstream:
        code, counts = run_git(repo, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        if code == 0 and counts:
            parts = counts.replace("\t", " ").split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])

    _, porcelain = run_git(repo, "status", "--porcelain=v1")
    changed: list[dict[str, str]] = []
    counts = {"modified": 0, "added": 0, "deleted": 0, "renamed": 0, "untracked": 0, "other": 0}

    for line in porcelain.splitlines():
        if len(line) < 3:
            continue
        code = line[:2]
        path = line[3:]
        if code == "??":
            kind = "untracked"
        elif "D" in code:
            kind = "deleted"
        elif "R" in code:
            kind = "renamed"
        elif "A" in code:
            kind = "added"
        elif "M" in code:
            kind = "modified"
        else:
            kind = "other"
        counts[kind] += 1
        changed.append({"status": code, "kind": kind, "path": path})

    _, diff_numstat = run_git(repo, "diff", "HEAD", "--numstat")
    added_lines = deleted_lines = 0
    for line in diff_numstat.splitlines():
        parts = line.split("\t", 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            added_lines += int(parts[0])
            deleted_lines += int(parts[1])

    return {
        "is_git_repo": True,
        "branch": branch or None,
        "head": head or None,
        "upstream": upstream if upstream_code == 0 else None,
        "ahead": ahead,
        "behind": behind,
        "dirty": bool(changed),
        "change_counts": counts,
        "changed_files": changed[:500],
        "diff_stat": {"added_lines": added_lines, "deleted_lines": deleted_lines},
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_file_metadata(path: Path, project_root: Path) -> dict[str, Any] | None:
    try:
        relative = path.relative_to(project_root).as_posix()
        stat = path.stat()
    except (OSError, ValueError):
        return None

    if is_sensitive_path(path, project_root):
        return {"path": relative, "sensitive": True}

    try:
        digest = file_sha256(path)
    except OSError:
        return None

    return {
        "path": relative,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": digest,
        "suffix": path.suffix.lower(),
    }


def expand_path(project_root: Path, raw: str) -> Iterable[Path]:
    has_glob = any(ch in raw for ch in "*?[")
    candidates = list(project_root.glob(raw)) if has_glob else [project_root / raw]
    for candidate in candidates:
        if candidate.is_file():
            yield candidate
        elif candidate.is_dir():
            yield from (item for item in candidate.rglob("*") if item.is_file())


def manifest_metadata(project_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Collect only metadata from declared document/test/output roots."""
    items: list[dict[str, Any]] = []
    configured = manifest.get("paths") or {}
    roots = (
        list(configured.get("documents") or [])
        + list(configured.get("tests") or [])
        + list(configured.get("outputs") or [])
    )

    seen: set[str] = set()
    for raw in roots:
        for file_path in expand_path(project_root, raw):
            if ".git" in file_path.parts:
                continue
            try:
                relative = file_path.relative_to(project_root).as_posix()
            except ValueError:
                continue
            if relative in seen:
                continue
            seen.add(relative)
            meta = safe_file_metadata(file_path, project_root)
            if meta:
                items.append(meta)
            if len(items) >= 2000:
                return {"files": items, "truncated": True}

    return {"files": items, "truncated": False}


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if data.get("version") != 1:
        raise ValueError("unsupported project.yaml version")
    project = data.get("project") or {}
    if not project.get("id") or not project.get("name"):
        raise ValueError("project.id and project.name are required")
    return data


def discover_projects() -> list[tuple[Path, dict[str, Any]]]:
    discovered: list[tuple[Path, dict[str, Any]]] = []
    if not PROJECTS_ROOT.exists():
        return discovered

    for child in sorted(PROJECTS_ROOT.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "project.yaml"
        if not manifest_path.is_file():
            continue
        try:
            discovered.append((child, load_manifest(manifest_path)))
        except Exception as exc:
            print(json.dumps({"level": "error", "project": child.name, "error": str(exc)}, ensure_ascii=False))
    return discovered


def build_snapshot(project_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    project = manifest["project"]
    security = manifest.get("security") or {}
    snapshot = {
        "schema_version": 1,
        "snapshot_type": "local.workspace",
        "observed_at": utc_now(),
        "project_id": project["id"],
        "project_name": project["name"],
        "user_id": USER_ID,
        "device_id": DEVICE_ID,
        "workspace_name": project_root.name,
        "collector": {"name": "project-sentinel", "version": SENTINEL_VERSION},
        "security_mode": security.get("mode", "metadata_only"),
        "git": git_snapshot(project_root),
        "files": manifest_metadata(project_root, manifest),
    }

    # metadata_only 不读取正文；local_analysis 才进入增量文档解析与本地分析。
    snapshot["analysis"] = analyze_project_files(project_root, manifest, STATE_ROOT)
    return snapshot


def upload_snapshot(snapshot: dict[str, Any]) -> bool:
    if not CENTRAL_URL:
        print(json.dumps(snapshot, ensure_ascii=False))
        return True

    body = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"project-sentinel/{SENTINEL_VERSION}",
    }
    if COLLECTOR_TOKEN:
        headers["X-Collector-Token"] = COLLECTOR_TOKEN

    request = urllib.request.Request(
        f"{CENTRAL_URL}/api/v1/snapshots",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError) as exc:
        print(json.dumps({"level": "error", "upload": False, "error": str(exc)}, ensure_ascii=False))
        return False


def scan_once() -> int:
    projects = discover_projects()
    for project_root, manifest in projects:
        snapshot = build_snapshot(project_root, manifest)
        upload_snapshot(snapshot)
    return len(projects)


def main() -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    print(
        json.dumps(
            {
                "service": "project-sentinel",
                "version": SENTINEL_VERSION,
                "projects_root": str(PROJECTS_ROOT),
                "state_root": str(STATE_ROOT),
                "interval_seconds": INTERVAL_SECONDS,
                "central_enabled": bool(CENTRAL_URL),
            },
            ensure_ascii=False,
        )
    )
    while True:
        try:
            count = scan_once()
            print(json.dumps({"level": "info", "projects_scanned": count, "at": utc_now()}, ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"level": "error", "error": str(exc), "at": utc_now()}, ensure_ascii=False))
        time.sleep(max(INTERVAL_SECONDS, 10))


if __name__ == "__main__":
    main()
