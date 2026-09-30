#!/usr/bin/env python3
"""EN save-select 表面/裏面 toggle — ETC1A4 B_Card_b_btn_lite @ pkg 5238.

Zhoumaru NCommonIcon.check paints the two cells as Front Side / Back Side.
The highlight (B_Card_b_btn_on) and white pill (B_Card_b_btn_base) stay vanilla.
Patch the live NCommonIcon ARC so Back/Next/OK/Quit/Restore Default stay.
Bake last-writer after deploy_softkey_defaults_en.py.

  python tools/deploy_card_side_btn_en.py
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import parse_bclim, png_to_bclim_etc1a4_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_exact_zopfli, try_fast_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import AZAHAR_INSTANCES, find_ui_png, iter_deploy_targets, resolve_img_paths  # noqa: E402

MOD_IMG, _VANILLA = resolve_img_paths()


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

OUT = ROOT / "out" / "card_side_btn_en"
PKG = 5238
TARGET = "timg/B_Card_b_btn_lite.bclim"


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

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
    print(f"live pkg {PKG} slot={cmp_len}", flush=True)

    darc = DarcArchive(bytearray(arc_elem.parsed()))
    entry = darc.find(TARGET) or darc.find(Path(TARGET).name)
    if entry is None:
        raise SystemExit(f"missing {TARGET}")
    orig_b = darc.extract_file(entry)
    _pix, w, h, fmt, _ft = parse_bclim(orig_b)
    if fmt != 0xB:
        raise SystemExit(f"{TARGET} fmt {fmt:#x} not ETC1A4")
    master = find_ui_png(("NCommonIcon.check",), Path(TARGET).stem, (w, h))
    if master is None:
        raise SystemExit("missing Zhoumaru PNG for B_Card_b_btn_lite")
    rgba = Image.open(master).convert("RGBA")
    png = tmp / "B_Card_b_btn_lite.png"
    orig = tmp / "B_Card_b_btn_lite.bclim"
    rgba.save(png)
    orig.write_bytes(orig_b)
    darc.replace_same_size(entry, png_to_bclim_etc1a4_same_size(png, orig))
    rgba.save(OUT / "B_Card_b_btn_lite_en.png")
    print(f"OK {TARGET} <- {master.relative_to(ROOT)} ({w}x{h})", flush=True)

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

    print("deployed Front Side / Back Side pkg", PKG, "->", MOD_IMG, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
