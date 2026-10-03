"""Stop the title-screen model chunk walk before an unmapped load.

Preexisting-save boot (Luma 2026-09-28 19:19, 21:35, and 2026-09-29 15:14)
data-aborts in vanilla file ``0x15664`` (runtime ``0x11566C``, ``ldrne r0, [r0]``). The pair's node
pointer is ``chunk + 8 + size``, and that size word is the fourcc ``PUPU``
(``0x55505550``), so the next address is ``0x6Axxxxxx`` (translation fault,
section, read). The caller then calls file ``0x15684``, which would load the
same pointer. Both helpers return 0 for a null node; 0 ends the walk
(``cmp r0, #0`` / ``bne`` back to the tag load).

A pointer outside ``[0x08000000, 0x20000000)``, or a size that would put the
next node outside that range, is treated as the end of the walk. The mesh
can stop early. This is not the CESA malloc smash and not a name-input cave.

The same ``PUPU`` offset is added to a loaded blob at file ``0x297EC``
(runtime ``0x1297EC``: ``add r0, r0, r1`` then ``ldr r2, [r0]``). That sum is ``0x6Axxxxxx`` and
aborts once the walker itself has been guarded. A pointer outside the heap
range clears the offset and skips the reloc loop.

Title-background reloc (file ``0x542E28``, runtime ``0x642E28``: ``ldr r3, [r2, #8]``)
does ``r2 = object + [object+0x10]`` and then dereferences it. With a save
loaded that sum is ``0x2Axxxxxx`` (still a translation fault). The caller's
``cmp r0, #0`` / ``beq`` pops the function, so returning 0 skips the node.
The cave lives in the advance helper's NOP tail (the entry branches away).

The next consumer (file ``0x542D48``, runtime ``0x642D48``) indexes that stored
pointer (``ldr r1, [r1, r2, lsl #2]``). After the reloc returns 0 the base
is null and the load faults at FAR 0. A base outside the heap range takes
the function's existing ``mov r0, #0`` return. That cave sits in the NOP
tail of ``ClearNameCharPanes`` (the name-pane stub branches away), so the
name-pane patch has to be applied first.

The next boot (Luma 2026-10-01 01:18, before the title screen) data-aborts
in ``FSUSER_OpenFileDirectly`` while ``Lyt_C_Com_Win01.bclyt`` is on the
stack in its ``txl1`` texture list. File ``0x2381C`` (runtime ``0x12381C``)
is ``ldr r0, [r0]`` then ``svc #0x32``. ``r0`` is the pointer to the
``fs:USER`` handle and it is 0, so the load faults at FAR 0 (translation,
section, read). Every code.bin caller passes ``sp+imm``, which cannot be
null; the caller this time is heap code.

Skipping the load and returning handle 0 makes the stub pop its saved LR.
On that boot the saved LR is the ``mat1`` fourcc inside the loaded layout
(Luma 2026-10-01 02:25, prefetch abort, permission fault, PC ``0x15B76308``).
A ``.text`` BL cannot leave that address in LR. The texture-bind frame is
still on the stack: ``0x6EB844`` saved ``0x006E9C74``, and the object is the
saved ``r4``. A null handle whose saved return is outside ``.text`` restores
that frame and branches to the bind failure path (file ``0x5E9CE8``), which
frees the object and returns 0. A saved return inside ``.text`` still falls
through to ``svc`` so the real callers see the error.

The next boot (Luma 2026-10-01 02:57) gets past that open and data-aborts
in the texture release at file ``0x5E96DC`` (runtime ``0x6E96DC``,
``ldr r5, [r0, #8]``, FAR 8). The caller at file ``0x5C60D0`` passed the
word at ``[r6, #0xb2c]``, which is 0, then ignored the return. ``r7`` is
already 0, so a null object or a null inner list branches to the
function's own ``mov r0, r7; pop`` and the loop continues.

The next boot (Luma 2026-10-01 03:16, title music already playing) is
the same open, for ``Lyt_Title_bg02``. The handle pointer was valid and
the word at it was 0, so the null-pointer check loaded handle 0, the
kernel returned ``0xD8E007F7``, and the stub popped a saved LR of 0
(prefetch abort, PC 0). The return-address check now runs after a
successful load too. A saved return outside ``.text`` still takes the
bind failure path instead of ``svc``.

The next boot (Luma 2026-10-01 17:50) data-aborts in the pane-field
getter at file ``0x191888`` (runtime ``0x291888``, ``ldreq r0, [r0, #0x60]``,
FAR ``0x60``). The caller passed index 0 and a null object (``r7`` from
the lookup just above). The getter's own exit is ``bx lr`` once a field
is null, so a null object takes that exit before any of the three loads.

The next boot (Luma 2026-10-01 17:58) is the twin getter at file
``0x1920B8``. The same caller passes ``r5`` from the second lookup,
which is also 0. Only these two copies exist.

The next boot (Luma 2026-10-01 18:04, title music already up) is
``OpenFileDirectly`` again, opening ``Lyt_Title_bg02.bclyt``. The saved
return is 0 and the texture-bind frame is not above it, so the old scan
fell through to ``svc`` and the stub popped address 0. The layout
constructor's return (``0x00376C80``) is on that stack. Resuming its
failure epilogue returns 0 to the caller that already checks for a
null layout.

The next boot (Luma 2026-10-01 18:36) data-aborts in the resource-name
walk at file ``0x544D78`` (runtime ``0x644D78``, ``ldrh r0, [r4]``,
FAR ``0x160912F8``). The caller is resolving the fourcc ``blyt`` inside
``Lyt_C_Com_Win01.bclyt``. ``r4`` is the string base plus the low 24
bits of the directory entry (``0x1594A9A4 + 0x746954``). That page is
not mapped. An offset of 1 MiB or more takes the walker's own
not-found epilogue (``mvn r0, #0``), which the caller already checks.

The next boot (Luma 2026-10-01 19:58) data-aborts at file ``0x1EEDA8``
(runtime ``0x2EEDA8``, ``ldr r0, [r0]``, FAR 0). The caller passed the
first lookup result in ``r6``, which is 0, into a virtual call through
``[object+0x94]``. The caller's next instruction replaces ``r0``, so a
null object pops the frame and returns.

The title screen then data-aborts at file ``0x544338`` (runtime
``0x644338``, ``ldr r1, [r2, r1]``). ``r1`` is already the table address
and ``r2`` is a file delta. A delta of 0 still loads the table, which
draws the logo and the scrolling background. A delta of 16 MiB or more
(the ``IDX `` tag ``0x20584449``, and ``0x0110E113``) skips to this
function's epilogue.
The next read in that function, file ``0x544348`` (``ldrb r0, [sl, #0x14]``),
faults when the loaded offset makes ``sl`` itself unmapped (FAR
``0x56AF97E3``, ``sl`` ``0x56AF97CF``). ``sl`` at or above ``0x20000000``
takes the same epilogue.

Leaving the save-file screen data-aborts at file ``0xDE4C`` (runtime
``0x10DE4C``, ``ldr r2, [r0, #4]``, FAR ``0x55505554``). ``r0`` is the
free-list node and it is the fourcc ``PUPU`` (``0x55505550``). The
allocator's own end (``cmp r7, #0`` at file ``0xDE7C``) returns null when
no block was chosen, and the save-screen caller already checks that.
A node at or above ``0x20000000`` takes that end instead of reading
``[node+4]``.

The same allocator then writes through the chosen block's backward
link at file ``0xDEE0`` (``str r0, [r2, #8]``, FAR ``0x55505558``).
``r2`` is again ``PUPU``. That link is left alone, and the block is
still returned. A free-list next of ``PUPU`` becomes the heap's end
sentinel, and a previous node of ``PUPU`` makes the remainder the
heap head, so the next image buffer can still be allocated.

The next boot data-aborts in the PACK init at file ``0xD3B0``
(runtime ``0x10D3B0``, ``stm r5, {r1, r6}``, FAR 0). ``r5`` is
``[global+0xc]`` and it is 0; ``r1`` is the ``PAK `` fourcc. A null
table skips those header stores and the init keeps going. Returning
from the pop there leaves the object empty and the boot stays black.
The allocation that follows returns 0 when heap 0 has no block, and
file ``0xD3E4`` (``strb r1, [r0]``) then writes through that null.
A null allocation pops the frame with ``r0`` still 0. A real
allocation is stored at ``[table, #4]`` only when the table exists.

The next instruction in that boot is file ``0x151E4`` (runtime
``0x1151E4``, ``ldrb r0, [r4, #0x13]``, FAR ``0x6F3``). ``r4`` is
``[global+0xc] + index * 20``, and the global word is 0, so the
address is ``0x6E0``. The caller's ``cmp r0, #0`` takes the failure
path, and this function already returns 0 from file ``0x15278``.
A null base takes that pop. The check is Thumb in the padding after
the message-speed sample (the sample rewrite clears those bytes, so
the hook is written again after that rewrite).

Returning 0 there is what the caller at file ``0xD9B4`` treats as
"create the entry". That path calls file ``0x14F00``, which loads
the same null base and faults at file ``0x14F40`` (``ldrb r1, [r7,
#0x13]``, FAR ``0x6F3``). ``tst r1, #8`` already skips the body, so a
null base sets ``r1`` to 8 and returns to that test. The 16 bytes are
the fillcand null tail plus the pad after it; the tail moves to the
8 zero bytes before the commu-header cave.

The caves sit in the dead tail of ``FUN_002573ac`` (strcat-raw branches away
at the first instruction) so they stay in ``.text`` RX. Apply strcat-raw first.
The OpenFileDirectly guard uses the NOP tail of ``SetNameCharsToPanes``
(the name-pane rewrite returns before that tail). The pane-field guard
uses the NOP tail of ``BackspaceNameCharPane``. Apply name panes first.
"""
from __future__ import annotations

import struct

from patch_input_cave_map import ADDR_CHUNK_WALK_CAVE, ADDR_CHUNK_WALK_LIMIT
from patch_input_romaji import (
    add_imm,
    add_reg,
    b_cond,
    b_ins,
    bl,
    blx_imm,
    cmp_imm,
    cmp_reg,
    ldr_imm,
    mov_imm,
    mov_imm_cond,
    mov_reg,
    orr_reg,
    str_imm,
    sub_imm,
    sub_reg,
)
from patch_code import (
    ADDR_BACKSPACE,
    ADDR_CLEAR,
    ADDR_SET,
    SIZE_BACKSPACE,
    SIZE_CLEAR,
    SIZE_SET,
    assemble_backspace,
    assemble_set_name,
    nop,
)
from patch_input_strcat_raw import ADDR as STRCAT_ADDR
from patch_input_strcat_raw import NOP, is_patched as strcat_patched

