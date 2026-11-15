#!/usr/bin/env python3
"""3DS System Clock as US MM / DD / YYYY and HH : MM PM (Option06 pkg 5248).

Vanilla row is ``2026年 10月 17日 (土)``. The unit pictures come from the
``Pts_Opt_Time_Win`` part (code attaches it at ``Pos_Opt_Win_T``), and two of
them reuse weekday textures: 月 is ``Opt_Time_Week01`` (Monday) and 日 is
``Opt_Time_Week07`` (Sunday). English weekday glyphs therefore showed
``10 Mo 17 Su (Sa)``.

Digits and spinner arrows are parts that code attaches at the
``Pos_Opt_Num_*`` / ``Pos_Opt_Btn_{T,U}_*`` anchors in ``Lyt_Opt_Time``.
Moving those anchors moves the fields. Year is digits 00–03, month 04–05,
day 06–07. The weekday parentheses are baked into ``Opt_Time_Win1_img``
(world x≈61..88 around ``Pos_Opt_week`` at 74). The US row is shorter than
vanilla's, so the parentheses and weekday move 24px left with the date to
keep the row centered under the time.

This deploy:

- moves month and day left and year right (anchors, spinners, frames);
- paints ``Opt_Time_tex2`` (was 年) as ``/`` between month and day;
- rebinds ``Pic_Opt_Win_tex3`` (was 月 → Week01) to ``Opt_Time_tex2`` for
  the second slash between day and year;
- hides ``Pic_Opt_Win_tex4`` (was 日 → Week07);
- moves AM/PM (``Pos_Opt_ampm``, ``window_05``) from before the hour to
  after the minutes and centers ``HH : MM AM`` in the window;
- draws the spinner arrows at their texture's own 32px width (vanilla
  stretched them to 48), so fields sit as close as English needs instead of
  keeping the gaps that once held 年 / 月 / 日;
- repaints ``Opt_Time_Win1_img`` with the baked ``( )`` 24px left and
  moves ``Pos_Opt_week`` with them.

Weekday textures stay untouched, so ``(Sa)`` still uses Week06.

  python tools/deploy_clock_date_order_en.py
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from PIL import Image, ImageDraw  # noqa: E402

from bclimutil import (  # noqa: E402
    canvas_for_pixel_bytes,
    d2xy,
    decode_bclim_to_image,
    gcm,
    parse_bclim,
    png_to_bclim_same_size,
)
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_to_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    iter_deploy_targets,
    maybe_backup_img,
    resolve_img_paths,
)
from deploy_dsel_data_visible import set_pane_visible  # noqa: E402

MOD_IMG, _VANILLA = resolve_img_paths()

PKG = 5248
ANCHOR_LYT = "blyt/Lyt_Opt_Time.bclyt"
WIN_LYT = "blyt/Pts_Opt_Time_Win.bclyt"
SLASH_BCLIM = "timg/Opt_Time_tex2.bclim"
WIN_BCLIM = "timg/Opt_Time_Win1_img.bclim"
SLASH_TEX = "Opt_Time_tex2.bclim"
PNG_REL = Path("assets/images/Option06.check/timg/Opt_Time_tex2.png")

TEX = 16
SS = 8  # supersample factor for the slash stroke
# Digit ink spans rows 2..13 with ~2px strokes (Opt_Time_Num2 bbox).
SLASH_LINE = ((10.5, 2.0), (5.5, 14.0))
SLASH_STROKE = 1.9

# Date row shift: the whole row (fields, slashes, "( )", weekday) moves
# left so "MM / DD / YYYY (Sa)" (ink -74..64) centers on the time row (~-6).
ROW_SHIFT = 24.0
# Baked "( )" in Opt_Time_Win1_img: texture x 179..206 (with anti-aliasing),
# rows 45..64. The picture's left edge is world -119, so "(" ink starts near
# world 61 in vanilla. The nearest background cross sits at x 140..141.
PAREN_BOX = (170, 40, 216, 68)  # x0, y0, x1, y1 (exclusive) around both glyphs
PAREN_INK_X0 = 179
PAREN_X = 61.0 - ROW_SHIFT  # world x where "(" ink starts
WEEK_X = 74.0 - ROW_SHIFT

# Field centers in Anm_Opt_time space. Digits are 8px wide on an 8px pitch.
# The row ends 11px before the "(" (ink from 37): month ink -74..-58,
# day -40..-24, year -6..26, slashes (ink ±3.4) at -50 and -16.
#
# The field frames (window_01..03, white, inset 4px, drawn after the slash
# pictures) sit 2px left of their field and would cover a slash under them:
# month/day frames show center±12, year ±20. Each slash sits 1px left of the
# digit-ink midpoint so it clears both neighbouring frames.
MONTH_X = -42.0 - ROW_SHIFT
DAY_X = -8.0 - ROW_SHIFT
YEAR_X = 34.0 - ROW_SHIFT
# Window_base sits at x=-2 inside the part, so part x = world x + 2.
SLASH1_PART_X = -24.0 - ROW_SHIFT
SLASH2_PART_X = 10.0 - ROW_SHIFT

# Time row "HH : MM AM", centered on the window (~-6): hour ink -45..-29,
# colon -21, minute -13..3, then an 8px gap and the 24px AM/PM glyph
# (ink ±11) at 22. Vanilla spinners sit +1 off the hour center and the
# hour/minute/AM-PM frames -2/+2/-2 in world x; those offsets stay, and the
# colon clears the hour (right edge -24) and minute (left edge -15) frames.
HOUR_X = -37.0
MINUTE_X = -5.0
AMPM_X = 22.0
COLON_PART_X = -19.0

# pane -> (vanilla x, US x). Vanilla is checked so a re-run is a no-op and
# an unexpected layout fails loudly.
ANCHOR_X: dict[str, tuple[float, float]] = {
    "Pos_Opt_Num_00": (-90.0, YEAR_X - 12),
    "Pos_Opt_Num_01": (-82.0, YEAR_X - 4),
    "Pos_Opt_Num_02": (-74.0, YEAR_X + 4),
    "Pos_Opt_Num_03": (-66.0, YEAR_X + 12),
    "Pos_Opt_Num_04": (-26.0, MONTH_X - 4),
    "Pos_Opt_Num_05": (-18.0, MONTH_X + 4),
    "Pos_Opt_Num_06": (20.0, DAY_X - 4),
    "Pos_Opt_Num_07": (28.0, DAY_X + 4),
    "Pos_Opt_Btn_T_00": (-78.0, YEAR_X),
    "Pos_Opt_Btn_U_00": (-78.0, YEAR_X),
    "Pos_Opt_Btn_T_01": (-22.0, MONTH_X),
    "Pos_Opt_Btn_U_01": (-22.0, MONTH_X),
    "Pos_Opt_Btn_T_02": (26.0, DAY_X),
    "Pos_Opt_Btn_U_02": (26.0, DAY_X),
    "Pos_Opt_Num_08": (-13.0, HOUR_X - 4),
    "Pos_Opt_Num_09": (-5.0, HOUR_X + 4),
    "Pos_Opt_Num_10": (34.0, MINUTE_X - 4),
    "Pos_Opt_Num_11": (42.0, MINUTE_X + 4),
    "Pos_Opt_Btn_T_03": (-8.0, HOUR_X + 1),
    "Pos_Opt_Btn_U_03": (-8.0, HOUR_X + 1),
    "Pos_Opt_Btn_T_04": (38.0, MINUTE_X),
    "Pos_Opt_Btn_U_04": (38.0, MINUTE_X),
    "Pos_Opt_ampm": (-50.0, AMPM_X),
    "Pos_Opt_week": (74.0, WEEK_X),
}
# Field frames keep vanilla's "part x = field center" relation.
WIN_X: dict[str, tuple[float, float]] = {
    "window_01": (-78.0, YEAR_X),
    "window_02": (-22.0, MONTH_X),
    "window_03": (26.0, DAY_X),
    "Pic_Opt_Win_tex2": (-45.8333, SLASH1_PART_X),
    "Pic_Opt_Win_tex3": (2.16666, SLASH2_PART_X),
    "window_05": (-50.0, AMPM_X),
    "window_06": (-6.0, HOUR_X + 3),
    "window_07": (42.0, MINUTE_X + 4),
    "Pic_Opt_Win_tex1": (18.0, COLON_PART_X),
}
REBIND = {"Pic_Opt_Win_tex3": ("Opt_Time_Week01.bclim", SLASH_TEX)}
HIDE = ("Pic_Opt_Win_tex4",)

# Spinner arrows draw the 32x32 Opt_Btn_{Up,Down}_OFF stretched to 48 wide
# (ink ~38px), which forced field centers ~40 apart. At the native 32 the
# ink is -14..+11, so neighbours 31+ apart clear. Touch areas
# (Pic_Opt_btn_{T,U}_*) stay 32 wide.
ARROW_W: dict[str, tuple[float, float]] = {
    f"Pic_Opt_Btn_{kind}{i:02d}": (48.0, 32.0) for kind in ("Up", "D") for i in range(5)
}

PANE_TAGS = (b"pan1", b"pic1", b"wnd1", b"txt1", b"prt1", b"bnd1")
X_OFF = 0x24  # translate.x inside a pane section
W_OFF = 0x44  # size.x inside a pane section


def _sections(data: bytes):
    magic, _bom, header_size, _rev, file_size, count = struct.unpack_from(
        "<4sHHIII", data, 0
    )
    if magic != b"CLYT" or file_size != len(data):
        raise ValueError("bad CLYT")
    off = header_size
    for _ in range(count):
        tag = bytes(data[off : off + 4])
        size = struct.unpack_from("<I", data, off + 4)[0]
        yield tag, off, size
        off += size


def _pane_name(data: bytes, off: int) -> str:
    return bytes(data[off + 12 : off + 28]).split(b"\x00", 1)[0].decode("ascii")


def move_panes(
    layout: bytes, moves: dict[str, tuple[float, float]], *, offset: int = X_OFF
) -> tuple[bytes, int]:
    """Set each pane's x (or the float at ``offset``) to its US value.

    Returns (layout, panes changed).
    """
    data = bytearray(layout)
    seen: set[str] = set()
    changed = 0
    for tag, off, _size in _sections(data):
        if tag not in PANE_TAGS:
            continue
        name = _pane_name(data, off)
        if name not in moves:
            continue
        vanilla, target = moves[name]
        x = struct.unpack_from("<f", data, off + offset)[0]
        if abs(x - target) < 0.01:
            pass
        elif abs(x - vanilla) < 0.01:
            struct.pack_into("<f", data, off + offset, target)
            changed += 1
        else:
            raise ValueError(f"{name} {x=}, expected vanilla {vanilla} or {target}")
        seen.add(name)
    missing = set(moves) - seen
    if missing:
        raise ValueError(f"missing panes: {sorted(missing)}")
    return bytes(data), changed


def rebind_textures(layout: bytes, rebind: dict[str, tuple[str, str]]) -> tuple[bytes, int]:
    """Point a material's first texMap from one ``txl1`` texture to another."""
    data = bytearray(layout)
    textures: list[str] = []
    seen: set[str] = set()
    changed = 0
    for tag, off, _size in _sections(data):
        if tag == b"txl1":
            count = struct.unpack_from("<I", data, off + 8)[0]
            base = off + 12
            for rel in struct.unpack_from(f"<{count}I", data, base):
                end = data.index(b"\x00", base + rel)
                textures.append(bytes(data[base + rel : end]).decode("ascii"))
        elif tag == b"mat1":
            count = struct.unpack_from("<I", data, off + 8)[0]
            for i in range(count):
                mo = off + struct.unpack_from("<I", data, off + 12 + 4 * i)[0]
                name = bytes(data[mo : mo + 20]).split(b"\x00", 1)[0].decode("ascii")
                if name not in rebind:
                    continue
                if struct.unpack_from("<I", data, mo + 0x30)[0] & 3 < 1:
                    raise ValueError(f"{name} has no texMap")
                old, new = rebind[name]
                cur = textures[struct.unpack_from("<H", data, mo + 0x34)[0]]
                if cur == old:
                    struct.pack_into("<H", data, mo + 0x34, textures.index(new))
                    changed += 1
                elif cur != new:
                    raise ValueError(f"{name} uses {cur}, expected {old} or {new}")
                seen.add(name)
    missing = set(rebind) - seen
    if missing:
        raise ValueError(f"missing materials: {sorted(missing)}")
    return bytes(data), changed


