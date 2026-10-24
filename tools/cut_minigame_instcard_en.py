#!/usr/bin/env python3
"""Build the mini-game how-to-play card masters from the EN mockups (needs scipy).

Offline tool. The bake only reads ``assets/images/minigame/InstCard_*.png``
(``deploy_minigame_textures_en.py``).

Each game's ``InstCard`` ``000.l2mgtex`` (pkg 117 Puzzle-dama, 135 TwinBee+,
141 Yie Ar Kung-Fu+) is one 512×256 RGBA8 texture holding the 320×240
bottom-screen card at (96, 8): the left half (x 96–256) is the controls card,
the right half (x 256–416) is the game's tips card. Each EN half has its own
screenshot mockup; a half without one stays JP.

The mockups are softer than the game art, so only the pixels where the text
changed are taken from them:

1. Register the mockup on the JP left card (scale + offset, min abs diff).
2. Mask where the two differ, grow it to cover whole words, take the full box
   of each text-line-shaped region, feather 1 px.
3. Quantize the EN pixels to a palette (no dither). Raw screenshot noise does
   not fit the 87894-byte zlib slot.
4. Puzzle-dama only: sync the small logo with the title screen (pkg 125, ``PuzzleTitle_*``):
   the mockup has もえろ bubbles and MOE! in the burst. Paste the EN M / O / E
   bubbles and the BATTLE burst at the card positions of the JP pieces, keep
   the card's PUZZLE-DAMA on top, remove the mockup's small green BATTLE label,
   and redraw the ``!`` bubble over it.

  python tools/cut_minigame_instcard_en.py [117|135|141 ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

import cv2  # noqa: E402

import l2mgtex  # noqa: E402
from img import Image as ImgBin  # noqa: E402
from nlpp_paths import require_vanilla_img  # noqa: E402

MASTERS = ROOT / "assets" / "images" / "minigame"
LEFT = (96, 8, 256, 248)  # card box x0 y0 x1 y1 in the texture
RIGHT = (256, 8, 416, 248)
# pkg -> (master, [(mockup, card box)], Puzzle-dama logo sync, palette size)
SETS = {
    117: ("InstCard_Puzzle.png", (
        (MASTERS / "source" / "instcard_puzzle_left_en_mockup.png", LEFT),
        (MASTERS / "source" / "instcard_puzzle_right_en_mockup.png", RIGHT),
    ), True, 256),
    135: ("InstCard_TwinBee.png", (
        (MASTERS / "source" / "instcard_twinbee_left_en_mockup.png", LEFT),
        (MASTERS / "source" / "instcard_twinbee_right_en_mockup.png", RIGHT),
    ), False, 64),  # both halves at 128+ colours overflow the 90897-byte slot
    141: ("InstCard_KungFu.png", (
        # The mockup's art is softer than the game's, so a diff mask flags
        # every edge: replace explicit text regions (card px) at a fixed fit
        # (scale x, scale y, offset x, offset y) instead.
        (MASTERS / "source" / "instcard_kungfu_left_en_mockup.png", LEFT, {
            "place": (0.23, 0.2295, 5, 0),
            "regions": ((6, 3, 154, 21), (40, 112, 124, 129), (16, 137, 148, 224)),
        }),
    ), False, 256),
}
# Title pieces on the card (pkg 125 texture px -> card texture px): scale, x, y.
# Found by masked template matching of the JP pieces on the vanilla card.
CARD_LOGO = {
    "011": (0.26, 144.04, 67.96),  # burst (behind the wordmark)
    "007": (0.29, 156, 61),
    "006": (0.29, 171, 59),
    "008": (0.29, 187, 65),
    "005": (0.29, 200, 75),  # ! (unchanged, redrawn on top)
    "009": (0.29526, 102.912, 84.02),  # JP wordmark, only to protect it
}
LABEL_BOX = (190, 82, 222, 98)  # mockup's small green BATTLE label, x0 y0 x1 y1
DIFF_THR = 70
LINE_MAX_H = 22


def vanilla_texture(pkg: int) -> tuple[bytes, int]:
    """``(l2mgtex bytes, zlib slot length)`` of a package's InstCard."""
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    res = img.entries[pkg]
    res.parse(False)
    e = next(e for e in res.entries if e.fn == "000.l2mgtex")
    return e.parsed(), e.fw.len()


