"""Coverage for patch_spotpass_embed's data checks: occupied caves, map
comments, payload loading, the menu cell on a full-size code.bin, and revert.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import SRC, load_module
from test_patch_spotpass_embed import _vanilla_blob, sp


@pytest.fixture(autouse=True)
def quiet(capsys):
    yield
    capsys.readouterr()


def _bubbles(data: bytearray) -> bytearray:
    """Vanilla map-bubble sites, as in a real code.bin."""
    cave = sp.build_comment_cave()
    data[sp.ADDR_DESC_BL : sp.ADDR_DESC_BL + 4] = sp._bl(sp.ADDR_DESC_BL, sp.ADDR_DESC_BUILD)
    for site in (sp.ADDR_BODY_BL, sp.ADDR_BODY_BL2):
        data[site : site + 4] = sp._bl(site, sp.ADDR_TEXT_LOOKUP)
    data[sp.ADDR_COMMENT_CAVE : sp.ADDR_COMMENT_CAVE + len(cave)] = sp.VANILLA_COMMENT_HOLE
    return data


def test_module_adds_src_to_path(monkeypatch):
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p).resolve() != SRC])
    fresh = load_module("patch_spotpass_embed_fresh", SRC / "patch_spotpass_embed.py")
    assert str(SRC) in sys.path and fresh.ARM_NOP == sp.ARM_NOP


def test_ldr_pc_range():
    assert len(sp._ldr_pc(0x1000, 0x1000 - 0x100)) == 4
    with pytest.raises(ValueError, match="out of range"):
        sp._ldr_pc(0x10000, 0x10000 - 0x2000)
    with pytest.raises(ValueError, match="out of range"):
        sp._ldr_pc(0x10000, 0x10000 + 0x2000)


def test_menu_move_cave_default_address():
    assert sp.build_menu_move_cave() == sp.build_menu_move_cave(sp.menu_move_addr())


def test_full_size_code_bin_seeds_the_menu_cell():
    data = _vanilla_blob()
    data += bytes(sp.ADDR_MENU_CELL + 44 - len(data))
    assert sp.apply_patch(data) is True
    cell = sp.ADDR_MENU_CELL
    assert data[cell : cell + 4] == sp._u32(sp.lake_body_va())
    assert data[cell + 40 : cell + 44] == sp._u32(sp.fever_body_va())
    assert sp.revert_patch(data) is True


@pytest.mark.parametrize("where, msg", [
    ("ADDR_LAKE_BODY", "article sentences"),
    ("ADDR_MENU_PAD", "menu pad"),
    ("ADDR_MENU_POLL", "menu poll"),
    ("ADDR_PAGE_BLOCK", "page block"),
])
def test_info_menu_refuses_occupied_caves(where, msg):
    data = _vanilla_blob()
    addr = getattr(sp, where)
    data[addr : addr + 4] = b"\x11\x22\x33\x44"
    if where == "ADDR_PAGE_BLOCK":
        data[sp.ADDR_PAGE_BLOCK_LIMIT : sp.ADDR_PAGE_BLOCK_LIMIT + 2] = b"\x01\x01"
    with pytest.raises(ValueError, match=msg):
        sp.apply_info_menu(data)


def test_worker_host_writes_both_caves():
    data = _vanilla_blob()
    sp.apply_worker_host(data)
    worker = sp.build_worker_cave()
    child = sp.build_child_cave()
    assert data[sp.ADDR_WORKER_CAVE : sp.ADDR_WORKER_CAVE + len(worker)] == worker
    assert data[sp.ADDR_CHILD_CAVE : sp.ADDR_CHILD_CAVE + len(child)] == child
    assert sp._bl_target(data, sp.ADDR_CHILD_CALL) == sp.ADDR_CHILD_CAVE


def _voice_dat(tmp_path: Path, places: list[int], text: bytes = b"hi") -> Path:
    blob = bytearray(sp.INFO_DAT.read_bytes())
    for i, place in enumerate(places):
        off = sp._VOICE_OFF + i * sp._VOICE_STRIDE
        rec = bytearray(sp._VOICE_STRIDE)
        rec[24 : 24 + len(text)] = text
        rec[-4:-2] = place.to_bytes(2, "big")
        blob[off : off + sp._VOICE_STRIDE] = rec
    path = tmp_path / "info.dat"
    path.write_bytes(blob)
    return path


def test_voice_comment_checks(tmp_path, monkeypatch):
    good = [1, 2, 3, 4, 6, 28]
    monkeypatch.setattr(sp, "INFO_DAT", _voice_dat(tmp_path, [9, 9, 9, 9, 9, 9]))
    with pytest.raises(ValueError, match="voice places"):
        sp._voice_comments()
    monkeypatch.setattr(sp, "_VOICE_STRIDE", 24 + 0x101 + 4)
    monkeypatch.setattr(sp, "INFO_DAT", _voice_dat(tmp_path, good, b"x" * 0x101))
    with pytest.raises(ValueError, match="voice 0 is"):
        sp._voice_comments()


def test_map_comments_states():
    cave = sp.build_comment_cave()
    # Short data and unknown body sites are left alone.
    assert sp.apply_map_comments(bytearray(16)) is False
    sp._undo_map_comments(bytearray(16))
    data = _vanilla_blob()
    for site in (sp.ADDR_BODY_BL, sp.ADDR_BODY_BL2):
        data[site : site + 4] = b"\x01\x02\x03\x04"
    assert sp.apply_map_comments(data) is False

    # Not hooked yet, but the merge body is something else.
    data = _bubbles(_vanilla_blob())
    data[sp.ADDR_COMMENT_CAVE] ^= 0xFF
    with pytest.raises(ValueError, match="not the merge body"):
        sp.apply_map_comments(data)
    # Text room already used.
    data = _bubbles(_vanilla_blob())
    data[sp.ADDR_COMMENT_TEXT] = 1
    with pytest.raises(ValueError, match="is not empty"):
        sp.apply_map_comments(data)
    # Hooked, but the cave was changed since.
    data = _bubbles(_vanilla_blob())
    assert sp.apply_map_comments(data) is True
    data[sp.ADDR_COMMENT_CAVE] ^= 0xFF
    with pytest.raises(ValueError, match="changed"):
        sp.apply_map_comments(data)

    # An older build hooked the shop description bl instead; moving off it is
    # allowed even though the merge body is already the cave.
    data = _bubbles(_vanilla_blob())
    data[sp.ADDR_DESC_BL : sp.ADDR_DESC_BL + 4] = sp._bl(sp.ADDR_DESC_BL, sp.ADDR_COMMENT_CAVE)
    data[sp.ADDR_COMMENT_CAVE : sp.ADDR_COMMENT_CAVE + len(cave)] = cave
    assert sp.apply_map_comments(data) is True
    assert data[sp.ADDR_DESC_BL : sp.ADDR_DESC_BL + 4] == sp._bl(sp.ADDR_DESC_BL, sp.ADDR_DESC_BUILD)

    # Undo with only the shop hook in place.
    data = _bubbles(_vanilla_blob())
    data[sp.ADDR_DESC_BL : sp.ADDR_DESC_BL + 4] = sp._bl(sp.ADDR_DESC_BL, sp.ADDR_COMMENT_CAVE)
    sp._undo_map_comments(data)
    assert data[sp.ADDR_DESC_BL : sp.ADDR_DESC_BL + 4] == sp._bl(sp.ADDR_DESC_BL, sp.ADDR_DESC_BUILD)


def test_payload_errors_and_short_data(tmp_path, monkeypatch):
    assert not sp.is_vanilla(bytes(16))
    assert not sp.is_patched(bytes(16))
    data = _vanilla_blob()
    assert sp.apply_patch(data) is True
    monkeypatch.setattr(sp, "INFO_DAT", tmp_path / "missing.dat")
    assert sp.is_patched(data) is False
    assert sp._old_embed(data) is False


def test_old_embed_requires_known_newflag_head():
    data = _vanilla_blob()
    sp.apply_patch(data)
    data[sp.ADDR_NEWFLAG : sp.ADDR_NEWFLAG + 4] = b"\x99\x99\x99\x99"
    assert sp._old_embed(data) is False
    with pytest.raises(ValueError, match="cannot revert"):
        sp.revert_patch(data)


def test_revert_handles_partly_restored_menu():
    data = _vanilla_blob()
    sp.apply_patch(data)
    # Pad, page block and step hooks were already put back by hand.
    blob = sp.menu_control_blob()
    data[sp.ADDR_MENU_PAD : sp.ADDR_MENU_PAD + len(blob)] = bytes(len(blob))
    block = sp.build_page_block()
    data[sp.ADDR_PAGE_BLOCK : sp.ADDR_PAGE_BLOCK + len(block)] = bytes(len(block))
    for addr in (sp.ADDR_TWIN_STEP, sp.ADDR_THIRD_STEP):
        data[addr : addr + 4] = sp._bl(addr, sp.ADDR_PAGE_STEP)
    assert sp.revert_patch(data) is True


def test_revert_unhooks_old_page_block_steps():
    data = _vanilla_blob()
    sp.apply_patch(data)
    for addr in (sp.ADDR_TWIN_STEP, sp.ADDR_THIRD_STEP):
        data[addr : addr + 4] = sp._bl(addr, sp.ADDR_PAGE_BLOCK)  # older builds
    assert sp.revert_patch(data) is True
    for addr in (sp.ADDR_TWIN_STEP, sp.ADDR_THIRD_STEP):
        assert sp._bl_target(data, addr) == sp.ADDR_PAGE_STEP
