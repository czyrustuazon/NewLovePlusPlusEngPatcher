#!/usr/bin/env python3
"""Run the GitHub Test workflow's checks locally, the way CI sees the repo.

Clones HEAD into a temp dir, so untracked files, cache/, extracted/ and other
game dumps are absent, and clears NLPP_* / Azahar paths. Then runs the same
steps as .github/workflows/test.yml. Coverage numbers then match CI except
for platform branches (SLACK in dev/check_coverage.py).

  python dev/ci_local.py                 # check HEAD (commit first)
  python dev/ci_local.py --update-floors # raise floors from CI-equivalent numbers
  python dev/ci_local.py --keep          # leave the clone for a look
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOOR_FILE = Path("tests") / "snapshots" / "coverage_floor.json"

# Same order and arguments as .github/workflows/test.yml.
STEPS = [
    ("Lint (ruff hard errors)", ["-m", "ruff", "check", "--select", "E9,F63,F7,F82", "src", "tools", "tests"]),
    ("Run unit tests (with coverage)", ["-m", "coverage", "run", "-m", "pytest", "tests/", "-q", "-rs", "-m", "not local_data"]),
    ("Run local-data tests (skip without vanilla dumps)", ["-m", "pytest", "tests/", "-q", "-rs", "-m", "local_data"]),
    ("Coverage report", ["-m", "coverage", "report", "--skip-covered", "--sort=cover"]),
    ("Coverage ratchet", ["dev/check_coverage.py"]),
]


def clean_env(tmp: Path) -> dict[str, str]:
    """No env overrides pointing at game dumps, the Azahar fork or user dir."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NLPP_", "AZAHAR_"))}
    env["APPDATA"] = str(tmp / "appdata")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def clone_head(dest: Path) -> str:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(
        ["git", "clone", "--quiet", "--no-checkout", "--depth", "1", ROOT.as_uri(), str(dest)],
        check=True,
    )
    subprocess.run(["git", "-c", "advice.detachedHead=false", "checkout", "--quiet", sha], cwd=dest, check=True)
    return sha


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update-floors", action="store_true", help="copy raised floors back into this checkout")
    ap.add_argument("--keep", action="store_true", help="keep the temp clone")
    args = ap.parse_args(argv)

    if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        print("[ci-local] note: uncommitted changes are not checked; this runs HEAD only")

    tmp = Path(tempfile.mkdtemp(prefix="nlpp-ci-"))
    repo = tmp / "repo"
    try:
        sha = clone_head(repo)
        print(f"[ci-local] checking {sha[:7]} in {repo}")
        env = clean_env(tmp)
        for name, cmd in STEPS:
            if args.update_floors and name == "Coverage ratchet":
                cmd = [*cmd, "--update"]
            print(f"[ci-local] {name}", flush=True)
            if subprocess.run([sys.executable, *cmd], cwd=repo, env=env).returncode:
                print(f"[ci-local] FAILED: {name}")
                return 1
        if args.update_floors:
            shutil.copyfile(repo / FLOOR_FILE, ROOT / FLOOR_FILE)
            print(f"[ci-local] wrote {FLOOR_FILE}; review and commit it")
        print("[ci-local] all CI checks passed")
        return 0
    finally:
        if args.keep:
            print(f"[ci-local] kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