def register(mock: Image.Image, card: np.ndarray) -> Image.Image:
    """Mockup scaled and offset onto the card grid."""
    ch, cw = card.shape[:2]
    rgb = mock.convert("RGB")
    best = None
    for s in np.arange(0.225, 0.260, 0.0015):
        w, h = round(rgb.width * s), round(rgb.height * s)
        a = np.array(rgb.resize((w, h), Image.Resampling.LANCZOS)).astype(np.float32)
        for oy in range(-12, 13):
            for ox in range(-12, 13):
                y0, x0 = max(0, oy), max(0, ox)
                y1, x1 = min(ch, oy + h), min(cw, ox + w)
                if (y1 - y0) * (x1 - x0) < 0.8 * ch * cw:
                    continue
                d = np.abs(card[y0:y1, x0:x1, :3] - a[y0 - oy : y1 - oy, x0 - ox : x1 - ox]).mean()
                if best is None or d < best[0]:
                    best = (d, w, h, ox, oy)
    _d, w, h, ox, oy = best
    print(f"registered mockup {w}x{h} at ({ox}, {oy}), mean diff {_d:.1f}")
    out = Image.new("RGBA", (cw, ch))
    out.paste(mock.convert("RGBA").resize((w, h), Image.Resampling.LANCZOS), (ox, oy))
    return out


def place_fixed(mock: Image.Image, card: np.ndarray, sx: float, sy: float, ox: int, oy: int) -> Image.Image:
    ch, cw = card.shape[:2]
    out = Image.new("RGBA", (cw, ch))
    size = (round(mock.width * sx), round(mock.height * sy))
    out.paste(mock.convert("RGBA").resize(size, Image.Resampling.LANCZOS), (ox, oy))
    return out


def apply_card(jp: np.ndarray, mockup: Path, box: tuple[int, int, int, int],
               colors: int, opts: dict | None = None) -> int:
    """Blend the changed pixels of one EN card into ``jp`` in place."""
    opts = opts or {}
    x0, y0, x1, y1 = box
    card = jp[y0:y1, x0:x1].copy()
    if "place" in opts:
        en = np.array(place_fixed(Image.open(mockup), card, *opts["place"])).astype(np.float32)
    else:
        en = np.array(register(Image.open(mockup), card)).astype(np.float32)

    if "regions" in opts:
        m = np.zeros(card.shape[:2], bool)
        for rx0, ry0, rx1, ry1 in opts["regions"]:
            m[ry0:ry1, rx0:rx1] = True
        return _blend(jp, card, en, m, box, colors)

    m = np.abs(card - en)[..., :3].max(2) > DIFF_THR
    lab, n = ndi.label(m)
    sizes = ndi.sum(m, lab, range(1, n + 1))
    m = np.isin(lab, 1 + np.flatnonzero(sizes >= 6))
    m = ndi.binary_dilation(m, iterations=3)
    # Text lines: take the whole line box. Where the JP had dark text under an
    # EN letter the diff stays low and the letter would drop out. Done before
    # the closing, which can merge a line with its box outline.
    lab, _n = ndi.label(ndi.binary_dilation(m, structure=np.ones((1, 11), bool)))
    for sl in ndi.find_objects(lab):
        if sl[0].stop - sl[0].start <= LINE_MAX_H:
            m[sl[0], max(0, sl[1].start - 4) : sl[1].stop + 4] = True
    m = ndi.binary_closing(m, iterations=4)
    m = ndi.binary_fill_holes(m)
    return _blend(jp, card, en, m, box, colors)


