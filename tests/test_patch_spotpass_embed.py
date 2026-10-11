"""Embed SpotPass NsData and spoof BOSS NewFlag/ReadNsData."""

from __future__ import annotations

from conftest import SRC, load_module

sp = load_module("patch_spotpass_embed", SRC / "patch_spotpass_embed.py")


def _vanilla_blob() -> bytearray:
    data = bytearray(sp.ADDR_LIST_BLOB + sp.LIST_BLOB_LEN)
    data[sp.ADDR_NEWFLAG : sp.ADDR_NEWFLAG + sp.NEWFLAG_LEN] = sp.VANILLA_FUN
    data[sp.ADDR_CONFIRM : sp.ADDR_CONFIRM + len(sp.VANILLA_CONFIRM)] = sp.VANILLA_CONFIRM
    data[sp.ADDR_CONFIRM_INC : sp.ADDR_CONFIRM_INC + 4] = sp.VANILLA_CONFIRM_INC
    data[sp.ADDR_CONFIRM_DEC : sp.ADDR_CONFIRM_DEC + 4] = sp.VANILLA_CONFIRM_DEC
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
    data[sp.ADDR_MAGLIST_FATAL_BL : sp.ADDR_MAGLIST_FATAL_BL + 4] = (
        sp.VANILLA_MAGLIST_FATAL_BL
    )
    data[sp.ADDR_HOME_OPEN_BL : sp.ADDR_HOME_OPEN_BL + 4] = sp.VANILLA_HOME_OPEN_BL
    data[sp.ADDR_WEB_NOTIFY : sp.ADDR_WEB_NOTIFY + 4] = sp.VANILLA_WEB_NOTIFY
    data[sp.ADDR_BOOK_OPEN_NEXT : sp.ADDR_BOOK_OPEN_NEXT + 4] = (
        sp.VANILLA_BOOK_OPEN_NEXT
    )
    data[sp.ADDR_BOOK_CTOR : sp.ADDR_BOOK_CTOR + 4] = sp.VANILLA_BOOK_CTOR
    data[sp.ADDR_MENU_CAVE : sp.ADDR_MENU_CAVE + len(sp.VANILLA_MENU_CAVE)] = (
        sp.VANILLA_MENU_CAVE
    )
    data[sp.ADDR_MENU_DRAW : sp.ADDR_MENU_DRAW + len(sp.VANILLA_MENU_DRAW)] = (
        sp.VANILLA_MENU_DRAW
    )
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
    assert sp.VANILLA_CONFIRM_INC == sp._bl(sp.ADDR_CONFIRM_INC, 0x0059A7C4)
    assert sp.VANILLA_CONFIRM_DEC == sp._bl(sp.ADDR_CONFIRM_DEC, 0x0059A824)


def test_forced_confirm_does_not_hold_home_lock():
    """Forced +0x48 makes SpotPass state 1 run again after state 2.

    State 1's ``bl FUN_0059a7c4`` increments ``0x008ab420+0xc``. State 2's
    ``bl FUN_0059a824`` decrements it and stores state 1, so the count stays
    up for the session and HOME draws the crossed icon. Both calls are NOP.
    Restoring either call is not a patched embed, and apply puts both back.
    The destructor pair at ``0x006097E8`` / ``0x0060987C`` is left alone.
    """
    dtor_inc = 0x006097E8
    dtor_dec = 0x0060987C
    data = _vanilla_blob()
    data[dtor_inc : dtor_inc + 4] = sp._bl(dtor_inc, 0x0059A7C4)
    data[dtor_dec : dtor_dec + 4] = sp._bl(dtor_dec, 0x0059A824)
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_CONFIRM : sp.ADDR_CONFIRM + 4] == sp._u32(0xE3A00001)
    assert data[sp.ADDR_CONFIRM_INC : sp.ADDR_CONFIRM_INC + 4] == sp.ARM_NOP
    assert data[sp.ADDR_CONFIRM_DEC : sp.ADDR_CONFIRM_DEC + 4] == sp.ARM_NOP
    assert data[dtor_inc : dtor_inc + 4] == sp._bl(dtor_inc, 0x0059A7C4)
    assert data[dtor_dec : dtor_dec + 4] == sp._bl(dtor_dec, 0x0059A824)

    for site, vanilla in (
        (sp.ADDR_CONFIRM_INC, sp.VANILLA_CONFIRM_INC),
        (sp.ADDR_CONFIRM_DEC, sp.VANILLA_CONFIRM_DEC),
    ):
        broken = bytearray(data)
        broken[site : site + 4] = vanilla
        assert not sp.is_patched(broken)
        assert sp.apply_patch(broken) is True
        assert broken[sp.ADDR_CONFIRM_INC : sp.ADDR_CONFIRM_INC + 4] == sp.ARM_NOP
        assert broken[sp.ADDR_CONFIRM_DEC : sp.ADDR_CONFIRM_DEC + 4] == sp.ARM_NOP
        assert broken[dtor_inc : dtor_inc + 4] == sp._bl(dtor_inc, 0x0059A7C4)
        assert broken[dtor_dec : dtor_dec + 4] == sp._bl(dtor_dec, 0x0059A824)
        assert sp.is_patched(broken)
        assert sp.apply_patch(broken) is False


