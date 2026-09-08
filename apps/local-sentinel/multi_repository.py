from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


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


def configured_repositories(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return repository configs while preserving the legacy single-repository manifest."""
    repositories = manifest.get("repositories")
    if isinstance(repositories, list) and repositories:
        result = [dict(item) for item in repositories if isinstance(item, dict)]
    else:
        legacy = manifest.get("repository") or {}
        result = [dict(legacy)] if legacy else []

    for index, item in enumerate(result):
        item.setdefault("id", "primary" if len(result) == 1 else f"repo-{index + 1}")
        item.setdefault("role", "application")
        if "primary" not in item:
            item["primary"] = index == 0
    if result and not any(bool(item.get("primary")) for item in result):
        result[0]["primary"] = True
    return result


def resolve_repository(project_root: Path, repository: dict[str, Any]) -> tuple[Path | None, str]:
    raw = str(repository.get("local_path") or ".").strip() or "."
    project_resolved = project_root.resolve()
    candidate = (project_root / raw).resolve() if raw not in {".", "./"} else project_resolved
    try:
        relative = candidate.relative_to(project_resolved).as_posix() or "."
    except ValueError:
        return None, raw
    return candidate, relative


def inspect_repository(project_root: Path, repository: dict[str, Any]) -> tuple[Path | None, dict[str, Any]]:
    repo, repository_path = resolve_repository(project_root, repository)
    identity = {
        "repository_id": repository.get("id"),
        "role": repository.get("role"),
        "provider": repository.get("provider"),
        "repository_url": repository.get("url"),
        "repository_path": repository_path,
        "primary": bool(repository.get("primary")),
    }
    if repo is None:
        return None, {**identity, "is_git_repo": False, "reason": "repository.local_path escapes project root"}
    if not repo.exists():
        return repo, {**identity, "is_git_repo": False, "reason": "declared repository.local_path does not exist"}
    git_marker = repo / ".git"
    if not git_marker.exists():
        return repo, {**identity, "is_git_repo": False, "reason": "declared repository path has no .git"}

    _, branch = run_git(repo, "branch", "--show-current")
    _, head = run_git(repo, "rev-parse", "HEAD")
    upstream_code, upstream = run_git(repo, "rev-parse", "--abbrev-ref", "@{upstream}")

    ahead = behind = None
    if upstream_code == 0 and upstream:
        code, counts_text = run_git(repo, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        if code == 0 and counts_text:
            parts = counts_text.replace("\t", " ").split()
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                behind, ahead = int(parts[0]), int(parts[1])

    _, porcelain = run_git(repo, "status", "--porcelain=v1")
    changed: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
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
        changed.append(
            {
                "status": code,
                "kind": kind,
                "path": path,
                "repository_id": repository.get("id"),
                "repository_role": repository.get("role"),
            }
        )

    _, diff_numstat = run_git(repo, "diff", "HEAD", "--numstat")
    added_lines = deleted_lines = 0
    for line in diff_numstat.splitlines():
        parts = line.split("\t", 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            added_lines += int(parts[0])
            deleted_lines += int(parts[1])

    return repo, {
        **identity,
        "is_git_repo": True,
        "branch": branch or None,
        "head": head or None,
        "upstream": upstream if upstream_code == 0 else None,
        "ahead": ahead,
        "behind": behind,
        "dirty": bool(changed),
        "change_counts": {
            key: counts.get(key, 0)
            for key in ("modified", "added", "deleted", "renamed", "untracked", "other")
        },
        "changed_files": changed[:500],
        "diff_stat": {"added_lines": added_lines, "deleted_lines": deleted_lines},
    }


def inspect_repositories(project_root: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[dict[str, Any], Path | None, dict[str, Any]]]]:
    runtime: list[tuple[dict[str, Any], Path | None, dict[str, Any]]] = []
    snapshots: list[dict[str, Any]] = []
    for repository in configured_repositories(manifest):
        repo_path, snapshot = inspect_repository(project_root, repository)
        runtime.append((repository, repo_path, snapshot))
        snapshots.append(snapshot)

    primary = next((item for item in snapshots if item.get("primary")), snapshots[0] if snapshots else {})
    change_counts: Counter[str] = Counter()
    changed_files: list[dict[str, Any]] = []
    total_added = total_deleted = 0
    any_git = False
    any_dirty = False
    ahead_values: list[int] = []
    behind_values: list[int] = []

    for item in snapshots:
        if item.get("is_git_repo"):
            any_git = True
        if item.get("dirty"):
            any_dirty = True
        for key, value in (item.get("change_counts") or {}).items():
            if isinstance(value, int):
                change_counts[key] += value
        changed_files.extend(item.get("changed_files") or [])
        diff_stat = item.get("diff_stat") or {}
        total_added += int(diff_stat.get("added_lines") or 0)
        total_deleted += int(diff_stat.get("deleted_lines") or 0)
        if isinstance(item.get("ahead"), int):
            ahead_values.append(int(item["ahead"]))
        if isinstance(item.get("behind"), int):
            behind_values.append(int(item["behind"]))

    aggregate = {
        "is_git_repo": any_git,
        "multi_repository": len(snapshots) > 1,
        "repository_count": len(snapshots),
        "available_repository_count": sum(1 for item in snapshots if item.get("is_git_repo")),
        "dirty": any_dirty,
        "branch": primary.get("branch"),
        "head": primary.get("head"),
        "upstream": primary.get("upstream"),
        "ahead": sum(ahead_values) if ahead_values else None,
        "behind": sum(behind_values) if behind_values else None,
        "repository_path": primary.get("repository_path"),
        "repository_id": primary.get("repository_id"),
        "change_counts": {
            key: change_counts.get(key, 0)
            for key in ("modified", "added", "deleted", "renamed", "untracked", "other")
        },
        "changed_files": changed_files[:1000],
        "diff_stat": {"added_lines": total_added, "deleted_lines": total_deleted},
        "repositories": snapshots,
    }
    return aggregate, runtime
