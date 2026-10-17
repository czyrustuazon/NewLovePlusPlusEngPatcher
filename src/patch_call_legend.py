"""Top-screen legend for the Called list's no-voice marker (Profile.arc, pkg 5252).

The Called list marks a typed name the heroine can't say as "Zack *"
(src/call_romaji_match.c). This explains the "*" under the Last Name /
First Name boxes on the top screen, the same way the Title "Eng Patch" line is
a rendered texture, but without a new file: Profile.arc must keep its
decompressed size (deploy_profile_en.patch_package).

The box art is LA8 and stored at power-of-two size, so it has unused rows below
the visible image: Profile_Info_Call01 240x152 in a 256x256 canvas,
Profile_Info_Call02 240x104 in 256x128. The legend is painted into those rows
and the box pane grows by LEGEND_H, with its bottom UVs stretched over them.
Panes are centred (origin 0x4), so ty moves down by half the growth to keep
the boxes where they were.
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from bclimutil import canvas_for_pixel_bytes, d2xy, gcm, parse_bclim

LEGEND_TEXT = "* = She can't say this name"
LEGEND_H = 16
INK = 51  # vanilla dark label ink (L8)
HALO = 255

# texture -> (visible height, [(layout, pic pane)])
TARGETS: dict[str, tuple[int, list[tuple[str, str]]]] = {
    "timg/Profile_Info_Call01.bclim": (152, [("blyt/Pts_Prf_Info_Call01.bclyt", "Pic_Call01")]),
    "timg/Profile_Info_Call02.bclim": (
        104,
        [
            ("blyt/Pts_Prf_Info_Call02.bclyt", "Pic_Call02"),
            ("blyt/Lyt_Prf_Info_Call02.bclyt", "Pic_Call02"),
        ],
    ),
}

LA8_FMT = 3
_PIC_TY = 8 + 32
_PIC_H = 8 + 64
_PIC_ORIGIN = 9
_PIC_UV = 0x60  # TL, TR, BL, BR (u, v) floats
_XY_TO_MORTON = {d2xy(i): i for i in range(64)}


def render_legend(font_path: Path, w: int, h: int = LEGEND_H, text: str = LEGEND_TEXT) -> Image.Image:
    """LA-style RGBA: dark ink with a 1px white halo, centred, transparent elsewhere."""
    for size in range(12, 7, -1):
        font = ImageFont.truetype(str(font_path), size)
        probe = ImageDraw.Draw(Image.new("L", (w, h)))
        b = probe.textbbox((0, 0), text, font=font)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w - 4 or th > h - 2:
            continue
        x, y = (w - tw) // 2 - b[0], (h - th) // 2 - b[1]
        halo = Image.new("L", (w, h), 0)
        body = Image.new("L", (w, h), 0)
        hd, bd = ImageDraw.Draw(halo), ImageDraw.Draw(body)
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                hd.text((x + ox, y + oy), text, font=font, fill=255)
        bd.text((x, y), text, font=font, fill=255)
        im = Image.new("RGBA", (w, h), (HALO, HALO, HALO, 0))
        im.putalpha(halo)
        ink = Image.new("RGBA", (w, h), (INK, INK, INK, 255))
        im.paste(ink, (0, 0), body)
        return im
    raise RuntimeError(f"cannot fit {text!r} in {w}x{h}")


def paint_la8_rows(raw: bytes, y0: int, im: Image.Image) -> bytes:
    """Write im into an LA8 BCLIM's canvas at (0, y0); rows may be past the
    visible height. Other texels keep their bytes."""
    pix, w, h, fmt, footer = parse_bclim(raw)
    if fmt != LA8_FMT:
        raise ValueError(f"expected LA8 (fmt {LA8_FMT}), got {fmt}")
    pot_w, pot_h = canvas_for_pixel_bytes(len(pix), w, h, 2)
    if im.width > pot_w or y0 + im.height > pot_h:
        raise ValueError(f"{im.size} at y {y0} does not fit the {pot_w}x{pot_h} canvas")
    tiles_x = max(1, gcm(pot_w, 8) // 8)
    out = bytearray(pix)
    src = im.convert("RGBA").load()
    for y in range(im.height):
        cy = y0 + y
        for x in range(im.width):
            r, g, b, a = src[x, y]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            i = ((cy // 8) * tiles_x + x // 8) * 64 + _XY_TO_MORTON[(x % 8, cy % 8)]
            out[2 * i : 2 * i + 2] = bytes([a, lum]) if a else b"\x00\x00"
    return bytes(out) + footer


def extend_pic_pane(layout: bytes, pane: str, visible_h: int, grow: int = LEGEND_H) -> bytes:
    """Grow a centred pic pane downward by grow px and map its new rows to
    texture rows visible_h..visible_h+grow (UV v past 1.0)."""
    data = bytearray(layout)
    header_size = struct.unpack_from("<H", data, 6)[0]
    count = struct.unpack_from("<I", data, 0x10)[0]
    off, found = header_size, False
    for _ in range(count):
        tag = bytes(data[off : off + 4])
        size = struct.unpack_from("<I", data, off + 4)[0]
        if tag == b"pic1" and data[off + 12 : off + 36].split(b"\0", 1)[0] == pane.encode():
            if data[off + _PIC_ORIGIN] != 0x4:
                raise ValueError(f"{pane}: origin {data[off + _PIC_ORIGIN]:#x}, expected centre 0x4")
            ty, h = (struct.unpack_from("<f", data, off + o)[0] for o in (_PIC_TY, _PIC_H))
            uv = list(struct.unpack_from("<8f", data, off + _PIC_UV))
            if h != visible_h or uv != [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0]:
                raise ValueError(f"{pane}: h={h} uv={uv}, expected vanilla {visible_h} / unit UVs")
            struct.pack_into("<f", data, off + _PIC_H, h + grow)
            struct.pack_into("<f", data, off + _PIC_TY, ty - grow / 2)
            v = (visible_h + grow) / visible_h
            struct.pack_into("<f", data, off + _PIC_UV + 5 * 4, v)
            struct.pack_into("<f", data, off + _PIC_UV + 7 * 4, v)
            found = True
        off += size
    if not found:
        raise ValueError(f"pic1 {pane} not found")
    return bytes(data)


def add_call_legend(darc, font_path: Path) -> list[str]:
    """Patch the Called box textures and panes in a Profile.arc DarcArchive."""
    logs = []
    for tex, (visible_h, panes) in TARGETS.items():
        entry = darc.find(tex)
        if entry is None:
            raise SystemExit(f"missing {tex}")
        raw = darc.extract_file(entry)
        _pix, w, _h, _fmt, _ft = parse_bclim(raw)
        darc.replace_same_size(entry, paint_la8_rows(raw, visible_h, render_legend(font_path, w)))
        for lyt, pane in panes:
            le = darc.find(lyt)
            if le is None:
                raise SystemExit(f"missing {lyt}")
            darc.replace_same_size(le, extend_pic_pane(darc.extract_file(le), pane, visible_h))
            logs.append(f"{Path(lyt).name} {pane} +{LEGEND_H}px legend ({Path(tex).name})")
    return logs
