#!/usr/bin/env python3
"""Bisect Title.arc black-screen: noop DARC rebuild (no new files).

Rebuilds Title.arc with the same 69 files. Packing usually grows ~576 bytes
(alignment). No Eng_Patch, no BCLYT edit.

  - If title goes **black** → any ARC size/layout change is toxic.
  - If title stays **OK** → growth itself is fine; only adding files breaks.

Usage:
  python tools/deploy_title_noop_rebuild_bisect.py
  # reinstall out/NewLovePlusPlus-EN.cia after patch_cia
"""
from __future__ import annotations

import hashlib
import shutil
import struct
import sys
import zlib
from pathlib import Path

import zopfli.zlib as zopfli_zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_exact_zopfli, _force_zero_gaps  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import iter_deploy_targets, resolve_img_paths  # noqa: E402

MOD_IMG, VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "title_noop_bisect"
PKG = 5261


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

    bak = MOD_IMG.with_suffix(".bin.bak_pre_title_noop_bisect")
    if not bak.is_file():
        bak.write_bytes(MOD_IMG.read_bytes())
        print("created", bak, flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = OUT / "extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)

    # Use live MOD so EN hub labels stay.
    src_img = MOD_IMG
    raw = src_img.read_bytes()
    img = ImgBin(str(src_img))
    img.parse(False)
    res = img.entries[PKG]
    src_pkg = pkg_dir / f"{PKG:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc.fw.len()
    orig_arc = bytes(arc.parsed())
    print(f"pkg {PKG} slot={cmp_len} arc={len(orig_arc)}", flush=True)

    darc = DarcArchive(bytearray(orig_arc))
    if darc.find("timg/Eng_Patch.bclim"):
        raise SystemExit("Eng_Patch still present — restore bak first")

    orig_hashes = {
        f.name: hashlib.sha1(darc.extract_file(f)).hexdigest() for f in darc.files
    }
    n_files = len(darc.files)
    darc.extract_all(extract_dir)

    rebuilt_path = OUT / "Title_noop.arc"
    darc.rebuild_from_dir(extract_dir, rebuilt_path)
    cand = _force_zero_gaps(rebuilt_path.read_bytes())
    print(
        f"noop rebuild: {len(orig_arc)} -> {len(cand)} (delta={len(cand) - len(orig_arc)})",
        flush=True,
    )

    d2 = DarcArchive(bytearray(cand))
    if len(d2.files) != n_files:
        raise SystemExit(f"file count changed {n_files} -> {len(d2.files)}")
    for name, h in orig_hashes.items():
        f = d2.find(name)
        if f is None or hashlib.sha1(d2.extract_file(f)).hexdigest() != h:
            raise SystemExit(f"integrity fail: {name}")
    if d2.find("timg/Eng_Patch.bclim"):
        raise SystemExit("Eng_Patch appeared unexpectedly")
    print(f"integrity OK ({n_files} files, no new entries)", flush=True)

    z0 = len(zopfli_zlib.compress(cand))
    print(f"zopfli={z0} slot={cmp_len}", flush=True)
    if z0 > cmp_len:
        raise SystemExit(f"zopfli {z0} exceeds slot {cmp_len}")

    tuned, slot = compress_exact_zopfli(cand, cmp_len)
    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned or do.unused_data or not do.eof:
        raise SystemExit("zlib verify failed")

    blob = bytearray(src_pkg.read_bytes())
    entry_off = Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp or slot_len != cmp_len:
        raise SystemExit("ARC entry mismatch")
    if len(tuned) != dec_len:
        delta = len(tuned) - dec_len
        print(f"ARC dec_len {dec_len} -> {len(tuned)}", flush=True)
        struct.pack_into("<I", blob, entry_off + 8, len(tuned))
        hdr_dec = struct.unpack_from("<I", blob, 20)[0]
        struct.pack_into("<I", blob, 20, hdr_dec + delta)
        print(f"pkg dec_len {hdr_dec} -> {hdr_dec + delta}", flush=True)
    else:
        print("ARC dec_len unchanged", flush=True)

    blob[cmp_off : cmp_off + cmp_len] = slot
    new_pkg = pkg_dir / f"new_{PKG:04d}"
    # splice reads new_* — also keep plain copy for inspection
    src_pkg.write_bytes(blob)  # overwrite extract with patched pkg header+slot
    new_pkg.write_bytes(blob)

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC):
            if b.parsed() != tuned:
                raise SystemExit("ARC mismatch")
        elif a.parsed() != b.parsed():
            raise SystemExit("DMST changed")
    print("DMST OK", flush=True)

    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("deployed NOOP rebuild bisect ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    print(
        "TEST: title OK => adding files was the killer. "
        "Title black => any ARC rebuild/size change is toxic.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
