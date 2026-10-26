#!/usr/bin/env python3
"""Home header clock reads ``18D(Su)04:53 PM`` (ClockInfo pkg 5402).

Vanilla row is ``18日(日)午後04:53``: AM/PM sits between the weekday and
the hour. The glyphs are parts that code attaches at ``manl_pos_*`` anchors
in ``manl_lyt_left_0``. That layout is drawn rotated (anchors carry
rz=-90), so layout y is screen x with the sign flipped: higher y is
further left.

Row anchors (layout y, vanilla):

- ``btn05`` AM/PM, 26px glyph (ink 2..23) at scale 1: -13
- ``btn06``/``btn07`` hour digits, 16px (ink ±7) at scale 0.8: -32, -45
- ``btn10`` colon, 6px at scale 1: -55
- ``btn08``/``btn09`` minute digits: -65, -77

This deploy slides hour, colon and minutes left so the hour starts where
AM/PM started (same 2px gap after the weekday ``)``), then puts AM/PM 3px
after the minutes. Minute ink ended at screen x 82.6; AM/PM ink now ends
at 82.2, so the row keeps vanilla's span.

  python tools/deploy_header_clock_ampm_en.py
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

from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_to_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_clock_date_order_en import move_panes  # noqa: E402
from deploy_common import (  # noqa: E402
    iter_deploy_targets,
    maybe_backup_img,
    resolve_img_paths,
)

MOD_IMG, _VANILLA = resolve_img_paths()

PKG = 5402
LAYOUT = "blyt/manl_lyt_left_0.bclyt"
Y_OFF = 0x28  # translate.y inside a pane section

# Vanilla hour-tens ink starts 2px after AM/PM's left edge (y -13 + 13 - 2).
TIME_SHIFT = 24.4
AMPM_Y = -72.2

# pane -> (vanilla y, US y). Vanilla is checked so a re-run is a no-op and
# an unexpected layout fails loudly.
ANCHOR_Y: dict[str, tuple[float, float]] = {
    "manl_pos_btn06_0": (-32.0, -32.0 + TIME_SHIFT),
    "manl_pos_btn07_0": (-45.0, -45.0 + TIME_SHIFT),
    "manl_pos_btn10_0": (-55.0, -55.0 + TIME_SHIFT),
    "manl_pos_btn08_0": (-65.0, -65.0 + TIME_SHIFT),
    "manl_pos_btn09_0": (-77.0, -77.0 + TIME_SHIFT),
    "manl_pos_btn05_0": (-13.0, AMPM_Y),
}


def patch_layout(layout: bytes) -> tuple[bytes, int]:
    """Set each anchor's y to its US value. Returns (layout, panes changed)."""
    return move_panes(layout, ANCHOR_Y, offset=Y_OFF)


def _load_pkg(img_path: Path, pkg_dir: Path) -> tuple[Package, ARC]:
    raw = img_path.read_bytes()
    img = ImgBin(str(img_path))
    img.parse(False)
    ent = img.entries[PKG]
    if ent is None:
        raise SystemExit(f"pkg {PKG} missing")
    src = pkg_dir / f"{PKG:04d}"
    src.write_bytes(raw[ent.fw.base_offset : ent.fw.base_offset + ent.fw.len()])
    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    return pkg, arc


def _write_arc_slot(pkg_dir: Path, pkg: Package, slot: bytes, dec: bytes) -> None:
    src = pkg_dir / f"{PKG:04d}"
    blob = bytearray(src.read_bytes())
    entry_off = None
    for i in range(struct.unpack_from("=6sH", blob, 0)[1]):
        off = Package.ENTRY_SIZE + i * Package.ENTRY_SIZE
        if blob[off : off + 4] == b"ARC ":
            entry_off = off
            break
    if entry_off is None:
        raise SystemExit("ARC entry missing")
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
            raise SystemExit(f"other entry changed {old.fn}")


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    bak = maybe_backup_img(MOD_IMG, "header_clock_ampm")
    pkg_dir = ROOT / "out" / "header_clock_ampm_en" / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    pkg, arc = _load_pkg(MOD_IMG, pkg_dir)
    cmp_len = arc.fw.len()
    darc = DarcArchive(bytearray(arc.parsed()))
    lay = darc.find(LAYOUT)
    if lay is None:
        raise SystemExit(f"missing {LAYOUT}")
    patched, changed = patch_layout(darc.extract_file(lay))
    darc.replace_same_size(lay, patched)
    print(f"OK {LAYOUT} changed={changed}", flush=True)

    slot = compress_to_exact_slot(bytes(darc.data), cmp_len)
    do = zlib.decompressobj()
    # The exact-slot search may retune zero gaps between ARC files, so check
    # the layout itself after the round trip.
    got = do.decompress(slot)
    if do.unused_data or not do.eof:
        raise SystemExit("exact zlib verify failed")
    tuned = DarcArchive(bytearray(got))
    if tuned.extract_file(tuned.find(LAYOUT)) != patched:
        raise SystemExit(f"exact zlib changed {LAYOUT}")
    _write_arc_slot(pkg_dir, pkg, slot, got)
    print(f"ARC exact {len(slot)}", flush=True)

    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
            print("spliced", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed header clock HH:MM AM/PM ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)


if __name__ == "__main__":
    main()
