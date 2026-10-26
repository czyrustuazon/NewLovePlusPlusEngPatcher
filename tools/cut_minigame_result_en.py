#!/usr/bin/env python3
"""Cut the Puzzle-dama LOSE / WIN stamps from the EN mockup (needs scipy + cv2).

Offline tool. The bake only reads ``assets/images/minigame/PuzzleGame_*.png``
(``deploy_minigame_textures_en.py``).

pkg 116 ``GameMain`` draws the end-of-round stamp as a word plus a shadow,
each 128×64 ETC1A4 drawn 1:1:

  043 まけ (blue)   044 its shadow
  125 かち (red)    126 its shadow

Words: the mockup lettering keyed by its dark outline (navy, not the purple
stripes behind it / dark red) and the fill inside it, plus the bright white
outline next to the letters. Shadows: the word's alpha shifted 0–4 px down and
0–1 px right, flat (43, 43, 43) on every texel like vanilla (identical colour
blocks leave only the alpha to compress).

The slots are small (1805 / 1750, shadows ~470), so both words are scaled to
74% (LOSE then matches the JP width) and each texture keeps the most alpha
levels that fit.

  python tools/cut_minigame_result_en.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

import l2mgtex  # noqa: E402
from img import Image as ImgBin  # noqa: E402
from nlpp_paths import require_vanilla_img  # noqa: E402

MASTERS = ROOT / "assets" / "images" / "minigame"
MOCKUP = MASTERS / "source" / "puzzle_result_en_mockup.png"
PKG = 116
# word texture -> (shadow texture, place (scale, x, y) in the mockup, mockup box)
_K = 2.56 / 1.365  # JP screenshot is 1.365×, mockup 2.56×
WORDS = {
    "043": ("044", (2.56, -4.36 * _K, 214.2 * _K), (30, 418, 315, 550)),
    "125": ("126", (2.56, 371.55 * _K, 214.25 * _K), (715, 412, 1000, 560)),
}
SCALE = 0.74
SHADOW_RGB = 43
WHITE_PX = 8  # white outline width, mockup px
LEVELS = (16, 8, 5, 3, 2)


def _letters(mock: np.ndarray, key: str, box: tuple[int, int, int, int]) -> np.ndarray:
    h, w = mock.shape[:2]
    x0, y0, x1, y1 = box
    reg = np.zeros((h, w), bool)
    reg[y0:y1, x0:x1] = True
    p = mock
    if key == "043":
        outline = (p[..., 2] > p[..., 0] + 60) & (p[..., 0] < 90) & (p[..., 1] < 120) & (p[..., 1] > p[..., 0] + 15)
        fill = (p[..., 2] > 230) & (p[..., 0] > 80) & (p[..., 0] < 210) & (p[..., 1] > 150)
    else:
        outline = (p[..., 0] > 110) & (p[..., 1] < 70) & (p[..., 2] < 70)
        fill = (p[..., 0] > 220) & (p[..., 1] > 70) & (p[..., 2] < 110)
    outline &= reg
    lab, n = ndi.label(outline)
    outline = np.isin(lab, 1 + np.flatnonzero(ndi.sum(outline, lab, range(1, n + 1)) > 40))
    inside = ndi.binary_fill_holes(ndi.binary_closing(outline, iterations=2))
    letters = ndi.binary_closing(outline | (fill & reg & inside), iterations=2)
    letters |= _small_holes(letters, 60)
    mask = letters | (ndi.binary_dilation(letters, iterations=WHITE_PX) & (p.min(2) > 175) & reg)
    mask = ndi.binary_closing(mask, iterations=1)
    return mask | _small_holes(mask, 40)


def _small_holes(m: np.ndarray, max_px: int) -> np.ndarray:
    holes = ndi.binary_fill_holes(m) & ~m
    lab, n = ndi.label(holes)
    return np.isin(lab, 1 + np.flatnonzero(ndi.sum(holes, lab, range(1, n + 1)) < max_px))


def cut(mock: np.ndarray, key: str) -> np.ndarray:
    _sh, (s, x, y), box = WORDS[key]
    mask = _letters(mock, key, box)
    alpha = np.clip(ndi.distance_transform_edt(mask) / 1.5, 0, 1).astype(np.float32)
    pm = cv2.GaussianBlur(np.dstack([mock * alpha[..., None], alpha]).astype(np.float32), (0, 0), 0.45 * s)
    m = np.float32([[s, 0, x + 0.5 * s - 0.5], [0, s, y + 0.5 * s - 0.5]])
    o = cv2.warpAffine(pm, m, (128, 64), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    a = np.clip(o[..., 3], 0, 1)
    # scale around the content centre
    ys, xs = np.where(a > 0.05)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    f = SCALE
    o = cv2.warpAffine(o, np.float32([[f, 0, cx * (1 - f)], [0, f, cy * (1 - f)]]), (128, 64), flags=cv2.INTER_AREA)
    a = np.clip(o[..., 3], 0, 1)
    # drop specks left by the panel behind the mockup
    lab, n = ndi.label(a > 0.05)
    a[~np.isin(lab, 1 + np.flatnonzero(ndi.sum(a > 0.05, lab, range(1, n + 1)) >= 15))] = 0
    rgb = o[..., :3] / np.maximum(a, 1e-4)[..., None]
    out = np.dstack([np.clip(rgb, 0, 255), a * 255]).astype(np.uint8)
    out[out[..., 3] == 0, :3] = 255  # vanilla stores white under the word's clear texels
    return out


def shadow(word: np.ndarray) -> np.ndarray:
    a = word[..., 3].astype(np.float32)
    u = np.zeros_like(a)
    for dy in range(5):
        for dx in range(2):
            u = np.maximum(u, np.roll(np.roll(a, dy, 0), dx, 1))
    out = np.full(word.shape, SHADOW_RGB, np.uint8)
    out[..., 3] = u.astype(np.uint8)
    return out


def fit(im: np.ndarray, raw: bytes, slot: int, clear_rgb: int | None) -> tuple[np.ndarray, int]:
    import zopfli.zlib as zz

    for lv in LEVELS:
        a = im.astype(np.int32)
        a[..., 3] = np.round(a[..., 3] / 255 * (lv - 1)) / (lv - 1) * 255
        if clear_rgb is not None:
            a[a[..., 3] == 0, :3] = clear_rgb
        q = a.astype(np.uint8)
        if len(zz.compress(l2mgtex.encode_like(raw, Image.fromarray(q, "RGBA")))) <= slot - 8:
            return q, lv
    raise SystemExit("does not fit its slot")


def main() -> int:
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    res = img.entries[PKG]
    res.parse(False)
    van = {e.fn[:3]: (e.parsed(), e.fw.len()) for e in res.entries if e.fn.endswith(".l2mgtex")}
    mock = np.array(Image.open(MOCKUP).convert("RGB")).astype(np.float32)
    for key, (sh, _place, _box) in WORDS.items():
        word = cut(mock, key)
        wq, wl = fit(word, *van[key], 255)
        sq, sl = fit(shadow(word), *van[sh], None)
        for k, im, lv in ((key, wq, wl), (sh, sq, sl)):
            path = MASTERS / f"PuzzleGame_{k}.png"
            Image.fromarray(im, "RGBA").save(path)
            print(f"wrote {path.relative_to(ROOT)} ({lv} alpha levels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