# File offsets. Runtime VA = file + 0x100000.
ADDR_DEREF = 0x00015664  # ldr r0,[r0,#4]; cmp r0,#0; ldrne r0,[r0]; bx lr
ADDR_ADVANCE = 0x00015684  # walk node+8+size back into the pair
DEREF_LEN = 0x10
ADVANCE_LEN = 0x30  # stops before copy8 at file 0x156B4
# Blob reloc: r0 = object + [object+8], then ldr from that pointer.
ADDR_FIXUP = 0x000297EC
ADDR_FIXUP_SKIP = 0x0002984C
VANILLA_FIXUP = bytes.fromhex("010080e0")  # add r0, r0, r1
# Title bg: r2 = object + [object+0x10], then ldr r3, [r2, #8].
ADDR_TITLE_RELOC = 0x00542E28
ADDR_TITLE_RELOC_RESUME = 0x00542E2C
VANILLA_TITLE_RELOC = bytes.fromhex("083092e5")  # ldr r3, [r2, #8]
# Advance helper is a branch plus NOP. The cave sits in that NOP tail.
ADDR_TITLE_RELOC_CAVE = ADDR_ADVANCE + 4
ADDR_TITLE_RELOC_LIMIT = ADDR_ADVANCE + ADVANCE_LEN
# Index of the relocated pointer. Null / off-heap takes the mov r0,#0 return.
ADDR_TITLE_INDEX = 0x00542D48
ADDR_TITLE_INDEX_RESUME = 0x00542D4C
ADDR_TITLE_INDEX_FAIL = 0x00542D5C
VANILLA_TITLE_INDEX = bytes.fromhex("021191e7")  # ldr r1, [r1, r2, lsl #2]
# ClearNameCharPanes stub is 12 bytes, then NOP through SIZE_CLEAR.
ADDR_TITLE_INDEX_CAVE = ADDR_CLEAR + 12
ADDR_TITLE_INDEX_LIMIT = ADDR_CLEAR + SIZE_CLEAR
NAME_PANE_STUB = bytes.fromhex("04109fe5")  # ldr r1, [pc, #4]
# CLYT header check. A null blob (the reloc skip) faults on ldr r12, [r0].
ADDR_CLYT = 0x00541CE4
ADDR_CLYT_RESUME = 0x00541CE8
VANILLA_CLYT = bytes.fromhex("00c090e5")  # ldr r12, [r0]
POP_R4 = bytes.fromhex("04409de4")  # ldr r4, [sp], #4
# Same null blob, next use: ldrh r1, [r6, #6] in the caller. FAR is 6.
ADDR_LYT_HDR = 0x00548AC8
ADDR_LYT_HDR_RESUME = 0x00548ACC
ADDR_LYT_HDR_FAIL = 0x00548CF8  # add sp, #0x24; mov r0, #1; pop
VANILLA_LYT_HDR = bytes.fromhex("b610d6e1")  # ldrh r1, [r6, #6]
# Virtual call through a null object: ldr r2, [r0] at file 0x277FB4.
ADDR_VT = 0x00277FB4
ADDR_VT_RESUME = 0x00277FB8
ADDR_VT_FAIL = 0x00277FC4  # bx lr
VANILLA_VT = bytes.fromhex("002090e5")  # ldr r2, [r0]
# Title reloc entry. The source object itself is now 0x6Axxxxxx.
ADDR_TITLE_OBJ = 0x00542E0C
ADDR_TITLE_OBJ_RESUME = 0x00542E10
VANILLA_TITLE_OBJ = bytes.fromhex("000081e5")  # str r0, [r1]
# FSUSER_OpenFileDirectly: ldr r0, [r0]; svc #0x32. r0 is &fs:USER handle.
ADDR_FS_OPEN = 0x0002381C
ADDR_FS_OPEN_RESUME = 0x00023820
VANILLA_FS_OPEN = bytes.fromhex("000090e5")  # ldr r0, [r0]
# .text RX. A saved return outside this range is not a code.bin caller.
TEXT_LO = 0x00100000
TEXT_HI = 0x00790000
# bl at file 0x5E9C70 returns here. The word on the stack is the runtime VA.
ADDR_TEX_BIND_RET = 0x006E9C74
ADDR_TEX_BIND_FAIL = 0x005E9CE8  # destroy the object, then return 0
# Layout constructor return, runtime VA. Its fail epilogue returns 0.
ADDR_LYT_CTOR_RET = 0x00376C80
ADDR_LYT_CTOR_FAIL = 0x00276CEC
FS_SCAN = 0x80
# Resource-name walk: ldrh r0, [r4] after base + (entry & 0x00ffffff).
ADDR_NAME = 0x00544D78
ADDR_NAME_RESUME = 0x00544D7C
ADDR_NAME_FAIL = 0x00544E00  # add sp, #0xc; mvn r0, #0; pop
VANILLA_NAME = bytes.fromhex("b000d4e1")  # ldrh r0, [r4]
# A real name sits next to the directory. 0x746954 is past the file.
NAME_OFF_MAX = 0x00100000
# Virtual call: push {r4,lr}; mov r4, r0; ldr r0, [r0]; ldr r1, [r0, #0x94].
ADDR_MENU_VT = 0x001EEDA8
ADDR_MENU_VT_RESUME = 0x001EEDAC
VANILLA_MENU_VT = bytes.fromhex("000090e5")  # ldr r0, [r0]
# Title draw: ldr r1, [r2, r1]. r1 is already a heap address; r2 is a
# file delta. 0 keeps the logo and the scrolling background. The IDX tag
# and the 0x0110E113 delta are past this.
ADDR_IDX_LOAD = 0x00544338
ADDR_IDX_LOAD_RESUME = 0x0054433C
ADDR_IDX_LOAD_FAIL = 0x005445C8  # add sp; vpop; pop
VANILLA_IDX_LOAD = bytes.fromhex("011092e7")  # ldr r1, [r2, r1]
IDX_DELTA_MAX = 0x01000000
ADDR_IDX_LOAD_CAVE = 0x00190100
ADDR_IDX_LOAD_LIMIT = 0x00190110
# Following byte load: ldrb r0, [sl, #0x14]. sl is the offset applied to the table.
ADDR_NODE_BYTE = 0x00544348
ADDR_NODE_BYTE_RESUME = 0x0054434C
VANILLA_NODE_BYTE = bytes.fromhex("1400dae5")  # ldrb r0, [sl, #0x14]
ADDR_NODE_BYTE_CAVE = 0x00190350
ADDR_NODE_BYTE_LIMIT = 0x00190360
# Free-list best fit: ldr r2, [r0, #4]. r0 is the node. PUPU is not one.
# Luma 2026-10-03 00:50: file 0x2C6070 ``ldrb r0, [r6, #0x5f]`` with r6 == 0
# (FAR 0x5F). r6 is the first pane lookup in the title menu update. The
# ``beq`` at 0x2C5FCC is the only way in, so it goes through a null check
# and the epilogue at 0x2C6040 instead.
ADDR_PANE_FLAG_BR = 0x002C5FCC
ADDR_PANE_FLAG_LOAD = 0x002C6070
ADDR_PANE_FLAG_FAIL = 0x002C6040  # pop {r3-r8, sb, pc}
VANILLA_PANE_FLAG_BR = bytes.fromhex("2700000a")  # beq 0x2C6070
# Zero padding the heap link pad uses when APPLY_HEAP_AND_PAK is on.
ADDR_PANE_FLAG_CAVE = 0x005AEC0C
ADDR_PANE_FLAG_CAVE_LEN = 12

ADDR_HEAP_WALK = 0x0000DE4C
ADDR_HEAP_WALK_RESUME = 0x0000DE50
ADDR_HEAP_WALK_FAIL = 0x0000DE7C  # cmp r7, #0; return null if none
VANILLA_HEAP_WALK = bytes.fromhex("042090e5")  # ldr r2, [r0, #4]
# Three dead words after the deref hook. The next helper starts at +0x10.
ADDR_HEAP_WALK_CAVE = ADDR_DEREF + 4
ADDR_HEAP_WALK_CAVE_LEN = 12
# Neighbor link: str r0, [r2, #8] after ldr r2, [r7, #0xc]. PUPU is r2.
ADDR_HEAP_LINK = 0x0000DED4
ADDR_HEAP_LINK_BODY = 0x0000DED8
ADDR_HEAP_LINK_END = 0x0000DEEC
VANILLA_HEAP_LINK = bytes.fromhex("0c2097e5")  # ldr r2, [r7, #0xc]
# Twelve zero bytes after bx lr, before a float literal at +0xc.
ADDR_HEAP_LINK_PAD = 0x005AEC0C
ADDR_HEAP_LINK_PAD_LEN = 12
# str r0, [r2, #0x10] / str r0, [r2, #0x14] for the other two links.
ADDR_HEAP_BIN = 0x0000DEEC
ADDR_HEAP_BIN_END = 0x0000DF14
# Size fixup was at 0xDF0C. It slides down so the bin check can reject null.
ADDR_HEAP_TAIL = 0x0000DF14
ADDR_HEAP_FAIL = 0x0000DF2C
ADDR_HEAP_FAIL_OLD = 0x0000DF24
ADDR_HEAP_TAIL_END = 0x0000DF40
ADDR_HEAP_SUCCESS = 0x0000DF50
ADDR_HEAP_UNLOCK = 0x0001FD88
ADDR_HEAP_EMPTY = 0x0000DE48
ADDR_HEAP_NOFIT = 0x0000DE80
VANILLA_HEAP_BIN = bytes.fromhex("142097e5")  # ldr r2, [r7, #0x14]
# Row clear: str r0, [r1] with r1 = 0x3E0. The empty span already jumps here.
ADDR_ROW_CLEAR = 0x00029020
ADDR_ROW_STORE = 0x00029024
ADDR_ROW_RESUME = 0x00029028
ADDR_ROW_SKIP = 0x0002903C
VANILLA_ROW_CLEAR = bytes.fromhex("0500008a")  # bhi skip
ROW_PTR_MIN = 0x00001000
# Dead bytes after a pop, and alignment zeros before the strcat cave.
ADDR_ROW_GATE = 0x000D4C90
ADDR_ROW_CHECK = 0x0068FDA8
# memset: stm r0! after malloc returned 0. Caller checks the pointer on return.
ADDR_MEMSET = 0x001FDDD8
ADDR_MEMSET_BODY = 0x001FDDDC
VANILLA_MEMSET = bytes.fromhex("0020a0e3")  # mov r2, #0
ADDR_MEMSET_CAVE = 0x0064790C
ADDR_MEMSET_STUB = 0x0021D5B4
# PACK init. r5 = [global+0xc]; stm through a null r5 is the boot abort.
ADDR_PAK_INIT = 0x0000D3A4
ADDR_PAK_INIT_END = 0x0000D3C4
ADDR_PAK_POP = 0x0000D634
VANILLA_PAK_INIT = bytes.fromhex(
    "0620a0e10c5090e50200a0e3420085e8"
    "086085e5b071c5e11260c5e51300c5e5"
)
# Soft-failing PACK when the table/alloc is null blacks the boot (the caller
# keeps going with an empty archive). The heap walk/link splice can also
# starve that alloc. Leave both vanilla until the free-list fix is proven
# not to empty the heap at CESA/PACK setup. Instance B (no heap/PACK soft
# fail) still draws; A with those soft fails stayed black with no abort.
APPLY_HEAP_AND_PAK = False
# Same null [global+0xc], indexed. ldrb r0, [r4, #0x13].
ADDR_PAK_TABLE = 0x000151E4
ADDR_PAK_TABLE_FAIL = 0x00015278  # mov r0, #0; pop {r4, r5, r6, pc}
ADDR_PAK_TABLE_CAVE = 0x005D1934  # after "Speed test." in the sample pool
ADDR_PAK_TABLE_CAVE_LEN = 12
VANILLA_PAK_TABLE = bytes.fromhex("1300d4e5")
# Create-path sibling of the table load. ldrb r1, [r7, #0x13].
ADDR_PAK_FLAG = 0x00014F40
ADDR_PAK_FLAG_CAVE = 0x0068F850  # fillcand cave1 null tail + the 8-byte pad
ADDR_PAK_FLAG_CAVE_LEN = 16
ADDR_FILLCAND_TAIL = 0x0068FFCC  # 8 zeros before the commu-header cave
VANILLA_PAK_FLAG = bytes.fromhex("1310d7e5")  # ldrb r1, [r7, #0x13]
_PAK_TABLE_JP = "メッセージ速度テストです。".encode("utf-8") + b"\x00"
VANILLA_PAK_TABLE_CAVE = _PAK_TABLE_JP[-ADDR_PAK_TABLE_CAVE_LEN:]
# Texture release: ldr r5, [r0, #8]. Caller ignores r0. r7 is already 0.
ADDR_TEX_REL = 0x005E96DC
ADDR_TEX_REL_RESUME = 0x005E96E0
ADDR_TEX_REL_FAIL = 0x005E9758  # mov r0, r7; pop {r4-r8, pc}
VANILLA_TEX_REL = bytes.fromhex("085090e5")  # ldr r5, [r0, #8]
# Pane field getter. Index 0/1/2 loads [r0+0x60/64/68]. Null object bx-lrs.
ADDR_FIELD = 0x00191884
ADDR_FIELD_RESUME = 0x00191888
ADDR_FIELD_FAIL = 0x001918C4  # bx lr
ADDR_FIELD_B = 0x001920B8
ADDR_FIELD_B_RESUME = 0x001920BC
ADDR_FIELD_B_FAIL = 0x001920F8  # bx lr
VANILLA_FIELD = bytes.fromhex("000051e3")  # cmp r1, #0

HEAP_LO = 0x08000000
HEAP_HI = 0x20000000
HEAP_SPAN = HEAP_HI - HEAP_LO
# PUPU is 0x55505550. A real node this walker steps is far smaller, and a
# size this large wraps the next pointer back into a mapped page.
MAX_SIZE = 0x01000000

VANILLA_DEREF = bytes.fromhex("040090e5000050e3000090151eff2fe1")
VANILLA_ADVANCE = bytes.fromhex(
    "041090e5000051e300209115000052130000a0030400000a"
    "0420b1e5041081e2021081e0041080e50100a0e31eff2fe1"
)


def _u32(x: int) -> bytes:
    return struct.pack("<I", x & 0xFFFFFFFF)


def bx_lr(cond: int = 0xE) -> bytes:
    return _u32((cond << 28) | 0x012FFF1E)


