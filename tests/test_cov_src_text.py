"""Branch coverage for text/code patch modules that CI still misses.

Tiny stand-ins only: no vanilla code.bin or img.bin, no network, no zopfli
of a full 240x400 CESA texture.
"""

from __future__ import annotations

import argparse
import builtins
import json
import os
import struct
import sys
import types
import zlib
from pathlib import Path

import pytest
from PIL import Image

import fake_img as fi
import live_status as live
import patch_cesa as cesa
import patch_chunk_walk_guard as guard
import patch_code as code
import patch_input_romaji as romaji
import patch_names as names
import patch_spotpass_embed as embed
import patch_spotpass_skip as skip
import patch_textresource as trb
from patch_code import nop
from patch_input_strcat_raw import ADDR as STRCAT_AT
from patch_input_strcat_raw import cave_addr as strcat_cave_addr

CODE_LEN = 0x006A0000
LOOKUP = ["A", "B", "C"]


def _chunk(name: str, body: bytes) -> bytes:
    return name.encode("ascii") + struct.pack("<I", len(body)) + body


def _trb(
    rows: list[tuple[int, bytes]],
    extra: list[tuple[str, bytes]] | None = None,
    tail: bytes = b"",
) -> bytes:
    strb = bytearray()
    stri = bytearray()
    for flag, raw in rows:
        if flag == 2:
            stri += struct.pack("<IHH", len(strb), 0, 2)
            continue
        stri += struct.pack("<IHH", len(strb), len(raw), flag)
        strb += raw + b"\x00"
    pad = (4 - (len(strb) % 4)) % 4
    strb += b"\xc9" * pad
    parts = [_chunk("STRI", bytes(stri)), _chunk("STRB", bytes(strb))]
    for name, body in extra or []:
        parts.append(_chunk(name, body))
    return b"".join(parts) + tail


def _put(data: bytearray, addr: int, blob: bytes) -> None:
    data[addr : addr + len(blob)] = blob


