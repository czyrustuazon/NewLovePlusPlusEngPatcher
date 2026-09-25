"""Embed SpotPass NsData and spoof BOSS NewFlag/ReadNsData."""

from __future__ import annotations

from conftest import SRC, load_module

sp = load_module("patch_spotpass_embed", SRC / "patch_spotpass_embed.py")


def _vanilla_blob() -> bytearray:
    data = bytearray(sp.ADDR_SPOTPASS_PAYLOAD + 0x920)
    data[sp.ADDR_NEWFLAG : sp.ADDR_NEWFLAG + sp.NEWFLAG_LEN] = sp.VANILLA_FUN
    data[sp.ADDR_CONFIRM : sp.ADDR_CONFIRM + len(sp.VANILLA_CONFIRM)] = sp.VANILLA_CONFIRM
    data[sp.ADDR_READ_BL1 : sp.ADDR_READ_BL1 + 4] = sp.VANILLA_READ_BL1
    data[sp.ADDR_READ_BL2 : sp.ADDR_READ_BL2 + 4] = sp.VANILLA_READ_BL2
    data[sp.ADDR_MERGE_ENTRY : sp.ADDR_MERGE_ENTRY + 8] = sp.VANILLA_MERGE_ENTRY
    data[sp.ADDR_MERGE : sp.ADDR_MERGE + 4] = sp.VANILLA_MERGE
    data[sp.ADDR_MERGE_AC : sp.ADDR_MERGE_AC + 4] = sp.VANILLA_MERGE_AC
    data[sp.ADDR_MERGE_BEQ : sp.ADDR_MERGE_BEQ + 4] = sp.VANILLA_MERGE_BEQ
    data[sp.ADDR_MERGE_PARSE : sp.ADDR_MERGE_PARSE + sp.MERGE_PARSE_LEN] = (
        sp.VANILLA_MERGE_PARSE
    )
    data[sp.ADDR_DATA_KICK : sp.ADDR_DATA_KICK + 4] = sp.VANILLA_DATA_KICK
    data[sp.ADDR_MAGLIST_EXTRA : sp.ADDR_MAGLIST_EXTRA + 4] = sp.VANILLA_MAGLIST_EXTRA
    data[sp.ADDR_MAGLIST_NODATA_BEQ : sp.ADDR_MAGLIST_NODATA_BEQ + 4] = (
        sp.VANILLA_MAGLIST_NODATA_BEQ
    )
    for addr, vanilla in sp.WATCHER_RET1_SITES:
        data[addr : addr + 8] = vanilla
    data[sp.ADDR_HASROWS_READY : sp.ADDR_HASROWS_READY + 8] = sp.VANILLA_HASROWS_READY
    for addr, vanilla in sp.WATCHER_NOP_SITES:
        data[addr : addr + 4] = vanilla
    for addr, vanilla, _patched in sp.MAGLIST_WORD_SITES:
        data[addr : addr + 4] = vanilla
    for addr, vanilla in sp.WATCHER_RESTORE_SITES:
        data[addr : addr + 4] = vanilla
    data[sp.ADDR_GATE_ENTRY : sp.ADDR_GATE_ENTRY + 8] = sp.VANILLA_GATE_ENTRY
    data[sp.ADDR_WEB_WATCHER_CLICK : sp.ADDR_WEB_WATCHER_CLICK + 8] = (
        sp.VANILLA_WEB_WATCHER_CLICK
    )
    data[sp.ADDR_WEB_PILL_LAYOUT : sp.ADDR_WEB_PILL_LAYOUT + 4] = (
        sp.VANILLA_WEB_PILL_LAYOUT
    )
    data[sp.ADDR_WEB_PILL_BODY : sp.ADDR_WEB_PILL_BODY + 12] = sp.VANILLA_WEB_PILL_BODY
    data[sp.ADDR_WEB_PILL_OTHER : sp.ADDR_WEB_PILL_OTHER + 4] = sp.VANILLA_WEB_PILL_OTHER
    data[sp.ADDR_GATE_HASROWS_BL : sp.ADDR_GATE_HASROWS_BL + 4] = (
        sp.VANILLA_GATE_HASROWS_BL
    )
    data[sp.ADDR_UNPACK_LDRB : sp.ADDR_UNPACK_LDRB + 4] = sp.VANILLA_TABLES_READY
    data[sp.ADDR_HASENTRY_LDRB : sp.ADDR_HASENTRY_LDRB + 4] = sp.VANILLA_TABLES_READY
    data[sp.ADDR_HASLIST_LDRB : sp.ADDR_HASLIST_LDRB + 4] = sp.VANILLA_TABLES_READY
    return data


