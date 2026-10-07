#!/usr/bin/env python3
"""Check a built name_input_code.bin against the reviewed snapshot.

tests/snapshots/code_patch_map.json records the vanilla code.bin hash and the
hash the gold stack produces from it. The gold runner calls this after the
bake, before publishing, so only reviewed code.bin output ships.

  python tools/verify_name_input_code.py
  python tools/verify_name_input_code.py --code release/name_input_code.bin --vanilla /opt/nlpp/vanilla/exefs/code.bin
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests" / "snapshots" / "code_patch_map.json"
DEFAULT_CODE = ROOT / "release" / "name_input_code.bin"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(code: Path, vanilla: Path | None, snapshot: Path = SNAPSHOT) -> list[str]:
    """Return a list of problems (empty when the build matches)."""
    want = json.loads(snapshot.read_text(encoding="utf-8"))
    problems = []
    if vanilla is not None:
        got_vanilla = sha256_file(vanilla)
        if got_vanilla != want["vanilla_sha256"]:
            problems.append(
                f"vanilla {vanilla} is {got_vanilla}, snapshot expects "
                f"{want['vanilla_sha256']} (wrong dump, or an already-patched code.bin)"
            )
    if not code.is_file():
        problems.append(f"missing {code}")
        return problems
    got = sha256_file(code)
    if got != want["final_sha256"]:
        problems.append(
            f"{code.name} is {got}, snapshot expects {want['final_sha256']}. "
            "The patch output changed without a snapshot update: run "
            "tests/test_code_patch_map.py with a vanilla code.bin."
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--code", type=Path, default=DEFAULT_CODE)
    ap.add_argument(
        "--vanilla",
        type=Path,
        default=Path(os.environ["NLPP_VANILLA_CODE"]) if os.environ.get("NLPP_VANILLA_CODE") else None,
        help="vanilla code.bin to check too (default: NLPP_VANILLA_CODE)",
    )
    args = ap.parse_args(argv)
    problems = verify(args.code, args.vanilla)
    for p in problems:
        print(f"[verify] {p}", file=sys.stderr)
    if problems:
        return 1
    print(f"[verify] {args.code.name} matches the reviewed snapshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
