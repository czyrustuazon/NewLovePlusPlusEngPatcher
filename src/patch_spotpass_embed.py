#!/usr/bin/env python3
"""Impersonate BOSS NsData so Watcher / city tables merge without a boss inject.

Cold-boot ``FUN_006096d8`` only needs two IPC results, then the stock apply
state machine (``FUN_006094c0`` / ``FUN_006088c8``) writes the blob into save:

  * ``FUN_00609ab0`` GetNsDataNewFlag → **1** so the tick can enter apply
    after boot skip has already hidden the nag. Confirm ``+0x48`` is forced
    to 1 so apply does not wait on a BOSS UI latch.
    * ``FUN_00609ef4`` ReadNsData BLs still memcpy into dest ``r1`` when the
    wrapper has a buffer. Null dest stores the payload VA at ``wrapper+0x48``
    (``.rodata`` is read-only on hardware — no self-copy) and returns
    ``0x914`` so ``wrapper+0x44`` is the size. Do **not** write ``r4+0x200``.
    * Magazine Watcher still said “No data” after the ``+0x44`` ldrb skip:
      ``FUN_00608cac`` / ``FUN_00609164`` WaitSync the BOSS worker and return
      0. Stub those entries (and ``FUN_00609600`` / ``FUN_006093f4``) to
      ``mov r0,#1; bx lr``. State 5 still failed: ``FUN_006090b0`` returns 0
      when NetDl ``+0x268`` is unset (no BOSS job), before unpack runs.
      Parent / Watcher state 0x17 skipped ``FUN_00609600`` when
      ``FUN_00608f50`` returned 0; NOP those ``beq`` so ``+0x67`` can go 1.
    * Merge ``FUN_006088c8`` is ``mov r0,#1; bx lr``. NewFlag still enters
    apply; skip-ac:u still let WaitSync latch ``+0x250=1`` with a bad
    handle, then parse ``bl FUN_004e19b0`` smashed (``LR`` ``0x00708988``).
    Do **not** memcpy into ``this+0x200`` or take the ``svc 0x24`` path.
    * MagList ``FUN_004fd248!=0`` + ``FUN_004fd2c8==0`` waits in state 5;
    NOP of that ``beq`` fell through to worker command **10** (empty
      SpotPass list → “No data.”). Always command **9** (cart ``Mag_Tit02``–
      ``08``). Stubbing has-rows ``FUN_005fe9d8`` skipped the worker poll
      and made parent ``+0x66==+0x69``, so MagList never ran and Watcher
      layout ``0x31`` opened empty (ERROR “No data.”). Restore has-rows;
      NOP its ``+0x45/+0x46`` gate (and bind ``FUN_005fe718``); NOP parent
      state 0 so ``FUN_005fe5d0`` inits ``+0x908``; keep MagList in state 6
      until rows bind; keep layout ``+0x7c`` so state 0x17 waits for Back;
      after MagList go parent ``0x17`` (dismiss), not Watcher.
      Watcher extra-missing kept layout ``0x31`` and DrawText pack
      ``0xB200`` (empty → “No data.”). Skip that layout (state 0 → 5)
      and after Watcher open MagList ``0xC`` (cart ``Mag_Tit``). Always
      treat extra as present so state 5 does not sit on the empty pane.
      In-room WEB layout ``0xC`` (``web_tex_watcher``) is operator
      vtable+0x40 ``FUN`` @ ``0x0005B61C``. Button id 9 stores
      ``+0x5e=0xD`` and ``FUN_0005b49c`` then builds layout ``0xC``
      ``r2=2`` (pack ``0x1901``). Article count is 0, and state 0xE
      leaves that layout up (ERROR “No data.”). Button 9 and button 10
      both branch to the click epilogue. Drawing ``FUN_00255764`` on a
      window ``+0x60`` pane clears the room backdrop. If state ``0xD``
      still runs, ``0x0005B574`` goes
      to hub state 7. An empty count at ``0x0005BC70`` dismisses.
      Skipping ``WebUIOperator`` button 0 (``0x00149694``) blacks the
      room behind the WEB pills. Leave that click vanilla.
    * ``FUN_0014eb9c`` return is ``(extra & ~bit0x20 & has-rows) ^ 1``.
      Cleared extra-data makes ``extra==0``, so the function still binds
      pack ``0x9d01`` slot ``0x60`` and returns **1** even when has-rows
      is forced 1. Stub the entry ``mov r0,#0; bx lr``. The caller then
      still opens the 0x84 ERROR window when leftover ``+0xb4 != -1``;
      turn ``beq 0x14e2a4`` @ ``0x0014E16C`` into ``b`` so that path
      never binds. Restore the inner ``bl FUN_005fe9d8``.
    * Communication Settings ``bl FUN_0059a788`` @ ``0x14F018`` finishes the
    type-``0xf`` job idle (``+0`` done, ``+1`` / ``+4`` empty). Setting
    ``+1=1`` opened state 24's blank ERROR overlay.

Boot skip (§16.7) still hides the nag. Payload lives in ``.rodata`` (NX on
hardware). Stubs replace ``FUN_00609ab0`` in-place (RX).

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
ADDR_MERGE_ENTRY = 0x006088C8  # SpotPass_MergeNsData — never parse / ac:u
VANILLA_MERGE_ENTRY = bytes.fromhex("f04f2de90040a0e1")  # stmdb {r4-r11,lr}; mov r4,r0
ADDR_MERGE = 0x006088D0  # add r6, r0, #0x200  (must stay vanilla)
ADDR_MERGE_AC = 0x006089EC  # bl FUN_004e1998  ac:u SendSyncRequest
VANILLA_MERGE_AC = bytes.fromhex("e963fbeb")  # bl FUN_004e1998
PATCHED_MERGE_AC = bytes.fromhex("0000a0e3")  # mov r0, #0  skip dead ac:u handle
# Magazine Watcher “No data” — these fns WaitSync the BOSS worker and return 0
# without a live NsData list. Force ``mov r0,#1; bx lr`` at the entry.
PATCHED_RET1 = bytes.fromhex("0100a0e31eff2fe1")  # mov r0,#1; bx lr
ADDR_UNPACK_READY = 0x006092C8  # SpotPass_UnpackTables
VANILLA_UNPACK_READY = bytes.fromhex("f0402de90040a0e1")
ADDR_HASENTRY_READY = 0x00609164  # FUN_00609164
VANILLA_HASENTRY_READY = bytes.fromhex("30402de90040a0e1")
ADDR_HASLIST_READY = 0x00609600  # FUN_00609600
VANILLA_HASLIST_READY = bytes.fromhex("f0412de90060a0e3")
ADDR_HASSTATE6_READY = 0x006093F4  # FUN_006093f4 (magazine state 6)
VANILLA_HASSTATE6_READY = bytes.fromhex("30402de90040a0e1")
ADDR_PREUNPACK_READY = 0x006090B0  # FUN_006090b0 (NewFlag via +0x268)
VANILLA_PREUNPACK_READY = bytes.fromhex("681290e50000a0e3")  # ldr r1,[r0,#0x268]; mov r0,#0
ADDR_HASROWS_READY = 0x005FE9D8  # FUN_005fe9d8 MagazineListHasRows (keep vanilla)
VANILLA_HASROWS_READY = bytes.fromhex("38402de90050a0e3")  # stmdb {r3-r5,lr}; mov r5,#0
# Leftover from the +0x44 ldrb gate (mid-function). Restore on apply/revert.
VANILLA_TABLES_READY = bytes.fromhex("4400d0e5")  # ldrb r0, [r0, #0x44]
ADDR_UNPACK_LDRB = 0x006092D4
ADDR_HASENTRY_LDRB = 0x0060916C
ADDR_HASLIST_LDRB = 0x00609608
WATCHER_RET1_SITES = (
    (ADDR_UNPACK_READY, VANILLA_UNPACK_READY),
    (ADDR_HASENTRY_READY, VANILLA_HASENTRY_READY),
    (ADDR_HASLIST_READY, VANILLA_HASLIST_READY),
    (ADDR_HASSTATE6_READY, VANILLA_HASSTATE6_READY),
    (ADDR_PREUNPACK_READY, VANILLA_PREUNPACK_READY),
)
ARM_NOP = bytes.fromhex("00f020e3")  # nop
# Holy-site AREA name. Tex_Place is DrawText'd from an inline buffer the
# stubbed merge never fills, and the pane pointer stays null while the
# binder searches the empty-data group. The cave binds Tex_Place, then
# draws a static UTF-8 station name. It sits in the dead body of the
# ret0 gate, after the vanilla has-rows BL at 0x14EBC4.
ADDR_AREA_DRAW = 0x004DCBCC  # add r1, r5, #0x84 ; mov r0, r8 ; bl drawer
VANILLA_AREA_DRAW = bytes.fromhex("841085e20800a0e17ca7f5eb")
ADDR_AREA_CAVE = 0x0014EBC8
ADDR_AREA_CAVE_LIMIT = 0x0014ECFC
_AREA_LOOKUP = 0x005C6E84
_AREA_FINDER_INIT = 0x005E828C
_AREA_FIND = 0x005EBA00
_AREA_STORE = 0x00199B98
_AREA_DRAW_PLACE = 0x002469CC
_AREA_GLOBAL_VA = 0x008BFA40
_AREA_POS_VA = 0x003468E4  # "Pos_Spot_O01"
_AREA_PLACE_VA = 0x00346900  # "Tex_Place"
_AREA_NAME = "奥十羽野駅".encode("utf-8") + b"\x00"
# Dead instructions the cave replaces (gate body after the has-rows BL).
VANILLA_AREA_CAVE_BODY = bytes.fromhex(
    "30a19fe530919fe530719fe5000054e30060a0e10080a0e30500000a"
    "000055e32500000a000097e5000050e31100000a180000ea000097e5"
    "000050e30700001a1020a0e30010a0e38400a0e35020fbeb000050e3"
    "00f020e317e4021b000087e50070b0e12d00000a0120a0e36010a0e3"
    "0a00a0e1220000ea1020a0e30010a0e38400a0e34220fbeb000050e3"
    "00f020e309e4021b000087e50070b0e11f00000a0120a0e37010a0e3"
    "0a00a0e134c811eb00f020e300f020e3120000ea000056e31600001a"
    "000097e5000050e30700001a1020a0e3"
)
# MagList: extra-data version + no bit 0x20 → state 5. NOP of that beq
# sent worker command 10 (empty SpotPass). Force command 9 (cart).
ADDR_MAGLIST_EXTRA = 0x0010441C  # cmp r0,#0 after FUN_004fd248
VANILLA_MAGLIST_EXTRA = bytes.fromhex("000050e3")  # cmp r0, #0
PATCHED_MAGLIST_EXTRA = bytes.fromhex("0c0000ea")  # b 0x104454 mov r2,#9
ADDR_MAGLIST_NODATA_BEQ = 0x00104434  # beq 0x1043c0 (restore; dead after EXTRA)
VANILLA_MAGLIST_NODATA_BEQ = bytes.fromhex("e1ffff0a")
ADDR_MAGLIST_CLEAR_LAYOUT = 0x001043FC  # str r10, [r4, #0x7c]
VANILLA_MAGLIST_CLEAR_LAYOUT = bytes.fromhex("7ca084e5")
ADDR_MAGLIST_CMD9_TAIL = 0x0010446C  # b 0x1044e8 (state 0x17)
VANILLA_MAGLIST_CMD9_TAIL = bytes.fromhex("1d0000ea")
PATCHED_MAGLIST_CMD9_TAIL = bytes.fromhex("210000ea")  # b 0x1044f8 state 6
ADDR_MAGLIST_ST6_FAIL = 0x00104508  # beq 0x1044f0 (state 0x14 ERROR)
VANILLA_MAGLIST_ST6_FAIL = bytes.fromhex("f8ffff0a")
PATCHED_MAGLIST_ST6_FAIL = bytes.fromhex("2c00000a")  # beq 0x1045c0 stay
ADDR_PARENT_MAGLIST_SKIP = 0x00105D78  # beq skip MagList when +0x66==+0x69
VANILLA_PARENT_MAGLIST_SKIP = bytes.fromhex("0500000a")
ADDR_PARENT_AFTER_MAGLIST = 0x00105D94  # mov r0, #0xd (Watcher)
VANILLA_PARENT_AFTER_MAGLIST = bytes.fromhex("0d00a0e3")
PATCHED_PARENT_AFTER_MAGLIST = bytes.fromhex("1700a0e3")  # mov r0, #0x17 dismiss
ADDR_WATCHER_ST0_MOV = 0x00104624  # moveq r0, #4 (create layout 0x31)
VANILLA_WATCHER_ST0_MOV = bytes.fromhex("0400a003")
PATCHED_WATCHER_ST0_MOV = bytes.fromhex("0500a003")  # moveq r0, #5 skip empty pane
ADDR_WATCHER_EXTRA_CMP = 0x00104724  # cmp r0, #0 extra-data
VANILLA_WATCHER_EXTRA_CMP = bytes.fromhex("000050e3")
PATCHED_WATCHER_EXTRA_CMP = bytes.fromhex("0100a0e3")  # mov r0, #1 treat extra present
ADDR_PARENT_AFTER_WATCHER = 0x00105DD4  # mov r0, #0xe
VANILLA_PARENT_AFTER_WATCHER = bytes.fromhex("0e00a0e3")
PATCHED_PARENT_AFTER_WATCHER = bytes.fromhex("0c00a0e3")  # mov r0, #0xc MagList
ADDR_WEB_WATCHER_EXTRA_BEQ = 0x0005B570  # beq 0x5b600 when FUN_004e7d34==0
VANILLA_WEB_WATCHER_EXTRA_BEQ = bytes.fromhex("2200000a")
ADDR_WEB_WATCHER_FAIL_ST = 0x0005B600  # mov r0, #9 empty Watcher viewer
VANILLA_WEB_WATCHER_FAIL_ST = bytes.fromhex("0900a0e3")
PATCHED_WEB_WATCHER_FAIL_ST = bytes.fromhex("0900a0e3")  # mov r0, #9 open the viewer
ADDR_WEB_WATCHER_ST9_FROM_E = 0x0005BC74  # state 0xE empty count → 9
VANILLA_WEB_WATCHER_ST9_FROM_E = bytes.fromhex("0900a0e3")
ADDR_WEB_WATCHER_EMPTY_BL = 0x0005BC70  # bl FUN_004450f4; page stays up
VANILLA_WEB_WATCHER_EMPTY_BL = bytes.fromhex("1fa50feb")
# Next insn is mov r0,#7; b 0x5B92C (store state, return). Do not branch to
# 0x5BC98: that sets +0xa4 and opens the empty layout (“No data.”).
PATCHED_WEB_WATCHER_EMPTY_BL = bytes.fromhex("020000ea")  # b 0x5BC80 show the row
# FUN_0005b0c0 (state 0xC) hides the list and, when +0xc5==0, opens the
# staying empty page (state 0x12). Always return so layout 0xC stays up.
ADDR_WEB_LIST_HOLD = 0x0005B0F0  # bne 0x5B1EC
VANILLA_WEB_LIST_HOLD = bytes.fromhex("3d00001a")
PATCHED_WEB_LIST_HOLD = bytes.fromhex("3d0000ea")  # b 0x5B1EC
# Layout 12 is created here and the function returns. Drawing on the
# returned handle's +0x60 treats the room backdrop as a text pane and
# clears it. Leave the bind vanilla. WebUI button 0 (0x149694) stays
# vanilla for the same reason: it is what attaches Lyt_Bg.
ADDR_WEB_OPEN_LAYOUT = 0x0005B5F0  # bl FUN_00195fa4
VANILLA_WEB_OPEN_LAYOUT = bytes.fromhex("6bea04eb")
# Message id 80 returns pack 0x1901 slot 356 ("No data."). Slot 178 is the
# retitled issue line. Same draw path; does not touch Lyt_Bg.
ADDR_NODATA_MSG80 = 0x0030C198  # mov r0, #0x164
VANILLA_NODATA_MSG80 = bytes.fromhex("590fa0e3")
PATCHED_NODATA_MSG80 = bytes.fromhex("b200a0e3")  # mov r0, #0xb2 (slot 178)
# Message id 3 is the other slot for this sentence (pack 0x1001 slot 23).
# Both dialog copies call the switch. The in-room copy is the vmethod
# at 0x629998; returning -1 makes it skip the text gate.
ADDR_NODATA_MSG3 = 0x0030C008  # mov r0, #0x17
VANILLA_NODATA_MSG3 = bytes.fromhex("1700a0e3")
PATCHED_NODATA_MSG3 = bytes.fromhex("0000e0e3")  # mvn r0, #0
# Empty spot content tells the room screen command 3, which opens the
# ERROR card. State 6 (0x149D00) is the tap that still showed the card.
# The content bind has the same notify at 0x14A0CC. Skip both.
# Button 0 (0x149694) still binds Lyt_Bg.
ADDR_WEB_EMPTY_NOTIFY = 0x00149D00  # blx parent vtable+0x4c, r1 = 3
VANILLA_WEB_EMPTY_NOTIFY = bytes.fromhex("3cff2fe1")
ADDR_WEB_EMPTY_NOTIFY2 = 0x0014A0CC
VANILLA_WEB_EMPTY_NOTIFY2 = bytes.fromhex("3cff2fe1")
# Message id 3 returns pack 0x1001 slot 23, the other STRI for this card.
# Parent notifies were not it. Return before the dialog is built.
ADDR_MSG3_ENTRY = 0x0030628C  # stmdb of the message dialog
VANILLA_MSG3_ENTRY = bytes.fromhex("f04f2de9")
ADDR_WEB_WATCHER_ST9_DUP = 0x0005AC04  # FUN_0005abd4 empty count → 9
VANILLA_WEB_WATCHER_ST9_DUP = bytes.fromhex("0900a0e3")
ADDR_WEB_WATCHER_ST9_ENTRY = 0x0005BA44  # state 9 viewer start
VANILLA_WEB_WATCHER_ST9_ENTRY = bytes.fromhex("641094e5")  # ldr r1, [r4, #0x64]
PATCHED_WEB_WATCHER_ST9_ENTRY = VANILLA_WEB_WATCHER_ST9_ENTRY
ADDR_WEB_WATCHER_CLICK = 0x0005B49C  # FUN_0005b49c Watcher tick (keep vanilla)
VANILLA_WEB_WATCHER_CLICK = bytes.fromhex("f0402de90040a0e1")  # stmdb {r4-r7,lr}; cpy r4,r0
# Button id 9 @ 0x5B6DC: do not enter state 0xD (that tick builds the viewer).
# Branch to the issue-draw cave (filled in after the branch helper).
ADDR_WEB_PILL_LAYOUT = 0x0005B6DC
VANILLA_WEB_PILL_LAYOUT = bytes.fromhex("0d50a0e3")  # mov r5, #0xd
ADDR_PILL_EPILOGUE = 0x0005B780
# Dead body of stubbed SpotPass_UnpackTables. Entry stays ret1; this slice
# is only reached from the pill branch. Ends before the info.dat literal.
ADDR_ISSUE_CAVE = 0x006092D0
# Empty in-room lists skip the row loop. One row uses pack 0x1901 slot 356,
# the sentence currently titled Towano Watcher #28. Count stays real when
# the list already has rows.
ADDR_ROW_EMPTY = 0x005CE558  # ble epilogue when count <= 0
VANILLA_ROW_EMPTY = bytes.fromhex("510000da")
ADDR_ROW_RESUME = 0x005CE55C
ADDR_ROW2_EMPTY = 0x005CD748
VANILLA_ROW2_EMPTY = bytes.fromhex("200000da")
ADDR_ROW2_RESUME = 0x005CD74C
# FUN_00195fa4 slot = table[layout] + mode. 356 is this card's sentence.
# Return 0 before the dialog record is built. Flags for the next beq
# are restored when the slot is anything else.
ADDR_SLOT_SUM = 0x00195FE0  # add r8, r1, r7
VANILLA_SLOT_SUM = bytes.fromhex("078081e0")
ADDR_SLOT_RESUME = 0x00195FE4
ADDR_ISSUE_DRAW = 0x00255764  # FUN_00255764(window, cstring) → pane +0x60
ISSUE_TITLE = b"Towano Watcher #28\x00\x00"  # 20 bytes, keeps the cave 4-aligned
VANILLA_ISSUE_BODY = bytes.fromhex(
    "43df4de24400d0e50270a0e10350a0e1000050e30000a0e3"
    "1000000a0100a0e16d0400eb0060a0e1011ca0e308008de2"
    "b4d2efeb2c109fe5"
)
# Button id 10 @ 0x5B724: same click. Builds the empty pack 0xB200 page.
ADDR_WEB_PILL_OTHER = 0x0005B724
VANILLA_WEB_PILL_OTHER = bytes.fromhex("0050e0e3")  # mvn r5, #0
PATCHED_WEB_PILL_OTHER = bytes.fromhex("150000ea")  # b 0x5B780 epilogue
# Older builds rewrote 0x5B6E8..0x5B6F3 and still entered state 0xD.
ADDR_WEB_PILL_BODY = 0x0005B6E8
VANILLA_WEB_PILL_BODY = bytes.fromhex("003091e50c508de208308de5")
ADDR_WEB_NO_LIST = 0x0005B544  # strb state 7 when the list object is missing
VANILLA_WEB_NO_LIST = bytes.fromhex("5e70c4e5")
PATCHED_WEB_NO_LIST = bytes.fromhex("2d0000ea")  # b 0x5B600 enter the viewer
ADDR_WEB_NO_ARTICLE = 0x0005B560  # beq state 9 when the article is missing
VANILLA_WEB_NO_ARTICLE = bytes.fromhex("2600000a")
PATCHED_WEB_NO_ARTICLE = VANILLA_WEB_NO_ARTICLE
# Menu index 9 is a different screen. Leave the jump table vanilla.
ADDR_MENU_ERROR_CASE = 0x0012BB14
VANILLA_MENU_ERROR_CASE = bytes.fromhex("64bc2200")  # VA 0x0022bc64
PATCHED_MENU_ERROR_CASE = VANILLA_MENU_ERROR_CASE
# Item types 6/7/8/9/0x1b overwrite the page layout with 29 (slot 356,
# the ERROR card) before the dialog is built. Ask for the magazine page.
ADDR_EMPTY_LAYOUT = 0x000F3ED8  # mov r0, #0x1d
VANILLA_EMPTY_LAYOUT = bytes.fromhex("1d00a0e3")
PATCHED_EMPTY_LAYOUT = VANILLA_EMPTY_LAYOUT
# Menu types 5, 6, and 9 return layout 29 (mode 1 → slot 356, this ERROR card).
ADDR_LAYOUT29_RET = 0x00100DA0  # mov r0, #0x1d ; bx lr
VANILLA_LAYOUT29_RET = bytes.fromhex("1d00a0e3")
PATCHED_LAYOUT29_RET = VANILLA_LAYOUT29_RET
# In-room empty list: [obj+0x88]==0 opens layout 29 mode 1 (slot 356).
ADDR_EMPTY_DIALOG_LAYOUT = 0x003E6DC0  # moveq r1, #0x1d
VANILLA_EMPTY_DIALOG_LAYOUT = bytes.fromhex("1d10a003")
PATCHED_EMPTY_DIALOG_LAYOUT = VANILLA_EMPTY_DIALOG_LAYOUT
# +0x88 is still 0 on the first pass, so state 6 opens the empty card.
# Build the list instead of leaving through the OK step.
ADDR_EMPTY_DIALOG_BEQ = 0x003E6DC8  # beq 0x3e6de0
VANILLA_EMPTY_DIALOG_BEQ = bytes.fromhex("0400000a")
PATCHED_EMPTY_DIALOG_BEQ = bytes.fromhex("cefeff0a")  # beq 0x3e6908
# An empty blob used to set state 6 again. Open TownGuideUIOperator instead.
ADDR_EMPTY_LIST_STATE = 0x003E6944  # moveq r0, #6
VANILLA_EMPTY_LIST_STATE = bytes.fromhex("0600a003")
PATCHED_EMPTY_LIST_STATE = VANILLA_EMPTY_LIST_STATE
# Issue 28's lake sentence belongs on 恋愛の聖地 (bit 1 → Mag_Tit03).
# The other six cart corners stay out of the book. FEVER (bit 3) is the
# heated-pool corner, but it uses this same sheet, so it stays out too.
ADDR_PAGE_MASK_WALK = 0x004DA664  # ldr r2, [r4, #0x8c]
VANILLA_PAGE_MASK_WALK = bytes.fromhex("8c2094e5")
PATCHED_PAGE_MASK = bytes.fromhex("0220a0e3")  # mov r2, #2
ADDR_PAGE_MASK_LOOKUP = 0x00631354  # ldr ip, [r0, #0x8c]
VANILLA_PAGE_MASK_LOOKUP = bytes.fromhex("8cc090e5")
PATCHED_PAGE_MASK_LOOKUP = bytes.fromhex("02c0a0e3")  # mov ip, #2
ADDR_EMPTY_LIST_BEQ = 0x003E6948  # beq 0x3e6d90
VANILLA_EMPTY_LIST_BEQ = bytes.fromhex("1001000a")
PATCHED_EMPTY_LIST_BEQ = bytes.fromhex("f600000a")  # beq 0x3e6d28
ADDR_WEB_ST14_NO_ARTICLE = 0x0005BC58  # beq hub when state 0xE has no article
VANILLA_WEB_ST14_NO_ARTICLE = bytes.fromhex("70ffff0a")
PATCHED_WEB_ST14_NO_ARTICLE = bytes.fromhex("0e00000a")  # beq 0x5BC98 stay
ADDR_WEB_WATCHER_OPEN = 0x0005B574  # success path after extra-data check
VANILLA_WEB_WATCHER_OPEN = bytes.fromhex("700094e5")  # ldr r0, [r4, #0x70]
PATCHED_WEB_WATCHER_OPEN = VANILLA_WEB_WATCHER_OPEN  # open state 0xE, layout 12
ADDR_MYROOM_NODATA_WIN = 0x0004FC20  # blne FUN_00207c84 0x84 ERROR window
VANILLA_MYROOM_NODATA_WIN = bytes.fromhex("17e0061b")
ADDR_MYROOM_NODATA_BL = 0x0004FC58  # bl FUN_00207b74 pack slot 0x17
VANILLA_MYROOM_NODATA_BL = bytes.fromhex("c5df06eb")
ADDR_LEFTOVER_SLOT8_BL = 0x0014E110  # bl FUN_00207b74 pack 0x9d01 slot 8
VANILLA_LEFTOVER_SLOT8_BL = bytes.fromhex("97e602eb")
ADDR_GATE_HASROWS_BL = 0x0014EBC4  # bl FUN_005fe9d8 (keep vanilla; entry stubbed)
VANILLA_GATE_HASROWS_BL = bytes.fromhex("83bf12eb")
ADDR_GATE_ENTRY = 0x0014EB9C  # FUN_0014eb9c extra-data No-data overlay
VANILLA_GATE_ENTRY = bytes.fromhex("f0472de908d04de2")  # stmdb {r4-r10,lr}; sub sp,#8
PATCHED_RET0 = bytes.fromhex("0000a0e31eff2fe1")  # mov r0,#0; bx lr
ADDR_GATE_OVERLAY_BEQ = 0x0014E16C  # beq 0x14e2a4 when +0xb4 == -1
VANILLA_GATE_OVERLAY_BEQ = bytes.fromhex("4c00000a")
PATCHED_GATE_OVERLAY_B = bytes.fromhex("4c0000ea")  # b 0x14e2a4 skip 0x84 ERROR
ADDR_PARENT_ST0_BEQ = 0x0010581C  # beq skip FUN_005fe5d0 when +0x45==0
VANILLA_PARENT_ST0_BEQ = bytes.fromhex("a002000a")
ADDR_HASROWS_FLAG_BEQ = 0x005FE9F0  # beq return 0 unless +0x45/+0x46
VANILLA_HASROWS_FLAG_BEQ = bytes.fromhex("0600000a")
ADDR_BINDROWS_FLAG_BEQ = 0x005FE730  # beq skip FUN_005fe718 bind
VANILLA_BINDROWS_FLAG_BEQ = bytes.fromhex("1000000a")
# Watcher extra-data bne restored (state 5). Command 0x10 was empty ERROR.
ADDR_WATCHER_EXTRA_BNE = 0x0010472C  # bne 0x104714
VANILLA_WATCHER_EXTRA_BNE = bytes.fromhex("f8ffff1a")
ADDR_WATCHER_ST17_BEQ = 0x00104890  # beq 0x1048ac
VANILLA_WATCHER_ST17_BEQ = bytes.fromhex("0500000a")
ADDR_PARENT_ST1_BEQ = 0x001058B0  # beq 0x1058cc
VANILLA_PARENT_ST1_BEQ = bytes.fromhex("0500000a")
WATCHER_RESTORE_SITES = (
    (ADDR_WATCHER_EXTRA_BNE, VANILLA_WATCHER_EXTRA_BNE),
    (ADDR_WATCHER_ST17_BEQ, VANILLA_WATCHER_ST17_BEQ),
    (ADDR_PARENT_ST1_BEQ, VANILLA_PARENT_ST1_BEQ),
)
# MagList command 9/10 is a no-op unless NetDl +0x45/+0x46 (BOSS pump).
# Merge ret1 never sets those, so the cart worker never runs → ERROR “No data.”
ADDR_MAGLIST_PUMP_BEQ = 0x005FE798  # beq skip FUN_005f838c
VANILLA_MAGLIST_PUMP_BEQ = bytes.fromhex("0200000a")
WATCHER_NOP_SITES = (
    (ADDR_MAGLIST_PUMP_BEQ, VANILLA_MAGLIST_PUMP_BEQ),
    (ADDR_HASROWS_FLAG_BEQ, VANILLA_HASROWS_FLAG_BEQ),
    (ADDR_BINDROWS_FLAG_BEQ, VANILLA_BINDROWS_FLAG_BEQ),
    (ADDR_PARENT_ST0_BEQ, VANILLA_PARENT_ST0_BEQ),
    (ADDR_PARENT_MAGLIST_SKIP, VANILLA_PARENT_MAGLIST_SKIP),
    (ADDR_MAGLIST_CLEAR_LAYOUT, VANILLA_MAGLIST_CLEAR_LAYOUT),
)
MAGLIST_WORD_SITES = (
    (ADDR_MAGLIST_CMD9_TAIL, VANILLA_MAGLIST_CMD9_TAIL, PATCHED_MAGLIST_CMD9_TAIL),
    (ADDR_MAGLIST_ST6_FAIL, VANILLA_MAGLIST_ST6_FAIL, PATCHED_MAGLIST_ST6_FAIL),
    (ADDR_PARENT_AFTER_MAGLIST, VANILLA_PARENT_AFTER_MAGLIST, PATCHED_PARENT_AFTER_MAGLIST),
    (ADDR_GATE_OVERLAY_BEQ, VANILLA_GATE_OVERLAY_BEQ, PATCHED_GATE_OVERLAY_B),
    (ADDR_WATCHER_ST0_MOV, VANILLA_WATCHER_ST0_MOV, PATCHED_WATCHER_ST0_MOV),
    (ADDR_WATCHER_EXTRA_CMP, VANILLA_WATCHER_EXTRA_CMP, PATCHED_WATCHER_EXTRA_CMP),
    (ADDR_PARENT_AFTER_WATCHER, VANILLA_PARENT_AFTER_WATCHER, PATCHED_PARENT_AFTER_WATCHER),
    (ADDR_WEB_WATCHER_EXTRA_BEQ, VANILLA_WEB_WATCHER_EXTRA_BEQ, ARM_NOP),
    (ADDR_WEB_WATCHER_FAIL_ST, VANILLA_WEB_WATCHER_FAIL_ST, PATCHED_WEB_WATCHER_FAIL_ST),
    (ADDR_WEB_WATCHER_ST9_FROM_E, VANILLA_WEB_WATCHER_ST9_FROM_E, PATCHED_WEB_WATCHER_FAIL_ST),
    (ADDR_WEB_WATCHER_ST9_DUP, VANILLA_WEB_WATCHER_ST9_DUP, PATCHED_WEB_WATCHER_FAIL_ST),
    (ADDR_WEB_WATCHER_ST9_ENTRY, VANILLA_WEB_WATCHER_ST9_ENTRY, PATCHED_WEB_WATCHER_ST9_ENTRY),
    (ADDR_WEB_WATCHER_OPEN, VANILLA_WEB_WATCHER_OPEN, PATCHED_WEB_WATCHER_OPEN),
    (ADDR_WEB_NO_LIST, VANILLA_WEB_NO_LIST, PATCHED_WEB_NO_LIST),
    (ADDR_WEB_NO_ARTICLE, VANILLA_WEB_NO_ARTICLE, PATCHED_WEB_NO_ARTICLE),
    (ADDR_WEB_ST14_NO_ARTICLE, VANILLA_WEB_ST14_NO_ARTICLE, PATCHED_WEB_ST14_NO_ARTICLE),
    (ADDR_MENU_ERROR_CASE, VANILLA_MENU_ERROR_CASE, PATCHED_MENU_ERROR_CASE),
    (ADDR_EMPTY_LAYOUT, VANILLA_EMPTY_LAYOUT, PATCHED_EMPTY_LAYOUT),
    (ADDR_LAYOUT29_RET, VANILLA_LAYOUT29_RET, PATCHED_LAYOUT29_RET),
    (ADDR_EMPTY_DIALOG_LAYOUT, VANILLA_EMPTY_DIALOG_LAYOUT, PATCHED_EMPTY_DIALOG_LAYOUT),
    (ADDR_EMPTY_DIALOG_BEQ, VANILLA_EMPTY_DIALOG_BEQ, PATCHED_EMPTY_DIALOG_BEQ),
    (ADDR_EMPTY_LIST_STATE, VANILLA_EMPTY_LIST_STATE, PATCHED_EMPTY_LIST_STATE),
    (ADDR_EMPTY_LIST_BEQ, VANILLA_EMPTY_LIST_BEQ, PATCHED_EMPTY_LIST_BEQ),
    (ADDR_PAGE_MASK_WALK, VANILLA_PAGE_MASK_WALK, PATCHED_PAGE_MASK),
    (ADDR_PAGE_MASK_LOOKUP, VANILLA_PAGE_MASK_LOOKUP, PATCHED_PAGE_MASK_LOOKUP),
    (ADDR_WEB_WATCHER_EMPTY_BL, VANILLA_WEB_WATCHER_EMPTY_BL, PATCHED_WEB_WATCHER_EMPTY_BL),
    (ADDR_WEB_LIST_HOLD, VANILLA_WEB_LIST_HOLD, PATCHED_WEB_LIST_HOLD),
    (ADDR_WEB_OPEN_LAYOUT, VANILLA_WEB_OPEN_LAYOUT, VANILLA_WEB_OPEN_LAYOUT),
    (ADDR_NODATA_MSG80, VANILLA_NODATA_MSG80, PATCHED_NODATA_MSG80),
    (ADDR_NODATA_MSG3, VANILLA_NODATA_MSG3, PATCHED_NODATA_MSG3),
    (ADDR_WEB_EMPTY_NOTIFY, VANILLA_WEB_EMPTY_NOTIFY, ARM_NOP),
    (ADDR_WEB_EMPTY_NOTIFY2, VANILLA_WEB_EMPTY_NOTIFY2, ARM_NOP),
    (ADDR_MYROOM_NODATA_WIN, VANILLA_MYROOM_NODATA_WIN, ARM_NOP),
    (ADDR_MYROOM_NODATA_BL, VANILLA_MYROOM_NODATA_BL, ARM_NOP),
    (ADDR_LEFTOVER_SLOT8_BL, VANILLA_LEFTOVER_SLOT8_BL, ARM_NOP),
)
FUN_START_JOB = 0x0059A788  # Communication Settings type-0xf kick
ADDR_DATA_KICK = 0x0014F018  # bl FUN_0059a788 from FUN_0014ed0c state 22
VANILLA_DATA_KICK = bytes.fromhex("da2d11eb")  # bl FUN_0059a788

FUN_SAVE_READY = 0x004E122C  # FUN_004e122c
FUN_APPLIED_HDR = 0x004E1C68  # unused; leftover from the header latch

VANILLA_FUN = bytes.fromhex(
    "38402de90040a0e10050a0e30500a0e1c64efceb00008de5080094e50d20a0e1"
    "0210a0e3cdadffeb000050e30e00001a080094e5b400d0e1040050e30a00001a"
    "2c009fe50020a0e30316a0e3434ffceb00008de5080094e50d20a0e10310a0e3"
    "beadffeb000050e30150a0130500a0e13880bde8"
)
# State 1: ldrb +0x48 / cmp #0 / beq / cmp #1 / bne  (then vanilla bl FUN_0059a7c4)
VANILLA_CONFIRM = bytes.fromhex("4800d4e5000050e30e00000a010050e30c00001a")
# Force +0x48 == 1 so tick state 1 enters apply (NewFlag already 1).
PATCHED_CONFIRM = bytes.fromhex("0100a0e3") + VANILLA_CONFIRM[4:]
VANILLA_READ_BL1 = bytes.fromhex("eb52fceb")  # bl FUN_0051eb8c
VANILLA_READ_BL2 = bytes.fromhex("db52fceb")
VANILLA_MERGE = bytes.fromhex("026c80e2")  # add r6, r0, #0x200
# Merge +0x250==0 is ac:u/WaitSync (skipped). The +0x250!=0 path maps a
# MemoryBlock (svc 0x24) — not a local parse of this+0x200. Stay vanilla.
ADDR_MERGE_BEQ = 0x006088FC  # beq 0x6089a8 MemoryBlock path
VANILLA_MERGE_BEQ = bytes.fromhex("2900000a")
ADDR_MERGE_PARSE = 0x00608900
VANILLA_MERGE_PARSE = bytes.fromhex(
    "0020a0e34c0294e50230a0e1240000efa01fb0e100008de5634be81b00009de50c129fe5000b51e15d00000a"
)
MERGE_PARSE_LEN = 0x2C

PAYLOAD_VA = ADDR_SPOTPASS_PAYLOAD + 0x100000


def _u32(word: int) -> bytes:
    return struct.pack("<I", word & 0xFFFFFFFF)


def _bl(here: int, target: int) -> bytes:
    return _u32(0xEB000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def _b_cond(cond: int, here: int, target: int) -> bytes:
    return _u32((cond << 28) | 0x0A000000 | (((target - here - 8) >> 2) & 0xFFFFFF))


def _b(here: int, target: int) -> bytes:
    return _b_cond(0xE, here, target)


def _ldr_pc(here: int, pool: int, rt: int = 0) -> bytes:
    imm = pool - (here + 8)
    if not 0 <= imm <= 0xFFF:
        raise ValueError(f"ldr pool {pool:#x} out of range from {here:#x}")
    return _u32(0xE5900000 | (15 << 16) | (rt << 12) | imm)


def build_area_cave(cave: int = ADDR_AREA_CAVE) -> bytes:
    """Bind Tex_Place on the spot widget (r8), then draw the station name.

    Entered in place of ``add r1, r5, #0x84``. r8 is the spot widget.
    Layout lookup tries the has-data group first, then the empty group.
    A miss leaves the pane null; the drawer returns without drawing.
    """
    name = _AREA_NAME
    # Code is fixed; the pool and string sit immediately after the epilogue.
    # Offsets below match the instruction list. Update both together.
    code_len = 0xB4
    pool = cave + code_len
    string_at = pool + 16
    words = [
        0xE92D4070,  # push {r4, r5, r6, lr}
        0xE24DD018,  # sub sp, sp, #0x18
        0xE5980078,  # ldr r0, [r8, #0x78]
        0xE3500000,  # cmp r0, #0
        None,  # bne draw
        0xE3A00001,  # mov r0, #1          store at pane index 1
        0xE5880070,  # str r0, [r8, #0x70]
        None,  # ldr r0, [pc, global]
        0xE5900000,  # ldr r0, [r0]
        0xE5982008,  # ldr r2, [r8, #8]
        0xE3A01001,  # mov r1, #1
        None,  # bl lookup
        0xE3500000,  # cmp r0, #0
        None,  # bne have
        None,  # ldr r0, [pc, global]
        0xE5900000,  # ldr r0, [r0]
        0xE5982008,  # ldr r2, [r8, #8]
        0xE3A01000,  # mov r1, #0
        None,  # bl lookup
        0xE3500000,  # cmp r0, #0
        None,  # beq draw
        0xE1A05000,  # mov r5, r0          have:
        0xE3A06000,  # mov r6, #0
        0xE1A04008,  # mov r4, r8
        0xE28D0010,  # add r0, sp, #0x10
        None,  # bl finder init
        0xE3A03000,  # mov r3, #0
        0xE28D2010,  # add r2, sp, #0x10
        None,  # ldr r1, [pc, pos]
        0xE1A00005,  # mov r0, r5
        None,  # bl find
        0xE3A030FF,  # mov r3, #0xff
        None,  # ldr r2, [pc, place]
        0xE28D1010,  # add r1, sp, #0x10
        0xE1A00004,  # mov r0, r4
        0xE58D6000,  # str r6, [sp]
        0xE58D6004,  # str r6, [sp, #4]
        0xE58D6008,  # str r6, [sp, #8]
        0xE58D600C,  # str r6, [sp, #0xc]
        None,  # bl store
        None,  # ldr r1, [pc, string]   draw:
        0xE1A00008,  # mov r0, r8
        None,  # bl drawer
        0xE28DD018,  # add sp, sp, #0x18
        0xE8BD8070,  # pop {r4, r5, r6, pc}
    ]
    if len(words) * 4 != code_len:
        raise ValueError(f"area cave code {len(words) * 4:#x} != {code_len:#x}")
    draw_at = cave + 0xA0
    have_at = cave + 0x54
    fixups = {
        4: _b_cond(0x1, cave + 0x10, draw_at),
        7: _ldr_pc(cave + 0x1C, pool, 0),
        11: _bl(cave + 0x2C, _AREA_LOOKUP),
        13: _b_cond(0x1, cave + 0x34, have_at),
        14: _ldr_pc(cave + 0x38, pool, 0),
        18: _bl(cave + 0x48, _AREA_LOOKUP),
        20: _b_cond(0x0, cave + 0x50, draw_at),
        25: _bl(cave + 0x64, _AREA_FINDER_INIT),
        28: _ldr_pc(cave + 0x70, pool + 4, 1),
        30: _bl(cave + 0x78, _AREA_FIND),
        32: _ldr_pc(cave + 0x80, pool + 8, 2),
        39: _bl(cave + 0x9C, _AREA_STORE),
        40: _ldr_pc(cave + 0xA0, pool + 12, 1),
        42: _bl(cave + 0xA8, _AREA_DRAW_PLACE),
    }
    blob = bytearray()
    for i, word in enumerate(words):
        if i in fixups:
            blob += fixups[i]
        else:
            if word is None:
                raise ValueError(f"area cave slot {i} has no encoding")
            blob += _u32(word)
    blob += _u32(_AREA_GLOBAL_VA)
    blob += _u32(_AREA_POS_VA)
    blob += _u32(_AREA_PLACE_VA)
    blob += _u32(string_at + 0x100000)
    blob += name
    if cave + len(blob) > ADDR_AREA_CAVE_LIMIT:
        raise ValueError(
            f"area cave ends @{cave + len(blob):#x}, past {ADDR_AREA_CAVE_LIMIT:#x}"
        )
    return bytes(blob)


def apply_area_name(data: bytearray) -> None:
    cave = build_area_cave()
    data[ADDR_AREA_CAVE : ADDR_AREA_CAVE + len(cave)] = cave
    hook = _bl(ADDR_AREA_DRAW, ADDR_AREA_CAVE) + ARM_NOP + ARM_NOP
    data[ADDR_AREA_DRAW : ADDR_AREA_DRAW + 12] = hook


def _one_row(cave: int, count_off: int, row_off: int, resume: int, prelude: bytes = b"") -> bytes:
    """Point the current stack row at pack 0x1901 slot 356 and continue."""
    code = bytearray(prelude)
    code += _u32(0xE3A00001)  # mov r0, #1
    code += _u32(0xE5800000 | (13 << 16) | count_off)  # str r0, [sp, #count]
    code += _u32(0xE2800000 | (13 << 16) | row_off)  # add r0, sp, #row
    code += _u32(0xE3A01C19)  # mov r1, #0x1900
    code += _u32(0xE2811001)  # add r1, r1, #1
    code += _u32(0xE1C010B8)  # strh r1, [r0, #8]
    code += _u32(0xE3A01F59)  # mov r1, #0x164
    code += _u32(0xE1C010BA)  # strh r1, [r0, #0xa]
    code += _b(cave + len(code), resume)
    return bytes(code)


def build_row_caves(cave: int = ADDR_ISSUE_CAVE) -> bytes:
    first = _one_row(cave, 0x184, 0x24, ADDR_ROW_RESUME)
    second_at = cave + len(first)
    # The second fill only sets the row base on the taken path.
    prelude = _u32(0xE28D8004) + _u32(0xE3A09001)  # add r8, sp, #4; mov r9, #1
    second = _one_row(second_at, 0x164, 0x4, ADDR_ROW2_RESUME, prelude)
    blob = first + second
    end = cave + len(blob)
    if end > 0x00609330:
        raise ValueError(f"row cave ends @{end:#x}")
    return blob


def build_slot_cave(cave: int = ADDR_ISSUE_CAVE) -> bytes:
    """Redo the slot add, then restore the flags the following beq needs."""
    code = bytearray()
    code += bytes.fromhex("078081e0")  # add r8, r1, r7
    code += _u32(0xE3500000)  # cmp r0, #0
    code += _b(cave + len(code), ADDR_SLOT_RESUME)
    if cave + len(code) > 0x00609330:
        raise ValueError(f"slot cave ends @{cave + len(code):#x}")
    return bytes(code)


def build_msg3_cave(cave: int = ADDR_ISSUE_CAVE) -> bytes:
    """Return from the message dialog when r2 is message id 3.

    Id 3 is pack 0x1001 slot 23, the STRI on the ERROR card. Other ids
    run the stolen prologue and continue at the next instruction.
    """
    code = bytearray()
    code += _u32(0xE3520003)  # cmp r2, #3
    code += _u32(0x012FFF1E)  # bxeq lr
    code += bytes.fromhex("f04f2de9")  # stmdb sp!, {r4-r11,lr}
    code += _b(cave + 12, ADDR_MSG3_ENTRY + 4)
    if len(code) != 16:
        raise ValueError(f"msg3 cave {len(code)} != 16")
    return bytes(code)


def build_issue_cave(cave: int = ADDR_ISSUE_CAVE) -> bytes:
    """Draw ISSUE_TITLE into window+0x60 when that pane is a heap object.

    r4 is the watcher operator. ``[r4+0x98]`` is the hit-test window. A pane
    pointer lives in FCRAM (``>= 0x08000000``). A null or a small field skips
    the draw and still returns to the click epilogue, so the empty layout
    never opens and BOSS is not called.
    """
    code = bytearray()
    code += _u32(0xE5940098)  # ldr r0, [r4, #0x98]
    code += _u32(0xE3500408)  # cmp r0, #0x08000000
    code += _b_cond(0x3, cave + 8, ADDR_PILL_EPILOGUE)
    code += _u32(0xE5902060)  # ldr r2, [r0, #0x60]
    code += _u32(0xE3520408)  # cmp r2, #0x08000000
    code += _b_cond(0x3, cave + 20, ADDR_PILL_EPILOGUE)
    code += _u32(0xE28F1004)  # add r1, pc, #4 → title
    code += _bl(cave + 28, ADDR_ISSUE_DRAW)
    code += _b(cave + 32, ADDR_PILL_EPILOGUE)
    if len(code) != 36:
        raise ValueError(f"issue cave code {len(code)} != 36")
    blob = bytes(code) + ISSUE_TITLE
    end = cave + len(blob)
    if end > 0x00609338:
        raise ValueError(f"issue cave ends @{end:#x}, past the info.dat literal")
    if len(blob) != len(VANILLA_ISSUE_BODY):
        raise ValueError(
            f"issue cave {len(blob)} != vanilla body {len(VANILLA_ISSUE_BODY)}"
        )
    return blob


# Do not draw on +0x60. That call clears Lyt_Bg. Both pills return.
PATCHED_WEB_PILL_LAYOUT = _b(ADDR_WEB_PILL_LAYOUT, ADDR_PILL_EPILOGUE)


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
    """Always return 1 so the tick enters apply (boot skip hides the nag)."""
    del base
    blob = _u32(0xE3A00001) + _u32(0xE12FFF1E)  # mov r0, #1; bx lr
    if len(blob) != 0x08:
        raise ValueError(f"newflag cave {len(blob):#x} != 0x08")
    return blob


def build_memcpy_cave(
    addr: int, payload_va: int = PAYLOAD_VA, size: int = 0x914
) -> bytes:
    """Copy ``size`` bytes from ``payload_va`` into the ReadNsData dest.

    Replaces ``bl FUN_0051eb8c``. Caller has ``r1 = dest`` from
    ``ldmia [wrapper,#0x48]``. ``r4`` is the ReadNsData wrapper, **not**
    merge ``this`` — do not write ``r4+0x200``.

    Null dest: store payload VA + size at ``wrapper+0x48/+0x4c`` and return
    ``size`` (``.rodata`` is RO on hardware, so do not self-copy).
    """
    blob = (
        _u32(0xE3510000)  # cmp r1, #0
        + _b_cond(0x1, addr + 0x04, addr + 0x1C)  # bne copy
        + _u32(0xE59F102C)  # ldr r1, [pc, #0x2c]  payload
        + _u32(0xE5841048)  # str r1, [r4, #0x48]
        + _u32(0xE59F0028)  # ldr r0, [pc, #0x28]  size
        + _u32(0xE584004C)  # str r0, [r4, #0x4c]
        + _u32(0xE12FFF1E)  # bx lr
        + _u32(0xE59F0018)  # copy: ldr r0,  [pc, #0x18]  payload
        + _u32(0xE59FC018)  # ldr r12, [pc, #0x18]  size
        + _u32(0xE4D03001)  # ldrb r3, [r0], #1
        + _u32(0xE4C13001)  # strb r3, [r1], #1
        + _u32(0xE25CC001)  # subs r12, r12, #1
        + _b_cond(0x1, addr + 0x30, addr + 0x24)  # bne loop
        + _u32(0xE59F0004)  # ldr r0, [pc, #0x4]  size
        + _u32(0xE12FFF1E)  # bx lr
        + _u32(payload_va)
        + _u32(size)
    )
    if len(blob) != 0x44:
        raise ValueError(f"memcpy cave {len(blob):#x} != 0x44")
    return blob


def memcpy_addr(base: int = ADDR_NEWFLAG) -> int:
    return base + len(build_newflag_cave(base))


def data_kick_addr(base: int = ADDR_NEWFLAG) -> int:
    return memcpy_addr(base) + 0x44


def build_data_kick_cave(addr: int) -> bytes:
    """Finish FUN_0059a788 then force the type-0xf job idle (no success bit).

    ``+1=1`` sent Communication Settings into state 24, whose layout ``0xCA``
    is the blank ERROR window. Keep the job done with empty flags so DATA
    does not open that overlay.
    """
    blob = (
        _u32(0xE92D4003)  # stmdb sp!, {r0, r1, lr}
        + _bl(addr + 4, FUN_START_JOB)
        + _u32(0xE8BD4003)  # ldmia sp!, {r0, r1, lr}
        + _u32(0xE3A02000)  # mov r2, #0
        + _u32(0xE5C02000)  # strb r2, [r0]      state done
        + _u32(0xE5C02001)  # strb r2, [r0, #1]  no success
        + _u32(0xE5C02004)  # strb r2, [r0, #4]  no incoming bits
        + _u32(0xE1A00000)  # nop
        + _u32(0xE12FFF1E)  # bx lr
    )
    if len(blob) != 0x24:
        raise ValueError(f"data-kick cave {len(blob):#x} != 0x24")
    return blob


def build_function_blob(base: int = ADDR_NEWFLAG) -> bytes:
    newflag = build_newflag_cave(base)
    memcpy = build_memcpy_cave(base + len(newflag))
    kick = build_data_kick_cave(base + len(newflag) + len(memcpy))
    blob = newflag + memcpy + kick
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
        and data[ADDR_CONFIRM : ADDR_CONFIRM + len(VANILLA_CONFIRM)] == VANILLA_CONFIRM
        and data[ADDR_READ_BL1 : ADDR_READ_BL1 + 4] == VANILLA_READ_BL1
        and data[ADDR_READ_BL2 : ADDR_READ_BL2 + 4] == VANILLA_READ_BL2
        and data[ADDR_MERGE_ENTRY : ADDR_MERGE_ENTRY + 8] == VANILLA_MERGE_ENTRY
        and data[ADDR_MERGE : ADDR_MERGE + 4] == VANILLA_MERGE
        and data[ADDR_MERGE_AC : ADDR_MERGE_AC + 4] == VANILLA_MERGE_AC
        and data[ADDR_MERGE_BEQ : ADDR_MERGE_BEQ + 4] == VANILLA_MERGE_BEQ
        and data[ADDR_MERGE_PARSE : ADDR_MERGE_PARSE + MERGE_PARSE_LEN]
        == VANILLA_MERGE_PARSE
        and data[ADDR_DATA_KICK : ADDR_DATA_KICK + 4] == VANILLA_DATA_KICK
        and data[ADDR_MAGLIST_EXTRA : ADDR_MAGLIST_EXTRA + 4] == VANILLA_MAGLIST_EXTRA
        and data[ADDR_MAGLIST_NODATA_BEQ : ADDR_MAGLIST_NODATA_BEQ + 4]
        == VANILLA_MAGLIST_NODATA_BEQ
        and all(
            data[addr : addr + 8] == vanilla
            for addr, vanilla in WATCHER_RET1_SITES
        )
        and data[ADDR_HASROWS_READY : ADDR_HASROWS_READY + 8] == VANILLA_HASROWS_READY
        and all(
            data[addr : addr + 4] == vanilla
            for addr, vanilla in WATCHER_NOP_SITES
        )
        and all(
            data[addr : addr + 4] == vanilla
            for addr, vanilla, _patched in MAGLIST_WORD_SITES
        )
        and all(
            data[addr : addr + 4] == vanilla
            for addr, vanilla in WATCHER_RESTORE_SITES
        )
        and data[ADDR_GATE_ENTRY : ADDR_GATE_ENTRY + 8] == VANILLA_GATE_ENTRY
        and data[ADDR_WEB_WATCHER_CLICK : ADDR_WEB_WATCHER_CLICK + 8]
        == VANILLA_WEB_WATCHER_CLICK
        and data[ADDR_WEB_PILL_LAYOUT : ADDR_WEB_PILL_LAYOUT + 4]
        == VANILLA_WEB_PILL_LAYOUT
        and data[ADDR_WEB_PILL_BODY : ADDR_WEB_PILL_BODY + 12]
        == VANILLA_WEB_PILL_BODY
        and data[ADDR_WEB_PILL_OTHER : ADDR_WEB_PILL_OTHER + 4]
        == VANILLA_WEB_PILL_OTHER
        and data[ADDR_GATE_HASROWS_BL : ADDR_GATE_HASROWS_BL + 4]
        == VANILLA_GATE_HASROWS_BL
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
    kick = data_kick_addr()
    return (
        data[ADDR_NEWFLAG : ADDR_NEWFLAG + NEWFLAG_LEN] == stub
        and data[ADDR_CONFIRM : ADDR_CONFIRM + len(PATCHED_CONFIRM)] == PATCHED_CONFIRM
        and _bl_target(data, ADDR_READ_BL1) == memcpy
        and _bl_target(data, ADDR_READ_BL2) == memcpy
        and _bl_target(data, ADDR_DATA_KICK) == kick
        and data[ADDR_MERGE_ENTRY : ADDR_MERGE_ENTRY + 8] == PATCHED_RET1
        and data[ADDR_MERGE : ADDR_MERGE + 4] == VANILLA_MERGE
        and data[ADDR_MERGE_AC : ADDR_MERGE_AC + 4] == PATCHED_MERGE_AC
        and data[ADDR_MERGE_BEQ : ADDR_MERGE_BEQ + 4] == VANILLA_MERGE_BEQ
        and data[ADDR_MERGE_PARSE : ADDR_MERGE_PARSE + MERGE_PARSE_LEN]
        == VANILLA_MERGE_PARSE
        and data[ADDR_MAGLIST_EXTRA : ADDR_MAGLIST_EXTRA + 4] == PATCHED_MAGLIST_EXTRA
        and data[ADDR_MAGLIST_NODATA_BEQ : ADDR_MAGLIST_NODATA_BEQ + 4]
        == VANILLA_MAGLIST_NODATA_BEQ
        and all(
            data[addr : addr + 8] == PATCHED_RET1 for addr, _ in WATCHER_RET1_SITES
        )
        and data[ADDR_HASROWS_READY : ADDR_HASROWS_READY + 8] == VANILLA_HASROWS_READY
        and all(
            data[addr : addr + 4] == ARM_NOP for addr, _ in WATCHER_NOP_SITES
        )
        and all(
            data[addr : addr + 4] == patched
            for addr, _vanilla, patched in MAGLIST_WORD_SITES
        )
        and all(
            data[addr : addr + 4] == vanilla
            for addr, vanilla in WATCHER_RESTORE_SITES
        )
        and data[ADDR_GATE_ENTRY : ADDR_GATE_ENTRY + 8] == PATCHED_RET0
        and data[ADDR_WEB_WATCHER_CLICK : ADDR_WEB_WATCHER_CLICK + 8]
        == VANILLA_WEB_WATCHER_CLICK
        and data[ADDR_WEB_PILL_LAYOUT : ADDR_WEB_PILL_LAYOUT + 4]
        == PATCHED_WEB_PILL_LAYOUT
        and data[ADDR_ROW_EMPTY : ADDR_ROW_EMPTY + 4] == VANILLA_ROW_EMPTY
        and data[ADDR_ROW2_EMPTY : ADDR_ROW2_EMPTY + 4] == VANILLA_ROW2_EMPTY
        and data[ADDR_SLOT_SUM : ADDR_SLOT_SUM + 4]
        == _b(ADDR_SLOT_SUM, ADDR_ISSUE_CAVE)
        and data[ADDR_ISSUE_CAVE : ADDR_ISSUE_CAVE + len(build_slot_cave())]
        == build_slot_cave()
        and data[ADDR_WEB_PILL_BODY : ADDR_WEB_PILL_BODY + 12]
        == VANILLA_WEB_PILL_BODY
        and data[ADDR_WEB_PILL_OTHER : ADDR_WEB_PILL_OTHER + 4]
        == PATCHED_WEB_PILL_OTHER
        and data[ADDR_GATE_HASROWS_BL : ADDR_GATE_HASROWS_BL + 4]
        == VANILLA_GATE_HASROWS_BL
        and data[ADDR_AREA_DRAW : ADDR_AREA_DRAW + 4]
        == _bl(ADDR_AREA_DRAW, ADDR_AREA_CAVE)
        and data[ADDR_AREA_CAVE : ADDR_AREA_CAVE + len(build_area_cave())]
        == build_area_cave()
        and _payload_slice(data) == payload
    )


def _old_embed(data: bytes) -> bool:
    """Prior merge-prologue memcpy (+0x250 smash) or dest-pointer ReadNsData."""
    try:
        payload = load_payload()
    except (OSError, ValueError):
        return False
    if _payload_slice(data) != payload:
        return False
    if data[ADDR_NEWFLAG : ADDR_NEWFLAG + 4] not in (
        _u32(0xE92D4010),
        _u32(0xE3A00000),
        _u32(0xE3A00001),
    ):
        return False
    return not is_patched(data)


def apply_patch(data: bytearray) -> bool:
    """Embed NsData + spoof NewFlag; copy into ReadNsData dest, not merge."""
    if is_patched(data):
        print("[spotpass-embed] already patched (NewFlag=1 + DATA kick + ReadNsData memcpy)")
        return False
    if not is_vanilla(data) and not _old_embed(data):
        got = data[ADDR_NEWFLAG : ADDR_NEWFLAG + 8].hex()
        raise ValueError(
            f"unexpected GetNsDataNewFlag @{ADDR_NEWFLAG:#x}: {got} "
            "(want vanilla FUN_00609ab0 + zero .rodata pad)"
        )
    payload = load_payload()
    stub = build_function_blob()
    memcpy = memcpy_addr()
    kick = data_kick_addr()
    data[ADDR_NEWFLAG : ADDR_NEWFLAG + NEWFLAG_LEN] = stub
    data[ADDR_CONFIRM : ADDR_CONFIRM + len(PATCHED_CONFIRM)] = PATCHED_CONFIRM
    data[ADDR_READ_BL1 : ADDR_READ_BL1 + 4] = _bl(ADDR_READ_BL1, memcpy)
    data[ADDR_READ_BL2 : ADDR_READ_BL2 + 4] = _bl(ADDR_READ_BL2, memcpy)
    data[ADDR_DATA_KICK : ADDR_DATA_KICK + 4] = _bl(ADDR_DATA_KICK, kick)
    data[ADDR_MERGE_ENTRY : ADDR_MERGE_ENTRY + 8] = PATCHED_RET1
    data[ADDR_MERGE : ADDR_MERGE + 4] = VANILLA_MERGE
    data[ADDR_MERGE_AC : ADDR_MERGE_AC + 4] = PATCHED_MERGE_AC
    data[ADDR_MERGE_BEQ : ADDR_MERGE_BEQ + 4] = VANILLA_MERGE_BEQ
    data[ADDR_MERGE_PARSE : ADDR_MERGE_PARSE + MERGE_PARSE_LEN] = VANILLA_MERGE_PARSE
    data[ADDR_MAGLIST_EXTRA : ADDR_MAGLIST_EXTRA + 4] = PATCHED_MAGLIST_EXTRA
    data[ADDR_MAGLIST_NODATA_BEQ : ADDR_MAGLIST_NODATA_BEQ + 4] = (
        VANILLA_MAGLIST_NODATA_BEQ
    )
    for addr, _vanilla in WATCHER_RET1_SITES:
        data[addr : addr + 8] = PATCHED_RET1
    data[ADDR_HASROWS_READY : ADDR_HASROWS_READY + 8] = VANILLA_HASROWS_READY
    for addr, _vanilla in WATCHER_NOP_SITES:
        data[addr : addr + 4] = ARM_NOP
    for addr, _vanilla, patched in MAGLIST_WORD_SITES:
        data[addr : addr + 4] = patched
    for addr, vanilla in WATCHER_RESTORE_SITES:
        data[addr : addr + 4] = vanilla
    data[ADDR_GATE_ENTRY : ADDR_GATE_ENTRY + 8] = PATCHED_RET0
    data[ADDR_WEB_WATCHER_CLICK : ADDR_WEB_WATCHER_CLICK + 8] = (
        VANILLA_WEB_WATCHER_CLICK
    )
    data[ADDR_WEB_PILL_LAYOUT : ADDR_WEB_PILL_LAYOUT + 4] = PATCHED_WEB_PILL_LAYOUT
    data[ADDR_WEB_PILL_BODY : ADDR_WEB_PILL_BODY + 12] = VANILLA_WEB_PILL_BODY
    data[ADDR_WEB_PILL_OTHER : ADDR_WEB_PILL_OTHER + 4] = PATCHED_WEB_PILL_OTHER
    data[ADDR_GATE_HASROWS_BL : ADDR_GATE_HASROWS_BL + 4] = VANILLA_GATE_HASROWS_BL
    apply_area_name(data)
    data[ADDR_HASENTRY_LDRB : ADDR_HASENTRY_LDRB + 4] = VANILLA_TABLES_READY
    data[ADDR_HASLIST_LDRB : ADDR_HASLIST_LDRB + 4] = VANILLA_TABLES_READY
    data[ADDR_ISSUE_CAVE : ADDR_ISSUE_CAVE + len(VANILLA_ISSUE_BODY)] = (
        VANILLA_ISSUE_BODY
    )
    slot = build_slot_cave()
    data[ADDR_ISSUE_CAVE : ADDR_ISSUE_CAVE + len(slot)] = slot
    data[ADDR_SLOT_SUM : ADDR_SLOT_SUM + 4] = _b(ADDR_SLOT_SUM, ADDR_ISSUE_CAVE)
    data[ADDR_ROW_EMPTY : ADDR_ROW_EMPTY + 4] = VANILLA_ROW_EMPTY
    data[ADDR_ROW2_EMPTY : ADDR_ROW2_EMPTY + 4] = VANILLA_ROW2_EMPTY
    data[ADDR_MSG3_ENTRY : ADDR_MSG3_ENTRY + 4] = VANILLA_MSG3_ENTRY
    data[ADDR_SPOTPASS_PAYLOAD : ADDR_SPOTPASS_PAYLOAD + len(payload)] = payload
    print(
        f"[spotpass-embed] NewFlag=1 @{ADDR_NEWFLAG:#x}, "
        f"ReadNsData memcpy @{memcpy:#x} dest r1 or payload VA, "
        f"confirm +0x48=1, DATA kick @{ADDR_DATA_KICK:#x} -> {kick:#x}, "
        f"merge ret1 @{ADDR_MERGE_ENTRY:#x} (no parse / ac:u), "
        f"MagList command 9 @{ADDR_MAGLIST_EXTRA:#x} then state 6, "
        f"parent dismiss @{ADDR_PARENT_AFTER_MAGLIST:#x}, "
        f"Watcher skip layout @{ADDR_WATCHER_ST0_MOV:#x} extra @{ADDR_WATCHER_EXTRA_CMP:#x} "
        f"then MagList @{ADDR_PARENT_AFTER_WATCHER:#x}, "
        f"WEB Watcher extra nop @{ADDR_WEB_WATCHER_EXTRA_BEQ:#x} "
        f"fail hub @{ADDR_WEB_WATCHER_FAIL_ST:#x}/"
        f"{ADDR_WEB_WATCHER_ST9_FROM_E:#x}/{ADDR_WEB_WATCHER_ST9_DUP:#x} "
        f"st9 @{ADDR_WEB_WATCHER_ST9_ENTRY:#x}, "
        f"gate ret0 @{ADDR_GATE_ENTRY:#x}, "
        f"skip leftover overlay @{ADDR_GATE_OVERLAY_BEQ:#x}, "
        f"Watcher ret1 @{ADDR_UNPACK_READY:#x}/"
        f"{ADDR_HASENTRY_READY:#x}/{ADDR_HASLIST_READY:#x}/"
        f"{ADDR_HASSTATE6_READY:#x}/{ADDR_PREUNPACK_READY:#x}, "
        f"has-rows vanilla @{ADDR_HASROWS_READY:#x}, "
        f"nop MagList pump @{ADDR_MAGLIST_PUMP_BEQ:#x} "
        f"has-rows/bind flags + parent MagList skip/st0, "
        f"payload {len(payload)} B @ {ADDR_SPOTPASS_PAYLOAD:#x}, "
        f"pills return @{ADDR_WEB_PILL_LAYOUT:#x}/{ADDR_WEB_PILL_OTHER:#x} "
        f"(no +0x60 draw), "
        f"list hold @{ADDR_WEB_LIST_HOLD:#x}, "
        f"open layout @{ADDR_WEB_OPEN_LAYOUT:#x} vanilla (room backdrop), "
        f"msg80 slot @{ADDR_NODATA_MSG80:#x} -> 178, "
        f"skip empty notify @{ADDR_WEB_EMPTY_NOTIFY:#x}/{ADDR_WEB_EMPTY_NOTIFY2:#x}, "
        f"skip slot 356 @{ADDR_SLOT_SUM:#x}"
    )
    return True


def restore_readnsdata_ipc(data: bytearray) -> None:
    """Point ReadNsData back at BOSS. Merge stays ``mov r0,#1``.

    The embed memcpy never asks Azahar to open boss extdata. This build's
    HLE scans the title archive ``extdata/00000000/00000F4E/boss/`` (ROM
    extdata id). Shared ``00000321`` is the hardware SpotPass id; Azahar's
    session does not switch to it. A later default ``apply_patch`` puts the
    memcpy back.
    """
    data[ADDR_READ_BL1 : ADDR_READ_BL1 + 4] = VANILLA_READ_BL1
    data[ADDR_READ_BL2 : ADDR_READ_BL2 + 4] = VANILLA_READ_BL2


def revert_patch(data: bytearray) -> bool:
    if is_vanilla(data):
        print("[spotpass-embed] already vanilla")
        return False
    if not is_patched(data) and not _old_embed(data):
        raise ValueError("cannot revert: SpotPass embed is neither vanilla nor patched")
    data[ADDR_NEWFLAG : ADDR_NEWFLAG + NEWFLAG_LEN] = VANILLA_FUN
    data[ADDR_CONFIRM : ADDR_CONFIRM + len(VANILLA_CONFIRM)] = VANILLA_CONFIRM
    data[ADDR_READ_BL1 : ADDR_READ_BL1 + 4] = VANILLA_READ_BL1
    data[ADDR_READ_BL2 : ADDR_READ_BL2 + 4] = VANILLA_READ_BL2
    data[ADDR_DATA_KICK : ADDR_DATA_KICK + 4] = VANILLA_DATA_KICK
    data[ADDR_MERGE_ENTRY : ADDR_MERGE_ENTRY + 8] = VANILLA_MERGE_ENTRY
    data[ADDR_MERGE : ADDR_MERGE + 4] = VANILLA_MERGE
    data[ADDR_MERGE_AC : ADDR_MERGE_AC + 4] = VANILLA_MERGE_AC
    data[ADDR_MERGE_BEQ : ADDR_MERGE_BEQ + 4] = VANILLA_MERGE_BEQ
    data[ADDR_MERGE_PARSE : ADDR_MERGE_PARSE + MERGE_PARSE_LEN] = VANILLA_MERGE_PARSE
    data[ADDR_MAGLIST_EXTRA : ADDR_MAGLIST_EXTRA + 4] = VANILLA_MAGLIST_EXTRA
    data[ADDR_MAGLIST_NODATA_BEQ : ADDR_MAGLIST_NODATA_BEQ + 4] = (
        VANILLA_MAGLIST_NODATA_BEQ
    )
    for addr, vanilla in WATCHER_RET1_SITES:
        data[addr : addr + 8] = vanilla
    data[ADDR_HASROWS_READY : ADDR_HASROWS_READY + 8] = VANILLA_HASROWS_READY
    for addr, vanilla in WATCHER_NOP_SITES:
        data[addr : addr + 4] = vanilla
    for addr, vanilla, _patched in MAGLIST_WORD_SITES:
        data[addr : addr + 4] = vanilla
    for addr, vanilla in WATCHER_RESTORE_SITES:
        data[addr : addr + 4] = vanilla
    data[ADDR_GATE_ENTRY : ADDR_GATE_ENTRY + 8] = VANILLA_GATE_ENTRY
    data[ADDR_WEB_WATCHER_CLICK : ADDR_WEB_WATCHER_CLICK + 8] = VANILLA_WEB_WATCHER_CLICK
    data[ADDR_WEB_PILL_LAYOUT : ADDR_WEB_PILL_LAYOUT + 4] = VANILLA_WEB_PILL_LAYOUT
    data[ADDR_WEB_PILL_BODY : ADDR_WEB_PILL_BODY + 12] = VANILLA_WEB_PILL_BODY
    data[ADDR_WEB_PILL_OTHER : ADDR_WEB_PILL_OTHER + 4] = VANILLA_WEB_PILL_OTHER
    data[ADDR_GATE_HASROWS_BL : ADDR_GATE_HASROWS_BL + 4] = VANILLA_GATE_HASROWS_BL
    data[ADDR_AREA_DRAW : ADDR_AREA_DRAW + len(VANILLA_AREA_DRAW)] = VANILLA_AREA_DRAW
    data[ADDR_AREA_CAVE : ADDR_AREA_CAVE + len(VANILLA_AREA_CAVE_BODY)] = (
        VANILLA_AREA_CAVE_BODY
    )
    data[ADDR_HASENTRY_LDRB : ADDR_HASENTRY_LDRB + 4] = VANILLA_TABLES_READY
    data[ADDR_HASLIST_LDRB : ADDR_HASLIST_LDRB + 4] = VANILLA_TABLES_READY
    data[ADDR_ISSUE_CAVE : ADDR_ISSUE_CAVE + len(VANILLA_ISSUE_BODY)] = (
        VANILLA_ISSUE_BODY
    )
    data[ADDR_ROW_EMPTY : ADDR_ROW_EMPTY + 4] = VANILLA_ROW_EMPTY
    data[ADDR_ROW2_EMPTY : ADDR_ROW2_EMPTY + 4] = VANILLA_ROW2_EMPTY
    data[ADDR_SLOT_SUM : ADDR_SLOT_SUM + 4] = VANILLA_SLOT_SUM
    data[ADDR_MSG3_ENTRY : ADDR_MSG3_ENTRY + 4] = VANILLA_MSG3_ENTRY
    data[ADDR_SPOTPASS_PAYLOAD : ADDR_SPOTPASS_PAYLOAD + 0x914] = b"\x00" * 0x914
    print("[spotpass-embed] restored vanilla GetNsDataNewFlag / merge / .rodata pad")
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
            f"FUN_00609ab0 @{ADDR_NEWFLAG:#x}: NewFlag always 1 + "
            f"ReadNsData memcpy @{memcpy:#x} (0x44), "
            f"DATA kick @{data_kick_addr():#x} (0x24), "
            f"pad {NEWFLAG_LEN - len(stub):#x}"
        )
        print(f"ReadNsData BLs @{ADDR_READ_BL1:#x}/@{ADDR_READ_BL2:#x} -> {memcpy:#x}")
        print(f"merge entry @{ADDR_MERGE_ENTRY:#x} -> mov r0,#1; bx lr")
        print(f"merge @{ADDR_MERGE:#x} stays vanilla add r6,#0x200")
        print(f"merge ac:u @{ADDR_MERGE_AC:#x} still skip (dead after ret1)")
        print(f"merge parse @{ADDR_MERGE_BEQ:#x}/@{ADDR_MERGE_PARSE:#x} vanilla")
        print(f"confirm @{ADDR_CONFIRM:#x} mov r0,#1 (enter apply)")
        print(f"DATA kick @{ADDR_DATA_KICK:#x} -> {data_kick_addr():#x}")
        print(
            f"Watcher ret1 @{ADDR_UNPACK_READY:#x}/"
            f"{ADDR_HASENTRY_READY:#x}/{ADDR_HASLIST_READY:#x}/"
            f"{ADDR_HASSTATE6_READY:#x}/{ADDR_PREUNPACK_READY:#x}"
        )
        print(
            f"MagList command 9 @{ADDR_MAGLIST_EXTRA:#x} -> state 6, "
            f"parent dismiss @{ADDR_PARENT_AFTER_MAGLIST:#x}, "
            f"Watcher skip layout @{ADDR_WATCHER_ST0_MOV:#x} then MagList @{ADDR_PARENT_AFTER_WATCHER:#x}, "
            f"WEB Watcher extra nop @{ADDR_WEB_WATCHER_EXTRA_BEQ:#x} "
            f"fail hub @{ADDR_WEB_WATCHER_FAIL_ST:#x}/"
            f"{ADDR_WEB_WATCHER_ST9_FROM_E:#x}/{ADDR_WEB_WATCHER_ST9_DUP:#x} "
            f"st9 @{ADDR_WEB_WATCHER_ST9_ENTRY:#x}, "
            f"gate ret0 @{ADDR_GATE_ENTRY:#x}, "
            f"WEB pills return @{ADDR_WEB_PILL_LAYOUT:#x}/{ADDR_WEB_PILL_OTHER:#x} "
            f"(no +0x60 draw), "
            f"skip leftover overlay @{ADDR_GATE_OVERLAY_BEQ:#x}, "
            f"nop MagList pump @{ADDR_MAGLIST_PUMP_BEQ:#x}"
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