def _fill(data: bytearray, start: int, size: int) -> None:
    data[start : start + size] = nop() * (size // 4)


def _plant_chunk() -> bytearray:
    data = bytearray(CODE_LEN)
    _fill(data, code.ADDR_CLEAR, code.SIZE_CLEAR)
    _fill(data, code.ADDR_SET, code.SIZE_SET)
    _fill(data, code.ADDR_BACKSPACE, code.SIZE_BACKSPACE)
    _fill(data, guard.ADDR_NODE_BYTE_CAVE, guard.ADDR_NODE_BYTE_LIMIT - guard.ADDR_NODE_BYTE_CAVE)
    _put(data, guard.ADDR_DEREF, guard.VANILLA_DEREF)
    _put(data, guard.ADDR_ADVANCE, guard.VANILLA_ADVANCE)
    _put(data, guard.ADDR_FIXUP, guard.VANILLA_FIXUP)
    _put(data, guard.ADDR_TITLE_RELOC, guard.VANILLA_TITLE_RELOC)
    _put(data, code.ADDR_CLEAR, guard.NAME_PANE_STUB)
    _put(data, guard.ADDR_TITLE_INDEX, guard.VANILLA_TITLE_INDEX)
    _put(data, guard.ADDR_CLYT, guard.VANILLA_CLYT)
    _put(data, guard.ADDR_LYT_HDR, guard.VANILLA_LYT_HDR)
    _put(data, guard.ADDR_VT, guard.VANILLA_VT)
    _put(data, guard.ADDR_TITLE_OBJ, guard.VANILLA_TITLE_OBJ)
    _put(data, guard.ADDR_FS_OPEN, guard.VANILLA_FS_OPEN)
    _put(data, guard.ADDR_TEX_REL, guard.VANILLA_TEX_REL)
    _put(data, guard.ADDR_FIELD, guard.VANILLA_FIELD)
    _put(data, guard.ADDR_FIELD_B, guard.VANILLA_FIELD)
    _put(data, guard.ADDR_NAME, guard.VANILLA_NAME)
    _put(data, guard.ADDR_MENU_VT, guard.VANILLA_MENU_VT)
    _put(data, guard.ADDR_IDX_LOAD, guard.VANILLA_IDX_LOAD)
    _put(data, guard.ADDR_NODE_BYTE, guard.VANILLA_NODE_BYTE)
    _put(data, guard.ADDR_BIND_THIS, guard.BIND_THIS_SKIP)
    _put(data, guard.ADDR_PANE_FLAG_BR, guard.VANILLA_PANE_FLAG_BR)
    _put(data, guard.ADDR_HEAP_WALK, guard.VANILLA_HEAP_WALK)
    _put(data, guard.ADDR_HEAP_LINK, guard.VANILLA_HEAP_LINK)
    _put(
        data,
        guard.ADDR_HEAP_LINK_BODY,
        bytes.fromhex("0c2080e50c2097e5080082e50c0087e5087080e5"),
    )
    _put(
        data,
        guard.ADDR_HEAP_BIN,
        bytes.fromhex(
            "142097e5100082e5102097e5140082e5102097e5102080e5"
            "142097e5142080e5042097e5012042e0202042e2042080e5"
            "041087e50a0000ea0d00a0e1964700eb0d00a0e100f020e3"
            "0000a0e10700a0e1f880bde8"
        ),
    )
    _put(data, guard.ADDR_HEAP_EMPTY, guard.b_cond(0, guard.ADDR_HEAP_EMPTY, guard.ADDR_HEAP_FAIL_OLD))
    _put(data, guard.ADDR_HEAP_NOFIT, guard.b_cond(0, guard.ADDR_HEAP_NOFIT, guard.ADDR_HEAP_FAIL))
    _put(data, guard.ADDR_ROW_CLEAR, guard.VANILLA_ROW_CLEAR)
    _put(data, guard.ADDR_MEMSET, guard.VANILLA_MEMSET)
    _put(data, guard.ADDR_PAK_INIT, guard.VANILLA_PAK_INIT)
    _put(data, guard.ADDR_IDX_LOAD_CAVE, nop() * 3 + bytes.fromhex("0c2f7c00"))
    _put(data, STRCAT_AT, guard.b_ins(STRCAT_AT, strcat_cave_addr()))
    return data


def _expect_guard(data: bytearray, addr: int, n: int, match: str) -> None:
    old = bytes(data[addr : addr + n])
    data[addr : addr + n] = b"\xff" * n
    with pytest.raises(ValueError, match=match):
        guard.apply_patch(data)
    data[addr : addr + n] = old


# ---------------------------------------------------------------------------
# patch_chunk_walk_guard
# ---------------------------------------------------------------------------


def test_chunk_walk_applies_rewrites_hooks_and_stops_early(capsys):
    data = _plant_chunk()
    assert guard.is_patched(data) is False
    assert guard.cave_blob().startswith(guard.build_cave()[0][:4])
    guard.apply_patch(data)
    assert guard.is_patched(data) is True
    guard.apply_patch(data)
    out = capsys.readouterr().out
    assert "already applied" in out
    assert "[chunk-walk]" in out
    data[guard.ADDR_CHUNK_WALK_CAVE] ^= 0xFF
    assert guard.is_patched(data) is False
    guard.apply_patch(data)
    assert guard.is_patched(data) is True


def test_chunk_walk_accepts_old_tex_cave_and_eb_fs_head():
    old = _plant_chunk()
    rel_at = guard.tex_release_cave_addr()
    _put(old, rel_at, guard.OLD_TEX_REL_CAVE)
    guard.apply_patch(old)
    assert guard.is_patched(old) is True

    eb = _plant_chunk()
    eb[guard.ADDR_FS_OPEN : guard.ADDR_FS_OPEN + 4] = b"\x00\x00\x00\xeb"
    guard.apply_patch(eb)
    assert guard.is_patched(eb) is True


def test_chunk_walk_rejects_each_unexpected_site():
    data = _plant_chunk()
    with pytest.raises(ValueError, match="strcat-raw"):
        guard.apply_patch(bytearray())
    heads = [
        (guard.ADDR_DEREF, "unexpected deref"),
        (guard.ADDR_ADVANCE, "unexpected advance"),
        (guard.ADDR_FIXUP, "unexpected fixup"),
        (guard.ADDR_TITLE_RELOC, "unexpected title reloc"),
        (code.ADDR_CLEAR, "name-pane stub"),
        (guard.ADDR_TITLE_INDEX, "unexpected title index"),
        (guard.ADDR_CLYT, "unexpected clyt"),
        (guard.ADDR_LYT_HDR, "unexpected layout header"),
        (guard.ADDR_VT, "unexpected virtual call"),
        (guard.ADDR_TITLE_OBJ, "unexpected title object"),
        (guard.ADDR_FS_OPEN, "unexpected fs open"),
        (guard.ADDR_TEX_REL, "unexpected texture release"),
        (guard.ADDR_FIELD, "unexpected field getter"),
        (guard.ADDR_FIELD_B, "unexpected field getter"),
        (guard.ADDR_NAME, "unexpected name walk"),
        (guard.ADDR_MENU_VT, "unexpected menu vt"),
        (guard.ADDR_IDX_LOAD, "unexpected idx"),
        (guard.ADDR_NODE_BYTE, "unexpected node byte"),
        (guard.ADDR_BIND_THIS, "unexpected bind"),
        (guard.ADDR_PANE_FLAG_BR, "unexpected pane flag"),
        (guard.ADDR_HEAP_WALK, "unexpected heap walk"),
        (guard.ADDR_HEAP_LINK, "unexpected heap link"),
        (guard.ADDR_HEAP_EMPTY, "unexpected heap fail"),
        (guard.ADDR_ROW_CLEAR, "unexpected row clear"),
        (guard.ADDR_MEMSET, "unexpected memset"),
    ]
    for addr, match in heads:
        _expect_guard(data, addr, 4, match)

    blob, labs = guard.build_cave()
    _put(data, guard.ADDR_DEREF, guard.b_ins(guard.ADDR_DEREF, labs["deref"]))
    _expect_guard(data, guard.ADDR_TEX_REL_TAIL, 12, "texture release tail")
    _put(data, guard.ADDR_DEREF, guard.VANILLA_DEREF)

    slots = [
        (guard.fs_open_cave_addr(), len(guard.build_fs_open_cave()), "fs open cave"),
        (guard.tex_release_cave_addr(), len(guard.build_tex_release_cave()), "texture release cave"),
        (guard.field_cave_addr(), len(guard.build_field_cave()), "field cave"),
        (
            guard.field_b_cave_addr(),
            len(guard.build_field_cave(guard.field_b_cave_addr(), resume=guard.ADDR_FIELD_B_RESUME, fail=guard.ADDR_FIELD_B_FAIL)),
            "field cave",
        ),
        (guard.fs_open_miss_addr(), len(guard.build_fs_open_miss()), "fs open miss"),
        (guard.name_cave_addr(), len(guard.build_name_cave()), "name cave"),
        (guard.menu_vt_cave_addr(), len(guard.build_menu_vt_cave()), "menu vt cave"),
        (guard.ADDR_IDX_LOAD_CAVE, len(guard.build_idx_load_cave()), "idx load cave"),
        (guard.ADDR_NODE_BYTE_CAVE, len(guard.build_node_byte_cave()), "node byte cave"),
        (guard.ADDR_PANE_FLAG_CAVE, len(guard.build_pane_flag_cave()), "pane flag cave"),
        (guard.ADDR_HEAP_LINK_BODY, 20, "heap link body"),
        (guard.ADDR_HEAP_BIN, 4, "heap split"),
        (guard.ADDR_ROW_GATE, len(guard.build_row_gate()), "row gate"),
        (guard.ADDR_ROW_CHECK, len(guard.build_row_check()), "row check"),
        (guard.ADDR_MEMSET_CAVE, len(guard.build_memset_cave()), "memset cave"),
        (guard.ADDR_MEMSET_STUB, len(guard.build_memset_stub()), "memset stub"),
        (guard.ADDR_PAK_INIT, 4, "unexpected pak init"),
    ]
    for addr, n, match in slots:
        _expect_guard(data, addr, n, match)
    assert blob


def test_chunk_walk_diag_heap_and_pak_edges(monkeypatch):
    monkeypatch.setattr(guard, "DIAG_TRAP", False)
    plain = guard.fail_b(1, 0x1000, 0x1100, trap=True)
    monkeypatch.setattr(guard, "DIAG_TRAP", True)
    monkeypatch.setattr(guard, "DIAG_ALL", False)
    trapped = guard.fail_b(1, 0x1000, 0x1100, trap=True)
    assert trapped != plain
    assert (int.from_bytes(trapped, "little") & 0x0F000000) == 0x0B000000
    assert guard.fail_b(1, 0x1000, 0x1100, trap=False) == guard.b_cond(1, 0x1000, 0x1100)
    monkeypatch.setattr(guard, "DIAG_ALL", True)
    assert guard.fail_b(1, 0x1000, 0x1100, trap=False) != plain
    assert guard.fail_b(1, 0x1000, 0x1100, trap=None) == guard.b_cond(1, 0x1000, 0x1100)
    assert guard.bx_lr(0) != guard.bx_lr()

    data = _plant_chunk()
    guard.apply_patch(data)
    assert guard.is_patched(data) is True
    assert data[guard.ADDR_DIAG_UDF : guard.ADDR_DIAG_UDF + 4] == guard._u32(0xE7F000F0)

    monkeypatch.setattr(guard, "DIAG_TRAP", False)
    monkeypatch.setattr(guard, "DIAG_ALL", False)
    monkeypatch.setattr(guard, "APPLY_HEAP_AND_PAK", True)
    with pytest.raises(ValueError, match="pane flag cave shares"):
        guard.apply_patch(_plant_chunk())
    monkeypatch.setattr(guard, "APPLY_HEAP_AND_PAK", False)
    normal = _plant_chunk()
    guard.apply_patch(normal)
    monkeypatch.setattr(guard, "APPLY_HEAP_AND_PAK", True)
    normal[guard.ADDR_HEAP_WALK : guard.ADDR_HEAP_WALK + 4] = guard.b_ins(
        guard.ADDR_HEAP_WALK, guard.ADDR_HEAP_WALK_CAVE
    )
    assert guard.is_patched(normal) is False

    monkeypatch.setattr(guard, "APPLY_HEAP_AND_PAK", False)
    monkeypatch.setattr(guard, "heap_walk_stub_addr", lambda: 0)
    with pytest.raises(ValueError, match="heap walk stub"):
        guard.apply_patch(_plant_chunk())


def test_chunk_walk_pak_table_and_flag_helpers():
    with pytest.raises(ValueError, match="not word aligned"):
        guard._thumb_blx(0x1000, 0x2002)
    with pytest.raises(ValueError, match="pak init"):
        guard.build_pak_init(guard.ADDR_PAK_INIT + 4)
    with pytest.raises(ValueError, match="fixed"):
        guard.build_pak_table_cave(0)
    with pytest.raises(ValueError, match="pak flag cave runs"):
        guard.build_pak_flag_cave(guard.ADDR_PAK_FLAG_CHECK + 4)

    table = bytearray(CODE_LEN)
    _put(table, guard.ADDR_PAK_TABLE, guard.VANILLA_PAK_TABLE)
    guard.apply_pak_table(table)
    guard.apply_pak_table(table)
    _expect_like = table
    old = bytes(_expect_like[guard.ADDR_PAK_TABLE : guard.ADDR_PAK_TABLE + 4])
    _expect_like[guard.ADDR_PAK_TABLE : guard.ADDR_PAK_TABLE + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="unexpected pak table"):
        guard.apply_pak_table(_expect_like)
    _expect_like[guard.ADDR_PAK_TABLE : guard.ADDR_PAK_TABLE + 4] = old
    cave = guard.build_pak_table_cave()
    _expect_like[guard.ADDR_PAK_TABLE_CAVE : guard.ADDR_PAK_TABLE_CAVE + len(cave)] = b"\xff" * len(cave)
    with pytest.raises(ValueError, match="pak table cave"):
        guard.apply_pak_table(_expect_like)

    from patch_input_candidate_nullguard import CAVE1
    from patch_input_candidate_nullguard import beq as cand_beq

    flag = bytearray(CODE_LEN)
    alloc = guard.build_pak_alloc_cave()
    old_tail = guard._fillcand_tail(CAVE1 + 0x10)
    _put(flag, guard.ADDR_PAK_ALLOC, guard.VANILLA_PAK_ALLOC)
    _put(flag, guard.ADDR_PAK_FLAG_CAVE, old_tail + b"\x00" * 8)
    beq_at = CAVE1 + 4
    _put(flag, beq_at, cand_beq(beq_at, CAVE1 + 0x10))
    _put(flag, guard.ADDR_PAK_FLAG, guard.VANILLA_PAK_FLAG)
    guard.apply_pak_flag(flag)
    guard.apply_pak_flag(flag)

    bad = bytearray(flag)
    bad[guard.ADDR_PAK_ALLOC : guard.ADDR_PAK_ALLOC + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="unexpected pak alloc"):
        guard.apply_pak_flag(bad)
    bad = bytearray(flag)
    bad[guard.ADDR_PAK_FLAG_CAVE : guard.ADDR_PAK_FLAG_CAVE + len(alloc)] = b"\xff" * len(alloc)
    with pytest.raises(ValueError, match="pak alloc cave"):
        guard.apply_pak_flag(bad)
    fresh = bytearray(CODE_LEN)
    _put(fresh, guard.ADDR_PAK_ALLOC, guard.VANILLA_PAK_ALLOC)
    _put(fresh, guard.ADDR_PAK_FLAG_CAVE, old_tail + b"\x00" * 8)
    _put(fresh, beq_at, cand_beq(beq_at, CAVE1 + 0x10))
    fresh[guard.ADDR_FILLCAND_TAIL : guard.ADDR_FILLCAND_TAIL + 8] = b"\xff" * 8
    with pytest.raises(ValueError, match="fillcand tail"):
        guard.apply_pak_flag(fresh)
    fresh[guard.ADDR_FILLCAND_TAIL : guard.ADDR_FILLCAND_TAIL + 8] = b"\x00" * 8
    fresh[beq_at : beq_at + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="unexpected fillcand"):
        guard.apply_pak_flag(fresh)
    fresh[beq_at : beq_at + 4] = cand_beq(beq_at, CAVE1 + 0x10)
    fresh[guard.ADDR_PAK_FLAG : guard.ADDR_PAK_FLAG + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="unexpected pak flag"):
        guard.apply_pak_flag(fresh)


# ---------------------------------------------------------------------------
# patch_textresource
# ---------------------------------------------------------------------------


def test_trb_decode_parse_and_wrap_edges(tmp_path: Path):
    missing = tmp_path / "no-lookup.txt"
    with pytest.raises(SystemExit, match="missing lookup"):
        trb.load_lookup(missing)
    look = tmp_path / "lookup.txt"
    look.write_text("A\nB\n", encoding="utf-8")
    assert trb.load_lookup(look) == ["A", "B"]

    wide = ["X"] * 300
    assert trb.nlp_get_string(b"\x01", LOOKUP) == "A"
    assert trb.nlp_get_string(b"\x00", LOOKUP) == "?"
    assert trb.nlp_get_string(b"\x09", LOOKUP) == "?"
    assert trb.nlp_get_string(b"\x81\x01", wide) == "X"
    assert trb.nlp_get_string(b"\x81", LOOKUP) == ""
    assert trb.nlp_payload_bytes(b"\x81\x00\x00", 0) == b"\x81\x00"
    assert trb.nlp_payload_bytes(b"\x81", 0) == b"\x81"
    assert trb.nlp_payload_bytes(b"\x01\x00", 0) == b"\x01"

    assert trb.decode_entry(b"", 0, 2, LOOKUP) == ("", b"")
    text, raw = trb.decode_entry(b"\xffno-nul", 0, 1, LOOKUP)
    assert raw == b"\xffno-nul"
    assert text

    with pytest.raises(ValueError, match="not a STRI"):
        trb.parse_chunks(b"NOPE")
    huge = b"STRI" + struct.pack("<I", 999999) + b"xx"
    parsed = trb.parse_chunks(huge)
    assert parsed["_tail"].startswith(b"STRI")
    bad_sig = _trb([(1, b"Hi")]) + b"\xff\xff\xff\xff\x00\x00\x00\x00"
    assert "_tail" in trb.parse_chunks(bad_sig)
    exact = _trb([(1, b"Hi")])
    assert "_tail" not in trb.parse_chunks(exact)
    leftover = exact + b"XYZ"
    assert trb.parse_chunks(leftover)["_tail"] == b"XYZ"

    assert trb.normalize_newlines("a◙b\r\nc\rd") == "a\nb\nc\nd"
    assert trb.to_game_newlines("a◙b") == "a\nb"
    assert trb.fit_wrap("hello", "あ") == "hello"
    assert trb.fit_wrap("hello", "") == "hello"
    assert trb.fit_wrap("hi", "あ" * 40) == "hi"
    assert trb.fit_wrap(" ab \n cd ", "あ", force_width=10) == "ab\ncd"
    wrapped = trb.fit_wrap("abcdefghij\nklmnopqrst", "あ", force_width=5)
    assert "\n" in wrapped
    assert trb.fit_wrap("abcdef\nghijkl", "あ\nい", force_width=4).count("\n") >= 1
    assert trb.fit_wrap("short\nok", "あ\nい") == "short\nok"
    assert trb.fit_wrap("   \n  ", "あ\nい") == "\n"
    assert trb.fit_wrap("   ", "あ\nい") == "   "
    assert trb._soft_wrap_words(["one", "two"], 3) == ["one", "two"]


def test_trb_rebuild_restore_inplace_and_seed(tmp_path: Path):
    data = _trb(
        [
            (2, b""),
            (1, b""),
            (0, b"\x01"),
            (1, "Why?".encode()),
            (1, "a\nb".encode()),
            (1, "いつの間に通信の◙受信データがありません。".encode()),
        ],
        extra=[("CONF", b"keep")],
        tail=b"XYZ",
    )
    mapping = {"Why?": "Yes?", "a◙b": "Line", trb.PATCHES[0][0]: trb.PATCHES[0][1]}
    out, stats = trb.rebuild_trb(data, mapping, LOOKUP)
    assert stats["empty"] == 1
    assert stats["translated"] == 3
    assert stats["kept"] == 2
    entries = trb.dump_entries(out, LOOKUP)
    assert entries[0]["flag"] == 2
    assert entries[2]["text"] == "A"
    assert "Yes？" in entries[3]["text"]
    assert entries[4]["text"] == "Line"
    chunks = trb.parse_chunks(out)
    assert chunks["CONF"] == b"keep"
    assert chunks["_tail"] == b"XYZ"

    token = "Hello ▲Protagonist＊▲".encode()
    restored_src = _trb(
        [(2, b""), (1, b""), (1, token)],
        extra=[("CONF", b"c")],
        tail=b"T",
    )
    restored, rst = trb.restore_control_tokens_in_trb(restored_src, LOOKUP)
    assert rst["empty"] == 1 and rst["kept"] == 1 and rst["restored"] == 1
    assert "主人公" in trb.dump_entries(restored, LOOKUP)[2]["text"]
    assert trb.parse_chunks(restored)["_tail"] == b"T"

    marker = "▲小早川＊▲".encode()
    stay = b"Z"
    marked = _trb([(2, b""), (1, marker), (1, stay)], tail=b"Q")
    rewritten, count = trb.rewrite_rinko_marker_in_trb(marked, LOOKUP)
    assert count == 1
    assert trb.parse_chunks(rewritten)["_tail"] == b"Q"
    again, count2 = trb._rewrite_marker_slots(rewritten, LOOKUP, lambda text: text, "same")
    assert count2 == 0 and again == rewritten

    tight = _trb([(1, b"AB"), (1, b"CD")])
    with pytest.raises(ValueError, match="marker needs"):
        trb._rewrite_marker_slots(tight, LOOKUP, lambda text: "MUCH LONGER", "Rinko")

    calls = {"n": 0}

    def _flip(text: str) -> str:
        calls["n"] += 1
        return "A" if calls["n"] == 1 else "BB"

    shared = _trb([(1, b"HELLO"), (1, b"HELLO")])
    # Point both entries at the same STRB slot.
    stri = bytearray(trb.parse_chunks(shared)["STRI"])
    struct.pack_into("<IHH", stri, 8, 0, 5, 1)
    chunks = trb.parse_chunks(shared)
    body = _chunk("STRI", bytes(stri)) + _chunk("STRB", chunks["STRB"])
    with pytest.raises(ValueError, match="rewrites disagree"):
        trb._rewrite_marker_slots(body, LOOKUP, _flip, "Rinko")

    spot = trb.PATCHES[0][0].encode()
    src = _trb([(1, spot), (1, b"other")])
    patched, logs = trb.patch_inplace(src, trb.PATCHES, LOOKUP)
    assert logs and b"SpotPass" in patched
    with pytest.raises(ValueError, match="not found"):
        trb.patch_inplace(_trb([(1, b"nope")]), [("missing", "x")], LOOKUP)
    with pytest.raises(ValueError, match="only has"):
        trb.patch_inplace(_trb([(1, b"AB"), (1, b"CD")]), [("AB", "TOO-LONG-FOR-SLOT")], LOOKUP)

    assert trb.slot_room(trb.parse_chunks(src)["STRI"], 10, 0) > 0
    cfg = bytearray(b"SIZE" + b"\x00" * 8)
    updated = trb.update_config_size(bytes(cfg), 99)
    assert struct.unpack_from("<I", updated, 8)[0] == 99
    with pytest.raises(ValueError, match="SIZE"):
        trb.update_config_size(b"NOPE" + b"\x00" * 8, 1)

    assert trb.load_translations(tmp_path / "missing.json") == {}
    nested = tmp_path / "nested.json"
    nested.write_text(json.dumps({"translations": {"a": "b", "n": 1}}), encoding="utf-8")
    assert trb.load_translations(nested) == {"a": "b", "n": "1"}
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps({"k": "v", "skip": 1}), encoding="utf-8")
    assert trb.load_translations(flat) == {"k": "v"}
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        trb.load_translations(bad)
    dest = tmp_path / "sub" / "out.json"
    trb.save_translations(dest, {"a": "b"})
    assert trb.load_translations(dest)["a"] == "b"

    van = _trb([(1, "漢字".encode()), (1, "同じ".encode()), (1, b""), (1, "残".encode())])
    alt = _trb([(1, b"Kanji"), (1, "同じ".encode()), (1, b"X"), (1, "まだ".encode())])
    seeded = trb.seed_from_alt_trb(van, alt, LOOKUP)
    assert seeded["漢字"] == "Kanji"
    assert "同じ" not in seeded and "" not in seeded and "残" not in seeded
    with pytest.raises(ValueError, match="entry count"):
        trb.seed_from_alt_trb(van, _trb([(1, b"only")]), LOOKUP)


