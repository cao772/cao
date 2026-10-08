"""Fail closed before Codex execution when effective tools escape the P2 allowlist.

Installed as a dedicated executable named `codex`; never changes the user's config.
"""

import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

from p2_policy import P2_ARGS, P2_TOOLS
from p2_builtin_audit import audit


def execution_environment():
    # Do not inherit desktop parent sandbox/session overrides or API keys.
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("CODEX_") or key == "CODEX_HOME"
    }


def validate_config(config):
    enabled = {
        name: value
        for name, value in config.get("mcp_servers", {}).items()
        if value.get("enabled", True)
    }
    if set(enabled) != {"cao-sentinel"}:
        raise RuntimeError("Unapproved MCP server; execution refused")
    server = enabled["cao-sentinel"]
    if (
        server.get("url") != "http://127.0.0.1:6410/mcp"
        or server.get("command")
        or set(server.get("enabled_tools", [])) != set(P2_TOOLS)
        or server.get("default_tools_approval_mode") != "approve"
    ):
        raise RuntimeError("Unapproved report tool policy")
    if config.get("agents", {}).get("enabled") is not False:
        raise RuntimeError("Agent delegation must be disabled")
    features = config.get("features", {})
    if (
        any(
            features.get(key) is not False
            for key in (
                "plugins",
                "remote_plugin",
                "apps",
                "multi_agent",
                "multi_agent_v2",
            )
        )
        or config.get("web_search") != "disabled"
    ):
        raise RuntimeError("Unapproved plugin/app/delegation/web capability")


class Probe:
    def __init__(self, binary, args, cwd):
        self.process = subprocess.Popen(
            [binary, *args, "app-server"],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=execution_environment(),
        )
        self.counter = 0
        self.rpc(
            "initialize",
            {
                "clientInfo": {"name": "cao-p2-guard", "version": "2"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.process.stdin.write(json.dumps({"method": "initialized"}) + "\n")
        self.process.stdin.flush()

    def rpc(self, method, params):
        self.counter += 1
        request_id = self.counter
        self.process.stdin.write(
            json.dumps({"id": request_id, "method": method, "params": params}) + "\n"
        )
        self.process.stdin.flush()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if not select.select([self.process.stdout], [], [], 1)[0]:
                continue
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("Codex preflight exited")
            value = json.loads(line)
            if value.get("id") == request_id:
                if "error" in value:
                    raise RuntimeError("Codex preflight RPC rejected")
                return value["result"]
        raise RuntimeError("Codex preflight timeout")

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def inspect_tools(probe, cwd):
    # Check effective project/user layers BEFORE initializing any MCP server.
    validate_config(
        probe.rpc("config/read", {"includeLayers": False, "cwd": cwd})["config"]
    )
    tools = {}
    cursor = None
    while True:
        result = probe.rpc(
            "mcpServerStatus/list", {"detail": "toolsAndAuthOnly", "cursor": cursor}
        )
        for server in result["data"]:
            if server.get("toolsError"):
                raise RuntimeError("MCP tool inventory unconfirmed")
            for name in server["tools"]:
                tools[server["name"] + "/" + name] = True
        cursor = result.get("nextCursor")
        if not cursor:
            break
    expected = {"cao-sentinel/" + name for name in P2_TOOLS}
    if set(tools) != expected:
        raise RuntimeError("MCP inventory differs from the approved four tools")
    return sorted(tools)


def main(binary, args):
    if args[: len(P2_ARGS)] != P2_ARGS:
        raise RuntimeError("P2 launch arguments do not match reviewed policy")
    # Superset may append only model/effort and a single argv prompt.
    tail = args[len(P2_ARGS) :]
    options = []
    while tail and tail[0] in ("--model", "-c"):
        if len(tail) < 2 or (
            tail[0] == "-c"
            and tail[1]
            not in {"model_reasoning_effort=" + v for v in ("low", "medium", "high")}
        ):
            raise RuntimeError("Unapproved runtime override")
        options += tail[:2]
        tail = tail[2:]
    if tail[:1] == ["--"]:
        tail = tail[1:]
    if len(tail) != 1:
        raise RuntimeError("Expected exactly one task prompt")
    model = (
        options[options.index("--model") + 1] if "--model" in options else "gpt-6-luna"
    )
    audit(binary, P2_ARGS, os.getcwd(), execution_environment(), model)
    probe = Probe(binary, P2_ARGS + options, os.getcwd())
    try:
        inspect_tools(probe, os.getcwd())
    finally:
        probe.close()
    print(
        "P2 MCP preflight passed: four report tools; plugins/apps/web disabled",
        flush=True,
    )
    os.execve(binary, [binary, *args], execution_environment())


if __name__ == "__main__":
    try:
        # A private deployment file selects the actual CLI, never supplied by Muse.
        binary = json.loads(Path(__file__).with_name("p2-runtime.json").read_text())[
            "binary"
        ]
        main(binary, sys.argv[1:])
    except Exception:
        raise SystemExit("P2 tool preflight failed; no Codex task dispatched") from None
