#!/usr/bin/env python3
"""EN DataDelete menu — button labels + header.

Screen: Data Management → Delete Save Data
  pkg 4187 RGB565:
    DD_Data_Txt_Big01 — プレイデータ削除
    DD_Data_Txt_Big02 — ギャラリーデータ全削除
  pkg 5237 ETC1A4 MultiWin header (FUN_00255a18 idx 0x1a):
    Com_MultiWin_W01_Text05_01_00 — セーブデータ削除
"""
from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import (  # noqa: E402
    parse_bclim,
    png_to_bclim_etc1a4_same_size,
    png_to_bclim_rgb565_same_size,
)
from darcutil import DarcArchive  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    UI_FONT,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "datadelete_en"
FONT = UI_FONT

PKG_BUTTONS = 4187
PKG_HEADER = 5237

# Match vanilla chroma: green key + cyan glyph (+ yellow fringe in JP).
BG = (57, 161, 0)
INK = (57, 186, 238)
FRINGE = (255, 226, 0)

BUTTON_LABELS = [
    ("timg/DD_Data_Txt_Big01.bclim", "Delete Play Data"),
    # Shorter than "Delete All Gallery Data" — 152px strip + outline stays readable.
    ("timg/DD_Data_Txt_Big02.bclim", "Delete Gallery Data"),
]
HEADER_LABELS = [
    ("timg/Com_MultiWin_W01_Text05_01_00.bclim", "Delete Save Data"),
]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size=size)


def interfile_zero_gaps(data: bytes) -> list[tuple[int, int]]:
    darc = DarcArchive(data)
    spans = sorted((e.offset, e.offset + e.length) for e in darc.files)
    gaps: list[tuple[int, int]] = []
    for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
        if b0 > a1:
            gaps.append((a1, b0))
    if spans and spans[-1][1] < len(data):
        gaps.append((spans[-1][1], len(data)))
    out: list[tuple[int, int]] = []
    for g0, g1 in gaps:
        chunk = data[g0:g1]
        if len(chunk) >= 4 and chunk == b"\x00" * len(chunk):
            out.append((g1 - g0, g0))
    out.sort(reverse=True)
    return out


def apply_gap_pad(data: bytes, n_bytes: int, pad_rng: bytes) -> bytes:
    runs = interfile_zero_gaps(data)
    t = bytearray(data)
    left = n_bytes
    off = 0
    for sz, po in runs:
        take = min(left, sz)
        if take:
            t[po : po + take] = pad_rng[off : off + take]
        left -= take
        off += sz
        if left <= 0:
            break
    return bytes(t)


def compress_exact_empty_blocks(data: bytes, exact_len: int) -> bytes | None:
    adler = struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF)
    bodies: list[bytes] = []
    for level in range(10):
        co = zlib.compressobj(level, wbits=-15)
        bodies.append(co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH))
    hdrs = (b"\x78\x9c", b"\x78\xda", b"\x78\x5e", b"\x78\x01")
    for body in bodies:
        for hdr in hdrs:
            remain = exact_len - len(hdr) - 4 - len(body)
            if remain < 5 or remain % 5 != 0:
                continue
            n_empty = remain // 5
            extras = b"\x00\x00\x00\xff\xff" * (n_empty - 1)
            final = b"\x01\x00\x00\xff\xff"
            out = hdr + body + extras + final + adler
            if len(out) != exact_len:
                continue
            d = zlib.decompressobj()
            try:
                got = d.decompress(out)
            except zlib.error:
                continue
            if got == data and not d.unused_data and d.eof:
                return out
    return None


