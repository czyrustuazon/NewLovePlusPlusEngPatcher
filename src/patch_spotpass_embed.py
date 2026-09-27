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
# Holy-site names. Tex_Name / Tex_Place are DrawText'd from inline buffers
# the stubbed merge never fills, and the pane pointers stay null while the
# binder searches the empty-data group. The cave binds both panes, then
# draws 「湖」 and the station in the game font. It sits in the dead body
# of the ret0 gate, after the vanilla has-rows BL at 0x14EBC4.
ADDR_AREA_DRAW = 0x004DCBCC  # add r1, r5, #0x84 ; mov r0, r8 ; bl drawer
VANILLA_AREA_DRAW = bytes.fromhex("841085e20800a0e17ca7f5eb")
ADDR_AREA_CAVE = 0x0014EBC8
ADDR_AREA_CAVE_LIMIT = 0x0014ECFC
_AREA_LOOKUP = 0x005C6E84
_AREA_FINDER_INIT = 0x005E828C
_AREA_FIND = 0x005EBA00
_AREA_STORE = 0x00199B98
_AREA_DRAW_PLACE = 0x002469CC  # index 1, Tex_Place
_AREA_DRAW_NAME = 0x002469D8  # index 0, Tex_Name
_AREA_GLOBAL_VA = 0x008BFA40
_AREA_POS_VA = 0x003468E4  # "Pos_Spot_O01"
_AREA_NAME_VA = 0x003468F4  # "Tex_Name"
_AREA_PLACE_VA = 0x00346900  # "Tex_Place"
_AREA_NAME = "奥十羽野駅".encode("utf-8") + b"\x00"
_SPOT_NAME = "湖".encode("utf-8") + b"\x00"
# Dead instructions the cave replaces (gate body after the has-rows BL).
VANILLA_AREA_CAVE_BODY = bytes.fromhex(
    "30a19fe530919fe530719fe5000054e30060a0e10080a0e30500000a"
    "000055e32500000a000097e5000050e31100000a180000ea000097e5"
    "000050e30700001a1020a0e30010a0e38400a0e35020fbeb000050e3"
    "00f020e317e4021b000087e50070b0e12d00000a0120a0e36010a0e3"
    "0a00a0e1220000ea1020a0e30010a0e38400a0e34220fbeb000050e3"
    "00f020e309e4021b000087e50070b0e11f00000a0120a0e37010a0e3"
    "0a00a0e134c811eb00f020e300f020e3120000ea000056e31600001a"
    "000097e5000050e30700001a1020a0e30010a0e38400a0e32c20fbeb"
    "000050e300f020e3f3e3021b000087e50070b0e10900000a0120a0e3"
    "0f10a0e39d0c82e21ec811eb0030a0e10120a0e30310a0e30700a0e1"
    "f080cde1"
)
# MagList: extra-data version + no bit 0x20 → state 5. NOP of that beq
# sent worker command 10 (empty SpotPass). Force command 9 (cart).
ADDR_MAGLIST_EXTRA = 0x0010441C  # cmp r0,#0 after FUN_004fd248
VANILLA_MAGLIST_EXTRA = bytes.fromhex("000050e3")  # cmp r0, #0
PATCHED_MAGLIST_EXTRA = bytes.fromhex("0c0000ea")  # b 0x104454 mov r2,#9
# bl FUN_004fd248. Leaving it in crashes with 0xD8E007F7. NOP-ing it
# reaches command 9. A constructed worker still dies in FUN_005fe718:
# PC=0, LR=0x005F99B4. Keep the call. Do not host this operator.
ADDR_MAGLIST_FATAL_BL = 0x00104418
VANILLA_MAGLIST_FATAL_BL = bytes.fromhex("8ae30feb")
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
# The book opens on Holy Site and the arrows turn to FEVER. Bits 1 and 3
# are those two corners. Empty corners stay clear, so the page number only
# moves between 01/02 and 03/04.
ADDR_PAGE_MASK_WALK = 0x004DA664  # ldr r2, [r4, #0x8c]
VANILLA_PAGE_MASK_WALK = bytes.fromhex("8c2094e5")
PATCHED_PAGE_MASK = bytes.fromhex("0a20a0e3")  # mov r2, #0x0a
ADDR_PAGE_MASK_LOOKUP = 0x00631354  # ldr ip, [r0, #0x8c]
VANILLA_PAGE_MASK_LOOKUP = bytes.fromhex("8cc090e5")
PATCHED_PAGE_MASK_LOOKUP = bytes.fromhex("0ac0a0e3")  # mov ip, #0x0a
ADDR_EMPTY_LIST_BEQ = 0x003E6948  # beq 0x3e6d90
VANILLA_EMPTY_LIST_BEQ = bytes.fromhex("1001000a")
# Book-only rollback 69df39c jumps straight at the TownGuide constructor.
PATCHED_EMPTY_LIST_BEQ = bytes.fromhex("f600000a")  # beq 0x3e6d28
# Empty index: point the parser at a two-row contents blob, then fall
# into the same fill that opens the book. Cave sits in the dead gate
# body, after the area-name cave and before the pop at 0x14ECF8.
# The magazine list operator shows the StreetPass prompt (layout 7).
# FUN_004fd248 then fatals (0xD8E007F7). Skipping that call reaches
# command 9 with a null worker (R8=0, PC=0, LR=0x006FE7A4). Do not
# construct it in the book's slot.
# The room tap builds TownGuideHome, which always opens the book.
# WebUIOperator is the in-game browser, constructed the same way
# (alloc, ctor, link) from 0x3b02c8 / 0x3b04b8 / 0x45125c.
ADDR_HOME_OPEN_BL = 0x003E6574  # bl TownGuideHome ctor
VANILLA_HOME_OPEN_BL = bytes.fromhex("590300eb")  # bl 0x3e72e0
ADDR_WEB_UI_CTOR = 0x0014A31C
# WebUI state 0 asks the parent to show it (vtable+0x58). The room
# has no such slot (PC 0, LR 0x0024977C). Skipping that call leaves
# the browser idle on the classroom. Its real parent is LoveplusModeHome.
# Do not open it from the watcher tap.
ADDR_WEB_NOTIFY = 0x00149778  # blx ip
VANILLA_WEB_NOTIFY = bytes.fromhex("3cff2fe1")
# Holding book tick state 2 (mov r0,#2 here) left the classroom.
# State 1's layouts are not drawn. State 2 returns while its anim slot
# is empty, and the spread is built in state 3+. Keep the vanilla mov.
ADDR_BOOK_OPEN_NEXT = 0x004DBA58  # mov r0, #3
VANILLA_BOOK_OPEN_NEXT = bytes.fromhex("0300a0e3")
ADDR_BOOK_CTOR = 0x003E6D54  # bl TownGuideUIOperator ctor
ADDR_MENU_CTOR = 0x001064F4
ADDR_MENU_CAVE = 0x0014EBA4
ADDR_BOOK_CTOR_RESUME = 0x003E6D58
ADDR_MENU_DRAW = 0x001040D8  # magazine vtable+0x10
VANILLA_BOOK_CTOR = bytes.fromhex("75d803eb")  # bl 0x4dcf30
VANILLA_MENU_CAVE = bytes.fromhex("e832fbeba6b90eeb0040a0e1c4b90eeb")
VANILLA_MENU_DRAW = bytes.fromhex("30402de90040a0e1")
PATCHED_MENU_DRAW = bytes.fromhex("0100a0e31eff2fe1")  # mov r0,#1; bx lr
# Factory at 0x249C2C allocates 0xA60 (2656). Forcing +0x5e=0xC and
# skipping the fatal bl showed StreetPass, then FUN_005fe718 jumped
# [worker+0x4c vtable+0x24]. State 0 is the untried entry: it calls
# FUN_005fe5d0 on *0x008BFAEC and advances to state 1. The ctor already
# stores +0x5e=0. Do not call apply_worker_host from apply_patch.
ADDR_WORKER_FACTORY = 0x00249C2C
ADDR_DRAW_BODY = 0x001040E0  # vtable+0x10 body; must stay vanilla so it can draw
ADDR_DRAW_CHILD = 0x00104144
# Dead body of FUN_006093f4. Entry is ret1. Stop before the live call at 0x6094C0.
ADDR_WORKER_CAVE = 0x006093FC
ADDR_STATE6_LIMIT = 0x006094C0
# Contents list. The book draws record+0x104 into Tex_Info_01 (180x128,
# right page) and merge leaves that pane null. This cave binds it and
# draws the six section names. The string sits in .rodata; the code stays
# in this dead body. Do not execute the string.
ADDR_INFO_DRAW = 0x004DCBD8  # add r1, r5, #0x104 ; mov r0, r6 ; bl index 0
VANILLA_INFO_DRAW = bytes.fromhex("411f85e20600a0e109a9f5eb")
ADDR_MENU_LIST_CAVE = ADDR_WORKER_CAVE
ADDR_MENU_LIST_LIMIT = 0x006094BC
ADDR_MENU_LIST_STR = 0x006E6A38
_INFO_DRAW = 0x0024700C
_INFO_POS_VA = 0x00346FB0  # Pos_Spot_U01
_INFO_TEX_VA = 0x00346FC0  # Tex_Info_01
# Title binder tail calls. Leaving them in swaps the banner to 恋愛の聖地
# because the mask is bit 1. bx lr keeps the layout's own banner.
ADDR_TITLE_BIND_FIXED = 0x004DB6C8
VANILLA_TITLE_BIND_FIXED = bytes.fromhex("52aef5ea")  # b 0x247018
ADDR_TITLE_BIND_INDEX = 0x004DB730
VANILLA_TITLE_BIND_INDEX = bytes.fromhex("38aef5ea")  # b 0x247018
PATCHED_TITLE_BIND_SKIP = bytes.fromhex("1eff2fe1")  # bx lr
# Banner index, then the name drawn in the list. An issue leaves a corner
# out when that corner has no sentence. Issue 28 has the lake and the pool.
MENU_FILLED = (
    (1, "Holy Site"),
    (3, "FEVER"),
)
# Six stride slots. The arrow stores the banner index and adds index<<7.
MENU_SLOT_COUNT = 6
MENU_STRIDE = 128
# Dead body of the ret1 has-entry function, then its literal pool, stopping
# before the live function at 0x609208. The arrow cave plus its pool sit here.
ADDR_MENU_ARROW = 0x00609170
ADDR_MENU_ARROW_LIMIT = 0x00609208
VANILLA_MENU_ARROW_BODY = bytes.fromhex(
    "1cd04de2000050e30000a0e31900000a0100a0e1c80400eb0050a0e15c009fe5"
    "14008de50d00a0e1f655fceb0510a0e10d00a0e1d553fceb14008de514208de2"
    "0a10a0e39d0f84e214b0ffeb000050e314009d050200000a0d00a0e10655fceb"
    "14008de5c00fa0e1015080e20d00a0e10000a0e10500a0e11cd08de23080bde8"
    "ffffe3e70d00a0e100f020e30000a0e100f020e39de3effa"
)
VANILLA_MENU_OPEN_BODY = bytes.fromhex(
    "000050e32c00000a0100a0e1a30300eb0070a0e11020a0e30010a0e3ff0f82e2"
    "ca35e8eb000050e30050a0030100000acd4cfceb0050a0e10500a0e1934ffceb"
    "c00fa0e1010090e21500000a0040a0e30500a0e1b400d0e1000050e300f020e3"
    "0f00009a0410a0e10500a0e1b84cfceb0710a0e100f020e36dd2efeb000050e3"
    "00f020e30e00000a010084e27040ffe60500a0e1b400d0e1040050e100f020e3"
    "efffff8a000055e30300000a000095e5041090e50500a0e131ff2fe10600a0e1"
    "f081bde80160a0e3f5ffffea"
)
# Dead body after the has-list ret1 and the restored ldrb at 0x609608.
# Prep and the sheet show/hide sit here. Stop before the next live function.
ADDR_MENU_OPEN = 0x0060960C
ADDR_MENU_OPEN_LIMIT = 0x006096D8
# After the pad's pop. Draws 「湖」 / 奥十羽野駅, or the pool spot and a blank station.
ADDR_PLACE_LABELS = ADDR_MENU_OPEN + 21 * 4
# beq taken when the page mask has nowhere to turn. Both arrows land here.
ADDR_ARROW_SKIP = 0x004DCCB4
VANILLA_ARROW_SKIP = bytes.fromhex("0900000a")  # beq 0x4dcce0
ADDR_ARROW_CONSUME = 0x004DCCE0
# While the book is sitting still (+0x5e == 0) this beq used to skip the
# arrow poll. It now enters the back-finish check: a pending もどる leave
# completes, and every other idle frame still polls the page arrows.
ADDR_ARROW_IDLE = 0x004DCC30
VANILLA_ARROW_IDLE = bytes.fromhex("4100000a")  # beq 0x4dcd3c
ADDR_ARROW_POLL = 0x004DCC60  # vtable+0x84 on the left widget, then the right
ADDR_ARROW_POLL_TAIL = 0x004DCC80
# Stay on the vanilla branch to the もどる check. A clear +0xdb byte falls
# through to the page-arrow latch. A set byte leaves the book only while the
# list is up. An open article restores that list instead.
VANILLA_ARROW_POLL_TAIL = bytes.fromhex("efffffea")  # b 0x4dcc44
ADDR_ARROW_LATCH = 0x004DCC84
ADDR_BACK_SET = 0x004DCC4C
VANILLA_BACK_SET = bytes.fromhex("0c00000a")  # beq 0x4dcc84
ADDR_BACK_LEAVE = 0x004DCC50
VANILLA_BACK_LEAVE = bytes.fromhex("0108a0e3")  # mov r0, #0x10000
ADDR_BACK_LEAVE_CONT = 0x004DCC54
# The page step used to run before the marker cave, and a real page
# left the list. Branch straight to the cave instead.
ADDR_ARROW_STEP = 0x004DCCA8
VANILLA_ARROW_STEP = bytes.fromhex("6af6ffeb")  # bl 0x4da658
VANILLA_ARROW_CMN = bytes.fromhex("010070e3")  # cmn r0, #1 at 0x4dccac
# These two still call the page step. A real result stores a new page
# and leaves the list. The block moves the marker, redraws, then
# returns -1 so the press is only consumed.
ADDR_TWIN_STEP = 0x004DA97C
ADDR_THIRD_STEP = 0x004DAED8
ADDR_PAGE_STEP = 0x004DA658
# 26 zero bytes. The redraw wrapper uses 24. Do not touch 0x68F892,
# and do not put this over the back stub at 0x68F8E0.
ADDR_PAGE_BLOCK = 0x0068F878
ADDR_PAGE_BLOCK_LIMIT = 0x0068F890
# Name-input turns FUN_001fc304 into a branch and zeros the old body.
# The button poll sits in that padding. apply_info_menu runs after the
# romaji refresh, which clears this span first.
ADDR_MENU_PAD = 0x001FC308
ADDR_MENU_PAD_LIMIT = 0x001FC3A4
# Steady book frames skip the info-draw hook once +0x5c is 0. This load
# is on the path those frames do take, so the A poll has to run from here.
ADDR_MENU_POLL = 0x004DCC10
VANILLA_MENU_POLL = bytes.fromhex("8800d4e5")  # ldrb r0, [r4, #0x88]
MENU_PAD_LEN = 108
ADDR_KEYS = 0x005CB4C4
# One page makes both directions return -1, and these movs then hide
# the arrows, so the latches never get set. Leave the arrows shown.
ADDR_ARROW_SHOW = (
    0x004DCB34,  # name refresh, previous
    0x004DCB58,  # name refresh, next
    0x004DA8E4,  # other book update, previous
    0x004DA908,  # other book update, next
)
VANILLA_ARROW_HIDE = bytes.fromhex("0010a0e3")  # mov r1, #0
PATCHED_ARROW_SHOW = bytes.fromhex("0110a0e3")  # mov r1, #1
# 32 zero bytes between a finished name-input branch and the romaji cave.
ADDR_MENU_IDLE_POLL = 0x0068F8E0
ADDR_MENU_IDLE_POLL_LIMIT = 0x0068F900
# .data cell nothing else points at. +0 string VA, +4 index, +8 opened,
# +12 VA of the empty string used while an article is open,
# +16 last button word, +20 base VA of the six choice strings,
# +28 right-page widget, +32 left-page widget.
ADDR_MENU_CELL = 0x007A5100
ADDR_TITLE_BIND_FN = 0x00247018
_SHEET_NAME = b"Pic_Page01_04\x00"
_SHEET_PART = b"Pic_Page01_00\x00"
_PANE_SHOW = 0x005E7D18  # finder in r0, r1 = 0 hides / 1 shows (pane+0xb7 bit 0)
_LAKE_BODY = (
    "第28号\n"
    "今回の恋愛の聖地は\n"
    "「湖」に決定しました！\n"
    "湖面を伝わって流れる空気は\n"
    "見た目も相まって清涼感抜群。\n"
    "たまには趣を変え湖畔で\n"
    "カノジョと過ごすのも\n"
    "悪くないかもしれません。"
).encode("utf-8") + b"\x00"
# Issue 28's heated-pool paragraph, with the same issue header as Holy Site.
# Line breaks are the ones in info.dat.
_FEVER_BODY = (
    "第28号\n"
    "一年を通して水着で楽しめる大型\n"
    "温水プール施設です。流れるプー\n"
    "ルやウォータースライダーなどの\n"
    "遊具だけでなく、軽食も楽しむこ\n"
    "とができ、ここもカップルに人気\n"
    "の定番スポットとなっています。"
).encode("utf-8") + b"\x00"
# The pool record names the facility and no station. 「湖」 / 奥十羽野駅 stay
# the lake pair. Five ideographic spaces clear the station line.
_POOL_SPOT = "温水プール".encode("utf-8") + b"\x00"
_POOL_AREA = ("\u3000" * 5).encode("utf-8") + b"\x00"
_PLACE_NAMES = _SPOT_NAME + _AREA_NAME + _POOL_SPOT + _POOL_AREA
ADDR_LAKE_BODY = 0x006E6F42  # vanilla zero pad, after the menu strings
ADDR_FEVER_BODY = ADDR_LAKE_BODY + len(_LAKE_BODY)
ADDR_PLACE_NAMES = ADDR_FEVER_BODY + len(_FEVER_BODY)
_SENTENCE_ROOM = 986
ADDR_WORKER_GLOBAL = 0x008BFAEC
ADDR_SESSION_RET = 0x0024EB9C  # VA of mov r0,#0; bx lr
ADDR_UI_ROOT = 0x008A6558  # slot 2 is the parent 0x4525f4 attaches id 0x37 to
ADDR_UI_LOOKUP = 0x0044D370
ADDR_UI_CHILD = 0x004525F4
ADDR_CHILD_CALL = 0x00105CB4  # blx r3 on the null +0x60 child
VANILLA_CHILD_CALL = bytes.fromhex("33ff2fe1")
# State 11's taken path clears the inner state, then branches out.
# Start MagList at inner state 6 instead, and fall into the idle exit.
ADDR_MAGLIST_ENTER_INNER = 0x00105D38
VANILLA_MAGLIST_ENTER_INNER = bytes.fromhex("6450c4e5580100ea")
PATCHED_MAGLIST_ENTER_INNER = bytes.fromhex("0650a0e36450c4e5")  # mov r5,#6; strb
# State 6's exit stores inner state 0x17, and the parent then dismisses.
ADDR_MAGLIST_ST6_STAY = 0x00104534
VANILLA_MAGLIST_ST6_STAY = bytes.fromhex("ebffffea")  # b 0x1044e8
PATCHED_MAGLIST_ST6_STAY = bytes.fromhex("210000ea")  # b 0x1045c0 stay
ADDR_CHILD_CAVE = 0x00609460
VANILLA_CHILD_CAVE = bytes.fromhex(
    "000090e588240deb000050e3600094050200000a3710a0e324390deb"
    "600084e5000050e378408015e8009fe5000090e5000050e3b40084e5"
    "2400000a2f010debb40094e5c04080e5b40094e5001090e55c1091e5"
    "31ff2fe1"
)
VANILLA_STATE6_BODY = bytes.fromhex(
    "4400d0e51cd04de2000050e30000a0e32300000a0100a0e1240400eb"
    "0050a0e184009fe514008de50d00a0e15255fceb0510a0e10d00a0e1"
    "3153fceb14008de514208de20610a0e39d0f84e270afffeb000050e3"
    "0c00000a0d00a0e18654fceb14008de514208de20610a0e39d0f84e2"
    "67afffeb000050e30300000a0010a0e30d00a0e19750fceb14008de5"
    "14009de5c00fa0e1015080e20d00a0e10000a0e10500a0e11cd08de2"
    "3080bde8ffffe3e70d00a0e100f020e30000a0e1"
)
VANILLA_WORKER_CAVE = bytes.fromhex(
    "68019fe50cd04de2000090e5889dfdeb000050e30800000a"
    "54019fe5000090e55c5090e5000055e30300000a0500a0e176f814eb"
    "000050e34000000a00f020e3895dfceb0410a0e1df00a0e31613fdeb"
    "0410a0e1e100a0e31313fdeb14019fe50210a0e3"
)
ADDR_LIST_CAVE = 0x0014ECE4
ADDR_LIST_RESUME = 0x003E694C
ADDR_LIST_BLOB = 0x006FC500
LIST_BLOB_LEN = 0x4D2
VANILLA_LIST_CAVE = bytes.fromhex("a2e302eb0500c4e1060000e0")
_LIST_STRIDE = 306
_LIST_OPEN = "ニューオープン".encode("utf-8") + b"\x00"
_LIST_HOLY = "恋愛の聖地".encode("utf-8") + b"\x00"
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
ADDR_MAG_ST0_BUSY = 0x001057F0  # bne epilogue when scene +0x50 != 0
VANILLA_MAG_ST0_BUSY = bytes.fromhex("ab02001a")
ADDR_MAG_ST0_FLAG1 = 0x001057FC  # beq epilogue when scene +0x58 == 0
VANILLA_MAG_ST0_FLAG1 = bytes.fromhex("a802000a")
ADDR_MAG_ST0_FLAG2 = 0x00105808  # beq epilogue when scene +0x59 == 0
VANILLA_MAG_ST0_FLAG2 = bytes.fromhex("a502000a")
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
    if imm < 0:
        imm = -imm
        if imm > 0xFFF:
            raise ValueError(f"ldr pool {pool:#x} out of range from {here:#x}")
        # U=0: subtract the offset from pc.
        return _u32(0xE5100000 | (15 << 16) | (rt << 12) | imm)
    if imm > 0xFFF:
        raise ValueError(f"ldr pool {pool:#x} out of range from {here:#x}")
    return _u32(0xE5900000 | (15 << 16) | (rt << 12) | imm)


