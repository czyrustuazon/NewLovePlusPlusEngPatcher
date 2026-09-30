#!/usr/bin/env python3
"""EN for Card.arc friend-list sort header (受信日時) — exact-zopfli pkg 4152."""
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

from bclimutil import parse_bclim, png_to_bclim_rgb565_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    UI_FONT,
    maybe_backup_img,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "card_flist_en"
PKG = 4152
REF_FONTS = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025"
# Heisei Gothic P-face (index 1) matches vanilla chrome; MPLUS is OFL fallback.
CHROME_FONTS: list[tuple[Path, int]] = [
    (REF_FONTS / "df-heiseigothic-w5.ttc", 1),
    (REF_FONTS / "df-heiseigothic-w7.ttc", 1),
    (REF_FONTS / "df-heiseigothic-w9.ttc", 1),
    (UI_FONT, 0),
]
# Yellow is chroma-keyed on this grey window. Profile/DataDelete: the UI
# remaps *cyan* ink → dark readable text. Vanilla purple and CESA-black both
# remapped to a pale ghost here.
BG = (255, 226, 0)
INK = (49, 157, 255)  # same cyan family as Profile Call / DataDelete
# 受信日時 — "Received" alone was too vague and chroma-smeared to yellow.
LABELS = [
    ("timg/Flist_Txt03.bclim", "Received Date"),
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


def all_interfile_gaps(data: bytes) -> list[tuple[int, int]]:
    darc = DarcArchive(data)
    spans = sorted((e.offset, e.offset + e.length) for e in darc.files)
    gaps: list[tuple[int, int]] = []
    for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
        if b0 > a1:
            gaps.append((a1, b0))
    if spans and spans[-1][1] < len(data):
        gaps.append((spans[-1][1], len(data)))
    return gaps


def zero_interfile_gaps(data: bytes) -> bytes:
    """Clear prior urandom gap-salt so zlib can fit the slot again."""
    t = bytearray(data)
    for g0, g1 in all_interfile_gaps(data):
        t[g0:g1] = b"\x00" * (g1 - g0)
    return bytes(t)


def interfile_zero_gaps(data: bytes) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for g0, g1 in all_interfile_gaps(data):
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
    """Exact-length zlib via empty stored sync/final blocks (remain % 5 == 0)."""
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
    """Zero leftover gap-salt, then empty-block / light pad (no per-byte loop)."""
    data = zero_interfile_gaps(data)
    slot = compress_exact_empty_blocks(data, exact_len)
    if slot is not None:
        print("  hit empty-block after zeroing gaps", flush=True)
        return data, slot
    runs = interfile_zero_gaps(data)
    cap = sum(sz for sz, _ in runs)
    pad_rng = os.urandom(max(1, cap))
    print(f"  gap capacity={cap}; tuning pad for exact zlib…", flush=True)
    step = max(8, cap // 200) if cap else 1
    for n in range(0, cap + 1, step):
        cand = apply_gap_pad(data, n, pad_rng)
        slot = compress_exact_empty_blocks(cand, exact_len)
        if slot is not None:
            print(f"  hit at pad_bytes={n}", flush=True)
            return cand, slot
    raise SystemExit("could not build exact zlib stream with gap tune")


def _hard_cyan(mask: np.ndarray) -> Image.Image:
    """Binary cyan on yellow. Any mix toward yellow keys out on this pane."""
    out = np.empty((*mask.shape, 3), dtype=np.uint8)
    out[:, :] = BG
    out[mask] = INK
    return Image.fromarray(out, "RGB")


def render_flist_label(w: int, h: int, text: str) -> Image.Image:
    """Heisei W5 hard cyan — ~200 ink px. Zhoumaru/W9 fills were ~600 (vanilla ~144).

    Soft ramps ghost on this chroma key; extra fill remaps to a black slab.
    """
    for size in range(11, 7, -1):
        scale = 4
        mw, mh = w * scale, h * scale
        mask = Image.new("L", (mw, mh), 0)
        dr = ImageDraw.Draw(mask)
        f = font(size * scale)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > mw - 8 or th > mh - 4:
            continue
        x = (mw - tw) // 2 - b[0]
        y = (mh - th) // 2 - b[1]
        dr.text((x, y), text, font=f, fill=255)
        cov = (
            np.array(mask.resize((w, h), Image.Resampling.LANCZOS), dtype=np.float32)
            / 255.0
        )
        return _hard_cyan(cov >= 0.45)
    raise RuntimeError(f"cannot fit {text!r}")


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

    bak = maybe_backup_img(MOD_IMG, "card_flist")

    # Live package first so other Card.arc EN (Txt01/02, names) is kept.
    bases: list[tuple[str, Path]] = [("live", MOD_IMG)]
    if VANILLA.is_file() and VANILLA.resolve() != MOD_IMG.resolve():
        bases.append(("vanilla", VANILLA))

    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    last_err: Exception | None = None
    for base_name, base_path in bases:
        vraw = base_path.read_bytes()
        vimg = ImgBin(str(base_path))
        vimg.parse(False)
        res = vimg.entries[PKG]
        src_pkg = pkg_dir / f"{PKG:04d}"
        src_pkg.write_bytes(vraw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

        pkg = Package(FileWindow(str(src_pkg)), 0)
        pkg.parse(False)
        arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
        cmp_len = arc_elem.fw.len()
        print(f"Card.arc base={base_name} dec={len(arc_elem.parsed())} slot={cmp_len}", flush=True)

        darc = DarcArchive(bytearray(arc_elem.parsed()))
        for path, en in LABELS:
            entry = darc.find(path) or darc.find(Path(path).name)
            if entry is None:
                raise SystemExit(f"missing {path}")
            raw = darc.extract_file(entry)
            _pix, w, h, fmt, _ft = parse_bclim(raw)
            if fmt != 3:
                raise SystemExit(f"{path} fmt {fmt} not RGB565")
            rgb = render_flist_label(w, h, en)
            png = tmp / "t.png"
            orig = tmp / "o.bclim"
            rgb.save(png)
            orig.write_bytes(raw)
            new = png_to_bclim_rgb565_same_size(png, orig)
            darc.replace_same_size(entry, new)
            rgb.save(OUT / f"{Path(path).stem}_en.png")
            print(f"OK {path} -> {en!r} font=HeiseiGothic", flush=True)

        patched = bytes(darc.data)
        try:
            tuned, slot = compress_exact_with_gap_tune(patched, cmp_len)
        except SystemExit as exc:
            last_err = exc
            print(f"  {base_name} zlib miss: {exc}", flush=True)
            continue
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

        print("deployed Card Flist EN ->", MOD_IMG, flush=True)
        print("Rollback:", bak, flush=True)
        return

    raise SystemExit(f"Flist Received Date could not fit slot: {last_err}")


if __name__ == "__main__":
    main()
