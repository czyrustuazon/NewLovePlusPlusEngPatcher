"""Luma dump from a preexisting-save boot, before the girlfriend title.

2026-09-28 19:19, ``luma/dumps/arm11/crash_dump_00000001.dmp``. ARM11 data
abort (read, translation fault, section) in ``nlpp``. The faulting helper
is vanilla: it dereferences the second word of an 8-byte pair and the
caller compares that word to the ``IDX `` tag. Name-input must not rewrite
this window. This is not the CESA malloc smash at ``0x0010DE4C`` (FAR 3).
"""

from __future__ import annotations

import struct
from pathlib import Path

from conftest import ROOT

FIXTURE = ROOT / "tests" / "fixtures" / "luma_arm11_20260928_1919.dmp"
VA_BIAS = 0x100000

# Dump signature.
PC_VA = 0x0011566C
LR_VA = 0x0010C8FC
FAR = 0x6AC6FFF0
R2_PUPU = 0x55505550  # ASCII "PUPU"
DFSR_TRANSLATION_SECTION = 5
TITLE_ID = 0x00040000000F4E00

# Caller copies [r7+0x58] and dereferences the second word.
CALLER_BL_FILE = 0xC8F8
HELPER_FILE = 0x15664  # ldr r0, [r0, #4]; fault is the third insn
IDX_FILE = 0xCAF0
IDX_TAG = b"IDX "

# CESA idx-table heap smash (2026-09-14). Different site.
CESA_MALLOC_PC = 0x0010DE4C
CESA_MALLOC_FAR = 3


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def parse_luma_arm11(data: bytes) -> dict:
    """Luma exception dump v1.3, ARM11. Register order is r0–r12, sp, lr, pc, cpsr, dfsr, ifsr, far, fpexc."""
    magic0, magic1 = struct.unpack_from("<2I", data, 0)
    if (magic0, magic1) != (0xDEADC0DE, 0xDEADCAFE):
        raise ValueError(f"not a Luma dump: {magic0:#x} {magic1:#x}")
    version = _u32(data, 8)
    processor, core = struct.unpack_from("<HH", data, 12)
    exc_type = _u32(data, 16)
    total, regsz, codesz, stacksz, addsz = struct.unpack_from("<5I", data, 20)
    if 40 + regsz + codesz + stacksz + addsz != len(data) or total != len(data):
        raise ValueError("dump size does not match header")
    off = 40
    nreg = regsz // 4
    regs = struct.unpack_from("<" + "I" * nreg, data, off)
    off += regsz
    code = data[off : off + codesz]
    off += codesz + stacksz
    extra = data[off : off + addsz]
    return {
        "version": version,
        "processor": processor,
        "core": core,
        "type": exc_type,
        "regs": regs,
        "code": code,
        "process": extra[:8],
        "title_id": struct.unpack_from("<Q", extra, 8)[0] if len(extra) >= 16 else 0,
    }


def _code_window_file_off(pc_va: int, code: bytes, cpsr: int) -> int:
    """Luma copies ``code_size`` bytes ending at the faulting instruction."""
    thumb = (cpsr & 0x20) != 0
    start_va = pc_va + (2 if thumb else 4) - len(code)
    return start_va - VA_BIAS


def test_preexisting_save_boot_dump_is_idx_pointer_abort():
    dump = parse_luma_arm11(FIXTURE.read_bytes())
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 3)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID

    regs = dump["regs"]
    pc, lr, sp, cpsr, dfsr, far = regs[15], regs[14], regs[13], regs[16], regs[17], regs[19]
    assert (pc, lr, far) == (PC_VA, LR_VA, FAR)
    assert regs[0] == regs[1] == FAR
    assert regs[2] == R2_PUPU
    assert dfsr & 0xF == DFSR_TRANSLATION_SECTION
    assert (dfsr & (1 << 11)) == 0  # read, not write
    assert (cpsr & 0x20) == 0  # ARM, not Thumb
    assert pc != CESA_MALLOC_PC and far != CESA_MALLOC_FAR

    fault = _u32(dump["code"], len(dump["code"]) - 4)
    assert fault == 0x15900000  # ldrne r0, [r0]
    assert sp == 0x085E5D10