def build_cave(base: int = ADDR_CHUNK_WALK_CAVE) -> tuple[bytes, dict[str, int]]:
    """Guarded deref, then guarded advance, sharing the fail return."""
    stream: list = []

    def OP(b: bytes) -> None:
        stream.append(("op", b))

    def L(name: str) -> None:
        stream.append(("lab", name))

    def B(name: str, cond: int | None = None) -> None:
        stream.append(("b", name, cond))

    # r0 = pair. Return the tag word, or 0 when the node is not a heap pointer.
    L("deref")
    OP(ldr_imm(0, 0, 4))
    OP(cmp_imm(0, 0))
    OP(bx_lr(0))  # eq: null node, r0 already 0
    OP(cmp_imm(0, HEAP_LO))
    B("fail", 3)  # lo
    OP(cmp_imm(0, HEAP_HI))
    B("fail", 2)  # hs
    OP(ldr_imm(0, 0, 0))
    OP(bx_lr())

    # r0 = pair. Return 1 and store next, or 0 and leave the pair alone.
    L("advance")
    OP(ldr_imm(1, 0, 4))
    OP(cmp_imm(1, 0))
    B("fail", 0)
    OP(cmp_imm(1, HEAP_LO))
    B("fail", 3)
    OP(cmp_imm(1, HEAP_HI))
    B("fail", 2)
    OP(ldr_imm(2, 1, 0))
    OP(cmp_imm(2, 0))
    B("fail", 0)
    OP(ldr_imm(2, 1, 4))
    OP(cmp_imm(2, MAX_SIZE))
    B("fail", 2)
    OP(add_reg(2, 1, 2))
    OP(add_imm(2, 2, 8))
    OP(cmp_imm(2, HEAP_LO))
    B("fail", 3)
    OP(cmp_imm(2, HEAP_HI))
    B("fail", 2)
    OP(str_imm(2, 0, 4))
    OP(mov_imm(0, 1))
    OP(bx_lr())

    L("fail")
    OP(mov_imm(0, 0))
    OP(bx_lr())

    labs: dict[str, int] = {}
    addr = base
    for item in stream:
        if item[0] == "lab":
            labs[item[1]] = addr
        else:
            addr += 4
    out = bytearray()
    addr = base
    for item in stream:
        if item[0] == "lab":
            continue
        if item[0] == "op":
            out += item[1]
        elif item[0] == "b":
            name, cond = item[1], item[2]
            out += b_ins(addr, labs[name]) if cond is None else b_cond(cond, addr, labs[name])
        else:
            raise ValueError(item)
        addr += 4
    blob = bytes(out)
    if base + len(blob) > ADDR_CHUNK_WALK_LIMIT:
        raise ValueError(
            f"chunk-walk cave {len(blob):#x} exceeds tail "
            f"{ADDR_CHUNK_WALK_LIMIT - base:#x}"
        )
    return blob, labs


def cave_blob(base: int = ADDR_CHUNK_WALK_CAVE) -> bytes:
    return build_cave(base)[0]


def fixup_cave_addr() -> int:
    return ADDR_CHUNK_WALK_CAVE + len(cave_blob())


def build_fixup_cave(base: int | None = None) -> bytes:
    """add r0, r0, r1, then skip the reloc loop when the sum is off the heap.

    The good path returns with ``bxlo lr`` so the caller's next instruction
    (``ldrh r1, [r4, #6]``) still runs. The bad path stores 0 to ``[r4, #8]``
    and branches to the loop's existing skip.
    """
    if base is None:
        base = fixup_cave_addr()
    body = bytearray()
    body += add_reg(0, 0, 1)
    body += cmp_imm(0, HEAP_LO)
    blo_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_imm(0, HEAP_HI)
    body += bx_lr(3)  # lo: HEAP_LO <= r0 < HEAP_HI
    bad = base + len(body)
    body += mov_imm(0, 0)
    body += str_imm(0, 4, 8)
    body += b_ins(base + len(body), ADDR_FIXUP_SKIP)
    body[blo_at : blo_at + 4] = b_cond(3, base + blo_at, bad)
    blob = bytes(body)
    if base + len(blob) > ADDR_CHUNK_WALK_LIMIT:
        raise ValueError(
            f"fixup cave {base:#x}+{len(blob):#x} exceeds {ADDR_CHUNK_WALK_LIMIT:#x}"
        )
    return blob


def build_title_reloc_cave(base: int = ADDR_TITLE_RELOC_CAVE) -> bytes:
    """Skip ``ldr r3, [r2, #8]`` when ``r2`` is off the heap.

    Entered by ``b``, so ``lr`` is still the title function's caller. A bad
    pointer clears the absolute just stored at ``[r1, #4]`` and returns 0.
    """
    body = bytearray()
    body += cmp_imm(2, HEAP_LO)
    blo_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_imm(2, HEAP_HI)
    bhs_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += ldr_imm(3, 2, 8)
    body += b_ins(base + len(body), ADDR_TITLE_RELOC_RESUME)
    fail = base + len(body)
    body += mov_imm(3, 0)
    body += str_imm(3, 1, 4)
    body += mov_imm(0, 0)
    body += bx_lr()
    body[blo_at : blo_at + 4] = b_cond(3, base + blo_at, fail)
    body[bhs_at : bhs_at + 4] = b_cond(2, base + bhs_at, fail)
    blob = bytes(body)
    if base + len(blob) > ADDR_TITLE_RELOC_LIMIT:
        raise ValueError(
            f"title reloc cave {base:#x}+{len(blob):#x} exceeds "
            f"{ADDR_TITLE_RELOC_LIMIT:#x}"
        )
    return blob


def build_title_index_cave(base: int = ADDR_TITLE_INDEX_CAVE) -> bytes:
    """Skip the scaled index load when ``r1`` is not a heap pointer.

    The fail branch is the function's own ``mov r0, #0; pop``.
    """
    body = bytearray()
    body += cmp_imm(1, HEAP_LO)
    blo_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_imm(1, HEAP_HI)
    bhs_at = len(body)
    body += b"\x00\x00\x00\x00"
    # add r3, r1, r2, lsl #2 — the address the ldr would use.
    body += _u32(0xE0813102)
    body += cmp_imm(3, HEAP_HI)
    bhs2_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += VANILLA_TITLE_INDEX
    body += b_ins(base + len(body), ADDR_TITLE_INDEX_RESUME)
    fail = base + len(body)
    body += b_ins(base + len(body), ADDR_TITLE_INDEX_FAIL)
    body[blo_at : blo_at + 4] = b_cond(3, base + blo_at, fail)
    body[bhs_at : bhs_at + 4] = b_cond(2, base + bhs_at, fail)
    body[bhs2_at : bhs2_at + 4] = b_cond(2, base + bhs2_at, fail)
    blob = bytes(body)
    if base + len(blob) > ADDR_TITLE_INDEX_LIMIT:
        raise ValueError(
            f"title index cave {base:#x}+{len(blob):#x} exceeds "
            f"{ADDR_TITLE_INDEX_LIMIT:#x}"
        )
    return blob


def clyt_cave_addr() -> int:
    return ADDR_TITLE_INDEX_CAVE + len(build_title_index_cave())


def build_clyt_cave(base: int | None = None) -> bytes:
    """Return without reading when the CLYT blob pointer is off the heap.

    The entry already pushed r4, so the fail path pops it. The caller
    overwrites r0 immediately, so the return value is unused.
    """
    if base is None:
        base = clyt_cave_addr()
    body = bytearray()
    body += cmp_imm(0, HEAP_LO)
    blo_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_imm(0, HEAP_HI)
    bhs_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += ldr_imm(12, 0, 0)
    body += b_ins(base + len(body), ADDR_CLYT_RESUME)
    fail = base + len(body)
    body += POP_R4
    body += bx_lr()
    body[blo_at : blo_at + 4] = b_cond(3, base + blo_at, fail)
    body[bhs_at : bhs_at + 4] = b_cond(2, base + bhs_at, fail)
    blob = bytes(body)
    if base < ADDR_TITLE_INDEX_CAVE + len(build_title_index_cave()):
        raise ValueError(f"clyt cave {base:#x} overlaps the title index cave")
    if base + len(blob) > ADDR_TITLE_INDEX_LIMIT:
        raise ValueError(
            f"clyt cave {base:#x}+{len(blob):#x} exceeds {ADDR_TITLE_INDEX_LIMIT:#x}"
        )
    return blob


def lyt_hdr_cave_addr() -> int:
    return clyt_cave_addr() + len(build_clyt_cave())


def build_lyt_hdr_cave(base: int | None = None) -> bytes:
    """Skip the layout halfword load when ``r6`` is off the heap.

    Fail jumps to this function's epilogue. Its caller ignores r0.
    """
    if base is None:
        base = lyt_hdr_cave_addr()
    body = bytearray()
    body += cmp_imm(6, HEAP_LO)
    blo_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_imm(6, HEAP_HI)
    bhs_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += VANILLA_LYT_HDR
    body += b_ins(base + len(body), ADDR_LYT_HDR_RESUME)
    fail = base + len(body)
    body += b_ins(base + len(body), ADDR_LYT_HDR_FAIL)
    body[blo_at : blo_at + 4] = b_cond(3, base + blo_at, fail)
    body[bhs_at : bhs_at + 4] = b_cond(2, base + bhs_at, fail)
    blob = bytes(body)
    if base < clyt_cave_addr() + len(build_clyt_cave()):
        raise ValueError(f"layout header cave {base:#x} overlaps the clyt cave")
    if base + len(blob) > ADDR_TITLE_INDEX_LIMIT:
        raise ValueError(
            f"layout header cave {base:#x}+{len(blob):#x} exceeds "
            f"{ADDR_TITLE_INDEX_LIMIT:#x}"
        )
    return blob


def vt_cave_addr() -> int:
    return lyt_hdr_cave_addr() + len(build_lyt_hdr_cave())


def build_vt_cave(base: int | None = None) -> bytes:
    """Skip ``ldr r2, [r0]; ldr r3, [r2, #0x2c]; bx r3`` when ``r0`` is off-heap."""
    if base is None:
        base = vt_cave_addr()
    body = bytearray()
    body += cmp_imm(0, HEAP_LO)
    blo_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_imm(0, HEAP_HI)
    bhs_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += VANILLA_VT
    body += b_ins(base + len(body), ADDR_VT_RESUME)
    fail = base + len(body)
    body += b_ins(base + len(body), ADDR_VT_FAIL)
    body[blo_at : blo_at + 4] = b_cond(3, base + blo_at, fail)
    body[bhs_at : bhs_at + 4] = b_cond(2, base + bhs_at, fail)
    blob = bytes(body)
    if base < lyt_hdr_cave_addr() + len(build_lyt_hdr_cave()):
        raise ValueError(f"vt cave {base:#x} overlaps the layout header cave")
    if base + len(blob) > ADDR_TITLE_INDEX_LIMIT:
        raise ValueError(
            f"vt cave {base:#x}+{len(blob):#x} exceeds {ADDR_TITLE_INDEX_LIMIT:#x}"
        )
    return blob


def title_obj_cave_addr() -> int:
    return vt_cave_addr() + len(build_vt_cave())


def build_title_obj_cave(base: int | None = None) -> bytes:
    """Return 0 when the title reloc's source object is off the heap.

    The caller does ``cmp r0, #0`` / ``beq`` and pops. Nothing has been
    pushed in this function, so ``bx lr`` is the return.
    """
    if base is None:
        base = title_obj_cave_addr()
    body = bytearray()
    body += cmp_imm(0, HEAP_LO)
    blo_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_imm(0, HEAP_HI)
    bhs_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += VANILLA_TITLE_OBJ
    body += b_ins(base + len(body), ADDR_TITLE_OBJ_RESUME)
    fail = base + len(body)
    body += mov_imm(0, 0)
    body += bx_lr()
    body[blo_at : blo_at + 4] = b_cond(3, base + blo_at, fail)
    body[bhs_at : bhs_at + 4] = b_cond(2, base + bhs_at, fail)
    blob = bytes(body)
    if base < vt_cave_addr() + len(build_vt_cave()):
        raise ValueError(f"title object cave {base:#x} overlaps the vt cave")
    if base + len(blob) > ADDR_TITLE_INDEX_LIMIT:
        raise ValueError(
            f"title object cave {base:#x}+{len(blob):#x} exceeds "
            f"{ADDR_TITLE_INDEX_LIMIT:#x}"
        )
    return blob


def fs_open_cave_addr() -> int:
    """First NOP in the rewritten SetNameCharsToPanes tail."""
    blob = assemble_set_name()
    pad = nop()
    for i in range(0, len(blob), 4):
        if blob[i : i + 4] == pad:
            return ADDR_SET + i
    raise ValueError("SetNameCharsToPanes has no NOP tail")


def build_fs_open_cave(base: int | None = None) -> bytes:
    """Skip ``ldr r0, [r0]`` when the fs:USER handle pointer is null.

    A saved return inside ``.text`` goes back to ``svc #0x32``. Handle 0
    is the kernel's invalid-handle result; real callers already branch on
    it. A saved return outside ``.text`` is the layout file (``mat1``, or
    0). That check runs even when the pointer was valid and the handle
    word was 0. The texture-bind frame is still above this one; finding
    its return address restores that frame and takes the bind failure path.
    If that frame is absent, the follow-up cave looks for the layout
    constructor and takes that function's failure epilogue.
    """
    if base is None:
        base = fs_open_cave_addr()
    body = bytearray()

    def at(mark: int | None = None) -> int:
        return base + (len(body) if mark is None else mark)

    body += cmp_imm(0, 0)
    body += _u32(0x15900000)  # ldrne r0, [r0]
    body += ldr_imm(1, 13, 0x34)  # saved LR
    body += cmp_imm(1, TEXT_LO)
    blo_scan = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_imm(1, TEXT_HI)
    body += bx_lr(3)  # lo: still inside .text; r0 is the handle, or 0
    scan = at()
    body[blo_scan : blo_scan + 4] = b_cond(3, at(blo_scan), scan)

    body += add_imm(2, 13, 0x38)
    body += add_imm(3, 2, FS_SCAN)
    ldr_lit = len(body)
    body += b"\x00\x00\x00\x00"  # ldr r12, [pc, #lit]
    loop = at()
    body += _u32(0xE4921004)  # ldr r1, [r2], #4
    body += cmp_reg(1, 12)
    beq_found = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_reg(2, 3)
    blo_loop = len(body)
    body += b"\x00\x00\x00\x00"
    body += b_ins(at(), fs_open_miss_addr())
    found = at()
    body[beq_found : beq_found + 4] = b_cond(0, at(beq_found), found)
    body[blo_loop : blo_loop + 4] = b_cond(3, at(blo_loop), loop)
    body += _u32(0xE5124010)  # ldr r4, [r2, #-0x10]
    body += add_imm(13, 2, 0)  # sp = frame after the bind push
    body += b_ins(at(), ADDR_TEX_BIND_FAIL)
    lit = at()
    body[ldr_lit : ldr_lit + 4] = ldr_imm(12, 15, lit - at(ldr_lit) - 8)
    body += _u32(ADDR_TEX_BIND_RET)

    blob = bytes(body)
    tail = ADDR_SET + SIZE_SET
    if base < ADDR_SET or base + len(blob) > tail:
        raise ValueError(
            f"fs open cave {base:#x}+{len(blob):#x} is outside the "
            f"SetNameCharsToPanes tail ending {tail:#x}"
        )
    return blob


