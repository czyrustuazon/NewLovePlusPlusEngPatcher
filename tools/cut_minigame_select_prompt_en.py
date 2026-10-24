#!/usr/bin/env python3
"""Cut the Puzzle-dama attack-pattern prompt from the EN mockup (needs scipy + cv2).

Offline tool. The bake only reads ``assets/images/minigame/PuzzleSelect_015.png``
(``deploy_minigame_textures_en.py``).

pkg 120 ``Select`` ``015`` is the pink こうげきだまのパターンをえらんでね♥ line
(256×64 ETC1A4, drawn 1:1). The mockup's ``Choose an attack pattern! ♥`` is
keyed by its pink (the orange TIME LIMIT dial next to it is excluded by hue),
filled, grown by the white outline, feathered, and area-resampled onto the
texture grid. It keeps the most alpha levels whose zopfli stream fits the
vanilla 3108-byte slot (full 16-level edges are ~3.5 KB).

  python tools/cut_minigame_select_prompt_en.py
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
MOCKUP = MASTERS / "source" / "puzzle_pattern_en_mockup.png"
OUT_PNG = MASTERS / "PuzzleSelect_015.png"
PKG = 120
# texture px -> mockup px (scale, x, y), from the JP screenshot at 1.36×.
PLACE = (2.56, 446.64, 62.72)
REGION = (560, 95, 1000, 200)  # mockup box around the EN text
GROW = 5  # white outline, mockup px
ALPHA_LEVELS = (16, 8, 6, 5, 4, 3)


def cut(mock: np.ndarray) -> np.ndarray:
    h, w = mock.shape[:2]
    x0, y0, x1, y1 = REGION
    region = np.zeros((h, w), bool)
    region[y0:y1, x0:x1] = True
    core = (mock[..., 0] > 170) & (mock[..., 0] - mock[..., 1] > 50) & (mock[..., 2] > mock[..., 1] - 10)
    core &= region
    lab, n = ndi.label(core)
    core = np.isin(lab, 1 + np.flatnonzero(ndi.sum(core, lab, range(1, n + 1)) > 15))
    letters = ndi.binary_fill_holes(ndi.binary_closing(core, iterations=1))
    mask = ndi.binary_dilation(letters, iterations=GROW) & region
    alpha = np.clip(ndi.distance_transform_edt(mask) / 1.5, 0, 1).astype(np.float32)
    s, x, y = PLACE
    pm = cv2.GaussianBlur(np.dstack([mock * alpha[..., None], alpha]).astype(np.float32), (0, 0), 0.45 * s)
    m = np.float32([[s, 0, x + 0.5 * s - 0.5], [0, s, y + 0.5 * s - 0.5]])
    o = cv2.warpAffine(pm, m, (256, 64), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    a = np.clip(o[..., 3], 0, 1)
    rgb = o[..., :3] / np.maximum(a, 1e-4)[..., None]
    out = np.dstack([np.clip(rgb, 0, 255), a * 255]).astype(np.uint8)
    out[out[..., 3] == 0, :3] = 0
    return out


def fit_slot(out: np.ndarray, raw: bytes, slot: int) -> tuple[Image.Image, int]:
    import zopfli.zlib as zz

    for lv in ALPHA_LEVELS:
        a = out.astype(np.int32)
        al = np.round(a[..., 3] / 255 * (lv - 1)) / (lv - 1) * 255
        a[..., 3] = al
        a[al == 0, :3] = 0
        im = Image.fromarray(a.astype(np.uint8), "RGBA")
        if len(zz.compress(l2mgtex.encode_like(raw, im))) <= slot - 8:
            return im, lv
    raise SystemExit("prompt does not fit its slot")


def main() -> int:
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    res = img.entries[PKG]
    res.parse(False)
    elem = next(e for e in res.entries if e.fn == "015.l2mgtex")
    mock = np.array(Image.open(MOCKUP).convert("RGB")).astype(np.float32)
    im, lv = fit_slot(cut(mock), elem.parsed(), elem.fw.len())
    im.save(OUT_PNG)
    print(f"wrote {OUT_PNG.relative_to(ROOT)} ({lv} alpha levels, slot {elem.fw.len()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
