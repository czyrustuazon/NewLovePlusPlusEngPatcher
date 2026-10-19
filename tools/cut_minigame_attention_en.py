#!/usr/bin/env python3
"""Re-cut the mini-game attention masters from the EN mockup (needs scipy).

Offline tool. The bake only reads the committed PNGs in
``assets/images/minigame/`` (``deploy_minigame_textures_en.py``).

The mockup is a 1024×601 full-screen render on a cream background
(242, 240, 227). Text is keyed off that background, scaled to fit each
vanilla strip, and centred on the vanilla glyph box:

- title (006): 23 px tall, 5 alpha levels. The 3682-byte zlib slot does not
  hold 16-level edges at this width.
- A-button line (007, AttentionEnd 005): the 256 px strip width sets the scale.
- L/R line (005, under the A line): scaled to the strip width on its own so it
  stays as legible as the JP second line.
- 008 composite: vanilla 008 with the JP text replaced by the 64×64 background
  tile (000), then the EN title and A line pasted at the JP offsets.

  python tools/cut_minigame_attention_en.py
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

import l2mgtex  # noqa: E402
from img import Image as ImgBin  # noqa: E402
from nlpp_paths import require_vanilla_img  # noqa: E402

MASTERS = ROOT / "assets" / "images" / "minigame"
MOCKUP = MASTERS / "source" / "attention_start_en_mockup.png"
MOCKUP_BG = np.array([242, 240, 227], np.float32)
TITLE_H = 23
TITLE_ALPHA_LEVELS = 5


def _vanilla_textures() -> dict[str, Image.Image]:
    img = ImgBin(str(require_vanilla_img()))
    img.parse(False)
    out = {}
    for pkg_id, prefix in ((95, "AttentionStart"), (94, "AttentionEnd")):
        res = img.entries[pkg_id]
        res.parse(False)
        for e in res.entries:
            if e.fn.endswith(".l2mgtex"):
                out[f"{prefix}_{e.fn[:3]}"] = l2mgtex.decode(e.parsed()).convert("RGBA")
    return out


def matte(src: np.ndarray, y0: int, y1: int, *, drop_pink: bool = False,
          min_h: int = 0) -> Image.Image:
    """RGBA cut of the text in mockup rows ``y0:y1``."""
    a = src[y0:y1]
    dist = np.abs(a - MOCKUP_BG).max(2)
    white = (a[..., 2] > 238) & (a[..., 0] > 200) & (a[..., 1] > 200)
    mask = (dist > 45) | white
    if drop_pink:
        # Background heart dots touch the blue outline; the blue text has no pink.
        mask &= ~((a[..., 0] > a[..., 2] + 15) & ~white)
    lab, n = ndi.label(mask)
    sizes = ndi.sum(mask, lab, range(1, n + 1))
    ids = 1 + np.flatnonzero(sizes > 400)
    if min_h:
        # Drop shadow tails cut from the line above.
        sl = ndi.find_objects(lab)
        ids = [i for i in ids if sl[i - 1][0].stop - sl[i - 1][0].start >= min_h]
    keep = ndi.binary_closing(np.isin(lab, ids), iterations=1)
    # 1 px soft ring, un-blended against the mockup background.
    ring = ndi.binary_dilation(keep, iterations=1) & ~keep
    alpha = keep.astype(np.float32)
    alpha[ring] = np.clip(dist[ring] / 90.0, 0, 1)
    am = np.maximum(alpha, 1e-3)[..., None]
    rgb = np.clip(np.where(ring[..., None], (a - (1 - am) * MOCKUP_BG) / am, a), 0, 255)
    im = Image.fromarray(np.dstack([rgb, alpha * 255]).astype(np.uint8), "RGBA")
    ys, xs = np.where(alpha > 0.05)
    return im.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def fit(im: Image.Image, box_w: int, box_h: int) -> Image.Image:
    s = min(box_w / im.width, box_h / im.height)
    size = (max(1, round(im.width * s)), max(1, round(im.height * s)))
    return im.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")


def place(piece: Image.Image, w: int, h: int, cx: float, cy: float) -> Image.Image:
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.alpha_composite(piece, (max(0, round(cx - piece.width / 2)),
                                   max(0, round(cy - piece.height / 2))))
    return canvas


def glyph_center(im: Image.Image) -> tuple[float, float]:
    ys, xs = np.where(np.array(im)[..., 3] > 20)
    return (xs.min() + xs.max() + 1) / 2, (ys.min() + ys.max() + 1) / 2


def quantize_alpha(im: Image.Image, levels: int) -> Image.Image:
    a = np.array(im).astype(np.int32)
    al = np.round(a[..., 3] / 255 * (levels - 1)) / (levels - 1) * 255
    a[..., 3] = al
    a[al == 0, :3] = 0
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def strip_offset(strip: Image.Image, comp: np.ndarray) -> tuple[int, int]:
    """Where a JP strip sits inside the 008 composite (min abs diff on opaque px)."""
    sa = np.array(strip).astype(np.int32)
    ys, xs = np.where(sa[..., 3] > 200)
    best = None
    for dy in range(0, comp.shape[0] - strip.height + 1):
        for dx in range(0, comp.shape[1] - (xs.max() + 1) + 1):
            d = np.abs(comp[ys + dy, xs + dx, :3] - sa[ys, xs, :3]).mean()
            if best is None or d < best[0]:
                best = (d, dx, dy)
    return best[1], best[2]


def composite_008(jp: dict[str, Image.Image], title: Image.Image,
                  line: Image.Image) -> Image.Image:
    va = np.array(jp["AttentionStart_008"]).astype(np.int32)
    tile = np.array(jp["AttentionStart_000"]).astype(np.int32)
    opaque = va[..., 3] > 0
    ys, xs = np.where(opaque)
    # Background tile phase, from a text-free patch left of the stamp.
    y0, x0 = ys.min() + 52, xs.min() + 4
    reg = va[y0 : y0 + 50, x0 : x0 + 90, :3]
    best = None
    for oy in range(64):
        for ox in range(64):
            t = tile[(np.arange(y0, y0 + 50)[:, None] + oy) % 64,
                     (np.arange(x0, x0 + 90)[None, :] + ox) % 64, :3]
            d = np.abs(reg - t).mean()
            if best is None or d < best[0]:
                best = (d, ox, oy)
    _d, ox, oy = best
    h, w = va.shape[:2]
    bg = tile[(np.arange(h)[:, None] + oy) % 64, (np.arange(w)[None, :] + ox) % 64]
    comp = va.copy()
    offsets = []
    for strip in (jp["AttentionStart_006"], jp["AttentionStart_007"].crop((0, 0, 256, 32))):
        dx, dy = strip_offset(strip, va)
        offsets.append((dx, dy))
        sy, sx = np.where(np.array(strip)[..., 3] > 0)
        m = np.zeros((h, w), bool)
        m[sy + dy, sx + dx] = True
        m = ndi.binary_dilation(m, iterations=2) & opaque
        comp[m] = bg[m]
    out = Image.fromarray(comp.astype(np.uint8), "RGBA")
    out.alpha_composite(title, offsets[0])
    out.alpha_composite(line, offsets[1])
    return out


def main() -> int:
    src = np.array(Image.open(MOCKUP).convert("RGB")).astype(np.float32)
    jp = _vanilla_textures()

    title_cut = matte(src, 15, 95)
    line1_cut = matte(src, 500, 557, drop_pink=True)
    line2_cut = matte(src, 557, 601, drop_pink=True, min_h=15)

    title = quantize_alpha(
        place(fit(title_cut, 500, TITLE_H), 512, 32, *glyph_center(jp["AttentionStart_006"])),
        TITLE_ALPHA_LEVELS,
    )
    line1 = fit(line1_cut, 252, 28)
    line2 = fit(line2_cut, 252, 16)

    cx, cy = glyph_center(jp["AttentionStart_007"])
    a_only = place(line1, 256, 64, cx, cy)
    both = place(line1, 256, 64, cx, cy)
    both.alpha_composite(place(line2, 256, 64, cx, cy + (line1.height + line2.height) / 2))

    masters = {
        "AttentionStart_005": both,
        "AttentionStart_006": title,
        "AttentionStart_007": a_only,
        "AttentionStart_008": composite_008(jp, title, a_only),
        "AttentionEnd_005": place(line1, 256, 32, *glyph_center(jp["AttentionEnd_005"])),
    }
    for name, im in masters.items():
        path = MASTERS / f"{name}.png"
        im.save(path)
        print(f"wrote {path.relative_to(ROOT)} {im.size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