def test_trb_commands(tmp_path: Path, monkeypatch, capsys):
    look = tmp_path / "lookup.txt"
    look.write_text("A\n", encoding="utf-8")
    spot = trb.PATCHES[0][0].encode()
    src = tmp_path / "textresource_jpn.trb"
    src.write_bytes(
        _trb(
            [
                (1, "漢字".encode()),
                (1, b"Hello"),
                (1, spot),
                (1, "短い\n行".encode()),
            ]
        )
    )
    cfg = tmp_path / "textresource_config.trb"
    cfg.write_bytes(b"SIZE" + b"\x00" * 8)
    trans = tmp_path / "translations.json"
    trb.save_translations(trans, {"漢字": "Kanji"})
    parser = trb.build_parser()

    dump_jsonl = tmp_path / "out" / "dump.jsonl"
    args = parser.parse_args(["--lookup", str(look), "dump", "--trb", str(src), "--out", str(dump_jsonl)])
    assert trb.cmd_dump(args) == 0
    assert dump_jsonl.read_text(encoding="utf-8").splitlines()
    dump_json = tmp_path / "dump.json"
    args = parser.parse_args(["--lookup", str(look), "dump", "--trb", str(src), "--out", str(dump_json)])
    assert trb.cmd_dump(args) == 0
    assert dump_json.suffix == ".json"

    alt = tmp_path / "alt.trb"
    alt.write_bytes(_trb([(1, b"Kanji"), (1, b"Hello"), (1, b"No SpotPass"), (1, b"Short")]))
    seed_path = tmp_path / "seed.json"
    trb.save_translations(seed_path, {"漢字": "KeepMine"})
    args = parser.parse_args(
        ["--lookup", str(look), "seed", "--trb", str(src), "--alt-trb", str(alt), "--translations", str(seed_path)]
    )
    assert trb.cmd_seed(args) == 0
    assert trb.load_translations(seed_path)["漢字"] == "KeepMine"

    out_trb = tmp_path / "re" / "textresource_jpn.trb"
    cfg_out = tmp_path / "re" / "textresource_config.trb"
    az = tmp_path / "azahar"
    monkeypatch.setattr(trb, "AZAHAR_DIR", az)
    import report_progress as rp

    monkeypatch.setattr(rp, "try_report_progress", lambda **k: (_ for _ in ()).throw(RuntimeError("down")))
    args = parser.parse_args(
        [
            "--lookup",
            str(look),
            "rebuild",
            "--trb",
            str(src),
            "--translations",
            str(trans),
            "--out",
            str(out_trb),
            "--config-out",
            str(cfg_out),
            "--min-config-size",
            "5000",
            "--deploy-azahar",
        ]
    )
    assert trb.cmd_rebuild(args) == 0
    assert out_trb.is_file() and cfg_out.is_file()
    assert (az / "textresource_jpn.trb").is_file()
    assert (az / "textresource_config.trb").is_file()
    err = capsys.readouterr().err
    assert "soft-fail" in err

    monkeypatch.setattr(rp, "try_report_progress", lambda **k: False)
    args = parser.parse_args(
        [
            "--lookup",
            str(look),
            "rebuild",
            "--trb",
            str(src),
            "--translations",
            str(trans),
            "--out",
            str(tmp_path / "re2.trb"),
            "--config",
            str(cfg),
            "--config-out",
            str(tmp_path / "cfg2.trb"),
        ]
    )
    assert trb.cmd_rebuild(args) == 0

    inplace = tmp_path / "inplace.trb"
    args = parser.parse_args(["--lookup", str(look), "inplace", "--trb", str(src), "--out", str(inplace)])
    assert trb.cmd_inplace(args) == 0
    assert b"SpotPass" in inplace.read_bytes()

    args = parser.parse_args(["--lookup", str(look), "stats", "--trb", str(src), "--translations", str(trans)])
    assert trb.cmd_stats(args) == 0
    args.translations = None
    assert trb.cmd_stats(args) == 0

    en = tmp_path / "en.trb"
    en.write_bytes(
        _trb(
            [
                (1, b""),
                (1, "漢字".encode()),
                (1, "漢字だけ".encode()),
                (1, b"this english line is definitely wider than the japanese budget allows"),
            ]
        )
    )
    re_out = tmp_path / "rewrap.trb"
    upd = tmp_path / "wrap.json"
    args = parser.parse_args(
        [
            "--lookup",
            str(look),
            "rewrap",
            "--trb",
            str(src),
            "--en-trb",
            str(en),
            "--out",
            str(re_out),
            "--config-out",
            str(tmp_path / "rewrap-config.trb"),
            "--update-translations",
            str(upd),
            "--verbose",
            "--min-config-size",
            "80",
            "--deploy-azahar",
        ]
    )
    (az / "textresource_jpn.trb").write_bytes(b"old")
    assert trb.cmd_rewrap(args) == 0
    assert upd.is_file()
    assert (az / "textresource_jpn.trb.bak_pre_rewrap").is_file()
    assert trb.cmd_rewrap(args) == 0
    short = tmp_path / "short.trb"
    short.write_bytes(_trb([(1, b"only")]))
    args = parser.parse_args(
        ["--lookup", str(look), "rewrap", "--trb", str(src), "--en-trb", str(short), "--out", str(re_out)]
    )
    with pytest.raises(SystemExit, match="entry count"):
        trb.cmd_rewrap(args)

    monkeypatch.setattr(sys, "argv", ["patch_textresource.py", "--lookup", str(look), "stats", "--trb", str(src)])
    assert trb.main() == 0


