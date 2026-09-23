#!/usr/bin/env python3
"""EN communication-settings rows — pkg 4185 Commu_Option.

Vanilla pic panes:
  Commu_Op_Text02  すれちがい通信
  Commu_Op_Text03  いつの間に通信
  Commu_Op_Text04  ダブルデート
  Commu_Op_Text01  ON/OFF help line (RGB565)

Zhoumaru Text02/Text04 are ToDoList / Gallery (wrong screen). The three
rows are painted together. The help line's alpha is the right sentence
but its RGB is noisy, so the sentence is composited from that alpha.
The white bar 通信設定 is ETC1A4 Com_M_Sel_Plate_Text04_04_00 @ 5241
(deploy_commu_settings_header_en.py). Text04_04_00 @ 5237 is already
"Communication Settings" and is not the line in that crop.

  python tools/deploy_commu_option_en.py
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

from bclimutil import (  # noqa: E402
    parse_bclim,
    png_to_bclim_rgba4444_same_size,
    png_to_bclim_rgb565_same_size,
)
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_exact_zopfli, try_fast_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import AZAHAR_INSTANCES, HEISEI_W5, iter_deploy_targets, resolve_img_paths  # noqa: E402

MOD_IMG, VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "commu_option_en"
PKG = 4185
INK = (51, 51, 51)
# Vanilla rows sit in the top of the 128×32 sheet (glyph top ~y=2, gh ~13).
ROW_X = 3
ROW_Y = 2
ROW_GH = 12

# Zhoumaru Text02/Text04 say ToDoList / Gallery. Paint all three rows together
# so StreetPass / SpotPass / Double Date share one size.
ROW_TEXT = {
    "Commu_Op_Text02": "StreetPass",
    "Commu_Op_Text03": "SpotPass",
    "Commu_Op_Text04": "Double Date",
}
SPOTPASS_PNG = (
    ROOT / "assets" / "images" / "Commu_Option.check" / "timg" / "Commu_Op_Text03.png"
)
HELP_PNG = (
    ROOT / "assets" / "images" / "Commu_Option.check" / "timg" / "Commu_Op_Text01.png"
)


def _deploy_targets() -> list[Path]:
    targets = list(iter_deploy_targets(MOD_IMG))
    inst_root = AZAHAR_INSTANCES
    seen = {p.resolve() for p in targets}
    for img in inst_root.glob("*/user/load/mods/00040000000F4E00/romfs/img.bin"):
        rp = img.resolve()
        if rp.is_file() and rp not in seen:
            targets.append(rp)
            seen.add(rp)
    return targets


def render_row(text: str, w: int, h: int) -> Image.Image:
    """Gray (51) glyphs, left aligned like the Japanese rows."""
    for size in range(ROW_GH + 8, 8, -1):
        scale = 2
        big = Image.new("L", (w * scale, h * scale), 0)
        dr = ImageDraw.Draw(big)
        font = ImageFont.truetype(str(HEISEI_W5), size=size * scale, index=1)
        bbox = dr.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw > (w - ROW_X - 2) * scale:
            continue
        dr.text((-bbox[0], -bbox[1]), text, font=font, fill=255)
        small = big.resize((w, h), Image.Resampling.BILINEAR)
        alpha = np.array(small)
        ys, xs = np.where(alpha > 20)
        if len(ys) == 0:
            continue
        gh = int(ys.max() - ys.min() + 1)
        if gh > ROW_GH:
            continue
        glyph = alpha[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
        peak = float(glyph.max())
        if peak <= 0:
            continue
        glyph = np.clip(glyph.astype(np.float32) * (255.0 / peak), 0, 255).astype(
            np.uint8
        )
        sheet = np.zeros((h, w), np.uint8)
        y = min(ROW_Y, h - glyph.shape[0])
        x = ROW_X
        gh_, gw = glyph.shape
        sheet[y : y + gh_, x : x + gw] = glyph
        rgb = Image.new("RGBA", (w, h), (*INK, 0))
        rgb.putalpha(Image.fromarray(sheet, "L"))
        return rgb
    raise RuntimeError(f"cannot fit {text!r} into {w}x{h}")


def help_from_alpha(png: Path, w: int, h: int) -> Image.Image:
    """Zhoumaru help alpha onto white. RGB565 has no alpha; vanilla ink is black."""
    src = Image.open(png).convert("RGBA")
    if src.size != (w, h):
        src = src.resize((w, h), Image.Resampling.BILINEAR)
    alpha = np.array(src.getchannel("A")).astype(np.float32) / 255.0
    out = np.full((h, w, 4), 255, np.uint8)
    # Black glyphs, white paper. Drop the noisy Zhoumaru RGB.
    shade = np.clip(255 * (1.0 - alpha), 0, 255).astype(np.uint8)
    out[:, :, 0] = shade
    out[:, :, 1] = shade
    out[:, :, 2] = shade
    out[:, :, 3] = 255
    return Image.fromarray(out, "RGBA")


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    if not SPOTPASS_PNG.is_file() or not HELP_PNG.is_file():
        raise SystemExit("missing Commu_Option Zhoumaru masters")

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

    def replace(stem: str, rgba: Image.Image, encoder) -> None:
        path = f"timg/{stem}.bclim"
        entry = darc.find(path)
        if entry is None:
            raise SystemExit(f"missing {path}")
        orig = tmp / f"{stem}.bclim"
        png = tmp / f"{stem}.png"
        orig.write_bytes(darc.extract_file(entry))
        _pix, w, h, fmt, _ft = parse_bclim(orig.read_bytes())
        if rgba.size != (w, h):
            raise SystemExit(f"{stem} {rgba.size} != {w}x{h}")
        rgba.save(png)
        rgba.save(OUT / f"{stem}.png")
        darc.replace_same_size(entry, encoder(png, orig))
        print(f"  OK {stem} fmt={fmt} {w}x{h}", flush=True)

    for stem, text in ROW_TEXT.items():
        entry = darc.find(f"timg/{stem}.bclim")
        _pix, w, h, _fmt, _ft = parse_bclim(darc.extract_file(entry))
        replace(stem, render_row(text, w, h), png_to_bclim_rgba4444_same_size)
    entry = darc.find("timg/Commu_Op_Text01.bclim")
    _pix, w, h, _fmt, _ft = parse_bclim(darc.extract_file(entry))
    replace("Commu_Op_Text01", help_from_alpha(HELP_PNG, w, h), png_to_bclim_rgb565_same_size)

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

    try:
        targets = _deploy_targets()
        for dest in targets:
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("\ndeployed Commu_Option EN pkg", PKG, "->", MOD_IMG, flush=True)


if __name__ == "__main__":
    main()
