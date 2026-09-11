from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any


NEGATIVE_TEST_MARKERS = ("失败", "不通过", "未通过", "failed", "failure", "error", "异常")


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_time(values: list[Any]) -> str | None:
    parsed = [(item, _parse_time(item)) for item in values]
    parsed = [(raw, dt) for raw, dt in parsed if dt is not None]
    if not parsed:
        return None
    return str(max(parsed, key=lambda pair: pair[1])[0])


def _has_failed_test(memory: dict[str, Any]) -> bool:
    for fact in memory.get("tests") or []:
        text = str(fact.get("text") or "").lower()
        if any(marker in text for marker in NEGATIVE_TEST_MARKERS):
            return True
    return False


def _actor_key(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff@._-]+", "", text.lower())


def _new_contributor(user_id: str, display_name: str | None = None) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "display_name": display_name or user_id,
        "workspaces": [],
        "devices": set(),
        "branches": set(),
        "repositories": set(),
        "latest_activity_at": None,
        "dirty_workspace_count": 0,
        "changed_file_count": 0,
        "attention_workspace_count": 0,
        "agent_names": set(),
        "agent_event_count": 0,
        "remote_event_count": 0,
        "source_types": set(),
        "identity_refs": {},
    }


def _remote_actor(event: dict[str, Any]) -> tuple[str, str | None, str | None]:
    data = event.get("data") or {}
    provider = str(event.get("provider") or "gitlab").strip().lower() or "gitlab"
    author = data.get("author")
    username = data.get("author_username")
    display_name = data.get("author_name")

    if isinstance(author, dict):
        username = username or author.get("username") or author.get("login")
        display_name = display_name or author.get("name") or username
    elif isinstance(author, str):
        username = username or author
        display_name = display_name or author

    if event.get("event_type") == "git.commit":
        username = username or data.get("author_name")
        display_name = display_name or data.get("author_name")

    external_id = re.sub(r"\s+", " ", str(username or display_name or "")).strip() or None
    display = re.sub(r"\s+", " ", str(display_name or external_id or "")).strip() or None
    return provider, external_id, display