def test_fault_helper_matches_vanilla_code():
    """The dump's faulting ``ldrne`` is the vanilla helper. The caller still BL's it."""
    from nlpp_paths import find_vanilla_code

    vanilla_path = find_vanilla_code()
    if vanilla_path is None:
        return
    vanilla = vanilla_path.read_bytes()
    dump = parse_luma_arm11(FIXTURE.read_bytes())
    regs = dump["regs"]
    window_off = _code_window_file_off(regs[15], dump["code"], regs[16])
    assert vanilla[window_off : window_off + len(dump["code"])] == dump["code"]

    helper = vanilla[HELPER_FILE : HELPER_FILE + 16]
    assert helper == bytes.fromhex("040090e5000050e3000090151eff2fe1")
    bl = _u32(vanilla, CALLER_BL_FILE)
    assert (bl >> 24) == 0xEB
    imm = bl & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    assert (CALLER_BL_FILE + VA_BIAS + 8 + (imm << 2)) & 0xFFFFFFFF == HELPER_FILE + VA_BIAS
    assert vanilla[IDX_FILE : IDX_FILE + 4] == IDX_TAG


def _dec_imm12(imm12: int) -> int:
    imm8 = imm12 & 0xFF
    rot = ((imm12 >> 8) & 0xF) * 2
    if rot == 0:
        return imm8
    return ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF


def _run_cave(blob: bytes, base: int, entry: int, regs: dict[int, int], mem: dict[int, int]):
    """Execute the guard cave. A load missing from ``mem`` is the hardware abort."""
    pc = entry
    reads: list[int] = []
    for _ in range(64):
        if not base <= pc < base + len(blob):
            raise AssertionError(f"pc left cave: {pc:#x}")
        w = struct.unpack_from("<I", blob, pc - base)[0]
        cond = w >> 28
        z = regs.get("z", 0)
        c = regs.get("c", 0)
        take = {
            0: z == 1,
            2: c == 1,
            3: c == 0,
            0xE: True,
        }.get(cond)
        if take is None:
            raise AssertionError(f"unhandled cond {cond:#x} at {pc:#x}")
        if (w & 0x0FFFFFF0) == 0x012FFF10:  # bx lr — result is r0
            if take:
                if (w & 0xF) != 14:
                    raise AssertionError(f"bx r{w & 0xF} at {pc:#x}")
                return regs[0], reads
            pc += 4
            continue
        if not take:
            pc += 4
            continue
        op = (w >> 24) & 0xF
        if op in (0xA, 0xB):
            imm = w & 0xFFFFFF
            if imm & 0x800000:
                imm -= 0x1000000
            pc = (pc + 8 + (imm << 2)) & 0xFFFFFFFF
            if not base <= pc < base + len(blob):
                return ("leave", pc), reads
            continue
        if (w & 0xFFF00000) == 0xE4900000:  # ldr rd, [rn], #imm
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            addr = regs[rn]
            reads.append(addr)
            if addr not in mem:
                raise AssertionError(f"unmapped read {addr:#x}")
            regs[rd] = mem[addr]
            regs[rn] = (addr + (w & 0xFFF)) & 0xFFFFFFFF
            pc += 4
            continue
        if (w & 0x0F800000) == 0x05800000:  # ldr/str imm, pre, up
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            addr = (regs[rn] + (w & 0xFFF)) & 0xFFFFFFFF
            if (w >> 20) & 1:
                reads.append(addr)
                if addr not in mem:
                    raise AssertionError(f"unmapped read {addr:#x}")
                regs[rd] = mem[addr]
            else:
                mem[addr] = regs[rd]
            pc += 4
            continue
        if (w & 0x0FF0F000) == 0x03500000:  # cmp imm
            rn = (w >> 16) & 0xF
            imm = _dec_imm12(w & 0xFFF)
            val = regs[rn]
            regs["z"] = int(val == imm)
            regs["c"] = int(val >= imm)
            pc += 4
            continue
        if (w & 0x0FE00000) == 0x03A00000:  # mov imm
            regs[(w >> 12) & 0xF] = _dec_imm12(w & 0xFFF)
            pc += 4
            continue
        if (w & 0x0FE00000) == 0x02800000:  # add imm
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            regs[rd] = (regs[rn] + _dec_imm12(w & 0xFFF)) & 0xFFFFFFFF
            pc += 4
            continue
        if (w & 0x0FE00010) == 0x00800000:  # add reg
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            rm = w & 0xF
            regs[rd] = (regs[rn] + regs[rm]) & 0xFFFFFFFF
            pc += 4
            continue
        raise AssertionError(f"unhandled {w:#x} at {pc:#x}")
    raise AssertionError("cave did not return")


