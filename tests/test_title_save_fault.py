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

    def load(addr: int) -> int:
        if base <= addr < base + len(blob) and ((addr - base) & 3) == 0:
            return struct.unpack_from("<I", blob, addr - base)[0]
        if addr not in mem:
            raise AssertionError(f"unmapped read {addr:#x}")
        return mem[addr]

    for _ in range(256):
        if not base <= pc < base + len(blob):
            raise AssertionError(f"pc left cave: {pc:#x}")
        w = struct.unpack_from("<I", blob, pc - base)[0]
        cond = w >> 28
        z = regs.get("z", 0)
        c = regs.get("c", 0)
        take = {
            0: z == 1,
            1: z == 0,  # ne
            2: c == 1,
            3: c == 0,
            8: c == 1 and z == 0,  # hi
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
            regs[rd] = load(addr)
            regs[rn] = (addr + (w & 0xFFF)) & 0xFFFFFFFF
            pc += 4
            continue
        if (w & 0x0F800000) == 0x05800000:  # ldr/str imm, pre, up
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            imm = w & 0xFFF
            addr = ((pc + 8) if rn == 15 else regs[rn]) + imm
            addr &= 0xFFFFFFFF
            if (w >> 20) & 1:
                reads.append(addr)
                regs[rd] = load(addr)
            else:
                mem[addr] = regs[rd]
            pc += 4
            continue
        if (w & 0x0F800000) == 0x05000000:  # ldr/str imm, pre, down
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            addr = (regs[rn] - (w & 0xFFF)) & 0xFFFFFFFF
            if (w >> 20) & 1:
                reads.append(addr)
                regs[rd] = load(addr)
            else:
                mem[addr] = regs[rd]
            pc += 4
            continue
        if (w & 0x0FF0F000) == 0x01500000 and (w & 0xFF0) == 0:  # cmp reg
            rn = (w >> 16) & 0xF
            rm = w & 0xF
            regs["z"] = int(regs[rn] == regs[rm])
            regs["c"] = int(regs[rn] >= regs[rm])
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
        if (w & 0x0FE00000) == 0x02400000:  # sub imm
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            regs[rd] = (regs[rn] - _dec_imm12(w & 0xFFF)) & 0xFFFFFFFF
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
        if (w & 0x0FF00000) == 0x05D00000:  # ldrb rd, [rn, #imm]
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            addr = (regs[rn] + (w & 0xFFF)) & 0xFFFFFFFF
            reads.append(addr)
            regs[rd] = load(addr) & 0xFF
            pc += 4
            continue
        if (w & 0x0FF00FF0) == 0x07900000 and (w & 0xF0) == 0:
            # ldr rd, [rn, rm]
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            rm = w & 0xF
            addr = (regs[rn] + regs[rm]) & 0xFFFFFFFF
            reads.append(addr)
            regs[rd] = load(addr)
            pc += 4
            continue
        if (w & 0x0FFFFFFF) == 0x08BD8010:  # pop {r4, pc}
            sp = regs[13]
            reads.append(sp)
            regs[4] = load(sp)
            reads.append(sp + 4)
            regs[15] = load(sp + 4)
            regs[13] = (sp + 8) & 0xFFFFFFFF
            return ("leave", regs[15]), reads
        if (w & 0x0E500FF0) == 0x005000B0:  # ldrh rd, [rn]  (imm12 == 0)
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            addr = regs[rn]
            reads.append(addr)
            regs[rd] = load(addr) & 0xFFFF
            pc += 4
            continue
        if (w & 0x0FFF0FF0) == 0x01A00000:  # mov rd, rm
            regs[(w >> 12) & 0xF] = regs[w & 0xF]
            pc += 4
            continue
        if (w & 0x0FF00000) == 0x08800000:  # stm rn, {list}
            addr = regs[(w >> 16) & 0xF]
            for reg in range(16):
                if w & (1 << reg):
                    mem[addr] = regs[reg]
                    addr = (addr + 4) & 0xFFFFFFFF
            pc += 4
            continue
        if (w & 0x0FE00010) == 0x01800000 and ((w >> 5) & 3) == 0:  # orr rd, rn, rm, lsl #sh
            rd = (w >> 12) & 0xF
            rn = (w >> 16) & 0xF
            sh = (w >> 7) & 0x1F
            regs[rd] = (regs[rn] | ((regs[w & 0xF] << sh) & 0xFFFFFFFF)) & 0xFFFFFFFF
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


def test_fs_open_skips_null_handle_pointer():
    """A null fs:USER pointer with a real .text return skips the load."""
    from patch_chunk_walk_guard import build_fs_open_cave, fs_open_cave_addr

    base = fs_open_cave_addr()
    blob = build_fs_open_cave(base)
    sp = 0x08550BC4
    mem = {sp + 0x34: 0x006EB888}
    ret, reads = _run_cave(blob, base, base, {0: 0, 13: sp}, mem)
    assert ret == 0
    assert sp + 0x34 in reads
    assert 0 not in reads

    handle = 0x08001250
    session = 0x00012A00
    caller = 0x006EB888
    ret, reads = _run_cave(
        blob, base, base, {0: handle, 13: sp}, {handle: session, sp + 0x34: caller}
    )
    assert ret == session
    assert reads == [handle, sp + 0x34]


def test_fs_open_unwinds_when_the_handle_word_is_zero():
    """A valid pointer holding handle 0 still must not return to address 0."""
    from patch_chunk_walk_guard import (
        ADDR_TEX_BIND_FAIL,
        ADDR_TEX_BIND_RET,
        build_fs_open_cave,
        fs_open_cave_addr,
    )

    base = fs_open_cave_addr()
    blob = build_fs_open_cave(base)
    sp = 0x08550B8C
    handle = 0x08000F50
    obj = 0x08001310
    mem = {sp + off: 0 for off in range(0x38, 0x74, 4)}
    mem[handle] = 0
    mem[sp + 0x34] = 0
    mem[sp + 0x64] = obj
    mem[sp + 0x70] = ADDR_TEX_BIND_RET
    regs = {0: handle, 13: sp}
    ret, reads = _run_cave(blob, base, base, regs, mem)
    assert ret == ("leave", ADDR_TEX_BIND_FAIL)
    assert regs[4] == obj
    assert regs[13] == sp + 0x74
    assert reads[0] == handle


def test_fs_open_unwinds_layout_return():
    """Saved LR ``mat1`` is the layout. Resume the texture-bind failure path."""
    from patch_chunk_walk_guard import (
        ADDR_TEX_BIND_FAIL,
        ADDR_TEX_BIND_RET,
        build_fs_open_cave,
        fs_open_cave_addr,
    )

    base = fs_open_cave_addr()
    blob = build_fs_open_cave(base)
    sp = 0x08550BC4
    obj = 0x08001250
    mem = {sp + off: 0 for off in range(0x38, 0x74, 4)}
    mem[sp + 0x34] = 0x15B76308  # mat1, outside .text
    mem[sp + 0x64] = obj
    mem[sp + 0x70] = ADDR_TEX_BIND_RET
    regs = {0: 0, 13: sp}
    ret, reads = _run_cave(blob, base, base, regs, mem)
    assert ret == ("leave", ADDR_TEX_BIND_FAIL)
    assert regs[4] == obj
    assert regs[13] == sp + 0x74
    assert 0 not in reads


def test_fs_open_resumes_the_layout_constructor():
    """No texture-bind frame. Popping the saved return would execute address 0."""
    from patch_chunk_walk_guard import (
        ADDR_LYT_CTOR_FAIL,
        ADDR_LYT_CTOR_RET,
        build_fs_open_cave,
        build_fs_open_miss,
        fs_open_cave_addr,
        fs_open_miss_addr,
    )

    base = fs_open_cave_addr()
    blob = build_fs_open_cave(base)
    sp = 0x0855031C - 0x38
    mem = {sp + off: 0 for off in range(0x34, 0x38 + 0x80, 4)}
    mem[sp + 0x34] = 0
    mem[sp + 0x38 + 0x60] = ADDR_LYT_CTOR_RET
    regs = {0: 0, 13: sp}
    ret, _reads = _run_cave(blob, base, base, regs, mem)
    miss = fs_open_miss_addr()
    assert ret == ("leave", miss)

    miss_blob = build_fs_open_miss(miss)
    ret, _reads = _run_cave(miss_blob, miss, miss, regs, mem)
    assert ret == ("leave", ADDR_LYT_CTOR_FAIL)
    assert regs[13] == sp + 0x38 + 0x64


def test_tex_release_skips_null_list():
    """Luma 2026-10-01 02:57: ``ldr r5, [r0, #8]`` with r0 = 0 (FAR 8)."""
    from patch_chunk_walk_guard import (
        ADDR_TEX_REL_FAIL,
        ADDR_TEX_REL_RESUME,
        build_tex_release_cave,
        tex_release_cave_addr,
    )

    base = tex_release_cave_addr()
    blob = build_tex_release_cave(base)
    ret, reads = _run_cave(blob, base, base, {0: 0, 7: 0}, {})
    assert ret == ("leave", ADDR_TEX_REL_FAIL)
    assert reads == []

    obj = 0x08001250
    ret, reads = _run_cave(blob, base, base, {0: obj, 7: 0}, {obj + 8: 0})
    assert ret == ("leave", ADDR_TEX_REL_FAIL)
    assert reads == [obj + 8]

    inner = 0x08002000
    ret, reads = _run_cave(blob, base, base, {0: obj, 7: 0}, {obj + 8: inner})
    assert ret == ("leave", ADDR_TEX_REL_RESUME)
    assert reads == [obj + 8]


def test_field_getter_skips_null_object():
    """Index 0 on a null pane object must not load ``[r0, #0x60]``."""
    from patch_chunk_walk_guard import (
        ADDR_FIELD_FAIL,
        ADDR_FIELD_RESUME,
        build_field_cave,
        field_cave_addr,
    )

    base = field_cave_addr()
    blob = build_field_cave(base)
    ret, reads = _run_cave(blob, base, base, {0: 0, 1: 0}, {})
    assert ret == ("leave", ADDR_FIELD_FAIL)
    assert reads == []

    obj = 0x08648830
    ret, reads = _run_cave(blob, base, base, {0: obj, 1: 0}, {})
    assert ret == ("leave", ADDR_FIELD_RESUME)
    assert reads == []


def test_field_getter_twin_skips_null_object():
    """The second copy is what the caller uses for ``r5``."""
    from patch_chunk_walk_guard import (
        ADDR_FIELD_B_FAIL,
        ADDR_FIELD_B_RESUME,
        build_field_cave,
        field_b_cave_addr,
    )

    base = field_b_cave_addr()
    blob = build_field_cave(base, resume=ADDR_FIELD_B_RESUME, fail=ADDR_FIELD_B_FAIL)
    ret, reads = _run_cave(blob, base, base, {0: 0, 1: 0}, {})
    assert ret == ("leave", ADDR_FIELD_B_FAIL)
    assert reads == []

    obj = 0x08648830
    ret, reads = _run_cave(blob, base, base, {0: obj, 1: 0}, {})
    assert ret == ("leave", ADDR_FIELD_B_RESUME)
    assert reads == []


def test_oct1_boot_dump_is_null_fs_open():
    """Before the title screen: OpenFileDirectly dereferences a null handle pointer."""
    dump = parse_luma_arm11(
        (ROOT / "tests" / "fixtures" / "luma_arm11_20261001_0118.dmp").read_bytes()
    )
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 3)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID
    regs = dump["regs"]
    assert regs[15] == 0x0012381C
    assert regs[0] == 0
    assert regs[19] == 0  # FAR
    assert regs[17] & 0xF == DFSR_TRANSLATION_SECTION
    assert (regs[16] & 0x20) == 0
    fault = _u32(dump["code"], len(dump["code"]) - 4)
    assert fault == 0xE5900000  # ldr r0, [r0]


