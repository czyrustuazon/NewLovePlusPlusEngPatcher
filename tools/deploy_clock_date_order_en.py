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
at x≈61..86, so ``Pos_Opt_week`` stays at 74 and the date row ends before
that.

This deploy:

- moves month and day left and year right (anchors, spinners, frames);
- paints ``Opt_Time_tex2`` (was 年) as ``/`` between month and day;
- rebinds ``Pic_Opt_Win_tex3`` (was 月 → Week01) to ``Opt_Time_tex2`` for
  the second slash between day and year;
- hides ``Pic_Opt_Win_tex4`` (was 日 → Week07);
- moves AM/PM (``Pos_Opt_ampm``, ``window_05``) from before the hour to
  after the minutes, shifting hour, colon (``Pic_Opt_Win_tex1``) and
  minutes left to keep the row's span.

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

from bclimutil import png_to_bclim_same_size  # noqa: E402
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
SLASH_TEX = "Opt_Time_tex2.bclim"
PNG_REL = Path("assets/images/Option06.check/timg/Opt_Time_tex2.png")

TEX = 16
SS = 8  # supersample factor for the slash stroke
# Digit ink spans rows 2..13 with ~2px strokes (Opt_Time_Num2 bbox).
SLASH_LINE = ((10.5, 2.0), (5.5, 14.0))
SLASH_STROKE = 1.9

# Field centers in Anm_Opt_time space. Digits are 8px wide on an 8px pitch.
# Month ink -72..-56, day -28..-12, year 16..48; slashes sit mid-gap at -42
# and 2; the baked "(" starts near 61.
MONTH_X = -64.0
DAY_X = -20.0
YEAR_X = 32.0
# Window_base sits at x=-2 inside the part, so part x = world x + 2.
SLASH1_PART_X = -40.0
SLASH2_PART_X = 4.0

# Time row "HH : MM AM" over vanilla's span (AM/PM ink -61 .. minute ink 46).
# Hour ink -57..-41, colon -24, minute -10..6, then a 14px gap and the 24px
# AM/PM glyph (ink ±11) at 31. Vanilla spinners sit +1 off the hour center
# and the hour/minute/AM-PM frames -2/+2/-2 in world x; those offsets stay.
HOUR_X = -49.0
MINUTE_X = -2.0
AMPM_X = 31.0
COLON_PART_X = -22.0

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

PANE_TAGS = (b"pan1", b"pic1", b"wnd1", b"txt1", b"prt1", b"bnd1")
X_OFF = 0x24  # translate.x inside a pane section


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


def move_panes(layout: bytes, moves: dict[str, tuple[float, float]]) -> tuple[bytes, int]:
    """Set each pane's x to its US value. Returns (layout, panes changed)."""
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
        x = struct.unpack_from("<f", data, off + X_OFF)[0]
        if abs(x - target) < 0.01:
            pass
        elif abs(x - vanilla) < 0.01:
            struct.pack_into("<f", data, off + X_OFF, target)
            changed += 1
        else:
            raise ValueError(f"{name} x={x}, expected vanilla {vanilla} or {target}")
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
    return move_panes(layout, ANCHOR_X)


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
    for rel in (SLASH_BCLIM, ANCHOR_LYT, WIN_LYT):
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