def patch_anchor_layout(layout: bytes) -> tuple[bytes, int]:
    data, moved = move_panes(layout, ANCHOR_X)
    data, narrowed = move_panes(data, ARROW_W, offset=W_OFF)
    return data, moved + narrowed


def patch_win_layout(layout: bytes) -> tuple[bytes, int]:
    data, moved = move_panes(layout, WIN_X)
    data, rebound = rebind_textures(data, REBIND)
    hidden = set_pane_visible(data, (), HIDE)
    return hidden, moved + rebound + (hidden != data)


def paint_slash() -> Image.Image:
    """White ``/`` centered in 16x16 with the digits' ink rows and stroke.

    A font slash at this size is a faint 1px hairline next to the 2px
    ``Opt_Time_Num*`` digits, so draw the stroke supersampled instead.
    """
    big = Image.new("L", (TEX * SS, TEX * SS), 0)
    draw = ImageDraw.Draw(big)
    (x0, y0), (x1, y1) = SLASH_LINE
    draw.line(
        [(x0 * SS, y0 * SS), (x1 * SS, y1 * SS)],
        fill=255,
        width=round(SLASH_STROKE * SS),
    )
    alpha = big.resize((TEX, TEX), Image.LANCZOS)
    im = Image.new("RGBA", (TEX, TEX), (255, 255, 255, 0))
    im.putalpha(alpha)
    return im


