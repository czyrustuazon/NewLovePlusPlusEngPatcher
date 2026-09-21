#!/usr/bin/env python3
"""Impersonate BOSS NsData so Watcher / city tables merge without a boss inject.

Cold-boot ``FUN_006096d8`` only needs two IPC results, then the stock apply
state machine (``FUN_006094c0`` / ``FUN_006088c8``) writes the blob into save:

  * ``FUN_00609ab0`` GetNsDataNewFlag → 1 after save is loaded and no applied
    header (``FUN_004e122c`` / ``FUN_004e1c68``).
  * ``FUN_00609ef4`` ReadNsData BLs → memcpy of vendored ``tools/spotpass/info.dat``.
  * State 1 ``ldrb +0x48`` → ``mov r0,#1`` so apply does not wait on the UI.

NewFlag stays 0 until save load (title idle + §16.7 skip = no nag) and after a
non-zero applied header (no every-boot re-merge). Payload lives in ``.rodata``
(NX on hardware). Stubs replace ``FUN_00609ab0`` in-place (RX).

Ghidra image base 0; runtime VA = file + ``0x100000``. See technical.md §16.8.

  python src/patch_spotpass_embed.py --dry-run
  python src/patch_spotpass_embed.py --deploy-azahar
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from patch_input_cave_map import ADDR_SPOTPASS_PAYLOAD  # noqa: E402

ROOT = _SRC.parent
INFO_DAT = ROOT / "tools" / "spotpass" / "info.dat"

ADDR_NEWFLAG = 0x00609AB0
NEWFLAG_LEN = 0x74
ADDR_CONFIRM = 0x00609750
ADDR_READ_BL1 = 0x00609FD8
ADDR_READ_BL2 = 0x0060A018

FUN_SAVE_READY = 0x004E122C  # FUN_004e122c
FUN_APPLIED_HDR = 0x004E1C68  # FUN_004e1c68

VANILLA_FUN = bytes.fromhex(
    "38402de90040a0e10050a0e30500a0e1c64efceb00008de5080094e50d20a0e1"
    "0210a0e3cdadffeb000050e30e00001a080094e5b400d0e1040050e30a00001a"
    "2c009fe50020a0e30316a0e3434ffceb00008de5080094e50d20a0e10310a0e3"
    "beadffeb000050e30150a0130500a0e13880bde8"
)
VANILLA_CONFIRM = bytes.fromhex("4800d4e5")  # ldrb r0, [r4, #0x48]
PATCHED_CONFIRM = bytes.fromhex("0100a0e3")  # mov r0, #1
VANILLA_READ_BL1 = bytes.fromhex("eb52fceb")  # bl FUN_0051eb8c
VANILLA_READ_BL2 = bytes.fromhex("db52fceb")

PAYLOAD_VA = ADDR_SPOTPASS_PAYLOAD + 0x100000


def _u32(word: int) -> bytes:
    return struct.pack("<I", word & 0xFFFFFFFF)


def _bl(here: int, target: int) -> bytes:
    return _u32(0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def _b_cond(cond: int, here: int, target: int) -> bytes:
    return _u32((cond << 28) | 0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def _bl_target(data: bytes, site: int) -> int | None:
    insn = int.from_bytes(data[site : site + 4], "little")
    if insn >> 24 != 0xEB:
        return None
    imm = insn & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    return site + 8 + (imm << 2)


def load_payload() -> bytes:
    if not INFO_DAT.is_file():
        raise FileNotFoundError(f"missing SpotPass payload {INFO_DAT}")
    blob = INFO_DAT.read_bytes()
    if len(blob) != 0x914:
        raise ValueError(f"{INFO_DAT} is {len(blob)} bytes, want 0x914")
    return blob


def build_newflag_cave(base: int = ADDR_NEWFLAG) -> bytes:
    """Return 1 only when save is loaded and the applied header is empty/missing."""
    done = base + 0x3C
    bne_here = base + 0x14
    bl_ready = base + 0x08
    bl_hdr = base + 0x1C
    blob = (
        _u32(0xE92D4010)  # stmdb sp!, {r4, lr}
        + _u32(0xE24DD028)  # sub sp, sp, #0x28
        + _bl(bl_ready, FUN_SAVE_READY)
        + _u32(0xE3500000)  # cmp r0, #0
        + _u32(0x13A00000)  # movne r0, #0
        + _b_cond(0x1, bne_here, done)  # bne done
        + _u32(0xE1A0000D)  # mov r0, sp
        + _bl(bl_hdr, FUN_APPLIED_HDR)
        + _u32(0xE3500000)  # cmp r0, #0
        + _u32(0xE3A00000)  # mov r0, #0
        + _u32(0xB3A00001)  # movlt r0, #1
        + _u32(0xE59D1000)  # ldr r1, [sp]
        + _u32(0xE59D2004)  # ldr r2, [sp, #4]
        + _u32(0xE1911002)  # orrs r1, r1, r2
        + _u32(0x03A00001)  # moveq r0, #1
        + _u32(0xE28DD028)  # add sp, sp, #0x28
        + _u32(0xE8BD8010)  # ldmia sp!, {r4, pc}
    )
    if len(blob) != 0x44:
        raise ValueError(f"newflag cave {len(blob):#x} != 0x44")
    return blob


def build_memcpy_cave(
    addr: int, payload_va: int = PAYLOAD_VA, size: int = 0x914
) -> bytes:
    """Copy ``size`` bytes from ``payload_va`` to r1; return count in r0.

    Caller buffer is vanilla ReadNsData ``0x7D004`` (> payload). No min().
    Byte loop so NULs in the NsData body are preserved (strncpy would clip).
    """
    blob = (
        _u32(0xE59F0014)  # ldr r0,  [pc, #0x14]  payload
        + _u32(0xE59FC014)  # ldr r12, [pc, #0x14]  size
        + _u32(0xE1A0300C)  # mov r3, r12
        + _u32(0xE4D02001)  # ldrb r2, [r0], #1
        + _u32(0xE4C12001)  # strb r2, [r1], #1
        + _u32(0xE2533001)  # subs r3, r3, #1
        + _b_cond(0x1, addr + 0x18, addr + 0x0C)  # bne loop
        + _u32(0xE1A0000C)  # mov r0, r12
        + _u32(0xE12FFF1E)  # bx lr
        + _u32(payload_va)
        + _u32(size)
    )
    if len(blob) != 0x2C:
        raise ValueError(f"memcpy cave {len(blob):#x} != 0x2c")
    return blob


def memcpy_addr(base: int = ADDR_NEWFLAG) -> int:
    return base + len(build_newflag_cave(base))


def build_function_blob(base: int = ADDR_NEWFLAG) -> bytes:
    newflag = build_newflag_cave(base)
    memcpy = build_memcpy_cave(base + len(newflag))
    blob = newflag + memcpy
    if len(blob) > NEWFLAG_LEN:
        raise ValueError(f"SpotPass stubs {len(blob):#x} > {NEWFLAG_LEN:#x}")
    return blob + b"\x00" * (NEWFLAG_LEN - len(blob))


def _payload_slice(data: bytes) -> bytes:
    return bytes(data[ADDR_SPOTPASS_PAYLOAD : ADDR_SPOTPASS_PAYLOAD + 0x914])


def is_vanilla(data: bytes) -> bool:
    if len(data) < ADDR_SPOTPASS_PAYLOAD + 0x914:
        return False
    return (
        data[ADDR_NEWFLAG : ADDR_NEWFLAG + NEWFLAG_LEN] == VANILLA_FUN
        and data[ADDR_CONFIRM : ADDR_CONFIRM + 4] == VANILLA_CONFIRM
        and data[ADDR_READ_BL1 : ADDR_READ_BL1 + 4] == VANILLA_READ_BL1
        and data[ADDR_READ_BL2 : ADDR_READ_BL2 + 4] == VANILLA_READ_BL2
        and _payload_slice(data) == b"\x00" * 0x914
    )


def is_patched(data: bytes) -> bool:
    if len(data) < ADDR_SPOTPASS_PAYLOAD + 0x914:
        return False
    try:
        payload = load_payload()
    except (OSError, ValueError):
        return False
    stub = build_function_blob()
    memcpy = memcpy_addr()
    return (
        data[ADDR_NEWFLAG : ADDR_NEWFLAG + NEWFLAG_LEN] == stub
        and data[ADDR_CONFIRM : ADDR_CONFIRM + 4] == PATCHED_CONFIRM
        and _bl_target(data, ADDR_READ_BL1) == memcpy
        and _bl_target(data, ADDR_READ_BL2) == memcpy
        and _payload_slice(data) == payload
    )


def apply_patch(data: bytearray) -> bool:
    """Embed NsData + spoof NewFlag/ReadNsData. Returns True if bytes changed."""
    if is_patched(data):
        print("[spotpass-embed] already patched (NewFlag latch + ReadNsData memcpy)")
        return False
    if not is_vanilla(data):
        got = data[ADDR_NEWFLAG : ADDR_NEWFLAG + 8].hex()
        raise ValueError(
            f"unexpected GetNsDataNewFlag @{ADDR_NEWFLAG:#x}: {got} "
            "(want vanilla FUN_00609ab0 + zero .rodata pad)"
        )
    payload = load_payload()
    stub = build_function_blob()
    memcpy = memcpy_addr()
    data[ADDR_NEWFLAG : ADDR_NEWFLAG + NEWFLAG_LEN] = stub
    data[ADDR_CONFIRM : ADDR_CONFIRM + 4] = PATCHED_CONFIRM
    data[ADDR_READ_BL1 : ADDR_READ_BL1 + 4] = _bl(ADDR_READ_BL1, memcpy)
    data[ADDR_READ_BL2 : ADDR_READ_BL2 + 4] = _bl(ADDR_READ_BL2, memcpy)
    data[ADDR_SPOTPASS_PAYLOAD : ADDR_SPOTPASS_PAYLOAD + len(payload)] = payload
    print(
        f"[spotpass-embed] NewFlag latch @{ADDR_NEWFLAG:#x}, "
        f"ReadNsData memcpy @{memcpy:#x}, "
        f"payload {len(payload)} B @ {ADDR_SPOTPASS_PAYLOAD:#x} "
        "(Watcher #28 without BOSS inject)"
    )
    return True


def revert_patch(data: bytearray) -> bool:
    if is_vanilla(data):
        print("[spotpass-embed] already vanilla")
        return False
    if not is_patched(data):
        raise ValueError("cannot revert: SpotPass embed is neither vanilla nor patched")
    data[ADDR_NEWFLAG : ADDR_NEWFLAG + NEWFLAG_LEN] = VANILLA_FUN
    data[ADDR_CONFIRM : ADDR_CONFIRM + 4] = VANILLA_CONFIRM
    data[ADDR_READ_BL1 : ADDR_READ_BL1 + 4] = VANILLA_READ_BL1
    data[ADDR_READ_BL2 : ADDR_READ_BL2 + 4] = VANILLA_READ_BL2
    data[ADDR_SPOTPASS_PAYLOAD : ADDR_SPOTPASS_PAYLOAD + 0x914] = b"\x00" * 0x914
    print("[spotpass-embed] restored vanilla GetNsDataNewFlag / ReadNsData / .rodata pad")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    stub = build_function_blob()
    memcpy = memcpy_addr()
    payload = load_payload()
    if args.dry_run:
        print(
            f"FUN_00609ab0 @{ADDR_NEWFLAG:#x}: NewFlag latch 0x44 + "
            f"memcpy @{memcpy:#x} (0x2c), pad {NEWFLAG_LEN - 0x70:#x}"
        )
        print(
            f"ReadNsData BLs @{ADDR_READ_BL1:#x}/@{ADDR_READ_BL2:#x} -> {memcpy:#x}"
        )
        print(
            f"auto-confirm @{ADDR_CONFIRM:#x} ldrb +0x48 -> mov r0,#1"
        )
        print(
            f"payload {len(payload)} B @ {ADDR_SPOTPASS_PAYLOAD:#x} "
            f"(VA {PAYLOAD_VA:#x})"
        )
        print(f"stub {len(stub)} B")
        return 0

    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar (or import apply_patch)")

    from nlpp_paths import AZAHAR_MOD_CODE, AZAHAR_MOD_ROOT

    dest = AZAHAR_MOD_CODE
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")

    bak = dest.with_name(dest.name + ".bak_pre_spotpass_embed")
    if not bak.exists():
        shutil.copy2(dest, bak)
        print("backup", bak)

    data = bytearray(dest.read_bytes())
    if args.revert:
        revert_patch(data)
    else:
        apply_patch(data)
    dest.write_bytes(data)
    shutil.copy2(dest, AZAHAR_MOD_ROOT / "code.bin")
    print("Fully quit Azahar so LayeredFS reloads exefs/code.bin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
