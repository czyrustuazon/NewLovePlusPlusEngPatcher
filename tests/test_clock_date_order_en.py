"""3DS System Clock date row is MM / DD / YYYY with slash units."""

from __future__ import annotations

import re
import struct
from typing import TYPE_CHECKING

import pytest

from conftest import TOOLS, load_module

if TYPE_CHECKING:
    from PIL import Image

clock = load_module("deploy_clock_date_order_en", TOOLS / "deploy_clock_date_order_en.py")


def _pane(tag: bytes, name: str, x: float, flags: int = 1, w: float = 16.0) -> bytes:
    sec = bytearray(0x4C)
    sec[0:4] = tag
    struct.pack_into("<I", sec, 4, len(sec))
    sec[8] = flags
    sec[12 : 12 + len(name)] = name.encode("ascii")
    struct.pack_into("<f", sec, clock.X_OFF, x)
    struct.pack_into("<f", sec, clock.W_OFF, w)
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


def _w(layout: bytes, name: str) -> float:
    for tag, off, _size in clock._sections(layout):
        if tag in clock.PANE_TAGS and clock._pane_name(layout, off) == name:
            return struct.unpack_from("<f", layout, off + clock.W_OFF)[0]
    raise KeyError(name)


def _vanilla_anchor() -> bytes:
    panes = [_pane(b"pan1", n, v) for n, (v, _t) in clock.ANCHOR_X.items()]
    panes += [_pane(b"pic1", n, 0.0, w=v) for n, (v, _t) in clock.ARROW_W.items()]
    return _clyt(panes)


def _vanilla_win() -> bytes:
    panes = [_pane(b"wnd1" if n.startswith("window") else b"pic1", n, v) for n, (v, _t) in clock.WIN_X.items()]
    panes.append(_pane(b"pic1", "Pic_Opt_Win_tex4", 48.0))
    txl = _txl(["Opt_Time_tex1.bclim", "Opt_Time_tex2.bclim", "Opt_Time_Week01.bclim", "Opt_Time_Week07.bclim"])
    return _clyt([txl, _mat("Pic_Opt_Win_tex3", 2), *panes])


def test_fields_read_month_day_year_left_to_right():
    patched, changed = clock.patch_anchor_layout(_vanilla_anchor())
    assert changed == len(clock.ANCHOR_X) + len(clock.ARROW_W)
    month = [_x(patched, f"Pos_Opt_Num_0{i}") for i in (4, 5)]
    day = [_x(patched, f"Pos_Opt_Num_0{i}") for i in (6, 7)]
    year = [_x(patched, f"Pos_Opt_Num_0{i}") for i in range(4)]
    assert month == sorted(month) and day == sorted(day) and year == sorted(year)
    # 8px digits on an 8px pitch; each field clears the next.
    assert max(month) + 8 < min(day) and max(day) + 8 < min(year)
    # Weekday "(" is baked into the window art; it moves left with the row.
    assert max(year) + 4 < clock.PAREN_X
    assert _x(patched, "Pos_Opt_week") == clock.WEEK_X
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


# Native-width arrow ink spans -14..+11 around the spinner center.
ARROW_INK = (-14, 11)


def test_spinner_arrows_are_native_width_and_clear_each_other():
    patched, _ = clock.patch_anchor_layout(_vanilla_anchor())
    for name in clock.ARROW_W:
        assert _w(patched, name) == 32.0
    for row in ((1, 2, 0), (3, 4)):
        xs = [_x(patched, f"Pos_Opt_Btn_T_0{i}") for i in row]
        for a, b in zip(xs, xs[1:]):
            assert a + ARROW_INK[1] < b + ARROW_INK[0]


def test_separators_clear_field_frames():
    """White field frames (inset 4px, drawn over the part's pictures) must not hide / or :."""
    win, _ = clock.patch_win_layout(_vanilla_win())

    def frame(name: str, half: float) -> tuple[float, float]:
        c = _x(win, name) - 2
        return c - half, c + half

    slash_ink = 3.4
    s1 = _x(win, "Pic_Opt_Win_tex2") - 2
    s2 = _x(win, "Pic_Opt_Win_tex3") - 2
    assert frame("window_02", 12)[1] <= s1 - slash_ink
    assert s1 + slash_ink <= frame("window_03", 12)[0]
    assert frame("window_03", 12)[1] <= s2 - slash_ink
    assert s2 + slash_ink <= frame("window_01", 20)[0]
    colon = _x(win, "Pic_Opt_Win_tex1") - 2
    assert frame("window_06", 12)[1] < colon - 1 < colon + 1 < frame("window_07", 12)[0]


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