def _area_store(code: bytearray, cave: int, pool_off: int) -> None:
    """Store one pane name. The finder object is already at sp+0x10."""
    code += _u32(0xE3A030FF)  # mov r3, #0xff
    code += _ldr_pc(cave + len(code), cave + pool_off, 2)
    code += _u32(0xE28D1010)  # add r1, sp, #0x10
    code += _u32(0xE1A00004)  # mov r0, r4
    code += _u32(0xE58D6000)  # str r6, [sp]
    code += _u32(0xE58D6004)  # str r6, [sp, #4]
    code += _u32(0xE58D6008)  # str r6, [sp, #8]
    code += _u32(0xE58D600C)  # str r6, [sp, #0xc]
    code += _bl(cave + len(code), _AREA_STORE)


def build_area_cave(cave: int = ADDR_AREA_CAVE) -> bytes:
    """Bind Tex_Name and Tex_Place, then draw 「湖」 and the station.

    Entered in place of ``add r1, r5, #0x84``. r8 is the spot widget.
    Both names use the game font, so 「湖」 matches the AREA line.
    Layout lookup tries the has-data group first, then the empty group.
    A miss leaves the pane null; the drawer returns without drawing.
    The store call increments the pane index, so Tex_Name is stored at 0
    and Tex_Place lands at 1.
    """
    code = bytearray()
    code += _u32(0xE92D4070)  # push {r4, r5, r6, lr}
    code += _u32(0xE24DD018)  # sub sp, sp, #0x18
    code += _u32(0xE5980074)  # ldr r0, [r8, #0x74]  Tex_Name
    code += _u32(0xE3500000)  # cmp r0, #0
    bind_fix = len(code)
    code += b"\x00" * 4  # beq bind
    code += _u32(0xE5980078)  # ldr r0, [r8, #0x78]  Tex_Place
    code += _u32(0xE3500000)  # cmp r0, #0
    draw_fix = len(code)
    code += b"\x00" * 4  # bne draw
    bind_at = cave + len(code)
    code += _u32(0xE3A00000)  # mov r0, #0
    code += _u32(0xE5880070)  # str r0, [r8, #0x70]
    global_fixes = [len(code)]
    code += b"\x00" * 4  # ldr r0, [pc, global]
    code += _u32(0xE5900000)  # ldr r0, [r0]
    code += _u32(0xE5982008)  # ldr r2, [r8, #8]
    code += _u32(0xE3A01001)  # mov r1, #1
    code += _bl(cave + len(code), _AREA_LOOKUP)
    code += _u32(0xE3500000)  # cmp r0, #0
    have_fix = len(code)
    code += b"\x00" * 4  # bne have
    global_fixes.append(len(code))
    code += b"\x00" * 4  # ldr r0, [pc, global]
    code += _u32(0xE5900000)  # ldr r0, [r0]
    code += _u32(0xE5982008)  # ldr r2, [r8, #8]
    code += _u32(0xE3A01000)  # mov r1, #0
    code += _bl(cave + len(code), _AREA_LOOKUP)
    code += _u32(0xE3500000)  # cmp r0, #0
    miss_fix = len(code)
    code += b"\x00" * 4  # beq draw
    have_at = cave + len(code)
    code += _u32(0xE1A05000)  # mov r5, r0
    code += _u32(0xE3A06000)  # mov r6, #0
    code += _u32(0xE1A04008)  # mov r4, r8
    code += _u32(0xE28D0010)  # add r0, sp, #0x10
    code += _bl(cave + len(code), _AREA_FINDER_INIT)
    code += _u32(0xE3A03000)  # mov r3, #0
    code += _u32(0xE28D2010)  # add r2, sp, #0x10
    pos_fix = len(code)
    code += b"\x00" * 4  # ldr r1, [pc, pos]
    code += _u32(0xE1A00005)  # mov r0, r5
    code += _bl(cave + len(code), _AREA_FIND)
    # Pool layout, fixed once the code length is known. Two stores and two
    # draws refer into it. Code length is determined after these emits, so
    # the pool offsets are patched once `code` stops growing.
    name_store = len(code)
    code += b"\x00" * (9 * 4)
    place_store = len(code)
    code += b"\x00" * (9 * 4)
    draw_at = cave + len(code)
    spot_fix = len(code)
    code += b"\x00" * 4  # ldr r1, [pc, spot string]
    code += _u32(0xE1A00008)  # mov r0, r8
    code += _bl(cave + len(code), _AREA_DRAW_NAME)
    station_fix = len(code)
    code += b"\x00" * 4  # ldr r1, [pc, station string]
    code += _u32(0xE1A00008)  # mov r0, r8
    code += _bl(cave + len(code), _AREA_DRAW_PLACE)
    code += _u32(0xE28DD018)  # add sp, sp, #0x18
    code += _u32(0xE8BD8070)  # pop {r4, r5, r6, pc}
    pool = cave + len(code)
    spot_at = pool + 24
    station_at = spot_at + len(_SPOT_NAME)
    code[bind_fix : bind_fix + 4] = _b_cond(0x0, cave + bind_fix, bind_at)
    code[draw_fix : draw_fix + 4] = _b_cond(0x1, cave + draw_fix, draw_at)
    code[have_fix : have_fix + 4] = _b_cond(0x1, cave + have_fix, have_at)
    code[miss_fix : miss_fix + 4] = _b_cond(0x0, cave + miss_fix, draw_at)
    for fix in global_fixes:
        code[fix : fix + 4] = _ldr_pc(cave + fix, pool, 0)
    code[pos_fix : pos_fix + 4] = _ldr_pc(cave + pos_fix, pool + 4, 1)
    code[spot_fix : spot_fix + 4] = _ldr_pc(cave + spot_fix, pool + 16, 1)
    code[station_fix : station_fix + 4] = _ldr_pc(cave + station_fix, pool + 20, 1)
    _area_store_into(code, cave, name_store, pool + 8)
    _area_store_into(code, cave, place_store, pool + 12)
    blob = bytes(code)
    blob += _u32(_AREA_GLOBAL_VA)
    blob += _u32(_AREA_POS_VA)
    blob += _u32(_AREA_NAME_VA)
    blob += _u32(_AREA_PLACE_VA)
    blob += _u32(spot_at + 0x100000)
    blob += _u32(station_at + 0x100000)
    blob += _SPOT_NAME
    blob += _AREA_NAME
    # Stop before the gate function's pop at 0x14ECF8.
    if cave + len(blob) > 0x0014ECF8:
        raise ValueError(
            f"area cave ends @{cave + len(blob):#x}, past the gate pop"
        )
    return blob


