#!/usr/bin/env python3
"""EN for the save-card name tabs — RGBA4444 B_Card04_txt01 / txt06 @ pkg 4152.

名前 / カノジョの名前 are gray glyphs on a transparent 128×28 sheet. The white
tab and the save's name are other panes. Zhoumaru Card.check paints txt01 as
"Last Name" (that is 苗字, not 名前) and crams "Girlfriend's Name" to the
sheet edge. Same Heisei path as the white headers: W5, size 15, 2× bilinear,
ink (68,68,68), left-aligned on a 16px strip at the top of the sheet.

Live Card.arc first so Flist Received Date and any packed card EN stay.
Runs after deploy_card_flist_en.py.

  python tools/deploy_card_name_labels_en.py
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import parse_bclim, png_to_bclim_rgba4444_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_exact_zopfli, try_fast_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    AZAHAR_INSTANCES,
    HEADER_CORE_PX,
    HEADER_INK,
    HEADER_STRIP_H,
    chrome_font,
    iter_deploy_targets,
    maybe_backup_img,
    resolve_img_paths,
)

MOD_IMG, _VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "card_name_labels_en"
PKG = 4152
# Vanilla ink starts at x≈13. Right margin keeps "Girlfriend's Name" inside 128.
PAD_X = 13
LABELS = [
    ("timg/B_Card04_txt01.bclim", "Name"),
    ("timg/B_Card04_txt06.bclim", "Girlfriend's Name"),
]
# Lyt_B_Card04_btn stores the field row hidden (pane flag bit 0 clear).
# The open path never sets that bit, so the sheet draws with no row.
SHOW_PANES = {
    "Vis_White_Base",
    *(f"Vis_com_btn_m_{i:02d}" for i in range(9)),
}


def _deploy_targets() -> list[Path]:
    targets = list(iter_deploy_targets(MOD_IMG))
    inst_root = AZAHAR_INSTANCES
    seen = {p.resolve() for p in targets}
    for img in inst_root.glob("*/user/load/mods/00040000000F4E00/romfs/img.bin"):
        rp = img.resolve()
        if rp.is_file() and rp not in seen:
            targets.append(rp)
            seen.add(rp)
    return targets


def show_field_row(layout: bytes) -> bytes:
    """Set the visible bit on the card field-row panes. Same file length."""
    import struct

    data = bytearray(layout)
    magic, _bom, header_size, _rev, file_size, section_count = struct.unpack_from(
        "<4sHHIII", data, 0
    )
    if magic != b"CLYT" or file_size != len(data):
        raise RuntimeError("bad card field layout")
    off = header_size
    shown = []
    for _ in range(section_count):
        tag = bytes(data[off : off + 4])
        size = struct.unpack_from("<I", data, off + 4)[0]
        if tag in (b"pan1", b"pic1"):
            name = bytes(data[off + 12 : off + 36]).split(b"\x00", 1)[0].decode("ascii")
            if name in SHOW_PANES:
                flag = data[off + 8]
                if flag & 1 == 0:
                    data[off + 8] = flag | 1
                    shown.append(name)
        off += size
    if set(shown) != SHOW_PANES:
        raise RuntimeError(f"field-row panes missing: {sorted(SHOW_PANES - set(shown))}")
    return bytes(data)


def render_tab_label(w: int, h: int, text: str) -> Image.Image:
    """Header-style Heisei strip, left-aligned, sitting at the top of the sheet.

    Vanilla glyphs occupy y 1–16 of the 28px canvas. Starting the renderer at
    the full plate height would draw larger than Heart to Heart / Profile.
    """
    strip_h = min(HEADER_STRIP_H, h)
    budget = (w - PAD_X - 4) * 2
    for size in range(HEADER_CORE_PX, 7, -1):
        scale = 2
        big = Image.new("L", (w * scale, strip_h * scale), 0)
        dr = ImageDraw.Draw(big)
        f = chrome_font(size * scale)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > budget or th > strip_h * scale - 2:
            continue
        x = PAD_X * scale - b[0]
        y = (strip_h * scale - th) // 2 - b[1]
        dr.text((x, y), text, font=f, fill=255)
        alpha = np.array(
            big.resize((w, strip_h), Image.Resampling.BILINEAR), dtype=np.float32
        )
        peak = float(alpha.max())
        if peak > 0:
            alpha = np.clip(alpha * (255.0 / peak), 0, 255)
        rgb = Image.new("RGB", (w, strip_h), HEADER_INK)
        strip = Image.merge(
            "RGBA", (*rgb.split(), Image.fromarray(alpha.astype(np.uint8), "L"))
        )
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.paste(strip, (0, 0))
        return canvas
    raise RuntimeError(f"cannot fit {text!r} into {w}x{h}")


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

    maybe_backup_img(MOD_IMG, "card_name_labels")
    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    raw = MOD_IMG.read_bytes()
    img = ImgBin(str(MOD_IMG))
    img.parse(False)
    res = img.entries[PKG]
    if res is None:
        raise SystemExit(f"pkg {PKG} missing")
    src_pkg = pkg_dir / f"{PKG:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc_elem.fw.len()
    print(f"live Card.arc slot={cmp_len} dec={len(arc_elem.parsed())}", flush=True)

    darc = DarcArchive(bytearray(arc_elem.parsed()))
    for path, en in LABELS:
        entry = darc.find(path) or darc.find(Path(path).name)
        if entry is None:
            raise SystemExit(f"missing {path}")
        orig_b = darc.extract_file(entry)
        _pix, w, h, fmt, _ft = parse_bclim(orig_b)
        if fmt != 8:
            raise SystemExit(f"{path} fmt {fmt:#x} not RGBA4444")
        rgba = render_tab_label(w, h, en)
        png = tmp / f"{Path(path).stem}.png"
        orig = tmp / f"{Path(path).stem}.bclim"
        rgba.save(png)
        orig.write_bytes(orig_b)
        darc.replace_same_size(entry, png_to_bclim_rgba4444_same_size(png, orig))
        rgba.save(OUT / f"{Path(path).stem}_en.png")
        print(f"OK {path} -> {en!r} {w}x{h} Heisei W5", flush=True)

    lyt_path = "blyt/Lyt_B_Card04_btn.bclyt"
    lyt_entry = darc.find(lyt_path)
    if lyt_entry is None:
        raise SystemExit(f"missing {lyt_path}")
    darc.replace_same_size(lyt_entry, show_field_row(darc.extract_file(lyt_entry)))
    print("OK field row visible", flush=True)

    patched = bytes(darc.data)
    fast = try_fast_exact_slot(patched, cmp_len)
    if fast is not None:
        tuned, slot = fast
        print("  hit exact-zlib fast-path", flush=True)
    else:
        print("  escalating to zopfli + empty-block pad", flush=True)
        tuned, slot = compress_exact_zopfli(patched, cmp_len)
    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned or do.unused_data or not do.eof:
        raise SystemExit("exact zlib verify failed")
    print(f"  ARC exact zlib {len(slot)} unused_data=0", flush=True)

    blob = bytearray(src_pkg.read_bytes())
    entry_off = Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp or slot_len != cmp_len or len(tuned) != dec_len:
        raise SystemExit("ARC entry mismatch")
    blob[cmp_off : cmp_off + cmp_len] = slot
    new_pkg = pkg_dir / f"new_{PKG:04d}"
    new_pkg.write_bytes(blob)

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC):
            if b.parsed() != tuned:
                raise SystemExit("ARC mismatch")
        elif a.parsed() != b.parsed():
            raise SystemExit(f"DMST changed {a.fn}")
    print("DMST unchanged OK", flush=True)

    try:
        for dest in _deploy_targets():
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
            print("spliced", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("deployed Name / Girlfriend's Name pkg", PKG, "->", MOD_IMG, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
