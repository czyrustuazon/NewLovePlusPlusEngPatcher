#!/usr/bin/env python3
"""Merge Gemini dialogue line by line, because git cannot merge a .dbin2.

Takes a line from THEIRS only when the working tree still has the BASE text,
so edits on this branch survive. Covers the dbin2 packs, the XML, and the
phrase map. A line both sides changed keeps this branch's text and is reported.

During a conflicted merge, take this branch's copies first, then run it:

  git checkout --ours -- assets/gemini_heroines
  python tools/merge_gemini_lines.py --base $(git merge-base HEAD MERGE_HEAD) --theirs MERGE_HEAD
  python tools/merge_gemini_lines.py --base ... --theirs MERGE_HEAD --apply
  git add assets/gemini_heroines

Dry-run is the default. Exits 1 when something needs a person.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
for folder in (SRC, TOOLS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from patch_names import parse_dbin2  # noqa: E402
from restore_dialog_endings import DIALOG_RE, _norm, _write_dbin, _write_xml  # noqa: E402
from sync_workbench import _replace_map_value  # noqa: E402

GEMINI = "assets/gemini_heroines"


def blob(rev: str, rel: str) -> bytes | None:
    done = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=ROOT, capture_output=True)
    return done.stdout if done.returncode == 0 else None


def tracked(rev: str, folder: str) -> list[str]:
    done = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", rev, folder],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return done.stdout.split()


def lines_of(rel: str, raw: bytes | None) -> list[str] | None:
    if raw is None:
        return None
    if rel.endswith(".xml"):
        return [_norm(hit) for hit in DIALOG_RE.findall(raw.decode("utf-8"))]
    return [dialog for entry in parse_dbin2(raw)[2] for dialog in entry.sdl2.dialogs]


def merge_lines(
    base: list[str], theirs: list[str], ours: list[str]
) -> tuple[list[str], int, int]:
    """Merged lines, how many came from theirs, and how many both sides changed."""
    merged: list[str] = []
    taken = conflicts = 0
    for old, new, mine in zip(base, theirs, ours):
        if mine == old and new != old:
            merged.append(new)
            taken += 1
            continue
        merged.append(mine)
        if new not in (old, mine) and mine != old:
            conflicts += 1
    return merged, taken, conflicts


def merge_file(rel: str, base_rev: str, theirs_rev: str, *, apply: bool) -> tuple[int, str | None]:
    path = ROOT / rel
    ours_raw = path.read_bytes() if path.is_file() else None
    base = lines_of(rel, blob(base_rev, rel))
    theirs = lines_of(rel, blob(theirs_rev, rel))
    ours = lines_of(rel, ours_raw)
    if theirs == ours:
        return 0, None
    if base is None or ours is None or not len(base) == len(theirs) == len(ours):
        return 0, "line count differs, or a side lacks this file"
    merged, taken, conflicts = merge_lines(base, theirs, ours)
    if apply and taken:
        (_write_xml if rel.endswith(".xml") else _write_dbin)(path, merged)
    return taken, f"{conflicts} line(s) changed on both sides" if conflicts else None


def merge_map(base_rev: str, theirs_rev: str, *, apply: bool) -> tuple[int, list[str]]:
    rel = f"{GEMINI}/translations.json"
    path = ROOT / rel
    text = path.read_text(encoding="utf-8", newline="")
    ours = json.loads(text)["translations"]
    base = json.loads(blob(base_rev, rel))["translations"]
    theirs = json.loads(blob(theirs_rev, rel))["translations"]
    taken = 0
    problems: list[str] = []
    for key, new in theirs.items():
        mine, old = ours.get(key), base.get(key)
        if new in (mine, old):
            continue
        spliced = _replace_map_value(text, key, mine, new) if mine == old else None
        if spliced is None:
            problems.append(f"phrase map {key!r}: kept {mine!r} over {new!r}")
            continue
        text = spliced
        taken += 1
    if apply:
        path.write_text(text, encoding="utf-8", newline="")
    return taken, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", required=True, help="merge base")
    parser.add_argument("--theirs", required=True, help="the side being merged in")
    parser.add_argument("--apply", action="store_true", help="write the merged lines")
    args = parser.parse_args(argv)

    lines = changed = 0
    problems: list[str] = []
    for rel in tracked(args.theirs, f"{GEMINI}/dbin2") + tracked(args.theirs, f"{GEMINI}/xml"):
        taken, problem = merge_file(rel, args.base, args.theirs, apply=args.apply)
        lines += taken
        changed += 1 if taken else 0
        if problem:
            problems.append(f"{rel}: {problem}")
    keys, map_problems = merge_map(args.base, args.theirs, apply=args.apply)
    problems.extend(map_problems)

    mode = "took" if args.apply else "would take"
    print(f"[merge] {mode} {lines} line(s) in {changed} file(s) and {keys} phrase-map key(s)")
    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
