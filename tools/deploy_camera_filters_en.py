#!/usr/bin/env python3
"""EN camera buttons and filter names (pkgs 5322-5326).

pack_images leaves these Japanese: the masters re-encode the whole plate, so
each ARC zlibs past its fixed slot (Camera_Btn02_c 19114 > 16803). Here every
pixel the English lettering does not change is snapped back to the vanilla
texel, so ETC1A4 keeps the shipped 8x8 tiles and only the text costs bytes.
The filter-name strips (5324 / 5325) still overflow that way; their text
blocks are written with one shared ETC1 header and fewer alpha levels.
"""
from __future__ import annotations

import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import (  # noqa: E402
    _decode_tiled,
    decode_bclim_to_image,
    etc1_scramble,
    parse_bclim,
    png_to_bclim_same_size,
)
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import _force_zero_gaps, compress_to_exact_slot  # noqa: E402
from image_map import IMAGE_MAP  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, prefer_asset_folders, splice_packages_into_img  # noqa: E402

from deploy_common import iter_deploy_targets, maybe_backup_img, resolve_img_paths  # noqa: E402

MOD_IMG, VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "camera_filters_en"
PKGS = (5322, 5323, 5324, 5325, 5326)

# Faithful to coarse. "pixels": re-encode the text pixels (diff threshold,
# alpha levels, colour levels). "blocks": shared-header ETC1A4 text blocks
# (diff threshold, alpha levels).
STEPS = [
    ("pixels", (24, 16, 256)),
    ("blocks", (24, 16)),
    ("blocks", (24, 8)),
    ("blocks", (24, 6)),
    ("blocks", (24, 4)),
]


def decode(raw: bytes) -> Image.Image:
    pix, w, h, fmt, _ = parse_bclim(raw)
    if fmt == 3:  # the game samples fmt 3 as LA8
        return _decode_tiled(pix, w, h, 2, lambda b, i: (b[2 * i + 1],) * 3 + (b[2 * i],))
    im = decode_bclim_to_image(raw)
    if im is None:
        raise SystemExit(f"cannot decode fmt {fmt}")
    return im.convert("RGBA")


def text_only(master: Image.Image, van: Image.Image, thresh: int, a_lv: int, c_lv: int) -> Image.Image:
    m = np.asarray(master.convert("RGBA"), dtype=np.int16)
    v = np.asarray(van.convert("RGBA"), dtype=np.int16)
    vis = np.maximum(m[..., 3], v[..., 3])[..., None] / 255.0
    d = np.maximum(np.abs(m[..., 3] - v[..., 3]), (np.abs(m[..., :3] - v[..., :3]) * vis).max(-1))
    changed = ndi.binary_dilation(d > thresh, iterations=1)
    out = v.copy()
    t = m[changed].astype(np.float32)
    a_step = 255 / (a_lv - 1)
    c_step = 255 / (c_lv - 1)
    t[:, 3] = np.round(t[:, 3] / a_step) * a_step
    t[:, :3] = np.round(t[:, :3] / c_step) * c_step
    t[t[:, 3] == 0, :3] = 0
    out[changed] = np.clip(t, 0, 255).astype(np.int16)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


_MOD = np.array([(2, 8), (5, 17), (9, 29), (13, 42), (18, 60), (24, 80), (33, 106), (47, 183)])


def _levels(base5: np.ndarray, cw: int) -> np.ndarray:
    """The 4 colours one ETC1 diff-mode subblock can show, in selector order."""
    c = (base5 << 3) | (base5 >> 2)
    a, b = _MOD[cw]
    return np.clip(c[None, :] + np.array([a, b, -a, -b])[:, None], 0, 255)


def _fit_header(px: np.ndarray) -> tuple[np.ndarray, int]:
    """One (5-bit base, table) for every text block, anchored on the plate colour."""
    cols, counts = np.unique(px.reshape(-1, 3), axis=0, return_counts=True)
    plate = cols[np.argmax(counts)].astype(np.int32)
    best = (None, 0, np.inf)
    for cw in range(8):
        for mod in (_MOD[cw][0], _MOD[cw][1], -_MOD[cw][0], -_MOD[cw][1]):
            b0 = np.clip(np.round((plate - mod) / 8.225).astype(int), 0, 31)
            for d in np.ndindex(3, 3, 3):
                base = np.clip(b0 + np.array(d) - 1, 0, 31)
                lv = _levels(base, cw)
                err = ((cols[:, None, :] - lv[None]) ** 2).sum(-1).min(1)
                e = float((err * counts).sum())
                if e < best[2]:
                    best = (base, cw, e)
    return best[0], best[1]