def test_pills_return_without_drawing_on_backdrop():
    insn = int.from_bytes(sp.PATCHED_WEB_PILL_LAYOUT, "little")
    imm = insn & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    assert sp.ADDR_WEB_PILL_LAYOUT + 8 + (imm << 2) == sp.ADDR_PILL_EPILOGUE
    other = int.from_bytes(sp.PATCHED_WEB_PILL_OTHER, "little")
    imm = other & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    assert sp.ADDR_WEB_PILL_OTHER + 8 + (imm << 2) == sp.ADDR_PILL_EPILOGUE
    assert sp.VANILLA_WEB_OPEN_LAYOUT == bytes.fromhex("6bea04eb")
    assert sp.VANILLA_NODATA_MSG80 == bytes.fromhex("590fa0e3")
    assert sp.VANILLA_NODATA_MSG3 == bytes.fromhex("1700a0e3")
    assert sp.PATCHED_NODATA_MSG3 == bytes.fromhex("0000e0e3")
    assert sp.PATCHED_NODATA_MSG80 == bytes.fromhex("b200a0e3")
    assert sp.VANILLA_WEB_EMPTY_NOTIFY == bytes.fromhex("3cff2fe1")
    assert sp.VANILLA_WEB_EMPTY_NOTIFY2 == bytes.fromhex("3cff2fe1")
    assert sp.VANILLA_MSG3_ENTRY == bytes.fromhex("f04f2de9")
    slot = sp.build_slot_cave()
    assert sp.ADDR_ISSUE_CAVE + len(slot) <= 0x00609330
    assert slot[0:4] == bytes.fromhex("078081e0")
    assert sp.VANILLA_SLOT_SUM == bytes.fromhex("078081e0")


def test_caves_fit_in_replaced_function():
    stub = sp.build_function_blob()
    assert len(stub) == sp.NEWFLAG_LEN
    newflag = sp.build_newflag_cave()
    memcpy = sp.build_memcpy_cave(sp.memcpy_addr())
    assert len(newflag) == 0x08
    assert len(memcpy) == 0x44
    assert len(sp.build_data_kick_cave(sp.data_kick_addr())) == 0x24
    kick = sp.build_data_kick_cave(sp.data_kick_addr())
    assert kick[20:24] == bytes.fromhex("0120c0e5")  # strb r2, [r0, #1] r2=0
    assert bytes.fromhex("0120a0e3") not in kick  # no mov r2, #1
    assert sp.memcpy_addr() == sp.ADDR_NEWFLAG + 0x08
    assert sp.data_kick_addr() == sp.ADDR_NEWFLAG + 0x08 + 0x44


def test_newflag_always_returns_one():
    cave = sp.build_newflag_cave()
    assert cave[0:4] == sp._u32(0xE3A00001)  # mov r0, #1
    assert cave[4:8] == sp._u32(0xE12FFF1E)  # bx lr


def test_memcpy_literals_are_payload_va_and_size():
    addr = sp.memcpy_addr()
    cave = sp.build_memcpy_cave(addr)
    assert cave[-8:-4] == sp._u32(sp.PAYLOAD_VA)
    assert cave[-4:] == sp._u32(0x914)
    assert cave[0:4] == sp._u32(0xE3510000)  # cmp r1, #0
    assert cave[0x0C:0x10] == sp._u32(0xE5841048)  # str r1, [r4, #0x48]
    assert cave[0x28:0x2C] == sp._u32(0xE4C13001)  # strb [r1], #1
    # pc-relative lits: insn_pc = addr+off+8
    assert addr + 0x08 + 8 + 0x2C == addr + 0x3C
    assert addr + 0x10 + 8 + 0x28 == addr + 0x40
    assert cave[0x3C:0x40] == sp._u32(sp.PAYLOAD_VA)
    assert cave[0x40:0x44] == sp._u32(0x914)


