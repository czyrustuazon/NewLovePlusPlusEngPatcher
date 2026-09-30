#!/usr/bin/env python3
"""EN password-entry window title パスワード — ETC1A4 Pass_Win01 @ pkg 5251.

Zhoumaru master: assets/images/OptionPassword.check/timg/Pass_Win01.png
Not DrawText / TRB. Lyt_Pass_Info_Display / Pts_Pass_Display are pic panes only.
Vanilla bake left this package unpatched (pack_images miss); splice exact-zlib
into live bake the same way as other chrome deploys.
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

from deploy_common import (  # noqa: E402
    find_ui_png,
    maybe_backup_img,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "optionpassword_en"
PKG = 5251
ARC_NAME = "OptionPassword.arc"
TARGET = "timg/Pass_Win01.bclim"
STEM = "Pass_Win01"


def _extract_vanilla_pkg(vanilla: Path, pkg_dir: Path) -> Path:
    raw = vanilla.read_bytes()
    img = ImgBin(str(vanilla))
    img.parse(False)
    res = img.entries[PKG]
    src_pkg = pkg_dir / f"{PKG:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])
    return src_pkg


def _patch_pass_win(arc_bytes: bytes, tmp: Path) -> bytes:
    darc = DarcArchive(bytearray(arc_bytes))
    entry = darc.find(TARGET) or darc.find(Path(TARGET).name)
    if entry is None:
        raise SystemExit(f"missing {TARGET} in {ARC_NAME}")
    raw_b = darc.extract_file(entry)
    _pix, w, h, fmt, _ft = parse_bclim(raw_b)
    if fmt != 0xB:
        raise SystemExit(f"{TARGET} fmt {fmt} (expected ETC1A4)")
    master = find_ui_png(("OptionPassword.check",), STEM, (w, h))
    if master is None:
        raise SystemExit(
            f"missing Zhoumaru master {STEM}.png under OptionPassword.check "
            f"(need {w}x{h})"
        )
    png = tmp / "t.png"
    orig = tmp / "o.bclim"
    Image.open(master).convert("RGBA").save(png)
    orig.write_bytes(raw_b)
    darc.replace_same_size(entry, png_to_bclim_etc1a4_same_size(png, orig))
    preview = OUT / f"{STEM}_en.png"
    preview.write_bytes(png.read_bytes())
    print(f"OK {TARGET} <- {master.relative_to(ROOT)} ({w}x{h} ETC1A4)", flush=True)
    return bytes(darc.data)


def main() -> int:
    vanilla = VANILLA if VANILLA.is_file() else MOD_IMG
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    if not vanilla.is_file():
        raise SystemExit(f"missing vanilla img.bin: {vanilla}")

    bak = maybe_backup_img(MOD_IMG, "optionpassword")

    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    src_pkg = _extract_vanilla_pkg(vanilla, pkg_dir)
    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc_elem.fw.len()
    print(
        f"pkg {PKG} {ARC_NAME} dec={len(arc_elem.parsed())} slot={cmp_len}",
        flush=True,
    )

    patched = _patch_pass_win(arc_elem.parsed(), tmp)
    fast = try_fast_exact_slot(patched, cmp_len)
    if fast is not None:
        tuned, slot = fast
        print("exact-zlib fast-path", flush=True)
    else:
        print("escalating to zopfli…", flush=True)
        tuned, slot = compress_exact_zopfli(patched, cmp_len)

    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned or do.unused_data or not do.eof:
        raise SystemExit("exact zlib verify failed")
    print(f"ARC exact zlib {len(slot)} unused_data=0", flush=True)

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
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("deployed OptionPassword EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
