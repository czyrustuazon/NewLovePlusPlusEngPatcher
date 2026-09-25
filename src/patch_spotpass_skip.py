#!/usr/bin/env python3
"""Skip the boot “No SpotPass data found.” nag when BOSS NsData is missing.

The string is TRB pack ``0x1901`` STRI 4808 (slots ``0x1e6`` / ``0x1e7``).
``FUN_0059a010`` is heap-arena stats, not DrawText.

Boot UI ``FUN_000ea254`` state 0 binds slot ``0x1e7`` through
``FUN_002626e8`` → ``FUN_004b119c``, shows it with
``FUN_004b17b0(pane, 0x2b61)``, then **opens** ``FUN_000ea964`` (layout
id ``0x3074``) — that is the empty warning window after the TRB wipe.
``FUN_00319320`` @ ``0x000EED44`` is a later SysPopup of slot ``0x1e6``.

Patch:

  * Hide ``FUN_000ea254`` ctor layout ``+0xa8`` then dismiss to state 7
    (``0x001EA6C4``) so the empty warning window never stays up.
  * NOP ``bl FUN_004b17b0`` (0x2b61 show) and ``bl FUN_004b119c`` (0x1e7 pane).
  * State 4 tail ``b FUN_004b17b0`` @ ``0x000EA628`` → ``bx lr`` (BL NOPs miss this).
  * Sister tick ``FUN_000ebe0c``: skip ``FUN_000eb3bc`` start-apply, and
    ``mov r1,#1/#3/#4`` → ``#7`` so applying-wait never sticks.
  * Title    UIOperator: skip ``+0x8c`` fail flag and pack ``0xd201`` DrawText.
    State 1 still shows ``+0x90`` (cafe overlay). Overlay
    24–31 / 41–42 idle-stay. ``CommunicationOptionUIOperator`` pack
    ``0xd201`` ERROR DrawText is skipped (Communication Settings DATA).
    Title init state 8 leaves ``+0x90`` up, skips the apply-done wait and
    ``FUN_00196b7c`` busy stay, then creates layout 49 (title attract).
    ``FUN_0014ed0c`` state 1 with ``+0x85==0`` still enters the Name Card
    setup at ``0x14EEC8``. The following ``mov`` goes to state 2 (the
    right-hand bars) instead of state 22. Apply states 22+ stay idle.
  * Overlay show/wait helpers stay vanilla (function-level stubs blanked
    title attract). Boot UI still NOPs its own ``FUN_00443cd8`` call sites.
  * NOP ``bl FUN_00319320`` @ ``0x000EED44`` (keep ``strb [obj,#0x5a]=1``).
  * Unconditional skip of the type-2 site (``beq`` → ``b`` @ ``0x0011021C``).
  * NOP leftover ``bl FUN_0059a010`` in NetDlTaskManager.
  * Jump table state 0 ``0x00709708`` → ``0x00709734`` (NewFlag only).
  * ``moveq r0, #4`` → ``moveq r0, #0`` so a missing CDN stays idle.

Does **not** apply Towano Watcher / city tables — that is
``patch_spotpass_embed.py`` (technical.md §16.8). Does **not** gate Enoshima
(already on-cart).

Ghidra image base 0; runtime VA = file + ``0x100000``. See technical.md §16.7.

  python src/patch_spotpass_skip.py --dry-run
  python src/patch_spotpass_skip.py --deploy-azahar
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

FUN_DIALOG = 0x0059A010
FUN_SYSPOPUP = 0x00319320
FUN_PANE_TEXT = 0x004B119C
FUN_PANE_SHOW = 0x004B17B0
FUN_LAYOUT_VIS = 0x0044DFA4
NOP = bytes.fromhex("0000a0e1")  # mov r0, r0

# Boot UI FUN_000ee9f0 state 3: bl FUN_00319320(..., slot 0x1e6)
ADDR_NODATA_BL = 0x000EED44
# Second 0x1e6 SysPopup (type 2): beq skip → always skip
ADDR_NODATA2_BEQ = 0x0011021C
VANILLA_NODATA2_BEQ = bytes.fromhex("0f00000a")  # beq 0x00110260
PATCHED_NODATA2_BEQ = bytes.fromhex("0f0000ea")  # b 0x00110260

# Boot UI binds slot 0x1e7 (same STRI) via FUN_002626e8 → FUN_004b119c.
# 0xEA2D0 = state 0 default sentence; 0x110298 = type-2 pane.
BIND_SITES = (
    0x0005FDD0,
    0x00060464,
    0x000EA2D0,
    0x000EB128,
    0x000EE5D0,
    0x000EEFF4,
    0x00110298,
    0x0017A7E0,
)
# TitleUI 0x2C8090/0x2C809C stay vanilla (msgid 0x2b61, blanked TRB).

# FUN_000ea254 ldrcc-pc table @ 0x000EA280: state 0 opens FUN_000ea964.
ADDR_UI_JT0 = 0x000EA280
VANILLA_UI_JT0 = bytes.fromhex("a0a21e00")  # 0x001EA2A0
OLD_DISMISS_UI_JT0 = bytes.fromhex("c4a61e00")  # 0x001EA6C4 skip-without-hide
# FUN_000ea964 opens layout id 0x3074 (empty warning / apply chrome).
ADDR_OPEN_WARN = 0x000EA964
VANILLA_OPEN_WARN = bytes.fromhex("f04f2de9")  # stmdb {r4-r11, lr}
PATCHED_OPEN_WARN = bytes.fromhex("1eff2fe1")  # bx lr

# Hide ctor layout at +0xa8 then jump to dismiss 0xEA6C4. Overwrites state 0 head.
ADDR_STATE0 = 0x000EA2A0
VANILLA_STATE0 = bytes.fromhex("0d00a0e17a6010ebd000cde10020a0e3f801cde138049fe5")
STATE0_LEN = 24

# FUN_004b17b0(pane, 0x2b61) maps to slot 0x1e7 and actually *shows* the nag.
SHOW_SITES = (
    0x0005FDDC,
    0x00060470,
    0x000EA2DC,
    0x000EE5DC,
    0x000EF000,
    0x0017A7EC,
)

# State 4 is a tail-call `b FUN_004b17b0` (not a BL), so SHOW_SITES miss it.
# FUN_000ebe0c sends the same object here after FUN_000ea964 returns.
ADDR_STATE4_SHOW = 0x000EA628
VANILLA_STATE4_SHOW = bytes.fromhex("601c0fea")  # b FUN_004b17b0
PATCHED_STATE4_SHOW = bytes.fromhex("1eff2fe1")  # bx lr

# FUN_000ebe0c: state 1 is applying-wait (FUN_0062fa8c / save IPC).
# After ea964 no-op, mov r1,#1/#4/#3 then b FUN_000ea218.
ADDR_EBE_START = 0x000EBE8C  # bl FUN_000eb3bc
VANILLA_EBE_START = bytes.fromhex("4afdffeb")
ADDR_EBE_ST1 = 0x000EBECC
VANILLA_EBE_ST1 = bytes.fromhex("0110a0e3")  # mov r1, #1
ADDR_EBE_ST4 = 0x000EBF20
VANILLA_EBE_ST4 = bytes.fromhex("0410a0e3")  # mov r1, #4
ADDR_EBE_ST3 = 0x000EBF44
VANILLA_EBE_ST3 = bytes.fromhex("0310a0e3")  # mov r1, #3
PATCHED_EBE_STATE = bytes.fromhex("0710a0e3")  # mov r1, #7

# TitleUIOperator fail: FUN_00443e18 != 0 → +0x8c=1 / +0x5c=0xb → pack 0xd201.
ADDR_TITLE_FAIL_BEQ = 0x002C6E18
VANILLA_TITLE_FAIL_BEQ = bytes.fromhex("2501000a")  # beq 0x002C72B4
PATCHED_TITLE_FAIL_BEQ = bytes.fromhex("250100ea")  # b 0x002C72B4
ADDR_TITLE_FAIL_STORES = 0x002C6E1C
VANILLA_TITLE_FAIL_STORES = bytes.fromhex("0110a0e3")  # mov r1, #1
PATCHED_TITLE_FAIL_STORES = bytes.fromhex("240100ea")  # b 0x002C72B4
ADDR_TITLE_D201 = 0x002C718C
VANILLA_TITLE_D201 = bytes.fromhex("8c00d6e5")  # ldrb r0, [r6, #0x8c]
PATCHED_TITLE_D201 = bytes.fromhex("480000ea")  # b 0x002C72B4

# FUN_000ee9f0 (SysPopup parent): after skipped no-data, +0xf0==0
# does mov r1,#6 → applying-wait (FUN_0062fa8c). Dismiss instead.
ADDR_EE9_JT6 = 0x000EEA28
VANILLA_EE9_JT6 = bytes.fromhex("dcee1e00")  # 0x001EEEDC wait
PATCHED_EE9_JT6 = bytes.fromhex("0cef1e00")  # 0x001EEF0C hide+state 7
ADDR_EE9_ST6 = 0x000EEE1C
VANILLA_EE9_ST6 = bytes.fromhex("0610a0e3")  # mov r1, #6
PATCHED_EE9_ST6 = bytes.fromhex("0710a0e3")  # mov r1, #7

# Applying spinner: FUN_0062fa8c r0==0 stays in the wait state; r0!=0
# falls through to pack 0x1901 DrawText (“Applying SpotPass…”). Forcing
# r0=1 therefore *showed* the spinner. Hide +0xd0 then always epilogue.
FUN_APPLY_WAIT = 0x0062FA8C
FUN_APPLY_SHOW = 0x00443CD8
FUN_APPLY_HIDE = 0x00443BA8
FUN_APPLY_WAIT_OV = 0x00443E18
PATCHED_BX_LR = bytes.fromhex("1eff2fe1")  # bx lr
VANILLA_SHOW_FN = bytes.fromhex("70402de9")  # stmdb {r4-r6, lr}
VANILLA_WAIT_OV_FN = bytes.fromhex("70402de90040a0e1")  # stmdb; mov r4, r0
PATCHED_WAIT_OV_FN = bytes.fromhex("0100a0e31eff2fe1")  # mov r0, #1; bx lr
WAIT_APPLY_HEAD_LEN = 20
VANILLA_WAIT_APPLY_HEAD = bytes.fromhex(
    "480090e5000050e30500000a18009fe5000090e5"
)
# TitleUI state 2 stays forever while FUN_0026c9ac returns 0.
ADDR_TITLE_ST2_STAY = 0x002C63A8
VANILLA_TITLE_ST2_STAY = bytes.fromhex("c103000a")  # beq 0x2C72B4
WAIT_LEN = 16
WAIT_AFTER = bytes.fromhex("000050e300f020e3")  # cmp r0,#0; nop
WAIT_SITES = (
    0x000EB860,
    0x000EBF5C,
    0x000EC3C0,
    0x000EC990,
    0x000ECA94,
    0x000EEEE8,
    0x000EF0F4,
    0x000EF240,
)
WAIT_EPILOGUE = {
    0x000EB860: 0x000EBA68,
    0x000EBF5C: 0x000EC17C,
    0x000EC3C0: 0x000EC5C8,
    0x000EC990: 0x000ECCBC,
    0x000ECA94: 0x000ECCBC,
    0x000EEEE8: 0x000EEF54,
    0x000EF0F4: 0x000EF098,
    0x000EF240: 0x000EF098,
}
SHOW_APPLY_SITES = (
    0x000E0EAC,
    0x000EBA30,
    0x000EC12C,
    0x000EC590,
    0x000ECC6C,
    0x000EEDF4,
    0x000EF08C,
    0x000EF384,
)
# Same show, but tail `b FUN_00443cd8` (BL list misses these).
SHOW_APPLY_TAILS = (
    0x000EB814,
    0x000EBF10,
    0x000EC374,
    0x000EC950,
    0x000EF1F0,
)

# FUN_0014ed0c is the Name Card operator as well as save/boot DATA apply.
# State 1 with +0x85==0 beqs to 0x14EEC8, which fades in the card panes
# (group 1 slots 1–3) and the pack 0x9d00 slot 0xc help. Sending that beq
# to 0x150658 left the main-menu Name Card as an empty folder. Keep the
# beq. The mov at 0x14EFE8 goes to state 2 (FUN_0014d584 draws the
# right-hand bars). Apply states 22+ stay at 21. Overlay 24–31 / 41–42
# idle-stay.
ADDR_14ED_ST1_DATA = 0x0014EE3C  # beq 0x14EEC8 Name Card setup
VANILLA_14ED_ST1_DATA = bytes.fromhex("2100000a")
PATCHED_14ED_ST1_DATA = VANILLA_14ED_ST1_DATA
OLD_14ED_ST1_SKIP = bytes.fromhex("0506000a")  # beq 0x150658, hid the card
ADDR_14B890_MULTIWIN = 0x0014B94C  # beq 0x14B988 MultiWin
VANILLA_14B890_MULTIWIN = bytes.fromhex("0d00000a")
ADDR_14E648_ERROR = 0x0014E7B0  # beq 0x14E808 DrawText ERROR
VANILLA_14E648_ERROR = bytes.fromhex("1400000a")
PATCHED_14E648_ERROR = bytes.fromhex("5400000a")  # beq 0x14E908 epilogue
ADDR_14ED_ST3_MULTIWIN = 0x0014FC04  # blne FUN_00255a18 idx 0x16
VANILLA_14ED_ST3_MULTIWIN = bytes.fromhex("8317041b")
ADDR_14ED_TO_APPLY = (
    0x0014EFE8,  # 1 → 22
    0x0014F020,  # 22 → 23
    0x0014F068,  # 23 → 24
    0x0014F0E4,  # 14F080 → 41
    0x0014FB14,  # → 26
    0x0014FDA0,
    0x0014FDC4,
    0x001500A8,
)
VANILLA_14ED_TO_APPLY = {
    0x0014EFE8: bytes.fromhex("1610a0e3"),  # mov r1, #22
    0x0014F020: bytes.fromhex("1710a0e3"),  # mov r1, #23
    0x0014F068: bytes.fromhex("1810a0e3"),  # mov r1, #24
    0x0014F0E4: bytes.fromhex("2910a0e3"),  # mov r1, #41
    0x0014FB14: bytes.fromhex("1a10a0e3"),  # mov r1, #26
    0x0014FDA0: bytes.fromhex("1a10a0e3"),
    0x0014FDC4: bytes.fromhex("1a10a0e3"),
    0x001500A8: bytes.fromhex("1a10a0e3"),
}
PATCHED_14ED_TO_APPLY = bytes.fromhex("1510a0e3")  # mov r1, #21 idle stay
PATCHED_14ED_NAMECARD = bytes.fromhex("0210a0e3")  # mov r1, #2  Name Card bars


def patched_14ed_mov(site: int) -> bytes:
    """Name Card setup asks for state 2. Later apply slots stay idle."""
    if site == 0x0014EFE8:
        return PATCHED_14ED_NAMECARD
    return PATCHED_14ED_TO_APPLY


ADDR_14ED_JT = 0x0014ED2C
_14ED_APPLY_SLOTS = tuple(range(24, 32)) + (41, 42)
VANILLA_14ED_JT_APPLY_FILE = {
    24: 0x0014F0FC,
    25: 0x0014F188,
    26: 0x0014F1DC,
    27: 0x0014F268,
    28: 0x0014F2F0,
    29: 0x0014F388,
    30: 0x0014F3CC,
    31: 0x0014F518,
    41: 0x00150554,
    42: 0x001505DC,
}
ADDR_14ED_STAY = 0x00150658
ADDR_14ED_ST31 = 0x0014F518
ADDR_14ED_WAIT_STAY = (
    0x0014F060,  # ST23 +1==0 beq 0x14F080 (FUN_0014c68c → state 41)
    0x0014F168,  # ST24 show fail beq stay
    0x0014F198,  # ST25 overlay-wait beq stay
    0x0014F30C,  # WAIT_APPLY beq stay
    0x0014F31C,  # WAIT_APPLY bne stay
)
VANILLA_14ED_WAIT_STAY = {
    0x0014F060: bytes.fromhex("0600000a"),
    0x0014F168: bytes.fromhex("3a05000a"),
    0x0014F198: bytes.fromhex("2e05000a"),
    0x0014F30C: bytes.fromhex("d104000a"),
    0x0014F31C: bytes.fromhex("cd04001a"),
}
ADDR_14ED_ERROR = 0x0014F4C0  # mov r1, #31  blank ERROR
VANILLA_14ED_ERROR = bytes.fromhex("1f10a0e3")  # mov r1, #0x1f
PATCHED_14ED_ERROR = bytes.fromhex("0310a0e3")  # mov r1, #3  back to menu
# CommunicationOptionUIOperator @ 0x10EF5C state 3: pack 0xd201 DrawText
# r1=#2 (ERROR chrome). Slot 0/1 body is blanked TRB — empty ERROR.
ADDR_COMMOPT_D201 = 0x0010F20C  # beq 0x10F234 (no dialog obj)
VANILLA_COMMOPT_D201 = bytes.fromhex("0800000a")
PATCHED_COMMOPT_D201 = bytes.fromhex("080000ea")  # b 0x10F234
ADDR_COMMOPT_D201_FAIL = 0x0010F594  # mov r2,#1 then fail DrawText
VANILLA_COMMOPT_D201_FAIL = bytes.fromhex("0120a0e3")
PATCHED_COMMOPT_D201_FAIL = bytes.fromhex("280000ea")  # b 0x10F63C stay


def _14ed_jt_off(slot: int) -> int:
    return ADDR_14ED_JT + slot * 4


def _14ed_jt_va(file_off: int) -> bytes:
    return struct.pack("<I", file_off + 0x100000)


PATCHED_14ED_JT_APPLY = _14ed_jt_va(ADDR_14ED_STAY)


# TitleUIOperator @ 0x2C6284: states 1–5 overlay / loading spinner; 8 is
# title init (FUN_00195fa4). 6/7 applying. Stub apply only.
# State 8 waits FUN_00443e18 then FUN_00196b7c; apply-done never arrives.
# State 1 still shows +0x90 (cafe). FUN_0014ed0c DATA apply idles after
# the type-0xf kick (22→21) so 14F080 / state 41 DrawText never runs.
ADDR_TITLE_CMP_MAX = 0x002C629C
VANILLA_TITLE_CMP_MAX = bytes.fromhex("200050e3")  # cmp r0, #0x20
ADDR_TITLE_OOR = 0x002C62A4
VANILLA_TITLE_OOR = bytes.fromhex("020400ea")  # b 0x2C72B4
# FUN_004b2574 type 2 → pack 0x1901 slot 0x1e5 applying SysPopup.
# Skipping only the ldreq still joined the SysPopup at 0x4B2660.
ADDR_TYPE2_1E5 = 0x004B2634
VANILLA_TYPE2_1E5 = bytes.fromhex("a4619f05")  # ldreq r6, [pc, #0x1a4]
ADDR_TYPE2_EPILOGUE = 0x004B27CC
ADDR_TITLE_ST6_SHOW = 0x002C6C84
VANILLA_TITLE_ST6_SHOW = bytes.fromhex("13f4051b")  # blne FUN_00443cd8
ADDR_TITLE_ST1_SHOW = 0x002C6374
VANILLA_TITLE_ST1_SHOW = bytes.fromhex("57f6051b")  # blne FUN_00443cd8
ADDR_TITLE_ST8_HEAD = 0x002C64E8
VANILLA_TITLE_ST8_HEAD = bytes.fromhex("900096e5")  # ldr r0, [r6, #0x90]
ADDR_TITLE_ST8_SKIP = 0x002C64EC
VANILLA_TITLE_ST8_SKIP = bytes.fromhex("000050e3")  # cmp r0, #0
PATCHED_TITLE_ST8_SKIP = bytes.fromhex("040000ea")  # b 0x2C6504
ADDR_TITLE_ST8_GATE = 0x002C64F0
VANILLA_TITLE_ST8_GATE = bytes.fromhex("0300000a")  # beq 0x2C6504
ADDR_TITLE_ST8_POLL = 0x002C64F4
VANILLA_TITLE_ST8_POLL = bytes.fromhex("47f605eb")  # bl FUN_00443e18
ADDR_TITLE_ST8_STAY = 0x002C6500
VANILLA_TITLE_ST8_STAY = bytes.fromhex("6b03000a")  # beq 0x2C72B4
ADDR_TITLE_ST8_READY = 0x002C6518
VANILLA_TITLE_ST8_READY = bytes.fromhex("6503001a")  # bne 0x2C72B4
ADDR_TITLE_ST8_LAYOUT = 0x002C6588
VANILLA_TITLE_ST8_LAYOUT = bytes.fromhex("853efbeb")  # bl FUN_00195fa4 layout 49
ADDR_TITLE_ST18_STAY = 0x002C66DC
VANILLA_TITLE_ST18_STAY = bytes.fromhex("f40200ba")  # blt 0x2C72B4 timer not elapsed
ADDR_TITLE_ST8_TAIL = 0x002C6678
VANILLA_TITLE_ST8_TAIL = bytes.fromhex("1200a0e3")  # mov r0, #0x12
ADDR_TITLE_ST8_TAIL2 = 0x002C667C
VANILLA_TITLE_ST8_TAIL2 = bytes.fromhex("00f020e3")  # nop
ADDR_TITLE_HIDE_CAVE = 0x002C6CB8  # unused state-7 body (jt 7 → stub)
HIDE_CAVE_LEN = 40
VANILLA_TITLE_HIDE_CAVE = bytes.fromhex(
    "840096e5001090e5781091e531ff2fe1000050e37801001a0020a0e3840096e50210a0e1ad290deb"
)
ADDR_TITLE_STUB = 0x002C6C28
TITLE_STUB_LEN = 24
VANILLA_TITLE_STUB = bytes.fromhex("900096e5000050e30300000a0000a0e3000050e300f020e3")
ADDR_TITLE_JT = 0x002C62A8
TITLE_JT_SLOTS = (6, 7, 10, 11, 12, 15)
VANILLA_TITLE_JT = {
    6: bytes.fromhex("286c3c00"),
    7: bytes.fromhex("b86c3c00"),
    10: bytes.fromhex("006e3c00"),
    11: bytes.fromhex("546e3c00"),
    12: bytes.fromhex("7c6f3c00"),
    15: bytes.fromhex("a86f3c00"),
}
PATCHED_TITLE_JT_VA = bytes.fromhex("286c3c00")  # stub @ 0x2C6C28
ADDR_TITLE_SET_STATE = 0x002C7258
# Keep vanilla TitleUI ctor msgid 0x2b61 (no-data, blanked). Do not retarget
# to applying 0x2b5f — that replaced title Communication copy.
ADDR_TITLE_MSGID = 0x002C8180
VANILLA_TITLE_MSGID = bytes.fromhex("612b0000")

# ctor 608738/608820, reset 608efc/608f40, +0x45 pump 608f9c/609050,
# tick state 0 609710, dtor 6097e4/609888
DIALOG_SITES = (
    0x00608738,
    0x00608820,
    0x00608EFC,
    0x00608F40,
    0x00608F9C,
    0x00609050,
    0x00609710,
    0x006097E4,
    0x00609888,
)

# ldrcc pc, [pc, r0, lsl #2] table @ 0x006096FC: state 0/1/2 VAs.
ADDR_JT0 = 0x006096FC
VANILLA_JT0 = bytes.fromhex("08977000")  # 0x00709708 FUN_0059a010 then NewFlag
PATCHED_JT0 = bytes.fromhex("34977000")  # 0x00709734 NewFlag only

# cmp r0,#0 / moveq r0,#4 / strbeq r0,[r4,#0x46] / beq epilogue
ADDR_CMP = 0x0060973C
ADDR_MOVEQ = 0x00609740
VANILLA_CMP = bytes.fromhex("000050e3")
VANILLA_MOVEQ = bytes.fromhex("0400a003")  # moveq r0, #4
PATCHED_MOVEQ = bytes.fromhex("0000a003")  # moveq r0, #0
VANILLA_STRB = bytes.fromhex("4600c405")  # strbeq r0, [r4, #0x46]


def _bl(here: int, target: int) -> bytes:
    return struct.pack("<I", 0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def _b(here: int, target: int) -> bytes:
    return struct.pack("<I", 0xEA000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def _beq(here: int, target: int) -> bytes:
    return struct.pack("<I", 0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def _blne(here: int, target: int) -> bytes:
    return struct.pack("<I", 0x1B000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def build_state0_hide() -> bytes:
    """Hide ctor layout +0xa8 then take the state-7 dismiss path."""
    blob = (
        bytes.fromhex("a80094e5")  # ldr r0, [r4, #0xa8]
        + bytes.fromhex("000050e3")  # cmp r0, #0
        + bytes.fromhex("0100000a")  # beq skip bl
        + bytes.fromhex("0010a0e3")  # mov r1, #0
        + _bl(ADDR_STATE0 + 0x10, FUN_LAYOUT_VIS)
        + _b(ADDR_STATE0 + 0x14, 0x000EA6C4)
    )
    if len(blob) != STATE0_LEN:
        raise ValueError(f"state0 hide {len(blob)} != {STATE0_LEN}")
    return blob


PATCHED_STATE0 = build_state0_hide()


def build_title_dismiss_stub() -> bytes:
    """Hide TitleUI +0x90 applying layout and force +0x5c idle."""
    blob = (
        bytes.fromhex("900096e5")  # ldr r0, [r6, #0x90]
        + bytes.fromhex("000050e3")  # cmp r0, #0
        + bytes.fromhex("0000000a")  # beq skip bl (pc+8)
        + _bl(ADDR_TITLE_STUB + 0xC, FUN_APPLY_HIDE)
        + bytes.fromhex("0000a0e3")  # mov r0, #0
        + _b(ADDR_TITLE_STUB + 0x14, ADDR_TITLE_SET_STATE)
    )
    if len(blob) != TITLE_STUB_LEN:
        raise ValueError(f"title dismiss stub {len(blob)} != {TITLE_STUB_LEN}")
    return blob


PATCHED_TITLE_STUB = build_title_dismiss_stub()
PATCHED_TYPE2_1E5 = _beq(ADDR_TYPE2_1E5, ADDR_TYPE2_EPILOGUE)


def build_title_hide_cave() -> bytes:
    """Hide TitleUI +0x90, clear layout ptr, drop the overlay slot."""
    blob = (
        bytes.fromhex("10402de9")  # stmdb sp!, {r4, lr}
        + bytes.fromhex("904096e5")  # ldr r4, [r6, #0x90]
        + bytes.fromhex("000054e3")  # cmp r4, #0
        + bytes.fromhex("0400000a")  # beq pop
        + bytes.fromhex("0400a0e1")  # mov r0, r4
        + _bl(ADDR_TITLE_HIDE_CAVE + 0x14, FUN_APPLY_HIDE)
        + bytes.fromhex("0010a0e3")  # mov r1, #0
        + bytes.fromhex("481084e5")  # str r1, [r4, #0x48]
        + bytes.fromhex("901086e5")  # str r1, [r6, #0x90]
        + bytes.fromhex("1080bde8")  # ldmia sp!, {r4, pc}
    )
    if len(blob) != HIDE_CAVE_LEN:
        raise ValueError(f"title hide cave {len(blob)} != {HIDE_CAVE_LEN}")
    return blob


PATCHED_TITLE_HIDE_CAVE = build_title_hide_cave()
PATCHED_TITLE_ST8_HEAD = _bl(ADDR_TITLE_ST8_HEAD, ADDR_TITLE_HIDE_CAVE)


def build_wait_apply_stub() -> bytes:
    """Hide the overlay in r0, then return 0 so callers do not DrawText."""
    here = FUN_APPLY_WAIT
    blob = (
        bytes.fromhex("00402de9")  # stmdb sp!, {lr}
        + _bl(here + 4, FUN_APPLY_HIDE)
        + bytes.fromhex("0040bde8")  # ldmia sp!, {lr}
        + bytes.fromhex("0000a0e3")  # mov r0, #0
        + PATCHED_BX_LR
    )
    if len(blob) != WAIT_APPLY_HEAD_LEN:
        raise ValueError(f"wait-apply stub {len(blob)} != {WAIT_APPLY_HEAD_LEN}")
    return blob


PATCHED_WAIT_APPLY_HEAD = build_wait_apply_stub()


def _bl_to_dialog(here: int) -> bytes:
    return _bl(here, FUN_DIALOG)


def _bl_to_syspopup(here: int = ADDR_NODATA_BL) -> bytes:
    return _bl(here, FUN_SYSPOPUP)


def _bl_to_bind(here: int) -> bytes:
    return _bl(here, FUN_PANE_TEXT)


def _bl_to_show(here: int) -> bytes:
    return _bl(here, FUN_PANE_SHOW)


def _bl_to_wait(here: int) -> bytes:
    return _bl(here, FUN_APPLY_WAIT)


def _bl_to_apply_show(here: int) -> bytes:
    return _bl(here, FUN_APPLY_SHOW)


def _bl_to_apply_hide(here: int) -> bytes:
    return _bl(here, FUN_APPLY_HIDE)


def _b_to_apply_show(here: int) -> bytes:
    return _b(here, FUN_APPLY_SHOW)


def _wait_vanilla_bytes(site: int) -> bytes:
    return (
        _bl_to_wait(site)
        + WAIT_AFTER
        + _beq(site + 12, WAIT_EPILOGUE[site])
    )


def _wait_patched_bytes(site: int) -> bytes:
    """Hide +0xd0 then return; do not fall through to applying DrawText."""
    return (
        bytes.fromhex("d00094e5")  # ldr r0, [r4, #0xd0]
        + bytes.fromhex("000050e3")  # cmp r0, #0
        + _blne(site + 8, FUN_APPLY_HIDE)
        + _b(site + 12, WAIT_EPILOGUE[site])
    )


def _wait_vanilla(data: bytes) -> bool:
    return all(
        data[site : site + WAIT_LEN] == _wait_vanilla_bytes(site)
        for site in WAIT_SITES
    )


def _wait_patched(data: bytes) -> bool:
    return all(
        data[site : site + WAIT_LEN] == _wait_patched_bytes(site)
        for site in WAIT_SITES
    )


def _apply_wait(data: bytearray) -> None:
    for site in WAIT_SITES:
        data[site : site + WAIT_LEN] = _wait_patched_bytes(site)


def _apply_show_nops(data: bytes) -> bool:
    return all(data[site : site + 4] == NOP for site in SHOW_APPLY_SITES)


def _apply_show_vanilla(data: bytes) -> bool:
    return all(
        data[site : site + 4] == _bl_to_apply_show(site) for site in SHOW_APPLY_SITES
    )


def _apply_show_apply(data: bytearray) -> None:
    for site in SHOW_APPLY_SITES:
        data[site : site + 4] = NOP
    for site in SHOW_APPLY_TAILS:
        data[site : site + 4] = PATCHED_BX_LR


def _title_jt_off(slot: int) -> int:
    return ADDR_TITLE_JT + slot * 4


def _title_vanilla(data: bytes) -> bool:
    if data[ADDR_TITLE_STUB : ADDR_TITLE_STUB + TITLE_STUB_LEN] != VANILLA_TITLE_STUB:
        return False
    if data[ADDR_TITLE_ST1_SHOW : ADDR_TITLE_ST1_SHOW + 4] != VANILLA_TITLE_ST1_SHOW:
        return False
    if data[ADDR_TITLE_ST2_STAY : ADDR_TITLE_ST2_STAY + 4] != VANILLA_TITLE_ST2_STAY:
        return False
    if data[ADDR_TITLE_ST6_SHOW : ADDR_TITLE_ST6_SHOW + 4] != VANILLA_TITLE_ST6_SHOW:
        return False
    if data[ADDR_TITLE_ST8_HEAD : ADDR_TITLE_ST8_HEAD + 4] != VANILLA_TITLE_ST8_HEAD:
        return False
    if data[ADDR_TITLE_ST8_SKIP : ADDR_TITLE_ST8_SKIP + 4] != VANILLA_TITLE_ST8_SKIP:
        return False
    if data[ADDR_TITLE_ST8_GATE : ADDR_TITLE_ST8_GATE + 4] != VANILLA_TITLE_ST8_GATE:
        return False
    if data[ADDR_TITLE_ST8_POLL : ADDR_TITLE_ST8_POLL + 4] != VANILLA_TITLE_ST8_POLL:
        return False
    if data[ADDR_TITLE_ST8_STAY : ADDR_TITLE_ST8_STAY + 4] != VANILLA_TITLE_ST8_STAY:
        return False
    if data[ADDR_TITLE_ST8_READY : ADDR_TITLE_ST8_READY + 4] != VANILLA_TITLE_ST8_READY:
        return False
    if data[ADDR_TITLE_ST8_LAYOUT : ADDR_TITLE_ST8_LAYOUT + 4] != VANILLA_TITLE_ST8_LAYOUT:
        return False
    if data[ADDR_TITLE_ST18_STAY : ADDR_TITLE_ST18_STAY + 4] != VANILLA_TITLE_ST18_STAY:
        return False
    if data[ADDR_TITLE_ST8_TAIL : ADDR_TITLE_ST8_TAIL + 4] != VANILLA_TITLE_ST8_TAIL:
        return False
    if data[ADDR_TITLE_ST8_TAIL2 : ADDR_TITLE_ST8_TAIL2 + 4] != VANILLA_TITLE_ST8_TAIL2:
        return False
    if data[ADDR_TITLE_HIDE_CAVE : ADDR_TITLE_HIDE_CAVE + HIDE_CAVE_LEN] != VANILLA_TITLE_HIDE_CAVE:
        return False
    if data[ADDR_TITLE_CMP_MAX : ADDR_TITLE_CMP_MAX + 4] != VANILLA_TITLE_CMP_MAX:
        return False
    if data[ADDR_TITLE_OOR : ADDR_TITLE_OOR + 4] != VANILLA_TITLE_OOR:
        return False
    if data[ADDR_TYPE2_1E5 : ADDR_TYPE2_1E5 + 4] != VANILLA_TYPE2_1E5:
        return False
    if data[ADDR_TITLE_MSGID : ADDR_TITLE_MSGID + 4] != VANILLA_TITLE_MSGID:
        return False
    for slot in TITLE_JT_SLOTS:
        if data[_title_jt_off(slot) : _title_jt_off(slot) + 4] != VANILLA_TITLE_JT[slot]:
            return False
    return all(
        data[site : site + 4] == _b_to_apply_show(site) for site in SHOW_APPLY_TAILS
    )


def _title_patched(data: bytes) -> bool:
    if data[ADDR_TITLE_STUB : ADDR_TITLE_STUB + TITLE_STUB_LEN] != PATCHED_TITLE_STUB:
        return False
    if data[ADDR_TITLE_ST1_SHOW : ADDR_TITLE_ST1_SHOW + 4] != VANILLA_TITLE_ST1_SHOW:
        return False
    if data[ADDR_TITLE_ST2_STAY : ADDR_TITLE_ST2_STAY + 4] != NOP:
        return False
    if data[ADDR_TITLE_ST6_SHOW : ADDR_TITLE_ST6_SHOW + 4] != NOP:
        return False
    if data[ADDR_TITLE_ST8_HEAD : ADDR_TITLE_ST8_HEAD + 4] != VANILLA_TITLE_ST8_HEAD:
        return False
    if data[ADDR_TITLE_ST8_SKIP : ADDR_TITLE_ST8_SKIP + 4] != PATCHED_TITLE_ST8_SKIP:
        return False
    if data[ADDR_TITLE_ST8_GATE : ADDR_TITLE_ST8_GATE + 4] != VANILLA_TITLE_ST8_GATE:
        return False
    if data[ADDR_TITLE_ST8_POLL : ADDR_TITLE_ST8_POLL + 4] != VANILLA_TITLE_ST8_POLL:
        return False
    if data[ADDR_TITLE_ST8_STAY : ADDR_TITLE_ST8_STAY + 4] != VANILLA_TITLE_ST8_STAY:
        return False
    if data[ADDR_TITLE_ST8_READY : ADDR_TITLE_ST8_READY + 4] != NOP:
        return False
    if data[ADDR_TITLE_ST8_LAYOUT : ADDR_TITLE_ST8_LAYOUT + 4] != VANILLA_TITLE_ST8_LAYOUT:
        return False
    if data[ADDR_TITLE_ST18_STAY : ADDR_TITLE_ST18_STAY + 4] != VANILLA_TITLE_ST18_STAY:
        return False
    if data[ADDR_TITLE_ST8_TAIL : ADDR_TITLE_ST8_TAIL + 4] != VANILLA_TITLE_ST8_TAIL:
        return False
    if data[ADDR_TITLE_ST8_TAIL2 : ADDR_TITLE_ST8_TAIL2 + 4] != VANILLA_TITLE_ST8_TAIL2:
        return False
    if data[ADDR_TITLE_HIDE_CAVE : ADDR_TITLE_HIDE_CAVE + HIDE_CAVE_LEN] != PATCHED_TITLE_HIDE_CAVE:
        return False
    if data[ADDR_TITLE_CMP_MAX : ADDR_TITLE_CMP_MAX + 4] != VANILLA_TITLE_CMP_MAX:
        return False
    if data[ADDR_TITLE_OOR : ADDR_TITLE_OOR + 4] != VANILLA_TITLE_OOR:
        return False
    if data[ADDR_TYPE2_1E5 : ADDR_TYPE2_1E5 + 4] != PATCHED_TYPE2_1E5:
        return False
    if data[ADDR_TITLE_MSGID : ADDR_TITLE_MSGID + 4] != VANILLA_TITLE_MSGID:
        return False
    for slot in TITLE_JT_SLOTS:
        if data[_title_jt_off(slot) : _title_jt_off(slot) + 4] != PATCHED_TITLE_JT_VA:
            return False
    return all(data[site : site + 4] == PATCHED_BX_LR for site in SHOW_APPLY_TAILS)


def _apply_title(data: bytearray) -> None:
    data[ADDR_TITLE_STUB : ADDR_TITLE_STUB + TITLE_STUB_LEN] = PATCHED_TITLE_STUB
    data[ADDR_TITLE_ST1_SHOW : ADDR_TITLE_ST1_SHOW + 4] = VANILLA_TITLE_ST1_SHOW
    data[ADDR_TITLE_ST2_STAY : ADDR_TITLE_ST2_STAY + 4] = NOP
    data[ADDR_TITLE_ST6_SHOW : ADDR_TITLE_ST6_SHOW + 4] = NOP
    data[ADDR_TITLE_ST8_HEAD : ADDR_TITLE_ST8_HEAD + 4] = VANILLA_TITLE_ST8_HEAD
    data[ADDR_TITLE_ST8_SKIP : ADDR_TITLE_ST8_SKIP + 4] = PATCHED_TITLE_ST8_SKIP
    data[ADDR_TITLE_ST8_GATE : ADDR_TITLE_ST8_GATE + 4] = VANILLA_TITLE_ST8_GATE
    data[ADDR_TITLE_ST8_POLL : ADDR_TITLE_ST8_POLL + 4] = VANILLA_TITLE_ST8_POLL
    data[ADDR_TITLE_ST8_STAY : ADDR_TITLE_ST8_STAY + 4] = VANILLA_TITLE_ST8_STAY
    data[ADDR_TITLE_ST8_READY : ADDR_TITLE_ST8_READY + 4] = NOP
    data[ADDR_TITLE_ST8_LAYOUT : ADDR_TITLE_ST8_LAYOUT + 4] = VANILLA_TITLE_ST8_LAYOUT
    data[ADDR_TITLE_ST18_STAY : ADDR_TITLE_ST18_STAY + 4] = VANILLA_TITLE_ST18_STAY
    data[ADDR_TITLE_ST8_TAIL : ADDR_TITLE_ST8_TAIL + 4] = VANILLA_TITLE_ST8_TAIL
    data[ADDR_TITLE_ST8_TAIL2 : ADDR_TITLE_ST8_TAIL2 + 4] = VANILLA_TITLE_ST8_TAIL2
    data[ADDR_TITLE_HIDE_CAVE : ADDR_TITLE_HIDE_CAVE + HIDE_CAVE_LEN] = PATCHED_TITLE_HIDE_CAVE
    data[ADDR_TITLE_CMP_MAX : ADDR_TITLE_CMP_MAX + 4] = VANILLA_TITLE_CMP_MAX
    data[ADDR_TITLE_OOR : ADDR_TITLE_OOR + 4] = VANILLA_TITLE_OOR
    data[ADDR_TYPE2_1E5 : ADDR_TYPE2_1E5 + 4] = PATCHED_TYPE2_1E5
    data[ADDR_TITLE_MSGID : ADDR_TITLE_MSGID + 4] = VANILLA_TITLE_MSGID
    for slot in TITLE_JT_SLOTS:
        data[_title_jt_off(slot) : _title_jt_off(slot) + 4] = PATCHED_TITLE_JT_VA
    for site in SHOW_APPLY_TAILS:
        data[site : site + 4] = PATCHED_BX_LR


def _revert_title(data: bytearray) -> None:
    data[ADDR_TITLE_STUB : ADDR_TITLE_STUB + TITLE_STUB_LEN] = VANILLA_TITLE_STUB
    data[ADDR_TITLE_ST1_SHOW : ADDR_TITLE_ST1_SHOW + 4] = VANILLA_TITLE_ST1_SHOW
    data[ADDR_TITLE_ST2_STAY : ADDR_TITLE_ST2_STAY + 4] = VANILLA_TITLE_ST2_STAY
    data[ADDR_TITLE_ST6_SHOW : ADDR_TITLE_ST6_SHOW + 4] = VANILLA_TITLE_ST6_SHOW
    data[ADDR_TITLE_ST8_HEAD : ADDR_TITLE_ST8_HEAD + 4] = VANILLA_TITLE_ST8_HEAD
    data[ADDR_TITLE_ST8_SKIP : ADDR_TITLE_ST8_SKIP + 4] = VANILLA_TITLE_ST8_SKIP
    data[ADDR_TITLE_ST8_GATE : ADDR_TITLE_ST8_GATE + 4] = VANILLA_TITLE_ST8_GATE
    data[ADDR_TITLE_ST8_POLL : ADDR_TITLE_ST8_POLL + 4] = VANILLA_TITLE_ST8_POLL
    data[ADDR_TITLE_ST8_STAY : ADDR_TITLE_ST8_STAY + 4] = VANILLA_TITLE_ST8_STAY
    data[ADDR_TITLE_ST8_READY : ADDR_TITLE_ST8_READY + 4] = VANILLA_TITLE_ST8_READY
    data[ADDR_TITLE_ST8_LAYOUT : ADDR_TITLE_ST8_LAYOUT + 4] = VANILLA_TITLE_ST8_LAYOUT
    data[ADDR_TITLE_ST18_STAY : ADDR_TITLE_ST18_STAY + 4] = VANILLA_TITLE_ST18_STAY
    data[ADDR_TITLE_ST8_TAIL : ADDR_TITLE_ST8_TAIL + 4] = VANILLA_TITLE_ST8_TAIL
    data[ADDR_TITLE_ST8_TAIL2 : ADDR_TITLE_ST8_TAIL2 + 4] = VANILLA_TITLE_ST8_TAIL2
    data[ADDR_TITLE_HIDE_CAVE : ADDR_TITLE_HIDE_CAVE + HIDE_CAVE_LEN] = VANILLA_TITLE_HIDE_CAVE
    data[ADDR_TITLE_CMP_MAX : ADDR_TITLE_CMP_MAX + 4] = VANILLA_TITLE_CMP_MAX
    data[ADDR_TITLE_OOR : ADDR_TITLE_OOR + 4] = VANILLA_TITLE_OOR
    data[ADDR_TYPE2_1E5 : ADDR_TYPE2_1E5 + 4] = VANILLA_TYPE2_1E5
    data[ADDR_TITLE_MSGID : ADDR_TITLE_MSGID + 4] = VANILLA_TITLE_MSGID
    for slot in TITLE_JT_SLOTS:
        data[_title_jt_off(slot) : _title_jt_off(slot) + 4] = VANILLA_TITLE_JT[slot]
    for site in SHOW_APPLY_TAILS:
        data[site : site + 4] = _b_to_apply_show(site)


def _sites_vanilla(data: bytes) -> bool:
    return all(
        data[site : site + 4] == _bl_to_dialog(site) for site in DIALOG_SITES
    )


def _sites_nops(data: bytes) -> bool:
    return all(data[site : site + 4] == NOP for site in DIALOG_SITES)


def _manager_patched(data: bytes) -> bool:
    return (
        _sites_nops(data)
        and data[ADDR_JT0 : ADDR_JT0 + 4] == PATCHED_JT0
        and data[ADDR_CMP : ADDR_CMP + 4] == VANILLA_CMP
        and data[ADDR_MOVEQ : ADDR_MOVEQ + 4] == PATCHED_MOVEQ
        and data[ADDR_MOVEQ + 4 : ADDR_MOVEQ + 8] == VANILLA_STRB
    )


def _popup_vanilla(data: bytes) -> bool:
    return (
        data[ADDR_NODATA_BL : ADDR_NODATA_BL + 4] == _bl_to_syspopup()
        and data[ADDR_NODATA2_BEQ : ADDR_NODATA2_BEQ + 4] == VANILLA_NODATA2_BEQ
    )


def _popup_patched(data: bytes) -> bool:
    return (
        data[ADDR_NODATA_BL : ADDR_NODATA_BL + 4] == NOP
        and data[ADDR_NODATA2_BEQ : ADDR_NODATA2_BEQ + 4] == PATCHED_NODATA2_BEQ
    )


def _binds_vanilla(data: bytes) -> bool:
    return all(data[site : site + 4] == _bl_to_bind(site) for site in BIND_SITES)


def _binds_nops(data: bytes) -> bool:
    return all(data[site : site + 4] == NOP for site in BIND_SITES)


def _apply_popup(data: bytearray) -> None:
    data[ADDR_NODATA_BL : ADDR_NODATA_BL + 4] = NOP
    data[ADDR_NODATA2_BEQ : ADDR_NODATA2_BEQ + 4] = PATCHED_NODATA2_BEQ


def _apply_binds(data: bytearray) -> None:
    for site in BIND_SITES:
        data[site : site + 4] = NOP


def _show_vanilla(data: bytes) -> bool:
    return all(data[site : site + 4] == _bl_to_show(site) for site in SHOW_SITES)


def _show_nops(data: bytes) -> bool:
    return all(data[site : site + 4] == NOP for site in SHOW_SITES)


def _apply_show(data: bytearray) -> None:
    for site in SHOW_SITES:
        data[site : site + 4] = NOP


def _ui_jt_vanilla(data: bytes) -> bool:
    return data[ADDR_UI_JT0 : ADDR_UI_JT0 + 4] == VANILLA_UI_JT0


def _state0_vanilla(data: bytes) -> bool:
    return data[ADDR_STATE0 : ADDR_STATE0 + STATE0_LEN] == VANILLA_STATE0


def _state0_patched(data: bytes) -> bool:
    return data[ADDR_STATE0 : ADDR_STATE0 + STATE0_LEN] == PATCHED_STATE0


def _apply_ui_jt(data: bytearray) -> None:
    data[ADDR_UI_JT0 : ADDR_UI_JT0 + 4] = VANILLA_UI_JT0
    data[ADDR_STATE0 : ADDR_STATE0 + STATE0_LEN] = PATCHED_STATE0
    data[ADDR_OPEN_WARN : ADDR_OPEN_WARN + 4] = PATCHED_OPEN_WARN
    _apply_ui2(data)


def _overlay_fn_vanilla(data: bytes) -> bool:
    return (
        data[FUN_APPLY_SHOW : FUN_APPLY_SHOW + 4] == VANILLA_SHOW_FN
        and data[FUN_APPLY_WAIT_OV : FUN_APPLY_WAIT_OV + 8] == VANILLA_WAIT_OV_FN
        and data[FUN_APPLY_WAIT : FUN_APPLY_WAIT + WAIT_APPLY_HEAD_LEN]
        == VANILLA_WAIT_APPLY_HEAD
    )


def _overlay_fn_patched(data: bytes) -> bool:
    # Global show/wait stubs blanked title attract. Leave the helpers vanilla.
    return _overlay_fn_vanilla(data)


def _apply_overlay_fn(data: bytearray) -> None:
    _revert_overlay_fn(data)


def _revert_overlay_fn(data: bytearray) -> None:
    data[FUN_APPLY_SHOW : FUN_APPLY_SHOW + 4] = VANILLA_SHOW_FN
    data[FUN_APPLY_WAIT_OV : FUN_APPLY_WAIT_OV + 8] = VANILLA_WAIT_OV_FN
    data[FUN_APPLY_WAIT : FUN_APPLY_WAIT + WAIT_APPLY_HEAD_LEN] = VANILLA_WAIT_APPLY_HEAD


def _14ed_vanilla(data: bytes) -> bool:
    if data[ADDR_14ED_ST1_DATA : ADDR_14ED_ST1_DATA + 4] != VANILLA_14ED_ST1_DATA:
        return False
    if not all(
        data[site : site + 4] == VANILLA_14ED_TO_APPLY[site]
        for site in ADDR_14ED_TO_APPLY
    ):
        return False
    if not all(
        data[_14ed_jt_off(slot) : _14ed_jt_off(slot) + 4]
        == _14ed_jt_va(VANILLA_14ED_JT_APPLY_FILE[slot])
        for slot in _14ED_APPLY_SLOTS
    ):
        return False
    return (
        all(
            data[site : site + 4] == VANILLA_14ED_WAIT_STAY[site]
            for site in ADDR_14ED_WAIT_STAY
        )
        and data[ADDR_14ED_ERROR : ADDR_14ED_ERROR + 4] == VANILLA_14ED_ERROR
        and data[ADDR_14B890_MULTIWIN : ADDR_14B890_MULTIWIN + 4]
        == VANILLA_14B890_MULTIWIN
        and data[ADDR_14E648_ERROR : ADDR_14E648_ERROR + 4] == VANILLA_14E648_ERROR
        and data[ADDR_14ED_ST3_MULTIWIN : ADDR_14ED_ST3_MULTIWIN + 4]
        == VANILLA_14ED_ST3_MULTIWIN
        and data[ADDR_COMMOPT_D201 : ADDR_COMMOPT_D201 + 4] == VANILLA_COMMOPT_D201
        and data[ADDR_COMMOPT_D201_FAIL : ADDR_COMMOPT_D201_FAIL + 4]
        == VANILLA_COMMOPT_D201_FAIL
    )


def _14ed_patched(data: bytes) -> bool:
    if data[ADDR_14ED_ST1_DATA : ADDR_14ED_ST1_DATA + 4] != PATCHED_14ED_ST1_DATA:
        return False
    if not all(
        data[site : site + 4] == patched_14ed_mov(site)
        for site in ADDR_14ED_TO_APPLY
    ):
        return False
    if not all(
        data[_14ed_jt_off(slot) : _14ed_jt_off(slot) + 4] == PATCHED_14ED_JT_APPLY
        for slot in _14ED_APPLY_SLOTS
    ):
        return False
    return all(data[site : site + 4] == NOP for site in ADDR_14ED_WAIT_STAY) and (
        data[ADDR_14ED_ERROR : ADDR_14ED_ERROR + 4] == PATCHED_14ED_ERROR
        and data[ADDR_14B890_MULTIWIN : ADDR_14B890_MULTIWIN + 4] == NOP
        and data[ADDR_14E648_ERROR : ADDR_14E648_ERROR + 4] == PATCHED_14E648_ERROR
        and data[ADDR_14ED_ST3_MULTIWIN : ADDR_14ED_ST3_MULTIWIN + 4] == NOP
        and data[ADDR_COMMOPT_D201 : ADDR_COMMOPT_D201 + 4] == PATCHED_COMMOPT_D201
        and data[ADDR_COMMOPT_D201_FAIL : ADDR_COMMOPT_D201_FAIL + 4]
        == PATCHED_COMMOPT_D201_FAIL
    )


def _apply_14ed(data: bytearray) -> None:
    data[ADDR_14ED_ST1_DATA : ADDR_14ED_ST1_DATA + 4] = PATCHED_14ED_ST1_DATA
    for site in ADDR_14ED_TO_APPLY:
        data[site : site + 4] = patched_14ed_mov(site)
    for slot in _14ED_APPLY_SLOTS:
        off = _14ed_jt_off(slot)
        data[off : off + 4] = PATCHED_14ED_JT_APPLY
    for site in ADDR_14ED_WAIT_STAY:
        data[site : site + 4] = NOP
    data[ADDR_14ED_ERROR : ADDR_14ED_ERROR + 4] = PATCHED_14ED_ERROR
    data[ADDR_14B890_MULTIWIN : ADDR_14B890_MULTIWIN + 4] = NOP
    data[ADDR_14E648_ERROR : ADDR_14E648_ERROR + 4] = PATCHED_14E648_ERROR
    data[ADDR_14ED_ST3_MULTIWIN : ADDR_14ED_ST3_MULTIWIN + 4] = NOP
    data[ADDR_COMMOPT_D201 : ADDR_COMMOPT_D201 + 4] = PATCHED_COMMOPT_D201
    data[ADDR_COMMOPT_D201_FAIL : ADDR_COMMOPT_D201_FAIL + 4] = (
        PATCHED_COMMOPT_D201_FAIL
    )


def _revert_14ed(data: bytearray) -> None:
    data[ADDR_14ED_ST1_DATA : ADDR_14ED_ST1_DATA + 4] = VANILLA_14ED_ST1_DATA
    for site in ADDR_14ED_TO_APPLY:
        data[site : site + 4] = VANILLA_14ED_TO_APPLY[site]
    for slot in _14ED_APPLY_SLOTS:
        off = _14ed_jt_off(slot)
        data[off : off + 4] = _14ed_jt_va(VANILLA_14ED_JT_APPLY_FILE[slot])
    for site in ADDR_14ED_WAIT_STAY:
        data[site : site + 4] = VANILLA_14ED_WAIT_STAY[site]
    data[ADDR_14ED_ERROR : ADDR_14ED_ERROR + 4] = VANILLA_14ED_ERROR
    data[ADDR_14B890_MULTIWIN : ADDR_14B890_MULTIWIN + 4] = VANILLA_14B890_MULTIWIN
    data[ADDR_14E648_ERROR : ADDR_14E648_ERROR + 4] = VANILLA_14E648_ERROR
    data[ADDR_14ED_ST3_MULTIWIN : ADDR_14ED_ST3_MULTIWIN + 4] = (
        VANILLA_14ED_ST3_MULTIWIN
    )
    data[ADDR_COMMOPT_D201 : ADDR_COMMOPT_D201 + 4] = VANILLA_COMMOPT_D201
    data[ADDR_COMMOPT_D201_FAIL : ADDR_COMMOPT_D201_FAIL + 4] = (
        VANILLA_COMMOPT_D201_FAIL
    )


def _ui2_vanilla(data: bytes) -> bool:
    return (
        data[ADDR_STATE4_SHOW : ADDR_STATE4_SHOW + 4] == VANILLA_STATE4_SHOW
        and data[ADDR_EBE_START : ADDR_EBE_START + 4] == VANILLA_EBE_START
        and data[ADDR_EBE_ST1 : ADDR_EBE_ST1 + 4] == VANILLA_EBE_ST1
        and data[ADDR_EBE_ST4 : ADDR_EBE_ST4 + 4] == VANILLA_EBE_ST4
        and data[ADDR_EBE_ST3 : ADDR_EBE_ST3 + 4] == VANILLA_EBE_ST3
        and data[ADDR_TITLE_FAIL_BEQ : ADDR_TITLE_FAIL_BEQ + 4] == VANILLA_TITLE_FAIL_BEQ
        and data[ADDR_TITLE_FAIL_STORES : ADDR_TITLE_FAIL_STORES + 4] == VANILLA_TITLE_FAIL_STORES
        and data[ADDR_TITLE_D201 : ADDR_TITLE_D201 + 4] == VANILLA_TITLE_D201
        and data[ADDR_EE9_JT6 : ADDR_EE9_JT6 + 4] == VANILLA_EE9_JT6
        and data[ADDR_EE9_ST6 : ADDR_EE9_ST6 + 4] == VANILLA_EE9_ST6
        and _wait_vanilla(data)
        and _apply_show_vanilla(data)
        and _14ed_vanilla(data)
        and _overlay_fn_vanilla(data)
        and _title_vanilla(data)
    )


def _ui2_patched(data: bytes) -> bool:
    return (
        data[ADDR_STATE4_SHOW : ADDR_STATE4_SHOW + 4] == PATCHED_STATE4_SHOW
        and data[ADDR_EBE_START : ADDR_EBE_START + 4] == NOP
        and data[ADDR_EBE_ST1 : ADDR_EBE_ST1 + 4] == PATCHED_EBE_STATE
        and data[ADDR_EBE_ST4 : ADDR_EBE_ST4 + 4] == PATCHED_EBE_STATE
        and data[ADDR_EBE_ST3 : ADDR_EBE_ST3 + 4] == PATCHED_EBE_STATE
        and data[ADDR_TITLE_FAIL_BEQ : ADDR_TITLE_FAIL_BEQ + 4] == PATCHED_TITLE_FAIL_BEQ
        and data[ADDR_TITLE_FAIL_STORES : ADDR_TITLE_FAIL_STORES + 4] == PATCHED_TITLE_FAIL_STORES
        and data[ADDR_TITLE_D201 : ADDR_TITLE_D201 + 4] == PATCHED_TITLE_D201
        and data[ADDR_EE9_JT6 : ADDR_EE9_JT6 + 4] == PATCHED_EE9_JT6
        and data[ADDR_EE9_ST6 : ADDR_EE9_ST6 + 4] == PATCHED_EE9_ST6
        and _wait_patched(data)
        and _apply_show_nops(data)
        and _14ed_patched(data)
        and _overlay_fn_patched(data)
        and _title_patched(data)
    )


def _apply_ui2(data: bytearray) -> None:
    data[ADDR_STATE4_SHOW : ADDR_STATE4_SHOW + 4] = PATCHED_STATE4_SHOW
    data[ADDR_EBE_START : ADDR_EBE_START + 4] = NOP
    data[ADDR_EBE_ST1 : ADDR_EBE_ST1 + 4] = PATCHED_EBE_STATE
    data[ADDR_EBE_ST4 : ADDR_EBE_ST4 + 4] = PATCHED_EBE_STATE
    data[ADDR_EBE_ST3 : ADDR_EBE_ST3 + 4] = PATCHED_EBE_STATE
    data[ADDR_TITLE_FAIL_BEQ : ADDR_TITLE_FAIL_BEQ + 4] = PATCHED_TITLE_FAIL_BEQ
    data[ADDR_TITLE_FAIL_STORES : ADDR_TITLE_FAIL_STORES + 4] = PATCHED_TITLE_FAIL_STORES
    data[ADDR_TITLE_D201 : ADDR_TITLE_D201 + 4] = PATCHED_TITLE_D201
    data[ADDR_EE9_JT6 : ADDR_EE9_JT6 + 4] = PATCHED_EE9_JT6
    data[ADDR_EE9_ST6 : ADDR_EE9_ST6 + 4] = PATCHED_EE9_ST6
    _apply_wait(data)
    _apply_show_apply(data)
    _apply_14ed(data)
    _apply_overlay_fn(data)
    _apply_title(data)


def _revert_ui2(data: bytearray) -> None:
    data[ADDR_STATE4_SHOW : ADDR_STATE4_SHOW + 4] = VANILLA_STATE4_SHOW
    data[ADDR_EBE_START : ADDR_EBE_START + 4] = VANILLA_EBE_START
    data[ADDR_EBE_ST1 : ADDR_EBE_ST1 + 4] = VANILLA_EBE_ST1
    data[ADDR_EBE_ST4 : ADDR_EBE_ST4 + 4] = VANILLA_EBE_ST4
    data[ADDR_EBE_ST3 : ADDR_EBE_ST3 + 4] = VANILLA_EBE_ST3
    data[ADDR_TITLE_FAIL_BEQ : ADDR_TITLE_FAIL_BEQ + 4] = VANILLA_TITLE_FAIL_BEQ
    data[ADDR_TITLE_FAIL_STORES : ADDR_TITLE_FAIL_STORES + 4] = VANILLA_TITLE_FAIL_STORES
    data[ADDR_TITLE_D201 : ADDR_TITLE_D201 + 4] = VANILLA_TITLE_D201
    data[ADDR_EE9_JT6 : ADDR_EE9_JT6 + 4] = VANILLA_EE9_JT6
    data[ADDR_EE9_ST6 : ADDR_EE9_ST6 + 4] = VANILLA_EE9_ST6
    for site in WAIT_SITES:
        data[site : site + WAIT_LEN] = _wait_vanilla_bytes(site)
    for site in SHOW_APPLY_SITES:
        data[site : site + 4] = _bl_to_apply_show(site)
    _revert_14ed(data)
    _revert_overlay_fn(data)
    _revert_title(data)


def _apply_ui(data: bytearray) -> None:
    _apply_popup(data)
    _apply_binds(data)
    _apply_show(data)
    _apply_ui_jt(data)


def is_vanilla(data: bytes) -> bool:
    if len(data) < DIALOG_SITES[-1] + 4:
        return False
    return (
        _sites_vanilla(data)
        and data[ADDR_JT0 : ADDR_JT0 + 4] == VANILLA_JT0
        and data[ADDR_CMP : ADDR_CMP + 4] == VANILLA_CMP
        and data[ADDR_MOVEQ : ADDR_MOVEQ + 4] == VANILLA_MOVEQ
        and data[ADDR_MOVEQ + 4 : ADDR_MOVEQ + 8] == VANILLA_STRB
        and _popup_vanilla(data)
        and _binds_vanilla(data)
        and _show_vanilla(data)
        and _ui_jt_vanilla(data)
        and _state0_vanilla(data)
        and data[ADDR_OPEN_WARN : ADDR_OPEN_WARN + 4] == VANILLA_OPEN_WARN
        and _ui2_vanilla(data)
    )


def is_patched(data: bytes) -> bool:
    if len(data) < DIALOG_SITES[-1] + 4:
        return False
    return (
        _manager_patched(data)
        and _popup_patched(data)
        and _binds_nops(data)
        and _show_nops(data)
        and _ui_jt_vanilla(data)
        and _state0_patched(data)
        and data[ADDR_OPEN_WARN : ADDR_OPEN_WARN + 4] == PATCHED_OPEN_WARN
        and _ui2_patched(data)
    )


def _restore_namecard_setup(data: bytearray) -> bool:
    """Put back the Name Card setup branch if an older skip removed it."""
    if data[ADDR_14ED_ST1_DATA : ADDR_14ED_ST1_DATA + 4] != OLD_14ED_ST1_SKIP:
        return False
    trial = bytearray(data)
    trial[ADDR_14ED_ST1_DATA : ADDR_14ED_ST1_DATA + 4] = VANILLA_14ED_ST1_DATA
    if not is_patched(trial):
        return False
    data[ADDR_14ED_ST1_DATA : ADDR_14ED_ST1_DATA + 4] = VANILLA_14ED_ST1_DATA
    print(
        f"[spotpass-skip] restore Name Card setup beq @{ADDR_14ED_ST1_DATA:#x} "
        f"(was stay @{ADDR_14ED_STAY:#x})"
    )
    return True


def _upgrade_namecard_bars(data: bytearray) -> bool:
    """Older skips parked Name Card on state 21. Send that handoff to state 2."""
    if data[0x0014EFE8 : 0x0014EFE8 + 4] != PATCHED_14ED_TO_APPLY:
        return False
    trial = bytearray(data)
    trial[0x0014EFE8 : 0x0014EFE8 + 4] = PATCHED_14ED_NAMECARD
    if not is_patched(trial):
        return False
    data[0x0014EFE8 : 0x0014EFE8 + 4] = PATCHED_14ED_NAMECARD
    print("[spotpass-skip] Name Card handoff @0x14EFE8 state 21 -> 2")
    return True


def apply_patch(data: bytearray) -> bool:
    """Quiet missing NsData. Returns True if bytes changed."""
    if _restore_namecard_setup(data):
        return True
    if _upgrade_namecard_bars(data):
        return True
    if is_patched(data):
        print(
            f"[spotpass-skip] already patched "
            f"FUN_000ea254 hide+dismiss + state4/ebe0c + TitleUI 0xd201 + "
            f"apply-wait done + 0x2b61 show + 0x1e7 pane + SysPopup @{ADDR_NODATA_BL:#x}"
        )
        return False
    if (
        _manager_patched(data)
        and _popup_patched(data)
        and _binds_nops(data)
        and _show_nops(data)
        and _state0_patched(data)
        and data[ADDR_OPEN_WARN : ADDR_OPEN_WARN + 4] == PATCHED_OPEN_WARN
        and not _ui2_patched(data)
    ):
        _apply_ui2(data)
        print(
            f"[spotpass-skip] state4 show @{ADDR_STATE4_SHOW:#x} -> bx lr; "
            f"FUN_000ebe0c skip apply + state 7; FUN_000ee9f0 skip applying-wait; "
            f"FUN_0062fa8c wait -> done; NOP FUN_00443cd8; TitleUI skip 0xd201"
        )
        return True
    if (
        _manager_patched(data)
        and _popup_patched(data)
        and _binds_nops(data)
        and _show_nops(data)
        and _state0_patched(data)
        and data[ADDR_OPEN_WARN : ADDR_OPEN_WARN + 4] != PATCHED_OPEN_WARN
    ):
        data[ADDR_OPEN_WARN : ADDR_OPEN_WARN + 4] = PATCHED_OPEN_WARN
        _apply_ui2(data)
        print(f"[spotpass-skip] FUN_000ea964 @{ADDR_OPEN_WARN:#x} -> bx lr")
        return True
    if (
        _manager_patched(data)
        and _popup_patched(data)
        and _binds_nops(data)
        and _show_nops(data)
        and not _state0_patched(data)
    ):
        _apply_ui_jt(data)
        print(
            f"[spotpass-skip] FUN_000ea254 state0 @{ADDR_STATE0:#x} hide +0xa8 "
            f"then dismiss 0x001EA6C4"
        )
        return True
    if (
        _manager_patched(data)
        and _popup_patched(data)
        and _binds_nops(data)
        and _show_vanilla(data)
    ):
        _apply_show(data)
        _apply_ui_jt(data)
        print(
            f"[spotpass-skip] NOP {len(SHOW_SITES)} bl FUN_004b17b0 "
            f"(0x2b61 show, first @{SHOW_SITES[0]:#x}); "
            f"FUN_000ea254 jt0 -> dismiss"
        )
        return True
    if _manager_patched(data) and _popup_patched(data) and _binds_vanilla(data) and _show_vanilla(data):
        _apply_binds(data)
        _apply_show(data)
        _apply_ui_jt(data)
        print(
            f"[spotpass-skip] NOP {len(BIND_SITES)} bl FUN_004b119c + "
            f"{len(SHOW_SITES)} bl FUN_004b17b0; FUN_000ea254 jt0 -> dismiss"
        )
        return True
    if _manager_patched(data) and _popup_vanilla(data) and _binds_vanilla(data) and _show_vanilla(data):
        _apply_ui(data)
        print(
            f"[spotpass-skip] NOP bl FUN_00319320 @{ADDR_NODATA_BL:#x}; "
            f"NOP pane bind/show (0x1e7 / 0x2b61); FUN_000ea254 jt0 -> dismiss"
        )
        return True
    if not is_vanilla(data):
        got = data[ADDR_CMP : ADDR_MOVEQ + 8].hex()
        raise ValueError(
            f"unexpected SpotPass no-data store @{ADDR_CMP:#x}: {got} "
            f"(want vanilla 59a010 BLs + cmp + moveq #4 + strbeq + 0x1e6/0x1e7 UI)"
        )
    for site in DIALOG_SITES:
        data[site : site + 4] = NOP
    data[ADDR_JT0 : ADDR_JT0 + 4] = PATCHED_JT0
    data[ADDR_MOVEQ : ADDR_MOVEQ + 4] = PATCHED_MOVEQ
    _apply_ui(data)
    print(
        f"[spotpass-skip] FUN_000ea254 jt0 @{ADDR_UI_JT0:#x} -> dismiss; "
        f"NOP {len(SHOW_SITES)} bl FUN_004b17b0 (0x2b61 show); "
        f"NOP {len(BIND_SITES)} bl FUN_004b119c (0x1e7 pane); "
        f"NOP bl FUN_00319320 @{ADDR_NODATA_BL:#x}; "
        f"NOP {len(DIALOG_SITES)} FUN_0059a010; "
        f"jt0 @{ADDR_JT0:#x} -> NewFlag; @{ADDR_MOVEQ:#x} moveq r0,#4 -> #0"
    )
    return True


def revert_patch(data: bytearray) -> bool:
    if is_vanilla(data):
        print(f"[spotpass-skip] already vanilla @{ADDR_MOVEQ:#x}")
        return False
    if not is_patched(data):
        raise ValueError("cannot revert: SpotPass skip site is neither vanilla nor patched")
    for site in DIALOG_SITES:
        data[site : site + 4] = _bl_to_dialog(site)
    data[ADDR_JT0 : ADDR_JT0 + 4] = VANILLA_JT0
    data[ADDR_MOVEQ : ADDR_MOVEQ + 4] = VANILLA_MOVEQ
    data[ADDR_NODATA_BL : ADDR_NODATA_BL + 4] = _bl_to_syspopup()
    data[ADDR_NODATA2_BEQ : ADDR_NODATA2_BEQ + 4] = VANILLA_NODATA2_BEQ
    for site in BIND_SITES:
        data[site : site + 4] = _bl_to_bind(site)
    for site in SHOW_SITES:
        data[site : site + 4] = _bl_to_show(site)
    data[ADDR_UI_JT0 : ADDR_UI_JT0 + 4] = VANILLA_UI_JT0
    data[ADDR_STATE0 : ADDR_STATE0 + STATE0_LEN] = VANILLA_STATE0
    data[ADDR_OPEN_WARN : ADDR_OPEN_WARN + 4] = VANILLA_OPEN_WARN
    _revert_ui2(data)
    print("[spotpass-skip] restored FUN_000ea254 state0 + 0x2b61 show + 0x1e7 pane + FUN_00319320 + FUN_0059a010")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(
            f"FUN_000ea254 jt0 @{ADDR_UI_JT0:#x} 0x001EA2A0 -> 0x001EA6C4; "
            f"NOP {len(SHOW_SITES)} bl FUN_004b17b0 (first @{SHOW_SITES[0]:#x}); "
            f"NOP {len(BIND_SITES)} bl FUN_004b119c (first @{BIND_SITES[0]:#x}); "
            f"NOP bl FUN_00319320 @{ADDR_NODATA_BL:#x}; "
            f"b @{ADDR_NODATA2_BEQ:#x}; "
            f"NOP {len(DIALOG_SITES)} bl FUN_0059a010 "
            f"(first @{DIALOG_SITES[0]:#x}); "
            f"jt0 @{ADDR_JT0:#x} 0x00709708 -> 0x00709734; "
            f"moveq r0,#4 -> #0 @{ADDR_MOVEQ:#x}"
        )
        return 0

    if not args.deploy_azahar:
        raise SystemExit("pass --deploy-azahar (or import apply_patch)")

    from nlpp_paths import AZAHAR_MOD_CODE, AZAHAR_MOD_ROOT

    dest = AZAHAR_MOD_CODE
    if not dest.is_file():
        raise SystemExit(f"missing {dest}")

    bak = dest.with_name(dest.name + ".bak_pre_spotpass_skip")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