def encode_text_blocks(
    raw: bytes, master: Image.Image, van: Image.Image, thresh: int, a_levels: int = 16
) -> bytes:
    """Rewrite only the 4x4 ETC1A4 blocks the lettering touches; keep the rest.

    Every rewritten block shares one header, so zlib sees the same bytes again
    and again and pays mostly for the selector bits.
    """
    pix, w, h, fmt, _ = parse_bclim(raw)
    if fmt != 0xB:
        raise ValueError(f"fmt {fmt} is not ETC1A4")
    bx_n, by_n = w // 4, h // 4
    if len(pix) != bx_n * by_n * 16:
        raise ValueError("padded ETC1A4 canvas")
    m = np.asarray(master.convert("RGBA"), dtype=np.int32)
    v = np.asarray(van.convert("RGBA"), dtype=np.int32)
    vis = np.maximum(m[..., 3], v[..., 3])[..., None] / 255.0
    d = np.maximum(np.abs(m[..., 3] - v[..., 3]), (np.abs(m[..., :3] - v[..., :3]) * vis).max(-1))
    changed = d > thresh
    blocks = changed.reshape(by_n, 4, bx_n, 4).any(axis=(1, 3))
    if not blocks.any():
        return raw
    sel = np.repeat(np.repeat(blocks, 4, 0), 4, 1)
    seen = sel & (m[..., 3] >= 9)  # nibble 0 hides the colour
    base, cw = _fit_header(m[..., :3][seen] if seen.any() else m[..., :3][sel])
    lv = _levels(base, cw)
    # Hidden texels take the plate's selector so blocks of pure alpha text
    # share one colour word.
    pts = m[..., :3][seen] if seen.any() else m[..., :3][sel]
    cols, counts = np.unique(pts.reshape(-1, 3), axis=0, return_counts=True)
    hidden_code = int(((lv - cols[np.argmax(counts)]) ** 2).sum(1).argmin())
    head = (int(base[0]) << 59) | (int(base[1]) << 51) | (int(base[2]) << 43) | (cw << 37) | (cw << 34) | (1 << 33)
    order = etc1_scramble(w, h)
    out = bytearray(pix)
    for by, bx in zip(*np.nonzero(blocks)):
        tile = m[by * 4 : by * 4 + 4, bx * 4 : bx * 4 + 4]
        word = head
        alpha = bytearray(8)
        for i in range(16):
            x, y = i >> 2, i & 3
            r, g, b, a = tile[y, x]
            if a < 9:
                code = hidden_code
            else:
                code = int(((lv - np.array([r, g, b])) ** 2).sum(1).argmin())
            word |= ((code >> 1) << (16 + i)) | ((code & 1) << i)
            step = 15 / (a_levels - 1)
            nib = int(round(round(a / 17 / step) * step))
            alpha[i >> 1] |= (nib & 0xF) << ((i & 1) * 4)
        off = order[by * bx_n + bx] * 16
        out[off : off + 8] = alpha
        out[off + 8 : off + 16] = word.to_bytes(8, "little")
    if not raw.startswith(pix):
        raise ValueError("BCLIM pixels are not at offset 0")
    return bytes(out) + raw[len(pix) :]


def patch_arc_blocks(
    arc: bytes, masters: Path, thresh: int, a_levels: int, tmp: Path
) -> tuple[bytes, int]:
    darc = DarcArchive(bytearray(arc))
    n = 0
    for png in sorted(masters.rglob("*.png")):
        entry = darc.find(f"timg/{png.stem}.bclim")
        if entry is None:
            continue
        raw = darc.extract_file(entry)
        van = decode(raw)
        with Image.open(png) as im:
            master = im.convert("RGBA")
        if master.size != van.size:
            continue
        if parse_bclim(raw)[3] == 0xB:
            new = encode_text_blocks(raw, master, van, thresh, a_levels)
        else:
            src = tmp / f"{png.stem}.png"
            orig = tmp / f"{png.stem}.bclim"
            text_only(master, van, thresh, a_levels, 256).save(src)
            orig.write_bytes(raw)
            new = png_to_bclim_same_size(src, orig)
        darc.replace_same_size(entry, new)
        n += 1
    return _force_zero_gaps(bytes(darc.data)), n


