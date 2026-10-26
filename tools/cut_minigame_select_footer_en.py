#!/usr/bin/env python3
"""Cut the Puzzle-dama ✚ SELECT / Ⓐ DECIDE footer from the EN mockup (needs scipy + cv2).

Offline tool. The bake only reads ``assets/images/minigame/PuzzleSelect_122.png``
and ``_123.png`` (``deploy_minigame_textures_en.py``).

pkg 120 ``Select`` ``122`` (Ⓐ決定) and ``123`` (✚選択) are 64×32 ETC1A4, drawn
1:1. The icon fills columns 0–21. The mockup's words are ~80 px wide at 1:1,
so only the word is cut (keyed off the flat bar green), scaled to the free
40 px with up to 70% horizontal condensing, and composed next to the game's
own icon.

  python tools/cut_minigame_select_footer_en.py
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
MOCKUP = MASTERS / "source" / "puzzle_footer_en_mockup.png"
PKG = 120
BAR_ROWS = (567, 614)
BAR_GREEN = np.array([129, 219, 44], np.float32)
# mockup x range holding icon + word
WORDS = {"123": (200, 500), "122": (650, 940)}
ICON_END = 23  # texture columns kept from the vanilla icon
TEXT_BOX = (24, 63, 5, 28)  # x0, x1, y0, y1 for the word
MAX_CONDENSE = 0.7


def cut_word(mock: np.ndarray, key: str) -> np.ndarray:
    """RGBA of the mockup word (icon dropped at the widest column gap)."""
    y0, y1 = BAR_ROWS
    x0, x1 = WORDS[key]
    reg = mock[y0:y1, x0:x1]
    m = np.abs(reg - BAR_GREEN).max(2) > 70
    lab, n = ndi.label(m)
    m = ndi.binary_fill_holes(np.isin(lab, 1 + np.flatnonzero(ndi.sum(m, lab, range(1, n + 1)) > 20)))
    cols = np.flatnonzero(m.sum(0) > 0)
    split = np.diff(cols).argmax()
    wx0, wx1 = cols[split + 1], cols[-1] + 1
    rows = np.flatnonzero(m[:, wx0:wx1].sum(1) > 0)
    alpha = np.clip(ndi.distance_transform_edt(m) / 1.2, 0, 1)
    return np.dstack([reg, alpha * 255])[rows[0] : rows[-1] + 1, wx0:wx1].astype(np.float32)


def compose(word: np.ndarray, tex: np.ndarray) -> np.ndarray:
    h, w = word.shape[:2]
    bx0, bx1, by0, by1 = TEXT_BOX
    sx = (bx1 - bx0) / w
    sy = min((by1 - by0) / h, sx / MAX_CONDENSE)
    nw, nh = round(w * sx), round(h * sy)
    pm = word.copy()
    pm[..., :3] *= pm[..., 3:] / 255
    t = cv2.resize(pm, (nw, nh), interpolation=cv2.INTER_AREA)
    a = np.clip(t[..., 3] / 255, 0, 1)
    rgb = t[..., :3] / np.maximum(a, 1e-4)[..., None]
    out = tex.astype(np.float32).copy()
    out[:, ICON_END:] = 0
    y = int(round((by0 + by1) / 2 - nh / 2))
    x = bx0 + (bx1 - bx0 - nw) // 2
    r = out[y : y + nh, x : x + nw]
    r[..., :3] = rgb * a[..., None] + r[..., :3] * (1 - a[..., None])
    r[..., 3] = a * 255 + r[..., 3] * (1 - a)
    o = np.clip(out, 0, 255).astype(np.uint8)
    o[o[..., 3] == 0, :3] = 0
    return o


def main() -> int:
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    res = img.entries[PKG]
    res.parse(False)
    raw = {e.fn[:3]: e.parsed() for e in res.entries if e.fn[:3] in WORDS}
    mock = np.array(Image.open(MOCKUP).convert("RGB")).astype(np.float32)
    for key in WORDS:
        out = compose(cut_word(mock, key), np.array(l2mgtex.decode(raw[key])))
        path = MASTERS / f"PuzzleSelect_{key}.png"
        Image.fromarray(out, "RGBA").save(path)
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