def shift_weekday_parens(im: Image.Image) -> Image.Image:
    """Move the baked ``( )`` in ``Opt_Time_Win1_img`` ``ROW_SHIFT`` px left.

    Ink is any non-white pixel inside ``PAREN_BOX`` (anti-aliasing included). Each one is erased to the
    white the window shows there (opaque where its row is opaque white,
    clear elsewhere), then the glyphs are composited back shifted left.
    Already-shifted art is returned unchanged.
    """
    im = im.convert("RGBA")
    px = im.load()
    x0, y0, x1, y1 = PAREN_BOX
    shift = int(ROW_SHIFT)

    def is_ink(p: tuple[int, int, int, int]) -> bool:
        return p[3] > 0 and min(p[:3]) < 255

    def ink_in(lo: int, hi: int) -> list[tuple[int, int]]:
        return [
            (x, y)
            for x in range(max(lo, 0), min(hi, im.width))
            for y in range(y0, y1)
            if is_ink(px[x, y])
        ]

    ink = ink_in(x0 - shift, x1)
    if not ink:
        raise ValueError("Opt_Time_Win1_img has no weekday parentheses")
    start = min(x for x, _ in ink)
    if start == PAREN_INK_X0 - shift:
        return im
    if start != PAREN_INK_X0:
        raise ValueError(
            f"parentheses start at x={start}, expected {PAREN_INK_X0} "
            f"or {PAREN_INK_X0 - shift}"
        )

    glyphs = Image.new("RGBA", im.size, (0, 0, 0, 0))
    gpx = glyphs.load()
    out = im.copy()
    opx = out.load()
    for x, y in ink:
        gpx[x - shift, y] = px[x, y]
        neighbours = [px[nx, y] for nx in (x - 1, x + 1) if 0 <= nx < im.width]
        opaque = any(n[3] == 255 and not is_ink(n) for n in neighbours) and px[x, y][3] == 255
        opx[x, y] = (255, 255, 255, 255 if opaque else 0)
    return Image.alpha_composite(out, glyphs)


