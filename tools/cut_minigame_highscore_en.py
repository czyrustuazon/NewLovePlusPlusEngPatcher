#!/usr/bin/env python3
"""Puzzle-dama NEW HIGH SCORE! banner and EASY / HARD badges (needs scipy, cv2, Windows fonts).

Offline tool. The bake only reads ``assets/images/minigame/PuzzleResult_004.png``
and ``PuzzleBadge_{easy,hard}.png`` (``deploy_minigame_textures_en.py``).

pkg 119 ``Result``:
  004  256×64 RGBA4444  ハイスコア更新！ → NEW HIGH SCORE!  (cut from the mockup)
  000  32×32  ETC1A4    初級 badge → EASY
  001  32×32  ETC1A4    上級 badge → HARD
pkg 118 ``Ranking`` 181 / 182 are byte-identical copies of the badges.

Banner: the mockup lettering keyed by its reds (letter counters showing the
blue background stay clear), its dark shadow turned into semi-transparent black,
area-resampled onto the texture grid, then palette-quantized to the largest
palette that fits the 5332-byte slot (raw is ~9.3 KB).

Badges: the mockup shows EASY only, so both are rendered: the vanilla badge
with its kanji painted over by each row's own colour, plus white two-line
Arial Rounded MT Bold (EA / SY, HA / RD) squeezed to the badge width.
Arial Rounded MT Bold is a Windows/Office font; only the PNGs are committed.

  python tools/cut_minigame_highscore_en.py
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

import l2mgtex  # noqa: E402
from exact_zlib import pad_closed_zlib_stream  # noqa: E402
from img import Image as ImgBin  # noqa: E402
from nlpp_paths import require_vanilla_img  # noqa: E402

MASTERS = ROOT / "assets" / "images" / "minigame"
MOCKUP = MASTERS / "source" / "puzzle_highscore_en_mockup.png"
FONT = Path(r"C:\Windows\Fonts\ARLRDBD.TTF")
PKG = 119
# texture px -> mockup px, anchored on the unchanged TOTAL SCORE panel (016)
BANNER_PLACE = (2.615, 180.3, 55.8)
BANNER_BOX = (214, 90, 822, 215)  # mockup box around the lettering (stars excluded)
MOCKUP_BG = 224.0  # mean luminance of the light-blue background (190, 232, 250)
PALETTES = (128, 96, 64, 48, 32, 24, 16)
BADGES = {"000": ("PuzzleBadge_easy.png", ("EA", "SY")), "001": ("PuzzleBadge_hard.png", ("HA", "RD"))}
BADGE_CAP_PX = 9  # 10 px HARD leaves 3 bytes, too few for the empty-block padding


def banner(mock: np.ndarray) -> np.ndarray:
    h, w = mock.shape[:2]
    x0, y0, x1, y1 = BANNER_BOX
    reg = np.zeros((h, w), bool)
    reg[y0:y1, x0:x1] = True
    p = mock
    core = (p[..., 0] > 120) & (p[..., 0] - p[..., 2] > 40) & (p[..., 0] - p[..., 1] > 40) & reg
    lab, n = ndi.label(core)
    core = np.isin(lab, 1 + np.flatnonzero(ndi.sum(core, lab, range(1, n + 1)) > 30))
    filled = ndi.binary_fill_holes(ndi.binary_closing(core, iterations=1))
    letters = filled & ~((p[..., 2] > p[..., 0] + 20) & ~core)  # counters show the blue bg
    lab, n = ndi.label(letters)
    letters = np.isin(lab, 1 + np.flatnonzero(ndi.sum(letters, lab, range(1, n + 1)) > 30))
    alpha = np.clip(ndi.distance_transform_edt(letters) / 1.5, 0, 1).astype(np.float32)
    near = ndi.binary_dilation(letters, iterations=12) & ~letters & reg
    shadow = np.clip(1 - p.mean(2) / MOCKUP_BG, 0, 1) * near
    shadow[shadow < 0.12] = 0
    a = np.maximum(alpha, shadow)
    rgb = p.copy()
    rgb[(alpha < 0.5) & (shadow > 0)] = 0
    s, x, y = BANNER_PLACE
    pm = cv2.GaussianBlur(np.dstack([rgb * a[..., None], a]).astype(np.float32), (0, 0), 0.45 * s)
    m = np.float32([[s, 0, x + 0.5 * s - 0.5], [0, s, y + 0.5 * s - 0.5]])
    o = cv2.warpAffine(pm, m, (256, 64), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    aa = np.clip(o[..., 3], 0, 1)
    out = np.dstack([np.clip(o[..., :3] / np.maximum(aa, 1e-4)[..., None], 0, 255), aa * 255]).astype(np.uint8)
    out[out[..., 3] == 0, :3] = 0
    return out


def quantize_to_slot(out: np.ndarray, raw: bytes, slot: int) -> tuple[Image.Image, int]:
    import zopfli.zlib as zz

    for n in PALETTES:
        q = np.array(Image.fromarray(out).quantize(n, method=Image.Quantize.FASTOCTREE,
                                                   dither=Image.Dither.NONE).convert("RGBA"))
        q[q[..., 3] < 17] = 0
        im = Image.fromarray(q, "RGBA")
        if len(zz.compress(l2mgtex.encode_like(raw, im))) <= slot - 8:
            return im, n
    raise SystemExit("banner does not fit its slot")


def badge(tex: np.ndarray, lines: tuple[str, str], ss: int = 8) -> np.ndarray:
    out = tex.astype(np.float32).copy()
    inner = ndi.binary_erosion(tex[..., 3] > 200, iterations=2)
    for y in range(tex.shape[0]):
        xs = np.flatnonzero(inner[y])
        if len(xs):
            px = tex[y, xs, :3].astype(np.float32)
            keep = px.min(1) < 170  # badge colour, not the white kanji
            if keep.any():
                out[y, xs, :3] = px[keep].mean(0)
    size = next(sz for sz in range(200, 10, -1)
                if (lambda b: b[3] - b[1])(ImageFont.truetype(str(FONT), sz).getbbox("H")) <= BADGE_CAP_PX * ss)
    f = ImageFont.truetype(str(FONT), size)
    capt, capb = f.getbbox("H")[1], f.getbbox("H")[3]
    ys, xs = np.where(inner)
    cx = (xs.min() + xs.max() + 1) / 2 * ss
    top, bot = ys.min(), ys.max() + 1
    inner_w = (xs.max() - xs.min()) * ss
    big = Image.new("RGBA", (32 * ss, 32 * ss), (0, 0, 0, 0))
    for line, frac in zip(lines, (0.27, 0.73)):
        cy = (top + (bot - top) * frac) * ss
        tmp = Image.new("RGBA", (int(f.getlength(line)) + 4, 32 * ss), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((2, cy - (capt + capb) / 2), line, font=f, fill=(255, 255, 255, 255))
        bx = tmp.getbbox()
        tmp = tmp.crop((bx[0], 0, bx[2], 32 * ss))
        if tmp.width > inner_w:
            tmp = tmp.resize((int(inner_w), tmp.height), Image.Resampling.LANCZOS)
        big.alpha_composite(tmp, (int(cx - tmp.width / 2), 0))
    t = np.array(big.convert("RGBa").resize((32, 32), Image.Resampling.LANCZOS).convert("RGBA")).astype(np.float32)
    a = t[..., 3:] / 255
    out[..., :3] = t[..., :3] * a + out[..., :3] * (1 - a)
    o = np.clip(out, 0, 255).astype(np.uint8)
    o[o[..., 3] == 0, :3] = 0
    return o


def main() -> int:
    import zopfli.zlib as zz

    if not FONT.is_file():
        raise SystemExit(f"missing {FONT} (Arial Rounded MT Bold)")
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    res = img.entries[PKG]
    res.parse(False)
    van = {e.fn[:3]: (e.parsed(), e.fw.len()) for e in res.entries if e.fn.endswith(".l2mgtex")}
    mock = np.array(Image.open(MOCKUP).convert("RGB")).astype(np.float32)

    im, n = quantize_to_slot(banner(mock), *van["004"])
    im.save(MASTERS / "PuzzleResult_004.png")
    print(f"wrote PuzzleResult_004.png ({n} colours, slot {van['004'][1]})")
    for key, (name, lines) in BADGES.items():
        raw, slot = van[key]
        out = badge(np.array(l2mgtex.decode(raw)), lines)
        new = l2mgtex.encode_like(raw, Image.fromarray(out, "RGBA"))
        stream = min(zlib.compress(new, 9), zz.compress(new), key=len)
        size = len(stream)
        # Same test as the deploy: the stream must pad to exactly the slot.
        if size > slot or pad_closed_zlib_stream(stream, slot, expected=new) is None:
            raise SystemExit(f"{name}: {size} bytes cannot fill the {slot}-byte slot")
        Image.fromarray(out, "RGBA").save(MASTERS / name)
        print(f"wrote {name} ({size} / {slot})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
