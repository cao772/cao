"""Reviewed unattended execution profile for this local deployment."""

P2_TOOLS = [
    "report_task_started",
    "report_task_progress",
    "report_test_result",
    "report_task_finished",
]
P2_ARGS = [
    "--no-daemon",
    "--sandbox",
    "workspace-write",
    "--ask-for-approval",
    "never",
    "-c",
    "sandbox_workspace_write.network_access=false",
    "-c",
    "sandbox_workspace_write.writable_roots=[]",
    "-c",
    'mcp_servers.cao-sentinel.default_tools_approval_mode="approve"',
    "-c",
    'mcp_servers.cao-sentinel.enabled_tools=["report_task_started","report_task_progress","report_test_result","report_task_finished"]',
    "-c",
    "mcp_servers.node_repl.enabled=false",
    "-c",
    "mcp_servers.computer-use.enabled=false",
    "-c",
    "apps._default.enabled=false",
]
# Disable whole tool sources, including plugins installed after this deployment.
P2_ARGS += [
    "-c",
    "features.plugins=false",
    "-c",
    "features.remote_plugin=false",
    "-c",
    "features.apps=false",
    "-c",
    "features.multi_agent=false",
    "-c",
    "features.multi_agent_v2=false",
    "-c",
    "agents.enabled=false",
    "-c",
    'web_search="disabled"',
]
