#!/usr/bin/env python3
"""EN for the Camera Settings note CamSet_Alert01 (CameraSetting.arc @ 4151).

  撮影モード中でも特殊効果を変更することができます。
  → "Special effects can still be / changed in Photo Mode."

The Zhoumaru master read "During in Photo Mode, special effects can still be
changed." Its sibling CamSet_Alert00 ("During Photo Mode, parts cannot be
changed.") is good and stays as-is; this render matches it: Arial 13.25px,
baselines 14 / 28.5, ink (51, 51, 51), alpha ×1.4, centered on the 176×32 RGBA strip
(fit by mean alpha error against Alert00).

Overwrites ``assets/images/CameraSetting.check/timg/CamSet_Alert01.png``;
the normal ``pack_images`` pass bakes it (.check wins).

  python tools/render_camset_alert_en.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "images" / "CameraSetting.check" / "timg" / "CamSet_Alert01.png"
FONT = Path("C:/Windows/Fonts/arial.ttf")

LINES = ("Special effects can still be", "changed in Photo Mode.")
W, H = 176, 32
SIZE_PX = 13.25
BASELINES = (14.0, 28.5)
INK = (51, 51, 51)
# Arial at 4× BOX reads lighter than the master; 1.4 matches its total alpha.
ALPHA_GAIN = 1.4
SCALE = 4


def render() -> Image.Image:
    font = ImageFont.truetype(str(FONT), round(SIZE_PX * SCALE))
    mask = Image.new("L", (W * SCALE, H * SCALE), 0)
    draw = ImageDraw.Draw(mask)
    for text, base in zip(LINES, BASELINES):
        tw = draw.textlength(text, font=font)
        draw.text(((W * SCALE - tw) / 2, base * SCALE), text, font=font, fill=255, anchor="ls")
    alpha = np.array(mask.resize((W, H), Image.Resampling.BOX), dtype=np.float32)
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[:, :, :3] = INK
    rgba[:, :, 3] = np.clip(alpha * ALPHA_GAIN, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def main() -> None:
    im = render()
    cols = np.where(np.array(im)[:, :, 3].max(0) > 40)[0]
    if cols.min() < 2 or cols.max() > W - 3:
        raise SystemExit(f"text overflows {W}px strip: cols {cols.min()}..{cols.max()}")
    im.save(OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