def tex_release_cave_addr() -> int:
    return fs_open_cave_addr() + len(build_fs_open_cave())


def build_tex_release_cave(base: int | None = None) -> bytes:
    """Skip the texture release when the list object or its inner pointer is null.

    The function has already stored 0 in ``r7``. The fail branch is its
    epilogue, which returns that 0. The caller does not use the result.
    """
    if base is None:
        base = tex_release_cave_addr()
    body = bytearray()

    def at(mark: int | None = None) -> int:
        return base + (len(body) if mark is None else mark)

    body += cmp_imm(0, 0)
    beq_obj = len(body)
    body += b"\x00\x00\x00\x00"
    body += VANILLA_TEX_REL
    body += cmp_imm(5, 0)
    beq_inner = len(body)
    body += b"\x00\x00\x00\x00"
    body += b_ins(at(), ADDR_TEX_REL_RESUME)
    body[beq_obj : beq_obj + 4] = b_cond(0, at(beq_obj), ADDR_TEX_REL_FAIL)
    body[beq_inner : beq_inner + 4] = b_cond(0, at(beq_inner), ADDR_TEX_REL_FAIL)
    blob = bytes(body)
    tail = ADDR_SET + SIZE_SET
    if base < fs_open_cave_addr() + len(build_fs_open_cave()):
        raise ValueError(f"texture release cave {base:#x} overlaps the fs open cave")
    if base + len(blob) > tail:
        raise ValueError(
            f"texture release cave {base:#x}+{len(blob):#x} exceeds {tail:#x}"
        )
    return blob


def field_cave_addr() -> int:
    """First NOP in the rewritten BackspaceNameCharPane tail."""
    blob = assemble_backspace()
    pad = nop()
    for i in range(0, len(blob), 4):
        if blob[i : i + 4] == pad:
            return ADDR_BACKSPACE + i
    raise ValueError("BackspaceNameCharPane has no NOP tail")


def field_b_cave_addr() -> int:
    return field_cave_addr() + len(build_field_cave())


def build_field_cave(
    base: int | None = None,
    resume: int = ADDR_FIELD_RESUME,
    fail: int = ADDR_FIELD_FAIL,
) -> bytes:
    """Return from the pane-field getter when the object is null.

    A null field already ends at ``bx lr``. A null object takes that exit
    before the ``ldreq`` of ``+0x60``, ``+0x64``, or ``+0x68``.
    """
    if base is None:
        base = field_cave_addr()
    body = bytearray()

    def at(mark: int | None = None) -> int:
        return base + (len(body) if mark is None else mark)

    body += cmp_imm(0, 0)
    beq_null = len(body)
    body += b"\x00\x00\x00\x00"
    body += VANILLA_FIELD
    body += b_ins(at(), resume)
    body[beq_null : beq_null + 4] = b_cond(0, at(beq_null), fail)
    blob = bytes(body)
    tail = ADDR_BACKSPACE + SIZE_BACKSPACE
    if base < ADDR_BACKSPACE or base + len(blob) > tail:
        raise ValueError(
            f"field cave {base:#x}+{len(blob):#x} is outside the "
            f"BackspaceNameCharPane tail ending {tail:#x}"
        )
    return blob


def fs_open_miss_addr() -> int:
    """NOP bytes after both pane-field caves."""
    at = field_b_cave_addr()
    return at + len(
        build_field_cave(at, resume=ADDR_FIELD_B_RESUME, fail=ADDR_FIELD_B_FAIL)
    )


def build_fs_open_miss(base: int | None = None) -> bytes:
    """Resume the layout constructor when the texture-bind frame is absent.

    ``OpenFileDirectly`` was about to pop a saved return of 0. The
    constructor's return is still on the stack; its failure epilogue
    returns 0 to a caller that already checks for a null layout.
    """
    if base is None:
        base = fs_open_miss_addr()
    body = bytearray()

    def at(mark: int | None = None) -> int:
        return base + (len(body) if mark is None else mark)

    body += add_imm(2, 13, 0x38)
    body += add_imm(3, 2, FS_SCAN)
    ldr_lit = len(body)
    body += b"\x00\x00\x00\x00"
    loop = at()
    body += _u32(0xE4921004)  # ldr r1, [r2], #4
    body += cmp_reg(1, 12)
    beq_found = len(body)
    body += b"\x00\x00\x00\x00"
    body += cmp_reg(2, 3)
    blo_loop = len(body)
    body += b"\x00\x00\x00\x00"
    body += bx_lr()  # neither frame is here; still the svc return
    found = at()
    body[beq_found : beq_found + 4] = b_cond(0, at(beq_found), found)
    body[blo_loop : blo_loop + 4] = b_cond(3, at(blo_loop), loop)
    body += add_imm(13, 2, 0)  # sp = word after the constructor return
    body += b_ins(at(), ADDR_LYT_CTOR_FAIL)
    lit = at()
    body[ldr_lit : ldr_lit + 4] = ldr_imm(12, 15, lit - at(ldr_lit) - 8)
    body += _u32(ADDR_LYT_CTOR_RET)
    blob = bytes(body)
    tail = ADDR_BACKSPACE + SIZE_BACKSPACE
    if base < field_b_cave_addr() or base + len(blob) > tail:
        raise ValueError(
            f"fs open miss cave {base:#x}+{len(blob):#x} is outside the "
            f"BackspaceNameCharPane tail ending {tail:#x}"
        )
    return blob


def name_cave_addr() -> int:
    """NOP bytes after the fs-open miss cave."""
    return fs_open_miss_addr() + len(build_fs_open_miss())


def build_name_cave(base: int | None = None) -> bytes:
    """Skip the name halfword when the directory offset is past the file.

    ``r0`` is still the masked 24-bit offset. ``r4`` is ``base + r0``.
    The fail branch is this function's ``mvn r0, #0`` epilogue.
    """
    if base is None:
        base = name_cave_addr()
    body = bytearray()
    body += cmp_imm(0, NAME_OFF_MAX)
    # ldrhlo r0, [r4]
    body += _u32(0x31D400B0)
    body += b_cond(2, base + len(body), ADDR_NAME_FAIL)
    body += b_ins(base + len(body), ADDR_NAME_RESUME)
    blob = bytes(body)
    tail = ADDR_BACKSPACE + SIZE_BACKSPACE
    if base < fs_open_miss_addr() + len(build_fs_open_miss()):
        raise ValueError(f"name cave {base:#x} overlaps the fs open miss cave")
    if base + len(blob) > tail:
        raise ValueError(
            f"name cave {base:#x}+{len(blob):#x} exceeds the "
            f"BackspaceNameCharPane tail ending {tail:#x}"
        )
    return blob


def menu_vt_cave_addr() -> int:
    """NOP bytes after the name-walk cave."""
    return name_cave_addr() + len(build_name_cave())


def build_menu_vt_cave(base: int | None = None) -> bytes:
    """Return from the virtual call when the object is null.

    The entry already pushed ``r4``. The caller overwrites ``r0``.
    """
    if base is None:
        base = menu_vt_cave_addr()
    body = bytearray()
    body += cmp_imm(0, 0)
    # popeq {r4, pc}
    body += _u32(0x08BD8010)
    body += VANILLA_MENU_VT
    body += b_ins(base + len(body), ADDR_MENU_VT_RESUME)
    blob = bytes(body)
    tail = ADDR_BACKSPACE + SIZE_BACKSPACE
    if base < name_cave_addr() + len(build_name_cave()):
        raise ValueError(f"menu vt cave {base:#x} overlaps the name cave")
    if base + len(blob) > tail:
        raise ValueError(
            f"menu vt cave {base:#x}+{len(blob):#x} exceeds the "
            f"BackspaceNameCharPane tail ending {tail:#x}"
        )
    return blob


def build_idx_load_cave(base: int = ADDR_IDX_LOAD_CAVE) -> bytes:
    """Skip ``ldr r1, [r2, r1]`` when ``r2`` is not a small file delta.

    ``r1`` is the table address. A delta of 0 still loads it, which is the
    logo and the background track. A delta of 16 MiB or more takes the
    epilogue.
    """
    body = bytearray()
    body += cmp_imm(2, IDX_DELTA_MAX)
    bhs_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += VANILLA_IDX_LOAD
    body += b_ins(base + len(body), ADDR_IDX_LOAD_RESUME)
    body[bhs_at : bhs_at + 4] = b_cond(2, base + bhs_at, ADDR_IDX_LOAD_FAIL)
    blob = bytes(body)
    if base != ADDR_IDX_LOAD_CAVE:
        raise ValueError(f"idx load cave is fixed at {ADDR_IDX_LOAD_CAVE:#x}")
    if base + len(blob) > ADDR_IDX_LOAD_LIMIT:
        raise ValueError(
            f"idx load cave {base:#x}+{len(blob):#x} exceeds {ADDR_IDX_LOAD_LIMIT:#x}"
        )
    return blob


def build_node_byte_cave(base: int = ADDR_NODE_BYTE_CAVE) -> bytes:
    """Skip ``ldrb r0, [sl, #0x14]`` when ``sl`` is at or above the heap.

    The fail branch is the same epilogue as the IDX-base guard.
    """
    body = bytearray()
    body += cmp_imm(10, HEAP_HI)
    bhs_at = len(body)
    body += b"\x00\x00\x00\x00"
    body += _u32(0xE5DA0014)  # ldrb r0, [sl, #0x14]
    body += b_ins(base + len(body), ADDR_NODE_BYTE_RESUME)
    body[bhs_at : bhs_at + 4] = b_cond(2, base + bhs_at, ADDR_IDX_LOAD_FAIL)
    blob = bytes(body)
    if base != ADDR_NODE_BYTE_CAVE:
        raise ValueError(f"node byte cave is fixed at {ADDR_NODE_BYTE_CAVE:#x}")
    if base + len(blob) > ADDR_NODE_BYTE_LIMIT:
        raise ValueError(
            f"node byte cave {base:#x}+{len(blob):#x} exceeds {ADDR_NODE_BYTE_LIMIT:#x}"
        )
    return blob


def build_pane_flag_cave(base: int = ADDR_PANE_FLAG_CAVE) -> bytes:
    """Take the menu-update epilogue when the pane in ``r6`` is null."""
    body = bytearray()
    body += cmp_imm(6, 0)
    body += b_cond(0, base + len(body), ADDR_PANE_FLAG_FAIL)  # beq
    body += b_ins(base + len(body), ADDR_PANE_FLAG_LOAD)
    blob = bytes(body)
    if len(blob) != ADDR_PANE_FLAG_CAVE_LEN:
        raise ValueError(f"pane flag cave is {len(blob):#x} bytes")
    return blob


def heap_walk_stub_addr() -> int:
    """Last 8 bytes of the strcat tail, after the fixup cave."""
    return fixup_cave_addr() + len(build_fixup_cave())


def build_heap_walk_stub(base: int | None = None) -> bytes:
    """``ldr r2, [r0, #4]`` then the size compare."""
    if base is None:
        base = heap_walk_stub_addr()
    body = bytearray()
    body += VANILLA_HEAP_WALK
    body += b_ins(base + len(body), ADDR_HEAP_WALK_RESUME)
    blob = bytes(body)
    if base + len(blob) > ADDR_CHUNK_WALK_LIMIT:
        raise ValueError(
            f"heap walk stub {base:#x}+{len(blob):#x} exceeds "
            f"{ADDR_CHUNK_WALK_LIMIT:#x}"
        )
    return blob


def build_heap_walk_cave(base: int = ADDR_HEAP_WALK_CAVE) -> bytes:
    """Skip ``ldr r2, [r0, #4]`` when the free-list node is past the heap.

    ``PUPU`` (``0x55505550``) arrives as ``r0``. The fail branch is
    ``cmp r7, #0``, so a block already chosen is kept and an empty
    search returns null. The load lives in the strcat tail.
    """
    body = bytearray()
    body += cmp_imm(0, HEAP_HI)
    body += b_cond(2, base + len(body), ADDR_HEAP_WALK_FAIL)
    body += b_ins(base + len(body), heap_walk_stub_addr())
    blob = bytes(body)
    if len(blob) != ADDR_HEAP_WALK_CAVE_LEN:
        raise ValueError(
            f"heap walk cave is {len(blob):#x} bytes, slot is "
            f"{ADDR_HEAP_WALK_CAVE_LEN:#x}"
        )
    if base + len(blob) > ADDR_DEREF + DEREF_LEN:
        raise ValueError(
            f"heap walk cave {base:#x}+{len(blob):#x} overlaps the "
            f"next helper at {ADDR_DEREF + DEREF_LEN:#x}"
        )
    return blob


