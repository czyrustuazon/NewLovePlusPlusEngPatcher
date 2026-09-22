#!/usr/bin/env python3
"""EN communication-settings title — pkg 5241 ETC1A4.

The white bar on Communication Settings is
``Com_M_Sel_Plate_Text04_04_00`` (144×28). The parent-menu row is
``Com_M_Sel_Btn_Text04_04_00`` (246×48). Both stay Japanese in the live
archive: ``deploy_msel_menus_en.py`` paints the other Text04 labels as A8
and never lists these two, which are ETC1A4.

MultiWin ``Text04_04_00`` @ 5237 and the Options plate @ 5245 are already
"Communication Settings" and are not this bar. ``patch_commu_settings_header``
fills MultiWin ``Tex_Font_00``, which is the prompt line under the window.

Must run after ``deploy_msel_menus_en.py``. That script rebuilds 5241 from
vanilla and would drop this splice.

  python tools/deploy_commu_settings_header_en.py
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import parse_bclim, png_to_bclim_etc1a4_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_exact_zopfli, try_fast_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import UI_FONT, iter_deploy_targets, resolve_img_paths  # noqa: E402

MOD_IMG, _VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "commu_settings_header_en"
PKG = 5241
# Plate matches the Communication header (MPLUS, gh ~13). The row matches
# Name Card / Heart to Heart (Geomanist, gh 18).
# Plate is drawn as RGBA on the white bar. White glyphs match the bar and vanish.
# Vanilla ink is dark gray (~70). The menu row is an alpha mask, so it stays white.
PLATE_INK = (51, 51, 51)
PLATE = ("Com_M_Sel_Plate_Text04_04_00", "Communication Settings", 13, UI_FONT, 0, PLATE_INK)
ROW_FONT = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025" / "Geomanist-Regular.ttf"
BUTTON = ("Com_M_Sel_Btn_Text04_04_00", "Communication Settings", 18, ROW_FONT, 0, (255, 255, 255))
LABELS = (PLATE, BUTTON)


def _deploy_targets() -> list[Path]:
    targets = list(iter_deploy_targets(MOD_IMG))
    inst_root = ROOT / "out" / "azahar_instances"
    seen = {p.resolve() for p in targets}
    for img in inst_root.glob("*/user/load/mods/00040000000F4E00/romfs/img.bin"):
        rp = img.resolve()
        if rp.is_file() and rp not in seen:
            targets.append(rp)
            seen.add(rp)
    return targets


def _ink_blocks(rgba: Image.Image, ink: tuple[int, int, int]) -> Image.Image:
    """Fill every 4×4 block that contains a glyph so ETC1 keeps that color."""
    arr = np.array(rgba)
    a = arr[:, :, 3]
    h, w = a.shape
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            if int(a[by : by + 4, bx : bx + 4].max()) > 8:
                arr[by : by + 4, bx : bx + 4, 0] = ink[0]
                arr[by : by + 4, bx : bx + 4, 1] = ink[1]
                arr[by : by + 4, bx : bx + 4, 2] = ink[2]
    return Image.fromarray(arr, "RGBA")


def render_label(
    text: str,
    w: int,
    h: int,
    max_gh: int,
    font_path: Path,
    index: int,
    ink: tuple[int, int, int],
) -> Image.Image:
    """Centered glyphs. Side inset keeps the ETC1 edge blocks off the letters."""
    for size in range(max_gh + 6, 8, -1):
        scale = 2
        big = Image.new("L", (w * scale, h * scale), 0)
        dr = ImageDraw.Draw(big)
        font = ImageFont.truetype(str(font_path), size=size * scale, index=index)
        bbox = dr.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw > (w - 6) * scale:
            continue
        x = (w * scale - tw) // 2 - bbox[0]
        y = (h * scale - th) // 2 - bbox[1]
        dr.text((x, y), text, font=font, fill=255)
        alpha = np.array(big.resize((w, h), Image.Resampling.BILINEAR))
        ys, _xs = np.where(alpha > 20)
        if len(ys) == 0:
            continue
        gh = int(ys.max() - ys.min() + 1)
        if gh > max_gh:
            continue
        peak = float(alpha.max())
        if peak <= 0:
            continue
        alpha = np.clip(alpha.astype(np.float32) * (255.0 / peak), 0, 255).astype(np.uint8)
        rgb = Image.new("RGBA", (w, h), (*ink, 0))
        rgb.putalpha(Image.fromarray(alpha, "L"))
        return _ink_blocks(rgb, ink)
    raise RuntimeError(f"cannot fit {text!r} into {w}x{h}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    raw = MOD_IMG.read_bytes()
    img = ImgBin(str(MOD_IMG))
    img.parse(False)
    res = img.entries[PKG]
    if res is None:
        raise SystemExit(f"pkg {PKG} missing")
    src_pkg = pkg_dir / f"{PKG:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc_elem.fw.len()
    darc = DarcArchive(bytearray(arc_elem.parsed()))

    for stem, text, max_gh, font_path, index, ink in LABELS:
        path = f"timg/{stem}.bclim"
        entry = darc.find(path)
        if entry is None:
            raise SystemExit(f"missing {path}")
        orig = tmp / f"{stem}.bclim"
        png = tmp / f"{stem}.png"
        orig.write_bytes(darc.extract_file(entry))
        _pix, w, h, fmt, _ft = parse_bclim(orig.read_bytes())
        if fmt != 0xB:
            raise SystemExit(f"{stem} fmt {fmt:#x}, expected ETC1A4")
        rgba = render_label(text, w, h, max_gh, font_path, index, ink)
        rgba.save(png)
        rgba.save(OUT / f"{stem}.png")
        darc.replace_same_size(entry, png_to_bclim_etc1a4_same_size(png, orig))
        print(f"  OK {stem} -> {text!r} {w}x{h}", flush=True)

    patched = bytes(darc.data)
    if len(patched) != len(arc_elem.parsed()):
        raise SystemExit("ARC length changed")
    fast = try_fast_exact_slot(patched, cmp_len)
    if fast is not None:
        tuned, slot = fast
        print("  hit exact-zlib fast-path", flush=True)
    else:
        print("  escalating to zopfli + empty-block pad", flush=True)
        tuned, slot = compress_exact_zopfli(patched, cmp_len)
    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned or do.unused_data or not do.eof:
        raise SystemExit("exact zlib verify failed")
    print(f"  ARC exact zlib {len(slot)} unused_data=0", flush=True)

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

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC):
            if b.parsed() != tuned:
                raise SystemExit("ARC mismatch")
        elif a.parsed() != b.parsed():
            raise SystemExit(f"DMST changed {a.fn}")
    print("  DMST unchanged OK", flush=True)

    targets = _deploy_targets()
    src_len = res.fw.len()
    for dest in targets:
        dimg = ImgBin(str(dest))
        dimg.parse(False)
        dres = dimg.entries[PKG]
        if dres is None or dres.fw.len() != src_len:
            got_len = None if dres is None else dres.fw.len()
            raise SystemExit(f"{dest} pkg {PKG} length {got_len} != {src_len}")
    try:
        for dest in targets:
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("\ndeployed communication-settings header pkg", PKG, flush=True)


if __name__ == "__main__":
    main()
