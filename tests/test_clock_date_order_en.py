"""3DS System Clock date row is MM / DD / YYYY with slash units."""

from __future__ import annotations

import re
import struct

import pytest

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


def test_layout_shape_errors():
    with pytest.raises(ValueError, match="bad CLYT"):
        list(clock._sections(b"FLYT" + bytes(16)))
    with pytest.raises(ValueError, match="missing panes"):
        clock.move_panes(_clyt([_pane(b"pan1", "Other", 0.0)]), {"Gone": (0.0, 1.0)})
    txl = _txl(["a.bclim", "b.bclim", "c.bclim"])
    no_map = bytearray(_mat("M", 0))
    struct.pack_into("<I", no_map, 16 + 0x30, 0)
    with pytest.raises(ValueError, match="has no texMap"):
        clock.rebind_textures(_clyt([txl, bytes(no_map)]), {"M": ("a.bclim", "b.bclim")})
    with pytest.raises(ValueError, match="uses c.bclim"):
        clock.rebind_textures(_clyt([txl, _mat("M", 2)]), {"M": ("a.bclim", "b.bclim")})
    with pytest.raises(ValueError, match="missing materials"):
        clock.rebind_textures(_clyt([txl, _mat("Other", 0)]), {"M": ("a.bclim", "b.bclim")})


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


def _option06_arc(img_path):
    from img import ARC, FileWindow, Image as ImgBin, Package
    from darcutil import DarcArchive

    img = ImgBin(str(img_path))
    img.parse(False)
    res = img.entries[clock.PKG]
    pkg = Package(FileWindow(str(img_path), res.fw.base_offset, res.fw.len()), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    return DarcArchive(bytearray(arc.parsed()))


def test_bake_runs_clock_deploy():
    rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")
    assert "deploy_clock_date_order_en.py" in rebuild.DEPLOY_SCRIPTS
    # Unique package: no other bake script may splice 5248 after it.
    for name in rebuild.DEPLOY_SCRIPTS:
        if name == "deploy_clock_date_order_en.py":
            continue
        text = (TOOLS / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*PKG\s*=\s*5248\b", text, re.MULTILINE), name


def test_slash_master_is_committed():
    from PIL import Image

    with Image.open(TOOLS.parent / clock.PNG_REL) as im:
        assert im.convert("RGBA").tobytes() == clock.paint_slash().tobytes()


def test_fit_ui_masters_no_longer_relocates_year_glyph():
    """Title.check's Opt_Time_tex2 is a stray "P"; it must not overwrite the slash."""
    text = (TOOLS / "fit_ui_masters.py").read_text(encoding="utf-8")
    assert '"Option06.check" / "timg" / "Opt_Time_tex2.png"' not in text


@pytest.mark.local_data
def test_vanilla_option06_layouts_patch():
    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    darc = _option06_arc(vanilla)
    anchor = darc.extract_file(darc.find(clock.ANCHOR_LYT))
    win = darc.extract_file(darc.find(clock.WIN_LYT))
    a2, moved = clock.patch_anchor_layout(anchor)
    w2, changed = clock.patch_win_layout(win)
    assert moved == len(clock.ANCHOR_X)
    assert changed == len(clock.WIN_X) + 2  # + rebind + hide
    assert len(a2) == len(anchor) and len(w2) == len(win)
    # Weekday pane keeps Week01 (rebind raises if it points anywhere else).
    week = {"Pic_week_txt": ("Opt_Time_Week01.bclim", "Opt_Time_Week01.bclim")}
    assert clock.rebind_textures(a2, week)[0] == a2


@pytest.mark.local_data
def test_release_bake_has_us_clock():
    """Stale-bake guard: deploy-a ships release/bake_img.bin."""
    from nlpp_paths import BAKE_IMG

    if not BAKE_IMG.is_file():
        pytest.skip("no release/bake_img.bin")
    darc = _option06_arc(BAKE_IMG)
    anchor = darc.extract_file(darc.find(clock.ANCHOR_LYT))
    win = darc.extract_file(darc.find(clock.WIN_LYT))
    assert clock.patch_anchor_layout(anchor) == (anchor, 0)
    assert clock.patch_win_layout(win) == (win, 0)