def _ldr_cond(cond: int, rd: int, rn: int, imm: int) -> bytes:
    return _u32((cond << 28) | 0x05900000 | (rn << 16) | (rd << 12) | imm)


def _str_cond(cond: int, rd: int, rn: int, imm: int) -> bytes:
    return _u32((cond << 28) | 0x05800000 | (rn << 16) | (rd << 12) | imm)


def build_heap_link_pad(base: int = ADDR_HEAP_LINK_PAD) -> bytes:
    """Load ``[r7, #0xc]`` and reduce it to a heap offset in ``r12``."""
    body = bytearray()
    body += ldr_imm(2, 7, 0xC)
    body += sub_imm(12, 2, HEAP_LO)
    body += b_ins(base + len(body), ADDR_HEAP_LINK_BODY)
    blob = bytes(body)
    if len(blob) != ADDR_HEAP_LINK_PAD_LEN:
        raise ValueError(
            f"heap link pad is {len(blob):#x} bytes, slot is {ADDR_HEAP_LINK_PAD_LEN:#x}"
        )
    return blob


def build_heap_link_body(base: int = ADDR_HEAP_LINK_BODY) -> bytes:
    """Skip the backward-link stores when that neighbor is off the heap.

    The block's own links are still updated, so the allocation returns.
    """
    body = bytearray()
    body += cmp_imm(12, HEAP_SPAN)
    body += _str_cond(3, 2, 0, 0xC)  # strlo r2, [r0, #0xc]
    body += _str_cond(3, 0, 2, 8)  # strlo r0, [r2, #8]
    # Keep the allocated block off this list when the old link was PUPU.
    body += _str_cond(3, 0, 7, 0xC)  # strlo r0, [r7, #0xc]
    body += _str_cond(3, 7, 0, 8)  # strlo r7, [r0, #8]
    blob = bytes(body)
    if base + len(blob) != ADDR_HEAP_LINK_END:
        raise ValueError(
            f"heap link body {base:#x}+{len(blob):#x} ends "
            f"{base + len(blob):#x}, expected {ADDR_HEAP_LINK_END:#x}"
        )
    return blob


def _with_cond(word: bytes, cond: int) -> bytes:
    raw = int.from_bytes(word, "little")
    return _u32((raw & 0x0FFFFFFF) | ((cond & 0xF) << 28))


def build_heap_bin(base: int = ADDR_HEAP_BIN) -> bytes:
    """Splice the remainder without storing through 0 or ``PUPU``.

    A null or high next becomes the heap end sentinel. A null previous
    node becomes the new heap head, so the leftover block stays
    reachable. A high previous node is not stored through.
    """
    body = bytearray()
    body += ldr_imm(2, 7, 0x14)
    body += cmp_imm(2, 0)
    body += _with_cond(cmp_imm(2, HEAP_HI), 1)  # cmpne r2, #HEAP_HI
    body += _ldr_cond(2, 2, 5, 8)  # ldrhs r2, [r5, #8]
    body += str_imm(2, 0, 0x14)
    body += ldr_imm(2, 7, 0x10)
    body += cmp_imm(2, 0)
    body += _str_cond(0, 0, 5, 4)  # streq r0, [r5, #4]
    body += _with_cond(cmp_imm(2, HEAP_HI), 1)  # cmpne r2, #HEAP_HI
    body += _str_cond(3, 0, 2, 0x14)  # strlo r0, [r2, #0x14]
    blob = bytes(body)
    if base + len(blob) != ADDR_HEAP_BIN_END:
        raise ValueError(
            f"heap bin body {base:#x}+{len(blob):#x} ends "
            f"{base + len(blob):#x}, expected {ADDR_HEAP_BIN_END:#x}"
        )
    return blob


def build_heap_tail(base: int = ADDR_HEAP_TAIL) -> bytes:
    """Size split, then the null return, packed into the old epilogue."""
    body = bytearray()
    body += ldr_imm(2, 7, 4)
    body += sub_reg(2, 2, 1)
    body += sub_imm(2, 2, 0x20)
    body += str_imm(2, 0, 4)
    body += str_imm(1, 7, 4)
    body += b_ins(base + len(body), ADDR_HEAP_SUCCESS)
    body += mov_reg(0, 13)
    body += bl(base + len(body), ADDR_HEAP_UNLOCK)
    body += mov_reg(0, 13)
    body += mov_reg(0, 7)
    body += _u32(0xE8BD80F8)  # pop {r3, r4, r5, r6, r7, pc}
    blob = bytes(body)
    if base + len(blob) != ADDR_HEAP_TAIL_END:
        raise ValueError(
            f"heap tail {base:#x}+{len(blob):#x} ends "
            f"{base + len(blob):#x}, expected {ADDR_HEAP_TAIL_END:#x}"
        )
    return blob


def build_row_gate(base: int = ADDR_ROW_GATE) -> bytes:
    """Keep the original empty-span branch, then range-check the pointer."""
    body = bytearray()
    body += b_cond(8, base + len(body), ADDR_ROW_SKIP)  # bhi skip
    body += b_ins(base + len(body), ADDR_ROW_CHECK)
    blob = bytes(body)
    if len(blob) != 8:
        raise ValueError(f"row gate is {len(blob):#x} bytes")
    return blob


def build_row_check(base: int = ADDR_ROW_CHECK) -> bytes:
    """Skip ``str r0, [r1]`` when ``r1`` is below a real buffer."""
    body = bytearray()
    body += cmp_imm(1, ROW_PTR_MIN)
    body += b_cond(2, base + len(body), ADDR_ROW_STORE)  # bhs store
    body += b_ins(base + len(body), ADDR_ROW_SKIP)
    blob = bytes(body)
    if len(blob) != 12:
        raise ValueError(f"row check is {len(blob):#x} bytes")
    return blob


def build_memset_cave(base: int = ADDR_MEMSET_CAVE) -> bytes:
    """Return before the fill when the destination is null."""
    body = bytearray()
    body += cmp_imm(0, 0)
    body += bx_lr(0)  # bxeq lr
    body += b_ins(base + len(body), ADDR_MEMSET_STUB)
    blob = bytes(body)
    if len(blob) != 12:
        raise ValueError(f"memset cave is {len(blob):#x} bytes")
    return blob


def build_memset_stub(base: int = ADDR_MEMSET_STUB) -> bytes:
    body = bytearray()
    body += mov_imm(2, 0)
    body += b_ins(base + len(body), ADDR_MEMSET_BODY)
    blob = bytes(body)
    if len(blob) != 8:
        raise ValueError(f"memset stub is {len(blob):#x} bytes")
    return blob


def build_pak_init(base: int = ADDR_PAK_INIT) -> bytes:
    """Skip the header stores when the table is null. Keep building the object.

    ``mov r2, r6`` was dead (``r2`` is overwritten before it is read), and
    ``r2`` is 0, so ``stm {r1, r2, r6}`` covers the old ``stm`` plus the
    store at ``+8``. The halfword and two bytes at ``+0x10`` pack into
    ``0x02000001``. That frees the branch which skips those four stores.
    ``r2`` stays 0, which is the heap index the allocation below uses.
    """
    body = bytearray()
    body += mov_reg(2, 6)
    body += ldr_imm(5, 0, 0xC)
    body += cmp_imm(5, 0)
    body += b_cond(0, base + len(body), ADDR_PAK_INIT_END)
    body += mov_imm(0, 2)
    body += _u32(0xE8850046)  # stm r5, {r1, r2, r6}
    body += orr_reg(12, 7, 0, 24)  # orr r12, r7, r0, lsl #24 → 0x02000001
    body += str_imm(12, 5, 0x10)
    blob = bytes(body)
    if base + len(blob) != ADDR_PAK_INIT_END:
        raise ValueError(
            f"pak init {base:#x}+{len(blob):#x} ends "
            f"{base + len(blob):#x}, expected {ADDR_PAK_INIT_END:#x}"
        )
    return blob


def _thumb_blx(here: int, target: int) -> bytes:
    """Thumb BLX to a word-aligned ARM address."""
    pc = (here + 4) & ~3
    off = (target - pc) & 0xFFFFFFFF
    if off & 3:
        raise ValueError(f"thumb blx target {target:#x} is not word aligned")
    sign = (off >> 24) & 1
    i1 = (off >> 23) & 1
    i2 = (off >> 22) & 1
    imm10 = (off >> 12) & 0x3FF
    imm10l = (off >> 2) & 0x3FF
    j1 = (~(i1 ^ sign)) & 1
    j2 = (~(i2 ^ sign)) & 1
    hw1 = 0xF000 | (sign << 10) | imm10
    hw2 = 0xC000 | (j1 << 13) | (j2 << 11) | (imm10l << 1)
    return hw1.to_bytes(2, "little") + hw2.to_bytes(2, "little")


def build_pak_table_cave(base: int = ADDR_PAK_TABLE_CAVE) -> bytes:
    """Return 0 when the table base is null. Otherwise load the flag byte.

    Entered from ARM with ``blx``. ``r0`` is the base and ``r4`` is the
    indexed address. ``lr`` is the ``tst`` after the load. A null base
    branches to this function's ``mov r0, #0; pop``.
    """
    if base != ADDR_PAK_TABLE_CAVE:
        raise ValueError(f"pak table cave is fixed at {ADDR_PAK_TABLE_CAVE:#x}")
    body = bytearray()
    body += (0x2800).to_bytes(2, "little")  # cmp r0, #0
    body += (0xD101).to_bytes(2, "little")  # bne.n load
    body += _thumb_blx(base + 4, ADDR_PAK_TABLE_FAIL)
    body += (0x7CE0).to_bytes(2, "little")  # ldrb r0, [r4, #0x13]
    body += (0x4770).to_bytes(2, "little")  # bx lr
    blob = bytes(body)
    if len(blob) != ADDR_PAK_TABLE_CAVE_LEN:
        raise ValueError(f"pak table cave is {len(blob):#x} bytes")
    if base + len(blob) != 0x005D1940:
        raise ValueError("pak table cave runs into the flag check")
    return blob


def apply_pak_table(data: bytearray) -> None:
    """Write the table-base check. Safe after the message-speed sample rewrite."""
    cave = build_pak_table_cave()
    hook = blx_imm(ADDR_PAK_TABLE, ADDR_PAK_TABLE_CAVE)
    head = bytes(data[ADDR_PAK_TABLE : ADDR_PAK_TABLE + 4])
    if head != VANILLA_PAK_TABLE and head != hook:
        raise ValueError(f"unexpected pak table load at {ADDR_PAK_TABLE:#x}: {head.hex()}")
    slot = bytes(data[ADDR_PAK_TABLE_CAVE : ADDR_PAK_TABLE_CAVE + len(cave)])
    if slot not in (cave, VANILLA_PAK_TABLE_CAVE, b"\x00" * len(cave)):
        raise ValueError(f"pak table cave is not padding: {slot.hex()}")
    data[ADDR_PAK_TABLE_CAVE : ADDR_PAK_TABLE_CAVE + len(cave)] = cave
    data[ADDR_PAK_TABLE : ADDR_PAK_TABLE + 4] = hook
    print(
        f"[pak-table] @{ADDR_PAK_TABLE:#x} -> @{ADDR_PAK_TABLE_CAVE:#x} "
        f"({len(cave):#x})"
    )


ADDR_PAK_ALLOC = 0x0000D3D8  # str r0, [r5, #4] after the PACK malloc
VANILLA_PAK_ALLOC = bytes.fromhex("040085e5")
ADDR_PAK_FLAG_CHECK = 0x005D1940  # ARM, after the table check in the sample pool
ADDR_PAK_FLAG_CHECK_LEN = 16


def build_pak_flag_cave(base: int = ADDR_PAK_FLAG_CHECK) -> bytes:
    """Set bit 3 when the table base is null, else load the flag byte.

    Entered by ``bl`` with ``r1`` still the base and ``r7`` the indexed
    address. ``lr`` is ``tst r1, #8``. ``r1 = 8`` makes that test take
    the epilogue. A real base still loads ``[r7, #0x13]``.
    """
    body = bytearray()
    body += cmp_imm(1, 0)
    body += mov_imm_cond(0, 1, 8)  # moveq r1, #8
    body += _u32(0x15D71013)  # ldrneb r1, [r7, #0x13]
    body += _u32(0xE12FFF1E)  # bx lr
    blob = bytes(body)
    if len(blob) != ADDR_PAK_FLAG_CHECK_LEN:
        raise ValueError(f"pak flag cave is {len(blob):#x} bytes")
    if base + len(blob) != 0x005D1950:
        raise ValueError("pak flag cave runs into the next instruction")
    return blob