def _area_store_into(code: bytearray, cave: int, at: int, pool_addr: int) -> None:
    chunk = bytearray()
    _area_store(chunk, cave + at, pool_addr - (cave + at))
    if len(chunk) != 9 * 4:
        raise ValueError(f"store block {len(chunk)} != 36")
    code[at : at + len(chunk)] = chunk


def apply_area_name(data: bytearray) -> None:
    cave = build_area_cave()
    data[ADDR_AREA_CAVE : ADDR_AREA_CAVE + len(cave)] = cave
    hook = _bl(ADDR_AREA_DRAW, ADDR_AREA_CAVE) + ARM_NOP + ARM_NOP
    data[ADDR_AREA_DRAW : ADDR_AREA_DRAW + 12] = hook


def build_info_menu_cave(cave: int = ADDR_MENU_LIST_CAVE) -> bytes:
    """Bind Tex_Info_01 on the right-page widget, then draw the filled names.

    Entered with r6 = the right widget (the same one the vanilla draw
    passes to index 0). r4 and r5 are restored. Group 1 is tried first,
    then group 0, matching the left-page name bind.
    """
    code = bytearray()
    code += _u32(0xE92D4030)  # push {r4, r5, lr}
    code += _u32(0xE24DD018)  # sub sp, sp, #0x18
    code += _u32(0xE1A04006)  # mov r4, r6
    code += _u32(0xE5940074)  # ldr r0, [r4, #0x74]
    code += _u32(0xE3500000)  # cmp r0, #0
    skip_fix = len(code)
    code += b"\x00" * 4  # bne draw
    code += _u32(0xE3A00000)  # mov r0, #0
    code += _u32(0xE5840070)  # str r0, [r4, #0x70]
    global_fix = len(code)
    code += b"\x00" * 4  # ldr r5, [pc, global]
    code += _u32(0xE3A0C001)  # mov ip, #1
    try_at = cave + len(code)
    code += _u32(0xE5950000)  # ldr r0, [r5]
    code += _u32(0xE5942008)  # ldr r2, [r4, #8]
    code += _u32(0xE1A0100C)  # mov r1, ip
    code += _bl(cave + len(code), _AREA_LOOKUP)
    code += _u32(0xE3500000)  # cmp r0, #0
    have_fix = len(code)
    code += b"\x00" * 4  # bne have
    code += _u32(0xE35C0000)  # cmp ip, #0
    miss_fix = len(code)
    code += b"\x00" * 4  # beq draw
    code += _u32(0xE3A0C000)  # mov ip, #0
    code += _b(cave + len(code), try_at)
    have_at = cave + len(code)
    code += _u32(0xE1A05000)  # mov r5, r0
    code += _u32(0xE28D0010)  # add r0, sp, #0x10
    code += _bl(cave + len(code), _AREA_FINDER_INIT)
    code += _u32(0xE3A03000)  # mov r3, #0
    code += _u32(0xE28D2010)  # add r2, sp, #0x10
    pos_fix = len(code)
    code += b"\x00" * 4  # ldr r1, [pc, pos]
    code += _u32(0xE1A00005)  # mov r0, r5
    code += _bl(cave + len(code), _AREA_FIND)
    code += _u32(0xE3A05000)  # mov r5, #0
    code += _u32(0xE58D5000)  # str r5, [sp]
    code += _u32(0xE58D5004)  # str r5, [sp, #4]
    code += _u32(0xE58D5008)  # str r5, [sp, #8]
    code += _u32(0xE58D500C)  # str r5, [sp, #0xc]
    code += _u32(0xE3A030FF)  # mov r3, #0xff
    tex_fix = len(code)
    code += b"\x00" * 4  # ldr r2, [pc, tex]
    code += _u32(0xE28D1010)  # add r1, sp, #0x10
    code += _u32(0xE1A00004)  # mov r0, r4
    code += _bl(cave + len(code), _AREA_STORE)
    draw_at = cave + len(code)
    str_fix = len(code)
    code += b"\x00" * 4  # ldr r1, [pc, cell]
    code += _u32(0xE5911000)  # ldr r1, [r1]  ; cell holds the string VA
    code += _u32(0xE1A00004)  # mov r0, r4
    code += _bl(cave + len(code), _INFO_DRAW)
    code += _u32(0xE28DD018)  # add sp, sp, #0x18
    code += _u32(0xE8BD8030)  # pop {r4, r5, pc}
    pool = cave + len(code)
    code[skip_fix : skip_fix + 4] = _b_cond(0x1, cave + skip_fix, draw_at)
    code[have_fix : have_fix + 4] = _b_cond(0x1, cave + have_fix, have_at)
    code[miss_fix : miss_fix + 4] = _b_cond(0x0, cave + miss_fix, draw_at)
    code[global_fix : global_fix + 4] = _ldr_pc(cave + global_fix, pool, 5)
    code[pos_fix : pos_fix + 4] = _ldr_pc(cave + pos_fix, pool + 4, 1)
    code[tex_fix : tex_fix + 4] = _ldr_pc(cave + tex_fix, pool + 8, 2)
    code[str_fix : str_fix + 4] = _ldr_pc(cave + str_fix, pool + 12, 1)
    blob = bytes(code)
    blob += _u32(_AREA_GLOBAL_VA)
    blob += _u32(_INFO_POS_VA)
    blob += _u32(_INFO_TEX_VA)
    blob += _u32(ADDR_MENU_CELL + 0x100000)
    if cave + len(blob) > ADDR_MENU_LIST_LIMIT:
        raise ValueError(
            f"info menu cave ends @{cave + len(blob):#x}, past {ADDR_MENU_LIST_LIMIT:#x}"
        )
    return blob


