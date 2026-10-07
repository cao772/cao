#!/usr/bin/env python3
"""Launch a locally built Superset Host with an isolated state directory."""
import argparse
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=Path(".local/superset-host"))
    args = parser.parse_args()
    source, state = args.source.resolve(), args.state.resolve()
    binary = next(source.glob("node_modules/.bun/electron@*/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"), None)
    entry = source / "packages/host-service/dist/host-service.js"
    daemon = source / "apps/desktop/dist/main/pty-daemon.js"
    if not binary or not entry.is_file() or not daemon.is_file():
        parser.error("先构建 Superset Host 和 Desktop 的原生运行资源；见 docs/M9-local-superset.md")
    state.mkdir(parents=True, exist_ok=True)
    config = state / "config.json"
    if not config.exists():
        value = {"organization_id": str(uuid4()), "token": secrets.token_urlsafe(32),
                 "port": 4879, "url": "http://127.0.0.1:4879", "bindings": []}
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(value, file, indent=2)
    value = json.loads(config.read_text())
    env = dict(os.environ)
    for name in ("RELAY_URL", "HOST_SERVICE_SENTRY_DSN", "SUPERSET_AUTH_CONFIG_PATH"):
        env.pop(name, None)
    env.update(
        ELECTRON_RUN_AS_NODE="1", AUTH_TOKEN="local-development-only",
        SUPERSET_API_URL="http://127.0.0.1:3001",
        HOST_SERVICE_SECRET=value["token"], ORGANIZATION_ID=value["organization_id"],
        HOST_DB_PATH=str(state / "host.db"), PORT=str(value["port"]),
        HOST_MIGRATIONS_FOLDER=str(source / "packages/host-service/drizzle"),
        SUPERSET_HOME_DIR=str(state / "home"), SUPERSET_ENV="development",
        SUPERSET_AGENT_TEMPLATES_DIR=str(source / "packages/agent-setup/templates"),
        SUPERSET_PTY_DAEMON_SCRIPT_PATH=str(daemon),
    )
    os.execve(str(binary), [str(binary), str(entry)], env)


if __name__ == "__main__":
    main()
