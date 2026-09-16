#!/usr/bin/env python3
"""Render the English CESA boot warning to match vanilla JP layout.

Fonts: NLPPPATCH Graphics & Text Reference (2025) Heisei Gothic, already
extracted to assets/fonts/reference/nlppatch-2025/. Proportional P faces
(index 1) so Latin isn't fullwidth.

Vanilla pkg 90 (240x400) composition we copy:
  red title line + 2px underline, second title line + 2px underline,
  black body, one red emphasis line, black closing.

Red and black are drawn on separate coverage masks (2x) so red AA is only
red↔white (no black fringe / fake drop-shadow). Coverage is quantized to a
short ramp so zlib still fits the 13667-byte TEX slot.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025"
ASSET = ROOT / "assets" / "images" / "cesa" / "CESA_240X400.png"
COMPANION_ASSET = ROOT / "assets" / "images" / "cesa" / "CESA_400X240.png"
OUT_PREVIEW = ROOT / "out" / "cesa_en" / "CESA_240X400_preview.png"
OUT_COMPANION_PREVIEW = ROOT / "out" / "cesa_en" / "CESA_400X240_preview.png"

W, H = 240, 400
SCALE = 2
CW, CH = W * SCALE, H * SCALE
RED = (255, 0, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
# Dark teal for the companion-screen highlights (no red).
TEAL = (16, 96, 112)
MARGIN = 12
MAX_TEXT_W = (W - 2 * MARGIN) * SCALE
UNDERLINE_H = 2 * SCALE
UNDERLINE_GAP = 4 * SCALE
TITLE_Y = 82 * SCALE
TITLE_AFTER_LINE = 6 * SCALE
TITLE_TO_BODY = 18 * SCALE
BODY_LEADING = 23 * SCALE
RAMP_STEPS = 12
# Companion uses a short ramp so the extra TEX still fits pkg 90.
COMPANION_RAMP_STEPS = 3

# Landscape pane beside CESA (CESA_400X240.texi; vanilla 16×16 stub).
COMPANION_W, COMPANION_H = 400, 240
COMPANION_CW, COMPANION_CH = COMPANION_W * SCALE, COMPANION_H * SCALE
COMPANION_MAX_TEXT_W = (COMPANION_W - 2 * MARGIN) * SCALE
COMPANION_TITLE_Y = 28 * SCALE
COMPANION_TITLE = "Thanks for playing!"
# Wrapped to the 400-wide landscape column.
COMPANION_BODY = (
    (("This is a passionate, ", "black"), ("free", "accent"), (" community project.", "black")),
    (("It should ", "black"), ("never be sold", "accent"), (".", "black")),
    (("If you paid for this, you were ", "black"), ("scammed", "accent"), (".", "black")),
    (("Please support it by buying the ", "black"), ("official release", "accent"), (".", "black")),
)

# Proportional Heisei Gothic (DFPHSGothic) — same family as the JP CESA.
TITLE_TTC = FONTS / "df-heiseigothic-w9.ttc"
BODY_TTC = FONTS / "df-heiseigothic-w5.ttc"
TTC_INDEX = 1  # DFPHSGothic proportional Latin (not fullwidth index 0)

TITLE = (
    "Please do not illegally",
    "distribute or download.",
)
BODY = (
    "Distributing game software without",
    "the rights holder's permission over",
    "the internet, or downloading it",
    "knowing it comes from an illegal",
    "source, is",
)
EMPHASIS = ("strictly prohibited by law.",)
CLOSING = (
    "Thank you for your understanding",
    "and cooperation.",
)


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.is_file():
        raise SystemExit(
            f"missing NLPPPATCH reference font: {path}\n"
            "Extract [NLPPATCH]_Graphics&Text_Reference_(2025).zip → "
            "assets/fonts/reference/nlppatch-2025/"
        )
    return ImageFont.truetype(str(path), size=size, index=TTC_INDEX)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t, l, t


def _fit_size(
    draw: ImageDraw.ImageDraw,
    lines: tuple[str, ...],
    path: Path,
    lo: int,
    hi: int,
    max_w: int,
) -> int:
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _font(path, mid)
        widest = max(_text_size(draw, line, font)[0] for line in lines)
        if widest <= max_w:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _center_x(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> tuple[int, int, int]:
    tw, th, ox, _oy = _text_size(draw, text, font)
    x = (CW - tw) // 2 - ox
    return x, tw, th


def _draw_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    y: int,
    underline: bool = False,
) -> int:
    x, tw, th = _center_x(draw, text, font)
    draw.text((x, y), text, font=font, fill=255)
    bottom = y + th
    if underline:
        uy = bottom + UNDERLINE_GAP
        x0 = (CW - tw) // 2
        draw.rectangle((x0, uy, x0 + tw - 1, uy + UNDERLINE_H - 1), fill=255)
        bottom = uy + UNDERLINE_H
    return bottom


def _downscale_mask(mask: Image.Image, w: int, h: int) -> np.ndarray:
    small = mask.resize((w, h), Image.Resampling.LANCZOS)
    return np.array(small, dtype=np.float32) / 255.0


def _quantize_ramp(coverage: np.ndarray, steps: int = RAMP_STEPS) -> np.ndarray:
    q = np.round(coverage * (steps - 1)) / (steps - 1)
    return np.clip(q, 0.0, 1.0)


def _composite_masks(
    accent_cov: np.ndarray,
    black_cov: np.ndarray,
    accent_rgb: tuple[int, int, int] = RED,
    steps: int = RAMP_STEPS,
) -> Image.Image:
    """White background; black and accent coverage never mix into each other."""
    h, w = black_cov.shape
    accent_cov = _quantize_ramp(accent_cov, steps)
    black_cov = _quantize_ramp(black_cov, steps)
    black_cov = np.where(accent_cov > 0.0, 0.0, black_cov)
    out = np.full((h, w, 3), 255.0, dtype=np.float32)
    out *= (1.0 - black_cov)[..., None]
    accent = np.array(accent_rgb, dtype=np.float32)
    a = accent_cov[..., None]
    out = out * (1.0 - a) + accent * a
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _runs_width(font: ImageFont.FreeTypeFont, runs: tuple[tuple[str, str], ...]) -> float:
    return sum(font.getlength(text) for text, _role in runs)


def _draw_runs(
    accent_draw: ImageDraw.ImageDraw,
    black_draw: ImageDraw.ImageDraw,
    runs: tuple[tuple[str, str], ...],
    font: ImageFont.FreeTypeFont,
    y: int,
    canvas_w: int,
    underline: bool = False,
) -> int:
    total = _runs_width(font, runs)
    x = (canvas_w - total) / 2.0
    max_th = 0
    x0 = x
    for text, role in runs:
        tw, th, ox, _oy = _text_size(accent_draw, text, font)
        target = accent_draw if role == "accent" else black_draw
        target.text((int(round(x)) - ox, y), text, font=font, fill=255)
        x += font.getlength(text)
        max_th = max(max_th, th)
    bottom = y + max_th
    if underline:
        uy = bottom + UNDERLINE_GAP
        x_line = int(round(x0))
        accent_draw.rectangle(
            (x_line, uy, x_line + int(round(total)) - 1, uy + UNDERLINE_H - 1),
            fill=255,
        )
        bottom = uy + UNDERLINE_H
    return bottom


def render_cesa_en() -> Image.Image:
    red_mask = Image.new("L", (CW, CH), 0)
    black_mask = Image.new("L", (CW, CH), 0)
    red_draw = ImageDraw.Draw(red_mask)
    black_draw = ImageDraw.Draw(black_mask)
    measure = red_draw

    title_size = _fit_size(
        measure, TITLE, TITLE_TTC, 12 * SCALE, 22 * SCALE, MAX_TEXT_W
    )
    body_lines = BODY + EMPHASIS + CLOSING
    body_size = _fit_size(
        measure, body_lines, BODY_TTC, 10 * SCALE, 15 * SCALE, MAX_TEXT_W
    )
    body_size = min(body_size, title_size - 3 * SCALE)

    title_font = _font(TITLE_TTC, title_size)
    body_font = _font(BODY_TTC, body_size)

    y = TITLE_Y
    for line in TITLE:
        y = _draw_line(red_draw, line, title_font, y, underline=True)
        y += TITLE_AFTER_LINE

    y += TITLE_TO_BODY
    leading = BODY_LEADING
    for line in BODY:
        _draw_line(black_draw, line, body_font, y)
        y += leading
    y += 2 * SCALE
    for line in EMPHASIS:
        _draw_line(red_draw, line, body_font, y)
        y += leading
    y += 2 * SCALE
    for line in CLOSING:
        _draw_line(black_draw, line, body_font, y)
        y += leading

    if y // SCALE > H - 8:
        raise RuntimeError(f"CESA layout overflow: content ends at y={y // SCALE}")

    return _composite_masks(
        _downscale_mask(red_mask, W, H),
        _downscale_mask(black_mask, W, H),
        RED,
    )


def render_cesa_companion_en() -> Image.Image:
    """400×240 gothic blurb for CESA_400X240.texi (pane beside CESA)."""
    accent_mask = Image.new("L", (COMPANION_CW, COMPANION_CH), 0)
    black_mask = Image.new("L", (COMPANION_CW, COMPANION_CH), 0)
    accent_draw = ImageDraw.Draw(accent_mask)
    black_draw = ImageDraw.Draw(black_mask)

    title_font = None
    for size in range(22 * SCALE, 13 * SCALE - 1, -1):
        font = _font(TITLE_TTC, size)
        if font.getlength(COMPANION_TITLE) <= COMPANION_MAX_TEXT_W:
            title_font = font
            break
    if title_font is None:
        raise RuntimeError("companion title does not fit")

    body_font = None
    for size in range(14 * SCALE, 9 * SCALE - 1, -1):
        font = _font(BODY_TTC, size)
        if all(_runs_width(font, line) <= COMPANION_MAX_TEXT_W for line in COMPANION_BODY):
            body_font = font
            break
    if body_font is None:
        raise RuntimeError("companion body does not fit")

    title_th = _text_size(accent_draw, COMPANION_TITLE, title_font)[1]
    body_th = max(
        _text_size(accent_draw, run[0], body_font)[1]
        for line in COMPANION_BODY
        for run in line
    )
    leading = body_th + 6 * SCALE
    block_h = (
        title_th
        + UNDERLINE_GAP
        + UNDERLINE_H
        + TITLE_TO_BODY
        + leading * len(COMPANION_BODY)
    )
    y = COMPANION_TITLE_Y
    if y + block_h > COMPANION_CH - 8 * SCALE:
        y = max(18 * SCALE, (COMPANION_CH - block_h) // 2)

    y = _draw_runs(
        accent_draw,
        black_draw,
        ((COMPANION_TITLE, "accent"),),
        title_font,
        y,
        COMPANION_CW,
        underline=True,
    )
    y += TITLE_TO_BODY
    for line in COMPANION_BODY:
        y = _draw_runs(accent_draw, black_draw, line, body_font, y, COMPANION_CW)
        y += 6 * SCALE

    if y > COMPANION_CH - 8 * SCALE:
        raise RuntimeError(f"companion layout overflow: content ends at y={y // SCALE}")

    return _composite_masks(
        _downscale_mask(accent_mask, COMPANION_W, COMPANION_H),
        _downscale_mask(black_mask, COMPANION_W, COMPANION_H),
        TEAL,
        COMPANION_RAMP_STEPS,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Render English CESA PNG (NLPPPATCH fonts)")
    ap.add_argument(
        "--write-asset",
        action="store_true",
        help=f"Overwrite {ASSET} and {COMPANION_ASSET}",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=OUT_PREVIEW,
        help="Preview PNG path (ignored when --write-asset)",
    )
    ap.add_argument(
        "--companion-out",
        type=Path,
        default=OUT_COMPANION_PREVIEW,
        help="Companion preview PNG (ignored when --write-asset)",
    )
    args = ap.parse_args()
    im = render_cesa_en()
    dest = ASSET if args.write_asset else args.out
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest)
    print(f"[cesa] rendered {im.size} -> {dest}", flush=True)

    companion = render_cesa_companion_en()
    cdest = COMPANION_ASSET if args.write_asset else args.companion_out
    cdest.parent.mkdir(parents=True, exist_ok=True)
    companion.save(cdest)
    print(f"[cesa] companion {companion.size} -> {cdest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