def menu_choice(banner: int) -> bytes:
    """The filled names, with ``> `` on ``banner``."""
    rows = []
    for index, line in MENU_FILLED:
        rows.append(("> " if index == banner else "  ") + line)
    raw = ("\n".join(rows)).encode("utf-8") + b"\x00"
    if len(raw) > MENU_STRIDE:
        raise ValueError(f"menu choice {banner} is {len(raw)} bytes")
    return raw + b"\x00" * (MENU_STRIDE - len(raw))


def build_menu_text() -> bytes:
    """One stride slot per banner index, then a 0 byte, then the sheet name.

    Slots with no sentence stay zero. The arrow never selects them.
    """
    filled = {index: menu_choice(index) for index, _line in MENU_FILLED}
    blob = bytearray()
    for i in range(MENU_SLOT_COUNT):
        blob += filled.get(i, b"\x00" * MENU_STRIDE)
    if len(blob) != MENU_SLOT_COUNT * MENU_STRIDE:
        raise ValueError("menu text stride drifted")
    blob += b"\x00"  # empty string while an article is open
    blob += _SHEET_NAME
    blob += _SHEET_PART
    return bytes(blob)


def lake_body_va() -> int:
    """VA of the Holy Site sentence, drawn into Tex_Info_01."""
    return ADDR_LAKE_BODY + 0x100000


def fever_body_va() -> int:
    """VA of the FEVER sentence, drawn into the same pane."""
    return ADDR_FEVER_BODY + 0x100000


def _article_blob() -> bytes:
    """Lake sentence, pool sentence, then the four left-page labels."""
    return _LAKE_BODY + _FEVER_BODY + _PLACE_NAMES


def _place_vas() -> tuple[int, int, int, int]:
    """Lake spot, lake station, pool spot, blank station."""
    base = ADDR_PLACE_NAMES + 0x100000
    spot = base
    area = spot + len(_SPOT_NAME)
    pool_spot = area + len(_AREA_NAME)
    pool_area = pool_spot + len(_POOL_SPOT)
    return spot, area, pool_spot, pool_area


def _ldr_pc_eq(here: int, pool: int, rt: int) -> bytes:
    word = struct.unpack("<I", _ldr_pc(here, pool, rt))[0]
    return _u32(word & 0x0FFFFFFF)


def _menu_pool_addrs(menu_cave: bytes) -> tuple[int, int, int, int]:
    """VAs the arrow and sheet caves load. Global already lives in the draw cave."""
    base = ADDR_MENU_LIST_STR + 0x100000
    empty = base + MENU_SLOT_COUNT * MENU_STRIDE
    name = empty + 1
    global_at = ADDR_MENU_LIST_CAVE + len(menu_cave) - 16
    return base, empty, name, global_at


def build_menu_arrow_cave(menu_cave: bytes) -> tuple[bytes, int]:
    """Page arrows move the marker, or close an open row.

    Called with r1 < 0 for the previous arrow and r1 >= 0 for the next.
    While a row is open, either arrow puts the list back on the marked
    row's banner and draws that row's place names. Returns with
    r2 = cell and r1 = the string the page block redraws. A opens a row
    from the button poll, not from here.
    """
    base, empty, name, _global_at = _menu_pool_addrs(menu_cave)
    cave = ADDR_MENU_ARROW
    code = bytearray()

    def at() -> int:
        return cave + len(code)

    code += _u32(0xE92D40D0)  # push {r4, r6, r7, lr}
    cell_fix = len(code)
    code += b"\x00" * 4  # ldr r4, [pc, cell]
    code += _u32(0xE5940008)  # ldr r0, [r4, #8]
    code += _u32(0xE3500000)  # cmp r0, #0
    back_fix = len(code)
    code += b"\x00" * 4  # bne restore
    # Issue 28's filled banners are 1 and 3. Either arrow swaps them.
    code += _u32(0xE5940004)  # ldr r0, [r4, #4]
    code += _u32(0xE3500001)  # cmp r0, #1
    code += _u32(0x03A00003)  # moveq r0, #3
    code += _u32(0x13A00001)  # movne r0, #1
    code += _u32(0xE5840004)  # str r0, [r4, #4]
    paint_fix = len(code)
    code += b"\x00" * 4  # b paint
    code += _u32(0xE3A00000)  # mov r0, #0
    code += _u32(0xE5840008)  # str r0, [r4, #8]
    paint_at = at()
    # Banner and place names follow the marked row, including a closed row.
    code += _u32(0xE594001C)  # ldr r0, [r4, #0x1c]
    code += _u32(0xE5941004)  # ldr r1, [r4, #4]
    code += _u32(0xE3A02000)  # mov r2, #0
    code += _bl(at(), ADDR_TITLE_BIND_FN)
    code += _u32(0xE5940020)  # ldr r0, [r4, #0x20]
    code += _u32(0xE5941004)  # ldr r1, [r4, #4]
    code += _bl(at(), ADDR_PLACE_LABELS)
    code += _u32(0xE5940004)  # ldr r0, [r4, #4]
    base_fix = len(code)
    code += b"\x00" * 4  # ldr r1, [pc, base]
    code += _u32(0xE0810380)  # add r0, r1, r0, lsl #7
    code += _u32(0xE5840000)  # str r0, [r4]
    code += _u32(0xE1A01000)  # mov r1, r0
    code += _u32(0xE1A02004)  # mov r2, r4
    code += _u32(0xE3E00000)  # mvn r0, #0
    code += _u32(0xE8BD80D0)  # pop {r4, r6, r7, pc}
    pool = at()
    code[cell_fix : cell_fix + 4] = _ldr_pc(cave + cell_fix, pool, 4)
    code[base_fix : base_fix + 4] = _ldr_pc(cave + base_fix, pool + 4, 1)
    code[back_fix : back_fix + 4] = _b_cond(0x1, cave + back_fix, cave + paint_fix + 4)
    code[paint_fix : paint_fix + 4] = _b(cave + paint_fix, paint_at)
    code += _u32(ADDR_MENU_CELL + 0x100000)
    code += _u32(base)
    code += _u32(name)
    del empty
    if cave + len(code) > ADDR_MENU_ARROW_LIMIT:
        raise ValueError(
            f"menu arrow cave ends @{cave + len(code):#x}, "
            f"past {ADDR_MENU_ARROW_LIMIT:#x}"
        )
    return bytes(code), paint_at


def build_back_choice(at: int) -> bytes:
    """もどる while an article is open returns to the list.

    Entered only when the screen widget's back byte is set. The list cell
    is the word 12 bytes before this cave. An open row redraws that list
    and skips the leave, so the page is not rebuilt as New Open. A closed
    list stores 0x10000 and continues the vanilla leave.
    """
    code = bytearray()

    def here() -> int:
        return at + len(code)

    # The cell VA is the first pool word, 12 bytes above this cave.
    code += _u32(0xE51F2014)  # ldr r2, [pc, #-0x14]
    code += _u32(0xE5922008)  # ldr r2, [r2, #8]
    code += _u32(0xE3520000)  # cmp r2, #0
    code += _u32(0x03A00801)  # moveq r0, #0x10000
    code += _b_cond(0, here(), ADDR_BACK_LEAVE_CONT)
    code += _bl(here(), ADDR_PAGE_BLOCK)
    code += _b(here(), 0x004DCCF0)
    if len(code) != 28:
        raise ValueError(f"back choice is {len(code)} bytes, the arrow tail has 28")
    return bytes(code)


