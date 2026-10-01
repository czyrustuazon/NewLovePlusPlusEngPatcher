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
    cmp_imm,
    cmp_reg,
    ldr_imm,
    mov_imm,
    str_imm,
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
    # NOP the rest of each helper so a mid-function branch cannot reach ldrne.
    data[ADDR_DEREF : ADDR_DEREF + DEREF_LEN] = NOP * (DEREF_LEN // 4)
    data[ADDR_ADVANCE : ADDR_ADVANCE + ADVANCE_LEN] = NOP * (ADVANCE_LEN // 4)
    data[ADDR_DEREF : ADDR_DEREF + 4] = b_ins(ADDR_DEREF, labs["deref"])
    data[ADDR_ADVANCE : ADDR_ADVANCE + 4] = b_ins(ADDR_ADVANCE, labs["advance"])
    data[ADDR_CHUNK_WALK_CAVE : ADDR_CHUNK_WALK_CAVE + len(blob)] = blob
    data[ADDR_FIXUP : ADDR_FIXUP + 4] = bl(ADDR_FIXUP, fixup_at)
    data[fixup_at:end] = fixup
    if end < ADDR_CHUNK_WALK_LIMIT:
        slack = ADDR_CHUNK_WALK_LIMIT - end
        data[end:ADDR_CHUNK_WALK_LIMIT] = NOP * (slack // 4)
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
        f"name @{ADDR_NAME:#x} -> @{name_at:#x} ({len(name):#x})"
    )