def test_oct1_second_dump_returns_into_the_layout():
    """Handle 0 popped PC into the BCLYT ``mat1`` section (prefetch, XN)."""
    dump = parse_luma_arm11(
        (ROOT / "tests" / "fixtures" / "luma_arm11_20261001_0225.dmp").read_bytes()
    )
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 2)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID
    regs = dump["regs"]
    assert regs[15] == 0x15B76308
    assert regs[0] == 0xD8E007F7
    assert regs[14] == 0x00123820
    assert regs[18] & 0xF == 0xD  # IFSR permission, section
    assert (regs[16] & 0x20) == 0
    fault = _u32(dump["code"], len(dump["code"]) - 4)
    assert fault == 0x3174616D  # 'mat1'


def test_oct1_third_dump_is_null_texture_release():
    """After the file-open unwind: texture release loads ``[r0, #8]`` and r0 is 0."""
    dump = parse_luma_arm11(
        (ROOT / "tests" / "fixtures" / "luma_arm11_20261001_0257.dmp").read_bytes()
    )
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 3)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID
    regs = dump["regs"]
    assert regs[15] == 0x006E96DC
    assert regs[0] == 0
    assert regs[14] == 0x006C60D4
    assert regs[19] == 8  # FAR
    assert regs[17] & 0xF == DFSR_TRANSLATION_SECTION
    assert (regs[16] & 0x20) == 0
    fault = _u32(dump["code"], len(dump["code"]) - 4)
    assert fault == 0xE5905008  # ldr r5, [r0, #8]


