#!/usr/bin/env python3
"""Paint issue 28's lake paragraph onto the Towano Watcher holy-site page (pkg 5265).

Mag_Page01 is the shared sheet. The right page (Lyt_Spot_U01) keeps it.
The left page (Lyt_Spot_O01) is that sheet flipped, so those panes are hidden.
The heated-pool sentence belongs on FEVER; that corner stays out of the book
because it uses this same sheet. See technical.md §16.11.
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import (  # noqa: E402
    decode_bclim_to_image,
    png_to_bclim_la4_same_size,
    png_to_bclim_rgba4444_same_size,
    png_to_bclim_rgb565_same_size,
)
from darcutil import DarcArchive  # noqa: E402
from deploy_common import (  # noqa: E402
    AZAHAR_INSTANCES,
    UI_FONT,
    iter_deploy_targets,
    resolve_img_paths,
)
from exact_zlib import compress_exact_zopfli, try_fast_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

MOD_IMG, VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "watcher_issue28"
PKG = 5265

# Mag_Page01 is the one sheet behind every remaining spread. Issue 28's lake
# sentence belongs on the holy-site corner (Mag_Tit03). The heated-pool
# sentence belongs on FEVER (Mag_Tit05); that spread still uses this sheet.
LAKE = (
    "第28号\n"
    "今回の恋愛の聖地は\n"
    "「湖」に決定しました！\n"
    "湖面を伝わって流れる空気は\n"
    "見た目も相まって清涼感抜群。\n"
    "たまには趣を変え湖畔で\n"
    "カノジョと過ごすのも\n"
    "悪くないかもしれません。"
)


def _draw(base: Image.Image, text: str, ink: tuple[int, int, int, int]) -> Image.Image:
    """The book shows this sheet rotated 90 degrees counter-clockwise.

    The readable page is the unflipped sheet. The paragraph starts below the
    holy-site banner so it sits on the ruled lines. The SPOT name is not
    drawn here; it sits beside the SPOT badge on the left page.
    """
    tw, th = base.size
    screen = Image.new("RGBA", (th, tw), (0, 0, 0, 0))
    draw = ImageDraw.Draw(screen)
    font = ImageFont.truetype(str(UI_FONT), 13)
    # Screen space is 248 wide by 320 tall. The banner occupies the top of
    # the right page; the rules start under it.
    draw.multiline_text((16, 158), text, font=font, fill=ink, spacing=7)
    spun = screen.transpose(Image.Transpose.ROTATE_270)
    im = base.convert("RGBA")
    im.alpha_composite(spun)
    return im


def _hide_pic_panes(raw: bytes, names: tuple[bytes, ...]) -> bytes:
    """Drop the extra copies of the page sheet.

    Alpha alone stayed on screen, so the pane's width and height go to zero too.
    """
    out = bytearray(raw)
    for name in names:
        start = 0
        found = False
        while True:
            i = out.find(name, start)
            if i < 0:
                break
            if out[i - 12 : i - 8] == b"pic1":
                out[i - 4] &= 0xFE
                out[i - 2] = 0
                size_at = (i - 12) + 68
                out[size_at : size_at + 8] = b"\x00" * 8
                found = True
                break
            start = i + 1
        if not found:
            raise SystemExit(f"missing picture pane {name!r}")
    return bytes(out)


def _unbind_page_texture(raw: bytes, keep: bytes) -> bytes:
    """Point every Mag_Page01 material except `keep` at the plain white texture."""
    out = bytearray(raw)
    marker = bytes.fromhex("1500000007")
    start = 0
    while True:
        i = out.find(b"Pic_Page01_", start)
        if i < 0:
            break
        name = bytes(out[i : i + 16]).split(b"\x00", 1)[0]
        window = out[i : i + 0x50]
        k = window.find(marker)
        if k >= 0 and name != keep:
            out[i + k + 4] = 0
        start = i + 1
    return bytes(out)


# Each color set is its own BCLIM (Spot01 green … Spot02 pink). The holy-site
# page rebinds the pane to Mag_Obj_Spot02 after the layout loads, so the name
# has to be in that file. The badge art keeps the left 48 pixels. 「湖」 is the
# right 24, and the pane is widened so that strip sits on the row.
_SPOT_BADGE_PX = 48


def _paint_spot_name(badge: Image.Image) -> Image.Image:
    src = badge.convert("RGBA")
    width, height = src.size
    if width <= _SPOT_BADGE_PX:
        raise SystemExit(f"SPOT badge is only {width}px wide")
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shrunk = src.resize((_SPOT_BADGE_PX, height), Image.Resampling.LANCZOS)
    canvas.paste(shrunk, (0, 0), shrunk)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(UI_FONT), 22)
    text = "湖"
    box = draw.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    x = _SPOT_BADGE_PX + (width - _SPOT_BADGE_PX - tw) / 2 - box[0]
    y = (height - th) / 2 - box[1]
    draw.text((x, y), text, font=font, fill=(40, 40, 40, 255))
    return canvas


def _pic_base(raw: bytes, name: bytes) -> int:
    start = 0
    needle = name + b"\x00"
    while True:
        i = raw.find(needle, start)
        if i < 0:
            raise SystemExit(f"missing picture pane {name!r}")
        if raw[i - 12 : i - 8] == b"pic1":
            return i - 12
        start = i + 1


def _place_spot_name(raw: bytes) -> bytes:
    """Widen the SPOT badge so the 「湖」 painted on its texture sits on the row.

    The separate line pane stayed blank when it was retargeted at that
    texture, so the name has to be part of the badge picture itself.
    The underline pane is left alone.
    """
    import struct

    out = bytearray(raw)
    spot = _pic_base(out, b"Pic_Spot")
    struct.pack_into("<8f", out, spot + 0x60, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    # Current badge is centered at x=-60, width 72, so its left edge is -96.
    # The texture's left 48/72 is the badge art. Grow the pane to the right
    # until that art is still 72 wide and 「湖」 hangs past it.
    badge_frac = _SPOT_BADGE_PX / 72.0
    width = 72.0 / badge_frac
    struct.pack_into("<f", out, spot + 0x24, -96.0 + width / 2.0)
    struct.pack_into("<f", out, spot + 0x28, -40.0)
    struct.pack_into("<f", out, spot + 0x44, width)
    struct.pack_into("<f", out, spot + 0x48, 32.0)
    return bytes(out)


def _encode(page: Image.Image, orig: bytes, tmp: Path, stem: str, kind: str) -> bytes:
    png = tmp / f"{stem}.png"
    page.save(png)
    orig_path = tmp / f"{stem}.bclim"
    orig_path.write_bytes(orig)
    if kind == "la4":
        return png_to_bclim_la4_same_size(png, orig_path)
    if kind == "rgba4444":
        return png_to_bclim_rgba4444_same_size(png, orig_path)
    return png_to_bclim_rgb565_same_size(png, orig_path)


def patch_arc(vanilla_arc: bytes, tmp: Path) -> bytes:
    darc = DarcArchive(bytearray(vanilla_arc))
    page1 = darc.find("timg/Mag_Page01.bclim")
    if page1 is None:
        raise SystemExit("missing Mag_Page01")
    raw1 = darc.extract_file(page1)
    painted1 = _draw(decode_bclim_to_image(raw1), LAKE, (40, 40, 40, 255))
    darc.replace_same_size(page1, _encode(painted1, raw1, tmp, "page01", "la4"))
    painted_any = False
    for n in range(1, 6):
        rel = f"timg/Mag_Obj_Spot0{n}.bclim"
        spot = darc.find(rel)
        if spot is None:
            continue
        raw_spot = darc.extract_file(spot)
        painted_spot = _paint_spot_name(decode_bclim_to_image(raw_spot))
        darc.replace_same_size(
            spot, _encode(painted_spot, raw_spot, tmp, f"spot0{n}", "rgba4444")
        )
        painted_any = True
        print(f"OK {rel} SPOT name", flush=True)
    if not painted_any:
        raise SystemExit("missing Mag_Obj_Spot0N")
    # The upright sheet is Pic_Page01_04 (layout) and Pic_Page01_00 (page part).
    # Every other Mag_Page01 pane is the backwards copy.
    # O01 is the left page (photo, SPOT, AREA). Its sheet is the same
    # Mag_Page01 the right page shows, so the paragraph lands there backwards.
    # U01 is the right page (banner and rules). That sheet stays.
    hides = (
        ("blyt/Lyt_Spot_O01.bclyt", (b"Pic_Page01_02", b"Pic_Page01_03", b"Pic_Page01_04", b"Pic_Page01_05")),
        ("blyt/Lyt_Spot_U01.bclyt", (b"Pic_Page01_02", b"Pic_Page01_03", b"Pic_Page01_05")),
        ("blyt/Pts_Page_O01a.bclyt", (b"Pic_Page01_00", b"Pic_Page01_01")),
        ("blyt/Pts_Page_U01a.bclyt", (b"Pic_Page01_01",)),
        ("blyt/Pts_Shadow_O.bclyt", (b"Pic_Page01_00", b"Pic_Page01_01")),
        ("blyt/Pts_Shadow_U.bclyt", (b"Pic_Page01_00", b"Pic_Page01_01")),
    )
    for layout, names in hides:
        lay = darc.find(layout)
        if lay is None:
            raise SystemExit(f"missing {layout}")
        raw = _hide_pic_panes(darc.extract_file(lay), names)
        if layout == "blyt/Lyt_Spot_O01.bclyt":
            raw = _place_spot_name(raw)
        if layout.startswith("blyt/Lyt_Spot_"):
            raw = _unbind_page_texture(raw, b"Pic_Page01_04")
        if layout.startswith("blyt/Pts_Page_"):
            # Pic_Page01_01 is the flipped sheet. Its texture index is 3
            # (Mag_Page01). Pic_Page01_00 keeps that sheet.
            flipped = raw.find(b"Pic_Page01_01")
            window = raw[flipped : flipped + 0x50]
            k = window.find(bytes.fromhex("1500000003"))
            if k < 0:
                raise SystemExit(f"no flipped page texture in {layout}")
            raw = bytearray(raw)
            raw[flipped + k + 4] = 0
            raw = bytes(raw)
        darc.replace_same_size(lay, raw)
        print(f"OK {layout} mirror panes hidden", flush=True)
    for layout in ("blyt/Pts_Spot_O01.bclyt",):
        lay = darc.find(layout)
        if lay is None:
            raise SystemExit(f"missing {layout}")
        darc.replace_same_size(lay, _place_spot_name(darc.extract_file(lay)))
        print(f"OK {layout} SPOT name", flush=True)
    for layout in ("blyt/Pts_Shadow_O.bclyt", "blyt/Pts_Shadow_U.bclyt"):
        lay = darc.find(layout)
        raw = darc.extract_file(lay).replace(b"Mag_Page01.bclim", b"Mag_Page02.bclim")
        darc.replace_same_size(lay, raw)
        print(f"OK {layout} no longer uses the painted sheet", flush=True)
    print("OK Mag_Page01 lake paragraph", flush=True)
    return bytes(darc.data)


def _targets() -> list[Path]:
    targets = list(iter_deploy_targets(MOD_IMG))
    seen = {p.resolve() for p in targets}
    if AZAHAR_INSTANCES.is_dir():
        for img in AZAHAR_INSTANCES.glob(
            "*/user/load/mods/00040000000F4E00/romfs/img.bin"
        ):
            rp = img.resolve()
            if rp.is_file() and rp not in seen:
                targets.append(rp)
                seen.add(rp)
    return targets


def main() -> None:
    vanilla = VANILLA if VANILLA.is_file() else MOD_IMG
    if not vanilla.is_file():
        raise SystemExit(f"no img.bin: {vanilla}")
    vimg = ImgBin(str(vanilla))
    vimg.parse(False)
    res = vimg.entries[PKG]
    raw = vanilla.read_bytes()
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    src_pkg = pkg_dir / f"{PKG:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc_elem.fw.len()
    print(f"pkg {PKG} ARC dec={len(arc_elem.parsed())} slot={cmp_len}", flush=True)

    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)
    patched = patch_arc(arc_elem.parsed(), tmp)
    fast = try_fast_exact_slot(patched, cmp_len)
    if fast is not None:
        tuned, slot = fast
        print("  hit exact-zlib fast-path", flush=True)
    else:
        tuned, slot = compress_exact_zopfli(patched, cmp_len)
    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned or do.unused_data or not do.eof:
        raise SystemExit("zlib verify failed")

    blob = bytearray(src_pkg.read_bytes())
    entry_off = Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp or slot_len != cmp_len or len(tuned) != dec_len:
        raise SystemExit("ARC entry mismatch")
    blob[cmp_off : cmp_off + cmp_len] = slot
    new_pkg = pkg_dir / f"new_{PKG:04d}"
    new_pkg.write_bytes(blob)

    try:
        for dest in _targets():
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
            print(f"spliced {dest}", flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc


if __name__ == "__main__":
    main()