@pytest.mark.parametrize(
    ("src", "want"),
    [
        ("", ""),
        ("   ", ""),
        ("１２３：／", "123:/"),
        ("５時", "5:00"),
        ("３月", "March"),
        ("１３月", "13 month(s)"),
        ("３日", "3"),
        ("１５日", "1 5"),
        ("３２日", "32 day(s)"),
        ("２人", "2 people"),
        ("４個", "4"),
        ("時", "Time"),
        ("不可", "No"),
        ("名", "Name"),
        ("hello", None),
    ],
)
def test_local_translate_rules(src: str, want: str | None):
    assert trb.local_translate(src) == want


def test_openai_key_batch_and_translate(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert trb.load_openai_api_key("  key  ") == "key"
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert trb.load_openai_api_key() == "from-env"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = tmp_path / "root"
    root.mkdir()
    (root / ".env").write_text("# c\nFOO=1\nOPENAI_API_KEY=\nOPENAI_API_KEY='abc'\n", encoding="utf-8")
    monkeypatch.setattr(trb, "ROOT", root)
    assert trb.load_openai_api_key() == "abc"
    monkeypatch.setattr(trb, "ROOT", tmp_path / "empty")
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        trb.load_openai_api_key()

    class _Msg:
        def __init__(self, content):
            self.content = content

    class _Client:
        def __init__(self, content):
            self.content = content

            class _Completions:
                def create(_self, **kwargs):
                    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=_Msg(content))])

            self.chat = types.SimpleNamespace(completions=_Completions())

    texts = ["あ", "い", "う"]
    body = json.dumps(
        {
            "items": [
                {"i": 0, "t": "Hi?"},
                {"i": 1, "s": "echo"},
                "nope",
                {"i": 2, "t": "日本語がたくさん残っている文章です"},
            ]
        }
    )
    got = trb.openai_translate_batch(_Client(body), "m", texts, 0)
    assert got[0] == "Hi？"
    assert got[1] is None and got[2] is None
    assert trb.openai_translate_batch(_Client("{}"), "m", ["あ"], 0) == [None]
    assert trb.openai_translate_batch(_Client(None), "m", ["あ"], 3) == [None]
    with pytest.raises(AttributeError):
        trb.openai_translate_batch(_Client("[1, 2]"), "m", ["あ"], 0)

    mod = types.ModuleType("openai")
    monkeypatch.setitem(sys.modules, "openai", mod)
    look = tmp_path / "lookup.txt"
    look.write_text("A\n", encoding="utf-8")
    src = tmp_path / "t.trb"
    src.write_bytes(_trb([(1, "こんにちは".encode()), (1, "５時".encode()), (1, "さようなら".encode())]))
    trans = tmp_path / "map.json"
    trans.write_text("{}", encoding="utf-8")
    parser = trb.build_parser()
    args = parser.parse_args(
        [
            "--lookup",
            str(look),
            "translate",
            "--trb",
            str(src),
            "--translations",
            str(trans),
            "--api-key",
            "k",
            "--workers",
            "1",
            "--batch-size",
            "2",
            "--sleep",
            "0",
            "--keep-failed",
        ]
    )
    with pytest.raises(SystemExit, match="openai package missing"):
        trb.cmd_translate_remaining(args)

    class _OpenAI:
        def __init__(self, api_key):
            self.api_key = api_key

    mod.OpenAI = _OpenAI
    state = {"n": 0}

    def _batch(client, model, chunk, start):
        state["n"] += 1
        if len(chunk) > 1:
            raise RuntimeError("batch")
        if chunk[0].startswith("さ"):
            raise RuntimeError("item")
        return ["Hello"]

    monkeypatch.setattr(trb, "openai_translate_batch", _batch)
    assert trb.cmd_translate_remaining(args) == 0
    saved = trb.load_translations(trans)
    assert saved["５時"] == "5:00"
    assert "こんにちは" in saved
    assert saved["さようなら"] == "さようなら"

    args.limit = 1
    args.keep_failed = False
    state["n"] = 0
    monkeypatch.setattr(trb, "openai_translate_batch", lambda *a, **k: ["Ok"])
    assert trb.cmd_translate_remaining(args) == 0


