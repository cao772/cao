import mcp_server


def test_mcp_server_imports_with_streamable_http_sdk():
    assert mcp_server.mcp is not None
    assert mcp_server.MCP_PORT > 0
