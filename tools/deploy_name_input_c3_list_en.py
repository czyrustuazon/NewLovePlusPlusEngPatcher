#!/usr/bin/env python3
"""C3: hometown-style candidate list chrome (Input pkg 5190 + Profile 5252).

Name-input ML grid loads **InputCTexture / InputNTexture @ pkg 5190**, not
Profile.arc alone. Patches both 5190 ARCs plus 5252 Profile.arc for parity.

  python tools/deploy_name_input_c3_list_en.py
  python tools/deploy_name_input_c3_list_en.py --dest "../New Love Plus Plus/extracted/romfs/img.bin"

Splices into live img.bin. Rebuild .3ds / fully quit Azahar after deploy.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import (  # noqa: E402
    parse_bclim,
    png_to_bclim_etc1a4_same_size,
    png_to_bclim_rgb565_same_size,
    png_to_bclim_rgba4444_same_size,
)
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import _force_zero_gaps, compress_exact_with_gap_tune  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import iter_deploy_targets, resolve_img_paths  # noqa: E402

MOD_IMG, _VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "c3_list_en"

# Name-input runtime path (verified: same timg/* names as Profile.arc).
PKG_INPUT = 5190
INPUT_ARCS = ("InputCTexture.arc", "InputNTexture.arc")

# Profile field screens share the same BCLIM names.
PKG_PROFILE = 5252
PROFILE_ARC = "Profile.arc"

# Left ML column width matches Profile_Btn_Com01 cell chrome.
LIST_COL_W = 88
CELL_H = 40
LINE_W = 1

ROW_A = (255, 255, 255, 255)
ROW_B = (204, 229, 255, 255)
LINE = (0, 0, 0, 255)
# Neutral fill for per-cell RGB565 (no checkerboard grid on empty columns).
NEUTRAL = (210, 210, 210)

ETC1_NEUTRAL = ("timg/Profile_Btn_Com01_Color.bclim",)
ETC1_MLIST = (
    "timg/Profile_Win_MList_H.bclim",
    "timg/Profile_Win_MList_V.bclim",
)
RGB565_NEUTRAL = (
    "timg/Profile_Btn_Com01_Base.bclim",
    "timg/Profile_Btn_Com01_Efe.bclim",
    "timg/Profile_Win_MList_H_P01.bclim",
    "timg/Profile_Win_MList_V_P01.bclim",
)


def _next_pot(x: int) -> int:
    p = 1
    while p < x:
        p *= 2
    return p


def _etc1_pot(log_w: int, log_h: int, pix_len: int) -> tuple[int, int]:
    blocks = pix_len // 16
    pot_w, pot_h = _next_pot(log_w), _next_pot(log_h)
    if (pot_w // 4) * (pot_h // 4) != blocks:
        from bclimutil import canvas_for_pixel_bytes

        pot_w, pot_h = canvas_for_pixel_bytes(pix_len, log_w, log_h, 16)
        if (pot_w // 4) * (pot_h // 4) != blocks:
            bw = _next_pot(log_w) // 4
            if bw == 0 or blocks % bw:
                raise SystemExit(
                    f"unexpected ETC1A4 canvas for {log_w}x{log_h} ({pix_len} px)"
                )
            bh = blocks // bw
            pot_w, pot_h = bw * 4, bh * 4
    return pot_w, pot_h


def _pot_wh(orig_bytes: bytes) -> tuple[int, int, int, int]:
    pix, w, h, fmt, _ = parse_bclim(orig_bytes)
    if fmt == 0xB:
        pot_w, pot_h = _etc1_pot(w, h, len(pix))
        return w, h, pot_w, pot_h
    if fmt == 3:
        return w, h, w, h
    raise SystemExit(f"unsupported fmt {fmt:#x}")


def draw_bplace_stripes(
    im: Image.Image,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    row_h: int = CELL_H,
) -> None:
    dr = ImageDraw.Draw(im)
    y = y0
    row = 0
    while y < y1:
        y_end = min(y + row_h - LINE_W, y1)
        fill = ROW_A if row % 2 == 0 else ROW_B
        dr.rectangle((x0, y, x1 - 1, y_end - 1), fill=fill)
        if y_end < y1:
            dr.rectangle((x0, y_end - 1, x1 - 1, y_end - 1 + LINE_W - 1), fill=LINE)
        y += row_h
        row += 1


def make_mlist_canvas(
    log_w: int, log_h: int, pot_w: int, pot_h: int, *, fmt: int
) -> Image.Image:
    w, h = (pot_w, pot_h) if fmt == 0xB else (log_w, log_h)
    # Opaque grey everywhere; stripes only in the left list column. Transparent
    # fill showed the vanilla checkerboard underlay on hardware.
    im = Image.new("RGBA", (w, h), NEUTRAL + (255,))
    draw_bplace_stripes(im, 0, 0, min(LIST_COL_W, log_w), log_h)
    return im


def make_neutral_canvas(w: int, h: int) -> Image.Image:
    return Image.new("RGBA", (w, h), NEUTRAL + (255,))


def make_flat_rgb565(w: int, h: int, rgb: tuple[int, int, int]) -> Image.Image:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :] = rgb
    return Image.fromarray(arr)


def _encode_same_size(im: Image.Image, raw: bytes, work_png: Path, work_bclim: Path) -> bytes:
    pix, w, h, fmt, _ = parse_bclim(raw)
    work_png.parent.mkdir(parents=True, exist_ok=True)
    im.save(work_png)
    work_bclim.write_bytes(raw)
    if fmt == 0xB:
        return png_to_bclim_etc1a4_same_size(work_png, work_bclim)
    if fmt == 8:
        return png_to_bclim_rgba4444_same_size(work_png, work_bclim)
    if fmt == 3:
        return png_to_bclim_rgb565_same_size(work_png, work_bclim)
    raise SystemExit(f"unsupported fmt {fmt:#x} for {work_bclim.name}")


def patch_profile_arc(arc_bytes: bytes, tmp: Path, *, tag: str) -> bytes:
    darc = DarcArchive(bytearray(arc_bytes))

    for path in ETC1_NEUTRAL:
        entry = darc.find(path)
        if entry is None:
            raise SystemExit(f"{tag} missing {path}")
        raw = darc.extract_file(entry)
        log_w, log_h, pot_w, pot_h = _pot_wh(raw)
        im = make_neutral_canvas(pot_w, pot_h)
        work_png = tmp / f"{tag}_{Path(path).stem}.png"
        work_bclim = tmp / f"{tag}_{Path(path).stem}.bclim"
        new = _encode_same_size(im, raw, work_png, work_bclim)
        if len(new) != len(raw):
            raise SystemExit(f"size change {path}: {len(raw)} -> {len(new)}")
        darc.replace_same_size(entry, new)
        print(f"  OK {Path(path).name} {log_w}x{log_h} (neutral overlay)", flush=True)

    for path in ETC1_MLIST:
        entry = darc.find(path)
        if entry is None:
            raise SystemExit(f"{tag} missing {path}")
        raw = darc.extract_file(entry)
        _pix, log_w, log_h, fmt, _ = parse_bclim(raw)
        if fmt == 0xB:
            _, _, pot_w, pot_h = _pot_wh(raw)
            im = make_mlist_canvas(log_w, log_h, pot_w, pot_h, fmt=fmt)
        else:
            im = make_mlist_canvas(log_w, log_h, log_w, log_h, fmt=fmt)
        work_png = tmp / f"{tag}_{Path(path).stem}.png"
        work_bclim = tmp / f"{tag}_{Path(path).stem}.bclim"
        new = _encode_same_size(im, raw, work_png, work_bclim)
        if len(new) != len(raw):
            raise SystemExit(f"size change {path}: {len(raw)} -> {len(new)}")
        darc.replace_same_size(entry, new)
        print(
            f"  OK {Path(path).name} {log_w}x{log_h} fmt={fmt} (stripes col={LIST_COL_W})",
            flush=True,
        )

    for path in RGB565_NEUTRAL:
        entry = darc.find(path)
        if entry is None:
            raise SystemExit(f"{tag} missing {path}")
        raw = darc.extract_file(entry)
        _pix, log_w, log_h, fmt, _ = parse_bclim(raw)
        if fmt == 8:
            im = Image.new("RGBA", (log_w, log_h), NEUTRAL + (255,))
        elif fmt == 3:
            im = make_flat_rgb565(log_w, log_h, NEUTRAL).convert("RGBA")
        else:
            raise SystemExit(f"{path} expected RGB565/RGBA4444, got {fmt:#x}")
        work_png = tmp / f"{tag}_{Path(path).stem}.png"
        work_bclim = tmp / f"{tag}_{Path(path).stem}.bclim"
        new = _encode_same_size(im, raw, work_png, work_bclim)
        if len(new) != len(raw):
            raise SystemExit(f"size change {path}: {len(raw)} -> {len(new)}")
        darc.replace_same_size(entry, new)
        print(f"  OK {Path(path).name} {log_w}x{log_h} fmt={fmt} (neutral cell)", flush=True)

    return bytes(darc.data)


def _write_arc_slot(pkg_blob: bytearray, entry_index: int, tuned: bytes, slot: bytes) -> None:
    entry_off = (entry_index + 1) * Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(pkg_blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp:
        raise SystemExit(f"entry {entry_index} not compressed")
    if slot_len != len(slot) or len(tuned) != dec_len:
        raise SystemExit(
            f"entry {entry_index} mismatch slot={slot_len}/{len(slot)} "
            f"dec={dec_len}/{len(tuned)}"
        )
    pkg_blob[cmp_off : cmp_off + slot_len] = slot


def _compress_arc(arc_bytes: bytes, cmp_len: int, tmp: Path, tag: str) -> tuple[bytes, bytes]:
    tuned = _force_zero_gaps(patch_profile_arc(arc_bytes, tmp, tag=tag))
    tuned2, slot = compress_exact_with_gap_tune(tuned, cmp_len)
    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned2 or do.unused_data or not do.eof:
        raise SystemExit(f"zlib verify failed for {tag}")
    print(f"  exact zlib {len(slot)}", flush=True)
    return tuned2, slot


def deploy_input_pkg(base: Path, pkg_dir: Path, tmp: Path) -> None:
    raw = base.read_bytes()
    img = ImgBin(str(base))
    img.parse(False)
    res = img.entries[PKG_INPUT]
    src_pkg = pkg_dir / f"{PKG_INPUT:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    blob = bytearray(src_pkg.read_bytes())
    wanted = {n.lower() for n in INPUT_ARCS}

    for i, elem in enumerate(pkg.entries):
        if not isinstance(elem, ARC) or elem.fn.lower() not in wanted:
            continue
        cmp_len = elem.fw.len()
        print(f"pkg {PKG_INPUT} {elem.fn} slot={cmp_len}", flush=True)
        tuned2, slot = _compress_arc(bytes(elem.parsed()), cmp_len, tmp, elem.fn)
        _write_arc_slot(blob, i, tuned2, slot)

    new_pkg = pkg_dir / f"new_{PKG_INPUT:04d}"
    new_pkg.write_bytes(blob)

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC) and a.fn.lower() in wanted:
            continue
        if a.parsed() != b.parsed():
            raise SystemExit(f"pkg {PKG_INPUT} non-target changed: {getattr(a, 'fn', a)}")
    print(f"pkg {PKG_INPUT} non-target entries OK", flush=True)


def deploy_profile_pkg(base: Path, pkg_dir: Path, tmp: Path) -> None:
    raw = base.read_bytes()
    img = ImgBin(str(base))
    img.parse(False)
    res = img.entries[PKG_PROFILE]
    src_pkg = pkg_dir / f"{PKG_PROFILE:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_idx = next(i for i, e in enumerate(pkg.entries) if isinstance(e, ARC))
    arc_elem = pkg.entries[arc_idx]
    if arc_elem.fn != PROFILE_ARC:
        raise SystemExit(f"expected {PROFILE_ARC}, got {arc_elem.fn}")

    cmp_len = arc_elem.fw.len()
    print(f"pkg {PKG_PROFILE} {PROFILE_ARC} slot={cmp_len}", flush=True)
    tuned2, slot = _compress_arc(bytes(arc_elem.parsed()), cmp_len, tmp, PROFILE_ARC)

    blob = bytearray(src_pkg.read_bytes())
    _write_arc_slot(blob, arc_idx, tuned2, slot)
    new_pkg = pkg_dir / f"new_{PKG_PROFILE:04d}"
    new_pkg.write_bytes(blob)

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC):
            continue
        if a.parsed() != b.parsed():
            raise SystemExit(f"pkg {PKG_PROFILE} non-ARC entry changed")
    print(f"pkg {PKG_PROFILE} non-ARC entries OK", flush=True)


def deploy_all(targets: list[Path]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    base = MOD_IMG
    if not base.is_file():
        raise SystemExit(f"missing deploy img: {base}")

    print(f"=== C3 from {base.name} (live; keeps keyboard EN) ===", flush=True)
    deploy_input_pkg(base, pkg_dir, tmp)
    deploy_profile_pkg(base, pkg_dir, tmp)

    for dest in targets:
        bak = dest.with_suffix(".bin.bak_pre_c3_list")
        if not bak.is_file():
            bak.write_bytes(dest.read_bytes())
            print("created", bak, flush=True)
        for pkg_id in (PKG_INPUT, PKG_PROFILE):
            try:
                splice_packages_into_img(dest, pkg_dir, [pkg_id], dest)
                print(f"spliced [{pkg_id}] -> {dest}", flush=True)
            except PackError as exc:
                raise SystemExit(f"splice {pkg_id} failed: {exc}") from exc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dest",
        type=Path,
        help="single img.bin to patch (e.g. extracted/romfs for .3ds rebuild)",
    )
    args = ap.parse_args()

    if args.dest:
        dest = args.dest.resolve()
        if not dest.is_file():
            raise SystemExit(f"--dest not found: {dest}")
        targets = [dest]
    else:
        targets = iter_deploy_targets(MOD_IMG)

    print("=== C3 list chrome (pkg 5190 + 5252) ===", flush=True)
    deploy_all(targets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