# ---------------------------------------------------------------------------
# live_status
# ---------------------------------------------------------------------------


class _Raw:
    encoding = "utf-8"

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.unicode = False
        self.flush_error = False

    def write(self, s: str) -> int:
        if self.unicode and any(ord(ch) > 127 for ch in s):
            self.unicode = False
            raise UnicodeEncodeError("ascii", s, 0, 1, "ordinal")
        self.parts.append(s)
        return len(s)

    def flush(self) -> None:
        if self.flush_error:
            raise OSError("flush")

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 1


def _pin(monkeypatch, *, cols: int = 100, rows: int = 24):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("NLPP_PLAIN_LOG", raising=False)
    monkeypatch.setattr(live, "enable_vt", lambda: True)
    monkeypatch.setattr(
        live.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((cols, rows)),
    )
    raw = _Raw()
    monkeypatch.setattr(sys, "stdout", raw)
    status = live.LiveStatus()
    owner = types.SimpleNamespace(label="job", stage="s", elapsed_str=lambda: "1s")
    assert status.try_acquire(owner) is True
    return status, raw


def test_live_vt_stdio_and_plain_flags(monkeypatch):
    monkeypatch.setattr(live.os, "name", "posix")
    assert live.enable_vt() is True

    monkeypatch.setattr(live.os, "name", "nt")

    class _Mode:
        def __init__(self) -> None:
            self.value = 0

    class _K32:
        def __init__(self) -> None:
            self.mode = 0
            self.get_ok = True
            self.set_ok = True

        def GetStdHandle(self, handle):
            return 1

        def GetConsoleMode(self, handle, mode):
            mode.value = self.mode
            return 1 if self.get_ok else 0

        def SetConsoleMode(self, handle, mode):
            return 1 if self.set_ok else 0

    k32 = _K32()

    class _Ctypes:
        windll = types.SimpleNamespace(kernel32=k32)

        @staticmethod
        def c_uint():
            return _Mode()

        @staticmethod
        def byref(obj):
            return obj

    monkeypatch.setitem(sys.modules, "ctypes", _Ctypes())
    k32.get_ok = False
    assert live.enable_vt() is False
    k32.get_ok = True
    k32.set_ok = False
    assert live.enable_vt() is False
    k32.set_ok = True
    k32.mode = 0x4
    assert live.enable_vt() is True
    k32.mode = 0
    assert live.enable_vt() is True

    class _Boom:
        @property
        def windll(self):
            raise AttributeError("no console")

    monkeypatch.setitem(sys.modules, "ctypes", _Boom())
    assert live.enable_vt() is False

    class _BoomOS:
        @property
        def windll(self):
            raise OSError("no console")

    monkeypatch.setitem(sys.modules, "ctypes", _BoomOS())
    assert live.enable_vt() is False

    class _NoRec:
        pass

    class _Bad:
        def reconfigure(self, **kwargs):
            raise OSError("no")

    monkeypatch.setattr(sys, "stdout", _NoRec())
    monkeypatch.setattr(sys, "stderr", _Bad())
    live.relax_stdio_errors()

    for value in ("yes", "on", " true "):
        monkeypatch.setenv("NLPP_PLAIN_LOG", value)
        assert live.plain_log_requested() is True
    monkeypatch.delenv("NLPP_PLAIN_LOG", raising=False)
    assert live.plain_log_requested() is False


def test_live_render_color_and_stream_edges(monkeypatch):
    assert "0/1" in live.render_bar(0, 0)
    assert live.render_bar(0, 4, width=4).count(" ") > 2
    assert "=" in live.render_bar(9, 3, width=4)
    assert live.render_bar(1, 4, prefix="", width=4).startswith("  [")
    assert "0.0%" in live.render_percent(-1, width=1)
    assert live.render_percent(100, width=4).count("=") == 4
    assert "[" in live.render_percent(10, detail="", width=0)
    assert live.latest_progress_line("\n\n") == ""
    assert live.latest_progress_line("  a  \r") == "a"

    monkeypatch.setenv("NO_COLOR", "1")
    assert live.colors_enabled() is False
    assert live.colorize_bracket_line("[pack] x") == "[pack] x"
    assert live.colorize_chunk("[pack] x") == "[pack] x"
    assert live.paint("a", "31") == "a"
    assert live.color_bar(0.5, 4) == "[" + live._bar_body(0.5, 4) + "]"
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert live.paint("", "31") == ""
    assert "\033[32m" in live.color_bar(1, 4)
    assert "\033[92m" in live.color_bar(0.5, 4)
    assert "\033[90m" in live.color_bar(0, 4)
    assert live.colorize_bracket_line("") == ""
    assert live.colorize_bracket_line("\033[31m[pack] x") == "\033[31m[pack] x"
    assert live.colorize_bracket_line("plain") == "plain"
    assert live.colorize_chunk("") == ""
    assert live.colorize_chunk("plain") == "plain"
    colored = live.colorize_chunk("a [pack] z\nb")
    assert "\033[" in colored and colored.endswith("b")
    assert live.tag_color("  Pack ") == "36"
    assert live.tag_color("failed-step") == "91"
    assert live.tag_color("err") == "91"
    assert live.tag_color("zzz") in live._TAG_PALETTE
    assert live.visible_len("\033[31mab\033[0m") == 2
    assert live.fit_visible("hello", 0) == ""
    assert live.fit_visible("hi", 10) == "hi"
    assert live.fit_visible("abcdef", 4) == "abc…"
    clipped = live.fit_visible("\033[31mHELLO\033[0m", 4)
    assert clipped.endswith("\033[0m") and "…" in clipped
    assert live._clip("hello", "hello") == "hello"
    assert live._clip("hello", "") == ""
    assert live._clip("hello", "h") == "…"
    assert live._clip("hello", "hel") == "he…"

    lines: list[str] = []
    stream = live.StatusStream(lines.append)
    assert stream.write("") == 0
    assert stream.write("partial") == 7
    assert lines == []
    stream.flush()
    assert lines == ["partial"]
    stream.flush()
    stream.write("a\rb")
    assert lines[-1] == "b"
    stream.write("  \r")
    assert stream.isatty() is False
    all_lines: list[str] = []
    both = live.StatusStream(all_lines.append, emit_all=True)
    both.write("a\nb\n")
    assert all_lines == ["a", "b"]
    both.write("keep")
    assert both.write("\r\n") == 2


