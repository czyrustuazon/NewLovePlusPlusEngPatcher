#!/usr/bin/env python3
"""Refuse a push when a merge threw away one side's dialogue.

Git cannot merge a .dbin2, so a conflicted merge tempts "keep ours" on the
whole folder. That passes every test and silently reverts translation work
(merge 1bd0b64 lost 164 lines this way). This check replays each merge being
pushed. A dialogue file that conflicted, or that git would have merged
differently, and that ended up as one side's exact copy, lost the other side.

Fix a flagged merge with tools/merge_gemini_lines.py, then list its full hash
in REPAIRED. Bypass once, after checking by hand: git push --no-verify

  python dev/check_merges.py                   # merges not on origin/main
  python dev/check_merges.py --upstream REV
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DIALOGUE = (
    "assets/gemini_heroines",
    "assets/script_contrib",
    "assets/scripts",
    "rebuild_dbin2",
)

# Flagged merges whose dropped text was restored by a later commit.
REPAIRED = {"1bd0b64db19014e15fe402940a9d8acebd1f3686"}


def git(*args: str, check: bool = True) -> str:
    done = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=check
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def tree(rev: str) -> dict[str, str]:
    """Dialogue paths at ``rev``, mapped to their blob ids."""
    out: dict[str, str] = {}
    for row in git("ls-tree", "-r", "-z", rev, "--", *DIALOGUE).split("\0"):
        if row:
            meta, path = row.split("\t", 1)
            out[path] = meta.split()[2]
    return out


def replay(first: str, second: str) -> tuple[str, set[str]]:
    """The tree git would write for this merge, and the paths that conflicted."""
    done = subprocess.run(
        ["git", "merge-tree", "--write-tree", "--name-only", "--no-messages", first, second],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    rows = done.stdout.split("\n")
    return rows[0], {row for row in rows[1:] if row}


def check_merge(merge: str) -> list[str]:
    parents = git("rev-parse", f"{merge}^@").split()
    if len(parents) != 2 or merge in REPAIRED:
        return []
    first, second = parents
    auto, conflicted = replay(first, second)
    if not auto:  # unrelated histories: no merge base to replay
        return []
    result, one, two, replayed = tree(merge), tree(first), tree(second), tree(auto)
    return [
        path
        for path in sorted(set(one) | set(two))
        if one.get(path) != two.get(path)
        and result.get(path) in (one.get(path), two.get(path))
        and (path in conflicted or result.get(path) != replayed.get(path))
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", default="origin/main")
    args = ap.parse_args(argv)
    if not git("rev-parse", "--verify", "--quiet", args.upstream, check=False):
        print(f"[merges] {args.upstream} not found; skipped")
        return 0
    merges = git("rev-list", "--merges", f"{args.upstream}..HEAD").split()
    failed = 0
    for merge in merges:
        paths = check_merge(merge)
        if not paths:
            continue
        failed += 1
        print(f"[merges] {merge[:7]} dropped one side of {len(paths)} dialogue file(s):")
        for path in paths[:10]:
            print(f"  {path}")
        if len(paths) > 10:
            print(f"  ... {len(paths) - 10} more")
    if failed:
        print("[merges] Restore them with tools/merge_gemini_lines.py. See dev/check_merges.py.")
        return 1
    print(f"[merges] {len(merges)} merge(s) kept both sides")
    return 0


if __name__ == "__main__":
    sys.exit(main())