def test_embed_applies_idempotent_and_reverts():
    data = _vanilla_blob()
    assert sp.is_vanilla(data)
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert sp.is_patched(data)
    assert data[sp.ADDR_CONFIRM : sp.ADDR_CONFIRM + len(sp.PATCHED_CONFIRM)] == sp.PATCHED_CONFIRM
    assert data[sp.ADDR_CONFIRM_INC : sp.ADDR_CONFIRM_INC + 4] == sp.ARM_NOP
    assert data[sp.ADDR_CONFIRM_DEC : sp.ADDR_CONFIRM_DEC + 4] == sp.ARM_NOP
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
    assert "湖".encode("utf-8") + b"\x00" in cave
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


def test_info_menu_draws_filled_sections_into_tex_info():
    cave = sp.build_info_menu_cave()
    assert sp.ADDR_MENU_LIST_CAVE + len(cave) <= sp.ADDR_MENU_LIST_LIMIT
    assert len(cave) == len(sp.VANILLA_STATE6_BODY) + 4
    text = sp.build_menu_text()
    holy = text[sp.MENU_STRIDE : sp.MENU_STRIDE * 2]
    fever = text[sp.MENU_STRIDE * 3 : sp.MENU_STRIDE * 4]
    assert holy.startswith(b"> Holy Site\n  FEVER\x00")
    assert fever.startswith(b"  Holy Site\n> FEVER\x00")
    for absent in (b"New Open", b"START", b"PICK UP", b"Photo Contest"):
        assert absent not in text
    assert len(text) > sp.MENU_SLOT_COUNT * sp.MENU_STRIDE
    data = _vanilla_blob()
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_INFO_DRAW : sp.ADDR_INFO_DRAW + 4] == sp._bl(
        sp.ADDR_INFO_DRAW, sp.ADDR_MENU_OPEN
    )
    assert data[sp.ADDR_INFO_DRAW + 4 : sp.ADDR_INFO_DRAW + 8] == sp._bl(
        sp.ADDR_INFO_DRAW + 4, sp.ADDR_MENU_PAD
    )
    assert data[sp.ADDR_INFO_DRAW + 8 : sp.ADDR_INFO_DRAW + 12] == sp._bl(
        sp.ADDR_INFO_DRAW + 8, sp.ADDR_MENU_LIST_CAVE
    )
    assert data[sp.ADDR_MENU_POLL : sp.ADDR_MENU_POLL + 4] == sp._bl(
        sp.ADDR_MENU_POLL, sp.menu_poll_addr()
    )
    pad = sp.build_menu_pad_cave()
    blob = sp.menu_control_blob()
    assert sp.ADDR_MENU_PAD + len(blob) <= sp.ADDR_MENU_PAD_LIMIT
    assert data[sp.ADDR_MENU_PAD : sp.ADDR_MENU_PAD + len(blob)] == blob
    assert data[sp.ADDR_TWIN_STEP : sp.ADDR_TWIN_STEP + 4] == sp._bl(
        sp.ADDR_TWIN_STEP, sp.ADDR_PAGE_STEP
    )
    assert data[sp.ADDR_PAGE_BLOCK : sp.ADDR_PAGE_BLOCK + len(sp.build_page_block())] == (
        sp.build_page_block()
    )
    assert data[sp.ADDR_MENU_LIST_STR : sp.ADDR_MENU_LIST_STR + len(text)] == text
    assert data[sp.ADDR_ARROW_SKIP : sp.ADDR_ARROW_SKIP + 4] == sp.VANILLA_ARROW_SKIP
    _arrow, paint_at = sp.build_menu_arrow_cave(sp.build_info_menu_cave())
    back = sp.build_menu_back_stub(paint_at)
    assert sp.ADDR_MENU_IDLE_POLL + len(back) <= sp.ADDR_MENU_IDLE_POLL_LIMIT
    assert data[sp.ADDR_ARROW_IDLE : sp.ADDR_ARROW_IDLE + 4] == sp._b_cond(
        0, sp.ADDR_ARROW_IDLE, sp.back_finish_addr()
    )
    assert data[sp.ADDR_ARROW_POLL_TAIL : sp.ADDR_ARROW_POLL_TAIL + 4] == (
        sp.VANILLA_ARROW_POLL_TAIL
    )
    choice_at = sp.ADDR_MENU_ARROW + len(_arrow)
    assert data[choice_at : choice_at + 28] == sp.build_back_choice(choice_at)
    assert data[sp.ADDR_BACK_SET : sp.ADDR_BACK_SET + 4] == sp._b_cond(
        1, sp.ADDR_BACK_SET, choice_at
    )
    assert data[sp.ADDR_BACK_LEAVE : sp.ADDR_BACK_LEAVE + 4] == sp._b(
        sp.ADDR_BACK_LEAVE, sp.ADDR_ARROW_LATCH
    )
    assert data[sp.ADDR_ARROW_STEP : sp.ADDR_ARROW_STEP + 4] == sp.VANILLA_ARROW_STEP
    assert data[sp.ADDR_ARROW_STEP + 4 : sp.ADDR_ARROW_STEP + 8] == sp.VANILLA_ARROW_CMN
    assert data[sp.ADDR_MENU_IDLE_POLL : sp.ADDR_MENU_IDLE_POLL + len(back)] == back
    for addr, _vanilla, patched in sp.ARROW_EDGE:
        assert data[addr : addr + 4] == bytes.fromhex(patched)
    assert data[sp.ADDR_PAGE_MASK_WALK : sp.ADDR_PAGE_MASK_WALK + 4] == (
        sp.PATCHED_PAGE_MASK
    )
    assert data[sp.ADDR_PAGE_MASK_LOOKUP : sp.ADDR_PAGE_MASK_LOOKUP + 4] == (
        sp.PATCHED_PAGE_MASK_LOOKUP
    )
    assert data[sp.ADDR_TITLE_BIND_FIXED : sp.ADDR_TITLE_BIND_FIXED + 4] == (
        sp.PATCHED_TITLE_BIND_SKIP
    )
    assert data[sp.ADDR_TITLE_BIND_INDEX : sp.ADDR_TITLE_BIND_INDEX + 4] == (
        sp.PATCHED_TITLE_BIND_SKIP
    )
    assert sp.revert_patch(data) is True
    assert data[sp.ADDR_INFO_DRAW : sp.ADDR_INFO_DRAW + 12] == sp.VANILLA_INFO_DRAW
    assert data[sp.ADDR_MENU_POLL : sp.ADDR_MENU_POLL + 4] == sp.VANILLA_MENU_POLL
    assert data[sp.ADDR_MENU_PAD : sp.ADDR_MENU_PAD + len(blob)] == b"\x00" * len(blob)
    assert data[sp.ADDR_PAGE_BLOCK : sp.ADDR_PAGE_BLOCK + len(sp.build_page_block())] == (
        b"\x00" * len(sp.build_page_block())
    )
    assert data[sp.ADDR_TWIN_STEP : sp.ADDR_TWIN_STEP + 4] == sp._bl(
        sp.ADDR_TWIN_STEP, sp.ADDR_PAGE_STEP
    )
    assert data[sp.ADDR_TITLE_BIND_FIXED : sp.ADDR_TITLE_BIND_FIXED + 4] == (
        sp.VANILLA_TITLE_BIND_FIXED
    )
    assert data[sp.ADDR_TITLE_BIND_INDEX : sp.ADDR_TITLE_BIND_INDEX + 4] == (
        sp.VANILLA_TITLE_BIND_INDEX
    )
    assert data[sp.ADDR_MENU_LIST_CAVE : sp.ADDR_MENU_LIST_CAVE + len(sp.VANILLA_STATE6_BODY)] == (
        sp.VANILLA_STATE6_BODY
    )
    assert data[sp.ADDR_ARROW_SKIP : sp.ADDR_ARROW_SKIP + 4] == sp.VANILLA_ARROW_SKIP
    assert data[sp.ADDR_ARROW_IDLE : sp.ADDR_ARROW_IDLE + 4] == sp.VANILLA_ARROW_IDLE
    assert data[sp.ADDR_ARROW_POLL_TAIL : sp.ADDR_ARROW_POLL_TAIL + 4] == (
        sp.VANILLA_ARROW_POLL_TAIL
    )
    assert data[sp.ADDR_ARROW_STEP : sp.ADDR_ARROW_STEP + 4] == sp.VANILLA_ARROW_STEP
    assert data[sp.ADDR_ARROW_STEP + 4 : sp.ADDR_ARROW_STEP + 8] == sp.VANILLA_ARROW_CMN
    assert data[sp.ADDR_BACK_SET : sp.ADDR_BACK_SET + 4] == sp.VANILLA_BACK_SET
    assert data[sp.ADDR_BACK_LEAVE : sp.ADDR_BACK_LEAVE + 4] == sp.VANILLA_BACK_LEAVE
    assert data[sp.ADDR_MENU_IDLE_POLL : sp.ADDR_MENU_IDLE_POLL + len(back)] == (
        b"\x00" * len(back)
    )
    for addr, vanilla, _patched in sp.ARROW_EDGE:
        assert data[addr : addr + 4] == bytes.fromhex(vanilla)
    assert data[0x006094B8 : 0x006094BC] == sp.ARM_NOP


