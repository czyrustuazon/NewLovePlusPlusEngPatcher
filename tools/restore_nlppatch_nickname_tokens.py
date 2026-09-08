#!/usr/bin/env python3
"""Restore nickname tokens in vendored NLPPPATCH ``.dbin2`` scripts.

Compares each NLPPPATCH English script against Makein ``NLPP_scripts-Done``.
When a dialog line differs only by heroine/player tokens vs plain English names,
copies the Makein line (with ``▲小早川＊▲`` / ``▲姉ヶ崎＊▲`` / ``▲高嶺＊＊▲`` / etc.)
into the ``.dbin2``.

This fixes the ~28% Rinko/Nene/common layer in vendored NLPPATCH ``.dbin2``.
Re-deploy LayeredFS after running.

  python tools/restore_nlppatch_nickname_tokens.py --dry-run
  python tools/restore_nlppatch_nickname_tokens.py
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "tools"))

from patch_names import build_dbin2, parse_dbin2  # noqa: E402
from restore_nickname_tokens import (  # noqa: E402
    DEFAULT_CACHE,
    _HERO_TOKENS,
    fetch_makein,
    normalize_hero_refs,
)

DEFAULT_NLPP = (
    ROOT / "vendor" / "NLPPPATCH" / "release" / "romfs" / "script" / "bin" / "script"
)


@dataclass
class FileStats:
    stem: str
    dialogs: int
    restored: int
    skipped_count_mismatch: bool = False


def xml_dialogs(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [(el.text or "") for el in root.iter("Dialog")]


def dbin_dialogs(path: Path) -> list[str]:
    _, _, entries = parse_dbin2(path.read_bytes())
    return [d for entry in entries for d in entry.sdl2.dialogs]


def write_dbin_dialogs(path: Path, dialogs: list[str]) -> None:
    key, unknown, entries = parse_dbin2(path.read_bytes())
    idx = 0
    for entry in entries:
        for i in range(len(entry.sdl2.dialogs)):
            entry.sdl2.dialogs[i] = dialogs[idx]
            idx += 1
    path.write_bytes(build_dbin2(key, unknown, entries))


def needs_token_restore(makein: str, eng: str) -> bool:
    if makein == eng:
        return False
    if normalize_hero_refs(makein) != normalize_hero_refs(eng):
        return False
    for tok in _HERO_TOKENS:
        if tok in makein and tok not in eng:
            return True
    return False


def restore_dbin_file(
    dbin_path: Path,
    makein_path: Path,
    *,
    dry_run: bool,
) -> FileStats:
    mk = xml_dialogs(makein_path)
    eng = dbin_dialogs(dbin_path)
    stats = FileStats(dbin_path.stem, len(eng), 0)
    if len(mk) != len(eng):
        stats.skipped_count_mismatch = True
        return stats
    out = list(eng)
    for i, (m, e) in enumerate(zip(mk, eng)):
        if needs_token_restore(m, e):
            out[i] = m
            stats.restored += 1
    if stats.restored and not dry_run:
        write_dbin_dialogs(dbin_path, out)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=DEFAULT_NLPP)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--glob", default="*.dbin2")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    src = args.src.resolve()
    if not src.is_dir():
        raise SystemExit(f"NLPPPATCH scripts missing: {src}")

    results: list[FileStats] = []
    missing: list[str] = []
    mismatched: list[str] = []

    for dbin_path in sorted(src.glob(args.glob)):
        mk_path = fetch_makein(dbin_path.stem, args.cache.resolve())
        if mk_path is None:
            missing.append(dbin_path.stem)
            continue
        stats = restore_dbin_file(dbin_path, mk_path, dry_run=args.dry_run)
        if stats.skipped_count_mismatch:
            mismatched.append(dbin_path.stem)
            continue
        if stats.restored:
            results.append(stats)

    total = sum(s.restored for s in results)
    print(
        f"[nlppatch] {'would update' if args.dry_run else 'updated'} "
        f"{len(results)} files, {total} dialog lines"
    )
    if missing:
        print(f"[nlppatch] skipped {len(missing)} (no Makein ref)")
    if mismatched:
        print(f"[nlppatch] dialog-count mismatch: {len(mismatched)}")
    for s in sorted(results, key=lambda x: -x.restored)[:15]:
        print(f"  {s.stem}: {s.restored} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