def patch_arc(arc: bytes, masters: Path, step: tuple[int, int, int], tmp: Path) -> tuple[bytes, int]:
    darc = DarcArchive(bytearray(arc))
    n = 0
    for png in sorted(masters.rglob("*.png")):
        entry = darc.find(f"timg/{png.stem}.bclim")
        if entry is None:
            continue
        raw = darc.extract_file(entry)
        van = decode(raw)
        with Image.open(png) as im:
            master = im.convert("RGBA")
        if master.size != van.size:
            print(f"  skip {png.stem}: {master.size} != {van.size}", flush=True)
            continue
        src = tmp / f"{png.stem}.png"
        orig = tmp / f"{png.stem}.bclim"
        text_only(master, van, *step).save(src)
        orig.write_bytes(raw)
        darc.replace_same_size(entry, png_to_bclim_same_size(src, orig))
        n += 1
    return _force_zero_gaps(bytes(darc.data)), n


def build_pkg(pkg_id: int, chosen: dict[str, Path], pkg_dir: Path, tmp: Path) -> bool:
    raw = VANILLA.read_bytes()
    img = ImgBin(str(VANILLA))
    img.parse(False)
    res = img.entries[pkg_id]
    blob = bytearray(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])
    src = pkg_dir / f"{pkg_id:04d}"
    src.write_bytes(blob)
    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    by_arc = {arc.lower(): chosen.get(key) for key, (p, arc) in IMAGE_MAP.items() if p == pkg_id}
    touched = False
    for elem in pkg.entries:
        if not isinstance(elem, ARC) or not elem.is_cmp:
            continue
        masters = by_arc.get(Path(str(elem.fn)).name.lower())
        if masters is None:
            continue
        slot_len = elem.fw.len()
        vanilla_arc = elem.read()
        for kind, step in STEPS:
            if kind == "pixels":
                cand, n = patch_arc(vanilla_arc, masters, step, tmp)
            else:
                cand, n = patch_arc_blocks(vanilla_arc, masters, *step, tmp)
            try:
                slot = compress_to_exact_slot(cand, slot_len)
            except RuntimeError as exc:
                print(f"  {elem.fn} {kind} {step}: {exc}", flush=True)
                continue
            got = zlib.decompressobj().decompress(slot)
            if len(got) != len(vanilla_arc):
                raise SystemExit(f"{elem.fn}: ARC length changed")
            off = elem.fw.base_offset
            blob[off : off + slot_len] = slot
            print(f"OK {pkg_id} {elem.fn}: {n} masters, {kind} {step}", flush=True)
            touched = True
            break
        else:
            print(f"[warn] {pkg_id} {elem.fn}: no step fits slot {slot_len}; left Japanese", flush=True)
    if touched:
        (pkg_dir / f"new_{pkg_id:04d}").write_bytes(blob)
        check = Package(FileWindow(str(pkg_dir / f"new_{pkg_id:04d}")), 0)
        check.parse(False)
        for a, b in zip(pkg.entries, check.entries):
            if not isinstance(a, ARC) and a.parsed() != b.parsed():
                raise SystemExit(f"{pkg_id}: non-ARC entry changed")
    return touched


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    bak = maybe_backup_img(MOD_IMG, "camera_filters")
    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    chosen = prefer_asset_folders(ROOT / "assets" / "images")
    done = []
    with tempfile.TemporaryDirectory() as td:
        for pkg_id in PKGS:
            if build_pkg(pkg_id, chosen, pkg_dir, Path(td)):
                done.append(pkg_id)
    if not done:
        print("[warn] no camera package fit; nothing spliced", flush=True)
        return
    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, done, dest)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print(f"deployed camera EN pkgs {done} ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)


if __name__ == "__main__":
    main()