def test_restore_readnsdata_keeps_merge_stub():
    data = _vanilla_blob()
    assert sp.apply_patch(data) is True
    sp.restore_readnsdata_ipc(data)
    assert data[sp.ADDR_READ_BL1 : sp.ADDR_READ_BL1 + 4] == sp.VANILLA_READ_BL1
    assert data[sp.ADDR_READ_BL2 : sp.ADDR_READ_BL2 + 4] == sp.VANILLA_READ_BL2
    assert data[sp.ADDR_MERGE_ENTRY : sp.ADDR_MERGE_ENTRY + 8] == sp.PATCHED_RET1
    assert not sp.is_patched(data)


def test_confirm_forces_apply():
    assert sp.PATCHED_CONFIRM != sp.VANILLA_CONFIRM
    assert sp.PATCHED_CONFIRM[0:4] == sp._u32(0xE3A00001)


def test_embed_applies_idempotent_and_reverts():
    data = _vanilla_blob()
    assert sp.is_vanilla(data)
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert sp.is_patched(data)
    assert data[sp.ADDR_CONFIRM : sp.ADDR_CONFIRM + len(sp.PATCHED_CONFIRM)] == sp.PATCHED_CONFIRM
    memcpy = sp.memcpy_addr()
    assert sp._bl_target(data, sp.ADDR_READ_BL1) == memcpy
    assert sp._bl_target(data, sp.ADDR_READ_BL2) == memcpy
    assert sp._bl_target(data, sp.ADDR_DATA_KICK) == sp.data_kick_addr()
    assert data[sp.ADDR_MERGE_ENTRY : sp.ADDR_MERGE_ENTRY + 8] == sp.PATCHED_RET1
    assert data[sp.ADDR_MERGE : sp.ADDR_MERGE + 4] == sp.VANILLA_MERGE
    assert data[sp.ADDR_MERGE_AC : sp.ADDR_MERGE_AC + 4] == sp.PATCHED_MERGE_AC
    assert data[sp.ADDR_MERGE_BEQ : sp.ADDR_MERGE_BEQ + 4] == sp.VANILLA_MERGE_BEQ
    assert data[sp.ADDR_MERGE_PARSE : sp.ADDR_MERGE_PARSE + sp.MERGE_PARSE_LEN] == (
        sp.VANILLA_MERGE_PARSE
    )
    assert data[sp.ADDR_MAGLIST_EXTRA : sp.ADDR_MAGLIST_EXTRA + 4] == (
        sp.PATCHED_MAGLIST_EXTRA
    )
    assert data[sp.ADDR_MAGLIST_NODATA_BEQ : sp.ADDR_MAGLIST_NODATA_BEQ + 4] == (
        sp.VANILLA_MAGLIST_NODATA_BEQ
    )
    for addr, _vanilla in sp.WATCHER_RET1_SITES:
        assert data[addr : addr + 8] == sp.PATCHED_RET1
    assert data[sp.ADDR_HASROWS_READY : sp.ADDR_HASROWS_READY + 8] == (
        sp.VANILLA_HASROWS_READY
    )
    for addr, _vanilla in sp.WATCHER_NOP_SITES:
        assert data[addr : addr + 4] == sp.ARM_NOP
    for addr, _vanilla, patched in sp.MAGLIST_WORD_SITES:
        assert data[addr : addr + 4] == patched
    for addr, vanilla in sp.WATCHER_RESTORE_SITES:
        assert data[addr : addr + 4] == vanilla
    assert data[sp.ADDR_GATE_ENTRY : sp.ADDR_GATE_ENTRY + 8] == sp.PATCHED_RET0
    assert data[sp.ADDR_WEB_WATCHER_CLICK : sp.ADDR_WEB_WATCHER_CLICK + 8] == (
        sp.VANILLA_WEB_WATCHER_CLICK
    )
    assert data[sp.ADDR_WEB_PILL_LAYOUT : sp.ADDR_WEB_PILL_LAYOUT + 4] == (
        sp.PATCHED_WEB_PILL_LAYOUT
    )
    assert data[sp.ADDR_WEB_PILL_BODY : sp.ADDR_WEB_PILL_BODY + 12] == (
        sp.VANILLA_WEB_PILL_BODY
    )
    assert data[sp.ADDR_WEB_PILL_OTHER : sp.ADDR_WEB_PILL_OTHER + 4] == (
        sp.PATCHED_WEB_PILL_OTHER
    )
    assert data[sp.ADDR_MYROOM_NODATA_BL : sp.ADDR_MYROOM_NODATA_BL + 4] == sp.ARM_NOP
    assert data[sp.ADDR_WEB_WATCHER_EXTRA_BEQ : sp.ADDR_WEB_WATCHER_EXTRA_BEQ + 4] == (
        sp.ARM_NOP
    )
    assert data[sp.ADDR_WEB_WATCHER_FAIL_ST : sp.ADDR_WEB_WATCHER_FAIL_ST + 4] == (
        sp.PATCHED_WEB_WATCHER_FAIL_ST
    )
    assert data[sp.ADDR_WEB_WATCHER_ST9_FROM_E : sp.ADDR_WEB_WATCHER_ST9_FROM_E + 4] == (
        sp.PATCHED_WEB_WATCHER_FAIL_ST
    )
    assert data[sp.ADDR_WEB_WATCHER_ST9_ENTRY : sp.ADDR_WEB_WATCHER_ST9_ENTRY + 4] == (
        sp.PATCHED_WEB_WATCHER_ST9_ENTRY
    )
    assert data[sp.ADDR_GATE_HASROWS_BL : sp.ADDR_GATE_HASROWS_BL + 4] == (
        sp.VANILLA_GATE_HASROWS_BL
    )
    payload = sp.load_payload()
    assert data[sp.ADDR_SPOTPASS_PAYLOAD : sp.ADDR_SPOTPASS_PAYLOAD + 0x914] == payload
    assert sp.apply_patch(data) is False
    assert sp.revert_patch(data) is True
    assert sp.is_vanilla(data)
    assert sp.revert_patch(data) is False


