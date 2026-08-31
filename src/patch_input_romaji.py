#!/usr/bin/env python3
"""
Hepburn romaji for the name-input gojūon grid (technical.md §17).

Rewrites NameInput_DrawCell (0x1fc304) so DrawText shows romaji AND the
7-byte insert buffer stores the same display string (so kana-direct /
ABC-style insert writes romaji into the name field).

Romaji is built on a stack buffer (not the code cave): ExeFS .code is RX
under Azahar — stores into the cave are dropped.

Prerequisite: §17 stack (pane nullguard + candidate nullguard + fillflag).
Do not deploy candmode_reset. If labels go blank, the pane font may lack
Latin — compare with the in-UI ABC tab (same DrawCell).

Rollback: exefs/code.bin.bak_pre_input_romaji
"""
from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

ADDR_DRAW_CELL = 0x001FC304
SIZE_DRAW_CELL = 0xA0

ADDR_CLEAR_PANE = 0x0054B5FC
ADDR_MAKE_STR = 0x005A1EC8
ADDR_DRAW_TEXT = 0x0054B880
ADDR_FREE_STR = 0x005A2024
ADDR_MEMCPY7 = 0x000317DC

# 4KB zero pad in vanilla code.bin (verified empty)
ADDR_CAVE = 0x006FBB08
CAVE_MAX = 0x1000

VANILLA_HEAD = bytes.fromhex("f04f2de90060a0e1")  # stmdb …; mov r6,r0


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def encode_imm12(value: int) -> int:
    value &= 0xFFFFFFFF
    for rot in range(16):
        if rot == 0:
            imm8 = value
        else:
            r = (rot * 2) & 31
            imm8 = ((value << r) | (value >> (32 - r))) & 0xFFFFFFFF
        if imm8 <= 0xFF:
            r = (rot * 2) & 31
            got = imm8 if r == 0 else ((imm8 >> r) | (imm8 << (32 - r))) & 0xFFFFFFFF
            if got == value:
                return (rot << 8) | imm8
    raise ValueError(f"cannot encode imm {value:#x}")


def mov_imm(rd: int, imm: int) -> bytes:
    return u32(0xE3A00000 | (rd << 12) | encode_imm12(imm))


def mov_imm_cond(cond: int, rd: int, imm: int) -> bytes:
    return u32((cond << 28) | 0x03A00000 | (rd << 12) | encode_imm12(imm))


def add_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE2800000 | (rn << 16) | (rd << 12) | encode_imm12(imm))


def sub_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE2400000 | (rn << 16) | (rd << 12) | encode_imm12(imm))


def add_reg(rd: int, rn: int, rm: int, shift: int = 0) -> bytes:
    return u32(0xE0800000 | (rn << 16) | (rd << 12) | ((shift & 0x1F) << 7) | rm)


def sub_reg(rd: int, rn: int, rm: int) -> bytes:
    return u32(0xE0400000 | (rn << 16) | (rd << 12) | rm)


def mov_reg(rd: int, rm: int) -> bytes:
    return u32(0xE1A00000 | (rd << 12) | rm)


def cmp_imm(rn: int, imm: int) -> bytes:
    return u32(0xE3500000 | (rn << 16) | encode_imm12(imm))


def cmp_reg(rn: int, rm: int) -> bytes:
    return u32(0xE1500000 | (rn << 16) | rm)


def ldr_imm(rd: int, rn: int, imm: int) -> bytes:
    assert 0 <= imm <= 4095
    return u32(0xE5900000 | (rn << 16) | (rd << 12) | imm)


def str_imm(rd: int, rn: int, imm: int) -> bytes:
    assert 0 <= imm <= 4095
    return u32(0xE5800000 | (rn << 16) | (rd << 12) | imm)


def ldrb_imm(rd: int, rn: int, imm: int = 0) -> bytes:
    return u32(0xE5D00000 | (rn << 16) | (rd << 12) | imm)


def push(mask: int) -> bytes:
    return u32(0xE92D0000 | mask)


def pop(mask: int) -> bytes:
    return u32(0xE8BD0000 | mask)


