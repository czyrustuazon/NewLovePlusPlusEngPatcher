#!/usr/bin/env python3
"""Romaji Called-name candidates (Profile / first-boot 呼ばれ方 list).

The shipped TRB romanizes the reading dictionary (pack 0x7200 "Akiko",
0x7100+bucket "Aizawa"), but the vanilla lookup still buckets the typed name
by its first hiragana (pack 0x7000) and compares 3 bytes per character. No
name can match, so the list was empty for every name.

This patch:
  1. Replaces the bodies of FUN_00147b3c (exact lookup) and FUN_00147e04
     (candidate list) with src/call_romaji_match.c (compiled blob in
     call_romaji_match_blob.py). They search pack 0x7200 over the vanilla
     ID ranges, case-insensitively, with fuzzy suggestions. Call01 / Call02
     then draw the romaji reading and store its reading ID, so the heroine
     can say a chosen name. FUN_00148f44, which only FUN_00147e04 called,
     holds the scan loop.
  2. When the exact lookup fails for a non-empty Called name, draws the
     typed string as candidate 0, then the suggestions. Its reading ID is a
     long-vowel match (YUji -> ゆうじ "Yuuji") or -1; with -1 the row reads
     "Zack *" so the player knows she won't say it. The tap handlers' copy
     drops the " *" before the name is saved.

Ships in ``deploy_name_input_en.py`` / ``release/name_input_code.bin``.
"""
from __future__ import annotations

import argparse
import hashlib
import struct

from call_romaji_match_blob import PIECES as MATCH_PIECES
from call_romaji_match_blob import SYMBOLS as MATCH_SYMBOLS
from patch_input_cave_map import ADDR_COMMU_HEADER_CAVE, TEXT_PAGE_END
from patch_input_romaji import add_imm, b_ins, bl, cmp_imm, ldr_imm, ldrb_imm, mov_imm

# Each function body the matcher overwrites: start -> (end, sha256 of the
# vanilla bytes). FUN_001480a8 right after FUN_00147e04 stays live.
MATCH_REGIONS = {
    0x00147B3C: (0x00147E04, "e3f493120a3534f8cd019f0d31c175f989269e09d8919f0aff0314bfb17d1f08"),
    0x00147E04: (0x001480A8, "ad8376727c41071444538d3cb1cb514478f5935ad096106b6a26439fd13abc9b"),
    0x00148F44: (0x001493F0, "66c3d860de3e9689aba2b93dec32db5221522196a3a13884b59bf1364a8bdc17"),
}

