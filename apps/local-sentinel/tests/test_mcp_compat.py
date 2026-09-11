import mcp_server


def test_legacy_mcp_tools_remain_callable():
    for name in (
        "list_projects",
        "get_context",
        "get_tasks",
        "report_task_started",
        "report_task_progress",
        "report_test_result",
        "report_blocker",
        "report_task_finished",
    ):
        assert callable(getattr(mcp_server, name))


def test_optional_agent_session_tools_are_available():
    for name in (
        "report_session_started",
        "report_session_finished",
        "report_files_changed",
        "report_commit",
    ):
        assert callable(getattr(mcp_server, name))