def test_chunk_walk_guard_stops_on_pupu_and_keeps_idx():
    """A ``PUPU`` size ends the walk. A heap node still returns its tag and advances."""
    from patch_chunk_walk_guard import (
        ADDR_ADVANCE,
        ADDR_DEREF,
        HEAP_LO,
        apply_patch,
        build_cave,
        is_patched,
    )
    from patch_input_cave_map import ADDR_CHUNK_WALK_CAVE, ADDR_CHUNK_WALK_LIMIT, TEXT_PAGE_END
    from patch_input_strcat_raw import ADDR as STRCAT_ADDR
    from patch_input_strcat_raw import SIZE as STRCAT_SIZE
    from patch_input_strcat_raw import apply_patch as apply_strcat
    from nlpp_paths import find_vanilla_code

    blob, labs = build_cave()
    assert ADDR_CHUNK_WALK_CAVE + len(blob) <= ADDR_CHUNK_WALK_LIMIT
    assert ADDR_CHUNK_WALK_LIMIT <= TEXT_PAGE_END
    assert STRCAT_ADDR + 4 <= ADDR_CHUNK_WALK_CAVE
    assert ADDR_CHUNK_WALK_LIMIT == STRCAT_ADDR + STRCAT_SIZE

    pair = 0x08700000
    node = 0x1575C298
    idx = struct.unpack("<I", b"IDX ")[0]
    mem = {
        pair + 4: node,
        node: idx,
        node + 4: 0x20,
    }
    tag, reads = _run_cave(blob, ADDR_CHUNK_WALK_CAVE, labs["deref"], {0: pair}, dict(mem))
    assert tag == idx
    assert node in reads

    bad = 0x6AC617F0
    mem_bad = {pair + 4: bad}
    tag, reads = _run_cave(blob, ADDR_CHUNK_WALK_CAVE, labs["deref"], {0: pair}, dict(mem_bad))
    assert tag == 0
    assert bad not in reads

    tag, _ = _run_cave(
        blob, ADDR_CHUNK_WALK_CAVE, labs["deref"], {0: pair}, {pair + 4: 0}
    )
    assert tag == 0

    mem_adv = {pair + 4: node, node: 1, node + 4: 0x20}
    ret, reads = _run_cave(
        blob, ADDR_CHUNK_WALK_CAVE, labs["advance"], {0: pair}, mem_adv
    )
    assert ret == 1
    assert mem_adv[pair + 4] == (node + 8 + 0x20) & 0xFFFFFFFF
    assert HEAP_LO <= mem_adv[pair + 4] < 0x20000000

    mem_pupu = {pair + 4: node, node: 1, node + 4: R2_PUPU}
    ret, reads = _run_cave(
        blob, ADDR_CHUNK_WALK_CAVE, labs["advance"], {0: pair}, dict(mem_pupu)
    )
    assert ret == 0
    assert mem_pupu[pair + 4] == node
    assert all(addr != node + 8 + R2_PUPU for addr in reads)

    vanilla_path = find_vanilla_code()
    if vanilla_path is None:
        return
    from patch_code import apply_name_pane_patches

    data = bytearray(vanilla_path.read_bytes())
    apply_name_pane_patches(data)
    apply_strcat(data)
    apply_patch(data)
    assert is_patched(data)
    assert data[ADDR_DEREF + 8 : ADDR_DEREF + 12] != bytes.fromhex("00009015")
    assert data[IDX_FILE : IDX_FILE + 4] == IDX_TAG
    assert data[CALLER_BL_FILE : CALLER_BL_FILE + 4] == vanilla_path.read_bytes()[
        CALLER_BL_FILE : CALLER_BL_FILE + 4
    ]


def test_blob_fixup_skips_pupu_offset():
    """object + ``PUPU`` is the second abort (``ldr r2, [r0]`` at ``0x129824``)."""
    from patch_chunk_walk_guard import (
        ADDR_FIXUP_SKIP,
        build_fixup_cave,
        fixup_cave_addr,
    )

    base = fixup_cave_addr()
    blob = build_fixup_cave(base)
    obj = 0x156F9A00
    good, _ = _run_cave(blob, base, base, {0: obj, 1: 0x20, 4: obj}, {})
    assert good == (obj + 0x20) & 0xFFFFFFFF

    mem = {obj + 8: R2_PUPU}
    left, _ = _run_cave(
        blob, base, base, {0: obj, 1: R2_PUPU, 4: obj}, mem
    )
    assert left == ("leave", ADDR_FIXUP_SKIP)
    assert mem[obj + 8] == 0