def build_menu_open_cave(menu_cave: bytes) -> bytes:
    """Reset the list on a new page.

    Prep is the entry. Forty bytes later is a return, for the arrow
    path that used to hide the picture. The sentence picker is the
    next instruction: index 1 stores the lake lines, index 3 stores
    the pool lines, and every other index leaves the empty string.
    The picture panes stay size-zero in the layout. The place-label
    drawer follows the pad's pop.
    """
    _base, _empty, _name, _global_at = _menu_pool_addrs(menu_cave)
    cave = ADDR_MENU_OPEN
    code = bytearray()

    def at() -> int:
        return cave + len(code)

    # Prep. Remember the right-page widget, and set the list once.
    # Resetting every frame while the text pane was still empty put the
    # marker back on New Open after each arrow press.
    code += _u32(0xE92D4010)  # push {r4, lr}
    prep_cell = len(code)
    code += b"\x00" * 4  # ldr r4, [pc, cell]
    code += _u32(0xE584601C)  # str r6, [r4, #0x1c]
    code += _u32(0xE5940018)  # ldr r0, [r4, #0x18]
    code += _u32(0xE3500000)  # cmp r0, #0
    code += _u32(0x18BD8010)  # popne {r4, pc}
    prep_base = len(code)
    code += b"\x00" * 4  # ldr r0, [pc, base]
    # Slot 0 is empty. The cell already points at Holy Site. Remember that
    # the list was set, then put that row's banner up once.
    code += _u32(0xE5840018)  # str r0, [r4, #0x18]
    code += _bl(at(), bind_marked_addr())
    code += _u32(0xE8BD8010)  # pop {r4, pc}
    if len(code) != 10 * 4:
        raise ValueError(f"menu prep is {len(code)} bytes, sheet bl assumes 40")
    code += _u32(0xE12FFF1E)  # bx lr  arrow's old hide call returns
    # r4 = cell, r5 = index. Store the empty string, then a sentence.
    if at() != sentence_pick_addr():
        raise ValueError("sentence picker is not where the pad calls it")
    code += _u32(0xE594000C)  # ldr r0, [r4, #0xc]
    code += _u32(0xE5840000)  # str r0, [r4]
    code += _u32(0xE3550001)  # cmp r5, #1
    code += _u32(0x05940024)  # ldreq r0, [r4, #0x24]
    code += _u32(0x05840000)  # streq r0, [r4]
    code += _u32(0xE3550003)  # cmp r5, #3
    code += _u32(0x05940028)  # ldreq r0, [r4, #0x28]
    code += _u32(0x05840000)  # streq r0, [r4]
    code += _u32(0xE12FFF1E)  # bx lr
    code += _u32(0xE8BD8070)  # pop {r4, r5, r6, pc}
    if at() - 4 != sheet_frame_addr():
        raise ValueError("pad return is not the pop")
    if at() != ADDR_PLACE_LABELS:
        raise ValueError(
            f"place labels @{at():#x}, expected {ADDR_PLACE_LABELS:#x}"
        )
    code += build_place_labels()
    if at() != bind_marked_addr():
        raise ValueError(
            f"banner bind @{at():#x}, expected {bind_marked_addr():#x}"
        )
    code += build_bind_marked()
    if at() != back_finish_addr():
        raise ValueError(
            f"back finish @{at():#x}, expected {back_finish_addr():#x}"
        )
    code += build_back_finish()
    # Cover the old picture-hide cave so it cannot run.
    gap = ADDR_MENU_OPEN_LIMIT - at()
    if gap < 0:
        raise ValueError(f"menu open cave ends @{at():#x}, past {ADDR_MENU_OPEN_LIMIT:#x}")
    code += b"\x00" * gap
    pool = ADDR_MENU_ARROW  # filled in once the arrow cave's pool is known
    # The arrow builder places the pool at the end of its own bytes. Match it.
    arrow, _paint_at = build_menu_arrow_cave(menu_cave)
    pool = ADDR_MENU_ARROW + len(arrow) - 12
    code[prep_cell : prep_cell + 4] = _ldr_pc(cave + prep_cell, pool, 4)
    code[prep_base : prep_base + 4] = _ldr_pc(cave + prep_base, pool + 4, 0)
    if cave + len(code) > ADDR_MENU_OPEN_LIMIT:
        raise ValueError(
            f"menu open cave ends @{cave + len(code):#x}, "
            f"past {ADDR_MENU_OPEN_LIMIT:#x}"
        )
    return bytes(code)


def sentence_pick_addr() -> int:
    """Index 1 stores the lake sentence, index 3 stores the pool sentence."""
    return ADDR_MENU_OPEN + 11 * 4


def bind_marked_addr() -> int:
    """One-shot banner bind. Sits immediately after the place-label drawer."""
    return ADDR_PLACE_LABELS + 80


def back_finish_addr() -> int:
    """Idle check after the one-shot banner bind. 16 bytes, fills the open cave."""
    return bind_marked_addr() + 24


def build_back_finish() -> bytes:
    """Finish a もどる press, or keep polling the page arrows.

    The idle beq lands here with r0 still ``[left widget +0x24]``. A stored
    ``0x10000`` continues at the vanilla completion, which returns that code
    once both page widgets reach state 5. Any other value polls the arrows.
    """
    cave = back_finish_addr()
    code = bytearray()

    def at() -> int:
        return cave + len(code)

    code += _u32(0xE5941060)  # ldr r1, [r4, #0x60]
    code += _u32(0xE3510801)  # cmp r1, #0x10000
    code += _b_cond(0, at(), 0x004DCD3C)
    code += _b(at(), ADDR_ARROW_POLL)
    if len(code) != 16:
        raise ValueError(f"back finish is {len(code)} bytes, the open cave has 16")
    if cave + len(code) > ADDR_MENU_OPEN_LIMIT:
        raise ValueError(
            f"back finish ends @{cave + len(code):#x}, "
            f"past {ADDR_MENU_OPEN_LIMIT:#x}"
        )
    return bytes(code)


def sheet_frame_addr() -> int:
    """Where the pad branches to pop its own frame."""
    return ADDR_MENU_OPEN + 20 * 4


def build_bind_marked() -> bytes:
    """Point the right-page banner at the marked row.

    r4 is the cell and r6 is the widget. r0 and r4 are restored.
    """
    cave = bind_marked_addr()
    code = bytearray()

    def at() -> int:
        return cave + len(code)

    code += _u32(0xE92D4011)  # push {r0, r4, lr}
    code += _u32(0xE5941004)  # ldr r1, [r4, #4]
    code += _u32(0xE1A00006)  # mov r0, r6
    code += _u32(0xE3A02000)  # mov r2, #0
    code += _bl(at(), ADDR_TITLE_BIND_FN)
    code += _u32(0xE8BD8011)  # pop {r0, r4, pc}
    if cave + len(code) > ADDR_MENU_OPEN_LIMIT:
        raise ValueError(
            f"banner bind ends @{cave + len(code):#x}, "
            f"past {ADDR_MENU_OPEN_LIMIT:#x}"
        )
    return bytes(code)


def build_place_labels() -> bytes:
    """Draw the left-page spot and station for the open row.

    r0 is the left widget. r1 is the menu index. Index 3 draws 温水プール
    and a blank station. Every other index draws 「湖」 and 奥十羽野駅.
    A null widget returns without drawing.
    """
    cave = ADDR_PLACE_LABELS
    code = bytearray()

    def at() -> int:
        return cave + len(code)

    code += _u32(0xE3500000)  # cmp r0, #0
    code += _u32(0x012FFF1E)  # bxeq lr
    code += _u32(0xE92D4030)  # push {r4, r5, lr}
    code += _u32(0xE1A04000)  # mov r4, r0
    code += _u32(0xE1A05001)  # mov r5, r1
    spot_fix = len(code)
    code += b"\x00" * 4  # ldr r1, [pc, lake spot]
    code += _u32(0xE3550003)  # cmp r5, #3
    pool_spot_fix = len(code)
    code += b"\x00" * 4  # ldreq r1, [pc, pool spot]
    code += _u32(0xE1A00004)  # mov r0, r4
    code += _bl(at(), _AREA_DRAW_NAME)
    area_fix = len(code)
    code += b"\x00" * 4  # ldr r1, [pc, lake station]
    code += _u32(0xE3550003)  # cmp r5, #3
    pool_area_fix = len(code)
    code += b"\x00" * 4  # ldreq r1, [pc, blank station]
    code += _u32(0xE1A00004)  # mov r0, r4
    code += _bl(at(), _AREA_DRAW_PLACE)
    code += _u32(0xE8BD8030)  # pop {r4, r5, pc}
    pool = at()
    spot, area, pool_spot, pool_area = _place_vas()
    # Pool order matches the loads: lake spot, pool spot, lake station, blank.
    code[spot_fix : spot_fix + 4] = _ldr_pc(cave + spot_fix, pool, 1)
    code[pool_spot_fix : pool_spot_fix + 4] = _ldr_pc_eq(
        cave + pool_spot_fix, pool + 4, 1
    )
    code[area_fix : area_fix + 4] = _ldr_pc(cave + area_fix, pool + 8, 1)
    code[pool_area_fix : pool_area_fix + 4] = _ldr_pc_eq(
        cave + pool_area_fix, pool + 12, 1
    )
    code += _u32(spot)
    code += _u32(pool_spot)
    code += _u32(area)
    code += _u32(pool_area)
    if cave + len(code) > ADDR_MENU_OPEN_LIMIT:
        raise ValueError(
            f"place labels end @{cave + len(code):#x}, "
            f"past {ADDR_MENU_OPEN_LIMIT:#x}"
        )
    return bytes(code)


