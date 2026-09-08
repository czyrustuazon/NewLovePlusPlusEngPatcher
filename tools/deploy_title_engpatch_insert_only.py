#!/usr/bin/env python3
"""Bisect Title.arc Eng Patch black-screen: ADD unused BCLIM only (no BCLYT).

Adds ``timg/Eng_Patch.bclim`` (same size as Copyright) but does **not** wire it
into any layout. If the title stays healthy, DARC grow is OK and the prior
black-screen was the BCLYT edit. If it goes black again, DARC/package growth
is unsafe and we need another approach.

Usage:
  python tools/deploy_title_engpatch_insert_only.py
  # then reinstall CIA / reload LayeredFS and check title screen
"""
from __future__ import annotations

import hashlib
import shutil
import struct
import sys
import zlib
from pathlib import Path

import zopfli.zlib as zopfli_zlib
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import parse_bclim, png_to_bclim_etc1a4_same_size  # noqa: E402
from darcutil import DarcArchive, DarcFile  # noqa: E402
from exact_zlib import compress_exact_zopfli, _force_zero_gaps  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    UI_FONT,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "title_engpatch_bisect"
PKG = 5261
ENG_LINE = "Eng Patch v1.0.0-rc2"
ENG_REL = "timg/Eng_Patch.bclim"


def insert_file_entry_legacy(darc: DarcArchive, rel: str, after_rel: str) -> None:
    """Deprecated local helper — use DarcArchive.insert_file_entry."""
    darc.insert_file_entry(rel, after_rel=after_rel)


def render_eng(w: int, h: int) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    dr = ImageDraw.Draw(im)
    font = ImageFont.truetype(str(UI_FONT), 8)
    b = dr.textbbox((0, 0), ENG_LINE, font=font)
    tw, th = b[2] - b[0], b[3] - b[1]
    x = (w - tw) // 2 - b[0]
    y = (h - th) // 2 - b[1]
    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        dr.text((x + ox, y + oy), ENG_LINE, font=font, fill=(255, 255, 255, 255))
    dr.text((x, y), ENG_LINE, font=font, fill=(200, 200, 200, 255))
    return im


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

    # Prefer live MOD as ARC base so hub EN labels stay.
    src_img = MOD_IMG
    bak = MOD_IMG.with_suffix(".bin.bak_pre_engpatch_bisect")
    if not bak.is_file():
        bak.write_bytes(MOD_IMG.read_bytes())
        print("created", bak, flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = OUT / "extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)

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
    print(f"pkg {PKG} slot={cmp_len} arc={len(arc.parsed())}", flush=True)

    darc = DarcArchive(bytearray(arc.parsed()))
    if darc.find(ENG_REL):
        raise SystemExit(f"{ENG_REL} already present — restore bak first")

    orig = {
        f.name: hashlib.sha1(darc.extract_file(f)).hexdigest() for f in darc.files
    }
    darc.extract_all(extract_dir)

    cpath = extract_dir / "timg" / "Copyright.bclim"
    _pix, w, h, _fmt, _ft = parse_bclim(cpath.read_bytes())
    png = OUT / "Eng_Patch.png"
    render_eng(w, h).save(png)
    eng = png_to_bclim_etc1a4_same_size(png, cpath)
    (extract_dir / ENG_REL).write_bytes(eng)
    print(f"wrote {ENG_REL} {len(eng)} bytes (unused by layout)", flush=True)

    # Ensure BCLYT untouched
    lyt_before = (extract_dir / "blyt" / "Lyt_Copyright.bclyt").read_bytes()

    darc.insert_file_entry(ENG_REL, after_rel="timg/Copyright.bclim")
    rebuilt = OUT / "Title_insert_only.arc"
    darc.rebuild_from_dir(extract_dir, rebuilt)
    cand = _force_zero_gaps(rebuilt.read_bytes())

    d2 = DarcArchive(bytearray(cand))
    for name, h in orig.items():
        f = d2.find(name)
        if f is None or hashlib.sha1(d2.extract_file(f)).hexdigest() != h:
            raise SystemExit(f"integrity fail: {name}")
    if d2.extract_file(d2.find("blyt/Lyt_Copyright.bclyt")) != lyt_before:  # type: ignore[arg-type]
        raise SystemExit("BCLYT changed unexpectedly")
    if d2.find(ENG_REL) is None:
        raise SystemExit("Eng_Patch missing after rebuild")
    print("integrity OK (all original files + Eng_Patch); BCLYT unchanged", flush=True)

    z0 = len(zopfli_zlib.compress(cand))
    print(f"zopfli={z0} slot={cmp_len} dec={len(cand)}", flush=True)
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
            raise SystemExit("DMST changed")
    print("DMST OK", flush=True)

    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("deployed INSERT-ONLY Eng_Patch (not shown in UI) ->", MOD_IMG, flush=True)
    print("Rollback bak:", bak, flush=True)
    print(
        "TEST: title logo/menu should stay normal. If black again → DARC/package "
        "growth is the killer. If OK → prior crash was BCLYT wiring.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
