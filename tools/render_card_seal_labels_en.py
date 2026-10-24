#!/usr/bin/env python3
"""EN for the Business Card field-label stickers Seal_T000..T004.

Each sticker is a 160×64 ETC1A4 BCLIM in its own package
(``ExCardCommonT000.arc`` @ 4315 … ``ExCardCommonT004.arc`` @ 4319): a striped
tab with the label over a cream field the player writes in.

  T000 名前            → Name
  T001 呼ばれ方        → She Calls Me
  T002 出身地          → Hometown
  T003 呼び方          → I Call Her
  T004 カノジョの名前  → Girlfriend's Name

The Chinese-patch PSDs (Seal_T000..T004.psd) have seams in the tab art, so the
plate comes from vanilla. Old glyphs are wiped by interpolating each tab row
between clean columns either side of them (the stripes run horizontally).
English is DF Chubu Maru Gothic W7 (the vanilla glyphs are a rounded gothic)
in the sticker's own ink with a pale halo, 4× supersampled.

Writes ``assets/images/ExCardCommonT00N/timg/Seal_T00N_en.png``; the normal
``pack_images`` pass bakes them (folders are in ``src/image_map.py``).

  python tools/render_card_seal_labels_en.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import decode_bclim_to_image  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from img import ARC, Image as ImgBin  # noqa: E402

VANILLA_IMG = ROOT / "cache" / "vanilla_from_rom" / "romfs" / "img.bin"
FONT = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025" / "df-chubutomarugothic-w7.ttc"
OUT_ROOT = ROOT / "assets" / "images"

# (pkg, sticker, English, last JP glyph column, ink RGB). Ink sits between
# the median and darkest vanilla glyph pixels; thin Latin strokes read
# lighter than kana at the same color.
LABELS = [
    (4315, "Seal_T000", "Name", 34, (36, 78, 112)),
    (4316, "Seal_T001", "She Calls Me", 58, (36, 78, 112)),
    (4317, "Seal_T002", "Hometown", 46, (44, 120, 32)),
    (4318, "Seal_T003", "I Call Her", 46, (104, 26, 72)),
    (4319, "Seal_T004", "Girlfriend's Name", 82, (104, 26, 72)),
]
# Tab rows that hold glyphs + halo, and the tab's clean left column.
WIPE_Y = (17, 29)
LEFT_X = 9
# The tab top is straight up to x≈86; the slant starts after that.
TEXT_X0, TEXT_X1 = 11, 84
TEXT_Y0, TEXT_H = 18, 10
HALO = (255, 255, 255)
SCALE = 4


def load_vanilla(pkg: int, name: str) -> Image.Image:
    img = ImgBin(str(VANILLA_IMG))
    img.parse(False)
    res = img.entries[pkg]
    res.parse(False)
    arc = next(e for e in res.entries if isinstance(e, ARC))
    darc = DarcArchive(bytearray(arc.parsed()))
    entry = darc.find(f"timg/{name}.bclim")
    if entry is None:
        raise SystemExit(f"pkg {pkg}: missing timg/{name}.bclim")
    out = decode_bclim_to_image(darc.extract_file(entry))
    if out is None or out.size != (160, 64):
        raise SystemExit(f"pkg {pkg}: cannot decode {name}")
    return out.convert("RGBA")


def wipe_glyphs(plate: Image.Image, jp_end: int) -> Image.Image:
    """Per-row linear fill across the old label, between clean columns."""
    a = np.asarray(plate, dtype=np.float32).copy()
    x1 = min(jp_end + 3, TEXT_X1 + 1)
    for y in range(*WIPE_Y):
        left, right = a[y, LEFT_X], a[y, x1]
        for x in range(LEFT_X + 1, x1):
            t = (x - LEFT_X) / (x1 - LEFT_X)
            a[y, x] = left * (1 - t) + right * t
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype(np.uint8), "RGBA")


def render_text(text: str, ink: tuple[int, int, int]) -> Image.Image:
    """Ink + halo layer, 160×64. Squeezes horizontally past the tab width."""
    budget = TEXT_X1 - TEXT_X0
    font = ImageFont.truetype(str(FONT), size=TEXT_H * SCALE + 2 * SCALE)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    # Cap + x-height sit in TEXT_H rows; size by the cap height of "H".
    hb = probe.textbbox((0, 0), "H", font=font)
    cap = hb[3] - hb[1]
    font = ImageFont.truetype(str(FONT), size=round(font.size * (8 * SCALE) / cap))
    b = probe.textbbox((0, 0), text, font=font, stroke_width=SCALE // 4)
    tw, top = b[2] - b[0], font.getbbox("H")[1]
    big = Image.new("L", (tw + 4 * SCALE, TEXT_H * SCALE + 4 * SCALE), 0)
    ImageDraw.Draw(big).text((2 * SCALE - b[0], 2 * SCALE + SCALE - top), text, font=font, fill=255,
        stroke_width=SCALE // 4, stroke_fill=255)
    w = big.width // SCALE
    if w - 4 > budget:
        w = budget + 4
    mask = big.resize((w, big.height // SCALE), Image.Resampling.BOX)
    # Lift partial coverage so 1px stems stay solid like the vanilla glyphs.
    mask = mask.point(lambda v: round(255 * (v / 255) ** 0.8))
    halo = mask.filter(ImageFilter.MaxFilter(3))
    layer = Image.new("RGBA", (160, 64), (0, 0, 0, 0))
    ox, oy = TEXT_X0 - 2, TEXT_Y0 - 2
    halo_rgba = Image.new("RGBA", mask.size, HALO + (0,))
    halo_rgba.putalpha(halo.point(lambda v: v * 170 // 255))
    ink_rgba = Image.new("RGBA", mask.size, ink + (0,))
    ink_rgba.putalpha(mask)
    layer.alpha_composite(halo_rgba, (ox, oy))
    layer.alpha_composite(ink_rgba, (ox, oy))
    return layer


def render_sticker(
    vanilla: Image.Image, en: str, jp_end: int, ink: tuple[int, int, int]
) -> Image.Image:
    plate = wipe_glyphs(vanilla, jp_end)
    plate.alpha_composite(render_text(en, ink))
    return plate


def asset_path(name: str) -> Path:
    return OUT_ROOT / f"ExCardCommon{name[-4:]}" / "timg" / f"{name}_en.png"


def main() -> int:
    for pkg, name, en, jp_end, ink in LABELS:
        plate = render_sticker(load_vanilla(pkg, name), en, jp_end, ink)
        dest = asset_path(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        plate.save(dest)
        print(f"OK {name} -> {en!r} {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
