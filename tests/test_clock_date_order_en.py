"""3DS System Clock date row is MM / DD / YYYY with slash units."""

from __future__ import annotations

import struct

from conftest import TOOLS, load_module

clock = load_module("deploy_clock_date_order_en", TOOLS / "deploy_clock_date_order_en.py")


def _pane(tag: bytes, name: str, x: float, flags: int = 1) -> bytes:
    sec = bytearray(0x4C)
    sec[0:4] = tag
    struct.pack_into("<I", sec, 4, len(sec))
    sec[8] = flags
    sec[12 : 12 + len(name)] = name.encode("ascii")
    struct.pack_into("<f", sec, clock.X_OFF, x)
    return bytes(sec)


def _txl(names: list[str]) -> bytes:
    strings = b""
    offs = []
    base = 4 * len(names)
    for n in names:
        offs.append(base + len(strings))
        strings += n.encode("ascii") + b"\x00"
    body = struct.pack("<I", len(names)) + struct.pack(f"<{len(names)}I", *offs) + strings
    body += b"\x00" * (-len(body) % 4)
    return b"txl1" + struct.pack("<I", 8 + len(body)) + body


def _mat(name: str, tex_idx: int) -> bytes:
    mat = bytearray(0x38)
    mat[0 : len(name)] = name.encode("ascii")
    struct.pack_into("<I", mat, 0x30, 1)
    struct.pack_into("<H", mat, 0x34, tex_idx)
    head = 12 + 4
    return b"mat1" + struct.pack("<III", 8 + 4 + 4 + len(mat), 1, head) + bytes(mat)


def _clyt(sections: list[bytes]) -> bytes:
    header = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, 20, 0, 0, len(sections))
    blob = header + b"".join(sections)
    return blob[:0x0C] + struct.pack("<I", len(blob)) + blob[0x10:]


def _x(layout: bytes, name: str) -> float:
    for tag, off, _size in clock._sections(layout):
        if tag in clock.PANE_TAGS and clock._pane_name(layout, off) == name:
            return struct.unpack_from("<f", layout, off + clock.X_OFF)[0]
    raise KeyError(name)


def _vanilla_anchor() -> bytes:
    return _clyt([_pane(b"pan1", n, v) for n, (v, _t) in clock.ANCHOR_X.items()])


def _vanilla_win() -> bytes:
    panes = [_pane(b"wnd1" if n.startswith("window") else b"pic1", n, v) for n, (v, _t) in clock.WIN_X.items()]
    panes.append(_pane(b"pic1", "Pic_Opt_Win_tex4", 48.0))
    txl = _txl(["Opt_Time_tex1.bclim", "Opt_Time_tex2.bclim", "Opt_Time_Week01.bclim", "Opt_Time_Week07.bclim"])
    return _clyt([txl, _mat("Pic_Opt_Win_tex3", 2), *panes])


def test_fields_read_month_day_year_left_to_right():
    patched, changed = clock.patch_anchor_layout(_vanilla_anchor())
    assert changed == len(clock.ANCHOR_X)
    month = [_x(patched, f"Pos_Opt_Num_0{i}") for i in (4, 5)]
    day = [_x(patched, f"Pos_Opt_Num_0{i}") for i in (6, 7)]
    year = [_x(patched, f"Pos_Opt_Num_0{i}") for i in range(4)]
    assert month == sorted(month) and day == sorted(day) and year == sorted(year)
    # 8px digits on an 8px pitch; each field clears the next.
    assert max(month) + 8 < min(day) and max(day) + 8 < min(year)
    # Weekday "(" is baked into the window art near x=61.
    assert max(year) + 4 < 61
    for i, field in enumerate((clock.YEAR_X, clock.MONTH_X, clock.DAY_X)):
        assert _x(patched, f"Pos_Opt_Btn_T_0{i}") == field
        assert _x(patched, f"Pos_Opt_Btn_U_0{i}") == field


def test_time_reads_hour_colon_minute_then_ampm():
    anchor, _ = clock.patch_anchor_layout(_vanilla_anchor())
    win, _ = clock.patch_win_layout(_vanilla_win())
    hour = [_x(anchor, f"Pos_Opt_Num_0{i}") for i in (8, 9)]
    minute = [_x(anchor, f"Pos_Opt_Num_{i}") for i in (10, 11)]
    colon = _x(win, "Pic_Opt_Win_tex1") - 2
    ampm = _x(anchor, "Pos_Opt_ampm")
    assert hour == sorted(hour) and minute == sorted(minute)
    assert max(hour) + 4 < colon - 2 < colon + 2 < min(minute) - 4
    # 24px AM/PM glyph (ink ±11) clears the minutes.
    assert max(minute) + 4 < ampm - 11
    # Row keeps vanilla's span: AM/PM ink -61 .. minute ink 46.
    assert min(hour) - 4 >= -61 and ampm + 11 <= 46
    assert _x(anchor, "Pos_Opt_Btn_T_03") == _x(anchor, "Pos_Opt_Btn_U_03") == clock.HOUR_X + 1
    assert _x(anchor, "Pos_Opt_Btn_T_04") == _x(anchor, "Pos_Opt_Btn_U_04") == clock.MINUTE_X
    assert _x(win, "window_05") - 2 == ampm - 2


def test_slashes_sit_between_fields_and_day_unit_hides():
    patched, changed = clock.patch_win_layout(_vanilla_win())
    assert changed == len(clock.WIN_X) + 2
    # Part x is world x + 2 (Window_base at -2).
    s1 = _x(patched, "Pic_Opt_Win_tex2") - 2
    s2 = _x(patched, "Pic_Opt_Win_tex3") - 2
    assert clock.MONTH_X + 8 < s1 < clock.DAY_X - 8
    assert clock.DAY_X + 8 < s2 < clock.YEAR_X - 16
    for tag, off, _size in clock._sections(patched):
        if tag == b"pic1" and clock._pane_name(patched, off) == "Pic_Opt_Win_tex4":
            assert patched[off + 8] & 1 == 0
        if tag == b"mat1":
            mo = off + struct.unpack_from("<I", patched, off + 12)[0]
            assert struct.unpack_from("<H", patched, mo + 0x34)[0] == 1  # Opt_Time_tex2


def test_patch_is_idempotent():
    a, _ = clock.patch_anchor_layout(_vanilla_anchor())
    w, _ = clock.patch_win_layout(_vanilla_win())
    assert clock.patch_anchor_layout(a) == (a, 0)
    assert clock.patch_win_layout(w) == (w, 0)


def test_unexpected_layout_fails():
    raw = _clyt([_pane(b"pan1", n, 999.0) for n in clock.ANCHOR_X])
    try:
        clock.patch_anchor_layout(raw)
    except ValueError as exc:
        assert "expected vanilla" in str(exc)
    else:
        raise AssertionError("moved a non-vanilla pane")


def test_slash_matches_digit_rows():
    im = clock.paint_slash()
    assert im.size == (16, 16)
    left, top, right, bottom = im.getbbox()
    assert top <= 2 and bottom >= 13
    px = im.load()
    # Leans right: ink at the top is right of ink at the bottom.
    top_ink = [x for x in range(16) if px[x, top + 1][3] > 128]
    bot_ink = [x for x in range(16) if px[x, bottom - 2][3] > 128]
    assert top_ink and bot_ink and min(top_ink) > max(bot_ink) - 2