def test_oct1_fourth_dump_prefetches_address_zero():
    """Title music is up. OpenFileDirectly returns to a saved LR of 0."""
    dump = parse_luma_arm11(
        (ROOT / "tests" / "fixtures" / "luma_arm11_20261001_0316.dmp").read_bytes()
    )
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 2)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID
    regs = dump["regs"]
    assert regs[15] == 0
    assert regs[0] == 0xD8E007F7
    assert regs[14] == 0x00123820
    assert regs[10] == 0x316C7874  # txl1
    assert regs[18] & 0xF == DFSR_TRANSLATION_SECTION
    assert (regs[16] & 0x20) == 0


def test_oct1_fifth_dump_is_null_pane_field():
    """Pane field getter loads ``[r0, #0x60]`` and the object is null."""
    dump = parse_luma_arm11(
        (ROOT / "tests" / "fixtures" / "luma_arm11_20261001_1750.dmp").read_bytes()
    )
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 3)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID
    regs = dump["regs"]
    assert regs[15] == 0x00291888
    assert regs[0] == 0
    assert regs[1] == 0
    assert regs[14] == 0x0022B640
    assert regs[19] == 0x60
    assert regs[17] & 0xF == DFSR_TRANSLATION_SECTION
    assert (regs[16] & 0x20) == 0
    fault = _u32(dump["code"], len(dump["code"]) - 4)
    assert fault == 0x05900060  # ldreq r0, [r0, #0x60]


