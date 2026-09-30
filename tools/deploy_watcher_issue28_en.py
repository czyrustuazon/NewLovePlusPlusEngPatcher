#!/usr/bin/env python3
"""Paint issue 28's lake paragraph onto Mag_Page01 (pkg 5265).

The right-page panes that would show that sheet stay size-zero. Holy Site
draws the sentence into Tex_Info_01 instead (§16.11.3). The left page is
the same sheet flipped, so those panes stay hidden too. The heated-pool
sentence belongs on FEVER; that corner stays out of the book because it
uses this same sheet. See docs/technical.md §16.11.
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


# Pic_Line01–08 on Lyt_Spot_U01. Each pane is 16px tall and they tile, so
# the pink rules are 16px apart in this screen space. One paragraph line
# sits in the gap above each rule. x=58 is the indent off the spine.
_RULE_Y = tuple(143 + i * 16 for i in range(8))
_TEXT_X = 58


def _draw(base: Image.Image, text: str, ink: tuple[int, int, int, int]) -> Image.Image:
    """The book shows this sheet rotated 90 degrees counter-clockwise.

    The readable page is the unflipped sheet. Each line is centered in the
    gap above one pink rule. 「湖」 is not drawn here; the game font draws
    it into Tex_Name, beside the SPOT badge.
    """
    tw, th = base.size
    screen = Image.new("RGBA", (th, tw), (0, 0, 0, 0))
    draw = ImageDraw.Draw(screen)
    font = ImageFont.truetype(str(UI_FONT), 13)
    for i, line in enumerate(text.split("\n")):
        bbox = font.getbbox(line)
        ink_h = bbox[3] - bbox[1]
        gap_center = _RULE_Y[i] - 8
        top = gap_center - ink_h / 2 - bbox[1]
        draw.text((_TEXT_X, top), line, font=font, fill=ink)
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
    # 「湖」 is DrawText in Tex_Name, same game font as the AREA station.
    # Painting it into the badge scaled the glyph and made it soft.
    # The upright sheet is Pic_Page01_04 (layout) and Pic_Page01_00 (page part).
    # Both stay size-zero. The eight lines are DrawText in Tex_Info_01 when
    # Holy Site is open, so the painted sheet cannot sit under the name list.
    # Every other Mag_Page01 pane is the backwards copy.
    hides = (
        ("blyt/Lyt_Spot_O01.bclyt", (b"Pic_Page01_02", b"Pic_Page01_03", b"Pic_Page01_04", b"Pic_Page01_05")),
        ("blyt/Lyt_Spot_U01.bclyt", (b"Pic_Page01_02", b"Pic_Page01_03", b"Pic_Page01_04", b"Pic_Page01_05")),
        ("blyt/Pts_Page_O01a.bclyt", (b"Pic_Page01_00", b"Pic_Page01_01")),
        ("blyt/Pts_Page_U01a.bclyt", (b"Pic_Page01_00", b"Pic_Page01_01")),
        ("blyt/Pts_Shadow_O.bclyt", (b"Pic_Page01_00", b"Pic_Page01_01")),
        ("blyt/Pts_Shadow_U.bclyt", (b"Pic_Page01_00", b"Pic_Page01_01")),
    )
    for layout, names in hides:
        lay = darc.find(layout)
        if lay is None:
            raise SystemExit(f"missing {layout}")
        raw = _hide_pic_panes(darc.extract_file(lay), names)
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
