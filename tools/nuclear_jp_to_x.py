#!/usr/bin/env python3
"""Nuclear diagnostic: replace every JP char in textresource TRBs with 'X'.

Does NOT touch BCLIM textures (Options chrome). Use when string-path
screens still show Japanese after EN patching.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patch_textresource import (  # noqa: E402
    AZAHAR_DIR,
    LOOKUP_PATH,
    decode_entry,
    iter_entries,
    load_lookup,
    parse_chunks,
    rebuild_trb,
)

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9d]")

TRB_NAMES = (
    "textresource_jpn.trb",
    "textresource_resident_jpn.trb",
)


def to_x(text: str) -> str:
    return JP_RE.sub("X", text)


def build_map(data: bytes, lookup: list[str]) -> dict[str, str]:
    chunks = parse_chunks(data)
    stri, strb = chunks["STRI"], chunks["STRB"]
    out: dict[str, str] = {}
    for _idx, _off, stringindex, _bl, flag in iter_entries(stri):
        if flag == 2:
            continue
        text, _raw = decode_entry(strb, stringindex, flag, lookup)
        if not text or not JP_RE.search(text):
            continue
        out[text] = to_x(text)
        alt = text.replace("\n", "◙")
        if alt != text:
            out[alt] = to_x(alt)
    return out


def patch_file(src: Path, dst: Path, lookup: list[str]) -> dict:
    data = src.read_bytes()
    translations = build_map(data, lookup)
    new_data, stats = rebuild_trb(data, translations, lookup)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(new_data)
    stats["jp_strings"] = len(translations)
    stats["src"] = str(src)
    stats["dst"] = str(dst)
    stats["bytes"] = f"{len(data)} -> {len(new_data)}"
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write X-nuked TRBs into Azahar LayeredFS (backs up first)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many JP strings would be nuked",
    )
    args = ap.parse_args()

    lookup = load_lookup(LOOKUP_PATH)
    out_dir = ROOT / "out" / "nuclear_jp_x"
    out_dir.mkdir(parents=True, exist_ok=True)

    sources: list[Path] = []
    for name in TRB_NAMES:
        mod = AZAHAR_DIR / name
        if mod.is_file():
            sources.append(mod)
            continue
        # fall back to EngPatcher out / extracted
        for cand in (
            ROOT / "release" / "textresource" / name,
            ROOT.parent
            / "New Love Plus Plus"
            / "extracted"
            / "romfs"
            / "SystemData"
            / "TextResource"
            / name,
        ):
            if cand.is_file():
                sources.append(cand)
                break

    if not sources:
        raise SystemExit("no textresource TRBs found")

    for src in sources:
        dst = out_dir / src.name
        head = src.read_bytes()[:4]
        if head != b"STRI":
            print(f"SKIP {src.name}: not STRI textresource (head={head!r})")
            continue
        if args.dry_run:
            data = src.read_bytes()
            m = build_map(data, lookup)
            print(f"{src.name}: {len(m)} JP strings -> X")
            continue
        stats = patch_file(src, dst, lookup)
        print(
            f"{src.name}: translated={stats['translated']} "
            f"jp_strings={stats['jp_strings']} {stats['bytes']}"
        )
        if args.apply:
            live = AZAHAR_DIR / src.name
            live.parent.mkdir(parents=True, exist_ok=True)
            bak = live.with_suffix(live.suffix + ".bak_pre_jp_x")
            if live.is_file() and not bak.exists():
                shutil.copy2(live, bak)
                print("backup", bak)
            shutil.copy2(dst, live)
            print("applied", live)

    if args.dry_run:
        print("(dry-run; pass --apply to deploy)")
    elif not args.apply:
        print(f"wrote {out_dir}; re-run with --apply to deploy to Azahar")


if __name__ == "__main__":
    main()
