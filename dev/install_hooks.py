#!/usr/bin/env python3
"""Copy dev/hooks/* into .git/hooks (other hooks there are left alone).

  python dev/install_hooks.py          # skip hooks that differ locally
  python dev/install_hooks.py --force  # overwrite them
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dev" / "hooks"


def git_hooks_dir() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return (ROOT / out).resolve()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    dest_dir = git_hooks_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(HOOKS.iterdir()):
        dest = dest_dir / src.name
        if dest.is_file() and dest.read_bytes() != src.read_bytes() and not args.force:
            print(f"[hooks] skip {src.name}: local copy differs (use --force)")
            continue
        shutil.copyfile(src, dest)
        dest.chmod(0o755)
        print(f"[hooks] installed {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