def test_live_acquire_release_and_status_line(monkeypatch, capsys):
    monkeypatch.setattr(live, "enable_vt", lambda: False)
    quiet = live.LiveStatus()
    assert quiet.try_acquire(object()) is False
    assert quiet.owner is None
    quiet.set_progress(1, 2, "x")
    quiet.set_overall(1, "y")
    quiet.set_job("k", "z")
    quiet.clear_job("k")
    quiet.clear_jobs()
    quiet.log("")
    quiet.log("printed")
    quiet.refresh()
    assert "printed" in capsys.readouterr().out
    assert quiet._clock() == ("", "")

    status, raw = _pin(monkeypatch)
    other = types.SimpleNamespace(label="other", elapsed_str=lambda: "2s")
    status.set_job("a", "one")
    status.set_job("b", "two")
    assert status.try_acquire(other) is True
    assert status._jobs == {}
    assert status.owner is other
    status.release(object())
    status.release(other)
    assert status.owner is not None
    status._last_paint = 0
    status.set_progress(3, 9, "pkgs")
    status.set_overall(12.5, "detail")
    status.set_job("k", "x" * 200)
    assert status._jobs["k"].endswith("…") and len(status._jobs["k"]) == 180
    status.set_job("k", "[pack] file")
    status.clear_job("missing")
    status.clear_job("k")
    status.clear_jobs()
    status.log("[warn] hello")
    n = len(raw.parts)
    status._last_paint = live.time.monotonic()
    status.refresh()
    assert len(raw.parts) == n
    status.refresh(force=True)
    assert len(raw.parts) > n

    status._owner = types.SimpleNamespace(label="L" * 40, elapsed_str=lambda: "99h")
    status._progress = (1, 10, "D" * 30)
    status._overall = None
    status._jobs = {1: "J" * 30}
    assert status._status_line(16)
    assert "1/10" in status._status_line(120)
    status._overall = (12.5, "detail")
    assert "12.5%" in status._status_line(120)
    status._jobs = {1: "plain-job"}
    assert "plain-job" in status._status_line(200)
    status._owner = types.SimpleNamespace(label="GitHub bake", elapsed_str=lambda: "2s")
    assert "95" in status._status_line(100)
    monkeypatch.setenv("NO_COLOR", "1")
    assert "\033" not in status._status_line(100)
    monkeypatch.delenv("NO_COLOR", raising=False)
    status._owner = None
    status._overall = None
    status._progress = None
    status._jobs = {1: "onlyjob"}
    assert "onlyjob" in status._status_line(80)
    status._jobs.clear()
    assert status._status_line(80) == ""
    status._paint_body()
    monkeypatch.setattr(
        live.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((80, 4)),
    )
    status._owner = types.SimpleNamespace(label="job", elapsed_str=lambda: "1s")
    status._paint_body()
    monkeypatch.setattr(
        live.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((80, 24)),
    )
    status._anchored = True
    status._pin_rows = 3
    status._paint_body()
    status._anchored = True
    status._pin_rows = 0
    status._paint_body()

    wrapped = sys.stdout
    assert wrapped.write("") == 0
    assert wrapped.isatty() is True
    assert wrapped.fileno() == 1
    assert wrapped.encoding == "utf-8"
    status._raw.marker = 5
    assert wrapped.marker == 5
    assert wrapped.write("hi\n") == 3
    wrapped.flush()
    raw.unicode = True
    status._write_raw("日")
    assert any("日" in part or "?" in part for part in raw.parts)
    raw.flush_error = True
    status._flush()
    def _boom_size(fallback=(80, 24)):
        raise ValueError("size")

    monkeypatch.setattr(live.shutil, "get_terminal_size", _boom_size)
    status._paint_unlocked()
    raw.flush_error = False

    class _Boom:
        def write(self, s):
            raise OSError("no")

        def flush(self):
            raise OSError("no")

    status._raw = _Boom()
    status.shutdown()
    assert status.active is False
    status.shutdown()


# ---------------------------------------------------------------------------
# patch_cesa (no full-size zopfli)
# ---------------------------------------------------------------------------


def test_cesa_helpers_and_deploy(tmp_path: Path, monkeypatch):
    pkg = fi.package([(cesa.CESA_TEX_NAME, b"cesa-tex-payload", b"TEX ", True)])
    rows = list(cesa._iter_pack_entries(pkg))
    assert rows and rows[0][0] == 0
    assert cesa._align_pack(0) == 0
    assert cesa._align_pack(1) % cesa.PACK_ALIGN == 0

    monkeypatch.setattr(cesa, "_try_zlib_exact_candidate", lambda out, data: False)
    with pytest.raises(RuntimeError, match="unused_data"):
        cesa.compress_tex_best(b"abc")


def test_cesa_exact_zlib_without_zopfli(monkeypatch):
    real_import = builtins.__import__

    def _block(name, globals=None, locals=None, fromlist=(), level=0):
        if str(name).startswith("zopfli"):
            raise ImportError("blocked")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _block)
    data = b"hi"
    taken = {len(zlib.compress(data, level)) for level in range(10)}
    exact = None
    for length in range(8, 160):
        if length in taken:
            continue
        try:
            exact = cesa.compress_zlib_exact(data, length)
        except RuntimeError:
            continue
        break
    assert exact is not None and len(exact) not in taken
    assert zlib.decompress(exact) == data
    assert zlib.decompress(cesa.compress_tex_best(b"abc")) == b"abc"


def test_cesa_main_deploys_without_full_texture(tmp_path: Path, monkeypatch):
    tex = b"cesa-tex-payload"
    src = tmp_path / "img.bin"
    src.write_bytes(fi.img({90: fi.package([(cesa.CESA_TEX_NAME, tex, b"TEX ", True)])}))
    out = tmp_path / "out.bin"
    work = tmp_path / "work"
    real_path = cesa.Path

    def _path(p, *args, **kwargs):
        if isinstance(p, str) and "Azahar" in p:
            return tmp_path / "az" / "img.bin"
        return real_path(p, *args, **kwargs)

    monkeypatch.setattr(cesa, "Path", _path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["patch_cesa", "--img", str(src), "--recompress-only", "--out", str(out), "--work", str(work), "--deploy-azahar"],
    )
    assert cesa.main() == 0
    assert out.is_file()
    assert (tmp_path / "az" / "img.bin").is_file()


# ---------------------------------------------------------------------------
# patch_code
# ---------------------------------------------------------------------------


def _plant_code() -> bytearray:
    data = bytearray(0x00191000)
    _put(data, code.ADDR_CLEAR, code.ORIG_CLEAR_HEAD)
    _put(data, code.ADDR_SET, code.ORIG_SET_HEAD)
    _put(data, code.ADDR_BACKSPACE, code.ORIG_BACK_HEAD)
    _put(data, code.ADDR_PANE_SIZE, code.ORIG_PANE_SIZE)
    _put(data, code.ADDR_CESA_FACTORY, code.ORIG_CESA_FACTORY_HEAD)
    struct.pack_into("<I", data, code.ADDR_CESA_DURATION, code.ORIG_CESA_DURATION)
    _put(data, code.ADDR_CESA_LOGO_WHITE_BNE, code.ORIG_CESA_LOGO_WHITE_BNE)
    _put(data, code.ADDR_NINTENDO_LOGO_TEX_ID, code.ORIG_NINTENDO_LOGO_TEX_ID)
    return data


def test_code_assemble_edges_and_pane_errors(monkeypatch):
    with pytest.raises(ValueError, match="cannot encode"):
        code.encode_imm12(0x101)
    assert code._assemble_stream(1, [("lit", "p", 5), ("label", "z")])
    assert code._assemble_stream(0, [("op", b"\x11"), ("lit", "p", 5)])
    padded = code._assemble_stream(
        0,
        [("ldr", 0, "p"), ("op", code.nop()), ("lit", "p", 5), ("b", "p", None), ("b", "p", 0), ("bl", 0x1000)],
    )
    assert padded
    with pytest.raises(ValueError):
        code._assemble_stream(0, [("nope",)])
    monkeypatch.setattr(code, "SIZE_SET", 4)
    with pytest.raises(ValueError, match="SetName too large"):
        code.assemble_set_name()
    monkeypatch.setattr(code, "SIZE_BACKSPACE", 4)
    with pytest.raises(ValueError, match="Backspace too large"):
        code.assemble_backspace()
    monkeypatch.setattr(code, "PANE_SIZE_LEN", 99)
    with pytest.raises(RuntimeError, match="0x2c"):
        code.apply_name_pane_patches(bytearray(16))