def test_oct1_sixth_dump_is_null_pane_field_twin():
    """The twin getter loads ``[r0, #0x60]`` for the second lookup result."""
    dump = parse_luma_arm11(
        (ROOT / "tests" / "fixtures" / "luma_arm11_20261001_1758.dmp").read_bytes()
    )
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 3)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID
    regs = dump["regs"]
    assert regs[15] == 0x002920BC
    assert regs[0] == 0
    assert regs[1] == 0
    assert regs[14] == 0x0022B650
    assert regs[19] == 0x60
    assert regs[17] & 0xF == DFSR_TRANSLATION_SECTION
    assert (regs[16] & 0x20) == 0
    fault = _u32(dump["code"], len(dump["code"]) - 4)
    assert fault == 0x05900060


def test_oct1_seventh_dump_prefetches_address_zero():
    """Title bg open. Saved return is 0 and the bind frame is gone."""
    dump = parse_luma_arm11(
        (ROOT / "tests" / "fixtures" / "luma_arm11_20261001_1804.dmp").read_bytes()
    )
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 2)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID
    regs = dump["regs"]
    assert regs[15] == 0
    assert regs[0] == 0xD8E007F7
    assert regs[14] == 0x00123820
    assert regs[10] == 0x316C7874
    assert regs[18] & 0xF == DFSR_TRANSLATION_SECTION
    assert (regs[16] & 0x20) == 0


def test_oct1_eighth_dump_is_name_offset_past_the_file():
    """Directory entry offset 0x746954 plus the string base is unmapped."""
    dump = parse_luma_arm11(
        (ROOT / "tests" / "fixtures" / "luma_arm11_20261001_1836.dmp").read_bytes()
    )
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 3)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID
    regs = dump["regs"]
    assert regs[15] == 0x00644D78
    assert regs[14] == 0x002FD740
    assert regs[0] == 0x00746954
    assert regs[1] == 0x1594A9A4
    assert regs[4] == 0x160912F8
    assert regs[19] == 0x160912F8
    assert regs[17] & 0xF == DFSR_TRANSLATION_SECTION
    assert (regs[16] & 0x20) == 0
    fault = _u32(dump["code"], len(dump["code"]) - 4)
    assert fault == 0xE1D400B0  # ldrh r0, [r4]


def test_name_walk_skips_an_offset_past_the_file():
    """A name offset of 1 MiB or more returns -1 without the halfword load."""
    from patch_chunk_walk_guard import (
        ADDR_NAME_FAIL,
        ADDR_NAME_RESUME,
        build_name_cave,
        name_cave_addr,
    )

    base = name_cave_addr()
    blob = build_name_cave(base)
    wild = 0x160912F8
    ret, reads = _run_cave(blob, base, base, {0: 0x00746954, 4: wild}, {})
    assert ret == ("leave", ADDR_NAME_FAIL)
    assert wild not in reads

    name = 0x1594A9C4
    ret, reads = _run_cave(blob, base, base, {0: 0x20, 4: name}, {name: 0x62})
    assert ret == ("leave", ADDR_NAME_RESUME)
    assert reads == [name]


def test_oct1_ninth_dump_is_null_menu_vtable():
    """The first lookup result is null and the virtual call loads ``[r0]``."""
    dump = parse_luma_arm11(
        (ROOT / "tests" / "fixtures" / "luma_arm11_20261001_1958.dmp").read_bytes()
    )
    assert dump["version"] == (1 << 16) | 3
    assert (dump["processor"], dump["core"], dump["type"]) == (11, 0, 3)
    assert dump["process"].startswith(b"nlpp")
    assert dump["title_id"] == TITLE_ID
    regs = dump["regs"]
    assert regs[15] == 0x002EEDA8
    assert regs[0] == 0
    assert regs[4] == 0
    assert regs[14] == 0x003C604C
    assert regs[19] == 0
    assert regs[17] & 0xF == DFSR_TRANSLATION_SECTION
    assert (regs[16] & 0x20) == 0
    fault = _u32(dump["code"], len(dump["code"]) - 4)
    assert fault == 0xE5900000  # ldr r0, [r0]


