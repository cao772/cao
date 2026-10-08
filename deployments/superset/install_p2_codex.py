"""Install a dedicated guarded launcher; leaves the user's Codex config intact."""

import argparse
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    if not args.binary.resolve().is_file():
        raise SystemExit("Codex CLI binary is missing")
    directory = args.destination.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = Path(__file__).resolve()
    launcher = directory / "codex"
    launcher.write_text(
        "#!/usr/bin/env python3\n" + source.with_name("p2_codex.py").read_text()
    )
    launcher.chmod(0o700)
    shutil.copyfile(
        source.parents[2] / "apps/server/p2_policy.py", directory / "p2_policy.py"
    )
    shutil.copyfile(
        source.with_name("p2_builtin_audit.py"), directory / "p2_builtin_audit.py"
    )
    runtime = directory / "p2-runtime.json"
    runtime.write_text(json.dumps({"binary": str(args.binary.resolve())}))
    runtime.chmod(0o600)
    print(
        "P2 guarded launcher installed; configure its absolute path as p2_guarded_command and the dedicated preset command"
    )


if __name__ == "__main__":
    main()