def test_area_name_cave_draws_station_into_tex_place():
    cave = sp.build_area_cave()
    assert len(cave) == len(sp.VANILLA_AREA_CAVE_BODY)
    assert sp.ADDR_AREA_CAVE + len(cave) <= sp.ADDR_AREA_CAVE_LIMIT
    assert cave.endswith("奥十羽野駅".encode("utf-8") + b"\x00")
    data = _vanilla_blob()
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_AREA_DRAW : sp.ADDR_AREA_DRAW + 4] == sp._bl(
        sp.ADDR_AREA_DRAW, sp.ADDR_AREA_CAVE
    )
    assert data[sp.ADDR_GATE_HASROWS_BL : sp.ADDR_GATE_HASROWS_BL + 4] == (
        sp.VANILLA_GATE_HASROWS_BL
    )
    assert sp.revert_patch(data) is True
    assert data[sp.ADDR_AREA_DRAW : sp.ADDR_AREA_DRAW + 12] == sp.VANILLA_AREA_DRAW
    assert (
        data[sp.ADDR_AREA_CAVE : sp.ADDR_AREA_CAVE + len(cave)]
        == sp.VANILLA_AREA_CAVE_BODY
    )


def test_embed_rejects_unknown_function():
    data = _vanilla_blob()
    data[sp.ADDR_NEWFLAG] = 0x99
    try:
        sp.apply_patch(data)
    except ValueError as exc:
        assert "unexpected GetNsDataNewFlag" in str(exc)
    else:
        raise AssertionError("expected ValueError")
