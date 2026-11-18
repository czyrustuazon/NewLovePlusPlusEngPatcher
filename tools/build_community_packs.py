#!/usr/bin/env python3
"""Community Nene / Rinko English for the ``NLP_01`` / ``NLP_02`` script packs.

The game reads each script from one of three packs (``NLP_01``, ``NLP_02``,
``script``; FUN_006ee890 picks it from a per-session byte). The community
``a*`` / ``k*`` English in ``rebuild_dbin2/script`` only ever covered the
``script`` pack, so the same scenes in the other two packs stayed Japanese.

Each pack has its own copy of a stem: the same Japanese lines in the same
order (the packs differ in line breaks, a few typo-level edits, and their file
keys), sometimes with entries missing at the end. This writes
``rebuild_dbin2/<pack>/<stem>.dbin2``: the pack's own vanilla file with each
dialog replaced by the English line at the same entry and dialog index.

A stem is only written for a pack when every line lines up: the pack has no
more entries than ``script``, every entry has the same dialog count, and each
pack line matches the ``script`` Japanese once line breaks are ignored, or
at least ``MIN_RATIO`` alike (typo-level variants; a different sentence or
different choice text fails). Anything else is left out and listed, so the
pack keeps its Japanese or Gemini file.

  python tools/build_community_packs.py
  python tools/build_community_packs.py --check   # report only
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import script_inject
from patch_names import DbinEntry, SDL2Data, build_dbin2, parse_dbin2

DBIN = ROOT / "rebuild_dbin2"
VANILLA_BIN = ROOT / "cache" / "vanilla_from_rom" / "romfs" / "script" / "bin"
PACKS = ("NLP_01", "NLP_02")
MIN_RATIO = 0.75


def _norm(text: str) -> str:
    return text.replace("\n", "").replace("　", "")


def misaligned(jp_script: list[DbinEntry], jp_pack: list[DbinEntry]) -> str:
    """Why ``jp_pack`` does not line up with ``jp_script`` ('' when it does)."""
    if len(jp_pack) > len(jp_script):
        return f"{len(jp_pack)} entries, script has {len(jp_script)}"
    for i, (s, p) in enumerate(zip(jp_script, jp_pack)):
        if len(s.sdl2.dialogs) != len(p.sdl2.dialogs):
            return f"entry {i}: {len(p.sdl2.dialogs)} dialogs, script has {len(s.sdl2.dialogs)}"
        for j, (a, b) in enumerate(zip(s.sdl2.dialogs, p.sdl2.dialogs)):
            a, b = _norm(a), _norm(b)
            if a != b and difflib.SequenceMatcher(None, a, b).ratio() < MIN_RATIO:
                return f"entry {i} dialog {j}: {b!r} is not {a!r}"
    return ""


def map_pack(english: bytes, jp_script: bytes, jp_pack: bytes) -> tuple[bytes | None, str]:
    """``(pack file with the English dialogs, '')`` or ``(None, reason)``."""
    _ek, _eu, en = parse_dbin2(english)
    _sk, _su, js = parse_dbin2(jp_script)
    key, unknown, jp = parse_dbin2(jp_pack)
    if [len(e.sdl2.dialogs) for e in en] != [len(e.sdl2.dialogs) for e in js]:
        return None, "English does not match the script pack's shape"
    why = misaligned(js, jp)
    if why:
        return None, why
    out = [
        DbinEntry(p.unknown0, p.unknown1, SDL2Data(p.sdl2.key, p.sdl2.unknown, list(e.sdl2.dialogs)))
        for p, e in zip(jp, en)
    ]
    return build_dbin2(key, unknown, out), ""


def community_english(dbin: Path) -> list[str]:
    """Community a*/k* stems with English in ``dbin/script``."""
    allow = script_inject.community_stems()
    return sorted(
        p.stem
        for p in (dbin / "script").glob("*.dbin2")
        if script_inject.script_prefix(p.stem) in script_inject.COMMUNITY_PREFIXES
        and (not allow or p.stem in allow)
    )


def build(dbin: Path, vanilla: Path, *, write: bool) -> tuple[int, list[str]]:
    """Write (or with ``write=False`` only check) every pack file. Returns
    ``(files written or writable, skipped "pack/stem: reason" lines)``."""
    done, skipped = 0, []
    for stem in community_english(dbin):
        english = (dbin / "script" / f"{stem}.dbin2").read_bytes()
        jp_script = (vanilla / "script" / f"{stem}.dbin2").read_bytes()
        for pack in PACKS:
            src = vanilla / pack / f"{stem}.dbin2"
            if not src.is_file():
                continue
            mapped, why = map_pack(english, jp_script, src.read_bytes())
            if mapped is None:
                skipped.append(f"{pack}/{stem}: {why}")
                continue
            if write:
                dest = dbin / pack / f"{stem}.dbin2"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(mapped)
            done += 1
    return done, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dbin", type=Path, default=DBIN)
    ap.add_argument("--vanilla-bin", type=Path, default=VANILLA_BIN)
    ap.add_argument("--check", action="store_true", help="report without writing")
    args = ap.parse_args(argv)
    if not (args.vanilla_bin / "script").is_dir():
        raise SystemExit(f"missing vanilla script tree: {args.vanilla_bin}")
    done, skipped = build(args.dbin, args.vanilla_bin, write=not args.check)
    print(f"[community-packs] {'can write' if args.check else 'wrote'} {done} pack file(s)")
    for line in skipped:
        print(f"  skipped {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