def test_date_row_centers_on_time_row():
    anchor, _ = clock.patch_anchor_layout(_vanilla_anchor())
    month0 = _x(anchor, "Pos_Opt_Num_04") - 4
    paren_end = clock.WEEK_X + 14  # ")" ink ends 14 right of the weekday center
    hour0 = _x(anchor, "Pos_Opt_Num_08") - 4
    ampm_end = _x(anchor, "Pos_Opt_ampm") + 11
    assert abs((month0 + paren_end) / 2 - (hour0 + ampm_end) / 2) <= 2


def paren_window() -> Image.Image:
    """222x162 window art with vanilla-placed "( )" and a cross outside the box."""
    from PIL import Image

    im = Image.new("RGBA", (222, 162), (255, 255, 255, 0))
    px = im.load()
    for y in range(45, 65):
        for x in range(168, 222):
            px[x, y] = (255, 255, 255, 255)  # opaque white block under "("
        px[179, y] = (204, 204, 204, 255)  # anti-aliasing
        px[180, y] = px[181, y] = (51, 51, 51, 255)
        px[205, y] = px[206, y] = (51, 51, 51, 255)
    px[140, 66] = (238, 238, 238, 255)  # background cross
    return im


def test_weekday_parens_shift_left_and_clean_up():
    im = paren_window()
    out = clock.shift_weekday_parens(im)
    shift = int(clock.ROW_SHIFT)
    for y in range(45, 65):
        assert out.getpixel((180 - shift, y)) == (51, 51, 51, 255)
        assert out.getpixel((206 - shift, y)) == (51, 51, 51, 255)
        # Old ink erased to the white that surrounds it.
        assert out.getpixel((179, y)) == (255, 255, 255, 255)
        assert out.getpixel((180, y))[:3] == (255, 255, 255)
        assert out.getpixel((206, y))[:3] == (255, 255, 255)
    assert out.getpixel((140, 66)) == (238, 238, 238, 255)
    assert clock.shift_weekday_parens(out).tobytes() == out.tobytes()


def test_weekday_parens_unexpected_art_fails():
    from PIL import Image

    with pytest.raises(ValueError, match="no weekday parentheses"):
        clock.shift_weekday_parens(Image.new("RGBA", (222, 162), (255, 255, 255, 0)))
    im = paren_window()
    im.putpixel((175, 50), (0, 0, 0, 255))
    with pytest.raises(ValueError, match="start at x=175"):
        clock.shift_weekday_parens(im)


def test_rgba4444_patch_keeps_untouched_texels():
    from bclimutil import decode_bclim_to_image, encode_rgba4444_pixels, parse_bclim

    import fake_img as fi

    im = paren_window()
    raw = fi.bclim(222, 162, 8, pixels=encode_rgba4444_pixels(im, 256, 256))
    old = decode_bclim_to_image(raw)
    new = clock.shift_weekday_parens(old)
    patched = clock.patch_rgba4444_texels(raw, old, new)
    assert len(patched) == len(raw)
    a, b = parse_bclim(raw)[0], parse_bclim(patched)[0]
    changed = sum(a[i : i + 2] != b[i : i + 2] for i in range(0, len(a), 2))
    diff = sum(old.getpixel((x, y)) != new.getpixel((x, y)) for x in range(222) for y in range(162))
    assert changed == diff
    assert decode_bclim_to_image(patched).tobytes() == new.tobytes()
    with pytest.raises(ValueError, match="RGBA4444"):
        clock.patch_rgba4444_texels(fi.bclim(16, 16, 0xD, pixels=bytes(128)), old, new)


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
    assert moved == len(clock.ANCHOR_X) + len(clock.ARROW_W)
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
