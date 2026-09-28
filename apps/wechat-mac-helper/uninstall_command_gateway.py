"""Stop the WeChat command listener without deleting its local queue."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

LABEL = "com.aidev.wechat-command-gateway"


def main() -> int:
    path = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], check=False)
    path.unlink(missing_ok=True)
    print(f"Removed {path}; local command queue retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
