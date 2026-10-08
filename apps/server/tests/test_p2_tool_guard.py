import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[3] / "deployments/superset/p2_codex.py"
import sys

sys.path.insert(0, str(path.parent))
spec = importlib.util.spec_from_file_location("p2_codex_guard", path)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def safe_config():
    return {
        "mcp_servers": {
            "cao-sentinel": {
                "url": "http://127.0.0.1:6410/mcp",
                "enabled_tools": guard.P2_TOOLS,
                "default_tools_approval_mode": "approve",
            }
        },
        "features": {
            key: False
            for key in (
                "plugins",
                "remote_plugin",
                "apps",
                "multi_agent",
                "multi_agent_v2",
            )
        },
        "web_search": "disabled",
        "agents": {"enabled": False},
    }


@pytest.mark.parametrize(
    "change",
    [
        "new_server",
        "extra_tool",
        "plugins",
        "apps",
        "remote_plugin",
        "multi_agent",
        "endpoint",
        "web",
    ],
)
def test_guard_fails_closed_for_unapproved_capability(change):
    config = safe_config()
    if change == "new_server":
        config["mcp_servers"]["newly-installed"] = {"url": "http://unapproved.invalid"}
    elif change == "extra_tool":
        config["mcp_servers"]["cao-sentinel"]["enabled_tools"] = [
            *guard.P2_TOOLS,
            "business_write",
        ]
    elif change == "endpoint":
        config["mcp_servers"]["cao-sentinel"]["url"] = "http://unapproved.invalid"
    elif change == "web":
        config["web_search"] = "live"
    else:
        config["features"][change] = True
    with pytest.raises(RuntimeError):
        guard.validate_config(config)


def test_inventory_pagination_must_match_all_four_tools():
    class Probe:
        def rpc(self, method, params):
            if method == "config/read":
                return {"config": safe_config()}
            if not params.get("cursor"):
                return {
                    "data": [
                        {
                            "name": "cao-sentinel",
                            "tools": dict.fromkeys(guard.P2_TOOLS[:2]),
                        }
                    ],
                    "nextCursor": "next",
                }
            return {
                "data": [
                    {"name": "cao-sentinel", "tools": dict.fromkeys(guard.P2_TOOLS[2:])}
                ],
                "nextCursor": None,
            }

    assert len(guard.inspect_tools(Probe(), "/test")) == 4


def test_effective_config_rejected_before_any_server_start():
    class Probe:
        def rpc(self, method, params):
            assert method == "config/read"
            config = safe_config()
            config["mcp_servers"]["unknown"] = {}
            return {"config": config}

    with pytest.raises(RuntimeError):
        guard.inspect_tools(Probe(), "/test")


def test_parent_desktop_overrides_are_not_inherited(monkeypatch):
    monkeypatch.setenv("CODEX_PERMISSION_PROFILE", "disabled")
    monkeypatch.setenv("CODEX_THREAD_ID", "parent")
    monkeypatch.setenv("CODEX_API_KEY", "private-test-value")
    env = guard.execution_environment()
    assert (
        not {"CODEX_PERMISSION_PROFILE", "CODEX_THREAD_ID", "CODEX_API_KEY"}
        & env.keys()
    )


@pytest.mark.parametrize(
    "name", ["spawn_agent", "send_message", "browser", "new_unapproved_tool"]
)
def test_builtin_inventory_detects_unapproved_tools(name):
    from p2_builtin_audit import ALLOWED, tool_names

    payload = {"input": [{"type": "additional_tools", "tools": [{"name": name}]}]}
    assert not tool_names(payload) <= ALLOWED


def test_nested_code_mode_tools_are_included_in_inventory():
    from p2_builtin_audit import tool_names

    assert "spawn_agent" in tool_names(
        {"tools": [{"name": "exec", "description": "### `spawn_agent`\nNested tool."}]}
    )
