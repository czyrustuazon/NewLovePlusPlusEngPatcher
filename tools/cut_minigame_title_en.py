#!/usr/bin/env python3
"""Cut the Puzzle-dama title logo pieces from the EN mockup (needs scipy + cv2).

Offline tool. The bake only reads ``assets/images/minigame/PuzzleTitle_*.png``
(``deploy_minigame_textures_en.py``).

pkg 125 ``Title`` draws the logo from separate RGBA4444 ``.l2mgtex`` pieces:

  010 128×128  heart      もっと  → MORE
  007  64×64   bubble     も      → M
  006  64×64   bubble     え      → O
  008  64×64   bubble     ろ      → E
  005  64×64   bubble     !       (unchanged)
  011 256×128  burst      対戦    → BATTLE
  009 512×128  logo       ぱずるだま → PUZZLE-DAMA

The mockup is a 1024×621 render of the 400×240 top screen. ``PLACE`` maps
texture pixels to mockup pixels (scale, x, y). It was found by masked template
matching: the unchanged ``!`` bubble anchors the JP screenshot (1.36×) to the
mockup (2.59×); bubbles, heart and burst were then matched on colours their EN
and JP art share. The burst animates, so it is ~0.66× in the mockup frame.

Draw order, front to back: bubbles (later ones over earlier ones' shadows),
logo, heart, burst. Each piece is cut like this:

- background: the game's own tile (``002``, ETC1 64×64) fitted to the mockup,
  so the element mask is "differs from the tile";
- bubbles / burst: the JP silhouette; parts hidden behind a front piece keep the
  JP pixels (same ring, shadow and burst body);
- heart: the JP silhouette; parts hidden behind the logo or the M bubble take
  the nearest visible heart colour;
- logo: everything below its outer glow (found from the magenta outer ring)
  and above PUSH START BUTTON.

Each piece is then area-resampled to its texture grid and palette-quantized
(largest palette that fits the vanilla zlib slot). Raw resampled art is about
twice the slot size; the vanilla art is flat colour.

  python tools/cut_minigame_title_en.py
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

import l2mgtex  # noqa: E402
from bclimutil import decode_etc1a4_pixels  # noqa: E402
from img import Image as ImgBin  # noqa: E402
from nlpp_paths import require_vanilla_img  # noqa: E402

MASTERS = ROOT / "assets" / "images" / "minigame"
MOCKUP = MASTERS / "source" / "puzzle_title_en_mockup.png"
PKG = 125
# texture px -> mockup px: (scale, x, y)
PLACE = {
    "005": (2.59, 708, 156),
    "006": (2.61, 461, 18),
    "007": (2.59, 316, 26),
    "008": (2.61, 596, 65),
    "009": (2.59, -142.3, 232.3),
    "010": (2.59, 56, 49),
    "011": (1.72, 286.88, 128.12),
}
BUBBLES_FRONT_TO_BACK = ("005", "008", "006", "007")
EN_PIECES = ("006", "007", "008", "009", "010", "011")
TILE_SCALE = 2.59
PUSH_START_Y = 505  # mockup row where PUSH START BUTTON begins
LOGO_GLOW_PX = 3  # the magenta ring is the outer edge; more picks up the tile
PALETTES = (128, 96, 64, 48, 32, 24, 16)
SLOT_MARGIN = 100


def _vanilla() -> dict[str, tuple[bytes, int]]:
    """``{NNN: (l2mgtex bytes, zlib slot length)}`` for pkg 125."""
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    res = img.entries[PKG]
    res.parse(False)
    return {e.fn[:3]: (e.parsed(), e.fw.len()) for e in res.entries if e.fn.endswith(".l2mgtex")}


def _tile(raw: bytes) -> np.ndarray:
    """ETC1 (fmt 12) tile → RGB, via the ETC1A4 decoder with opaque alpha."""
    w, h, _fmt, n = l2mgtex.parse_header(raw)
    body = raw[l2mgtex.HEADER_LEN : l2mgtex.HEADER_LEN + n]
    buf = b"".join(b"\xff" * 8 + body[i : i + 8] for i in range(0, len(body), 8))
    return np.array(decode_etc1a4_pixels(buf, w, h).convert("RGB")).astype(np.float32)


def fit_background(mock: np.ndarray, tile: np.ndarray) -> np.ndarray:
    """Tile scaled to the mockup, phase and colour fitted on bare corners."""
    h, w = mock.shape[:2]
    reps = (h // 64 // 2 + 3, w // 64 // 2 + 3)
    big = np.tile(tile, (*reps, 1))
    up = cv2.resize(big, (round(big.shape[1] * TILE_SCALE), round(big.shape[0] * TILE_SCALE)),
                    interpolation=cv2.INTER_CUBIC)
    period = int(64 * TILE_SCALE)
    regs = ((0, 0, 330, 70), (880, 0, w, 330), (0, 330, 170, 600))
    best = None
    for py in range(period + 1):
        for px in range(period + 1):
            d = sum(np.abs(mock[y0:y1:3, x0:x1:3] - up[y0 + py : y1 + py : 3, x0 + px : x1 + px : 3]).mean()
                    for x0, y0, x1, y1 in regs)
            if best is None or d < best[0]:
                best = (d, px, py)
    _d, px, py = best
    bg = up[py : py + h, px : px + w].copy()
    a = np.concatenate([bg[y0:y1, x0:x1].reshape(-1, 3) for x0, y0, x1, y1 in regs])
    b = np.concatenate([mock[y0:y1, x0:x1].reshape(-1, 3) for x0, y0, x1, y1 in regs])
    for c in range(3):
        with np.errstate(all="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore")
            g, o = np.polyfit(a[:, c], b[:, c], 1)
        bg[..., c] = bg[..., c] * g + o
    print(f"background tile phase ({px}, {py})")
    return bg


def _warp(arr: np.ndarray, key: str, size: tuple[int, int]) -> np.ndarray:
    s, x, y = PLACE[key]
    return cv2.warpAffine(arr, np.float32([[s, 0, x], [0, s, y]]), size, flags=cv2.INTER_LINEAR)


def resample(key: str, src: np.ndarray, alpha: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Area-resample mockup-space RGB + alpha onto a piece's texture grid."""
    s, x, y = PLACE[key]
    pm = np.dstack([src * alpha[..., None], alpha]).astype(np.float32)
    pm = cv2.GaussianBlur(pm, (0, 0), 0.45 * s)
    m = np.float32([[s, 0, x + 0.5 * s - 0.5], [0, s, y + 0.5 * s - 0.5]])
    out = cv2.warpAffine(pm, m, size, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    a = np.clip(out[..., 3], 0, 1)
    rgb = out[..., :3] / np.maximum(a, 1e-4)[..., None]
    return np.dstack([np.clip(rgb, 0, 255), a * 255])


def quantize_to_slot(im: Image.Image, orig: bytes, slot: int) -> tuple[Image.Image, int]:
    for n in PALETTES:
        q = np.array(im.quantize(n, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).convert("RGBA"))
        q[q[..., 3] < 17] = 0
        out = Image.fromarray(q, "RGBA")
        if len(zlib.compress(l2mgtex.encode_like(orig, out), 9)) <= slot - SLOT_MARGIN:
            return out, n
    raise SystemExit("no palette fits the zlib slot")


def main() -> int:
    van = _vanilla()
    jp = {k: l2mgtex.decode(van[k][0]).convert("RGBA") for k in PLACE}
    mock = np.array(Image.open(MOCKUP).convert("RGB")).astype(np.float32)
    h, w = mock.shape[:2]
    bg = fit_background(mock, _tile(van["002"][0]))

    elem = ndi.binary_fill_holes(ndi.binary_opening(np.abs(mock - bg).max(2) > 40, iterations=1))
    alpha = {k: _warp(np.array(jp[k])[..., 3].astype(np.float32) / 255, k, (w, h)) for k in PLACE}
    jp_rgb = {k: _warp(np.array(jp[k].convert("RGB")).astype(np.float32), k, (w, h)) for k in PLACE}
    bubbles = np.zeros((h, w), bool)
    for k in BUBBLES_FRONT_TO_BACK:
        bubbles |= alpha[k] > 0.5

    # Logo top: first magenta outer-ring pixel per column, plus its AA edge.
    mag = (mock[..., 0] > 150) & (mock[..., 1] < 90) & (mock[..., 2] > 100)
    top = np.full(w, 10**6)
    for x in range(w):
        ys = np.flatnonzero(mag[280:430, x])
        if len(ys):
            y = y0 = 280 + ys[0]
            while y > 0 and y0 - y < LOGO_GLOW_PX and elem[y - 1, x] and mock[y - 1, x].min() > 170:
                y -= 1
            top[x] = y
    vx = np.flatnonzero(top < 10**6)
    for x in range(max(0, vx.min() - 40), min(w, vx.max() + 41)):
        if top[x] >= 10**6:
            top[x] = top[vx[np.abs(vx - x).argmin()]]
    # One-column spikes come from stray magenta-ish pixels above the ring.
    top = np.maximum(top, ndi.median_filter(top, size=15) - 1)
    rows = np.arange(h)[:, None]
    logo = elem & (rows >= top[None, :]) & (rows < PUSH_START_Y) & ~bubbles
    lab, n = ndi.label(logo)
    logo = np.isin(lab, 1 + np.flatnonzero(ndi.sum(logo, lab, range(1, n + 1)) > 2000))
    heart = (alpha["010"] > 0.5) & ~logo & ~bubbles
    burst = (alpha["011"] > 0.5) & ~logo & ~bubbles & ~heart

    def nearest_fill(vis: np.ndarray) -> np.ndarray:
        _d, (iy, ix) = ndi.distance_transform_edt(~vis, return_indices=True)
        return mock[iy, ix]

    pieces: dict[str, np.ndarray] = {}
    for i, k in enumerate(BUBBLES_FRONT_TO_BACK):
        if k not in EN_PIECES:
            continue
        front = np.zeros((h, w), bool)
        for f in BUBBLES_FRONT_TO_BACK[:i]:
            front |= alpha[f] > 0.5
        pieces[k] = resample(k, np.where(front[..., None], jp_rgb[k], mock), alpha[k], jp[k].size)
    hidden = (alpha["011"] > 0.5) & ~burst
    pieces["011"] = resample("011", np.where(hidden[..., None], jp_rgb["011"], mock), alpha["011"], jp["011"].size)
    pieces["010"] = resample("010", nearest_fill(heart), alpha["010"], jp["010"].size)
    pieces["009"] = resample("009", nearest_fill(logo), logo.astype(np.float32), jp["009"].size)
    for k in ("006", "007", "008", "010", "011"):
        pieces[k][..., 3] = np.array(jp[k])[..., 3]  # same silhouette as JP

    for k in EN_PIECES:
        raw, slot = van[k]
        im, n = quantize_to_slot(Image.fromarray(pieces[k].astype(np.uint8), "RGBA"), raw, slot)
        path = MASTERS / f"PuzzleTitle_{k}.png"
        im.save(path)
        print(f"wrote {path.relative_to(ROOT)} ({n} colours, slot {slot})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
