#!/usr/bin/env python3
"""EN Mail sort popup — Sort Method + Timestamp/Sender/Lock + Cancel @ Mail 5207.

``Lyt_Popup_Sort`` INFORMATION dialog. BCLIM (not TRB / DrawText):

| Asset | Fmt | EN |
|-------|-----|----|
| ``Mail_PopTxt04`` | ETC1A4 88×20 | Sort Method |
| ``Mail_PopTxt05`` | ETC1A4 104×96 | Timestamp / Sender / Lock |
| ``C_Com_Win01_Btn02_Cancel_{Off,Press}`` | RGBA4444 98×42 | Cancel |

Self-rendered Heisei (no Zhoumaru). Live Mail.arc first so Inbox / New Mail
from ``deploy_mail_home_en.py`` stays. Bake after mail_home.

  python tools/deploy_mail_sort_en.py
"""
from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import (  # noqa: E402
    decode_bclim_to_image,
    parse_bclim,
    png_to_bclim_etc1a4_same_size,
    png_to_bclim_rgba4444_same_size,
)
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import _force_zero_gaps  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    UI_FONT,
    maybe_backup_img,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "mail_sort_en"
PKG = 5207
REF_FONTS = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025"
CHROME_FONTS: list[tuple[Path, int]] = [
    (REF_FONTS / "df-heiseigothic-w5.ttc", 1),
    (REF_FONTS / "df-heiseigothic-w7.ttc", 1),
    (UI_FONT, 0),
]
INK = (51, 51, 51)

# Vanilla PopTxt05 ink bands (y0,y1 inclusive) — keep EN centered in each.
POP05_LINES: list[tuple[str, int, int]] = [
    ("Timestamp", 16, 29),
    ("Sender", 42, 54),
    ("Lock", 67, 79),
]