# Call01 (FUN_0023e468) / Call02 (FUN_001f1a6c): `beq` taken when the exact
# lookup returns 0. Candidate count is r7 (Call01) / r6 (Call02).
SITE_MISS01 = 0x0023E4BC
SITE_MISS02 = 0x001F1A9C
ORIG_MISS01 = bytes.fromhex("2300000a")  # beq 0x23e550
ORIG_MISS02 = bytes.fromhex("2400000a")  # beq 0x1f1b34
MISS01_SKIP = 0x0023E550
MISS02_SKIP = 0x001F1B34
# Candidate-0 strncpy+DrawText, entered with r1 = string to draw.
CALL01_DRAW0 = 0x0023E4F4
CALL02_DRAW0 = 0x001F1AD8
LDR_NAME = bytes.fromhex("68019de5")  # ldr r0, [sp, #0x168] (saved name arg)
# Free 0x20-byte stack buffer for the row text (the TRB copy target, unused
# when the exact lookup missed).
CALL01_BUF = 0x10C
CALL02_BUF = 0x110
# Candidate 0's reading ID: nlpp_call_typed's long-vowel match, else -1 ("no
# reading"). Tapping a candidate copies its ID next to its text (0x23e690 /
# 0x1f1cf0); Profile saves it as a halfword (0x5d282c). The getter 0x5d27b4
# returns -1 for >= 0x1444 and the talk setup at 0xe2b84 then skips the voice
# reading. Left alone, the slot keeps the ctor 0 (pack 0x7200 slot 0, Aizawa)
# or a stale ID.
STR_ID01 = bytes.fromhex("940386e5")  # str r0, [r6, #0x394]
ADD_IP_ID02 = bytes.fromhex("02cc87e2")  # add ip, r7, #0x200
STRH_ID02 = bytes.fromhex("b403cce1")  # strh r0, [ip, #0x34]
# Tap handlers copy a row's text into the Called name with `bl 0x317dc`
# (strncpy). nlpp_call_pick does the same copy, then drops the " *" no-voice
# marker nlpp_call_typed added to the row.
SITE_PICK01 = 0x0023E73C
SITE_PICK02 = 0x001F1D20
ORIG_PICK01 = bytes.fromhex("26ccf7eb")  # bl 0x317dc
ORIG_PICK02 = bytes.fromhex("adfef8eb")  # bl 0x317dc
NLPP_CALL_TYPED = MATCH_SYMBOLS["nlpp_call_typed"]
NLPP_CALL_PICK = MATCH_SYMBOLS["nlpp_call_pick"]


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def b_cond(cond: int, here: int, target: int) -> bytes:
    return u32((cond << 28) | 0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def cave_addr() -> int:
    from patch_input_strcat_raw import build_blob as strcat_blob
    from patch_input_strcat_raw import cave_addr as strcat_cave

    sc = strcat_cave()
    return sc + len(strcat_blob(base=sc))


def is_patched(data: bytes) -> bool:
    start, piece = MATCH_PIECES[0]
    return bytes(data[start : start + len(piece)]) == piece


def _build_stream() -> list:
    stream: list = []

    def OP(b: bytes) -> None:
        stream.append(("op", b))

    def L(name: str) -> None:
        stream.append(("label", name))

    def B(name: str, cond: int | None = None) -> None:
        stream.append(("b", name, cond))

    def BABS(addr: int, cond: int | None = None) -> None:
        stream.append(("b_abs", addr, cond))

    def BL(addr: int) -> None:
        stream.append(("bl", addr))

    # Exact lookup failed (r0 = 0). A non-empty name becomes candidate 0:
    # r0 = nlpp_call_typed(name, mode, buf) is its reading ID (long-vowel
    # match or -1) and buf its row text (name, " *" when -1). Count = 1, then
    # the candidate-0 tail with r1 = buf (skips the TRB `add r1, sp, …`). The
    # tail falls through to the suggestion list, which appends after it.
    # Empty name: vanilla skip. r9 is already 1 and obj is r6 (Call01) / r7
    # (Call02), as the tail expects; the BL keeps both. Mode is what vanilla
    # passes the lookup: 1 for Call01, [obj+0x2c] for Call02.
    for n, count_reg, mode, buf, store_id, draw0, skip in (
        ("01", 7, mov_imm(1, 1), CALL01_BUF, (STR_ID01,), CALL01_DRAW0, MISS01_SKIP),
        (
            "02",
            6,
            ldr_imm(1, 7, 0x2C),
            CALL02_BUF,
            (ADD_IP_ID02, STRH_ID02),
            CALL02_DRAW0,
            MISS02_SKIP,
        ),
    ):
        L("typed" + n)
        OP(LDR_NAME)
        OP(cmp_imm(0, 0))
        BABS(skip, cond=0x0)
        OP(ldrb_imm(1, 0, 0))
        OP(cmp_imm(1, 0))
        BABS(skip, cond=0x0)
        OP(mode)
        OP(add_imm(2, 13, buf))
        BL(NLPP_CALL_TYPED)
        for word in store_id:
            OP(word)
        OP(add_imm(1, 13, buf))
        OP(mov_imm(count_reg, 1))
        BABS(draw0)
    return stream


def _assemble(base: int, stream: list) -> tuple[bytes, dict[str, int]]:
    labs: dict[str, int] = {}
    addr = base
    for it in stream:
        if it[0] == "label":
            labs[it[1]] = addr
        else:
            addr += 4

    out = bytearray()
    addr = base
    for it in stream:
        kind = it[0]
        if kind == "label":
            continue
        if kind == "op":
            out.extend(it[1])
        elif kind == "bl":
            out.extend(bl(addr, it[1]))
        elif kind in ("b", "b_abs"):
            cond = it[2]
            tgt = labs[it[1]] if kind == "b" else it[1]
            out.extend(b_ins(addr, tgt) if cond is None else b_cond(cond, addr, tgt))
        else:
            raise ValueError(it)
        addr += 4
    return bytes(out), labs


def build_blob(base: int | None = None) -> tuple[bytes, dict[str, int]]:
    if base is None:
        base = cave_addr()
    return _assemble(base, _build_stream())


def apply_patch(data: bytearray) -> bool:
    base = cave_addr()
    blob, labs = build_blob(base=base)
    end = base + len(blob)
    if end > ADDR_COMMU_HEADER_CAVE:
        raise ValueError(
            f"call-romaji cave {end:#x} overlaps commu header {ADDR_COMMU_HEADER_CAVE:#x}"
        )
    if is_patched(data):
        print(f"[call-romaji] already patched cave @{base:#x}")
        return False

    if [s for s, _p in MATCH_PIECES] != list(MATCH_REGIONS):
        raise ValueError("call_romaji_match_blob regions do not match MATCH_REGIONS")
    for start, piece in MATCH_PIECES:
        body_end, sha = MATCH_REGIONS[start]
        if start + len(piece) > body_end:
            raise ValueError(f"matcher piece {start:#x} overruns {body_end:#x}")
        if hashlib.sha256(bytes(data[start:body_end])).hexdigest() != sha:
            raise ValueError(f"lookup body {start:#x}..{body_end:#x} is not vanilla")
    for site, orig in (
        (SITE_MISS01, ORIG_MISS01),
        (SITE_MISS02, ORIG_MISS02),
        (SITE_PICK01, ORIG_PICK01),
        (SITE_PICK02, ORIG_PICK02),
    ):
        if bytes(data[site : site + 4]) != orig:
            raise ValueError(f"unexpected Called list code at {site:#x}")
    if any(data[base:end]):
        raise ValueError(f"call-romaji cave {base:#x}..{end:#x} is not empty pad")

    size = len(data)
    for start, piece in MATCH_PIECES:
        data[start : start + len(piece)] = piece
    data[base:end] = blob
    if len(data) != size:
        raise AssertionError("call-romaji changed the code.bin size")
    data[SITE_MISS01 : SITE_MISS01 + 4] = b_cond(0x0, SITE_MISS01, labs["typed01"])
    data[SITE_MISS02 : SITE_MISS02 + 4] = b_cond(0x0, SITE_MISS02, labs["typed02"])
    data[SITE_PICK01 : SITE_PICK01 + 4] = bl(SITE_PICK01, NLPP_CALL_PICK)
    data[SITE_PICK02 : SITE_PICK02 + 4] = bl(SITE_PICK02, NLPP_CALL_PICK)
    sizes = ", ".join(f"{s:#x}+{len(p):#x}" for s, p in MATCH_PIECES)
    print(f"[call-romaji] romaji matcher {sizes}; typed-name cave @{base:#x} ({len(blob):#x})")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    base = cave_addr()
    blob, labs = build_blob(base=base)
    print(f"call-romaji {len(blob):#x} @ {base:#x}")
    print("  labels", {k: hex(v) for k, v in labs.items()})
    print(
        f"  end {base + len(blob):#x} text_end {TEXT_PAGE_END:#x} "
        f"free {TEXT_PAGE_END - (base + len(blob)):#x}"
    )
    for start, piece in MATCH_PIECES:
        print(f"  matcher {start:#x}..{start + len(piece):#x}")
    if args.dry_run:
        return 0
    raise SystemExit("applied via deploy_name_input_en.py")


if __name__ == "__main__":
    raise SystemExit(main())