def test_menu_vt_returns_when_the_object_is_null():
    """A null object pops the frame. A real object still loads the vtable."""
    from patch_chunk_walk_guard import ADDR_MENU_VT_RESUME, build_menu_vt_cave, menu_vt_cave_addr

    base = menu_vt_cave_addr()
    blob = build_menu_vt_cave(base)
    sp = 0x08001000
    ret, reads = _run_cave(
        blob, base, base, {0: 0, 13: sp}, {sp: 0, sp + 4: 0x003C604C}
    )
    assert ret == ("leave", 0x003C604C)
    assert reads == [sp, sp + 4]

    obj = 0x08690250
    ret, reads = _run_cave(
        blob, base, base, {0: obj, 13: sp}, {obj: 0x00100000, sp: 0, sp + 4: 0x003C604C}
    )
    assert ret == ("leave", ADDR_MENU_VT_RESUME)
    assert reads == [obj]


def test_idx_load_skips_the_fourcc_base():
    """``r2`` equal to the IDX tag must not be added to the heap pointer."""
    from patch_chunk_walk_guard import (
        ADDR_IDX_LOAD_FAIL,
        ADDR_IDX_LOAD_RESUME,
        build_idx_load_cave,
    )

    blob = build_idx_load_cave()
    base = 0x00190100
    table = 0x1574E4E0
    idx = 0x20584449
    ret, reads = _run_cave(blob, base, base, {1: table, 2: idx}, {})
    assert ret == ("leave", ADDR_IDX_LOAD_FAIL)
    assert reads == []

    low = 0x0110E113
    ret, reads = _run_cave(blob, base, base, {1: table, 2: low}, {})
    assert ret == ("leave", ADDR_IDX_LOAD_FAIL)
    assert reads == []

    ret, reads = _run_cave(blob, base, base, {1: table, 2: 0}, {table: 0x20})
    assert ret == ("leave", ADDR_IDX_LOAD_RESUME)
    assert reads == [table]

    slot = table + 0x20
    ret, reads = _run_cave(blob, base, base, {1: table, 2: 0x20}, {slot: 0x11})
    assert ret == ("leave", ADDR_IDX_LOAD_RESUME)
    assert reads == [slot]


def test_node_byte_skips_an_unmapped_sum():
    """``sl`` at ``0x56AF97CF`` must not be read at ``+0x14``."""
    from patch_chunk_walk_guard import (
        ADDR_IDX_LOAD_FAIL,
        ADDR_NODE_BYTE_RESUME,
        build_node_byte_cave,
    )

    blob = build_node_byte_cave()
    base = 0x00190350
    wild = 0x56AF97CF
    ret, reads = _run_cave(blob, base, base, {10: wild}, {})
    assert ret == ("leave", ADDR_IDX_LOAD_FAIL)
    assert wild + 0x14 not in reads

    node = 0x1573F550
    ret, reads = _run_cave(blob, base, base, {10: node}, {node + 0x14: 3})
    assert ret == ("leave", ADDR_NODE_BYTE_RESUME)
    assert reads == [node + 0x14]


def test_heap_walk_stops_on_pupu():
    """A free-list node of ``PUPU`` must not be read at ``+4``."""
    from patch_chunk_walk_guard import (
        ADDR_HEAP_WALK_CAVE,
        ADDR_HEAP_WALK_FAIL,
        ADDR_HEAP_WALK_RESUME,
        build_heap_walk_cave,
        build_heap_walk_stub,
        heap_walk_stub_addr,
    )

    base = ADDR_HEAP_WALK_CAVE
    blob = build_heap_walk_cave(base)
    stub_at = heap_walk_stub_addr()
    stub = build_heap_walk_stub(stub_at)
    pupu = 0x55505550
    ret, reads = _run_cave(blob, base, base, {0: pupu}, {})
    assert ret == ("leave", ADDR_HEAP_WALK_FAIL)
    assert reads == []

    node = 0x14826480
    ret, reads = _run_cave(blob, base, base, {0: node}, {})
    assert ret == ("leave", stub_at)
    assert reads == []
    ret, reads = _run_cave(stub, stub_at, stub_at, {0: node}, {node + 4: 0x80})
    assert ret == ("leave", ADDR_HEAP_WALK_RESUME)
    assert reads == [node + 4]


