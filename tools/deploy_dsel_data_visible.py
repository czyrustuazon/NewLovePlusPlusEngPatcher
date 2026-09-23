#!/usr/bin/env python3
"""Data-card labels once, plus the folder-tab captions.

The save card's field words are the 256x512 sheet on Lyt_Dsel_data
Pic_Dsel_data (D_Select_data03). Pts_Dsel_Data.bclyt in the same archive
has a second Pic_Dsel_data, stored visible, 9px to the left. With the
English sheet on both, Please Select Data / Full Name and the other rows
draw twice. The parts picture stays hidden. Vis_Dsel_Data stays visible
so the card keeps the one aligned sheet.

Folder tabs are separate: Lyt_C_Com_folder @ pkg 5208 stores
Vis_folder_txt and Vis_folder_tx_00 hidden, and no animation names them.

  python tools/deploy_dsel_data_visible.py
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
from exact_zlib import compress_exact_zopfli, try_fast_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import iter_deploy_targets, maybe_backup_img, resolve_img_paths  # noqa: E402

MOD_IMG, _VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "dsel_data_visible"
# (pkg, layout, panes to show, panes to hide). Bit 0 is the visible flag.
# One field sheet on the card. The parts layout's copy sits 9px left.
PATCHES = (
    (5152, "blyt/Lyt_Dsel_data.bclyt", ("Vis_Dsel_Data",), ()),
    (5152, "blyt/Pts_Dsel_Data.bclyt", (), ("Pic_Dsel_data",)),
    # Common folder tab words. Body is Vis_C_Com_folder; the two tab
    # captions sit beside it and stay off with the file flag.
    (5208, "blyt/Lyt_C_Com_folder.bclyt", ("Vis_folder_txt", "Vis_folder_tx_00"), ()),
)


def _deploy_targets() -> list[Path]:
    targets = list(iter_deploy_targets(MOD_IMG))
    inst_root = ROOT / "out" / "azahar_instances"
    seen = {p.resolve() for p in targets}
    for img in inst_root.glob("*/user/load/mods/00040000000F4E00/romfs/img.bin"):
        rp = img.resolve()
        if rp.is_file() and rp not in seen:
            targets.append(rp)
            seen.add(rp)
    return targets


def set_pane_visible(layout: bytes, show: tuple[str, ...], hide: tuple[str, ...]) -> bytes:
    data = bytearray(layout)
    magic, _bom, header_size, _rev, file_size, section_count = struct.unpack_from(
        "<4sHHIII", data, 0
    )
    if magic != b"CLYT" or file_size != len(data):
        raise RuntimeError("bad layout")
    show_set = set(show)
    hide_set = set(hide)
    if show_set & hide_set:
        raise RuntimeError(f"pane both shown and hidden: {sorted(show_set & hide_set)}")
    off = header_size
    found = []
    for _ in range(section_count):
        tag = bytes(data[off : off + 4])
        size = struct.unpack_from("<I", data, off + 4)[0]
        if tag in (b"pan1", b"pic1"):
            name = bytes(data[off + 12 : off + 36]).split(b"\x00", 1)[0].decode("ascii")
            if name in show_set:
                data[off + 8] = data[off + 8] | 1
                found.append(name)
            elif name in hide_set:
                data[off + 8] = data[off + 8] & ~1
                found.append(name)
        off += size
    missing = (show_set | hide_set) - set(found)
    if missing:
        raise RuntimeError(f"missing panes: {sorted(missing)}")
    return bytes(data)


def _splice_pkg(
    img_raw: bytes,
    img: ImgBin,
    pkg_id: int,
    edits: list[tuple[str, tuple[str, ...], tuple[str, ...]]],
    pkg_dir: Path,
) -> None:
    res = img.entries[pkg_id]
    if res is None:
        raise SystemExit(f"pkg {pkg_id} missing")
    src_pkg = pkg_dir / f"{pkg_id:04d}"
    src_pkg.write_bytes(img_raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc_elem.fw.len()
    print(f"pkg {pkg_id} slot={cmp_len} dec={len(arc_elem.parsed())}", flush=True)

    darc = DarcArchive(bytearray(arc_elem.parsed()))
    for lyt, show, hide in edits:
        entry = darc.find(lyt)
        if entry is None:
            raise SystemExit(f"missing {lyt}")
        darc.replace_same_size(entry, set_pane_visible(darc.extract_file(entry), show, hide))
        shown = ", ".join(show) or "-"
        hidden = ", ".join(hide) or "-"
        print(f"OK {lyt} show={shown} hide={hidden}", flush=True)

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
    if not is_cmp or slot_len != cmp_len or len(tuned) != dec_len:
        raise SystemExit("ARC entry mismatch")
    blob[cmp_off : cmp_off + cmp_len] = slot
    new_pkg = pkg_dir / f"new_{pkg_id:04d}"
    new_pkg.write_bytes(blob)

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC):
            if b.parsed() != tuned:
                raise SystemExit("ARC mismatch")
        elif a.parsed() != b.parsed():
            raise SystemExit(f"other entry changed {a.fn}")


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    maybe_backup_img(MOD_IMG, "dsel_data_visible")
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    raw = MOD_IMG.read_bytes()
    img = ImgBin(str(MOD_IMG))
    img.parse(False)
    # Same package can hold more than one layout. Apply those edits to one
    # ARC, then compress once — a second pass would reload the vanilla slot.
    grouped: dict[int, list[tuple[str, tuple[str, ...], tuple[str, ...]]]] = {}
    for pkg_id, lyt, show, hide in PATCHES:
        grouped.setdefault(pkg_id, []).append((lyt, show, hide))
    ids = list(grouped)
    for pkg_id, edits in grouped.items():
        _splice_pkg(raw, img, pkg_id, edits, pkg_dir)

    try:
        for dest in _deploy_targets():
            splice_packages_into_img(dest, pkg_dir, ids, dest)
            print("spliced", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed label panes", ids, "->", MOD_IMG, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