def build_workspace_view(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = snapshot.get("payload") or {}
    git = payload.get("git") or {}
    analysis = payload.get("analysis") or {}
    memory = analysis.get("current_project_memory") or {}
    git_changes = payload.get("git_change_analysis") or {}

    changed_files = list(git.get("changed_files") or [])
    blockers = list(memory.get("blockers") or [])
    failed_test = _has_failed_test(memory)

    return {
        "snapshot_id": snapshot.get("id"),
        "project_id": snapshot.get("project_id"),
        "project_name": snapshot.get("project_name"),
        "user_id": snapshot.get("user_id"),
        "device_id": snapshot.get("device_id"),
        "workspace_name": snapshot.get("workspace_name"),
        "observed_at": snapshot.get("observed_at"),
        "received_at": snapshot.get("received_at"),
        "git": {
            "is_git_repo": bool(git.get("is_git_repo")),
            "repository_path": git.get("repository_path"),
            "branch": git.get("branch"),
            "head": git.get("head"),
            "upstream": git.get("upstream"),
            "dirty": bool(git.get("dirty")),
            "ahead": git.get("ahead"),
            "behind": git.get("behind"),
            "changed_file_count": len(changed_files),
            "change_counts": git.get("change_counts") or {},
            "diff_stat": git.get("diff_stat") or {},
        },
        "analysis": {
            "enabled": bool(analysis.get("enabled")),
            "current_source_count": memory.get("current_source_count", 0),
            "historical_source_count": memory.get("historical_source_count", 0),
            "requirement_count": len(memory.get("requirements") or []),
            "task_count": len(memory.get("tasks") or []),
            "test_count": len(memory.get("tests") or []),
            "blocker_count": len(blockers),
            "has_failed_test": failed_test,
        },
        "git_change_analysis": {
            "enabled": bool(git_changes.get("enabled")),
            "changed_file_count": git_changes.get("changed_file_count", 0),
            "analyzed_file_count": git_changes.get("analyzed_file_count", 0),
        },
        "attention_required": bool(blockers or failed_test or (isinstance(git.get("behind"), int) and git.get("behind") > 0)),
    }


def build_project_rollup(
    workspace_snapshots: list[dict[str, Any]],
    agent_events: list[dict[str, Any]] | None = None,
    remote_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate contributors while keeping cross-provider identities separate until resolved."""
    agent_events = agent_events or []
    remote_events = remote_events or []
    workspaces = [build_workspace_view(snapshot) for snapshot in workspace_snapshots]

    contributor_map: dict[str, dict[str, Any]] = {}

    def contributor_for(
        namespace: str,
        raw_id: Any,
        display_name: str | None = None,
        *,
        identity_provider: str | None = None,
        identity_external_id: str | None = None,
    ) -> dict[str, Any]:
        raw_text = re.sub(r"\s+", " ", str(raw_id or "unknown")).strip() or "unknown"
        key = f"{namespace}:{_actor_key(raw_text) or 'unknown'}"
        item = contributor_map.get(key)
        if item is None:
            item = _new_contributor(raw_text, display_name)
            contributor_map[key] = item
        elif display_name and (not item.get("display_name") or item.get("display_name") == item.get("user_id")):
            item["display_name"] = display_name
        provider = str(identity_provider or "").strip().lower()
        external_id = re.sub(r"\s+", " ", str(identity_external_id or raw_text)).strip()
        if provider and external_id:
            item["identity_refs"][(provider, external_id.lower())] = {
                "provider": provider,
                "external_id": external_id,
                "display_name": display_name or raw_text,
            }
        return item

    for workspace in workspaces:
        user_id = workspace.get("user_id")
        contributor = contributor_for(
            "principal",
            user_id,
            identity_provider="local",
            identity_external_id=str(user_id or ""),
        )
        contributor["source_types"].add("local")
        contributor["workspaces"].append(workspace.get("workspace_name"))
        if workspace.get("device_id"):
            contributor["devices"].add(str(workspace["device_id"]))
        branch = (workspace.get("git") or {}).get("branch")
        if branch:
            contributor["branches"].add(str(branch))
        contributor["latest_activity_at"] = _latest_time(
            [contributor.get("latest_activity_at"), workspace.get("observed_at"), workspace.get("received_at")]
        )
        if (workspace.get("git") or {}).get("dirty"):
            contributor["dirty_workspace_count"] += 1
        contributor["changed_file_count"] += int((workspace.get("git") or {}).get("changed_file_count") or 0)
        if workspace.get("attention_required"):
            contributor["attention_workspace_count"] += 1

    for event in agent_events:
        user_id = event.get("user_id")
        contributor = contributor_for(
            "principal",
            user_id,
            identity_provider="agent",
            identity_external_id=str(user_id or ""),
        )
        contributor["source_types"].add("agent")
        agent = event.get("agent") or {}
        name = str(agent.get("name") or agent.get("vendor") or "").strip()
        if name:
            contributor["agent_names"].add(name)
        contributor["agent_event_count"] += 1
        contributor["latest_activity_at"] = _latest_time(
            [contributor.get("latest_activity_at"), event.get("observed_at"), event.get("received_at")]
        )

    for event in remote_events:
        provider, external_id, display_name = _remote_actor(event)
        if not external_id:
            continue
        contributor = contributor_for(
            f"remote:{provider}",
            external_id,
            display_name,
            identity_provider=provider,
            identity_external_id=external_id,
        )
        contributor["source_types"].add("repository")
        contributor["remote_event_count"] += 1
        repository_id = str(event.get("repository_id") or "").strip()
        if repository_id:
            contributor["repositories"].add(repository_id)
        branch = str(event.get("branch") or "").strip()
        if branch:
            contributor["branches"].add(branch)
        contributor["latest_activity_at"] = _latest_time(
            [contributor.get("latest_activity_at"), event.get("observed_at"), event.get("received_at")]
        )

    contributors: list[dict[str, Any]] = []
    for contributor in contributor_map.values():
        contributors.append(
            {
                "user_id": contributor["user_id"],
                "display_name": contributor["display_name"],
                "workspace_count": len(set(item for item in contributor["workspaces"] if item)),
                "workspaces": sorted(set(item for item in contributor["workspaces"] if item)),
                "devices": sorted(contributor["devices"]),
                "branches": sorted(contributor["branches"]),
                "repositories": sorted(contributor["repositories"]),
                "latest_activity_at": contributor["latest_activity_at"],
                "dirty_workspace_count": contributor["dirty_workspace_count"],
                "changed_file_count": contributor["changed_file_count"],
                "attention_workspace_count": contributor["attention_workspace_count"],
                "agents": sorted(contributor["agent_names"]),
                "agent_event_count": contributor["agent_event_count"],
                "remote_event_count": contributor["remote_event_count"],
                "source_types": sorted(contributor["source_types"]),
                "identity_refs": sorted(
                    contributor["identity_refs"].values(),
                    key=lambda item: (str(item.get("provider") or ""), str(item.get("external_id") or "")),
                ),
            }
        )
    contributors.sort(key=lambda item: item.get("latest_activity_at") or "", reverse=True)

    branch_counts = Counter(
        str((workspace.get("git") or {}).get("branch"))
        for workspace in workspaces
        if (workspace.get("git") or {}).get("branch")
    )
    dirty_count = sum(1 for workspace in workspaces if (workspace.get("git") or {}).get("dirty"))
    attention_count = sum(1 for workspace in workspaces if workspace.get("attention_required"))
    changed_files = sum(int((workspace.get("git") or {}).get("changed_file_count") or 0) for workspace in workspaces)

    event_type_counts = Counter(str(event.get("event_type") or "unknown") for event in agent_events)
    agents = sorted(
        {
            str((event.get("agent") or {}).get("name") or (event.get("agent") or {}).get("vendor") or "").strip()
            for event in agent_events
            if str((event.get("agent") or {}).get("name") or (event.get("agent") or {}).get("vendor") or "").strip()
        }
    )

    if attention_count:
        state = "attention"
        state_label = "需要关注"
    elif dirty_count or agent_events or remote_events:
        state = "active"
        state_label = "协作开发中"
    else:
        state = "quiet"
        state_label = "暂无明显开发活动"

    return {
        "version": 2,
        "project_state": state,
        "project_state_label": state_label,
        "workspace_count": len(workspaces),
        "contributor_count": len(contributors),
        "local_contributor_count": sum(1 for item in contributors if "local" in item["source_types"]),
        "repository_contributor_count": sum(1 for item in contributors if "repository" in item["source_types"]),
        "dirty_workspace_count": dirty_count,
        "attention_workspace_count": attention_count,
        "local_changed_file_count": changed_files,
        "branches": dict(branch_counts),
        "agents": agents,
        "agent_event_count": len(agent_events),
        "remote_event_count": len(remote_events),
        "agent_event_type_counts": dict(event_type_counts),
        "latest_activity_at": _latest_time(
            [workspace.get("observed_at") for workspace in workspaces]
            + [event.get("observed_at") for event in agent_events]
            + [event.get("observed_at") for event in remote_events]
        ),
        "contributors": contributors,
        "workspaces": workspaces,
    }