def test_title_bg_reloc_skips_unmapped_sum():
    """object + [object+0x10] at ``0x2Axxxxxx`` is the third abort (``ldr r3, [r2, #8]``)."""
    from patch_chunk_walk_guard import (
        ADDR_TITLE_RELOC_CAVE,
        ADDR_TITLE_RELOC_RESUME,
        build_title_reloc_cave,
    )

    blob = build_title_reloc_cave()
    r2 = 0x15700000
    dest = 0x08002000
    mem = {r2 + 8: 0x10, dest + 4: r2}
    left, reads = _run_cave(blob, ADDR_TITLE_RELOC_CAVE, ADDR_TITLE_RELOC_CAVE, {1: dest, 2: r2}, mem)
    assert left == ("leave", ADDR_TITLE_RELOC_RESUME)
    assert r2 + 8 in reads

    bad = 0x2AE0E59C
    mem_bad = {dest + 4: bad}
    ret, reads = _run_cave(
        blob, ADDR_TITLE_RELOC_CAVE, ADDR_TITLE_RELOC_CAVE, {1: dest, 2: bad}, mem_bad
    )
    assert ret == 0
    assert bad + 8 not in reads
    assert mem_bad[dest + 4] == 0


def test_title_index_skips_null_table():
    """The reloc's cleared pointer is indexed at ``0x642D48`` (FAR 0)."""
    from patch_chunk_walk_guard import (
        ADDR_TITLE_INDEX_CAVE,
        ADDR_TITLE_INDEX_FAIL,
        build_title_index_cave,
    )

    blob = build_title_index_cave()
    ret, reads = _run_cave(
        blob, ADDR_TITLE_INDEX_CAVE, ADDR_TITLE_INDEX_CAVE, {1: 0, 2: 0}, {}
    )
    assert ret == ("leave", ADDR_TITLE_INDEX_FAIL)
    assert reads == []

    ret, reads = _run_cave(
        blob,
        ADDR_TITLE_INDEX_CAVE,
        ADDR_TITLE_INDEX_CAVE,
        {1: 0x2AE0E59C, 2: 0},
        {},
    )
    assert ret == ("leave", ADDR_TITLE_INDEX_FAIL)
    assert 0x2AE0E59C not in reads


def test_clyt_header_skips_null_blob():
    """A null layout pointer faults in the CLYT magic load at ``0x641CE4``."""
    from patch_chunk_walk_guard import ADDR_CLYT_RESUME, build_clyt_cave, clyt_cave_addr

    base = clyt_cave_addr()
    blob = build_clyt_cave(base)
    sp = 0x08001000
    saved = 0x080013F0
    ret, reads = _run_cave(
        blob, base, base, {0: 0, 4: 0, 13: sp}, {sp: saved}
    )
    assert ret == 0
    assert 0 not in reads

    blob_addr = 0x15705380
    magic = struct.unpack("<I", b"CLYT")[0]
    left, reads = _run_cave(
        blob, base, base, {0: blob_addr, 13: sp}, {blob_addr: magic, sp: saved}
    )
    assert left == ("leave", ADDR_CLYT_RESUME)
    assert blob_addr in reads


def test_layout_header_skips_null_halfword():
    """The same null blob is read at ``+6`` (FAR 6, ``ldrh r1, [r6, #6]``)."""
    from patch_chunk_walk_guard import (
        ADDR_LYT_HDR_FAIL,
        build_lyt_hdr_cave,
        lyt_hdr_cave_addr,
    )

    base = lyt_hdr_cave_addr()
    blob = build_lyt_hdr_cave(base)
    ret, reads = _run_cave(blob, base, base, {6: 0}, {})
    assert ret == ("leave", ADDR_LYT_HDR_FAIL)
    assert 6 not in reads


def test_virtual_call_skips_null_object():
    """``ldr r2, [r0]`` at ``0x377FB4`` faults when the object word is null."""
    from patch_chunk_walk_guard import ADDR_VT_FAIL, build_vt_cave, vt_cave_addr

    base = vt_cave_addr()
    blob = build_vt_cave(base)
    ret, reads = _run_cave(blob, base, base, {0: 0}, {})
    assert ret == ("leave", ADDR_VT_FAIL)
    assert reads == []


def test_title_object_pointer_stops_before_the_field_load():
    """The reloc source itself is ``0x6Axxxxxx`` (``ldr r2, [r0, #0x10]``)."""
    from patch_chunk_walk_guard import build_title_obj_cave, title_obj_cave_addr

    base = title_obj_cave_addr()
    blob = build_title_obj_cave(base)
    bad = 0x6ABFB5D0
    ret, reads = _run_cave(blob, base, base, {0: bad, 1: 0x080013F0}, {})
    assert ret == 0
    assert bad + 0x10 not in reads