def build_menu_back_stub(_paint_at: int) -> bytes:
    """Try layout group 0 after group 1 missed.

    Entered with r0 = the global object, r1 = 1, r2 = the layout key,
    and r5 = the address of that global. r2 and r5 survive the lookup.
    Returns the layout in r0, or 0. The arrow cave restores the list
    itself; this pad is only the second group try.
    """
    here = ADDR_MENU_IDLE_POLL
    code = bytearray()
    code += _u32(0xE92D4000)  # push {lr}
    code += _bl(here + len(code), _AREA_LOOKUP)
    code += _u32(0xE3500000)  # cmp r0, #0
    code += _u32(0x18BD8000)  # popne {pc}
    code += _u32(0xE5950000)  # ldr r0, [r5]
    code += _u32(0xE3A01000)  # mov r1, #0
    code += _bl(here + len(code), _AREA_LOOKUP)
    code += _u32(0xE8BD8000)  # pop {pc}
    if here + len(code) > ADDR_MENU_IDLE_POLL_LIMIT:
        raise ValueError(
            f"menu group retry ends @{here + len(code):#x}, "
            f"past {ADDR_MENU_IDLE_POLL_LIMIT:#x}"
        )
    return bytes(code)


def build_menu_pad_cave() -> bytes:
    """Follow the page the arrows just turned to.

    Called every frame from the name refresh, with r4 the book, r6 the
    right-page widget, and r8 the left-page widget.     ``[book+0x68]`` is 0 on
    Holy Site and 1 on FEVER. Labels are drawn only while ``+0x5c`` is set,
    so a turn does not draw into a page that is still rebuilding. The banner
    and the sentence change only when the page does.
    """
    cave = ADDR_MENU_PAD
    code = bytearray()

    def at() -> int:
        return cave + len(code)

    code += _u32(0xE92D4070)  # push {r4, r5, r6, lr}
    # The turn clears +0x5c before the steady poll. Drawing then uses a
    # widget whose method is still null. The content refresh calls this
    # first, while +0x5c is still set.
    code += _u32(0xE5D4005C)  # ldrb r0, [r4, #0x5c]
    code += _u32(0xE3500000)  # cmp r0, #0
    code += _b(at(), sheet_frame_addr())  # placeholder, patched to beq
    ready_fix = len(code) - 4
    code += _u32(0xE5945068)  # ldr r5, [r4, #0x68]
    cell_fix = len(code)
    code += b"\x00" * 4  # ldr r4, [pc, cell]
    code += _u32(0xE5848020)  # str r8, [r4, #0x20]
    code += _u32(0xE3550000)  # cmp r5, #0
    code += _u32(0x03A05001)  # moveq r5, #1
    code += _u32(0x13A05003)  # movne r5, #3
    code += _u32(0xE5940020)  # ldr r0, [r4, #0x20]
    code += _u32(0xE1A01005)  # mov r1, r5
    code += _bl(at(), ADDR_PLACE_LABELS)
    code += _u32(0xE5940004)  # ldr r0, [r4, #4]
    code += _u32(0xE1500005)  # cmp r0, r5
    code += _b(at(), sheet_frame_addr())  # placeholder; patched to beq below
    same_fix = len(code) - 4
    code += _u32(0xE5845004)  # str r5, [r4, #4]
    code += _u32(0xE1A00006)  # mov r0, r6
    code += _u32(0xE1A01005)  # mov r1, r5
    code += _u32(0xE3A02000)  # mov r2, #0
    code += _bl(at(), ADDR_TITLE_BIND_FN)
    code += _bl(at(), sentence_pick_addr())
    code += _u32(0xE5941000)  # ldr r1, [r4]
    code += _u32(0xE1A00006)  # mov r0, r6
    code += _bl(at(), _INFO_DRAW)
    code += _b(at(), sheet_frame_addr())
    pool = 104
    if len(code) > pool:
        raise ValueError(f"menu pad body is {len(code)} bytes, literal is at {pool}")
    code += b"\x00" * (pool - len(code))
    code[cell_fix : cell_fix + 4] = _ldr_pc(cave + cell_fix, cave + pool, 4)
    code[same_fix : same_fix + 4] = _b_cond(0, cave + same_fix, sheet_frame_addr())
    code[ready_fix : ready_fix + 4] = _b_cond(0, cave + ready_fix, sheet_frame_addr())
    code += _u32(ADDR_MENU_CELL + 0x100000)
    if len(code) != MENU_PAD_LEN:
        raise ValueError(
            f"menu pad cave is {len(code)} bytes, move cave assumes {MENU_PAD_LEN}"
        )
    return bytes(code)


def menu_move_addr() -> int:
    return ADDR_MENU_PAD + len(build_menu_pad_cave())


def menu_poll_addr() -> int:
    """Steady-frame trampoline: poll A, then do the load it replaced."""
    return menu_move_addr() + 32


def build_menu_move_cave(cave: int | None = None) -> bytes:
    """Return the HID shared-memory pad word. Bit 0 set means A is down.

    Both hid:USER and hid:SPVR init the object at 0x009A13F8 (tail calls
    into 0x600c). Its +4 is the mapped 0x2B0 block. The current pad is at
    shared+0x1C. A missing map returns 0 instead of reading a null pointer.
    """
    if cave is None:
        cave = menu_move_addr()
    code = bytearray()
    pool_fix = len(code)
    code += b"\x00" * 4  # ldr r0, [pc, object]
    code += _u32(0xE5900004)  # ldr r0, [r0, #4]
    code += _u32(0xE3500000)  # cmp r0, #0
    code += _u32(0x03A00000)  # moveq r0, #0
    code += _u32(0x012FFF1E)  # bxeq lr
    code += _u32(0xE590001C)  # ldr r0, [r0, #0x1C]
    code += _u32(0xE12FFF1E)  # bx lr
    pool = cave + len(code)
    code[pool_fix : pool_fix + 4] = _ldr_pc(cave + pool_fix, pool, 0)
    code += _u32(0x009A13F8)
    if len(code) != 32:
        raise ValueError(f"HID reader is {len(code)} bytes, poll trampoline assumes 32")
    # Runs from the steady book path. Does the A poll, then the load it replaced.
    code += _u32(0xE92D4000)  # push {lr}
    code += _bl(cave + len(code), ADDR_MENU_PAD)
    code += _u32(0xE5D40088)  # ldrb r0, [r4, #0x88]
    code += _u32(0xE8BD8000)  # pop {pc}
    move_len = ADDR_MENU_PAD_LIMIT - ADDR_MENU_PAD - MENU_PAD_LEN
    if len(code) > move_len:
        raise ValueError(f"menu move cave is {len(code)} bytes, slot is {move_len}")
    code += b"\x00" * (move_len - len(code))
    if len(code) != move_len:
        raise ValueError(f"menu move cave is {len(code)} bytes, slot is {move_len}")
    if cave + len(code) > ADDR_MENU_PAD_LIMIT:
        raise ValueError(
            f"menu move cave ends @{cave + len(code):#x}, "
            f"past {ADDR_MENU_PAD_LIMIT:#x}"
        )
    return bytes(code)


def menu_control_blob() -> bytes:
    pad = build_menu_pad_cave()
    move = build_menu_move_cave(ADDR_MENU_PAD + len(pad))
    blob = pad + move
    if len(blob) != ADDR_MENU_PAD_LIMIT - ADDR_MENU_PAD:
        raise ValueError(f"menu controls are {len(blob)} bytes, slot is 156")
    return blob


def build_page_block() -> bytes:
    """Move the marker, redraw it on the saved right-page widget, return -1.

    r1 is already -1 for the previous arrow and +1 for the next. The move
    leaves the cell pointer in r2. Prep stored the widget at cell+0x1c.
    The following cmn/beq only consumes the press.
    """
    here = ADDR_PAGE_BLOCK
    code = bytearray()
    code += _u32(0xE92D4000)  # push {lr}
    code += _bl(here + len(code), ADDR_MENU_ARROW)
    code += _u32(0xE592001C)  # ldr r0, [r2, #0x1c]  widget saved by prep
    code += _bl(here + len(code), _INFO_DRAW)
    code += _u32(0xE3E00000)  # mvn r0, #0
    code += _u32(0xE8BD8000)  # pop {pc}
    if here + len(code) > ADDR_PAGE_BLOCK_LIMIT:
        raise ValueError(
            f"page block ends @{here + len(code):#x}, "
            f"past {ADDR_PAGE_BLOCK_LIMIT:#x}"
        )
    return bytes(code)


