"""Apply the reviewed optional Host guard; never reset upstream changes."""

import argparse
import subprocess
from pathlib import Path

REVISION = "9a50076c324b3d2575762e5bdcba6838061c8be5"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    if revision != REVISION:
        raise SystemExit("Unsupported source revision; no files changed")
    patch = Path(__file__).with_name("p2-guard.patch").resolve()
    target = source / "packages/host-service/src/trpc/router/terminal/terminal.ts"
    if "p2Capabilities:" in target.read_text():
        subprocess.run(
            ["git", "apply", "--reverse", "--check", str(patch)], cwd=source, check=True
        )
        print("Reviewed P2 guard already installed")
        return
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=source, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=source, check=True)
    print("P2 guard installed; rebuild/restart your local Host before enabling P2")


if __name__ == "__main__":
    main()
