from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import venv
from pathlib import Path

LABEL = "com.aidev.wechat-project-collector"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, check=check, capture_output=not check)


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("This installer only supports macOS.")

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent
    home = Path.home()
    state_root = home / "Library" / "Application Support" / "AI Dev Management"
    state_root.mkdir(parents=True, exist_ok=True)
    os.chmod(state_root, 0o700)

    venv_root = state_root / "wechat-helper-venv"
    if not (venv_root / "bin" / "python").exists():
        venv.EnvBuilder(with_pip=True, clear=False).create(venv_root)

    python = venv_root / "bin" / "python"
    requirements = script_dir / "requirements.txt"
    run(str(python), "-m", "pip", "install", "--upgrade", "pip")
    run(str(python), "-m", "pip", "install", "-r", str(requirements))

    central_url = os.getenv("CENTRAL_URL", "http://127.0.0.1:8080").strip()
    collector_token = os.getenv("COLLECTOR_TOKEN", "").strip()
    user_id = os.getenv("USER_ID", os.getenv("USER", "developer")).strip()
    device_id = os.getenv("DEVICE_ID", "").strip()

    if not collector_token:
        print(
            "WARNING: COLLECTOR_TOKEN is empty. The helper will start locally, "
            "but Central uploads will fail until you reinstall with COLLECTOR_TOKEN set."
        )

    log_dir = state_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    env = {
        "PYTHONPATH": str(script_dir),
        "WECHAT_STATE_ROOT": str(state_root),
        "CENTRAL_URL": central_url,
        "COLLECTOR_TOKEN": collector_token,
        "USER_ID": user_id,
    }
    if device_id:
        env["DEVICE_ID"] = device_id

    plist = {
        "Label": LABEL,
        "ProgramArguments": [
            str(python),
            "-m",
            "uvicorn",
            "wechat_helper:app",
            "--host",
            "127.0.0.1",
            "--port",
            "6412",
        ],
        "WorkingDirectory": str(repo_root),
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(log_dir / "wechat-helper.out.log"),
        "StandardErrorPath": str(log_dir / "wechat-helper.err.log"),
        "ThrottleInterval": 10,
    }

    launch_agents = home / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / f"{LABEL}.plist"
    with plist_path.open("wb") as fh:
        plistlib.dump(plist, fh, sort_keys=False)
    os.chmod(plist_path, 0o600)

    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False)
    run("launchctl", "bootstrap", domain, str(plist_path))
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=False)

    print(f"Installed: {plist_path}")
    print("Local helper: http://127.0.0.1:6412/health")
    print("Schedule: local timezone, every 30 minutes from 09:00 through 20:00.")
    print(
        "Before enabling automatic WeChat reading, run the helper manually once from "
        "Terminal and grant the required macOS Accessibility permission, then use the "
        "read-only accessibility snapshot endpoint for calibration."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