ETC1_LABELS = [
    ("timg/Mail_PopTxt04.bclim", "title"),
    ("timg/Mail_PopTxt05.bclim", "options"),
]
CANCEL_PATHS = [
    "timg/C_Com_Win01_Btn02_Cancel_Off.bclim",
    "timg/C_Com_Win01_Btn02_Cancel_Press.bclim",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    last: Exception | None = None
    for path, idx in CHROME_FONTS:
        if not path.is_file():
            continue
        try:
            return ImageFont.truetype(str(path), size=size, index=idx)
        except OSError as exc:
            last = exc
            continue
    raise SystemExit(f"no chrome font loaded: {last}")


def render_gray_label(w: int, h: int, text: str) -> Image.Image:
    """Gray ink on clear — matches vanilla PopTxt alpha text."""
    for size in range(min(14, h), 7, -1):
        scale = 2
        big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
        dr = ImageDraw.Draw(big)
        f = font(size * scale)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w * scale - 4 or th > h * scale - 2:
            continue
        x = (w * scale - tw) // 2 - b[0]
        y = (h * scale - th) // 2 - b[1]
        dr.text((x, y), text, font=f, fill=INK + (255,))
        return big.resize((w, h), Image.Resampling.BILINEAR)
    raise RuntimeError(f"cannot fit {text!r} in {w}x{h}")


def render_pop05(w: int, h: int) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for text, y0, y1 in POP05_LINES:
        band_h = y1 - y0 + 1
        line = render_gray_label(w, band_h, text)
        im.paste(line, (0, y0), line)
    return im


def reletter_cancel(raw: bytes, text: str = "Cancel") -> Image.Image:
    """Keep Mail light-pill chrome; wipe JP glyph bbox then draw EN."""
    im = decode_bclim_to_image(raw).convert("RGBA")
    arr = np.array(im)
    rgb = arr[:, :, :3].astype(np.int16)
    a = arr[:, :, 3]
    lum = rgb.mean(axis=2)
    # Dark glyph + AA fringe on light button (vanilla キャンセル).
    ink = (lum < 200) & (a > 180)
    if not ink.any():
        raise RuntimeError("Cancel glyph mask empty")
    ys, xs = np.where(ink)
    # Pad the glyph box so outline fringe is wiped with chrome fill.
    y0 = max(0, int(ys.min()) - 2)
    y1 = min(arr.shape[0], int(ys.max()) + 3)
    x0 = max(0, int(xs.min()) - 2)
    x1 = min(arr.shape[1], int(xs.max()) + 3)
    border = np.ones(arr.shape[:2], dtype=bool)
    border[2:-2, 2:-2] = False
    chrome = (a > 180) & ~ink & ~border
    if chrome.any():
        fill_rgb = tuple(int(x) for x in arr[:, :, :3][chrome].mean(axis=0))
    else:
        fill_rgb = (236, 236, 236)
    arr[y0:y1, x0:x1, 0] = fill_rgb[0]
    arr[y0:y1, x0:x1, 1] = fill_rgb[1]
    arr[y0:y1, x0:x1, 2] = fill_rgb[2]
    arr[y0:y1, x0:x1, 3] = 255
    cleared = Image.fromarray(arr, "RGBA")
    dr = ImageDraw.Draw(cleared)
    w, h = cleared.size
    for size in range(14, 8, -1):
        f = font(size)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w - 16:
            continue
        x = (w - tw) // 2 - b[0]
        y = (h - th) // 2 - b[1] - 1
        dr.text((x, y), text, font=f, fill=INK + (255,))
        return cleared
    raise RuntimeError(f"cannot fit Cancel {text!r}")


def _extract_pkg(img_path: Path, pkg_dir: Path) -> tuple[Path, Package, ARC]:
    raw = img_path.read_bytes()
    img = ImgBin(str(img_path))
    img.parse(False)
    res = img.entries[PKG]
    src_pkg = pkg_dir / f"{PKG:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])
    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    return src_pkg, pkg, arc


def _patch_arc(arc_bytes: bytes, tmp: Path) -> bytes:
    darc = DarcArchive(bytearray(arc_bytes))
    for path, kind in ETC1_LABELS:
        entry = darc.find(path) or darc.find(Path(path).name)
        if entry is None:
            raise SystemExit(f"missing {path}")
        raw = darc.extract_file(entry)
        _pix, w, h, fmt, _ft = parse_bclim(raw)
        if fmt != 0xB:
            raise SystemExit(f"{path} fmt {fmt} not ETC1A4")
        if kind == "title":
            rgba = render_gray_label(w, h, "Sort Method")
            label = "Sort Method"
        else:
            rgba = render_pop05(w, h)
            label = "Timestamp/Sender/Lock"
        png = tmp / "t.png"
        orig = tmp / "o.bclim"
        rgba.save(png)
        rgba.save(OUT / f"{Path(path).stem}_en.png")
        orig.write_bytes(raw)
        darc.replace_same_size(entry, png_to_bclim_etc1a4_same_size(png, orig))
        print(f"OK {path} -> {label!r}", flush=True)

    for path in CANCEL_PATHS:
        entry = darc.find(path) or darc.find(Path(path).name)
        if entry is None:
            raise SystemExit(f"missing {path}")
        raw = darc.extract_file(entry)
        _pix, w, h, fmt, _ft = parse_bclim(raw)
        if fmt != 8:
            raise SystemExit(f"{path} fmt {fmt} not RGBA4444")
        rgba = reletter_cancel(raw, "Cancel")
        png = tmp / "t.png"
        orig = tmp / "o.bclim"
        rgba.save(png)
        rgba.save(OUT / f"{Path(path).stem}_en.png")
        orig.write_bytes(raw)
        darc.replace_same_size(entry, png_to_bclim_rgba4444_same_size(png, orig))
        print(f"OK {path} -> 'Cancel'", flush=True)

    return bytes(darc.data)


def interfile_zero_gaps(data: bytes, min_len: int = 4) -> list[tuple[int, int]]:
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
        if len(chunk) >= min_len and chunk == b"\x00" * len(chunk):
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
    """Same empty-block playbook as ``deploy_mail_home_en`` (no zopfli)."""
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


def _fit_slot(cand: bytes, cmp_len: int) -> tuple[bytes, bytes] | None:
    """Zero gaps, then empty-block / light pad — Mail 5207 bake path."""
    cand = _force_zero_gaps(cand)
    slot = compress_exact_empty_blocks(cand, cmp_len)
    if slot is not None:
        print("  hit empty-block after zeroing gaps", flush=True)
        return cand, slot
    runs = interfile_zero_gaps(cand)
    cap = sum(sz for sz, _ in runs)
    pad_rng = os.urandom(cap) if cap else b""
    print(f"  gap capacity={cap}; tuning…", flush=True)
    step = max(1, cap // 400) if cap else 1
    for n in list(range(cap, -1, -step)) + list(range(cap, -1, -1)):
        trial = apply_gap_pad(cand, n, pad_rng) if cap else cand
        slot = compress_exact_empty_blocks(trial, cmp_len)
        if slot is not None:
            print(f"  hit pad_bytes={n}", flush=True)
            return trial, slot
    return None


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    bak = maybe_backup_img(MOD_IMG, "mail_sort")

    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    bases: list[tuple[str, Path]] = [("live", MOD_IMG)]
    if VANILLA.is_file() and VANILLA.resolve() != MOD_IMG.resolve():
        bases.append(("vanilla", VANILLA))

    last_err: Exception | None = None
    for base_name, base_path in bases:
        src_pkg, pkg, arc = _extract_pkg(base_path, pkg_dir)
        cmp_len = arc.fw.len()
        print(
            f"Mail.arc base={base_name} dec={len(arc.parsed())} slot={cmp_len}",
            flush=True,
        )
        patched = _patch_arc(arc.parsed(), tmp)
        fitted = _fit_slot(patched, cmp_len)
        if fitted is None:
            last_err = SystemExit(f"{base_name}: could not fit exact zlib")
            print(f"  {base_name} zlib miss", flush=True)
            continue
        tuned, slot = fitted
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
            for _dest in iter_deploy_targets(MOD_IMG):
                splice_packages_into_img(_dest, pkg_dir, [PKG], _dest)
        except PackError as exc:
            raise SystemExit(f"splice failed: {exc}") from exc

        print("deployed Mail sort popup EN ->", MOD_IMG, flush=True)
        print("Rollback:", bak, flush=True)
        return

    raise SystemExit(f"Mail sort EN could not fit slot: {last_err}")


if __name__ == "__main__":
    main()
