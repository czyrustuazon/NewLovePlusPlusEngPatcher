#!/usr/bin/env python3
"""Romaji Called-name candidates (Profile / first-boot 呼ばれ方 list).

The shipped TRB romanizes the reading dictionary (pack 0x7200 "Akiko",
0x7100+bucket "Aizawa"), but the vanilla lookup still buckets the typed name
by its first hiragana (pack 0x7000) and compares 3 bytes per character. No
name can match, so the list was empty for every name.

This patch replaces the bodies of FUN_00147b3c (exact lookup) and
FUN_00147e04 (candidate list) with src/call_romaji_match.c (compiled blob in
call_romaji_match_blob.py). They search pack 0x7200 over the vanilla ID
ranges, case-insensitively, with fuzzy suggestions. Call01 / Call02 then draw
the romaji reading and store its reading ID, so the heroine can say a chosen
name. FUN_00148f44, which only FUN_00147e04 called, holds the scan loop. A
name with no exact match or suggestion leaves the list empty, as in vanilla.

Ships in ``deploy_name_input_en.py`` / ``release/name_input_code.bin``.
"""
from __future__ import annotations

import argparse
import hashlib

from call_romaji_match_blob import PIECES as MATCH_PIECES

# Each function body the matcher overwrites: start -> (end, sha256 of the
# vanilla bytes). FUN_001480a8 right after FUN_00147e04 stays live.
MATCH_REGIONS = {
    0x00147B3C: (0x00147E04, "e3f493120a3534f8cd019f0d31c175f989269e09d8919f0aff0314bfb17d1f08"),
    0x00147E04: (0x001480A8, "ad8376727c41071444538d3cb1cb514478f5935ad096106b6a26439fd13abc9b"),
    0x00148F44: (0x001493F0, "66c3d860de3e9689aba2b93dec32db5221522196a3a13884b59bf1364a8bdc17"),
}


def is_patched(data: bytes) -> bool:
    start, piece = MATCH_PIECES[0]
    return bytes(data[start : start + len(piece)]) == piece


def apply_patch(data: bytearray) -> bool:
    if is_patched(data):
        print("[call-romaji] already patched")
        return False

    if [s for s, _p in MATCH_PIECES] != list(MATCH_REGIONS):
        raise ValueError("call_romaji_match_blob regions do not match MATCH_REGIONS")
    for start, piece in MATCH_PIECES:
        body_end, sha = MATCH_REGIONS[start]
        if start + len(piece) > body_end:
            raise ValueError(f"matcher piece {start:#x} overruns {body_end:#x}")
        if hashlib.sha256(bytes(data[start:body_end])).hexdigest() != sha:
            raise ValueError(f"lookup body {start:#x}..{body_end:#x} is not vanilla")

    size = len(data)
    for start, piece in MATCH_PIECES:
        data[start : start + len(piece)] = piece
    if len(data) != size:
        raise AssertionError("call-romaji changed the code.bin size")
    sizes = ", ".join(f"{s:#x}+{len(p):#x}" for s, p in MATCH_PIECES)
    print(f"[call-romaji] romaji matcher {sizes}")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    for start, piece in MATCH_PIECES:
        print(f"  matcher {start:#x}..{start + len(piece):#x}")
    if args.dry_run:
        return 0
    raise SystemExit("applied via deploy_name_input_en.py")


if __name__ == "__main__":
    raise SystemExit(main())
