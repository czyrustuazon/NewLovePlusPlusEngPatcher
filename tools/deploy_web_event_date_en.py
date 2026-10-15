#!/usr/bin/env python3
"""Show the Web event-card date as MM/DD Update in its original spot.

The four ``Web_Num12`` digits stay at vanilla centers 34, 40, 58, 64
(month, then day). ``Web_Txt_Date`` is the slash between those pairs plus a
smaller ``Update`` after the day. A full-size ``Update`` runs off the 64px
picture, and sliding the row left covers the Spot-tab HOT badge. The pane
stays at center 73, width 64.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from PIL import Image, ImageDraw  # noqa: E402

from bclimutil import png_to_bclim_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_to_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    chrome_font,
    iter_deploy_targets,
    maybe_backup_img,
    resolve_img_paths,
)

MOD_IMG, _VANILLA = resolve_img_paths()

PKG = 5316
PNG_REL = Path("assets/images/Web.check/timg/Web_Txt_Date.png")
DATE_BCLIM = "timg/Web_Txt_Date.bclim"
LAYOUTS = ("blyt/Lyt_Spot.bclyt", "blyt/Pts_Spot_Pnl.bclyt")

TEX_W, TEX_H = 64, 16
FONT_SIZE = 14
UPDATE = "Update"
UPDATE_SIZE = 11
# Pic_Txt_Date center / width. Vanilla, and where a widened experiment returns.
VANILLA_X = 73.0
VANILLA_W = 64.0
# The left-shifted experiment this deploy undoes.
WIDE_X = 60.0
WIDE_W = 80.0
# Slash center inside the 64px picture. Pane left is 41, so this is world x=49,
# midway between month-ones (40) and day-tens (58).
SLASH_LOCAL = 8
# Left edge of "Update". Day-ones ink ends near local 25 (center 64).
# Size 11 is 34px, so the word ends before the picture's right edge.
UPDATE_LEFT = 28


def _draw_label(draw: ImageDraw.ImageDraw, text: str, font, left: int) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    th = box[3] - box[1]
    x = left - box[0]
    y = (TEX_H - th) // 2 - box[1]
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))


def paint_date_label() -> Image.Image:
    """Slash at the date gap, then a smaller Update that stays inside 64px."""
    im = Image.new("RGBA", (TEX_W, TEX_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    slash = chrome_font(FONT_SIZE)
    box = draw.textbbox((0, 0), "/", font=slash)
    _draw_label(draw, "/", slash, SLASH_LOCAL - (box[2] - box[0]) // 2)
    _draw_label(draw, UPDATE, chrome_font(UPDATE_SIZE), UPDATE_LEFT)
    px = im.load()
    for yy in range(TEX_H):
        for xx in range(TEX_W):
            px[xx, yy] = (255, 255, 255, 255) if px[xx, yy][3] > 96 else (0, 0, 0, 0)
    return im


def _pane_name(sec: bytes) -> str:
    return sec[12:36].split(b"\x00", 1)[0].decode("ascii", "ignore")


def patch_date_layout(data: bytes) -> tuple[bytes, bool]:
    """Put ``Pic_Txt_Date`` back at its vanilla center and width."""
    if data[:4] != b"CLYT":
        raise ValueError("not CLYT")
    magic, bom, header_size, revision, _file_size, section_count = struct.unpack_from(
        "<4sHHIII", data, 0
    )
    sections: list[bytes] = []
    off = header_size
    changed = False
    found = False
    for _ in range(section_count):
        size = struct.unpack_from("<I", data, off + 4)[0]
        sec = bytearray(data[off : off + size])
        if sec[:4] == b"pic1" and _pane_name(sec) == "Pic_Txt_Date":
            found = True
            x = struct.unpack_from("<f", sec, 8 + 28)[0]
            width = struct.unpack_from("<f", sec, 8 + 60)[0]
            already = abs(x - VANILLA_X) < 0.01 and abs(width - VANILLA_W) < 0.01
            widened = abs(x - WIDE_X) < 0.01 and abs(width - WIDE_W) < 0.01
            if not already:
                if not widened:
                    raise ValueError(
                        f"Pic_Txt_Date is x={x} w={width}, expected vanilla "
                        f"{VANILLA_X}x{VANILLA_W} or the widened pane"
                    )
                struct.pack_into("<f", sec, 8 + 28, VANILLA_X)
                struct.pack_into("<f", sec, 8 + 60, VANILLA_W)
                changed = True
        sections.append(bytes(sec))
        off += size
    if not found:
        raise ValueError("layout has no Pic_Txt_Date")
    out = bytearray()
    out += struct.pack("<4sHHIII", magic, bom, header_size, revision, 0, section_count)
    if len(out) < header_size:
        out.extend(b"\x00" * (header_size - len(out)))
    for sec in sections:
        out.extend(sec)
    struct.pack_into("<I", out, 0x0C, len(out))
    if len(out) != len(data):
        raise ValueError(f"layout grew {len(data)} -> {len(out)}")
    return bytes(out), changed


def _load_pkg(img_path: Path, pkg_dir: Path) -> tuple[Package, ARC]:
    raw = img_path.read_bytes()
    img = ImgBin(str(img_path))
    img.parse(False)
    ent = img.entries[PKG]
    src = pkg_dir / f"{PKG:04d}"
    src.write_bytes(raw[ent.fw.base_offset : ent.fw.base_offset + ent.fw.len()])
    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    return pkg, arc


def _write_arc_slot(pkg_dir: Path, pkg: Package, slot: bytes, dec: bytes) -> Path:
    src = pkg_dir / f"{PKG:04d}"
    blob = bytearray(src.read_bytes())
    entry_off = Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp or slot_len != len(slot) or len(dec) != dec_len:
        raise SystemExit(
            f"ARC entry mismatch cmp={is_cmp} slot {len(slot)}/{slot_len} "
            f"dec {len(dec)}/{dec_len}"
        )
    blob[cmp_off : cmp_off + slot_len] = slot
    new_pkg = pkg_dir / f"new_{PKG:04d}"
    new_pkg.write_bytes(blob)
    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for old, new in zip(pkg.entries, pkg2.entries):
        if isinstance(old, ARC):
            if new.parsed() != dec:
                raise SystemExit("ARC round-trip mismatch")
        elif old.parsed() != new.parsed():
            raise SystemExit("DMST changed")
    return new_pkg


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    painted = paint_date_label()
    png_path = ROOT / PNG_REL
    png_path.parent.mkdir(parents=True, exist_ok=True)
    painted.save(png_path)
    print(f"painted date label -> {png_path}", flush=True)

    bak = maybe_backup_img(MOD_IMG, "web_event_date")
    out = ROOT / "out" / "web_event_date_en"
    pkg_dir = out / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = out / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    pkg, arc = _load_pkg(MOD_IMG, pkg_dir)
    cmp_len = arc.fw.len()
    darc = DarcArchive(bytearray(arc.parsed()))

    entry = darc.find(DATE_BCLIM)
    if entry is None:
        raise SystemExit(f"missing {DATE_BCLIM}")
    orig_bclim = tmp / "Web_Txt_Date.bclim"
    orig_bclim.write_bytes(darc.extract_file(entry))
    png_fit = tmp / "Web_Txt_Date.png"
    painted.save(png_fit)
    darc.replace_same_size(entry, png_to_bclim_same_size(png_fit, orig_bclim))
    print("OK Web_Txt_Date.bclim", flush=True)

    for rel in LAYOUTS:
        lay = darc.find(rel)
        if lay is None:
            raise SystemExit(f"missing {rel}")
        patched, changed = patch_date_layout(darc.extract_file(lay))
        darc.replace_same_size(lay, patched)
        print(f"OK {rel} widened={changed}", flush=True)

    tuned_slot = compress_to_exact_slot(bytes(darc.data), cmp_len)
    do = zlib.decompressobj()
    got = do.decompress(tuned_slot)
    if do.unused_data or not do.eof:
        raise SystemExit("zlib verify failed")
    _write_arc_slot(pkg_dir, pkg, tuned_slot, got)
    print(f"ARC exact {len(tuned_slot)}", flush=True)

    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed Web event date ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)


if __name__ == "__main__":
    main()
