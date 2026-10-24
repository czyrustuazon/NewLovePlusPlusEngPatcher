#!/usr/bin/env python3
"""Render the Puzzle-dama character-select name plates (needs Windows fonts).

Offline tool. The bake only reads ``assets/images/minigame/PuzzleSelect_*.png``
(``deploy_minigame_textures_en.py``).

pkg 120 ``Select`` has one 128×32 ETC1A4 ``.l2mgtex`` per name: blue under
PLAYER (137–147) and red under COM (149–159). The EN mockup
(``source/puzzle_select_en_mockup.png``) only shows SHARON, so every name is
rendered in its style: Arial Rounded MT Bold, white on navy (blue plate) and
light pink on maroon (red plate). Glyphs are centred on the JP glyph box of the
same strip.

The zlib slots are tiny (634–1203 bytes), so the names are slightly smaller
than the mockup's SHARON (13 px caps + 2 px outline, about the JP glyph height)
and each strip keeps the most alpha levels whose zopfli stream still fits its
slot (full 16 down to 2).

Arial Rounded MT Bold ships with Windows/Office and is not redistributable;
only the rendered PNGs are committed.

  python tools/cut_minigame_select_names_en.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

import l2mgtex  # noqa: E402
from img import Image as ImgBin  # noqa: E402
from nlpp_paths import require_vanilla_img  # noqa: E402

MASTERS = ROOT / "assets" / "images" / "minigame"
FONT = Path(r"C:\Windows\Fonts\ARLRDBD.TTF")
PKG = 120
# Same order in both colour sets.
NAMES = (
    "DIXIE",  # デキシー (Rumble Roses)
    "MANAKA",  # まなか
    "MIMI",  # ミミ
    "NENE",  # ねね
    "NYAMI",  # ニャミ
    "PASTEL",  # パステル
    "RINKO",  # りんこ
    "RUQUIA",  # ルキア
    "SHARON",  # シャロン (mockup)
    "SHIORI",  # しおり
    "HIKARI",  # ひかり
)
STYLES = {
    "blue": (137, (250, 255, 255), (5, 30, 70)),
    "red": (149, (252, 222, 228), (172, 72, 100)),
}
CAP_PX = 13  # the mockup's SHARON is ~17; larger does not fit the slots
STROKE_PX = 2
TRACK_PX = 0  # letter spacing; 1 px reads better but red MANAKA overflows its slot
MAX_W = 124
SS = 4  # supersampling


def _jp_strips() -> dict[int, tuple[bytes, int]]:
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    res = img.entries[PKG]
    res.parse(False)
    return {int(e.fn[:3]): (e.parsed(), e.fw.len()) for e in res.entries if e.fn.endswith(".l2mgtex")}


def _jp_centers(strips: dict[int, tuple[bytes, int]]) -> dict[int, tuple[float, float]]:
    out = {}
    for n, (raw, _slot) in strips.items():
        if 137 <= n <= 159 and n != 148:
            a = np.array(l2mgtex.decode(raw))[..., 3]
            ys, xs = np.where(a > 40)
            out[n] = ((xs.min() + xs.max() + 1) / 2, (ys.min() + ys.max() + 1) / 2)
    return out


def _text_width(f: ImageFont.FreeTypeFont, text: str) -> float:
    return f.getlength(text) + TRACK_PX * SS * (len(text) - 1)


def _font_size() -> int:
    """Largest size whose cap height is CAP_PX and every name fits MAX_W."""
    for size in range(80 * SS, 10, -1):
        f = ImageFont.truetype(str(FONT), size)
        cap = f.getbbox("H")[3] - f.getbbox("H")[1]
        if cap > CAP_PX * SS:
            continue
        widest = max(_text_width(f, n) for n in NAMES) + 2 * STROKE_PX * SS
        if widest <= MAX_W * SS:
            return size
    raise SystemExit("no font size fits")


def render(text: str, fill, stroke, size: int, cx: float, cy: float) -> Image.Image:
    f = ImageFont.truetype(str(FONT), size)
    big = Image.new("RGBA", (128 * SS, 32 * SS), (*stroke, 0))
    d = ImageDraw.Draw(big)
    capt, capb = f.getbbox("H")[1], f.getbbox("H")[3]
    x = cx * SS - _text_width(f, text) / 2
    y = cy * SS - (capt + capb) / 2
    # Outline pass for every letter first, then fills, so spacing stays even.
    for pass_fill in (False, True):
        xx = x
        for ch in text:
            if pass_fill:
                d.text((xx, y), ch, font=f, fill=(*fill, 255))
            else:
                d.text((xx, y), ch, font=f, fill=(*stroke, 255),
                       stroke_width=STROKE_PX * SS, stroke_fill=(*stroke, 255))
            xx += f.getlength(ch) + TRACK_PX * SS
    pm = big.convert("RGBa").resize((128, 32), Image.Resampling.LANCZOS).convert("RGBA")
    return pm


ALPHA_LEVELS = (16, 5, 4, 3, 2)


def quantize_alpha(im: Image.Image, levels: int) -> Image.Image:
    a = np.array(im).astype(np.int32)
    al = np.round(a[..., 3] / 255 * (levels - 1)) / (levels - 1) * 255
    a[..., 3] = al
    a[al == 0, :3] = 0
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def fit_slot(im: Image.Image, raw: bytes, slot: int) -> tuple[Image.Image, int]:
    import zopfli.zlib as zz

    for lv in ALPHA_LEVELS:
        q = quantize_alpha(im, lv)
        if len(zz.compress(l2mgtex.encode_like(raw, q))) <= slot - 8:
            return q, lv
    raise SystemExit("name does not fit its slot even with 2 alpha levels")


def main() -> int:
    if not FONT.is_file():
        raise SystemExit(f"missing {FONT} (Arial Rounded MT Bold)")
    strips = _jp_strips()
    centers = _jp_centers(strips)
    size = _font_size()
    cy = float(np.median([c[1] for c in centers.values()]))
    for style, (first, fill, stroke) in STYLES.items():
        for i, name in enumerate(NAMES):
            n = first + i
            im, lv = fit_slot(render(name, fill, stroke, size, 64.0, cy), *strips[n])
            path = MASTERS / f"PuzzleSelect_{n:03d}.png"
            im.save(path)
            print(f"wrote {path.relative_to(ROOT)} {style} {name} ({lv} alpha levels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
