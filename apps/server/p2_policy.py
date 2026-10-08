"""Reviewed unattended execution profile for this local deployment."""

P2_TOOLS = [
    "report_task_started",
    "report_task_progress",
    "report_test_result",
    "report_task_finished",
]
P2_ARGS = [
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
# Explicitly disable the installed plugins in this deployment. Re-probe a changed
# account configuration; no browser/native-app or app-task automation in P2.
P2_DISABLED_PLUGINS = [
    "documents@openai-primary-runtime",
    "presentations@openai-primary-runtime",
    "spreadsheets@openai-primary-runtime",
    "pdf@openai-primary-runtime",
    "template-creator@openai-primary-runtime",
    "visualize@openai-bundled",
    "codex-app-tools@openai-bundled",
    "browser@openai-bundled",
    "unified-computer-use@openai-bundled",
    "chrome@openai-bundled",
    "computer-use@openai-bundled",
    "code-review@openai-bundled",
]
for plugin in P2_DISABLED_PLUGINS:
    P2_ARGS.extend(["-c", f'plugins."{plugin}".enabled=false'])
