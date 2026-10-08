"""Audit model-visible builtins against a loopback-only mock Responses endpoint.

No model inference and no payload persistence: retain tool names only. CLI changes
that introduce any unknown tool fail closed until the inventory is reviewed.
"""

import gzip
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import threading

ALLOWED = {
    "functions",
    "exec",
    "wait",
    "request_user_input",
    "request_user_input_async",
    "clock",
    "sleep",
    "clock__curr_time",
    "apply_patch",
    "create_goal",
    "exec_command",
    "get_goal",
    "list_mcp_resource_templates",
    "list_mcp_resources",
    "read_mcp_resource",
    "update_goal",
    "view_image",
    "write_stdin",
}


def tool_names(payload):
    names = set()

    def visit(value):
        if isinstance(value, dict):
            for key, data in value.items():
                if key == "tools" and isinstance(data, list):
                    for tool in data:
                        names.add(tool.get("name", tool.get("type", "unknown")))
                        names.update(
                            re.findall(
                                r"### `([A-Za-z0-9_]+)`", tool.get("description", "")
                            )
                        )
                visit(data)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return names


def audit(binary, args, cwd, env, model="gpt-6-luna"):
    names = set()
    errors = []
    cache = (
        Path(env.get("CODEX_HOME", str(Path.home() / ".codex"))) / "models_cache.json"
    )
    models = json.loads(cache.read_text())["models"]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"models": models}).encode())

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8 * 1024 * 1024:
                    raise ValueError("Invalid audit request size")
                raw = self.rfile.read(size)
                encoding = self.headers.get("Content-Encoding")
                if encoding == "gzip":
                    raw = gzip.decompress(raw)
                elif encoding:
                    raise ValueError("Unsupported audit compression")
                names.update(tool_names(json.loads(raw)))
            except Exception:
                errors.append("inventory unavailable")
            self.send_response(400)
            self.end_headers()
            self.wfile.write(
                b'{"error":{"message":"P2 local inventory audit completed"}}'
            )

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        # exec does not accept the global approval/no-daemon flags.
        filtered = [arg for i, arg in enumerate(args) if i not in (0, 3, 4)]
        provider = (
            'model_providers.p2-inventory={name="P2 local inventory",base_url="http://127.0.0.1:'
            + str(server.server_port)
            + '",wire_api="responses",requires_openai_auth=false}'
        )
        audit_env = {
            k: v
            for k, v in env.items()
            if not k.endswith("API_KEY") and k not in {"OPENAI_BASE_URL"}
        }
        subprocess.run(
            [
                binary,
                "--no-daemon",
                "--ask-for-approval",
                "never",
                "exec",
                *filtered,
                "-c",
                'model_provider="p2-inventory"',
                "-c",
                provider,
                "-c",
                "features.enable_request_compression=false",
                "--json",
                "--model",
                model,
                "Local tool inventory audit only. Do not perform any task.",
            ],
            cwd=cwd,
            env=audit_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    if errors or not {"exec", "wait"} <= names or not names <= ALLOWED:
        raise RuntimeError("Builtin tools differ from reviewed inventory")
    return sorted(names)