def test_code_bin_patches_and_cli(tmp_path: Path, monkeypatch, capsys):
    data = _plant_code()
    assert code.is_vanilla_code(data) is True
    assert code.apply_name_pane_patches(data) is True
    assert code.is_patched_code(data) is True
    assert code.is_wide_name_panes(data) is True
    assert code.apply_name_pane_patches(data) is False
    assert code.apply_wide_name_glyph_panes(data) is False

    draw_only = _plant_code()
    draw_only[code.ADDR_CLEAR : code.ADDR_CLEAR + 4] = bytes.fromhex("04109fe5")
    assert code.apply_name_pane_patches(draw_only) is True

    bad_pane = _plant_code()
    bad_pane[code.ADDR_PANE_SIZE : code.ADDR_PANE_SIZE + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="CreateTextPane"):
        code.apply_wide_name_glyph_panes(bad_pane)
    with pytest.raises(ValueError, match="does not look like vanilla"):
        code.apply_name_pane_patches(bytearray(code.ADDR_BACKSPACE + 8))

    cesa_buf = _plant_code()
    assert code.patch_skip_cesa_logo(cesa_buf) is True
    assert code.patch_skip_cesa_logo(cesa_buf) is False
    assert code.patch_cesa_logo_white_native_size(cesa_buf) is True
    assert code.patch_cesa_logo_white_native_size(cesa_buf) is False
    assert code.patch_nintendo_logo_skip_thank_flash(cesa_buf) is True
    assert code.patch_nintendo_logo_skip_thank_flash(cesa_buf) is False
    assert code.patch_cesa_duration(cesa_buf, duration=5) is True
    assert code.patch_cesa_duration(cesa_buf, duration=5) is False
    broken = _plant_code()
    broken[code.ADDR_CESA_FACTORY : code.ADDR_CESA_FACTORY + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="CesaLogo factory"):
        code.patch_skip_cesa_logo(broken)
    broken = _plant_code()
    broken[code.ADDR_CESA_LOGO_WHITE_BNE : code.ADDR_CESA_LOGO_WHITE_BNE + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="logo_white"):
        code.patch_cesa_logo_white_native_size(broken)
    broken = _plant_code()
    broken[code.ADDR_NINTENDO_LOGO_TEX_ID : code.ADDR_NINTENDO_LOGO_TEX_ID + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="NintendoLogo"):
        code.patch_nintendo_logo_skip_thank_flash(broken)

    path = tmp_path / "code.bin"
    path.write_bytes(_plant_code())
    assert code.patch_code_bin(path, skip_cesa_logo=True, cesa_duration=5) is True
    assert path.with_suffix(".bin.bak").is_file()
    assert code.patch_code_bin(path, skip_cesa_logo=True, cesa_duration=5) is False

    garbage = tmp_path / "garbage.bin"
    garbage.write_bytes(b"\x00" * (code.ADDR_BACKSPACE + 16))
    bak = garbage.with_suffix(".bin.bak")
    bak.write_bytes(_plant_code())
    assert code.patch_code_bin(garbage) is True
    alien = tmp_path / "alien.bin"
    alien_bytes = bytearray(b"\x11" * (code.ADDR_BACKSPACE + 16))
    _put(alien_bytes, code.ADDR_PANE_SIZE, code.ORIG_PANE_SIZE)
    alien.write_bytes(alien_bytes)
    alien.with_suffix(".bin.bak").write_bytes(b"\x22" * 32)
    with pytest.raises(ValueError, match="does not look like vanilla"):
        code.patch_code_bin(alien)
    assert code.patch_code_bin(alien, force=True) is True

    src = tmp_path / "src.bin"
    src.write_bytes(_plant_code())
    dest = tmp_path / "nested" / "out.bin"
    assert code.write_patched_code_bin(src, dest) == dest
    assert dest.is_file()
    assert code.write_patched_code_bin(dest, dest) == dest

    with pytest.raises(SystemExit, match="missing"):
        code.main([str(tmp_path / "missing.bin")])
    monkeypatch.setattr(code, "require_vanilla_code", lambda: (_ for _ in ()).throw(FileNotFoundError("no code")))
    with pytest.raises(SystemExit, match="no code"):
        code.main([])
    monkeypatch.setattr(code, "require_vanilla_code", lambda: src)
    out = tmp_path / "cli-out.bin"
    assert code.main(["--cesa-only", "--cesa-duration", "7", "--out", str(out)]) == 0
    assert out.is_file()
    assert "using" in capsys.readouterr().out
    assert code.main([str(src), "--skip-cesa-logo", "--force"]) == 0


# ---------------------------------------------------------------------------
# patch_names
# ---------------------------------------------------------------------------


def _mini_dbin(dialogs: list[str]) -> bytes:
    unk = names.UnknownEntry([names.SectionAEntry(1, 2)], 3, 4)
    sdl = names.SDL2Data(7, [unk], dialogs)
    return names.build_dbin2(9, 3, [names.DbinEntry(1, 2, sdl), names.DbinEntry(8, 9, sdl)])


def test_names_sdl_exact_and_trees(tmp_path: Path, monkeypatch, capsys):
    with pytest.raises(ValueError, match="SDL2"):
        names.parse_sdl2(b"NOPE")
    with pytest.raises(ValueError, match="DBN2"):
        names.parse_dbin2(b"NOPE")
    with pytest.raises(ValueError, match="dialog too long"):
        names.build_sdl2(names.SDL2Data(1, [], ["x" * 70000]))

    blob = _mini_dbin(["A", "▲高嶺＊＊▲"])
    key, unknown, entries = names.parse_dbin2(blob)
    assert key == 9 and unknown == 3
    assert entries[0].sdl2.unknown[0].values[0].value1 == 2
    assert entries[1].sdl2.dialogs[0] == "A"
    assert names.rewrite_nene_surname_speakers(b"NO") == b"NO"
    assert names.rewrite_manaka_surname_speakers(b"NO") == b"NO"
    assert names.rewrite_rinko_surname_speakers(b"NO") == b"NO"
    assert names.rewrite_nene_nickname_tokens(b"NO") == b"NO"
    assert names.rewrite_manaka_nickname_tokens(b"NO") == b"NO"
    assert names.rewrite_rinko_nickname_tokens(b"NO") == b"NO"
    plate = _mini_dbin(["Nene"])
    parsed = names.parse_dbin2(names.rewrite_nene_surname_speakers(plate))
    assert parsed[2][0].sdl2.dialogs == ["Anegasaki"]

    buf = bytearray(b"x" + "高嶺".encode() + b"y")
    assert names.replace_exact_cstring(buf, "高嶺", "Takane") == 0
    exact = bytearray(b"\x00" + "高嶺".encode() + b"\x00")
    assert names.replace_exact_cstring(exact, "高嶺", "Takane") == 1
    assert b"Takane" in exact
    with pytest.raises(ValueError, match="empty C string"):
        names.replace_exact_cstring(bytearray(b"\x00"), "", "a")
    assert names.replace_all(bytearray(b"none"), "高嶺", "Takane") == 0
    assert names.patch_dbin2_file(tmp_path / "unused.dbin2", strip_tokens=False) == 0
    assert names.patch_dbin2_tree(tmp_path, strip_tokens=False) == (0, 0)
    assert names.patch_dbin2_tree(tmp_path / "empty-tree", strip_tokens=True) == (0, 0)

    tree = tmp_path / "scripts"
    (tree / "NLP_01").mkdir(parents=True)
    dbin = tree / "NLP_01" / "a.dbin2"
    dbin.write_bytes(_mini_dbin(["▲高嶺＊＊▲ says"]))
    touched, repl = names.patch_dbin2_tree(tree, strip_tokens=True)
    assert touched == 1 and repl >= 1
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "b.dbin2").write_bytes(_mini_dbin(["plain"]))
    assert names.patch_dbin2_tree(flat, strip_tokens=True) == (0, 0)

    res = tmp_path / "resident.trb"
    res.write_bytes(b"\x00" + "高嶺".encode() + b"\x00")
    assert names.patch_resident_file(res) >= 1
    assert b"Takane" in res.read_bytes()
    plain = tmp_path / "plain.trb"
    plain.write_bytes(b"hello")
    assert names.patch_resident_file(plain) == 0
    assert plain.read_bytes() == b"hello"

    tiny = tmp_path / "img.bin"
    tiny.write_bytes(b"x")
    with pytest.raises(ValueError, match="too small"):
        names.patch_img_name_table(tiny)
    monkeypatch.setattr(names, "IMG_NAME_REGION", (0, 16))
    img = tmp_path / "small-img.bin"
    window = bytearray(16)
    window[:7] = "高嶺".encode() + b"\x00"
    img.write_bytes(window)
    assert names.patch_img_name_table(img) >= 1
    assert names.patch_img_name_table(img) == 0

    romfs = tmp_path / "romfs"
    (romfs / "script" / "bin").mkdir(parents=True)
    stats = names.apply_romfs_name_patches(romfs)
    assert stats["resident"] == 0 and stats["img"] == 0
    (romfs / "script" / "bin" / "c.dbin2").write_bytes(_mini_dbin(["▲高嶺＊＊▲"]))
    stats = names.apply_romfs_name_patches(romfs, strip_dialog_tokens=True)
    assert stats["dbin_files"] == 1
    resident = romfs / "SystemData" / "TextResource" / "textresource_resident_jpn.trb"
    resident.parent.mkdir(parents=True)
    resident.write_bytes(b"\x00" + "寧々".encode() + b"\x00")
    (romfs / "img.bin").write_bytes(window)
    stats = names.apply_romfs_name_patches(romfs)
    assert stats["resident"] >= 1

    with pytest.raises(SystemExit):
        names.main([])
    assert names.main(["--dbin", str(flat)]) == 0
    assert "no changes" in capsys.readouterr().out
    assert names.main(["--dbin", str(tree), "--strip-dialog-tokens"]) == 0
    assert names.main(["--resident", str(plain)]) == 0
    assert names.main(["--romfs", str(romfs)]) == 0
    assert names.main(["--img", str(img)]) == 0


