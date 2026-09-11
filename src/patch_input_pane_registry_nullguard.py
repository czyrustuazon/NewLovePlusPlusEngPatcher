#!/usr/bin/env python3
"""Guard the unchecked call into FUN_00545550 -> FUN_00542230 (an unchecked
doubly-linked-list insert) from the per-cell "lazily create this pane"
handler inside the shared 60-cell keyboard/candidate pane-warmup loop.

(Renamed in Ghidra after this investigation: FUN_00545550 -> Pane_AttachToParent,
FUN_00542230 -> IntrusiveDList_InsertFront. Kept as FUN_ addresses below since
that's how they were identified live -- see those functions' plate comments in
Ghidra, or the Known-APIs table in technical.md / .cursor/rules/ghidra-mcp.mdc,
for the current names.)

Root cause (live GDB-traced 2026-08-13, arm-none-eabi-gdb over Azahar's
gdbstub, port 24689 -- see technical.md SS3.3j; supersedes the SS3.3i
CreateTextPane theory, which was live-disproven: 35 real CreateTextPane
calls traced clean in the same session):

    [HW.Memory] <Error> core/memory.cpp:UnmappedAccess:603:
      unmapped Read32 @ 0x00000018 at PC 0x00645550   (logged PC is the
      containing function's ENTRY -- Azahar/Dynarmic block-linking can
      report the outer/entry PC instead of the true faulting instruction;
      a live gdb breakpoint caught the real SIGSEGV 0x1c bytes deeper, at
      file 0x54556c, inside FUN_00545550)

The call site (file 0x1fa788-0x1fa790, inside the "create it now" branch of
the main pane-warmup loop) does:

    ldr r0, [sp, #0x3c]      ; r0 = a value read from this loop's own stack
                              ;      frame -- confirmed (disassemble_bytes,
                              ;      instruction-by-instruction, from the
                              ;      routine's real entry at file 0x1fa2d0
                              ;      through the per-cell handler) that this
                              ;      exact stack slot is NEVER WRITTEN
                              ;      anywhere in the reachable body. Reads
                              ;      back as a clean, deterministic 0 (the
                              ;      crash log's faulting address is
                              ;      literally absolute 0x18, not "some
                              ;      garbage address"), consistent with
                              ;      first-touch-zeroed, never-initialized
                              ;      stack memory.
    ldr r1, [r9, #0x54]      ; r1 = the pane pointer just created (always
                              ;      valid -- confirmed live)
    bl   FUN_00545550        ; CRASHES when r0 == 0: FUN_00545550 passes
                              ; r0 (as its own param_1) into
                              ; FUN_00542230's linked-list insert, which
                              ; unconditionally dereferences
                              ; *(param_1+0x14+4) with no null check
                              ; anywhere in the function.

FUN_00542230 has no existing vanilla null-check branch to redirect into
(unlike patch_input_candidate_nullguard.py's SS3.3h fix, which reuses
vanilla's own r1==0 fallback) -- every line in it assumes valid input
unconditionally. So this guard is added at the CALL SITE instead: skip the
`bl FUN_00545550` outright when the stack slot is still zero, since the
call's only observable effects (the list-insert bookkeeping and the
`*(paneptr+0xc) = <that stack value>` write) are meaningless/dangerous
when there is nothing valid to register. This does not change behavior for
any call where the slot is non-zero (the pane pool is otherwise unaffected
-- CreateTextPane itself is proven fine, see SS3.3j).

Part of the verified name-input stack (technical.md §17). Safe with
candidate_nullguard + fillflag_reset; do not combine with the removed
candmode_reset (+0x24 force-zero kills taps).

Rollback: exefs/code.bin.bak_pre_pane_registry_nullguard.
"""
from __future__ import annotations

import argparse
import shutil
import struct
from pathlib import Path

from patch_input_cave_map import ADDR_SHARED_PAD as ADDR_CAVE

# Call site: `bl 0x00545550` inside the per-cell "create it now" handler.
SITE = 0x001FA790
RESUME = 0x001FA794  # first instruction after the call (a nop; harmless)
EXPECT_SITE = bytes.fromhex("6e2b0deb")  # bl 0x00545550

CALL_TARGET = 0x00545550

# Same last-.text RX pad as the fillcand nullguard (technical.md §17).
# Sub-range +0x90 — keep clear of candidate (+0x40/+0x60) and fillflag (+0xC0).
CAVE = ADDR_CAVE + 0x90
CAVE_LEN = 0x10


def u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def b_ins(here: int, target: int) -> bytes:
    return u32(0xEA000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def bl_ins(here: int, target: int) -> bytes:
    return u32(0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def beq(here: int, target: int) -> bytes:
    return u32(0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def cmp_imm0(rn: int) -> bytes:
    return u32(0xE3500000 | (rn << 16))


def build_cave() -> bytes:
    code = bytearray(CAVE_LEN)
    struct.pack_into("<I", code, 0x00, int.from_bytes(cmp_imm0(0), "little"))  # cmp r0,#0
    struct.pack_into("<I", code, 0x04, int.from_bytes(beq(CAVE + 0x04, CAVE + 0x0C), "little"))
    struct.pack_into("<I", code, 0x08, int.from_bytes(bl_ins(CAVE + 0x08, CALL_TARGET), "little"))
    struct.pack_into("<I", code, 0x0C, int.from_bytes(b_ins(CAVE + 0x0C, RESUME), "little"))
    return bytes(code)


def apply_patch(data: bytearray) -> None:
    if bytes(data[SITE : SITE + 4]) != EXPECT_SITE:
        raise ValueError(
            f"unexpected bytes at site {SITE:#x}: "
            f"{data[SITE:SITE+4].hex()} (expected {EXPECT_SITE.hex()})"
        )
    region = bytes(data[CAVE : CAVE + CAVE_LEN])
    if region != b"\x00" * CAVE_LEN:
        raise ValueError(f"cave @{CAVE:#x} not empty: {region.hex()}")

    cave = build_cave()
    data[CAVE : CAVE + len(cave)] = cave
    data[SITE : SITE + 4] = b_ins(SITE, CAVE)

    print(f"[pane-registry-nullguard] site @{SITE:#x} -> cave @{CAVE:#x}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        build_cave()
        print("dry-run OK")
        return 0
    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar")

    dest = Path.home() / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")
    bak = dest.with_name(dest.name + ".bak_pre_pane_registry_nullguard")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)

    data = bytearray(dest.read_bytes())
    apply_patch(data)
    dest.write_bytes(data)
    shutil.copy2(dest, dest.parent.parent / "code.bin")
    print("Fully quit Azahar to reload exefs/code.bin.")
    print("Rollback: copy bak_pre_pane_registry_nullguard -> code.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
