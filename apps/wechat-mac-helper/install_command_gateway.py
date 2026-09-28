"""Install the owner-only WeChat command listener as a macOS LaunchAgent."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.aidev.wechat-command-gateway"


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("This installer only supports macOS")
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[1]
    state_root = Path.home() / "Library/Application Support/AI Dev Management"
    logs = state_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    os.chmod(state_root, 0o700)
    python = state_root / "wechat-helper-venv/bin/python"
    if not python.is_file():
        python = Path(sys.executable)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-u", str(script_dir / "command_gateway.py")],
        "WorkingDirectory": str(repo_root),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(logs / "wechat-command-gateway.out.log"),
        "StandardErrorPath": str(logs / "wechat-command-gateway.err.log"),
        "ThrottleInterval": 10,
    }
    launch_agents = Path.home() / "Library/LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    path = launch_agents / f"{LABEL}.plist"
    with path.open("wb") as stream:
        plistlib.dump(plist, stream, sort_keys=False)
    os.chmod(path, 0o600)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(path)], check=False, capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    print(f"Installed {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
