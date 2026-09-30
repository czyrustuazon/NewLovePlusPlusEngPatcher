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

The caves sit in the dead tail of ``FUN_002573ac`` (strcat-raw branches away
at the first instruction) so they stay in ``.text`` RX. Apply strcat-raw first.
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
    ldr_imm,
    mov_imm,
    str_imm,
)
from patch_code import ADDR_CLEAR, SIZE_CLEAR
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
        f"title obj @{ADDR_TITLE_OBJ:#x} -> @{obj_at:#x} ({len(obj):#x})"
    )
