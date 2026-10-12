import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from codex_desktop_collector import ReadRPC, collect, inspect_rollout
from codex_board_api import desktop_snapshot
from execution_p2 import muse_capability


def log(tmp_path, events):
    root = tmp_path / "sessions"
    root.mkdir(exist_ok=True)
    path = root / "approved.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "timestamp": datetime.fromtimestamp(t, timezone.utc).isoformat(),
                    "type": "event_msg",
                    "payload": p,
                }
            )
            for t, p in events
        )
    )
    return path


def test_finished_is_unverified_no_raw_text(tmp_path):
    p = log(
        tmp_path,
        [
            (90, {"type": "task_started"}),
            (99, {"type": "task_complete", "last_agent_message": "sk-private"}),
        ],
    )
    result = inspect_rollout(p, tmp_path, now=100, history_root=tmp_path)
    assert result["state"] == "ended_unverified"
    assert "sk-private" not in json.dumps(result)


def test_recent_start_expires_without_activity(tmp_path):
    p = log(tmp_path, [(10, {"type": "task_started"})])
    assert inspect_rollout(p, tmp_path, now=15, history_root=tmp_path)["state"] == "running"
    assert inspect_rollout(p, tmp_path, now=101, history_root=tmp_path)["state"] == "stale"


def test_current_desktop_item_schema_and_relative_files(tmp_path):
    p = log(
        tmp_path,
        [
            (
                90,
                {
                    "type": "item_completed",
                    "item": {
                        "type": "FileChange",
                        "changes": [
                            {"path": str(tmp_path / "src/a.py"), "diff": "secret"},
                            {"path": "/etc/password"},
                        ],
                    },
                },
            )
        ],
    )
    result = inspect_rollout(p, tmp_path, now=100, history_root=tmp_path)
    assert result["state"] == "unknown" and result["files"] == ["src/a.py"]
    assert result["progress"] == "最近编辑了文件" and "secret" not in json.dumps(result)


def test_counts_need_test_command_same_repository_and_real_output(tmp_path):
    p = log(
        tmp_path,
        [
            (
                99,
                {
                    "type": "item_completed",
                    "item": {
                        "type": "CommandExecution",
                        "command": "pytest -q",
                        "cwd": str(tmp_path),
                        "aggregated_output": "12 passed in 0.2s",
                        "exit_code": 0,
                    },
                },
            )
        ],
    )
    result = inspect_rollout(p, tmp_path, now=100, history_root=tmp_path)
    assert result["tests_passed"] == 12 and result["tests_failed"] == 0
    p = log(
        tmp_path,
        [
            (
                99,
                {
                    "type": "item_completed",
                    "item": {
                        "type": "CommandExecution",
                        "command": 'echo "12 passed"',
                        "cwd": str(tmp_path),
                        "aggregated_output": "12 passed",
                        "exit_code": 0,
                    },
                },
            )
        ],
    )
    assert inspect_rollout(p, tmp_path, now=100, history_root=tmp_path)["tests_passed"] is None


def test_outside_history_or_symlink_not_read(tmp_path):
    private = tmp_path / "private.txt"
    private.write_text("private")
    assert inspect_rollout(private, tmp_path, history_root=tmp_path) == {}
    (tmp_path / "sessions").mkdir()
    link = tmp_path / "sessions" / "link.jsonl"
    link.symlink_to(private)
    assert inspect_rollout(link, tmp_path, history_root=tmp_path) == {}


def test_rpc_mutations_are_not_callable():
    rpc = ReadRPC()
    with pytest.raises(ValueError):
        asyncio.run(rpc.call("turn/start", {}))


def test_scoped_metadata_collection_keeps_nonloaded_unknown():
    class RPC:
        async def call(self, method, params):
            assert (
                method == "thread/list"
                and params["cwd"] == ["/approved"]
                and params["useStateDbOnly"]
            )
            return {
                "data": [
                    {"id": str(uuid4()), "cwd": "/approved", "status": {"type": "notLoaded"}},
                    {"id": str(uuid4()), "cwd": "/private"},
                ],
                "nextCursor": None,
            }

    data = asyncio.run(
        collect(
            {"projects": [{"project_id": "p", "alias": "P09", "cwd": "/approved"}]}, "cap", RPC()
        )
    )
    assert len(data["projects"]) == 1 and len(data["projects"][0]["tasks"]) == 1
    assert data["projects"][0]["tasks"][0]["state"] == "unknown"
    assert not data["projects"][0]["tasks"][0]["feedback_allowed"]


def projection(tmp_path):
    key = "execution-token"
    data = asyncio.run(
        collect(
            {"projects": [{"project_id": "p", "alias": "P09", "cwd": "/approved"}]},
            muse_capability(key),
            type(
                "RPC",
                (),
                {
                    "call": lambda *a: asyncio.sleep(
                        0,
                        result={
                            "data": [{"id": str(uuid4()), "cwd": "/approved"}],
                            "nextCursor": None,
                        },
                    )
                },
            )(),
        )
    )
    path = tmp_path / "safe.json"
    path.write_text(json.dumps(data))
    return path, data, key


@pytest.mark.parametrize("change", ["capability", "scope", "stale", "extra", "write"])
def test_server_projection_fails_closed(tmp_path, change):
    path, data, key = projection(tmp_path)
    if change == "capability":
        data["muse_capability"] = "wrong"
    elif change == "scope":
        data["registered_project_ids"] = ["private"]
    elif change == "stale":
        data["observed_at"] = "2000-01-01T00:00:00+00:00"
    elif change == "extra":
        data["prompt"] = "private"
    elif change == "write":
        data["projects"][0]["tasks"][0]["feedback_allowed"] = True
    path.write_text(json.dumps(data))
    assert (
        desktop_snapshot(
            {"desktop_board_project_ids": ["p"], "desktop_board_snapshot_path": str(path)}, key
        )[1]
        is False
    )


def test_good_projection_is_always_readonly(tmp_path):
    path, data, key = projection(tmp_path)
    projects, ready, registered = desktop_snapshot(
        {"desktop_board_project_ids": ["p"], "desktop_board_snapshot_path": str(path)}, key
    )
    assert ready and registered == {"p"} and projects[0]["tasks"][0]["feedback_allowed"] is False