def _run_fallthrough(blob: bytes, base: int, regs: dict[int, int], mem: dict[int, int]):
    """Run a cave that continues into the next instruction instead of branching."""
    try:
        _run_cave(blob, base, base, regs, mem)
    except AssertionError as exc:
        text = str(exc)
        if not text.startswith("pc left cave:"):
            raise
        return
    raise AssertionError("cave returned without reaching its end")


def test_heap_link_does_not_write_through_pupu():
    """A ``PUPU`` backward link is not stored through. A real neighbor is."""
    from patch_chunk_walk_guard import (
        ADDR_HEAP_LINK_BODY,
        ADDR_HEAP_LINK_PAD,
        build_heap_bin,
        build_heap_link_body,
        build_heap_link_pad,
    )

    pad = build_heap_link_pad()
    body = build_heap_link_body()
    pupu = 0x55505550
    block = 0x14826480
    rem = 0x14A26520
    mem = {block + 0xC: pupu}
    regs = {0: rem, 7: block, 12: 0}
    ret, reads = _run_cave(pad, ADDR_HEAP_LINK_PAD, ADDR_HEAP_LINK_PAD, regs, mem)
    assert ret == ("leave", ADDR_HEAP_LINK_BODY)
    assert reads == [block + 0xC]
    _run_fallthrough(body, ADDR_HEAP_LINK_BODY, regs, mem)
    assert pupu + 8 not in mem
    assert mem[block + 0xC] == pupu
    assert rem + 8 not in mem

    neighbor = 0x15700040
    mem = {block + 0xC: neighbor, neighbor + 8: 0}
    regs = {0: rem, 7: block, 12: 0}
    _run_cave(pad, ADDR_HEAP_LINK_PAD, ADDR_HEAP_LINK_PAD, regs, mem)
    _run_fallthrough(body, ADDR_HEAP_LINK_BODY, regs, mem)
    assert mem[rem + 0xC] == neighbor
    assert mem[neighbor + 8] == rem
    assert mem[block + 0xC] == rem
    assert mem[rem + 8] == block

    blob = build_heap_bin()
    heap = 0x009A3D14
    sentinel = 0x15FFFFE0
    nxt = 0x15710020
    mem = {
        block + 0x14: pupu,
        block + 0x10: 0,
        heap + 8: sentinel,
        heap + 4: block,
    }
    regs = {0: rem, 5: heap, 7: block, "z": 0, "c": 0}
    _run_fallthrough(blob, 0x0000DEEC, regs, mem)
    assert 0x14 not in mem
    assert mem[rem + 0x14] == sentinel
    assert mem[heap + 4] == rem

    mem = {
        block + 0x14: nxt,
        block + 0x10: neighbor,
        heap + 8: sentinel,
        heap + 4: block,
    }
    regs = {0: rem, 5: heap, 7: block, "z": 0, "c": 0}
    _run_fallthrough(blob, 0x0000DEEC, regs, mem)
    assert mem[rem + 0x14] == nxt
    assert mem[neighbor + 0x14] == rem
    assert mem[heap + 4] == block

    mem = {
        block + 0x14: nxt,
        block + 0x10: pupu,
        heap + 8: sentinel,
        heap + 4: block,
    }
    regs = {0: rem, 5: heap, 7: block, "z": 0, "c": 0}
    _run_fallthrough(blob, 0x0000DEEC, regs, mem)
    assert pupu + 0x14 not in mem
    assert mem[heap + 4] == block
    assert mem[rem + 0x14] == nxt


def test_row_clear_skips_a_tiny_pointer():
    """``str r0, [r1]`` at ``0x3E0`` takes the empty-span exit."""
    from patch_chunk_walk_guard import (
        ADDR_ROW_CHECK,
        ADDR_ROW_GATE,
        ADDR_ROW_SKIP,
        ADDR_ROW_STORE,
        build_row_check,
        build_row_gate,
    )

    gate = build_row_gate()
    check = build_row_check()
    ret, reads = _run_cave(gate, ADDR_ROW_GATE, ADDR_ROW_GATE, {1: 0x3E0, 7: 0, "z": 0, "c": 0}, {})
    assert ret == ("leave", ADDR_ROW_CHECK)
    assert reads == []
    ret, reads = _run_cave(check, ADDR_ROW_CHECK, ADDR_ROW_CHECK, {1: 0x3E0, "z": 0, "c": 0}, {})
    assert ret == ("leave", ADDR_ROW_SKIP)
    assert reads == []

    ret, reads = _run_cave(
        check, ADDR_ROW_CHECK, ADDR_ROW_CHECK, {1: 0x0088E9F8, 0: 0, "z": 0, "c": 0}, {}
    )
    assert ret == ("leave", ADDR_ROW_STORE)


