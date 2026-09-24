from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.aidev.wechat-project-collector"


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("This uninstaller only supports macOS.")
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False)
    if plist_path.exists():
        plist_path.unlink()
    print("Removed LaunchAgent. Local configuration and message dedupe state were kept.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
