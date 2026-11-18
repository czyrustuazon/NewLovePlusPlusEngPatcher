#!/usr/bin/env python3
"""EN Photo Contest screens: raw TEX textures in img.bin pkgs **4090** / **4091**.

The Towanohigashi gallery's photo contest uses loose textures that no other
deploy touches:

  4090  Com_Btn_{Bck,GoHm,Nxt,Quit}_{Off,On}  128×32 RGBA4 (TEXI fmt 9)
        もどる / 帰る / 次へ / やめる -> Back / Leave / Next / Quit
  4091  Contest_Bg01-12                       256×256 RGB8 (TEXI fmt 11)
        写真コンテスト title and the とわのひがし地区 ギャラリー caption, one
        background per month -> PHOTO CONTEST / Towanohigashi Area Gallery

TEXI byte 62 is the game's own format code, not the PICA enum: 9 is 16 bpp
(RGBA4), 11 is 24 bpp (RGB8), 13 ETC1A4 (measured from TEX length / w·h).
Masters ``assets/images/photo_contest/<name>.png`` (``work/render_photo_contest.py``:
the Japanese is filled from its surroundings, the English drawn in the
original colours) are encoded and spliced into each texture's own vanilla
zlib slot, like ``deploy_shop_titles_en.py``. When one outgrows its slot but
the package's streams fit together (the 12 backgrounds fill one contiguous
range of pkg 4091), the group is recompressed back to back over that range
instead; the package length never changes.

  python tools/deploy_photo_contest_en.py
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import d2xy, encode_rgb8_pixels
from deploy_common import maybe_backup_img, resolve_img_paths
from deploy_minigame_textures_en import _deploy_targets, _vanilla_src, try_compress_to_slot
from img import FileWindow, Package
from img import Image as ImgBin

from pack_images import PackError, splice_packages_into_img

MOD_IMG, _FALLBACK_VANILLA = resolve_img_paths()
MASTERS = ROOT / "assets" / "images" / "photo_contest"
OUT = ROOT / "out" / "photo_contest_en"
JOBS = {
    4090: [f"Com_Btn_{b}_{s}" for b in ("Bck", "GoHm", "Nxt", "Quit") for s in ("Off", "On")],
    4091: [f"Contest_Bg{n:02d}" for n in range(1, 13)],
}


def encode_rgba4(img: Image.Image, w: int, h: int) -> bytes:
    """Tiled RGBA4 that keeps the colour of transparent texels, as the vanilla
    files do (``bclimutil.encode_rgba4444_pixels`` greys them, which costs the
    zlib slot a few dozen bytes)."""
    px = img.convert("RGBA").load()
    out = bytearray()
    for i in range(w * h):
        mx, my = d2xy(i % 64)
        tile = i // 64
        r, g, b, a = px[mx + (tile % (w // 8)) * 8, my + (tile // (w // 8)) * 8]
        out += struct.pack("<H", (r // 17) << 12 | (g // 17) << 8 | (b // 17) << 4 | a // 17)
    return bytes(out)


# TEXI fmt byte -> (encoder, bytes per pixel)
ENCODERS = {9: (encode_rgba4, 2), 11: (encode_rgb8_pixels, 3)}


def tex_slots(pkg_raw: bytes, pkg_path: Path) -> dict[str, tuple]:
    """``{name: (w, h, fmt, dec_len, is_cmp, cmp_len, cmp_off)}`` per TEX element.
    TEXI and TEX share each name, so entries are walked by position."""
    pkg = Package(FileWindow(str(pkg_path)), 0)
    pkg.parse(False)
    meta: dict[str, tuple[int, int, int]] = {}
    out: dict[str, tuple] = {}
    for i, elem in enumerate(pkg.entries):
        off = Package.ENTRY_SIZE * (i + 1)
        typ, dec_len, _do, _fl, is_cmp, cmp_len, cmp_off = Package.parse_entry(pkg_raw[off : off + Package.ENTRY_SIZE])
        name = elem.fn[: -len(".texi")]
        if typ == b"TEXI":
            texi = elem.read()
            meta[name] = (struct.unpack_from("<H", texi, 50)[0], struct.unpack_from("<H", texi, 54)[0], texi[62])
        elif typ == b"TEX " and name in meta:
            out[name] = (*meta[name], dec_len, is_cmp, cmp_len, cmp_off)
    return out


def encode_jobs(pkg: int, slots: dict[str, tuple], masters: Path) -> dict[str, bytes]:
    """Checked, encoded TEX payload for every job of ``pkg``."""
    out = {}
    for name in JOBS[pkg]:
        if name not in slots:
            raise SystemExit(f"pkg {pkg}: {name} missing")
        w, h, fmt, dec_len, is_cmp, _cmp_len, cmp_off = slots[name]
        if fmt not in ENCODERS or not is_cmp or dec_len != w * h * ENCODERS[fmt][1]:
            raise SystemExit(f"{name}: unexpected TEX (fmt={fmt}, cmp={is_cmp}, dec_len={dec_len}, {w}x{h})")
        if sum(s[6] == cmp_off for s in slots.values()) != 1:
            raise SystemExit(f"{name}: stream shared with another texture")
        im = Image.open(masters / f"{name}.png").convert("RGBA")
        if im.size != (w, h):
            raise SystemExit(f"{name}.png is {im.size}, expected {(w, h)}")
        out[name] = ENCODERS[fmt][0](im, w, h)
    return out


def relayout(pkg_raw: bytes, pkg_path: Path, data: dict[str, bytes]) -> bytes:
    """Recompress the ``data`` TEX streams back to back (16-aligned, original
    order) over the byte range they used to share, updating cmp_off/cmp_len.
    Only allowed when nothing else is stored in that range; the package length
    is unchanged. Used when a texture outgrows its own slot but the group fits."""
    import zopfli.zlib as zopfli_zlib

    pkg = Package(FileWindow(str(pkg_path)), 0)
    pkg.parse(False)
    rows = []  # (start, end, entry offset, name or None)
    for i, elem in enumerate(pkg.entries):
        off = Package.ENTRY_SIZE * (i + 1)
        typ, dec_len, dec_off, _fl, is_cmp, cmp_len, cmp_off = Package.parse_entry(pkg_raw[off : off + Package.ENTRY_SIZE])
        name = elem.fn[: -len(".texi")]
        start, length = (cmp_off, cmp_len) if is_cmp else (dec_off, dec_len)
        rows.append((start, start + length, off, name if typ == b"TEX " and name in data else None))
    jobs = sorted(r for r in rows if r[3])
    lo, hi = jobs[0][0], max(r[1] for r in jobs)
    others = [r for r in rows if not r[3] and r[0] < hi and r[1] > lo]
    if others:
        raise SystemExit(f"cannot relayout: other data inside {lo}-{hi}")
    streams = {r[3]: zlib.compress(data[r[3]], 9) for r in jobs}
    if sum(-(-len(v) // 16) * 16 for v in streams.values()) > hi - lo:
        streams = {k: min(v, zopfli_zlib.compress(data[k]), key=len) for k, v in streams.items()}
    blob = bytearray(pkg_raw)
    blob[lo:hi] = bytes(hi - lo)
    cur = lo
    for _start, _end, off, name in jobs:
        stream = streams[name]
        if cur + len(stream) > hi:
            raise SystemExit(f"textures do not fit their {hi - lo}-byte region together")
        blob[cur : cur + len(stream)] = stream
        struct.pack_into("<2I", blob, off + 24, len(stream), cur)
        print(f"OK {name} (relaid at {cur}, {len(stream)} bytes)", flush=True)
        cur = -(-(cur + len(stream)) // 16) * 16
    print(f"relayout: {cur - lo} of {hi - lo} bytes used", flush=True)
    return bytes(blob)


def patch_package(pkg: int, pkg_raw: bytes, pkg_path: Path, masters: Path | None = None) -> bytes:
    """Return ``pkg_raw`` with every job's texture replaced: each in its own
    vanilla slot when all fit, else the group re-laid over its shared range."""
    slots = tex_slots(pkg_raw, pkg_path)
    data = encode_jobs(pkg, slots, masters or MASTERS)
    fitted = {name: try_compress_to_slot(new, slots[name][5]) for name, new in data.items()}
    if any(slot is None for slot in fitted.values()):
        return relayout(pkg_raw, pkg_path, data)
    blob = bytearray(pkg_raw)
    for name, slot in fitted.items():
        cmp_len, cmp_off = slots[name][5:7]
        blob[cmp_off : cmp_off + cmp_len] = slot
        print(f"OK {name} (slot {cmp_len})", flush=True)
    return bytes(blob)


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    bak = maybe_backup_img(MOD_IMG, "photo_contest")
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    src_img = _vanilla_src()
    img = ImgBin(str(src_img))
    try:
        img.parse(False)
        for pkg in JOBS:
            res = img.entries[pkg]
            if res is None:
                raise SystemExit(f"pkg {pkg} missing")
            src = pkg_dir / f"vanilla_{pkg:04d}"
            src.write_bytes(res.fw.read())
            (pkg_dir / f"new_{pkg:04d}").write_bytes(patch_package(pkg, src.read_bytes(), src))
    finally:
        img.fh.close()

    try:
        for dest in _deploy_targets():
            splice_packages_into_img(dest, pkg_dir, list(JOBS), dest)
            print("spliced", list(JOBS), "->", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed photo contest EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