def apply_info_menu(data: bytearray) -> None:
    cave = build_info_menu_cave()
    data[ADDR_MENU_LIST_CAVE : ADDR_MENU_LIST_CAVE + len(cave)] = cave
    text = build_menu_text()
    data[ADDR_MENU_LIST_STR : ADDR_MENU_LIST_STR + len(text)] = text
    sentences = _article_blob()
    if len(sentences) > _SENTENCE_ROOM:
        raise ValueError(f"sentences are {len(sentences)} bytes, room is {_SENTENCE_ROOM}")
    there = bytes(data[ADDR_LAKE_BODY : ADDR_LAKE_BODY + len(sentences)])
    articles = _LAKE_BODY + _FEVER_BODY
    previous = (
        b"\x00" * len(sentences),
        sentences,
        articles + b"\x00" * len(_PLACE_NAMES),
        _LAKE_BODY + b"\x00" * (len(sentences) - len(_LAKE_BODY)),
    )
    if there not in previous:
        raise ValueError(f"article sentences @{ADDR_LAKE_BODY:#x} are not empty")
    data[ADDR_LAKE_BODY : ADDR_LAKE_BODY + len(sentences)] = sentences
    arrow, paint_at = build_menu_arrow_cave(cave)
    data[ADDR_MENU_ARROW : ADDR_MENU_ARROW + len(arrow)] = arrow
    choice_at = ADDR_MENU_ARROW + len(arrow)
    choice = build_back_choice(choice_at)
    if choice_at + len(choice) != ADDR_MENU_ARROW_LIMIT:
        raise ValueError(
            f"back choice ends @{choice_at + len(choice):#x}, "
            f"limit is {ADDR_MENU_ARROW_LIMIT:#x}"
        )
    data[choice_at : choice_at + len(choice)] = choice
    data[ADDR_BACK_SET : ADDR_BACK_SET + 4] = _b_cond(1, ADDR_BACK_SET, choice_at)
    data[ADDR_BACK_LEAVE : ADDR_BACK_LEAVE + 4] = _b(ADDR_BACK_LEAVE, ADDR_ARROW_LATCH)
    opened = build_menu_open_cave(cave)
    data[ADDR_MENU_OPEN : ADDR_MENU_OPEN + len(opened)] = opened
    data[ADDR_ARROW_SKIP : ADDR_ARROW_SKIP + 4] = VANILLA_ARROW_SKIP
    pad = build_menu_pad_cave()
    blob = menu_control_blob()
    pad_at = data[ADDR_MENU_PAD : ADDR_MENU_PAD + len(blob)]
    if pad_at != b"\x00" * len(blob) and pad_at != blob and pad_at[:4] != _u32(0xE92D4070):
        raise ValueError(
            f"menu pad @{ADDR_MENU_PAD:#x} is live code, not romaji padding"
        )
    data[ADDR_MENU_PAD : ADDR_MENU_PAD + len(blob)] = blob
    hook = (
        _bl(ADDR_INFO_DRAW, ADDR_MENU_OPEN)
        + _bl(ADDR_INFO_DRAW + 4, ADDR_MENU_PAD)
        + _bl(ADDR_INFO_DRAW + 8, ADDR_MENU_LIST_CAVE)
    )
    data[ADDR_INFO_DRAW : ADDR_INFO_DRAW + 12] = hook
    poll = _bl(ADDR_MENU_POLL, menu_poll_addr())
    there = bytes(data[ADDR_MENU_POLL : ADDR_MENU_POLL + 4])
    if there not in (VANILLA_MENU_POLL, poll, b"\x00\x00\x00\x00"):
        raise ValueError(f"menu poll @{ADDR_MENU_POLL:#x} is not the widget load")
    data[ADDR_MENU_POLL : ADDR_MENU_POLL + 4] = poll
    data[ADDR_TITLE_BIND_FIXED : ADDR_TITLE_BIND_FIXED + 4] = PATCHED_TITLE_BIND_SKIP
    data[ADDR_TITLE_BIND_INDEX : ADDR_TITLE_BIND_INDEX + 4] = PATCHED_TITLE_BIND_SKIP
    cell = ADDR_MENU_CELL
    if len(data) >= cell + 44:
        base = ADDR_MENU_LIST_STR + 0x100000
        first = MENU_FILLED[0][0]
        data[cell : cell + 4] = _u32(lake_body_va())
        data[cell + 4 : cell + 8] = _u32(first)
        data[cell + 8 : cell + 12] = _u32(0)
        data[cell + 12 : cell + 16] = _u32(base + MENU_SLOT_COUNT * MENU_STRIDE)
        data[cell + 16 : cell + 20] = _u32(0xFFFFFFFF)
        data[cell + 20 : cell + 24] = _u32(base)
        data[cell + 24 : cell + 28] = _u32(0)  # init once
        data[cell + 28 : cell + 32] = _u32(0)  # right-page widget
        data[cell + 32 : cell + 36] = _u32(0)  # left-page widget
        data[cell + 36 : cell + 40] = _u32(lake_body_va())
        data[cell + 40 : cell + 44] = _u32(fever_body_va())
    back = build_menu_back_stub(paint_at)
    if len(data) >= ADDR_MENU_IDLE_POLL + len(back):
        data[ADDR_MENU_IDLE_POLL : ADDR_MENU_IDLE_POLL + len(back)] = back
    data[ADDR_ARROW_IDLE : ADDR_ARROW_IDLE + 4] = _b_cond(
        0, ADDR_ARROW_IDLE, back_finish_addr()
    )
    data[ADDR_PAGE_MASK_WALK : ADDR_PAGE_MASK_WALK + 4] = PATCHED_PAGE_MASK
    data[ADDR_PAGE_MASK_LOOKUP : ADDR_PAGE_MASK_LOOKUP + 4] = PATCHED_PAGE_MASK_LOOKUP
    data[ADDR_ARROW_POLL_TAIL : ADDR_ARROW_POLL_TAIL + 4] = VANILLA_ARROW_POLL_TAIL
    # The front and back arrows turn the real page, so the number moves.
    data[ADDR_ARROW_STEP : ADDR_ARROW_STEP + 4] = VANILLA_ARROW_STEP
    data[ADDR_ARROW_STEP + 4 : ADDR_ARROW_STEP + 8] = VANILLA_ARROW_CMN
    for addr in ADDR_ARROW_SHOW:
        data[addr : addr + 4] = PATCHED_ARROW_SHOW
    block = build_page_block()
    gap = data[ADDR_PAGE_BLOCK : ADDR_PAGE_BLOCK + len(block)]
    hole_tail = data[ADDR_PAGE_BLOCK_LIMIT : ADDR_PAGE_BLOCK_LIMIT + 2]
    if gap != block and hole_tail != b"\x00\x00":
        raise ValueError(f"page block @{ADDR_PAGE_BLOCK:#x} is not empty")
    data[ADDR_PAGE_BLOCK : ADDR_PAGE_BLOCK + len(block)] = block
    for addr in (ADDR_TWIN_STEP, ADDR_THIRD_STEP):
        data[addr : addr + 4] = _bl(addr, ADDR_PAGE_STEP)


def build_list_blob() -> bytes:
    """Two contents rows the in-room parser already understands.

    Record stride is 306. The type byte is at +8 and sets one flag bit
    (type 1 → bit 0, type 2 → bit 1). The title is the C string at +12.
    A trailer halfword of -1 at +0x4D0 skips the extra block and opens
    the book. The page mask stays bit 1, so the open spread is still
    the holy-site page.
    """
    blob = bytearray(LIST_BLOB_LEN)
    blob[0] = 1
    blob[4:8] = _u32(2)
    blob[8] = 1
    blob[12 : 12 + len(_LIST_OPEN)] = _LIST_OPEN
    holy = _LIST_STRIDE
    blob[holy + 8] = 2
    blob[holy + 12 : holy + 12 + len(_LIST_HOLY)] = _LIST_HOLY
    blob[0x4D0:0x4D2] = struct.pack("<h", -1)
    return bytes(blob)


def build_list_cave(cave: int = ADDR_LIST_CAVE) -> bytes:
    """Replace r7 with the contents blob and continue the record fill."""
    code = bytearray()
    code += _ldr_pc(cave, cave + 8, 7)  # ldr r7, [pc, #0]
    code += _b(cave + len(code), ADDR_LIST_RESUME)
    code += _u32(ADDR_LIST_BLOB + 0x100000)
    if len(code) != len(VANILLA_LIST_CAVE):
        raise ValueError(f"list cave {len(code)} != {len(VANILLA_LIST_CAVE)}")
    if cave + len(code) > 0x0014ECF4:
        raise ValueError(f"list cave ends @{cave + len(code):#x}")
    return bytes(code)


def list_beq() -> bytes:
    return _b_cond(0, ADDR_EMPTY_LIST_BEQ, ADDR_LIST_CAVE)


def apply_list_menu(data: bytearray) -> None:
    blob = build_list_blob()
    cave = build_list_cave()
    data[ADDR_LIST_BLOB : ADDR_LIST_BLOB + len(blob)] = blob
    data[ADDR_LIST_CAVE : ADDR_LIST_CAVE + len(cave)] = cave
    data[ADDR_EMPTY_LIST_BEQ : ADDR_EMPTY_LIST_BEQ + 4] = list_beq()


def build_menu_cave(cave: int = ADDR_MENU_CAVE) -> bytes:
    """Construct the magazine list and start in MagList."""
    code = bytearray()
    code += _bl(cave + len(code), ADDR_MENU_CTOR)
    code += _u32(0xE3A0100C)  # mov r1, #0xc
    code += _u32(0xE5C0105E)  # strb r1, [r0, #0x5e]
    code += _b(cave + len(code), ADDR_BOOK_CTOR_RESUME)
    if len(code) != len(VANILLA_MENU_CAVE):
        raise ValueError(f"menu cave {len(code)} != {len(VANILLA_MENU_CAVE)}")
    if cave + len(code) > 0x0014EBC4:
        raise ValueError(f"menu cave ends @{cave + len(code):#x}")
    return bytes(code)


def build_worker_cave(cave: int = ADDR_WORKER_CAVE) -> bytes:
    """Allocate the worker, build the operator, then attach child id 0x37."""
    code = bytearray()
    code += _bl(cave + len(code), ADDR_WORKER_FACTORY)
    pool_global = 88
    pool_method = 92
    pool_ui = 96
    code += _ldr_pc(cave + len(code), cave + pool_global, 3)
    code += _u32(0xE5830000)  # str r0, [r3]
    code += _u32(0xE2801E92)  # add r1, r0, #0x920
    code += _u32(0xE5801910)  # str r1, [r0, #0x910]
    code += _ldr_pc(cave + len(code), cave + pool_method, 2)
    code += _u32(0xE581200C)  # str r2, [r1, #0xc]
    code += _bl(cave + len(code), ADDR_MENU_CTOR)
    code += _u32(0xE1A05000)  # mov r5, r0
    code += _ldr_pc(cave + len(code), cave + pool_ui, 0)
    code += _u32(0xE3A01002)  # mov r1, #2
    code += _u32(0xE5900000)  # ldr r0, [r0]
    code += _bl(cave + len(code), ADDR_UI_LOOKUP)
    skip = 80
    code += _u32(0xE3500000)  # cmp r0, #0
    code += _b_cond(0, cave + len(code), cave + skip)
    code += _u32(0xE3A01037)  # mov r1, #0x37
    code += _bl(cave + len(code), ADDR_UI_CHILD)
    code += _u32(0xE5850060)  # str r0, [r5, #0x60]
    code += _u32(0xE3500000)  # cmp r0, #0
    code += _u32(0x15805078)  # strne r5, [r0, #0x78]
    if len(code) != skip:
        raise ValueError(f"worker cave skip {len(code)} != {skip}")
    code += _u32(0xE1A00005)  # mov r0, r5
    code += _b(cave + len(code), ADDR_BOOK_CTOR_RESUME)
    if len(code) != pool_global:
        raise ValueError(f"worker cave code {len(code)} != {pool_global}")
    code += _u32(ADDR_WORKER_GLOBAL)
    code += _u32(ADDR_SESSION_RET)
    code += _u32(ADDR_UI_ROOT)
    if cave + len(code) > ADDR_CHILD_CAVE:
        raise ValueError(f"worker cave ends @{cave + len(code):#x}")
    return bytes(code)


def build_child_cave(cave: int = ADDR_CHILD_CAVE) -> bytes:
    """After the tutorial, signal state 11 to open the cart list.

    The draw already stored the real worker at ``*0x008BFAEC``. Setting
    ``+0xdc`` and one date byte makes state 11 enter MagList. The enter
    patch starts that list at inner state 6, which polls rows and does
    not open the StreetPass dialog.
    """
    code = bytearray()
    code += _u32(0xE3A01001)  # mov r1, #1
    code += _u32(0xE5C410DC)  # strb r1, [r4, #0xdc]
    code += _u32(0xE5C41066)  # strb r1, [r4, #0x66]
    code += _u32(0xE12FFF1E)  # bx lr
    while len(code) < 88:
        code += ARM_NOP
    if len(code) != 88:
        raise ValueError(f"child cave {len(code)} != 88")
    if cave + len(code) > ADDR_STATE6_LIMIT:
        raise ValueError(f"child cave ends @{cave + len(code):#x}")
    return bytes(code)


