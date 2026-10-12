"""Read-only Codex history collector for an explicit local project allowlist.

Only initialize/thread-list RPCs are sent; no resume, turns, inference or mutations.
Raw rollout text never leaves the process or enters the projection.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from codex_board_api import safe_text

MAX_TAIL = 256 * 1024


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def classify(command):
    if isinstance(command, list):
        command = " ".join(str(v) for v in command)
    if not isinstance(command, str):
        return None
    if re.search(r"\b(pytest|unittest|ctest|cargo test|npm test|vitest)\b", command):
        return "testing"
    return None


def inspect_rollout(path, cwd, *, now=None, history_root=None, repo_roots=None):
    """Bounded tail of the exact API-returned file, never a directory scan."""
    roots = [Path(p).resolve() for p in (repo_roots or [cwd])]

    def relative_path(name):
        path = Path(name).resolve()
        for root in roots:
            if path.is_relative_to(root):
                return path.relative_to(root).as_posix()
        raise ValueError("Outside approved repository")

    now = time.time() if now is None else now
    root = Path(history_root or Path.home() / ".codex").resolve()
    file = Path(path).resolve()
    if not any(file.is_relative_to(root / d) for d in ("sessions", "archived_sessions")):
        return {}
    if Path(path).is_symlink() or not file.is_file():
        return {}
    with file.open("rb") as stream:
        length = stream.seek(0, 2)
        stream.seek(max(0, length - MAX_TAIL))
        content = stream.read(MAX_TAIL)
    if length > MAX_TAIL:
        content = content.partition(b"\n")[2]
    state, phase, progress, last, passed, failed, test_at = (
        "unknown",
        None,
        None,
        None,
        None,
        None,
        None,
    )
    files = []
    for line in content.splitlines():
        try:
            record = json.loads(line)
            if record.get("type") != "event_msg":
                continue
            data = record["payload"]
            at = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
            if at.tzinfo is None or at.timestamp() > now + 5:
                continue
            event = data.get("type")
        except (ValueError, KeyError, TypeError):
            continue
        if event == "item_completed":
            if state == "ended_unverified":
                state = "unknown"
            item = data.get("item") or {}
            kind = item.get("type")
            if kind == "CommandExecution":
                phase = classify(item.get("command"))
                progress = "最近运行了测试" if phase == "testing" else "最近执行了工具"
                if type(item.get("exit_code")) is int and item["exit_code"] != 0:
                    progress = "最近测试返回异常" if phase == "testing" else "最近工具返回异常"
                output = item.get("aggregated_output") or ""
                try:
                    same_repo = any(
                        Path(item.get("cwd", "")).resolve().is_relative_to(root) for root in roots
                    )
                except TypeError:
                    same_repo = False
                counts = (
                    re.findall(r"(\d+) passed(?:, (\d+) failed)?", output)
                    if isinstance(output, str)
                    else []
                )
                if phase == "testing" and same_repo and counts and item.get("exit_code") == 0:
                    passed, failed, test_at = (
                        int(counts[-1][0]),
                        int(counts[-1][1] or 0),
                        at.isoformat(),
                    )
            elif kind == "FileChange":
                phase, progress = "editing", "最近编辑了文件"
                changes = item.get("changes") or []
                for change in list(changes)[:20]:
                    name = change.get("path") if isinstance(change, dict) else change
                    try:
                        relative = relative_path(name)
                    except (ValueError, TypeError):
                        continue
                    if (
                        re.fullmatch(r"[A-Za-z0-9_./-]{1,64}", relative)
                        and safe_text(relative)
                        and not relative.startswith(".env")
                    ):
                        files.append(relative)
            elif kind == "AgentMessage":
                progress = "最近更新了工作说明"
            else:
                continue
            last = at.isoformat()
            # Recent observed execution activity is not a loaded-engine guarantee.
            # Do not promote an unknown process into running solely from history.
            continue
        if event == "task_started":
            state, phase, progress = "running", None, None
            passed = failed = test_at = None
            files = []
        elif event in ("task_complete", "turn_complete"):
            state = "ended_unverified"
        elif event == "turn_aborted":
            state = "unknown"  # interruption is not an execution error
        elif event == "exec_command_begin":
            phase = classify(data.get("command"))
            progress = "正在运行测试" if phase == "testing" else "正在执行工具"
        elif event == "exec_command_end":
            progress = "工具执行结束" if data.get("exit_code") == 0 else "工具执行返回异常"
            # Only recognize explicit test summaries, never infer counts from exit status.
            output = data.get("aggregated_output") or data.get("stdout") or ""
            if isinstance(output, str):
                counts = re.search(r"(\d+) passed(?:, (\d+) failed)?", output)
                if counts and phase == "testing" and data.get("exit_code") == 0:
                    passed, failed, test_at = int(counts[1]), int(counts[2] or 0), at.isoformat()
        elif event == "agent_message":
            progress = "最近更新了工作说明"
        elif event in ("patch_apply_begin", "patch_apply_end"):
            phase, progress = (
                "editing",
                "正在编辑文件" if event.endswith("begin") else "文件编辑已结束",
            )
            changes = data.get("changes")
            if isinstance(changes, dict):
                for name in list(changes)[:20]:
                    try:
                        relative = relative_path(name)
                    except (ValueError, TypeError):
                        continue
                    if (
                        re.fullmatch(r"[A-Za-z0-9_./-]{1,64}", relative)
                        and safe_text(relative)
                        and not relative.startswith(".env")
                    ):
                        files.append(relative)
        else:
            continue
        last = at.isoformat()
    if state == "running" and (last is None or now - datetime.fromisoformat(last).timestamp() > 90):
        state = "stale"
    return dict(
        state=state,
        phase=phase,
        progress=progress,
        files=list(dict.fromkeys(files))[:3] or None,
        last_event_at=last,
        tests_passed=passed if passed is not None and passed <= 100000 else None,
        tests_failed=failed if failed is not None and failed <= 100000 else None,
        test_observed_at=test_at,
    )


class ReadRPC:
    allowed = {"initialize", "thread/list"}

    async def __aenter__(self):
        self.process = await asyncio.create_subprocess_exec(
            "codex",
            "app-server",
            "--listen",
            "stdio://",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=16 * 1024 * 1024,
        )
        self.sequence = 0
        await self.call("initialize", {"clientInfo": {"name": "muse_readonly", "version": "0.2"}})
        self.process.stdin.write(b'{"method":"initialized"}\n')
        await self.process.stdin.drain()
        return self

    async def call(self, method, params):
        if method not in self.allowed:
            raise ValueError("Only read RPC permitted")
        self.sequence += 1
        self.process.stdin.write(
            (json.dumps({"id": self.sequence, "method": method, "params": params}) + "\n").encode()
        )
        await self.process.stdin.drain()
        while True:
            line = await asyncio.wait_for(self.process.stdout.readline(), 20)
            if not line:
                raise RuntimeError("Read source closed")
            value = json.loads(line)
            if value.get("id") == self.sequence:
                if "error" in value:
                    raise RuntimeError("Read source rejected")
                return value["result"]

    async def __aexit__(self, *args):
        if self.process.returncode is None:
            self.process.terminate()
        await self.process.wait()


async def collect(registry, capability, rpc):
    registered = registry["projects"][:50]
    by_cwd = {}
    for p in registered:
        for cwd in [p["cwd"]] + p.get("additional_cwds", []):
            if cwd in by_cwd and by_cwd[cwd]["project_id"] != p["project_id"]:
                raise ValueError("Ambiguous registered workspace")
            by_cwd[cwd] = p
    rows = []
    cursor = None
    # A scoped metadata query never scans unrelated JSONL histories for repair.
    for _ in range(10):
        result = await rpc.call(
            "thread/list",
            {
                "cwd": list(by_cwd),
                "cursor": cursor,
                "limit": 100,
                "sortKey": "updated_at",
                "useStateDbOnly": True,
                "sourceKinds": ["cli", "vscode", "appServer", "exec"],
            },
        )
        rows.extend(result["data"])
        cursor = result.get("nextCursor")
        if not cursor:
            break
    else:
        raise ValueError("Incomplete scoped listing")
    projects = {}
    seen = set()
    for row in rows:
        p = by_cwd.get(row.get("cwd"))
        if not p or row.get("id") in seen:
            continue
        seen.add(row["id"])
        project = projects.setdefault(
            p["project_id"], dict(project_id=p["project_id"], alias=p["alias"], tasks=[])
        )
        if len(project["tasks"]) >= 5:
            continue
        evidence = (
            inspect_rollout(row["path"], row["cwd"], repo_roots=p.get("repo_roots"))
            if row.get("path")
            else {}
        )
        # Original engine status is only an observer of this read-only app-server.
        # Running comes solely from fresh execution events, not notLoaded->idle guesses.
        task = dict(
            execution_id=row["id"],
            repository_id="desktop:" + p["project_id"],
            title=safe_text(row.get("name")) or "Codex " + row["id"][:8],
            state="unknown",
            phase=None,
            progress=None,
            files=None,
            tests_passed=None,
            tests_failed=None,
            test_observed_at=None,
            last_event_at=None,
            model_profile=None,
            reasoning_effort=None,
            source="codex_desktop",
            feedback_allowed=False,
            formal_completion=False,
        )
        task.update(evidence)
        project["tasks"].append(task)
    return dict(
        schema_version=1,
        observed_at=iso(time.time()),
        muse_capability=capability,
        registered_project_ids=[p["project_id"] for p in registered],
        projects=list(projects.values()),
    )


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.chmod(0o600)
    temporary.replace(path)


async def run(args):
    registry = json.loads(Path(args.registry).read_text())
    capability = (
        args.capability or hashlib.sha256(os.environ["CAO_MUSE_TOKEN"].encode()).hexdigest()
    )
    while True:
        try:
            async with ReadRPC() as rpc:
                while True:
                    value = await collect(registry, capability, rpc)
                    atomic_write(args.output, value)
                    print(
                        json.dumps(
                            {
                                "projects": len(value["projects"]),
                                "tasks": sum(len(p["tasks"]) for p in value["projects"]),
                            }
                        ),
                        flush=True,
                    )
                    if args.once:
                        return
                    await asyncio.sleep(15)
        except Exception:
            # Projection expires; reconnect only the read transport, never resume a task.
            print("Read source unavailable", flush=True)
            if args.once:
                return
            await asyncio.sleep(15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--capability", help="Precomputed scope digest; no execution token needed")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
