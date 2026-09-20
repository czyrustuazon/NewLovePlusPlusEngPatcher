#!/usr/bin/env python3
"""Restore vanilla Com_Win_Warning chrome on pkg 5237.

The extra-data WARNING body is TRB DrawText (STRI 4429), not this BCLIM.
An earlier bake painted EN onto the empty window frame; this puts the
vanilla chrome back on the live ARC (keeps MultiWin EN).
"""
from __future__ import annotations

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

from deploy_common import iter_deploy_targets, resolve_img_paths  # noqa: E402

MOD_IMG, VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "win_warning_en"
PKG = 5237
TARGET = "timg/Com_Win_Warning.bclim"


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


def _extract_bclim(img_path: Path) -> bytes:
    raw = img_path.read_bytes()
    img = ImgBin(str(img_path))
    img.parse(False)
    res = img.entries[PKG]
    if res is None:
        raise SystemExit(f"pkg {PKG} missing in {img_path}")
    blob = raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
    tmp = OUT / f"_src_{img_path.stem}_{PKG:04d}"
    tmp.write_bytes(blob)
    pkg = Package(FileWindow(str(tmp)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    darc = DarcArchive(bytearray(arc_elem.parsed()))
    entry = darc.find(TARGET) or darc.find(Path(TARGET).name)
    if entry is None:
        raise SystemExit(f"missing {TARGET} in {img_path}")
    return darc.extract_file(entry)


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    if not VANILLA.is_file():
        raise SystemExit(f"missing vanilla {VANILLA}")

    OUT.mkdir(parents=True, exist_ok=True)
    vanilla_bclim = _extract_bclim(VANILLA)

    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
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
    if len(vanilla_bclim) != len(orig_b):
        raise SystemExit(
            f"vanilla bclim len {len(vanilla_bclim)} != live {len(orig_b)}"
        )
    if orig_b == vanilla_bclim:
        print("Com_Win_Warning already vanilla chrome; skip splice", flush=True)
        return 0
    darc.replace_same_size(entry, vanilla_bclim)
    print(f"restored vanilla {TARGET} ({len(vanilla_bclim)} bytes)", flush=True)

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
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("restored vanilla Com_Win_Warning chrome pkg", PKG, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