# ---------------------------------------------------------------------------
# patch_input_romaji
# ---------------------------------------------------------------------------


def test_romaji_encode_cave_and_cli(tmp_path: Path, monkeypatch, capsys):
    with pytest.raises(ValueError, match="cannot encode"):
        romaji.encode_imm12(0x101)
    with pytest.raises(ValueError, match="ABCD"):
        romaji._pad4("ABCD")
    assert romaji.fullwidth_latin_to_ascii("AＡ") == "AA"
    assert romaji._assemble(1, [("lit", "p", 5)])
    assert romaji._assemble(0, [("op", b"\x11"), ("lit", "p", 1), ("blx", 0x2000), ("bl_lab", "p")])
    with pytest.raises(ValueError):
        romaji._assemble(0, [("nope",)])
    calls = {"n": 0}

    def _short(base, stream):
        calls["n"] += 1
        return b"\x00\x00\x00\x00" if calls["n"] == 1 else b""

    monkeypatch.setattr(romaji, "_assemble", _short)
    with pytest.raises(RuntimeError, match="code size drift"):
        romaji.build_romaji_blob()
    monkeypatch.undo()
    monkeypatch.setattr(romaji, "CAVE_MAX", 1)
    with pytest.raises(ValueError, match="cave too large"):
        romaji.build_romaji_blob()
    monkeypatch.undo()

    buf = bytearray(romaji.ADDR_DRAW_CELL + 4)
    assert romaji.is_romaji_patched(buf) is False
    struct.pack_into("<I", buf, romaji.ADDR_DRAW_CELL, 0xEA800000)
    assert romaji.is_romaji_patched(buf) is False

    data = bytearray(CODE_LEN)
    _put(data, romaji.ADDR_DRAW_CELL, romaji.VANILLA_HEAD)
    assert romaji.patch_input_romaji(data) is True
    assert romaji.is_romaji_patched(data) is True
    assert romaji.patch_input_romaji(data) is False
    assert romaji.patch_input_romaji(data, canary=True) is True
    assert romaji.patch_input_romaji(data, force=True) is True
    bad = bytearray(CODE_LEN)
    with pytest.raises(ValueError, match="unexpected FUN_001fc304"):
        romaji.patch_input_romaji(bad)
    occupied = bytearray(CODE_LEN)
    _put(occupied, romaji.ADDR_DRAW_CELL, romaji.VANILLA_HEAD)
    occupied[romaji.ADDR_CAVE : romaji.ADDR_CAVE + 4] = b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="not empty"):
        romaji.patch_input_romaji(occupied)
    allowed = bytearray(CODE_LEN)
    _put(allowed, romaji.ADDR_DRAW_CELL, romaji.VANILLA_HEAD)
    allowed[romaji.ADDR_CAVE : romaji.ADDR_CAVE + 4] = bytes.fromhex("f04f2de9")
    assert romaji.patch_input_romaji(allowed) is True
    forced = bytearray(CODE_LEN)
    forced[romaji.ADDR_DRAW_CELL : romaji.ADDR_DRAW_CELL + 4] = b"\xff\xff\xff\xff"
    assert romaji.patch_input_romaji(forced, force=True) is True

    path = tmp_path / "code.bin"
    path.write_bytes(data)
    assert romaji.patch_code_bin_romaji(path) is False
    assert path.with_name(path.name + ".bak_pre_input_romaji").is_file()
    fresh = tmp_path / "fresh.bin"
    fresh.write_bytes(bytes(CODE_LEN))
    _blob = bytearray(fresh.read_bytes())
    _put(_blob, romaji.ADDR_DRAW_CELL, romaji.VANILLA_HEAD)
    fresh.write_bytes(_blob)
    assert romaji.patch_code_bin_romaji(fresh) is True
    assert romaji.main([str(fresh), "--dry-run"]) == 0
    assert "cave size" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="missing"):
        romaji.main([str(tmp_path / "missing.bin")])

    home = tmp_path / "home"
    monkeypatch.setattr(romaji.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(romaji, "patch_code_bin_romaji", lambda path, force=False: True)
    tex = home / "AppData/Roaming/Azahar/load/textures/00040000000F4E00"
    tex.mkdir(parents=True)
    assert romaji.main([str(fresh), "--deploy-azahar"]) == 0
    disabled = tex.with_name(tex.name + "_disabled")
    assert disabled.is_dir()
    tex.mkdir()
    assert romaji.main([str(fresh), "--deploy-azahar"]) == 0


# ---------------------------------------------------------------------------
# spotpass helpers (small buffers / mocked destinations)
# ---------------------------------------------------------------------------


def test_spotpass_helpers_and_cli(tmp_path: Path, monkeypatch, capsys):
    assert embed._bl_target(b"\x00\x00\x00\x00", 0) is None
    buf = bytearray(4)
    struct.pack_into("<I", buf, 0, 0xEB800000)
    assert isinstance(embed._bl_target(buf, 0), int)
    assert len(embed._body_bls(b"", 0x1000)) == 2
    assert embed.apply_map_comments(bytearray(4)) is False
    assert embed.build_newflag_cave() == embed._u32(0xE3A00001) + embed._u32(0xE12FFF1E)

    info = tmp_path / "info.dat"
    monkeypatch.setattr(embed, "INFO_DAT", info)
    with pytest.raises(FileNotFoundError, match="missing SpotPass"):
        embed.load_payload()
    info.write_bytes(b"\x00" * 4)
    with pytest.raises(ValueError, match="0x914"):
        embed.load_payload()
    payload = b"\xab" * 0x914
    info.write_bytes(payload)
    assert embed.load_payload() == payload

    monkeypatch.setattr(embed, "load_payload", lambda: payload)
    assert embed.main(["--dry-run"]) == 0
    assert "FUN_00609ab0" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="deploy-azahar"):
        embed.main([])

    import nlpp_paths

    dest = tmp_path / "exefs" / "code.bin"
    dest.parent.mkdir()
    dest.write_bytes(b"abc")
    monkeypatch.setattr(nlpp_paths, "AZAHAR_MOD_CODE", dest)
    monkeypatch.setattr(nlpp_paths, "AZAHAR_MOD_ROOT", tmp_path / "mod")
    (tmp_path / "mod").mkdir()
    monkeypatch.setattr(embed, "apply_patch", lambda data: True)
    monkeypatch.setattr(embed, "revert_patch", lambda data: False)
    assert embed.main(["--deploy-azahar"]) == 0
    assert dest.with_name(dest.name + ".bak_pre_spotpass_embed").is_file()
    assert embed.main(["--deploy-azahar", "--revert"]) == 0
    missing = tmp_path / "no-code.bin"
    monkeypatch.setattr(nlpp_paths, "AZAHAR_MOD_CODE", missing)
    with pytest.raises(SystemExit, match="missing"):
        embed.main(["--deploy-azahar"])

    assert skip.patched_14ed_mov(0x0014EFE8) == skip.PATCHED_14ED_NAMECARD
    assert skip.patched_14ed_mov(skip.ADDR_14ED_BACK[0]) == skip.PATCHED_14ED_BACK
    assert skip.patched_14ed_mov(0) == skip.PATCHED_14ED_TO_APPLY
    assert skip.patched_14ed_jt(26) == skip._14ed_jt_va(skip.VANILLA_14ED_JT_APPLY_FILE[26])
    assert skip.patched_14ed_jt(0) == skip.PATCHED_14ED_JT_APPLY
    assert skip.patched_14ed_wait(skip._14ED_EXIT_WAITS[0]) == skip.VANILLA_14ED_WAIT_STAY[skip._14ED_EXIT_WAITS[0]]
    assert skip.patched_14ed_wait(0) == skip.NOP
    assert skip._14ed_jt_off(2) == skip.ADDR_14ED_JT + 8
    assert len(skip.build_state0_hide()) > 0

    assert skip.main(["--dry-run"]) == 0
    with pytest.raises(SystemExit, match="deploy-azahar"):
        skip.main([])
    skip_dest = tmp_path / "skip" / "code.bin"
    skip_dest.parent.mkdir()
    skip_dest.write_bytes(b"xyz")
    monkeypatch.setattr(nlpp_paths, "AZAHAR_MOD_CODE", skip_dest)
    monkeypatch.setattr(skip, "apply_patch", lambda data: True)
    monkeypatch.setattr(skip, "revert_patch", lambda data: True)
    assert skip.main(["--deploy-azahar"]) == 0
    assert skip.main(["--deploy-azahar", "--revert"]) == 0
    monkeypatch.setattr(nlpp_paths, "AZAHAR_MOD_CODE", tmp_path / "absent.bin")
    with pytest.raises(SystemExit, match="missing"):
        skip.main(["--deploy-azahar"])