def build_pak_alloc_cave(base: int = ADDR_PAK_FLAG_CAVE) -> bytes:
    """Pop when the PACK allocation is null. Otherwise keep the table link.

    Thumb, entered by ARM ``blx`` so ``lr`` is the ``mov r1, #0x50`` after
    the store. A null ``r0`` takes the frame pop at ``0xD634`` (``r0``
    stays 0). A null table skips ``str r0, [r5, #4]``.
    """
    body = bytearray()
    body += (0x2800).to_bytes(2, "little")  # cmp r0, #0
    body += (0xD101).to_bytes(2, "little")  # bne.n past the blx
    body += _thumb_blx(base + 4, ADDR_PAK_POP)
    body += (0x2D00).to_bytes(2, "little")  # cmp r5, #0
    body += (0xD000).to_bytes(2, "little")  # beq.n bx
    body += (0x6068).to_bytes(2, "little")  # str r0, [r5, #4]
    body += (0x4770).to_bytes(2, "little")  # bx lr
    blob = bytes(body)
    if len(blob) != ADDR_PAK_FLAG_CAVE_LEN:
        raise ValueError(f"pak alloc cave is {len(blob):#x} bytes")
    return blob


def _fillcand_tail(at: int) -> bytes:
    """``mov r6, #0; b`` the fillcand site-1 null path, from ``at``."""
    from patch_input_candidate_nullguard import POST1, REG1, b_ins as cand_b
    from patch_input_candidate_nullguard import mov_imm0

    return mov_imm0(REG1) + cand_b(at + 4, POST1)


def apply_pak_flag(data: bytearray) -> None:
    """Pop the PACK init when its allocation is null.

    The fillcand null tail moves to the pad before the commu header so
    this cave can sit in the shared RX page. Apply after fillcand and
    after the commu header.
    """
    from patch_input_candidate_nullguard import CAVE1, beq as cand_beq

    cave = build_pak_alloc_cave()
    hook = blx_imm(ADDR_PAK_ALLOC, ADDR_PAK_FLAG_CAVE)
    tail = _fillcand_tail(ADDR_FILLCAND_TAIL)
    old_tail = _fillcand_tail(CAVE1 + 0x10)
    head = bytes(data[ADDR_PAK_ALLOC : ADDR_PAK_ALLOC + 4])
    if head != VANILLA_PAK_ALLOC and head != hook:
        raise ValueError(f"unexpected pak alloc store at {ADDR_PAK_ALLOC:#x}: {head.hex()}")
    slot = bytes(data[ADDR_PAK_FLAG_CAVE : ADDR_PAK_FLAG_CAVE + len(cave)])
    if slot not in (cave, old_tail + b"\x00" * 8):
        raise ValueError(f"pak alloc cave is not the fillcand tail: {slot.hex()}")
    dest = bytes(data[ADDR_FILLCAND_TAIL : ADDR_FILLCAND_TAIL + len(tail)])
    if dest != tail and dest != b"\x00" * len(tail):
        raise ValueError(f"fillcand tail pad is not empty: {dest.hex()}")
    beq_at = CAVE1 + 4
    old_beq = cand_beq(beq_at, CAVE1 + 0x10)
    new_beq = cand_beq(beq_at, ADDR_FILLCAND_TAIL)
    got = bytes(data[beq_at : beq_at + 4])
    if got != old_beq and got != new_beq:
        raise ValueError(f"unexpected fillcand beq at {beq_at:#x}: {got.hex()}")
    data[ADDR_FILLCAND_TAIL : ADDR_FILLCAND_TAIL + len(tail)] = tail
    data[beq_at : beq_at + 4] = new_beq
    data[ADDR_PAK_FLAG_CAVE : ADDR_PAK_FLAG_CAVE + len(cave)] = cave
    data[ADDR_PAK_ALLOC : ADDR_PAK_ALLOC + 4] = hook
    flag = build_pak_flag_cave()
    flag_hook = bl(ADDR_PAK_FLAG, ADDR_PAK_FLAG_CHECK)
    flag_head = bytes(data[ADDR_PAK_FLAG : ADDR_PAK_FLAG + 4])
    if flag_head != VANILLA_PAK_FLAG and flag_head != flag_hook:
        raise ValueError(f"unexpected pak flag load at {ADDR_PAK_FLAG:#x}: {flag_head.hex()}")
    data[ADDR_PAK_FLAG_CHECK : ADDR_PAK_FLAG_CHECK + len(flag)] = flag
    data[ADDR_PAK_FLAG : ADDR_PAK_FLAG + 4] = flag_hook
    print(
        f"[pak-alloc] @{ADDR_PAK_ALLOC:#x} -> @{ADDR_PAK_FLAG_CAVE:#x} "
        f"({len(cave):#x}); fillcand tail @{ADDR_FILLCAND_TAIL:#x}"
    )
    print(
        f"[pak-flag] @{ADDR_PAK_FLAG:#x} -> @{ADDR_PAK_FLAG_CHECK:#x} "
        f"({len(flag):#x})"
    )


def is_patched(data: bytes) -> bool:
    blob, labs = build_cave()
    fixup = build_fixup_cave()
    fixup_at = fixup_cave_addr()
    title = build_title_reloc_cave()
    index = build_title_index_cave()
    clyt_at = clyt_cave_addr()
    clyt = build_clyt_cave(clyt_at)
    lyt_at = lyt_hdr_cave_addr()
    lyt = build_lyt_hdr_cave(lyt_at)
    vt_at = vt_cave_addr()
    vt = build_vt_cave(vt_at)
    obj_at = title_obj_cave_addr()
    obj = build_title_obj_cave(obj_at)
    fs_at = fs_open_cave_addr()
    fs = build_fs_open_cave(fs_at)
    rel_at = tex_release_cave_addr()
    rel = build_tex_release_cave(rel_at)
    field_at = field_cave_addr()
    field = build_field_cave(field_at)
    field_b_at = field_b_cave_addr()
    field_b = build_field_cave(
        field_b_at, resume=ADDR_FIELD_B_RESUME, fail=ADDR_FIELD_B_FAIL
    )
    miss_at = fs_open_miss_addr()
    miss = build_fs_open_miss(miss_at)
    name_at = name_cave_addr()
    name = build_name_cave(name_at)
    menu_at = menu_vt_cave_addr()
    menu = build_menu_vt_cave(menu_at)
    idx = build_idx_load_cave()
    node = build_node_byte_cave()
    pane = build_pane_flag_cave()
    heap = build_heap_walk_cave()
    stub_at = heap_walk_stub_addr()
    stub = build_heap_walk_stub(stub_at)
    link_pad = build_heap_link_pad()
    link_body = build_heap_link_body()
    heap_bin = build_heap_bin()
    heap_tail = build_heap_tail()
    row_gate = build_row_gate()
    row_check = build_row_check()
    memset_cave = build_memset_cave()
    memset_stub = build_memset_stub()
    pak = build_pak_init()
    deref = labs["deref"]
    advance = labs["advance"]
    return (
        data[ADDR_DEREF : ADDR_DEREF + 4] == b_ins(ADDR_DEREF, deref)
        and data[ADDR_ADVANCE : ADDR_ADVANCE + 4] == b_ins(ADDR_ADVANCE, advance)
        and bytes(data[ADDR_CHUNK_WALK_CAVE : ADDR_CHUNK_WALK_CAVE + len(blob)]) == blob
        and data[ADDR_FIXUP : ADDR_FIXUP + 4] == bl(ADDR_FIXUP, fixup_at)
        and bytes(data[fixup_at : fixup_at + len(fixup)]) == fixup
        and data[ADDR_TITLE_RELOC : ADDR_TITLE_RELOC + 4]
        == b_ins(ADDR_TITLE_RELOC, ADDR_TITLE_RELOC_CAVE)
        and bytes(data[ADDR_TITLE_RELOC_CAVE : ADDR_TITLE_RELOC_CAVE + len(title)])
        == title
        and data[ADDR_TITLE_INDEX : ADDR_TITLE_INDEX + 4]
        == b_ins(ADDR_TITLE_INDEX, ADDR_TITLE_INDEX_CAVE)
        and bytes(data[ADDR_TITLE_INDEX_CAVE : ADDR_TITLE_INDEX_CAVE + len(index)])
        == index
        and data[ADDR_CLYT : ADDR_CLYT + 4] == b_ins(ADDR_CLYT, clyt_at)
        and bytes(data[clyt_at : clyt_at + len(clyt)]) == clyt
        and data[ADDR_LYT_HDR : ADDR_LYT_HDR + 4] == b_ins(ADDR_LYT_HDR, lyt_at)
        and bytes(data[lyt_at : lyt_at + len(lyt)]) == lyt
        and data[ADDR_VT : ADDR_VT + 4] == b_ins(ADDR_VT, vt_at)
        and bytes(data[vt_at : vt_at + len(vt)]) == vt
        and data[ADDR_TITLE_OBJ : ADDR_TITLE_OBJ + 4] == b_ins(ADDR_TITLE_OBJ, obj_at)
        and bytes(data[obj_at : obj_at + len(obj)]) == obj
        and data[ADDR_FS_OPEN : ADDR_FS_OPEN + 4] == bl(ADDR_FS_OPEN, fs_at)
        and bytes(data[fs_at : fs_at + len(fs)]) == fs
        and data[ADDR_TEX_REL : ADDR_TEX_REL + 4] == b_ins(ADDR_TEX_REL, rel_at)
        and bytes(data[rel_at : rel_at + len(rel)]) == rel
        and data[ADDR_FIELD : ADDR_FIELD + 4] == b_ins(ADDR_FIELD, field_at)
        and bytes(data[field_at : field_at + len(field)]) == field
        and data[ADDR_FIELD_B : ADDR_FIELD_B + 4] == b_ins(ADDR_FIELD_B, field_b_at)
        and bytes(data[field_b_at : field_b_at + len(field_b)]) == field_b
        and bytes(data[miss_at : miss_at + len(miss)]) == miss
        and data[ADDR_NAME : ADDR_NAME + 4] == b_ins(ADDR_NAME, name_at)
        and bytes(data[name_at : name_at + len(name)]) == name
        and data[ADDR_MENU_VT : ADDR_MENU_VT + 4] == b_ins(ADDR_MENU_VT, menu_at)
        and bytes(data[menu_at : menu_at + len(menu)]) == menu
        and data[ADDR_IDX_LOAD : ADDR_IDX_LOAD + 4]
        == b_ins(ADDR_IDX_LOAD, ADDR_IDX_LOAD_CAVE)
        and bytes(data[ADDR_IDX_LOAD_CAVE : ADDR_IDX_LOAD_CAVE + len(idx)]) == idx
        and data[ADDR_NODE_BYTE : ADDR_NODE_BYTE + 4]
        == b_ins(ADDR_NODE_BYTE, ADDR_NODE_BYTE_CAVE)
        and bytes(data[ADDR_NODE_BYTE_CAVE : ADDR_NODE_BYTE_CAVE + len(node)]) == node
        and data[ADDR_PANE_FLAG_BR : ADDR_PANE_FLAG_BR + 4]
        == b_cond(0, ADDR_PANE_FLAG_BR, ADDR_PANE_FLAG_CAVE)
        and bytes(data[ADDR_PANE_FLAG_CAVE : ADDR_PANE_FLAG_CAVE + len(pane)]) == pane
        and data[ADDR_ROW_CLEAR : ADDR_ROW_CLEAR + 4]
        == b_ins(ADDR_ROW_CLEAR, ADDR_ROW_GATE)
        and bytes(data[ADDR_ROW_GATE : ADDR_ROW_GATE + len(row_gate)]) == row_gate
        and bytes(data[ADDR_ROW_CHECK : ADDR_ROW_CHECK + len(row_check)]) == row_check
        and data[ADDR_MEMSET : ADDR_MEMSET + 4] == b_ins(ADDR_MEMSET, ADDR_MEMSET_CAVE)
        and bytes(data[ADDR_MEMSET_CAVE : ADDR_MEMSET_CAVE + len(memset_cave)])
        == memset_cave
        and bytes(data[ADDR_MEMSET_STUB : ADDR_MEMSET_STUB + len(memset_stub)])
        == memset_stub
        and (
            (
                APPLY_HEAP_AND_PAK
                and data[ADDR_HEAP_WALK : ADDR_HEAP_WALK + 4]
                == b_ins(ADDR_HEAP_WALK, ADDR_HEAP_WALK_CAVE)
                and bytes(data[ADDR_HEAP_WALK_CAVE : ADDR_HEAP_WALK_CAVE + len(heap)])
                == heap
                and bytes(data[stub_at : stub_at + len(stub)]) == stub
                and data[ADDR_HEAP_LINK : ADDR_HEAP_LINK + 4]
                == b_ins(ADDR_HEAP_LINK, ADDR_HEAP_LINK_PAD)
                and bytes(data[ADDR_HEAP_LINK_PAD : ADDR_HEAP_LINK_PAD + len(link_pad)])
                == link_pad
                and bytes(
                    data[ADDR_HEAP_LINK_BODY : ADDR_HEAP_LINK_BODY + len(link_body)]
                )
                == link_body
                and bytes(data[ADDR_HEAP_BIN : ADDR_HEAP_BIN + len(heap_bin)])
                == heap_bin
                and bytes(data[ADDR_HEAP_TAIL : ADDR_HEAP_TAIL + len(heap_tail)])
                == heap_tail
                and data[ADDR_HEAP_EMPTY : ADDR_HEAP_EMPTY + 4]
                == b_cond(0, ADDR_HEAP_EMPTY, ADDR_HEAP_FAIL)
                and data[ADDR_HEAP_NOFIT : ADDR_HEAP_NOFIT + 4]
                == b_cond(0, ADDR_HEAP_NOFIT, ADDR_HEAP_FAIL)
                and bytes(data[ADDR_PAK_INIT : ADDR_PAK_INIT + len(pak)]) == pak
            )
            or (
                not APPLY_HEAP_AND_PAK
                and data[ADDR_HEAP_WALK : ADDR_HEAP_WALK + 4] == VANILLA_HEAP_WALK
                and bytes(data[ADDR_PAK_INIT : ADDR_PAK_INIT + len(VANILLA_PAK_INIT)])
                == VANILLA_PAK_INIT
            )
        )
    )