def bl(here: int, target: int) -> bytes:
    return u32(0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def b_ins(here: int, target: int) -> bytes:
    return u32(0xEA000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def b_cond(cond: int, here: int, target: int) -> bytes:
    return u32((cond << 28) | 0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def and_imm(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE2000000 | (rn << 16) | (rd << 12) | encode_imm12(imm))


def orr_reg(rd: int, rn: int, rm: int, shift: int = 0) -> bytes:
    return u32(0xE1800000 | (rn << 16) | (rd << 12) | ((shift & 0x1F) << 7) | rm)


def lsl_imm(rd: int, rm: int, sh: int) -> bytes:
    return u32(0xE1A00000 | (rd << 12) | ((sh & 0x1F) << 7) | rm)


def stmia_sp(regs_mask: int) -> bytes:
    # stmia sp, {regs}  — write-back not set (like original stmia sp,{r7,r8})
    return u32(0xE88D0000 | regs_mask)


def ldr_pc_rel(rd: int, here: int, lit: int) -> bytes:
    imm = lit - (here + 8)
    assert 0 <= imm < 4096 and (imm % 4) == 0
    return u32(0xE59F0000 | (rd << 12) | imm)


def _pad4(s: str) -> bytes:
    b = s.encode("ascii")
    if len(b) > 3:
        raise ValueError(s)
    return b + b"\0" * (4 - len(b))


# Image-2 Hepburn map (small kana → lowercase). Keyed by hiragana codepoint.
HIRA_ROMAJI: dict[int, str] = {
    ord("ぁ"): "a",
    ord("ぃ"): "i",
    ord("ぅ"): "u",
    ord("ぇ"): "e",
    ord("ぉ"): "o",
    ord("あ"): "A",
    ord("い"): "I",
    ord("う"): "U",
    ord("え"): "E",
    ord("お"): "O",
    ord("か"): "KA",
    ord("き"): "KI",
    ord("く"): "KU",
    ord("け"): "KE",
    ord("こ"): "KO",
    ord("が"): "GA",
    ord("ぎ"): "GI",
    ord("ぐ"): "GU",
    ord("げ"): "GE",
    ord("ご"): "GO",
    ord("さ"): "SA",
    ord("し"): "SHI",
    ord("す"): "SU",
    ord("せ"): "SE",
    ord("そ"): "SO",
    ord("ざ"): "ZA",
    ord("じ"): "JI",
    ord("ず"): "ZU",
    ord("ぜ"): "ZE",
    ord("ぞ"): "ZO",
    ord("た"): "TA",
    ord("ち"): "CHI",
    ord("つ"): "TSU",
    ord("て"): "TE",
    ord("と"): "TO",
    ord("だ"): "DA",
    ord("ぢ"): "DI",
    ord("づ"): "DU",
    ord("で"): "DE",
    ord("ど"): "DO",
    ord("な"): "NA",
    ord("に"): "NI",
    ord("ぬ"): "NU",
    ord("ね"): "NE",
    ord("の"): "NO",
    ord("は"): "HA",
    ord("ひ"): "HI",
    ord("ふ"): "FU",
    ord("へ"): "HE",
    ord("ほ"): "HO",
    ord("ば"): "BA",
    ord("び"): "BI",
    ord("ぶ"): "BU",
    ord("べ"): "BE",
    ord("ぼ"): "BO",
    ord("ぱ"): "PA",
    ord("ぴ"): "PI",
    ord("ぷ"): "PU",
    ord("ぺ"): "PE",
    ord("ぽ"): "PO",
    ord("ま"): "MA",
    ord("み"): "MI",
    ord("む"): "MU",
    ord("め"): "ME",
    ord("も"): "MO",
    ord("ゃ"): "ya",
    ord("や"): "YA",
    ord("ゅ"): "yu",
    ord("ゆ"): "YU",
    ord("ょ"): "yo",
    ord("よ"): "YO",
    ord("ら"): "RA",
    ord("り"): "RI",
    ord("る"): "RU",
    ord("れ"): "RE",
    ord("ろ"): "RO",
    ord("ゎ"): "wa",
    ord("わ"): "WA",
    ord("ゐ"): "WI",
    ord("ゑ"): "WE",
    ord("を"): "WO",
    ord("ん"): "N",
    ord("っ"): "tsu",
}


def _assemble(base: int, stream: list) -> bytes:
    labs: dict[str, int] = {}
    addr = base
    for it in stream:
        if it[0] == "label":
            labs[it[1]] = addr
        elif it[0] == "lit":
            if addr & 3:
                addr = (addr + 3) & ~3
            labs[it[1]] = addr
            addr += 4
        else:
            addr += 4

    out = bytearray()
    addr = base
    for it in stream:
        kind = it[0]
        if kind == "label":
            continue
        if kind == "lit":
            while len(out) & 3:
                out.append(0)
                addr += 1
            out.extend(u32(it[2]))
            addr += 4
            continue
        if kind == "op":
            out.extend(it[1])
        elif kind == "bl":
            out.extend(bl(addr, it[1]))
        elif kind == "bl_lab":
            out.extend(bl(addr, labs[it[1]]))
        elif kind == "b":
            cond = it[2]
            tgt = labs[it[1]]
            out.extend(b_ins(addr, tgt) if cond is None else b_cond(cond, addr, tgt))
        elif kind == "ldr":
            out.extend(ldr_pc_rel(it[1], addr, labs[it[2]]))
        else:
            raise ValueError(it)
        addr += 4
    return bytes(out)


def build_romaji_blob(*, canary: bool = False) -> bytes:
    hira_tab = b"".join(
        _pad4(HIRA_ROMAJI.get(cp, "")) for cp in range(0x3041, 0x3041 + 0x56)
    )
    kata_tab = b"".join(
        _pad4(HIRA_ROMAJI.get(cp - 0x60, "")) for cp in range(0x30A1, 0x30A1 + 0x56)
    )

    stream: list = []

    def OP(b: bytes) -> None:
        stream.append(("op", b))

    def L(name: str) -> None:
        stream.append(("label", name))

    def BL(addr: int) -> None:
        stream.append(("bl", addr))

    def B(name: str, cond: int | None = None) -> None:
        stream.append(("b", name, cond))

    def LDR(rd: int, name: str) -> None:
        stream.append(("ldr", rd, name))

    def LIT(name: str, val: int = 0) -> None:
        stream.append(("lit", name, val))

    # ---- draw_cell (mirrors FUN_001fc304; MakeStr uses romaji) ----
    # r0=obj r1=idx r2=str
    # Stack: [0..0x33] same as vanilla MakeStr frame; [0x34..0x3B] RW romaji out
    # (must NOT write romaji into .text — ExeFS .code is RX on Azahar)
    L("draw")
    OP(push(0x4FF0))  # r4-r11, lr
    OP(mov_reg(6, 0))  # obj
    OP(mov_reg(5, 1))  # idx
    OP(sub_imm(13, 13, 0x3C))
    OP(mov_reg(9, 2))  # orig str
    OP(mov_imm(0, 0))
    OP(add_reg(4, 6, 5, shift=2))  # &pane_slot
    OP(cmp_imm(5, 0x3C))
    B("epilogue", cond=0x2)  # hs

    OP(ldr_imm(0, 4, 0x54))
    BL(ADDR_CLEAR_PANE)

    # r0 = kana_to_romaji(dst=sp+0x34, src=orig)
    OP(add_imm(0, 13, 0x34))
    if canary:
        OP(cmp_imm(5, 0))
        B("do_romaji", cond=0x1)  # ne
        LDR(10, "ok_str")
        B("after_kana")
        L("do_romaji")
    OP(mov_reg(1, 9))
    stream.append(("bl_lab", "kana"))
    OP(mov_reg(10, 0))  # display cstr
    L("after_kana")

    # Always maxGlyphs=0 (unlimited UTF-8 / short ASCII romaji).
    # maxGlyphs=1 truncates multi-byte UTF-8 to the first byte (blank/junk).
    # Do not use maxGlyphs=3 only for romaji — ABC/latin and Hepburn both need
    # the full C string; 0 matches candidate-kanji path and avoids length bugs.
    OP(mov_imm(7, 0))

    # MakeStr(sp+0x18, display)
    OP(mov_reg(1, 10))
    OP(add_imm(0, 13, 0x18))
    BL(ADDR_MAKE_STR)
    OP(mov_reg(3, 0))  # makestr handle

    # DrawTextToPane(pane, 0, 0, makestr, maxGlyphs, 0)
    OP(mov_imm(8, 0))
    OP(stmia_sp(0x0180))  # {r7,r8} = maxGlyphs,0
    OP(mov_imm(1, 0))
    OP(mov_imm(2, 0))
    OP(ldr_imm(0, 4, 0x54))
    BL(ADDR_DRAW_TEXT)
    OP(mov_reg(7, 0))  # keep draw result

    OP(add_imm(0, 13, 0x18))
    BL(ADDR_FREE_STR)

    # memcpy(obj+idx*8+0x541, DISPLAY, 7) — insert matches on-screen label
    # (romaji for gojuon; original kana/kanji/latin when unmapped).
    OP(add_reg(0, 6, 5, shift=3))
    OP(add_imm(0, 0, 0x500))
    OP(add_imm(0, 0, 0x41))
    OP(mov_imm(2, 7))
    OP(mov_reg(1, 10))
    BL(ADDR_MEMCPY7)
    OP(mov_reg(0, 7))

    L("epilogue")
    OP(add_imm(13, 13, 0x3C))
    OP(pop(0x8FF0))  # r4-r11, pc

    # ---- kana_to_romaji(r0=dst8, r1=src) -> r0=display cstr ----
    L("kana")
    OP(push(0x40F0))  # r4-r7, lr
    OP(mov_reg(7, 0))  # dst (RW stack)
    OP(mov_reg(4, 1))  # src
    OP(cmp_imm(4, 0))
    B("k_orig", cond=0x0)  # eq

    OP(ldrb_imm(0, 4, 0))
    OP(cmp_imm(0, 0))
    B("k_orig", cond=0x0)
    OP(cmp_imm(0, 0xE3))
    B("k_orig", cond=0x1)  # ne

    OP(ldrb_imm(1, 4, 1))
    OP(ldrb_imm(2, 4, 2))
    # cp = ((b0&0xf)<<12) | ((b1&0x3f)<<6) | (b2&0x3f)  into r5
    OP(and_imm(0, 0, 0x0F))
    OP(lsl_imm(0, 0, 12))
    OP(and_imm(1, 1, 0x3F))
    OP(lsl_imm(1, 1, 6))
    OP(orr_reg(5, 0, 1))
    OP(and_imm(2, 2, 0x3F))
    OP(orr_reg(5, 5, 2))

    # hiragana range?
    LDR(6, "hira_lo")
    OP(cmp_reg(5, 6))
    B("try_kata", cond=0x3)  # lo
    LDR(6, "hira_hi")
    OP(cmp_reg(5, 6))
    B("try_kata", cond=0x8)  # hi
    LDR(6, "hira_lo")
    OP(sub_reg(0, 5, 6))  # idx
    OP(cmp_imm(0, 0x56))
    B("k_orig", cond=0x2)  # hs
    LDR(1, "hira_tab")
    OP(add_reg(1, 1, 0, shift=2))
    OP(ldrb_imm(2, 1, 0))
    OP(cmp_imm(2, 0))
    B("k_orig", cond=0x0)
    OP(ldr_imm(2, 1, 0))
    OP(str_imm(2, 7, 0))
    OP(mov_reg(0, 7))
    B("k_done")

    L("try_kata")
    LDR(6, "kata_lo")
    OP(cmp_reg(5, 6))
    B("k_orig", cond=0x3)
    LDR(6, "kata_hi")
    OP(cmp_reg(5, 6))
    B("k_orig", cond=0x8)
    LDR(6, "kata_lo")
    OP(sub_reg(0, 5, 6))
    OP(cmp_imm(0, 0x56))
    B("k_orig", cond=0x2)
    LDR(1, "kata_tab")
    OP(add_reg(1, 1, 0, shift=2))
    OP(ldrb_imm(2, 1, 0))
    OP(cmp_imm(2, 0))
    B("k_orig", cond=0x0)
    OP(ldr_imm(2, 1, 0))
    OP(str_imm(2, 7, 0))
    OP(mov_reg(0, 7))
    B("k_done")

    L("k_orig")
    OP(mov_reg(0, 4))
    L("k_done")
    OP(pop(0x80F0))  # r4-r7, pc

    LIT("hira_lo", 0x3041)
    LIT("hira_hi", 0x3096)
    LIT("kata_lo", 0x30A1)
    LIT("kata_hi", 0x30F6)
    LIT("hira_tab", 0)
    LIT("kata_tab", 0)
    if canary:
        LIT("ok_str", 0)

    # First pass to measure code size / table offsets
    code = _assemble(ADDR_CAVE, stream)
    while len(code) & 3:
        code += b"\0"
    hira_off = len(code)
    kata_off = hira_off + len(hira_tab)
    ok_off = kata_off + len(kata_tab) if canary else 0
    ok_bytes = b"OK\x00" if canary else b""

    stream2: list = []
    for it in stream:
        if it[0] == "lit" and it[1] == "hira_tab":
            stream2.append(("lit", "hira_tab", 0x100000 + ADDR_CAVE + hira_off))
        elif it[0] == "lit" and it[1] == "kata_tab":
            stream2.append(("lit", "kata_tab", 0x100000 + ADDR_CAVE + kata_off))
        elif it[0] == "lit" and it[1] == "ok_str":
            stream2.append(("lit", "ok_str", 0x100000 + ADDR_CAVE + ok_off))
        else:
            stream2.append(it)

    code = _assemble(ADDR_CAVE, stream2)
    while len(code) & 3:
        code += b"\0"
    if len(code) != hira_off:
        raise RuntimeError(f"code size drift {len(code)} != {hira_off}")
    code += hira_tab + kata_tab + ok_bytes
    if len(code) > CAVE_MAX:
        raise ValueError(f"cave too large: {len(code):#x}")
    return bytes(code)


def assemble_trampoline() -> bytes:
    body = bytearray(b_ins(ADDR_DRAW_CELL, ADDR_CAVE))
    body.extend(b"\x00" * (SIZE_DRAW_CELL - len(body)))
    return bytes(body)


def is_romaji_patched(data: bytes | bytearray) -> bool:
    insn = struct.unpack_from("<I", data, ADDR_DRAW_CELL)[0]
    if (insn & 0xFF000000) != 0xEA000000:
        return False
    imm = insn & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    return ADDR_DRAW_CELL + 8 + (imm << 2) == ADDR_CAVE


def patch_input_romaji(data: bytearray, *, force: bool = False, canary: bool = False) -> bool:
    if is_romaji_patched(data) and not force and not canary:
        return False
    head = bytes(data[ADDR_DRAW_CELL : ADDR_DRAW_CELL + 8])
    if not is_romaji_patched(data) and head != VANILLA_HEAD and not force:
        raise ValueError(f"unexpected FUN_001fc304 head {head.hex()}")

    cave = build_romaji_blob(canary=canary)
    region = bytes(data[ADDR_CAVE : ADDR_CAVE + len(cave)])
    if (
        region != b"\x00" * len(cave)
        and not force
        and not is_romaji_patched(data)
        and region[:4] != bytes.fromhex("f04f2de9")
    ):
        raise ValueError(f"cave @{ADDR_CAVE:#x} not empty")

    data[ADDR_CAVE : ADDR_CAVE + len(cave)] = cave
    data[ADDR_DRAW_CELL : ADDR_DRAW_CELL + SIZE_DRAW_CELL] = assemble_trampoline()
    return True


def patch_code_bin_romaji(path: Path, *, force: bool = False) -> bool:
    data = bytearray(path.read_bytes())
    bak = path.with_name(path.name + ".bak_pre_input_romaji")
    if not bak.exists():
        shutil.copy2(path, bak)
    if not patch_input_romaji(data, force=force):
        print(f"[input-romaji] already patched: {path}")
        return False
    path.write_bytes(data)
    print(f"[input-romaji] FUN_001fc304 -> cave @{ADDR_CAVE:#x}")
    print(f"[input-romaji] wrote {path}")
    print(f"[input-romaji] backup {bak}")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("code_bin", nargs="?", type=Path)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    default = (
        Path(__file__).resolve().parents[2]
        / "New Love Plus Plus"
        / "extracted"
        / "exefs"
        / "code.bin"
    )
    src = (args.code_bin or default).resolve()
    if not src.is_file():
        raise SystemExit(f"missing {src}")

    cave = build_romaji_blob()
    print(f"cave size {len(cave)} / {CAVE_MAX}")
    samples = "AIUEOKASHICHITSUFUaatsuya"
    print("map ok, samples encoded")

    # Verify head matches vanilla
    head = src.read_bytes()[ADDR_DRAW_CELL : ADDR_DRAW_CELL + 8]
    print("vanilla head", head.hex(), "expected", VANILLA_HEAD.hex(), head == VANILLA_HEAD)

    if args.dry_run:
        return 0

    if args.deploy_azahar:
        mod_root = Path.home() / "AppData/Roaming/Azahar/load/mods/00040000000F4E00"
        dest = mod_root / "exefs" / "code.bin"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_file():
            shutil.copy2(src, dest)
            print("seeded", dest)
        patch_code_bin_romaji(dest, force=True)
        # Azahar also accepts Luma-style mods/<tid>/code.bin
        shutil.copy2(dest, mod_root / "code.bin")
        print("also", mod_root / "code.bin")
        # Keep the fragile F7 DrawText pack from shadowing this patch
        tex = Path.home() / "AppData/Roaming/Azahar/load/textures/00040000000F4E00"
        disabled = tex.with_name("00040000000F4E00_disabled")
        if tex.is_dir() and not disabled.exists():
            tex.rename(disabled)
            print("renamed custom texture pack ->", disabled.name)
        print("Fully quit Azahar so LayeredFS reloads exefs/code.bin.")
        print("No F7 / custom_textures needed — this is a code.bin LayeredFS patch.")
    else:
        patch_code_bin_romaji(src, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