def test_memset_returns_when_the_buffer_is_null():
    """A null destination must not enter the ``stm`` fill."""
    from patch_chunk_walk_guard import (
        ADDR_MEMSET_BODY,
        ADDR_MEMSET_CAVE,
        ADDR_MEMSET_STUB,
        build_memset_cave,
        build_memset_stub,
    )

    cave = build_memset_cave()
    stub = build_memset_stub()
    ret, reads = _run_cave(cave, ADDR_MEMSET_CAVE, ADDR_MEMSET_CAVE, {0: 0, 14: 0x00107190}, {})
    assert ret == 0
    assert reads == []

    buf = 0x088E9C0
    ret, reads = _run_cave(cave, ADDR_MEMSET_CAVE, ADDR_MEMSET_CAVE, {0: buf, 14: 0x00107190}, {})
    assert ret == ("leave", ADDR_MEMSET_STUB)
    ret, reads = _run_cave(stub, ADDR_MEMSET_STUB, ADDR_MEMSET_STUB, {0: buf, 14: 0x00107190}, {})
    assert ret == ("leave", ADDR_MEMSET_BODY)
    assert reads == []


def test_pak_init_skips_the_header_when_the_table_is_null():
    """``stm r5, {r1, r6}`` at ``0x10D3B0`` faults when ``[global+0xc]`` is 0.

    The rest of the init still runs. A real table still gets the header.
    """
    from patch_chunk_walk_guard import ADDR_PAK_INIT, ADDR_PAK_INIT_END, build_pak_init

    blob = build_pak_init()
    glob = 0x08001000
    pak = 0x204B4150
    mem = {glob + 0xC: 0}
    regs = {0: glob, 1: pak, 4: 0x14A00000, 6: 0, 7: 1}
    ret, reads = _run_cave(blob, ADDR_PAK_INIT, ADDR_PAK_INIT, regs, mem)
    assert ret == ("leave", ADDR_PAK_INIT_END)
    assert reads == [glob + 0xC]
    assert 0 not in mem
    assert 0x14A00000 not in mem

    struct = 0x15700000
    mem = {glob + 0xC: struct}
    regs = {0: glob, 1: pak, 6: 0, 7: 1}
    _run_fallthrough(blob, ADDR_PAK_INIT, regs, mem)
    assert mem[struct] == pak
    assert mem[struct + 4] == 0
    assert mem[struct + 8] == 0
    assert mem[struct + 0x10] == 0x02000001
    assert regs[0] == 2


def test_pak_table_skips_a_null_base():
    """``ldrb r0, [r4, #0x13]`` faults when ``[global+0xc]`` is 0."""
    from patch_chunk_walk_guard import (
        ADDR_PAK_TABLE_CAVE,
        ADDR_PAK_TABLE_FAIL,
        build_pak_table_cave,
    )

    cave = build_pak_table_cave()
    assert cave.hex() == "002801d143f69ee4e07c7047"
    assert ADDR_PAK_TABLE_CAVE + len(cave) == 0x005D1940

    def run(r0: int, r4: int, lr: int, mem: dict[int, int]):
        import struct

        regs = {0: r0, 4: r4, 14: lr}
        reads: list[int] = []
        pc = ADDR_PAK_TABLE_CAVE
        for _ in range(8):
            off = pc - ADDR_PAK_TABLE_CAVE
            hw = struct.unpack_from("<H", cave, off)[0]
            if hw == 0x2800:  # cmp r0, #0
                z = regs[0] == 0
                pc += 2
                continue
            if (hw & 0xFF00) == 0xD100:  # bne.n
                imm = hw & 0xFF
                if imm & 0x80:
                    imm -= 0x100
                dest = (pc + 4 + imm * 2) & 0xFFFFFFFF
                pc = dest if not z else pc + 2
                continue
            if (hw & 0xF800) == 0xF000:  # blx
                hw2 = struct.unpack_from("<H", cave, off + 2)[0]
                sign = (hw >> 10) & 1
                imm10 = hw & 0x3FF
                j1 = (hw2 >> 13) & 1
                j2 = (hw2 >> 11) & 1
                imm10l = (hw2 >> 1) & 0x3FF
                i1 = (~(j1 ^ sign)) & 1
                i2 = (~(j2 ^ sign)) & 1
                imm = (sign << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm10l << 2)
                if sign:
                    imm -= 0x2000000
                aligned = (pc + 4) & ~3
                return ("leave", (aligned + imm) & 0xFFFFFFFF), reads
            if hw == 0x7CE0:  # ldrb r0, [r4, #0x13]
                addr = (regs[4] + 0x13) & 0xFFFFFFFF
                if addr not in mem:
                    raise AssertionError(f"unmapped read {addr:#x}")
                reads.append(addr)
                regs[0] = mem[addr] & 0xFF
                pc += 2
                continue
            if hw == 0x4770:  # bx lr
                return ("leave", regs[14]), reads
            raise AssertionError(f"unhandled thumb {hw:#x} at {pc:#x}")
        raise AssertionError("pak table cave did not return")

    ret, reads = run(0, 0x6E0, 0x151E8, {})
    assert ret == ("leave", ADDR_PAK_TABLE_FAIL)
    assert reads == []

    struct = 0x15700000
    ret, reads = run(struct, struct + 0x6E0, 0x151E8, {struct + 0x6E0 + 0x13: 0x6})
    assert ret == ("leave", 0x151E8)
    assert reads == [struct + 0x6E0 + 0x13]