def compress_exact_with_gap_tune(data: bytes, exact_len: int) -> tuple[bytes, bytes]:
    runs = interfile_zero_gaps(data)
    cap = sum(sz for sz, _ in runs)
    pad_rng = os.urandom(max(1, cap))
    print(f"  gap capacity={cap}; tuning pad for exact zlib…", flush=True)
    step = max(1, cap // 400) if cap else 1
    for n in range(cap, -1, -step):
        cand = apply_gap_pad(data, n, pad_rng)
        slot = compress_exact_empty_blocks(cand, exact_len)
        if slot is not None:
            print(f"  hit at pad_bytes={n}", flush=True)
            return cand, slot
    for n in range(cap, -1, -1):
        cand = apply_gap_pad(data, n, pad_rng)
        slot = compress_exact_empty_blocks(cand, exact_len)
        if slot is not None:
            print(f"  hit at pad_bytes={n}", flush=True)
            return cand, slot
    raise SystemExit("could not build exact zlib stream with gap tune")


def render_button_label(w: int, h: int, text: str) -> Image.Image:
    """Solid cyan glyphs on green key — no yellow fringe / no AA greys.

    Vanilla uses cyan ink on green chroma; the UI remaps cyan → readable dark
    text. Soft AA + yellow fringe was remapping to pale outlined mush.
    """
    import numpy as np

    for size in range(min(13, h + 1), 7, -1):
        scale = 4
        mw, mh = w * scale, h * scale
        mask = Image.new("L", (mw, mh), 0)
        dr = ImageDraw.Draw(mask)
        f = font(size * scale)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > mw - 6:
            continue
        x = (mw - tw) // 2 - b[0]
        y = (mh - th) // 2 - b[1]
        dr.text((x, y), text, font=f, fill=255)
        m = np.array(mask)
        m = (m >= 140).astype(np.uint8) * 255
        # Slight dilate at hi-res for stroke weight, then nearest downscale.
        pad = np.pad(m, 1, mode="constant")
        dil = np.zeros_like(m)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                dil = np.maximum(
                    dil, pad[1 + dy : 1 + dy + mh, 1 + dx : 1 + dx + mw]
                )
        small = Image.fromarray(dil.astype(np.uint8), "L").resize(
            (w, h), Image.Resampling.NEAREST
        )
        g = np.array(small) >= 128
        out = np.empty((h, w, 3), dtype=np.uint8)
        out[:, :] = BG
        out[g] = INK
        return Image.fromarray(out, "RGB")
    raise RuntimeError(f"cannot fit {text!r} into {w}x{h}")


def render_header_label(w: int, h: int, text: str) -> Image.Image:
    """White alpha text for MultiWin ETC1A4 header strip."""
    for size in range(min(15, h + 2), 7, -1):
        scale = 2
        big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
        dr = ImageDraw.Draw(big)
        f = font(size * scale)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w * scale - 4:
            continue
        x = (w * scale - tw) // 2 - b[0]
        y = (h * scale - th) // 2 - b[1]
        dr.text((x, y), text, font=f, fill=(255, 255, 255, 255))
        return big.resize((w, h), Image.Resampling.BILINEAR)
    raise RuntimeError(f"cannot fit header {text!r} into {w}x{h}")


def patch_pkg(
    *,
    vanilla_raw: bytes,
    vimg: ImgBin,
    pkg_id: int,
    pkg_dir: Path,
    tmp: Path,
    labels: list[tuple[str, str]],
    kind: str,
) -> None:
    res = vimg.entries[pkg_id]
    if res is None:
        raise SystemExit(f"pkg {pkg_id} missing")
    src_pkg = pkg_dir / f"{pkg_id:04d}"
    src_pkg.write_bytes(
        vanilla_raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
    )

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc_elem.fw.len()
    print(
        f"\n=== PKG {pkg_id} ({kind}) dec={len(arc_elem.parsed())} slot={cmp_len} ===",
        flush=True,
    )

    darc = DarcArchive(bytearray(arc_elem.parsed()))
    for path, en in labels:
        entry = darc.find(path) or darc.find(Path(path).name)
        if entry is None:
            raise SystemExit(f"missing {path}")
        raw = darc.extract_file(entry)
        _pix, w, h, fmt, _ft = parse_bclim(raw)
        png = tmp / f"{pkg_id}_{Path(path).stem}.png"
        orig = tmp / f"{pkg_id}_{Path(path).stem}.bclim"
        orig.write_bytes(raw)
        if kind == "buttons":
            if fmt != 3:
                raise SystemExit(f"{path} fmt {fmt} not RGB565")
            candidates = [en]
            if path.endswith("Big02.bclim"):
                candidates += ["Delete Gallery Data", "Delete All Gallery"]
            rgb = None
            used = en
            last_err: Exception | None = None
            for cand in candidates:
                try:
                    rgb = render_button_label(w, h, cand)
                    used = cand
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
            if rgb is None:
                raise SystemExit(f"cannot render {path}: {last_err}")
            rgb.save(png)
            new = png_to_bclim_rgb565_same_size(png, orig)
            rgb.save(OUT / f"{Path(path).stem}_en.png")
            print(f"  OK {path} -> {used!r}", flush=True)
        else:
            if fmt != 0xB:
                raise SystemExit(f"{path} fmt {fmt:#x} not ETC1A4")
            rgba = render_header_label(w, h, en)
            rgba.save(png)
            new = png_to_bclim_etc1a4_same_size(png, orig)
            rgba.save(OUT / f"{Path(path).stem}_en.png")
            print(f"  OK {path} -> {en!r}", flush=True)
        darc.replace_same_size(entry, new)

    patched = bytes(darc.data)
    tuned, slot = compress_exact_with_gap_tune(patched, cmp_len)
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
    new_pkg = pkg_dir / f"new_{pkg_id:04d}"
    new_pkg.write_bytes(blob)

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC):
            if b.parsed() != tuned:
                raise SystemExit("ARC mismatch")
        elif a.parsed() != b.parsed():
            raise SystemExit(f"DMST changed {a.fn}")
    print("  DMST unchanged OK", flush=True)


def main() -> None:
    vanilla = VANILLA if VANILLA.is_file() else MOD_IMG
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

    bak = MOD_IMG.with_suffix(".bin.bak_pre_datadelete")
    if not bak.is_file():
        bak.write_bytes(MOD_IMG.read_bytes())
        print("created", bak, flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    vraw = vanilla.read_bytes()
    vimg = ImgBin(str(vanilla))
    vimg.parse(False)

    patch_pkg(
        vanilla_raw=vraw,
        vimg=vimg,
        pkg_id=PKG_BUTTONS,
        pkg_dir=pkg_dir,
        tmp=tmp,
        labels=BUTTON_LABELS,
        kind="buttons",
    )
    patch_pkg(
        vanilla_raw=vraw,
        vimg=vimg,
        pkg_id=PKG_HEADER,
        pkg_dir=pkg_dir,
        tmp=tmp,
        labels=HEADER_LABELS,
        kind="header",
    )

    pkgs = [PKG_BUTTONS, PKG_HEADER]
    try:
        for _dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(_dest, pkg_dir, pkgs, _dest)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("\ndeployed DataDelete EN pkgs", pkgs, "->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    print("Fully quit Azahar and re-open Delete Save Data.", flush=True)


if __name__ == "__main__":
    main()