def _blend(jp: np.ndarray, card: np.ndarray, en: np.ndarray, m: np.ndarray,
           box: tuple[int, int, int, int], colors: int) -> int:
    x0, y0, x1, y1 = box
    soft = np.clip(ndi.gaussian_filter(m.astype(np.float32), 0.8) * 1.5, 0, 1)[..., None]

    q = Image.fromarray(np.clip(en[..., :3], 0, 255).astype(np.uint8)).quantize(
        colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    en[..., :3] = np.array(q.convert("RGB"))
    out = card * (1 - soft) + en * soft
    out[..., 3] = card[..., 3]
    jp[y0:y1, x0:x1] = out
    return int(m.sum())


def _warp_piece(im: Image.Image, s: float, x: float, y: float) -> tuple[np.ndarray, np.ndarray]:
    """Area-resample a title piece onto the 512×256 card grid → (rgb, alpha)."""
    a = np.array(im.convert("RGBA")).astype(np.float32)
    a[..., :3] *= a[..., 3:] / 255
    a = cv2.GaussianBlur(a, (0, 0), 0.45 / s)
    m = np.float32([[s, 0, x + 0.5 * s - 0.5], [0, s, y + 0.5 * s - 0.5]])
    w = cv2.warpAffine(a, m, (512, 256), flags=cv2.INTER_LINEAR)
    al = np.clip(w[..., 3] / 255, 0, 1)
    return w[..., :3] / np.maximum(al, 1e-4)[..., None], al


def sync_logo(card: np.ndarray, vanilla: np.ndarray) -> None:
    """Make the card logo read MORE / M O E ! / BATTLE / PUZZLE-DAMA, in place."""
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    res = img.entries[125]
    res.parse(False)
    jp = {e.fn[:3]: l2mgtex.decode(e.parsed()) for e in res.entries if e.fn[:3] in CARD_LOGO}
    en = {k: Image.open(MASTERS / f"PuzzleTitle_{k}.png") for k in ("006", "007", "008", "011")}

    def over(rgb: np.ndarray, al: np.ndarray) -> None:
        card[..., :3] = rgb * al[..., None] + card[..., :3] * (1 - al[..., None])

    before = card.copy()
    _rgb, wordmark = _warp_piece(jp["009"], *CARD_LOGO["009"])
    rgb, al = _warp_piece(en["011"], *CARD_LOGO["011"])
    burst = al
    over(rgb, al * (1 - np.clip(wordmark * 1.5, 0, 1)))
    for k in ("007", "006", "008"):
        over(*_warp_piece(en[k], *CARD_LOGO[k]))
    _rgb, e_bubble = _warp_piece(jp["008"], *CARD_LOGO["008"])

    x0, y0, x1, y1 = LABEL_BOX
    box = np.zeros(card.shape[:2], bool)
    box[y0:y1, x0:x1] = True
    keep = (e_bubble > 0.3) | (burst > 0.3) | (wordmark > 0.3)
    label = np.abs(before - vanilla)[..., :3].max(2) > 25
    label = ndi.binary_dilation(box & label, iterations=1) & box & ~keep
    green = box.copy()
    green[:88] = False
    green &= (before[..., 1] - np.maximum(before[..., 0], before[..., 2]) > 20) & (e_bubble < 0.3) & (burst < 0.3)
    label |= ndi.binary_dilation(green, iterations=1) & box & (e_bubble < 0.3) & (burst < 0.3)
    rgb8 = np.ascontiguousarray(np.clip(card[..., :3], 0, 255).astype(np.uint8))
    card[label, :3] = cv2.inpaint(rgb8, label.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)[label]
    over(*_warp_piece(jp["005"], *CARD_LOGO["005"]))


def build(pkg: int) -> None:
    import zlib

    name, cards, logo, colors = SETS[pkg]
    van, slot = vanilla_texture(pkg)
    jp = np.array(l2mgtex.decode(van)).astype(np.float32)
    vanilla = jp.copy()
    for mockup, box, *opts in cards:
        n = apply_card(jp, mockup, box, colors, *opts)
        print(f"{mockup.name}: EN px {n}")
    if logo:
        sync_logo(jp, vanilla)
    im = Image.fromarray(np.clip(np.round(jp), 0, 255).astype(np.uint8), "RGBA")
    path = MASTERS / name
    im.save(path)
    size = len(zlib.compress(l2mgtex.encode_like(van, im), 9))
    print(f"wrote {path.relative_to(ROOT)} (zlib-9 {size}, slot {slot})")


def main() -> int:
    for pkg in [int(a) for a in sys.argv[1:]] or list(SETS):
        build(pkg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