def patch_rgba4444_texels(bclim: bytes, old: Image.Image, new: Image.Image) -> bytes:
    """Rewrite only the texels that differ between ``old`` and ``new``.

    ``png_to_bclim_rgba4444_same_size`` re-encodes every transparent texel as
    grey (86,86,86,0); vanilla stores white there, and filtering would bleed
    grey into the window's white edges. Untouched texels keep their bytes.
    """
    pixels, width, height, fmt, footer = parse_bclim(bclim)
    if fmt != 8:
        raise ValueError(f"expected RGBA4444 fmt 8, got {fmt}")
    pot_w, pot_h = canvas_for_pixel_bytes(len(pixels), width, height, 2)
    tiles_x = max(gcm(pot_w, 8) // 8, 1)
    a, b = old.convert("RGBA").load(), new.convert("RGBA").load()
    out = bytearray(pixels)
    for i in range(pot_w * pot_h):
        mx, my = d2xy(i % 64)
        x = mx + (i // 64 % tiles_x) * 8
        y = my + (i // 64 // tiles_x) * 8
        if x >= width or y >= height or a[x, y] == b[x, y]:
            continue
        r, g, bl, al = (round(v / 0x11) for v in b[x, y])
        val = al | bl << 4 | g << 8 | r << 12
        struct.pack_into("<H", out, 2 * i, val)
    return bytes(out) + footer


def _load_pkg(img_path: Path, pkg_dir: Path) -> tuple[Package, ARC]:
    raw = img_path.read_bytes()
    img = ImgBin(str(img_path))
    img.parse(False)
    ent = img.entries[PKG]
    if ent is None:
        raise SystemExit(f"pkg {PKG} missing")
    src = pkg_dir / f"{PKG:04d}"
    src.write_bytes(raw[ent.fw.base_offset : ent.fw.base_offset + ent.fw.len()])
    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    return pkg, arc


def _write_arc_slot(pkg_dir: Path, pkg: Package, slot: bytes, dec: bytes) -> None:
    src = pkg_dir / f"{PKG:04d}"
    blob = bytearray(src.read_bytes())
    entry_off = None
    for i in range(struct.unpack_from("=6sH", blob, 0)[1]):
        off = Package.ENTRY_SIZE + i * Package.ENTRY_SIZE
        if blob[off : off + 4] == b"ARC ":
            entry_off = off
            break
    if entry_off is None:
        raise SystemExit("ARC entry missing")
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp or slot_len != len(slot) or len(dec) != dec_len:
        raise SystemExit(
            f"ARC entry mismatch cmp={is_cmp} slot {len(slot)}/{slot_len} "
            f"dec {len(dec)}/{dec_len}"
        )
    blob[cmp_off : cmp_off + slot_len] = slot
    new_pkg = pkg_dir / f"new_{PKG:04d}"
    new_pkg.write_bytes(blob)
    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for old, new in zip(pkg.entries, pkg2.entries):
        if isinstance(old, ARC):
            if new.parsed() != dec:
                raise SystemExit("ARC round-trip mismatch")
        elif old.parsed() != new.parsed():
            raise SystemExit(f"other entry changed {old.fn}")


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    slash = paint_slash()
    png_path = ROOT / PNG_REL
    png_path.parent.mkdir(parents=True, exist_ok=True)
    slash.save(png_path)
    print(f"painted slash -> {png_path}", flush=True)

    bak = maybe_backup_img(MOD_IMG, "clock_date_order")
    out = ROOT / "out" / "clock_date_order_en"
    pkg_dir = out / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = out / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    pkg, arc = _load_pkg(MOD_IMG, pkg_dir)
    cmp_len = arc.fw.len()
    darc = DarcArchive(bytearray(arc.parsed()))

    entry = darc.find(SLASH_BCLIM)
    if entry is None:
        raise SystemExit(f"missing {SLASH_BCLIM}")
    orig_bclim = tmp / "Opt_Time_tex2.bclim"
    orig_bclim.write_bytes(darc.extract_file(entry))
    darc.replace_same_size(entry, png_to_bclim_same_size(png_path, orig_bclim))
    print("OK Opt_Time_tex2.bclim = /", flush=True)

    entry = darc.find(WIN_BCLIM)
    if entry is None:
        raise SystemExit(f"missing {WIN_BCLIM}")
    orig_win = tmp / "Opt_Time_Win1_img.bclim"
    orig_win.write_bytes(darc.extract_file(entry))
    win_im = decode_bclim_to_image(orig_win.read_bytes())
    if win_im is None:
        raise SystemExit(f"cannot decode {WIN_BCLIM}")
    try:
        shifted = shift_weekday_parens(win_im)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    shifted.save(tmp / "Opt_Time_Win1_img.png")
    darc.replace_same_size(
        entry, patch_rgba4444_texels(orig_win.read_bytes(), win_im, shifted)
    )
    print(f"OK Opt_Time_Win1_img.bclim ( ) -{ROW_SHIFT:g}px", flush=True)

    for rel, patch in ((ANCHOR_LYT, patch_anchor_layout), (WIN_LYT, patch_win_layout)):
        lay = darc.find(rel)
        if lay is None:
            raise SystemExit(f"missing {rel}")
        patched, changed = patch(darc.extract_file(lay))
        darc.replace_same_size(lay, patched)
        print(f"OK {rel} changed={changed}", flush=True)

    slot = compress_to_exact_slot(bytes(darc.data), cmp_len)
    do = zlib.decompressobj()
    # The exact-slot search may retune zero gaps between ARC files, so the
    # round-trip target is what decompresses, checked file by file below.
    got = do.decompress(slot)
    if do.unused_data or not do.eof:
        raise SystemExit("exact zlib verify failed")
    tuned = DarcArchive(bytearray(got))
    for rel in (SLASH_BCLIM, WIN_BCLIM, ANCHOR_LYT, WIN_LYT):
        if tuned.extract_file(tuned.find(rel)) != darc.extract_file(darc.find(rel)):
            raise SystemExit(f"exact zlib changed {rel}")
    _write_arc_slot(pkg_dir, pkg, slot, got)
    print(f"ARC exact {len(slot)}", flush=True)

    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
            print("spliced", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed clock MM/DD/YYYY ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)


if __name__ == "__main__":
    main()
