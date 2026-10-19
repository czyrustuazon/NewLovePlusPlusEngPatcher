#!/usr/bin/env python3
"""Cut the Puzzle-dama course plates from the EN mockup (needs scipy + cv2).

Offline tool. The bake only reads ``assets/images/minigame/PuzzleSelect_070.png``
and ``_071.png`` (``deploy_minigame_textures_en.py``).

pkg 120 ``Select`` ``070`` 初級コース (blue) and ``071`` 上級コース (red) are
256×64 ETC1A4 plates. Both stick ~15 px off the screen edge, and the mockup
redrew the plate fill as stripes, so the plates are not cut whole:

1. Clean plate: the vanilla plate with the JP text replaced by its own 6 px
   checker, copied from clean columns on the same rows; then each interior row
   is flattened to its mean colour (the mockup plate has no checker either).
2. EN text: the mockup lettering, keyed by its colours (blue / orange letters
   with dark outlines), filled, grown by the white outer outline, feathered,
   and area-resampled onto the texture grid. The mockup's own plate border is
   excluded (screen-edge columns, tall thin blobs, columns outside the text).
3. The text is scaled to 75% around its centre.

Full-size mockup lettering is ~2.4 KB against slots of 2272 / 1960. 75% on
the flat plate is the largest that fits the red slot. Re-laying out pkg 120
to make room hung the game after the title screen (see docs), so the plates
must fit in place.

  python tools/cut_minigame_select_course_en.py
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
MOCKUP = MASTERS / "source" / "puzzle_course_en_mockup.png"
PKG = 120
# texture px -> mockup px (scale, x, y). The JP screenshot is 1:1 at 1.36×;
# both shots are the full 400×240 screen, so the mockup is 2.56×.
PLACE = {"070": (2.56, -175.81, -39.53), "071": (2.56, 542.49, -39.53)}
CHECKER_PERIOD = 6
EDGE_EXCLUDE = (14, 8)  # mockup columns at the left / right screen edge (plate border)
TEXT_COLS = {"070": (12, 331), "071": (695, 1020)}  # mockup columns of the lettering
TEXT_SCALE = 0.75


def text_core(mock: np.ndarray, key: str) -> np.ndarray:
    if key == "070":  # blue gradient letters, navy outline, blue-grey shadow
        return mock[..., 0] < 140
    return (mock[..., 1] < 150) & (mock[..., 0] - mock[..., 1] > 60)  # orange/red


def clean_plate(tex: np.ndarray) -> np.ndarray:
    """Vanilla plate with its text replaced by the checker from clean columns."""
    a = tex.astype(np.float32)
    ys, xs = np.where(a[..., 3] > 0)
    x0, x1 = xs.min(), xs.max() + 1
    ref0 = x0 + 12  # clear of the rounded corner, left of the text
    ref = a[:, ref0 : ref0 + CHECKER_PERIOD, :3]
    dev = np.zeros(a.shape[:2])
    for x in range(ref0, x1 - 5):
        dev[:, x] = np.abs(a[:, x, :3] - ref[:, (x - ref0) % CHECKER_PERIOD]).max(1)
    txt = (dev > 45) & ndi.binary_erosion(a[..., 3] > 250, iterations=4)
    lab, n = ndi.label(txt)
    txt = np.isin(lab, 1 + np.flatnonzero(ndi.sum(txt, lab, range(1, n + 1)) > 8))
    ty, tx = np.where(txt)
    out = a.copy()
    for x in range(tx.min() - 2, tx.max() + 3):
        rows = slice(ty.min() - 2, ty.max() + 3)
        out[rows, x, :3] = ref[rows, (x - ref0) % CHECKER_PERIOD]
    inner = ndi.binary_erosion(out[..., 3] > 250, iterations=4)
    for y in range(out.shape[0]):
        cols = np.flatnonzero(inner[y])
        if len(cols):
            out[y, cols, :3] = out[y, cols, :3].mean(0)
    return out


def en_text(mock: np.ndarray, tex: np.ndarray, key: str, grow: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """EN lettering resampled onto the texture grid → (rgb, alpha)."""
    s, x, y = PLACE[key]
    h, w = mock.shape[:2]
    plate = cv2.warpAffine(tex[..., 3].astype(np.float32) / 255, np.float32([[s, 0, x], [0, s, y]]), (w, h)) > 0.5
    inner = ndi.binary_erosion(plate, iterations=5)
    core = text_core(mock, key) & inner
    core[:, : EDGE_EXCLUDE[0]] = False
    core[:, w - EDGE_EXCLUDE[1] :] = False
    lab, n = ndi.label(core)
    core = np.isin(lab, 1 + np.flatnonzero(ndi.sum(core, lab, range(1, n + 1)) > 30))
    lab, _n = ndi.label(core)
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        if sl[0].stop - sl[0].start > 40 and sl[1].stop - sl[1].start < 12:
            core[lab == i] = False  # a plate border, not a letter
    letters = ndi.binary_fill_holes(ndi.binary_closing(core, iterations=1))
    mask = ndi.binary_dilation(letters, iterations=grow) & inner
    c0, c1 = TEXT_COLS[key]
    mask[:, :c0] = False
    mask[:, c1:] = False
    alpha = np.clip(ndi.distance_transform_edt(mask) / 1.5, 0, 1).astype(np.float32)
    pm = cv2.GaussianBlur(np.dstack([mock * alpha[..., None], alpha]).astype(np.float32), (0, 0), 0.45 * s)
    m = np.float32([[s, 0, x + 0.5 * s - 0.5], [0, s, y + 0.5 * s - 0.5]])
    o = cv2.warpAffine(pm, m, (tex.shape[1], tex.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    a = np.clip(o[..., 3], 0, 1)
    rgb = o[..., :3] / np.maximum(a, 1e-4)[..., None]
    if TEXT_SCALE != 1.0:
        ys, xs = np.where(a > 0.05)
        cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
        f = TEXT_SCALE
        pm = cv2.warpAffine(np.dstack([rgb * a[..., None], a]).astype(np.float32),
                            np.float32([[f, 0, cx * (1 - f)], [0, f, cy * (1 - f)]]),
                            (tex.shape[1], tex.shape[0]), flags=cv2.INTER_AREA)
        a = np.clip(pm[..., 3], 0, 1)
        rgb = pm[..., :3] / np.maximum(a, 1e-4)[..., None]
    return rgb, a


def main() -> int:
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    res = img.entries[PKG]
    res.parse(False)
    raw = {e.fn[:3]: e.parsed() for e in res.entries if e.fn[:3] in PLACE}
    mock = np.array(Image.open(MOCKUP).convert("RGB")).astype(np.float32)
    for key in PLACE:
        tex = np.array(l2mgtex.decode(raw[key]))
        plate = clean_plate(tex)
        rgb, a = en_text(mock, tex, key)
        out = plate.copy()
        out[..., :3] = rgb * a[..., None] + plate[..., :3] * (1 - a[..., None])
        path = MASTERS / f"PuzzleSelect_{key}.png"
        Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA").save(path)
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
