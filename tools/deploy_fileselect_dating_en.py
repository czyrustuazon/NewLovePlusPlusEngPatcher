#!/usr/bin/env python3
"""Select Data post-game sheet: D-Duration → Dating @ FileSelect **5152**.

``D_Select_data03`` is the post-game profile BCLIM (Hometown / Dating / Title).
Zhoumaru painted ``D-Duration``; re-render **Dating** on the master with Heisei
W5 (same ink as the sheet) and splice into the live ARC.

  python tools/deploy_fileselect_dating_en.py
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

from bclimutil import (  # noqa: E402
    parse_bclim,
    png_to_bclim_etc1a4_same_size,
    png_to_bclim_rgba4444_same_size,
)
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_exact_zopfli, try_fast_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    AZAHAR_INSTANCES,
    find_ui_png,
    maybe_backup_img,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, _VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "fileselect_dating_en"
PKG = 5152
STEM = "D_Select_data03"
PATH = f"timg/{STEM}.bclim"
FOLDERS = ("FileSelect.check", "FileSelect")


def _zero_all_darc_pads(data: bytes) -> bytes:
    darc = DarcArchive(data)
    spans = sorted((e.offset, e.offset + e.length) for e in darc.files)
    t = bytearray(data)
    for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
        if b0 > a1:
            t[a1:b0] = b"\x00" * (b0 - a1)
    if spans and spans[-1][1] < len(data):
        t[spans[-1][1] :] = b"\x00" * (len(data) - spans[-1][1])
    return bytes(t)


def _compress_slot(patched: bytes, cmp_len: int) -> tuple[bytes, bytes]:
    candidates = [patched]
    zeroed = _zero_all_darc_pads(patched)
    if zeroed != patched:
        candidates.append(zeroed)
    last_err: Exception | None = None
    for i, cand in enumerate(candidates):
        label = "as-patched" if i == 0 else "unsalted pads"
        fast = try_fast_exact_slot(cand, cmp_len)
        if fast is not None:
            print(f"  hit exact-zlib fast-path ({label})", flush=True)
            return fast
        try:
            print(f"  escalating to zopfli ({label})", flush=True)
            return compress_exact_zopfli(cand, cmp_len)
        except RuntimeError as exc:
            last_err = exc
            print(f"  slot miss ({label}): {exc}", flush=True)
    assert last_err is not None
    raise last_err


def _deploy_targets() -> list[Path]:
    targets = list(iter_deploy_targets(MOD_IMG))
    seen = {p.resolve() for p in targets}
    for img in AZAHAR_INSTANCES.glob("*/user/load/mods/00040000000F4E00/romfs/img.bin"):
        rp = img.resolve()
        if rp.is_file() and rp not in seen:
            targets.append(rp)
            seen.add(rp)
    return targets


def _encode(png: Path, orig: Path, fmt: int) -> bytes:
    if fmt == 8:
        return png_to_bclim_rgba4444_same_size(png, orig)
    if fmt == 0xB:
        return png_to_bclim_etc1a4_same_size(png, orig)
    raise SystemExit(f"{PATH} fmt {fmt:#x} not RGBA4444/ETC1A4")


def _patch_arc(arc_bytes: bytes, tmp: Path) -> bytes:
    darc = DarcArchive(bytearray(arc_bytes))
    entry = darc.find(PATH) or darc.find(f"{STEM}.bclim")
    if entry is None:
        raise SystemExit(f"missing {PATH}")
    orig_b = darc.extract_file(entry)
    _pix, w, h, fmt, _ft = parse_bclim(orig_b)
    master = find_ui_png(FOLDERS, STEM, (w, h))
    if master is None:
        raise SystemExit(f"missing {STEM}.png under FileSelect.check ({w}x{h})")
    rgba = Image.open(master).convert("RGBA")
    if rgba.size != (w, h):
        raise SystemExit(f"master {rgba.size} != BCLIM {w}x{h}")
    png = tmp / f"{STEM}.png"
    orig = tmp / f"{STEM}.bclim"
    rgba.save(png)
    orig.write_bytes(orig_b)
    darc.replace_same_size(entry, _encode(png, orig, fmt))
    rgba.save(OUT / f"{STEM}_en.png")
    print(f"OK {PATH} <- {master.relative_to(ROOT)} fmt={fmt:#x} ({w}x{h})", flush=True)
    return bytes(darc.data)


def _write_slot(src_pkg: Path, pkg: Package, tuned: bytes, slot: bytes) -> None:
    blob = bytearray(src_pkg.read_bytes())
    entry_off = Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp or slot_len != len(slot) or len(tuned) != dec_len:
        raise SystemExit(
            f"ARC entry mismatch slot={slot_len}/{len(slot)} dec={dec_len}/{len(tuned)}"
        )
    blob[cmp_off : cmp_off + slot_len] = slot
    new_pkg = src_pkg.with_name(f"new_{src_pkg.name}")
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


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

    bak = maybe_backup_img(MOD_IMG, "fileselect_dating")

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
    print(f"live pkg {PKG} {arc_elem.fn} slot={cmp_len}", flush=True)

    patched = _patch_arc(arc_elem.parsed(), tmp)
    tuned, slot = _compress_slot(patched, cmp_len)
    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned or do.unused_data or not do.eof:
        raise SystemExit(f"pkg {PKG} exact zlib verify failed")
    print(f"  ARC exact zlib {len(slot)} unused_data=0", flush=True)
    _write_slot(src_pkg, pkg, tuned, slot)

    try:
        for dest in _deploy_targets():
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
            print("spliced", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("deployed FileSelect Dating", PKG, "->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