def apply_worker_host(data: bytearray) -> None:
    data[ADDR_DRAW_BODY : ADDR_DRAW_BODY + len(VANILLA_WORKER_CAVE)] = VANILLA_WORKER_CAVE
    data[ADDR_DRAW_CHILD : ADDR_DRAW_CHILD + len(VANILLA_CHILD_CAVE)] = VANILLA_CHILD_CAVE
    data[ADDR_MENU_DRAW : ADDR_MENU_DRAW + len(VANILLA_MENU_DRAW)] = VANILLA_MENU_DRAW
    cave = build_worker_cave()
    data[ADDR_WORKER_CAVE : ADDR_WORKER_CAVE + len(cave)] = cave
    child = build_child_cave()
    data[ADDR_CHILD_CAVE : ADDR_CHILD_CAVE + len(child)] = child
    data[ADDR_CHILD_CALL : ADDR_CHILD_CALL + 4] = _bl(ADDR_CHILD_CALL, ADDR_CHILD_CAVE)
    data[ADDR_BOOK_CTOR : ADDR_BOOK_CTOR + 4] = _b(ADDR_BOOK_CTOR, ADDR_WORKER_CAVE)
    for addr in (ADDR_MAG_ST0_BUSY, ADDR_MAG_ST0_FLAG1, ADDR_MAG_ST0_FLAG2):
        data[addr : addr + 4] = ARM_NOP
    data[ADDR_MAGLIST_ENTER_INNER : ADDR_MAGLIST_ENTER_INNER + 8] = (
        PATCHED_MAGLIST_ENTER_INNER
    )
    data[ADDR_MAGLIST_ST6_STAY : ADDR_MAGLIST_ST6_STAY + 4] = (
        PATCHED_MAGLIST_ST6_STAY
    )


def apply_menu_select(data: bytearray) -> None:
    cave = build_menu_cave()
    data[ADDR_MENU_CAVE : ADDR_MENU_CAVE + len(cave)] = cave
    data[ADDR_BOOK_CTOR : ADDR_BOOK_CTOR + 4] = _b(ADDR_BOOK_CTOR, ADDR_MENU_CAVE)
    data[ADDR_MENU_DRAW : ADDR_MENU_DRAW + len(PATCHED_MENU_DRAW)] = PATCHED_MENU_DRAW


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
        and data[ADDR_MAGLIST_FATAL_BL : ADDR_MAGLIST_FATAL_BL + 4]
        == VANILLA_MAGLIST_FATAL_BL
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
            data[addr : addr + 4]
            == patched
            for addr, _vanilla, patched in MAGLIST_WORD_SITES
        )
        and all(
            data[addr : addr + 4] == vanilla
            for addr, vanilla in WATCHER_RESTORE_SITES
        )
        and data[ADDR_HOME_OPEN_BL : ADDR_HOME_OPEN_BL + 4] == VANILLA_HOME_OPEN_BL
        and data[ADDR_WEB_NOTIFY : ADDR_WEB_NOTIFY + 4] == VANILLA_WEB_NOTIFY
        and data[ADDR_BOOK_OPEN_NEXT : ADDR_BOOK_OPEN_NEXT + 4]
        == VANILLA_BOOK_OPEN_NEXT
        and data[ADDR_BOOK_CTOR : ADDR_BOOK_CTOR + 4] == VANILLA_BOOK_CTOR
        and data[ADDR_MENU_CAVE : ADDR_MENU_CAVE + len(VANILLA_MENU_CAVE)]
        == VANILLA_MENU_CAVE
        and data[ADDR_MENU_DRAW : ADDR_MENU_DRAW + len(VANILLA_MENU_DRAW)]
        == VANILLA_MENU_DRAW
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
    data[ADDR_MAGLIST_FATAL_BL : ADDR_MAGLIST_FATAL_BL + 4] = (
        VANILLA_MAGLIST_FATAL_BL
    )
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
    apply_info_menu(data)
    # Do not open WebUI here. It stays blank unless LoveplusModeHome
    # is its parent, and that parent's show slot crashes on the room.
    # Do not hold the book in state 2. That frame is not drawn.
    data[ADDR_BOOK_OPEN_NEXT : ADDR_BOOK_OPEN_NEXT + 4] = VANILLA_BOOK_OPEN_NEXT
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
    data[ADDR_MAGLIST_FATAL_BL : ADDR_MAGLIST_FATAL_BL + 4] = VANILLA_MAGLIST_FATAL_BL
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
    data[ADDR_INFO_DRAW : ADDR_INFO_DRAW + len(VANILLA_INFO_DRAW)] = VANILLA_INFO_DRAW
    data[ADDR_MENU_POLL : ADDR_MENU_POLL + 4] = VANILLA_MENU_POLL
    blob = menu_control_blob()
    if data[ADDR_MENU_PAD : ADDR_MENU_PAD + len(blob)] == blob:
        data[ADDR_MENU_PAD : ADDR_MENU_PAD + len(blob)] = b"\x00" * len(blob)
    block = build_page_block()
    if data[ADDR_PAGE_BLOCK : ADDR_PAGE_BLOCK + len(block)] == block:
        data[ADDR_PAGE_BLOCK : ADDR_PAGE_BLOCK + len(block)] = b"\x00" * len(block)
    for addr in (ADDR_TWIN_STEP, ADDR_THIRD_STEP):
        if data[addr : addr + 4] == _bl(addr, ADDR_PAGE_BLOCK):
            data[addr : addr + 4] = _bl(addr, ADDR_PAGE_STEP)
    data[ADDR_TITLE_BIND_FIXED : ADDR_TITLE_BIND_FIXED + 4] = VANILLA_TITLE_BIND_FIXED
    data[ADDR_TITLE_BIND_INDEX : ADDR_TITLE_BIND_INDEX + 4] = VANILLA_TITLE_BIND_INDEX
    data[ADDR_MENU_LIST_STR : ADDR_MENU_LIST_STR + len(build_menu_text())] = b"\x00" * len(
        build_menu_text()
    )
    data[ADDR_LAKE_BODY : ADDR_LAKE_BODY + len(_article_blob())] = b"\x00" * len(
        _article_blob()
    )
    data[ADDR_ARROW_SKIP : ADDR_ARROW_SKIP + 4] = VANILLA_ARROW_SKIP
    data[ADDR_ARROW_IDLE : ADDR_ARROW_IDLE + 4] = VANILLA_ARROW_IDLE
    data[ADDR_ARROW_POLL_TAIL : ADDR_ARROW_POLL_TAIL + 4] = VANILLA_ARROW_POLL_TAIL
    data[ADDR_ARROW_STEP : ADDR_ARROW_STEP + 4] = VANILLA_ARROW_STEP
    data[ADDR_ARROW_STEP + 4 : ADDR_ARROW_STEP + 8] = VANILLA_ARROW_CMN
    _arrow, paint_at = build_menu_arrow_cave(build_info_menu_cave())
    back = build_menu_back_stub(paint_at)
    if len(data) >= ADDR_MENU_IDLE_POLL + len(back):
        data[ADDR_MENU_IDLE_POLL : ADDR_MENU_IDLE_POLL + len(back)] = b"\x00" * len(
            back
        )
    for addr in ADDR_ARROW_SHOW:
        data[addr : addr + 4] = VANILLA_ARROW_HIDE
    data[ADDR_MENU_ARROW : ADDR_MENU_ARROW + len(VANILLA_MENU_ARROW_BODY)] = (
        VANILLA_MENU_ARROW_BODY
    )
    data[ADDR_BACK_SET : ADDR_BACK_SET + 4] = VANILLA_BACK_SET
    data[ADDR_BACK_LEAVE : ADDR_BACK_LEAVE + 4] = VANILLA_BACK_LEAVE
    data[ADDR_MENU_OPEN : ADDR_MENU_OPEN + len(VANILLA_MENU_OPEN_BODY)] = (
        VANILLA_MENU_OPEN_BODY
    )
    data[0x006094B8 : 0x006094BC] = ARM_NOP
    data[ADDR_LIST_CAVE : ADDR_LIST_CAVE + len(VANILLA_LIST_CAVE)] = VANILLA_LIST_CAVE
    data[ADDR_LIST_BLOB : ADDR_LIST_BLOB + LIST_BLOB_LEN] = b"\x00" * LIST_BLOB_LEN
    data[ADDR_MENU_CAVE : ADDR_MENU_CAVE + len(VANILLA_MENU_CAVE)] = VANILLA_MENU_CAVE
    data[ADDR_DRAW_BODY : ADDR_DRAW_BODY + len(VANILLA_WORKER_CAVE)] = (
        VANILLA_WORKER_CAVE
    )
    data[ADDR_DRAW_CHILD : ADDR_DRAW_CHILD + len(VANILLA_CHILD_CAVE)] = (
        VANILLA_CHILD_CAVE
    )
    data[ADDR_WORKER_CAVE : ADDR_WORKER_CAVE + len(VANILLA_STATE6_BODY)] = (
        VANILLA_STATE6_BODY
    )
    data[ADDR_CHILD_CALL : ADDR_CHILD_CALL + 4] = VANILLA_CHILD_CALL
    data[ADDR_MAGLIST_ENTER_INNER : ADDR_MAGLIST_ENTER_INNER + 8] = (
        VANILLA_MAGLIST_ENTER_INNER
    )
    data[ADDR_MAGLIST_ST6_STAY : ADDR_MAGLIST_ST6_STAY + 4] = (
        VANILLA_MAGLIST_ST6_STAY
    )
    data[ADDR_HOME_OPEN_BL : ADDR_HOME_OPEN_BL + 4] = VANILLA_HOME_OPEN_BL
    data[ADDR_WEB_NOTIFY : ADDR_WEB_NOTIFY + 4] = VANILLA_WEB_NOTIFY
    data[ADDR_BOOK_OPEN_NEXT : ADDR_BOOK_OPEN_NEXT + 4] = VANILLA_BOOK_OPEN_NEXT
    data[ADDR_BOOK_CTOR : ADDR_BOOK_CTOR + 4] = VANILLA_BOOK_CTOR
    data[ADDR_MENU_DRAW : ADDR_MENU_DRAW + len(VANILLA_MENU_DRAW)] = VANILLA_MENU_DRAW
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
