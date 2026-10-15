#!/usr/bin/env python3
"""Give the Web weather screen room for English.

``Weekly Forecast`` is painted into ``Web_Pnl_Wea`` and runs into the live
date ``10/13～10/19`` (pane ``Txt_Week``, 122px, starting ~115px into the
248px panel). The weekly day names (``Txt_Day_*``) are 14×14, a one-kanji
box, so ``Tue`` is clipped. Shorten the painted title to ``Weekly`` and
widen those day panes to 30×14.
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

from bclimutil import png_to_bclim_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_to_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    HEISEI_W5,
    maybe_backup_img,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()

PKG = 5316
PNG_REL = Path("assets/images/Web.check/timg/Web_Pnl_Wea.png")
PANEL_BCLIM = "timg/Web_Pnl_Wea.bclim"
LAYOUTS = ("blyt/Pts_Wea_Pnl.bclyt", "blyt/Lyt_Weather.bclyt")
TITLE = "Weekly"
# Clear the old title. Date text starts ~115px into the panel.
CLEAR_X0, CLEAR_X1 = 26, 144
CLEAR_Y0, CLEAR_Y1 = 73, 91
TITLE_X = 28
TITLE_CY = 82
# One kanji was 14×14. The capture is 64×28 (same as today's Mon) and the
# pane is 32×14, so the bitmap scales by half. Columns are 32px apart.
DAY_W = 32.0
DAY_DY = -4.0
HEISEI_W7 = HEISEI_W5.with_name("df-heiseigothic-w7.ttc")


def _pane_name(sec: bytes) -> str:
    return sec[12:36].split(b"\x00", 1)[0].decode("ascii", "ignore")


def patch_weather_layout(data: bytes) -> tuple[bytes, int]:
    """Widen ``Txt_Day_*`` once. Same file length. Returns (layout, n)."""
    if data[:4] != b"CLYT":
        raise ValueError("not CLYT")
    magic, bom, header_size, revision, _file_size, section_count = struct.unpack_from(
        "<4sHHIII", data, 0
    )
    sections: list[bytes] = []
    off = header_size
    changed = 0
    for _ in range(section_count):
        size = struct.unpack_from("<I", data, off + 4)[0]
        sec = bytearray(data[off : off + size])
        if sec[:4] == b"pic1" and _pane_name(sec).startswith("Txt_Day_"):
            width = struct.unpack_from("<f", sec, 8 + 60)[0]
            if abs(width - DAY_W) > 0.01:
                # Shift down only from the vanilla 14px kanji pane.
                if width < 20.0:
                    ty = struct.unpack_from("<f", sec, 8 + 32)[0]
                    struct.pack_into("<f", sec, 8 + 32, ty + DAY_DY)
                struct.pack_into("<f", sec, 8 + 60, DAY_W)
                changed += 1
        sections.append(bytes(sec))
        off += size
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


def paint_weekly_title(src: Path) -> "object":
    """Erase the long title and paint ``Weekly`` on the left of the pink bar."""
    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(src).convert("RGBA")
    pix = im.load()
    for y in range(CLEAR_Y0, CLEAR_Y1):
        bg = pix[170, y]
        for x in range(CLEAR_X0, CLEAR_X1):
            pix[x, y] = bg

    font_path = HEISEI_W7 if HEISEI_W7.is_file() else HEISEI_W5
    scale = 2
    size = 16 * scale
    font = ImageFont.truetype(str(font_path), size=size, index=1)
    overlay = Image.new("RGBA", (im.width * scale, im.height * scale), (0, 0, 0, 0))
    dr = ImageDraw.Draw(overlay)
    bbox = dr.textbbox((0, 0), TITLE, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = TITLE_X * scale - bbox[0]
    y = TITLE_CY * scale - th // 2 - bbox[1]
    outline = (118, 68, 58, 255)
    for ox, oy in (
        (-2, 0),
        (2, 0),
        (0, -2),
        (0, 2),
        (-2, -2),
        (2, -2),
        (-2, 2),
        (2, 2),
        (-2, 1),
        (2, 1),
        (1, -2),
        (1, 2),
    ):
        dr.text((x + ox, y + oy), TITLE, font=font, fill=outline)
    dr.text((x, y), TITLE, font=font, fill=(255, 255, 255, 255))
    small = overlay.resize(im.size, Image.Resampling.BILINEAR)
    im = Image.alpha_composite(im, small)
    if tw // scale > 90:
        raise RuntimeError(f"{TITLE!r} is {tw // scale}px; date starts near x=115")
    return im


def _load_pkg(img_path: Path, pkg_dir: Path) -> tuple[bytes, Package, ARC]:
    raw = img_path.read_bytes()
    img = ImgBin(str(img_path))
    img.parse(False)
    ent = img.entries[PKG]
    src = pkg_dir / f"{PKG:04d}"
    src.write_bytes(raw[ent.fw.base_offset : ent.fw.base_offset + ent.fw.len()])
    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    return raw, pkg, arc


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
    if not VANILLA.is_file() and not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    png_path = ROOT / PNG_REL
    if not png_path.is_file():
        raise SystemExit(f"missing {png_path}")
    painted = paint_weekly_title(png_path)
    painted.save(png_path)
    print(f"painted {TITLE!r} -> {png_path}", flush=True)

    bak = maybe_backup_img(MOD_IMG, "web_weather")
    out = ROOT / "out" / "web_weather_en"
    pkg_dir = out / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = out / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    _raw, pkg, arc = _load_pkg(MOD_IMG, pkg_dir)
    cmp_len = arc.fw.len()
    darc = DarcArchive(bytearray(arc.parsed()))

    panel = darc.find(PANEL_BCLIM)
    if panel is None:
        raise SystemExit(f"missing {PANEL_BCLIM}")
    orig_bclim = tmp / "Web_Pnl_Wea.bclim"
    orig_bclim.write_bytes(darc.extract_file(panel))
    png_fit = tmp / "Web_Pnl_Wea.png"
    painted.save(png_fit)
    darc.replace_same_size(panel, png_to_bclim_same_size(png_fit, orig_bclim))
    print("OK Web_Pnl_Wea.bclim", flush=True)

    for rel in LAYOUTS:
        entry = darc.find(rel)
        if entry is None:
            raise SystemExit(f"missing {rel}")
        patched, n = patch_weather_layout(darc.extract_file(entry))
        if n != 7 and n != 0:
            raise SystemExit(f"{rel} patched {n} day panes, expected 7 or 0")
        darc.replace_same_size(entry, patched)
        print(f"OK {rel} day panes={n}", flush=True)

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
    print("deployed Web weather spacing ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)


if __name__ == "__main__":
    main()