def test_list_blob_is_not_installed_on_the_book():
    """The index title draws on the first rule. The book branch stays."""
    blob = sp.build_list_blob()
    assert blob[12:].split(b"\x00", 1)[0] == "ニューオープン".encode("utf-8")
    data = _vanilla_blob()
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_EMPTY_LIST_BEQ : sp.ADDR_EMPTY_LIST_BEQ + 4] == (
        sp.PATCHED_EMPTY_LIST_BEQ
    )
    assert data[sp.ADDR_LIST_BLOB : sp.ADDR_LIST_BLOB + len(blob)] == b"\x00" * len(blob)


def test_embed_rejects_unknown_function():
    data = _vanilla_blob()
    data[sp.ADDR_NEWFLAG] = 0x99
    try:
        sp.apply_patch(data)
    except ValueError as exc:
        assert "unexpected GetNsDataNewFlag" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_map_comments_replace_citizen_bubble_bodies():
    cave = sp.build_comment_cave()
    assert sp.ADDR_COMMENT_CAVE + len(cave) <= sp.ADDR_MERGE_AC
    placed = bytearray(sp.ADDR_COMMENT_CAVE + len(cave))
    placed[sp.ADDR_COMMENT_CAVE : sp.ADDR_COMMENT_CAVE + len(cave)] = cave
    assert sp._bl_target(placed, sp.ADDR_COMMENT_CAVE + 4) == sp.ADDR_TEXT_LOOKUP
    assert sp._bl_target(placed, sp.ADDR_COMMENT_CAVE + 15 * 4) == sp.ADDR_BOUND_COPY
    text = sp.build_comment_text()
    assert text[48:].split(b"\x00", 1)[0]
    assert "ラ一メン".encode("utf-8") in text
    data = _vanilla_blob()
    data[sp.ADDR_DESC_BL : sp.ADDR_DESC_BL + 4] = sp._bl(
        sp.ADDR_DESC_BL, sp.ADDR_DESC_BUILD
    )
    for site in (sp.ADDR_BODY_BL, sp.ADDR_BODY_BL2):
        data[site : site + 4] = sp._bl(site, sp.ADDR_TEXT_LOOKUP)
    data[sp.ADDR_COMMENT_CAVE : sp.ADDR_COMMENT_CAVE + len(cave)] = (
        sp.VANILLA_COMMENT_HOLE
    )
    assert sp.apply_map_comments(data) is True
    assert data[sp.ADDR_DESC_BL : sp.ADDR_DESC_BL + 4] == sp._bl(
        sp.ADDR_DESC_BL, sp.ADDR_DESC_BUILD
    )
    for site in (sp.ADDR_BODY_BL, sp.ADDR_BODY_BL2):
        assert data[site : site + 4] == sp._bl(site, sp.ADDR_COMMENT_CAVE)
    assert data[sp.ADDR_COMMENT_CAVE : sp.ADDR_COMMENT_CAVE + len(cave)] == cave
    assert data[sp.ADDR_MERGE_PARSE : sp.ADDR_MERGE_PARSE + sp.MERGE_PARSE_LEN] == (
        sp.VANILLA_MERGE_PARSE
    )
    assert data[sp.ADDR_MERGE_AC : sp.ADDR_MERGE_AC + 4] == sp.VANILLA_MERGE_AC
    assert "ラ一メン".encode("utf-8") in data[sp.ADDR_COMMENT_TEXT : sp.ADDR_COMMENT_LIMIT]
    assert sp.apply_map_comments(data) is False
    sp._undo_map_comments(data)
    assert data[sp.ADDR_DESC_BL : sp.ADDR_DESC_BL + 4] == sp._bl(
        sp.ADDR_DESC_BL, sp.ADDR_DESC_BUILD
    )
    for site in (sp.ADDR_BODY_BL, sp.ADDR_BODY_BL2):
        assert data[site : site + 4] == sp._bl(site, sp.ADDR_TEXT_LOOKUP)
    assert data[sp.ADDR_COMMENT_CAVE : sp.ADDR_COMMENT_CAVE + len(cave)] == (
        sp.VANILLA_COMMENT_HOLE
    )