def test_pak_alloc_pops_when_malloc_returns_null():
    """``strb r1, [r0]`` faults when the PACK allocation returns 0."""
    from patch_chunk_walk_guard import (
        ADDR_FILLCAND_TAIL,
        ADDR_PAK_ALLOC,
        ADDR_PAK_FLAG_CAVE,
        ADDR_PAK_POP,
        build_pak_alloc_cave,
    )
    from patch_input_candidate_nullguard import POST1

    cave = build_pak_alloc_cave()
    assert cave.hex() == "002801d17df5eee6002d00d068607047"

    def run(r0: int, r5: int, lr: int, mem: dict[int, int]):
        regs = {0: r0, 5: r5, 14: lr}
        z = False
        writes: list[int] = []
        pc = ADDR_PAK_FLAG_CAVE
        for _ in range(8):
            off = pc - ADDR_PAK_FLAG_CAVE
            hw = struct.unpack_from("<H", cave, off)[0]
            if hw in (0x2800, 0x2D00):  # cmp r0/r5, #0
                reg = 0 if hw == 0x2800 else 5
                z = regs[reg] == 0
                pc += 2
                continue
            if (hw & 0xFF00) in (0xD000, 0xD100):
                imm = hw & 0xFF
                if imm & 0x80:
                    imm -= 0x100
                dest = (pc + 4 + imm * 2) & 0xFFFFFFFF
                take = z if (hw & 0xFF00) == 0xD000 else not z
                pc = dest if take else pc + 2
                continue
            if (hw & 0xF800) == 0xF000:  # blx to the frame pop
                return ("leave", ADDR_PAK_POP), writes
            if hw == 0x6068:  # str r0, [r5, #4]
                addr = (regs[5] + 4) & 0xFFFFFFFF
                if addr < 0x1000:
                    raise AssertionError(f"unmapped write {addr:#x}")
                mem[addr] = regs[0]
                writes.append(addr)
                pc += 2
                continue
            if hw == 0x4770:  # bx lr
                return ("leave", regs[14]), writes
            raise AssertionError(f"unhandled thumb {hw:#x} at {pc:#x}")
        raise AssertionError("pak alloc cave did not return")

    ret, writes = run(0, 0, 0xD3DC, {})
    assert ret == ("leave", ADDR_PAK_POP)
    assert writes == []

    table = 0x15700000
    ret, writes = run(0x14800000, table, 0xD3DC, {})
    assert ret == ("leave", 0xD3DC)
    assert writes == [table + 4]

    ret, writes = run(0x14800000, 0, 0xD3DC, {})
    assert ret == ("leave", 0xD3DC)
    assert writes == []

    from nlpp_paths import find_vanilla_code

    vanilla_path = find_vanilla_code()
    if vanilla_path is None:
        return
    from patch_chunk_walk_guard import apply_pak_flag
    from patch_input_candidate_nullguard import CAVE1, apply_patch as apply_cand

    data = bytearray(vanilla_path.read_bytes())
    apply_cand(data)
    apply_pak_flag(data)
    apply_pak_flag(data)
    assert data[ADDR_PAK_ALLOC : ADDR_PAK_ALLOC + 4] != bytes.fromhex("040085e5")
    assert data[ADDR_PAK_FLAG_CAVE : ADDR_PAK_FLAG_CAVE + 16] == cave
    beq = struct.unpack_from("<I", data, CAVE1 + 4)[0]
    imm = beq & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    assert (CAVE1 + 4) + 8 + (imm << 2) == ADDR_FILLCAND_TAIL
    branch = struct.unpack_from("<I", data, ADDR_FILLCAND_TAIL + 4)[0]
    imm = branch & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    assert (ADDR_FILLCAND_TAIL + 4) + 8 + (imm << 2) == POST1