def apply_patch(data: bytearray) -> None:
    if not strcat_patched(data):
        raise ValueError(
            f"chunk-walk guard needs the strcat-raw branch at {STRCAT_ADDR:#x}"
        )
    blob, labs = build_cave()
    fixup_at = fixup_cave_addr()
    fixup = build_fixup_cave(fixup_at)
    end = fixup_at + len(fixup)
    if is_patched(data):
        print(f"[chunk-walk] already applied @{ADDR_CHUNK_WALK_CAVE:#x}")
        return
    for addr, vanilla, label in (
        (ADDR_DEREF, VANILLA_DEREF, "deref"),
        (ADDR_ADVANCE, VANILLA_ADVANCE, "advance"),
    ):
        head = bytes(data[addr : addr + 4])
        if bytes(data[addr : addr + len(vanilla)]) != vanilla and head != b_ins(
            addr, labs[label]
        ):
            raise ValueError(f"unexpected {label} at {addr:#x}: {head.hex()}")
    fixup_head = bytes(data[ADDR_FIXUP : ADDR_FIXUP + 4])
    if fixup_head != VANILLA_FIXUP and fixup_head != bl(ADDR_FIXUP, fixup_at):
        raise ValueError(f"unexpected fixup at {ADDR_FIXUP:#x}: {fixup_head.hex()}")
    title = build_title_reloc_cave()
    title_head = bytes(data[ADDR_TITLE_RELOC : ADDR_TITLE_RELOC + 4])
    title_hook = b_ins(ADDR_TITLE_RELOC, ADDR_TITLE_RELOC_CAVE)
    if title_head != VANILLA_TITLE_RELOC and title_head != title_hook:
        raise ValueError(
            f"unexpected title reloc at {ADDR_TITLE_RELOC:#x}: {title_head.hex()}"
        )
    if data[ADDR_CLEAR : ADDR_CLEAR + 4] != NAME_PANE_STUB:
        raise ValueError(
            "title index cave needs the name-pane stub at "
            f"{ADDR_CLEAR:#x} (apply name panes first)"
        )
    index = build_title_index_cave()
    index_head = bytes(data[ADDR_TITLE_INDEX : ADDR_TITLE_INDEX + 4])
    index_hook = b_ins(ADDR_TITLE_INDEX, ADDR_TITLE_INDEX_CAVE)
    if index_head != VANILLA_TITLE_INDEX and index_head != index_hook:
        raise ValueError(
            f"unexpected title index at {ADDR_TITLE_INDEX:#x}: {index_head.hex()}"
        )
    clyt_at = clyt_cave_addr()
    clyt = build_clyt_cave(clyt_at)
    clyt_head = bytes(data[ADDR_CLYT : ADDR_CLYT + 4])
    clyt_hook = b_ins(ADDR_CLYT, clyt_at)
    if clyt_head != VANILLA_CLYT and clyt_head != clyt_hook:
        raise ValueError(f"unexpected clyt check at {ADDR_CLYT:#x}: {clyt_head.hex()}")
    lyt_at = lyt_hdr_cave_addr()
    lyt = build_lyt_hdr_cave(lyt_at)
    lyt_head = bytes(data[ADDR_LYT_HDR : ADDR_LYT_HDR + 4])
    lyt_hook = b_ins(ADDR_LYT_HDR, lyt_at)
    if lyt_head != VANILLA_LYT_HDR and lyt_head != lyt_hook:
        raise ValueError(f"unexpected layout header at {ADDR_LYT_HDR:#x}: {lyt_head.hex()}")
    vt_at = vt_cave_addr()
    vt = build_vt_cave(vt_at)
    vt_head = bytes(data[ADDR_VT : ADDR_VT + 4])
    vt_hook = b_ins(ADDR_VT, vt_at)
    if vt_head != VANILLA_VT and vt_head != vt_hook:
        raise ValueError(f"unexpected virtual call at {ADDR_VT:#x}: {vt_head.hex()}")
    obj_at = title_obj_cave_addr()
    obj = build_title_obj_cave(obj_at)
    obj_head = bytes(data[ADDR_TITLE_OBJ : ADDR_TITLE_OBJ + 4])
    obj_hook = b_ins(ADDR_TITLE_OBJ, obj_at)
    if obj_head != VANILLA_TITLE_OBJ and obj_head != obj_hook:
        raise ValueError(
            f"unexpected title object at {ADDR_TITLE_OBJ:#x}: {obj_head.hex()}"
        )
    fs_at = fs_open_cave_addr()
    fs = build_fs_open_cave(fs_at)
    fs_hook = bl(ADDR_FS_OPEN, fs_at)
    fs_head = bytes(data[ADDR_FS_OPEN : ADDR_FS_OPEN + 4])
    # A previous build branched at this site into the 12-byte tail cave.
    fs_head_w = int.from_bytes(fs_head, "little")
    if fs_head != VANILLA_FS_OPEN and fs_head != fs_hook and (fs_head_w >> 24) != 0xEB:
        raise ValueError(f"unexpected fs open at {ADDR_FS_OPEN:#x}: {fs_head.hex()}")
    fs_slot = bytes(data[fs_at : fs_at + len(fs)])
    if fs_slot != fs and fs_slot != nop() * (len(fs) // 4):
        raise ValueError(f"fs open cave @{fs_at:#x} is not padding: {fs_slot.hex()}")
    rel_at = tex_release_cave_addr()
    rel = build_tex_release_cave(rel_at)
    rel_hook = b_ins(ADDR_TEX_REL, rel_at)
    rel_head = bytes(data[ADDR_TEX_REL : ADDR_TEX_REL + 4])
    if rel_head != VANILLA_TEX_REL and rel_head != rel_hook:
        raise ValueError(f"unexpected texture release at {ADDR_TEX_REL:#x}: {rel_head.hex()}")
    rel_slot = bytes(data[rel_at : rel_at + len(rel)])
    if rel_slot != rel and rel_slot != nop() * (len(rel) // 4):
        raise ValueError(f"texture release cave @{rel_at:#x} is not padding: {rel_slot.hex()}")
    field_at = field_cave_addr()
    field = build_field_cave(field_at)
    field_hook = b_ins(ADDR_FIELD, field_at)
    field_head = bytes(data[ADDR_FIELD : ADDR_FIELD + 4])
    if field_head != VANILLA_FIELD and field_head != field_hook:
        raise ValueError(f"unexpected field getter at {ADDR_FIELD:#x}: {field_head.hex()}")
    field_slot = bytes(data[field_at : field_at + len(field)])
    if field_slot != field and field_slot != nop() * (len(field) // 4):
        raise ValueError(f"field cave @{field_at:#x} is not padding: {field_slot.hex()}")
    field_b_at = field_b_cave_addr()
    field_b = build_field_cave(
        field_b_at, resume=ADDR_FIELD_B_RESUME, fail=ADDR_FIELD_B_FAIL
    )
    field_b_hook = b_ins(ADDR_FIELD_B, field_b_at)
    field_b_head = bytes(data[ADDR_FIELD_B : ADDR_FIELD_B + 4])
    if field_b_head != VANILLA_FIELD and field_b_head != field_b_hook:
        raise ValueError(
            f"unexpected field getter at {ADDR_FIELD_B:#x}: {field_b_head.hex()}"
        )
    field_b_slot = bytes(data[field_b_at : field_b_at + len(field_b)])
    if field_b_slot != field_b and field_b_slot != nop() * (len(field_b) // 4):
        raise ValueError(
            f"field cave @{field_b_at:#x} is not padding: {field_b_slot.hex()}"
        )
    miss_at = fs_open_miss_addr()
    miss = build_fs_open_miss(miss_at)
    miss_slot = bytes(data[miss_at : miss_at + len(miss)])
    if miss_slot != miss and miss_slot != nop() * (len(miss) // 4):
        raise ValueError(f"fs open miss cave @{miss_at:#x} is not padding: {miss_slot.hex()}")
    name_at = name_cave_addr()
    name = build_name_cave(name_at)
    name_hook = b_ins(ADDR_NAME, name_at)
    name_head = bytes(data[ADDR_NAME : ADDR_NAME + 4])
    if name_head != VANILLA_NAME and name_head != name_hook:
        raise ValueError(f"unexpected name walk at {ADDR_NAME:#x}: {name_head.hex()}")
    name_slot = bytes(data[name_at : name_at + len(name)])
    if name_slot != name and name_slot != nop() * (len(name) // 4):
        raise ValueError(f"name cave @{name_at:#x} is not padding: {name_slot.hex()}")
    menu_at = menu_vt_cave_addr()
    menu = build_menu_vt_cave(menu_at)
    menu_hook = b_ins(ADDR_MENU_VT, menu_at)
    menu_head = bytes(data[ADDR_MENU_VT : ADDR_MENU_VT + 4])
    if menu_head != VANILLA_MENU_VT and menu_head != menu_hook:
        raise ValueError(f"unexpected menu vt at {ADDR_MENU_VT:#x}: {menu_head.hex()}")
    menu_slot = bytes(data[menu_at : menu_at + len(menu)])
    if menu_slot != menu and menu_slot != nop() * (len(menu) // 4):
        raise ValueError(f"menu vt cave @{menu_at:#x} is not padding: {menu_slot.hex()}")
    idx = build_idx_load_cave()
    idx_hook = b_ins(ADDR_IDX_LOAD, ADDR_IDX_LOAD_CAVE)
    idx_head = bytes(data[ADDR_IDX_LOAD : ADDR_IDX_LOAD + 4])
    if idx_head != VANILLA_IDX_LOAD and idx_head != idx_hook:
        raise ValueError(f"unexpected idx load at {ADDR_IDX_LOAD:#x}: {idx_head.hex()}")
    idx_slot = bytes(data[ADDR_IDX_LOAD_CAVE : ADDR_IDX_LOAD_CAVE + len(idx)])
    # Three NOPs, then an unreferenced alignment word before the next function.
    idx_pad = nop() * 3 + bytes.fromhex("0c2f7c00")
    if idx_slot != idx and idx_slot != idx_pad:
        raise ValueError(f"idx load cave is not padding: {idx_slot.hex()}")
    node = build_node_byte_cave()
    node_hook = b_ins(ADDR_NODE_BYTE, ADDR_NODE_BYTE_CAVE)
    node_head = bytes(data[ADDR_NODE_BYTE : ADDR_NODE_BYTE + 4])
    if node_head != VANILLA_NODE_BYTE and node_head != node_hook:
        raise ValueError(f"unexpected node byte at {ADDR_NODE_BYTE:#x}: {node_head.hex()}")
    node_slot = bytes(data[ADDR_NODE_BYTE_CAVE : ADDR_NODE_BYTE_CAVE + len(node)])
    node_pad = nop() * 3 + bytes.fromhex("0c2f7c00")
    if node_slot != node and node_slot != nop() * (len(node) // 4) and node_slot != node_pad:
        raise ValueError(f"node byte cave is not padding: {node_slot.hex()}")
    if APPLY_HEAP_AND_PAK:
        raise ValueError("pane flag cave shares the heap link pad slot")
    pane = build_pane_flag_cave()
    pane_hook = b_cond(0, ADDR_PANE_FLAG_BR, ADDR_PANE_FLAG_CAVE)
    pane_head = bytes(data[ADDR_PANE_FLAG_BR : ADDR_PANE_FLAG_BR + 4])
    if pane_head != VANILLA_PANE_FLAG_BR and pane_head != pane_hook:
        raise ValueError(f"unexpected pane flag branch at {ADDR_PANE_FLAG_BR:#x}: {pane_head.hex()}")
    pane_slot = bytes(data[ADDR_PANE_FLAG_CAVE : ADDR_PANE_FLAG_CAVE + len(pane)])
    if pane_slot != pane and pane_slot != bytes(len(pane)):
        raise ValueError(f"pane flag cave is not padding: {pane_slot.hex()}")
    heap = build_heap_walk_cave()
    heap_hook = b_ins(ADDR_HEAP_WALK, ADDR_HEAP_WALK_CAVE)
    heap_head = bytes(data[ADDR_HEAP_WALK : ADDR_HEAP_WALK + 4])
    if heap_head != VANILLA_HEAP_WALK and heap_head != heap_hook:
        raise ValueError(f"unexpected heap walk at {ADDR_HEAP_WALK:#x}: {heap_head.hex()}")
    stub_at = heap_walk_stub_addr()
    stub = build_heap_walk_stub(stub_at)
    if stub_at != end:
        raise ValueError(f"heap walk stub @{stub_at:#x} is not the fixup slack")
    link_pad = build_heap_link_pad()
    link_hook = b_ins(ADDR_HEAP_LINK, ADDR_HEAP_LINK_PAD)
    link_head = bytes(data[ADDR_HEAP_LINK : ADDR_HEAP_LINK + 4])
    if link_head != VANILLA_HEAP_LINK and link_head != link_hook:
        raise ValueError(f"unexpected heap link at {ADDR_HEAP_LINK:#x}: {link_head.hex()}")
    link_body = build_heap_link_body()
    link_slot = bytes(data[ADDR_HEAP_LINK_BODY : ADDR_HEAP_LINK_BODY + len(link_body)])
    link_van = bytes.fromhex(
        "0c2080e50c2097e5080082e50c0087e5087080e5"
    )
    if link_slot != link_body and link_slot != link_van:
        raise ValueError(f"heap link body is not vanilla: {link_slot.hex()}")
    pad_slot = bytes(data[ADDR_HEAP_LINK_PAD : ADDR_HEAP_LINK_PAD + len(link_pad)])
    if pad_slot != link_pad and pad_slot != b"\x00" * len(link_pad):
        raise ValueError(f"heap link pad is not empty: {pad_slot.hex()}")
    heap_bin = build_heap_bin()
    heap_tail = build_heap_tail()
    split = heap_bin + heap_tail
    split_slot = bytes(data[ADDR_HEAP_BIN : ADDR_HEAP_TAIL_END])
    split_van = bytes.fromhex(
        "142097e5100082e5102097e5140082e5102097e5102080e5"
        "142097e5142080e5042097e5012042e0202042e2042080e5"
        "041087e50a0000ea0d00a0e1964700eb0d00a0e100f020e3"
        "0000a0e10700a0e1f880bde8"
    )
    if split_slot != split and split_slot != split_van:
        raise ValueError(f"heap split body is not vanilla: {split_slot.hex()}")
    for site in (ADDR_HEAP_EMPTY, ADDR_HEAP_NOFIT):
        word = bytes(data[site : site + 4])
        if word not in (
            b_cond(0, site, ADDR_HEAP_FAIL_OLD),
            b_cond(0, site, ADDR_HEAP_FAIL),
        ):
            raise ValueError(f"unexpected heap fail branch at {site:#x}: {word.hex()}")
    row_gate = build_row_gate()
    row_check = build_row_check()
    row_head = bytes(data[ADDR_ROW_CLEAR : ADDR_ROW_CLEAR + 4])
    if row_head != VANILLA_ROW_CLEAR and row_head != b_ins(ADDR_ROW_CLEAR, ADDR_ROW_GATE):
        raise ValueError(f"unexpected row clear at {ADDR_ROW_CLEAR:#x}: {row_head.hex()}")
    gate_slot = bytes(data[ADDR_ROW_GATE : ADDR_ROW_GATE + len(row_gate)])
    check_slot = bytes(data[ADDR_ROW_CHECK : ADDR_ROW_CHECK + len(row_check)])
    if gate_slot != row_gate and gate_slot != b"\x00" * len(row_gate):
        raise ValueError(f"row gate is not padding: {gate_slot.hex()}")
    if check_slot != row_check and check_slot != b"\x00" * len(row_check):
        raise ValueError(f"row check is not padding: {check_slot.hex()}")
    memset_cave = build_memset_cave()
    memset_stub = build_memset_stub()
    memset_head = bytes(data[ADDR_MEMSET : ADDR_MEMSET + 4])
    if memset_head != VANILLA_MEMSET and memset_head != b_ins(ADDR_MEMSET, ADDR_MEMSET_CAVE):
        raise ValueError(f"unexpected memset at {ADDR_MEMSET:#x}: {memset_head.hex()}")
    m_cave = bytes(data[ADDR_MEMSET_CAVE : ADDR_MEMSET_CAVE + len(memset_cave)])
    m_stub = bytes(data[ADDR_MEMSET_STUB : ADDR_MEMSET_STUB + len(memset_stub)])
    if m_cave != memset_cave and m_cave != b"\x00" * len(memset_cave):
        raise ValueError(f"memset cave is not padding: {m_cave.hex()}")
    if m_stub != memset_stub and m_stub != b"\x00" * len(memset_stub):
        raise ValueError(f"memset stub is not padding: {m_stub.hex()}")
    pak = build_pak_init()
    pak_slot = bytes(data[ADDR_PAK_INIT : ADDR_PAK_INIT + len(pak)])
    if pak_slot != pak and pak_slot != VANILLA_PAK_INIT:
        raise ValueError(f"unexpected pak init at {ADDR_PAK_INIT:#x}: {pak_slot.hex()}")
    # NOP the rest of each helper so a mid-function branch cannot reach ldrne.
    data[ADDR_DEREF : ADDR_DEREF + DEREF_LEN] = NOP * (DEREF_LEN // 4)
    data[ADDR_ADVANCE : ADDR_ADVANCE + ADVANCE_LEN] = NOP * (ADVANCE_LEN // 4)
    data[ADDR_DEREF : ADDR_DEREF + 4] = b_ins(ADDR_DEREF, labs["deref"])
    if APPLY_HEAP_AND_PAK:
        data[ADDR_HEAP_WALK_CAVE : ADDR_HEAP_WALK_CAVE + len(heap)] = heap
    data[ADDR_ADVANCE : ADDR_ADVANCE + 4] = b_ins(ADDR_ADVANCE, labs["advance"])
    data[ADDR_CHUNK_WALK_CAVE : ADDR_CHUNK_WALK_CAVE + len(blob)] = blob
    data[ADDR_FIXUP : ADDR_FIXUP + 4] = bl(ADDR_FIXUP, fixup_at)
    data[fixup_at:end] = fixup
    if end < ADDR_CHUNK_WALK_LIMIT:
        slack = ADDR_CHUNK_WALK_LIMIT - end
        data[end:ADDR_CHUNK_WALK_LIMIT] = NOP * (slack // 4)
    data[stub_at : stub_at + len(stub)] = stub
    if APPLY_HEAP_AND_PAK:
        data[ADDR_HEAP_WALK : ADDR_HEAP_WALK + 4] = heap_hook
        data[ADDR_HEAP_LINK_PAD : ADDR_HEAP_LINK_PAD + len(link_pad)] = link_pad
        data[ADDR_HEAP_LINK : ADDR_HEAP_LINK + 4] = link_hook
        data[ADDR_HEAP_LINK_BODY : ADDR_HEAP_LINK_BODY + len(link_body)] = link_body
        data[ADDR_HEAP_BIN : ADDR_HEAP_TAIL_END] = split
        data[ADDR_HEAP_EMPTY : ADDR_HEAP_EMPTY + 4] = b_cond(
            0, ADDR_HEAP_EMPTY, ADDR_HEAP_FAIL
        )
        data[ADDR_HEAP_NOFIT : ADDR_HEAP_NOFIT + 4] = b_cond(
            0, ADDR_HEAP_NOFIT, ADDR_HEAP_FAIL
        )
        data[ADDR_PAK_INIT : ADDR_PAK_INIT + len(pak)] = pak
    data[ADDR_ROW_GATE : ADDR_ROW_GATE + len(row_gate)] = row_gate
    data[ADDR_ROW_CHECK : ADDR_ROW_CHECK + len(row_check)] = row_check
    data[ADDR_ROW_CLEAR : ADDR_ROW_CLEAR + 4] = b_ins(ADDR_ROW_CLEAR, ADDR_ROW_GATE)
    data[ADDR_MEMSET_CAVE : ADDR_MEMSET_CAVE + len(memset_cave)] = memset_cave
    data[ADDR_MEMSET_STUB : ADDR_MEMSET_STUB + len(memset_stub)] = memset_stub
    data[ADDR_MEMSET : ADDR_MEMSET + 4] = b_ins(ADDR_MEMSET, ADDR_MEMSET_CAVE)
    # Advance NOP tail is written above; the title-bg cave replaces part of it.
    data[ADDR_TITLE_RELOC_CAVE : ADDR_TITLE_RELOC_CAVE + len(title)] = title
    data[ADDR_TITLE_RELOC : ADDR_TITLE_RELOC + 4] = title_hook
    data[ADDR_TITLE_INDEX_CAVE : ADDR_TITLE_INDEX_CAVE + len(index)] = index
    data[ADDR_TITLE_INDEX : ADDR_TITLE_INDEX + 4] = index_hook
    data[clyt_at : clyt_at + len(clyt)] = clyt
    data[ADDR_CLYT : ADDR_CLYT + 4] = clyt_hook
    data[lyt_at : lyt_at + len(lyt)] = lyt
    data[ADDR_LYT_HDR : ADDR_LYT_HDR + 4] = lyt_hook
    data[vt_at : vt_at + len(vt)] = vt
    data[ADDR_VT : ADDR_VT + 4] = vt_hook
    data[obj_at : obj_at + len(obj)] = obj
    data[ADDR_TITLE_OBJ : ADDR_TITLE_OBJ + 4] = obj_hook
    data[fs_at : fs_at + len(fs)] = fs
    data[ADDR_FS_OPEN : ADDR_FS_OPEN + 4] = fs_hook
    data[rel_at : rel_at + len(rel)] = rel
    data[ADDR_TEX_REL : ADDR_TEX_REL + 4] = rel_hook
    data[field_at : field_at + len(field)] = field
    data[ADDR_FIELD : ADDR_FIELD + 4] = field_hook
    data[field_b_at : field_b_at + len(field_b)] = field_b
    data[ADDR_FIELD_B : ADDR_FIELD_B + 4] = field_b_hook
    data[miss_at : miss_at + len(miss)] = miss
    data[name_at : name_at + len(name)] = name
    data[ADDR_NAME : ADDR_NAME + 4] = name_hook
    data[menu_at : menu_at + len(menu)] = menu
    data[ADDR_MENU_VT : ADDR_MENU_VT + 4] = menu_hook
    data[ADDR_IDX_LOAD_CAVE : ADDR_IDX_LOAD_CAVE + len(idx)] = idx
    data[ADDR_IDX_LOAD : ADDR_IDX_LOAD + 4] = idx_hook
    data[ADDR_NODE_BYTE_CAVE : ADDR_NODE_BYTE_CAVE + len(node)] = node
    data[ADDR_NODE_BYTE : ADDR_NODE_BYTE + 4] = node_hook
    data[ADDR_PANE_FLAG_CAVE : ADDR_PANE_FLAG_CAVE + len(pane)] = pane
    data[ADDR_PANE_FLAG_BR : ADDR_PANE_FLAG_BR + 4] = pane_hook
    print(
        f"[chunk-walk] deref @{ADDR_DEREF:#x} / advance @{ADDR_ADVANCE:#x} "
        f"-> @{ADDR_CHUNK_WALK_CAVE:#x} ({len(blob):#x}); "
        f"fixup @{ADDR_FIXUP:#x} -> @{fixup_at:#x} ({len(fixup):#x}); "
        f"title reloc @{ADDR_TITLE_RELOC:#x} -> @{ADDR_TITLE_RELOC_CAVE:#x} "
        f"({len(title):#x}); "
        f"title index @{ADDR_TITLE_INDEX:#x} -> @{ADDR_TITLE_INDEX_CAVE:#x} "
        f"({len(index):#x}); "
        f"clyt @{ADDR_CLYT:#x} -> @{clyt_at:#x} ({len(clyt):#x}); "
        f"layout hdr @{ADDR_LYT_HDR:#x} -> @{lyt_at:#x} ({len(lyt):#x}); "
        f"vt @{ADDR_VT:#x} -> @{vt_at:#x} ({len(vt):#x}); "
        f"title obj @{ADDR_TITLE_OBJ:#x} -> @{obj_at:#x} ({len(obj):#x}); "
        f"fs open @{ADDR_FS_OPEN:#x} -> @{fs_at:#x} ({len(fs):#x}); "
        f"tex release @{ADDR_TEX_REL:#x} -> @{rel_at:#x} ({len(rel):#x}); "
        f"field @{ADDR_FIELD:#x} -> @{field_at:#x} ({len(field):#x}); "
        f"field b @{ADDR_FIELD_B:#x} -> @{field_b_at:#x} ({len(field_b):#x}); "
        f"fs miss @{miss_at:#x} ({len(miss):#x}); "
        f"name @{ADDR_NAME:#x} -> @{name_at:#x} ({len(name):#x}); "
        f"menu vt @{ADDR_MENU_VT:#x} -> @{menu_at:#x} ({len(menu):#x}); "
        f"idx load @{ADDR_IDX_LOAD:#x} -> @{ADDR_IDX_LOAD_CAVE:#x} ({len(idx):#x}); "
        f"node byte @{ADDR_NODE_BYTE:#x} -> @{ADDR_NODE_BYTE_CAVE:#x} ({len(node):#x}); "
        f"pane flag @{ADDR_PANE_FLAG_BR:#x} -> @{ADDR_PANE_FLAG_CAVE:#x}; "
        f"heap/pak {'on' if APPLY_HEAP_AND_PAK else 'vanilla (boot)'} "
        f"walk @{ADDR_HEAP_WALK:#x} link @{ADDR_HEAP_LINK:#x} "
        f"pak @{ADDR_PAK_INIT:#x}"
    )
