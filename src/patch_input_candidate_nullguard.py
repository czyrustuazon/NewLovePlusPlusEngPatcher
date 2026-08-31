#!/usr/bin/env python3
"""Guard the two unchecked +0x10 dereferences in FUN_001fba38 (the ML-grid
row/cell-label formatter that runs on kana-row-tap and mode-tab switch, and
which conditionally calls NameInput_FillCandidates at its tail).

Root cause (live-reproduced 2026-08-11 without gdb attached -- a genuine
Azahar-logged fault, not a tracing artifact):

    [HW.Memory] <Error> core/memory.cpp:UnmappedAccess:603:
      unmapped Read32 @ 0x00000010 at PC 0x002FBD20

FUN_001fba38 formats up to two per-cell labels per grid position (60 cells),
each via: FUN_005eba00(...) (draw/measure call, expected to write a result
struct pointer into a stack slot) immediately followed by an unconditional
dereference of that pointer at +0x10:

    ldr r0, [sp, #0x24]
    ldr r1, [r0, #0x10]!   ; CRASHES if r0 == 0 -- unmapped Read32 @ 0x10
    cmp r1, #0x0
    ...

This pattern appears twice per outer-loop iteration (file 0x1fbc08 and
0x1fbd24, VA 0x2fbc08 / 0x2fbd24). Both share the exact same fallback shape
already present in vanilla: when the *loaded value* r1 is null, the code
already knows how to skip cleanly (zero the counter register, branch past
the free-call). The bug is only that the *pointer* r0 itself is never
checked before being dereferenced -- when FUN_005eba00 leaves the stack slot
unset/null, vanilla has no path for that at all and faults instead of
falling into its own null-r1 handling.

Fix: redirect each site to a small cave that checks r0 for null *before*
the dereference. If null, take the exact same path vanilla already takes
for the r1==0 case (same target register zeroed, same branch target) --
this doesn't change behavior for the working case at all, it only adds the
missing guard for the crashing one. See technical.md SS3.3h.

Whether this closes the "candidate list stays 0/0" symptom outright, or
just removes the crash and leaves a display bug to chase further, is not
yet known -- this patch is a targeted crash fix. Verified as part of the
name-input stack in technical.md §17 (with pane-registry nullguard +
fillflag_reset; without candmode_reset).

Rollback: exefs/code.bin.bak_pre_fillcand_nullguard.
"""
from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

# Site 1: first "ldr r1,[r0,#0x10]!" in FUN_001fba38's per-iteration label
# formatting (paired with r6 as the null-path counter register, r9 == 0).
SITE1 = 0x001FBC08
RESUME1 = 0x001FBC0C
POST1 = 0x001FBC30
REG1 = 6

# Site 2: second occurrence in the same iteration (r11 as the null-path
# counter register). This is the one that actually faulted live.
SITE2 = 0x001FBD24
RESUME2 = 0x001FBD28
POST2 = 0x001FBD4C
REG2 = 11

# Shared free vanilla pad @0x006E6A38 (technical.md §17 live cave map).
# Sub-range +0x40/+0x60 — keep clear of pane nullguard (+0x90) and fillflag (+0xC0).
ADDR_CAVE = 0x006E6A38
CAVE1 = ADDR_CAVE + 0x40
CAVE2 = ADDR_CAVE + 0x60
CAVE_CHECK_LEN = 0x80  # unused; apply_patch checks 0x18 per cave only

EXPECT_SITE = bytes.fromhex("1010b0e5")  # ldr r1,[r0,#0x10]!


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def b_ins(here: int, target: int) -> bytes:
    return u32(0xEA000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def beq(here: int, target: int) -> bytes:
    return u32(0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def cmp_imm0(rn: int) -> bytes:
    return u32(0xE3500000 | (rn << 16))


def mov_imm0(rd: int) -> bytes:
    return u32(0xE3A00000 | (rd << 12))


def ldr_pre_wb(rd: int, rn: int, imm: int) -> bytes:
    return u32(0xE5B00000 | (rn << 16) | (rd << 12) | (imm & 0xFFF))


def build_site_cave(cave_addr: int, resume: int, post: int, reg: int) -> bytes:
    null_path = cave_addr + 0x10
    code = bytearray(0x18)
    struct.pack_into("<I", code, 0x00, int.from_bytes(cmp_imm0(0), "little"))
    struct.pack_into("<I", code, 0x04, int.from_bytes(beq(cave_addr + 0x04, null_path), "little"))
    struct.pack_into("<I", code, 0x08, int.from_bytes(ldr_pre_wb(1, 0, 0x10), "little"))
    struct.pack_into("<I", code, 0x0C, int.from_bytes(b_ins(cave_addr + 0x0C, resume), "little"))
    struct.pack_into("<I", code, 0x10, int.from_bytes(mov_imm0(reg), "little"))
    struct.pack_into("<I", code, 0x14, int.from_bytes(b_ins(cave_addr + 0x14, post), "little"))
    return bytes(code)


def apply_patch(data: bytearray) -> None:
    if bytes(data[SITE1 : SITE1 + 4]) != EXPECT_SITE:
        raise ValueError(
            f"unexpected bytes at site1 {SITE1:#x}: "
            f"{data[SITE1:SITE1+4].hex()} (expected {EXPECT_SITE.hex()})"
        )
    if bytes(data[SITE2 : SITE2 + 4]) != EXPECT_SITE:
        raise ValueError(
            f"unexpected bytes at site2 {SITE2:#x}: "
            f"{data[SITE2:SITE2+4].hex()} (expected {EXPECT_SITE.hex()})"
        )
    # Only our two 0x18 caves (0x40 / 0x60). Do not scan 0x90+ —
    # pane-registry nullguard (+0x90) and fillflag_reset (+0xC0) share the pad.
    for addr, label in ((CAVE1, "cave1"), (CAVE2, "cave2")):
        region = bytes(data[addr : addr + 0x18])
        if region != b"\x00" * 0x18:
            raise ValueError(f"{label} @{addr:#x} not empty: {region.hex()}")

    cave1 = build_site_cave(CAVE1, RESUME1, POST1, REG1)
    cave2 = build_site_cave(CAVE2, RESUME2, POST2, REG2)
    data[CAVE1 : CAVE1 + len(cave1)] = cave1
    data[CAVE2 : CAVE2 + len(cave2)] = cave2

    data[SITE1 : SITE1 + 4] = b_ins(SITE1, CAVE1)
    data[SITE2 : SITE2 + 4] = b_ins(SITE2, CAVE2)

    print(
        f"[fillcand-nullguard] site1 @{SITE1:#x} -> cave @{CAVE1:#x}, "
        f"site2 @{SITE2:#x} -> cave @{CAVE2:#x}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        build_site_cave(CAVE1, RESUME1, POST1, REG1)
        build_site_cave(CAVE2, RESUME2, POST2, REG2)
        print("dry-run OK")
        return 0
    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar")

    dest = Path.home() / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")
    bak = dest.with_name(dest.name + ".bak_pre_fillcand_nullguard")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)

    data = bytearray(dest.read_bytes())
    apply_patch(data)
    dest.write_bytes(data)
    shutil.copy2(dest, dest.parent.parent / "code.bin")
    print("Fully quit Azahar to reload exefs/code.bin.")
    print("Rollback: copy bak_pre_fillcand_nullguard -> code.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
