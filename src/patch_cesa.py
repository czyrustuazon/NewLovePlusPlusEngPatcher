#!/usr/bin/env python3
"""Patch the boot CESA anti-piracy texture in img.bin package 90.

Same-offset splice only: never rewrites the whole img.bin (Image.write
relocates packages and can black-screen boot). Never touches code.bin.

The companion blurb grows PACK header dec_len; the game mallocs the *idx
table* size for pkg 90, so that field must be updated to match or boot
heap-smashes (see rebuild_pkg90_with_companion).
"""

from __future__ import annotations

import argparse
import mmap
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
NLPP_TOOLS = ROOT / "tools" / "nlpp-tools"
DEFAULT_ASSET = ROOT / "assets" / "images" / "cesa" / "CESA_240X400.png"
DEFAULT_IMG = Path(
    r"C:\Users\Zepse\Documents\New Love Plus Decompilation\New Love Plus Plus\extracted\romfs\img.bin"
)
CESA_PKG_INDEX = 90
CESA_TEX_NAME = "CESA_240X400.texi"
# Constructor IDs are 1-based TEXI indices (FUN_00598ff4: low16-1).
# CesaLogo +0x60 = 0x5A0002 → CESA_240X400; +0x64 = 0x5A0008 → logo_white.
# NintendoLogo also binds 0x5A0008 (white flash). Not CESA_400X240 /
# ProductionLogo_320X240 / Bottom_Thank — those left the right pane white.
CESA_COMPANION_TEX_NAME = "logo_white.texi"
BOTTOM_THANK_TEX_NAME = "Bottom_Thank.texi"
CESA_ALT_ORIENT_TEX_NAME = "CESA_400X240.texi"
PROD_LANDSCAPE_STUB_TEX_NAME = "ProductionLogo_320X240.texi"
TEX_W, TEX_H = 256, 512
VISIBLE_W, VISIBLE_H = 240, 400
COMPANION_TEX_W, COMPANION_TEX_H = 256, 512
COMPANION_VISIBLE_W, COMPANION_VISIBLE_H = 240, 320
VANILLA_PKG90_DEC_LEN = 1182976
STUB_TEX_DEC_LEN = 768
ENTRY_SIZE = 0x20
PACK_ALIGN = 0x10
# img.bin index table (see nlpp-tools Image.parse_idx_entry).
IMG_IDX_TABLE_ADDR = 0x800
IMG_IDX_ENTRY_SIZE = 0x14
# Stock padding outside the visible region is black, not white.
PAD_RGB = (0, 0, 0)


def img_idx_entry_off(pkg_index: int) -> int:
    return IMG_IDX_TABLE_ADDR + pkg_index * IMG_IDX_ENTRY_SIZE


def read_img_idx_dec_len(img: bytes | bytearray | mmap.mmap, pkg_index: int) -> int:
    """Decompressed size the game allocates for a PAK (idx table, not PACK header)."""
    off = img_idx_entry_off(pkg_index)
    typ, dec_len, _dec_data, _unk, _kind = struct.unpack_from("=4s4x2I2xBB", img, off)
    if typ != b"PAK ":
        raise RuntimeError(f"img idx {pkg_index} is {typ!r}, not PAK")
    return dec_len


def set_img_idx_dec_len(
    img: bytearray | mmap.mmap, pkg_index: int, dec_len: int
) -> int:
    """Write idx-table dec_len. Returns the previous value."""
    off = img_idx_entry_off(pkg_index)
    typ, old, dec_data, unk, kind = struct.unpack_from("=4s4x2I2xBB", img, off)
    if typ != b"PAK ":
        raise RuntimeError(f"img idx {pkg_index} is {typ!r}, not PAK")
    struct.pack_into("=4s4x2I2xBB", img, off, typ, dec_len, dec_data, unk, kind)
    return old


def sync_img_pkg90_idx_to_pack(img_path: Path) -> bool:
    """Set idx-table pkg90 dec_len from the inner PACK header. True if changed.

    Fast crash fix when the companion TEX is already in the PACK but idx was left
    at vanilla 1182976.
    """
    _ensure_nlpp_path()
    from img import Image as ImgBin
    from img import Package

    img_path = Path(img_path).resolve()
    im = ImgBin(str(img_path))
    im.parse(False)
    res = im.entries[CESA_PKG_INDEX]
    if res is None:
        im.fh.close()
        raise RuntimeError(f"img.bin missing package {CESA_PKG_INDEX}")
    pack_dec_len = Package.parse_header(res.fw.read()[:ENTRY_SIZE])[5]
    im.fh.close()
    with img_path.open("r+b") as fh:
        mm = mmap.mmap(fh.fileno(), 0)
        try:
            old = read_img_idx_dec_len(mm, CESA_PKG_INDEX)
            if old == pack_dec_len:
                return False
            set_img_idx_dec_len(mm, CESA_PKG_INDEX, pack_dec_len)
            mm.flush()
            print(
                f"[cesa] img idx pkg90 dec_len {old} -> {pack_dec_len} ({img_path})",
                flush=True,
            )
            return True
        finally:
            mm.close()


def _ensure_nlpp_path() -> None:
    tools = str(NLPP_TOOLS)
    if tools not in sys.path:
        sys.path.insert(0, tools)


def morton(n: int) -> tuple[int, int]:
    x = y = 0
    for b in range(8):
        x |= (n >> (2 * b) & 1) << b
        y |= (n >> (2 * b + 1) & 1) << b
    return x, y


def encode_tex(
    im: Image.Image,
    width: int,
    height: int,
    visible_w: int,
    visible_h: int,
    pad_rgb: tuple[int, int, int] = PAD_RGB,
) -> bytes:
    """RGB image → NLPP TEX bytes (BGR8 + 8x8 Morton). Padding is black like stock."""
    canvas = Image.new("RGB", (width, height), pad_rgb)
    rgb = im.convert("RGB")
    if rgb.size != (visible_w, visible_h):
        rgb = rgb.resize((visible_w, visible_h), Image.Resampling.NEAREST)
    canvas.paste(rgb, (0, 0))
    px = canvas.load()
    out = bytearray(width * height * 3)
    i = 0
    tile = 8
    for ty in range(0, height, tile):
        for tx in range(0, width, tile):
            for n in range(tile * tile):
                x, y = morton(n)
                r, g, b = px[tx + x, ty + y]
                out[i] = b
                out[i + 1] = g
                out[i + 2] = r
                i += 3
    return bytes(out)


def encode_cesa_tex(im: Image.Image, width: int = TEX_W, height: int = TEX_H) -> bytes:
    """Portrait CESA_240X400 TEX (256×512 canvas, 240×400 visible)."""
    return encode_tex(im, width, height, VISIBLE_W, VISIBLE_H)


def encode_cesa_companion_tex(im: Image.Image) -> bytes:
    """logo_white TEX: 240×320 portrait (256×512 canvas), same column as CESA.

    CesaLogo +0x64 is constructor ID 0x5A0008 = logo_white (vanilla 16×16
    white stub). Pad white so Morton tiles past the 240×320 crop stay poster-white.
    """
    return encode_tex(
        im,
        COMPANION_TEX_W,
        COMPANION_TEX_H,
        COMPANION_VISIBLE_W,
        COMPANION_VISIBLE_H,
        pad_rgb=(255, 255, 255),
    )


def decode_cesa_tex(
    raw: bytes,
    width: int = TEX_W,
    height: int = TEX_H,
    ow: int = VISIBLE_W,
    oh: int = VISIBLE_H,
) -> Image.Image:
    img = Image.new("RGB", (width, height))
    px = img.load()
    i = 0
    tile = 8
    for ty in range(0, height, tile):
        for tx in range(0, width, tile):
            for n in range(tile * tile):
                x, y = morton(n)
                o = i * 3
                px[tx + x, ty + y] = (raw[o + 2], raw[o + 1], raw[o])
                i += 1
    return img.crop((0, 0, ow, oh))


def _find_cesa_tex_entry(pkg_raw: bytes) -> tuple[int, int, int, int]:
    """Return (entry_table_off, cmp_off, cmp_len, dec_len) for CESA TEX."""
    _ensure_nlpp_path()
    from img import FileWindow, Package

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pkg") as tmp:
        tmp.write(pkg_raw)
        tmp_path = Path(tmp.name)
    try:
        pkg = Package(FileWindow(str(tmp_path)), 0)
        pkg.parse(False)
        for i, elem in enumerate(pkg.entries):
            if elem.fn == CESA_TEX_NAME and elem.typ == b"TEX ":
                entry_off = ENTRY_SIZE + i * ENTRY_SIZE
                _typ, dec_len, _dec_off, _flags, is_cmp, cmp_len, cmp_off = (
                    Package.parse_entry(pkg_raw[entry_off : entry_off + ENTRY_SIZE])
                )
                if not is_cmp:
                    raise RuntimeError("CESA TEX is not compressed")
                return entry_off, cmp_off, cmp_len, dec_len
    finally:
        tmp_path.unlink(missing_ok=True)
    raise RuntimeError(f"{CESA_TEX_NAME} TEX entry not found")


def read_cesa_tex_from_pkg(pkg_raw: bytes) -> bytes:
    """Decompress the stock CESA TEX payload from a PACK blob."""
    _entry_off, cmp_off, cmp_len, dec_len = _find_cesa_tex_entry(pkg_raw)
    tex = zlib.decompress(pkg_raw[cmp_off : cmp_off + cmp_len])
    if len(tex) != dec_len:
        raise RuntimeError(f"unexpected decompressed size {len(tex)} != {dec_len}")
    return tex


def _stored_final_block(payload: bytes) -> bytes:
    """Final deflate stored block carrying ``payload`` (len <= 65535)."""
    n = len(payload)
    if n > 0xFFFF:
        raise ValueError("stored block too large")
    return bytes(
        [
            0x01,
            n & 0xFF,
            (n >> 8) & 0xFF,
            (~n) & 0xFF,
            ((~n) >> 8) & 0xFF,
        ]
    ) + payload


def _try_zlib_exact_candidate(out: bytes, data: bytes) -> bool:
    try:
        d = zlib.decompressobj()
        got = d.decompress(out)
    except zlib.error:
        return False
    return got == data and d.unused_data == b"" and bool(d.eof)


def compress_zlib_exact(data: bytes, exact_len: int) -> bytes:
    """Build a zlib stream of exactly ``exact_len`` bytes with no trailing unused input.

    Trailing NUL padding after a short zlib stream leaves ``unused_data``; the
    game's inflater appears to hang/reject that (CESA white boot, Options freeze).
    Pad *inside* the deflate stream with stored blocks instead.
    """
    adler = struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF)
    for level in range(10):
        cand = zlib.compress(data, level)
        if len(cand) != exact_len:
            continue
        if _try_zlib_exact_candidate(cand, data):
            return cand

    bodies: list[bytes] = []
    for level in range(10):
        co = zlib.compressobj(level, wbits=-15)
        bodies.append(co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH))
    try:
        import zopfli.zlib as zopfli_zlib  # type: ignore

        # Raw deflate body via stripping zlib wrapper from zopfli output.
        z = zopfli_zlib.compress(data)
        if len(z) >= 6:
            bodies.insert(0, z[2:-4])
    except Exception:
        pass

    hdrs = (b"\x78\x9c", b"\x78\xda", b"\x78\x5e", b"\x78\x01")
    for body in bodies:
        for hdr in hdrs:
            budget = exact_len - len(hdr) - 4
            remain = budget - len(body)
            if remain < 5:
                continue
            # Prefer a single final stored block with arbitrary payload length.
            payload_len = remain - 5
            if 0 <= payload_len <= 0xFFFF:
                out = hdr + body + _stored_final_block(b"\x00" * payload_len) + adler
                if len(out) == exact_len and _try_zlib_exact_candidate(out, data):
                    return out
            # Fallback: empty sync markers + empty final (remain multiple of 5).
            if remain % 5 == 0:
                n_empty = remain // 5
                extras = b"\x00\x00\x00\xff\xff" * (n_empty - 1)
                final = b"\x01\x00\x00\xff\xff"
                out = hdr + body + extras + final + adler
                if len(out) == exact_len and _try_zlib_exact_candidate(out, data):
                    return out

    raise RuntimeError(f"cannot build exact zlib stream of length {exact_len}")


def compress_tex_to_slot(tex: bytes, slot_len: int) -> bytes:
    """zlib-compress TEX into a fixed-size slot; keep cmp_len unchanged."""
    slot = compress_zlib_exact(tex, slot_len)
    d = zlib.decompressobj()
    check = d.decompress(slot)
    if check != tex or d.unused_data != b"":
        raise RuntimeError("round-trip decompress mismatch / leftover input")
    return slot


def patch_cesa_package_inplace_tex(pkg_raw: bytes, tex: bytes) -> bytes:
    """Replace CESA compressed TEX inside original PACK; keep size/layout/cmp_len."""
    _entry_off, cmp_off, old_cmp_len, dec_len = _find_cesa_tex_entry(pkg_raw)
    if len(tex) != dec_len:
        raise RuntimeError(f"TEX size {len(tex)} != dec_len {dec_len}")
    out = bytearray(pkg_raw)
    out[cmp_off : cmp_off + old_cmp_len] = compress_tex_to_slot(tex, old_cmp_len)
    return bytes(out)


def patch_cesa_package_inplace(pkg_raw: bytes, png: Path) -> bytes:
    """Replace CESA TEX from a 240x400 PNG."""
    return patch_cesa_package_inplace_tex(pkg_raw, encode_cesa_tex(Image.open(png)))


def _align_pack(n: int) -> int:
    return (n + PACK_ALIGN - 1) & ~(PACK_ALIGN - 1)


def compress_tex_best(tex: bytes) -> bytes:
    """Smallest valid zlib stream (no trailing unused_data). Prefers zopfli."""
    cands = [zlib.compress(tex, level) for level in range(1, 10)]
    try:
        import zopfli.zlib as zopfli_zlib  # type: ignore

        cands.append(zopfli_zlib.compress(tex))
    except Exception:
        pass
    best = min(cands, key=len)
    if not _try_zlib_exact_candidate(best, tex):
        raise RuntimeError("compressed TEX failed unused_data==0 round-trip")
    return best


def _patch_texi_dims(blob: bytes, w: int, h: int, ow: int, oh: int) -> bytes:
    """Patch SERI integer fields w/h/ow/oh in an 82-byte TEXI blob."""
    idx = blob.find(b"\x69" * 8)
    if idx < 0 or idx + 8 + 32 > len(blob):
        raise RuntimeError("TEXI type table not found")
    data = idx + 8
    out = bytearray(blob)
    struct.pack_into("<I", out, data + 0, w)
    struct.pack_into("<I", out, data + 4, h)
    struct.pack_into("<I", out, data + 24, ow)
    struct.pack_into("<I", out, data + 28, oh)
    return bytes(out)


def _iter_pack_entries(pkg_raw: bytes):
    _ensure_nlpp_path()
    from img import Package

    _typ, cnt, _ptr, _str, _dec_data, _dec_len, _cmp_len, _pad = Package.parse_header(
        pkg_raw[:ENTRY_SIZE]
    )
    for i in range(cnt):
        entry_off = ENTRY_SIZE + i * ENTRY_SIZE
        parsed = Package.parse_entry(pkg_raw[entry_off : entry_off + ENTRY_SIZE])
        yield i, entry_off, parsed


def _pkg_names(pkg_raw: bytes) -> list[str]:
    _ensure_nlpp_path()
    from img import FileWindow, Package

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pkg") as tmp:
        tmp.write(pkg_raw)
        tmp_path = Path(tmp.name)
    try:
        pkg = Package(FileWindow(str(tmp_path)), 0)
        pkg.parse(False)
        return [elem.fn for elem in pkg.entries]
    finally:
        tmp_path.unlink(missing_ok=True)


def rebuild_pkg90_with_companion(
    pkg_raw: bytes,
    cesa_tex: bytes,
    companion_tex: bytes,
) -> bytes:
    """Rebuild pkg 90 inside the original 29232-byte slot with a real logo_white.

    First-boot dual pane is CESA_240X400 (0x5A0002) + logo_white (0x5A0008).
    Vanilla logo_white is a 16×16 stub, so the right pane is white. Growing
    the 15-byte zlib in place is impossible; instead stop padding CESA to 13667,
    zopfli Konami/ProductionLogo losslessly, and give logo_white its own
    256×512 / 240×320 TEX. Other stubs stay 16×16. Package file length stays
    exactly ``len(pkg_raw)``. Prefer vanilla pkg bytes as input.

    The PACK header ``dec_len`` grows by the companion TEX (393216). The caller
    **must** also update img.bin's idx-table dec_len for pkg 90 — the game
    mallocs that idx size, not the inner PACK header. Leaving idx at vanilla
    1182976 writes the companion one byte past the arena and heap-smashes boot
    (Luma data abort in malloc @ 0x0010DE4C, FAR=3). Prefer a vanilla pkg 90
    as ``pkg_raw`` so a previous wrong-slot grow is undone.
    """
    _ensure_nlpp_path()
    from img import Package

    if len(cesa_tex) != TEX_W * TEX_H * 3:
        raise RuntimeError(f"CESA TEX size {len(cesa_tex)}")
    if len(companion_tex) != COMPANION_TEX_W * COMPANION_TEX_H * 3:
        raise RuntimeError(f"companion TEX size {len(companion_tex)}")

    names = _pkg_names(pkg_raw)
    header = Package.parse_header(pkg_raw[:ENTRY_SIZE])
    _typ, cnt, ptr_off, str_table_off, dec_data_off, dec_len, cmp_len, pad_len = header
    if cmp_len != len(pkg_raw):
        raise RuntimeError(f"PACK cmp_len {cmp_len} != file {len(pkg_raw)}")

    # Unique compressed payloads keyed by (cmp_off, cmp_len).
    payloads: dict[tuple[int, int], bytes] = {}
    entries = []
    for i, entry_off, parsed in _iter_pack_entries(pkg_raw):
        typ, e_dec_len, e_dec_off, flags, is_cmp, e_cmp_len, e_cmp_off = parsed
        fn = names[i]
        entries.append(
            {
                "i": i,
                "off": entry_off,
                "typ": typ,
                "fn": fn,
                "dec_len": e_dec_len,
                "dec_off": e_dec_off,
                "flags": flags,
                "is_cmp": is_cmp,
                "cmp_len": e_cmp_len,
                "cmp_off": e_cmp_off,
            }
        )
        if typ == b"TEX " and is_cmp:
            key = (e_cmp_off, e_cmp_len)
            if key not in payloads:
                payloads[key] = pkg_raw[e_cmp_off : e_cmp_off + e_cmp_len]

    # Identify the shared 16×16 stub (smallest unique TEX).
    stub_key = min(payloads, key=lambda k: k[1])
    stub_cmp = payloads[stub_key]
    stub_dec = zlib.decompress(stub_cmp)

    named_tex = {e["fn"]: e for e in entries if e["typ"] == b"TEX "}
    if CESA_TEX_NAME not in named_tex or CESA_COMPANION_TEX_NAME not in named_tex:
        raise RuntimeError("pkg 90 missing CESA TEX entries")

    konami_e = next(e for e in entries if e["typ"] == b"TEX " and e["fn"].startswith("KONAMI_CI_240X400"))
    prod_e = next(
        e for e in entries if e["typ"] == b"TEX " and e["fn"].startswith("ProductionLogo_240X320")
    )
    konami_dec = zlib.decompress(
        pkg_raw[konami_e["cmp_off"] : konami_e["cmp_off"] + konami_e["cmp_len"]]
    )
    prod_dec = zlib.decompress(
        pkg_raw[prod_e["cmp_off"] : prod_e["cmp_off"] + prod_e["cmp_len"]]
    )

    cesa_cmp = compress_tex_best(cesa_tex)
    companion_cmp = compress_tex_best(companion_tex)
    konami_cmp = compress_tex_best(konami_dec)
    prod_cmp = compress_tex_best(prod_dec)

    tex_blobs = [
        ("stub", stub_cmp, len(stub_dec)),
        ("cesa", cesa_cmp, len(cesa_tex)),
        ("konami", konami_cmp, len(konami_dec)),
        ("prod", prod_cmp, len(prod_dec)),
        ("companion", companion_cmp, len(companion_tex)),
    ]

    tex_start = min(e["cmp_off"] for e in entries if e["typ"] == b"TEX " and e["is_cmp"])
    cursor = tex_start
    placed: dict[str, tuple[int, int, int]] = {}
    for label, blob, dec in tex_blobs:
        placed[label] = (cursor, len(blob), dec)
        cursor = _align_pack(cursor + len(blob))
    if cursor > len(pkg_raw):
        raise RuntimeError(
            f"pkg 90 overflow: TEX end {cursor} > slot {len(pkg_raw)} "
            f"(cesa {len(cesa_cmp)} companion {len(companion_cmp)} "
            f"konami {len(konami_cmp)} prod {len(prod_cmp)})"
        )

    print(
        f"[cesa] pkg90 TEX zlib: cesa={len(cesa_cmp)} companion={len(companion_cmp)} "
        f"konami={len(konami_cmp)} prod={len(prod_cmp)} end={cursor}/{len(pkg_raw)}",
        flush=True,
    )

    out = bytearray(pkg_raw)
    # Wipe old TEX payload region then write the new unique blobs.
    out[tex_start:] = b"\x00" * (len(pkg_raw) - tex_start)
    for label, blob, _dec in tex_blobs:
        off = placed[label][0]
        out[off : off + len(blob)] = blob

    def _write_tex_entry(entry: dict, slot: str, dec_off: int) -> None:
        cmp_off, cmp_len, dec_len_n = placed[slot]
        packed = struct.pack(
            "=4s4x6I",
            entry["typ"],
            dec_len_n,
            dec_off,
            entry["flags"],
            1,
            cmp_len,
            cmp_off,
        )
        out[entry["off"] : entry["off"] + ENTRY_SIZE] = packed

    companion_e = named_tex[CESA_COMPANION_TEX_NAME]
    if companion_e["dec_len"] == len(companion_tex):
        companion_dec_off = companion_e["dec_off"]
        new_dec_len = dec_len
    else:
        if dec_len != VANILLA_PKG90_DEC_LEN:
            raise RuntimeError(
                "pkg 90 PACK dec_len already grown but companion is still a stub; "
                "rebuild from vanilla pkg 90"
            )
        companion_dec_off = dec_len
        new_dec_len = dec_len + len(companion_tex)

    _write_tex_entry(named_tex[CESA_TEX_NAME], "cesa", named_tex[CESA_TEX_NAME]["dec_off"])
    _write_tex_entry(konami_e, "konami", konami_e["dec_off"])
    _write_tex_entry(prod_e, "prod", prod_e["dec_off"])
    _write_tex_entry(companion_e, "companion", companion_dec_off)

    stub_dec_off = next(
        e["dec_off"]
        for e in entries
        if e["typ"] == b"TEX " and e["dec_len"] == STUB_TEX_DEC_LEN
    )
    for e in entries:
        if e["typ"] != b"TEX " or e["fn"] in {
            CESA_TEX_NAME,
            CESA_COMPANION_TEX_NAME,
            konami_e["fn"],
            prod_e["fn"],
        }:
            continue
        _write_tex_entry(e, "stub", stub_dec_off)

    # Patch companion TEXI visible/canvas size (still 82 bytes).
    texi = next(e for e in entries if e["typ"] == b"TEXI" and e["fn"] == CESA_COMPANION_TEX_NAME)
    texi_blob = bytes(out[texi["dec_off"] : texi["dec_off"] + texi["dec_len"]])
    out[texi["dec_off"] : texi["dec_off"] + texi["dec_len"]] = _patch_texi_dims(
        texi_blob,
        COMPANION_TEX_W,
        COMPANION_TEX_H,
        COMPANION_VISIBLE_W,
        COMPANION_VISIBLE_H,
    )
    # Other dual-screen candidates stay 16×16 stubs (wrong-slot leftovers).
    for stub_name in (
        BOTTOM_THANK_TEX_NAME,
        CESA_ALT_ORIENT_TEX_NAME,
        PROD_LANDSCAPE_STUB_TEX_NAME,
    ):
        if stub_name == CESA_COMPANION_TEX_NAME:
            continue
        stub_texi = next(
            (e for e in entries if e["typ"] == b"TEXI" and e["fn"] == stub_name),
            None,
        )
        if stub_texi is None:
            continue
        stub_blob = bytes(
            out[stub_texi["dec_off"] : stub_texi["dec_off"] + stub_texi["dec_len"]]
        )
        out[stub_texi["dec_off"] : stub_texi["dec_off"] + stub_texi["dec_len"]] = (
            _patch_texi_dims(stub_blob, 16, 16, 16, 16)
        )

    out[0:ENTRY_SIZE] = struct.pack(
        "=6sH6I",
        _typ,
        cnt,
        ptr_off,
        str_table_off,
        dec_data_off,
        new_dec_len,
        len(pkg_raw),
        pad_len,
    )
    if len(out) != len(pkg_raw):
        raise RuntimeError("rebuild changed package file length")
    patched = bytes(out)
    for stub_name in (
        BOTTOM_THANK_TEX_NAME,
        CESA_ALT_ORIENT_TEX_NAME,
        PROD_LANDSCAPE_STUB_TEX_NAME,
    ):
        if stub_name == CESA_COMPANION_TEX_NAME:
            continue
        stub = read_named_tex_from_pkg(patched, stub_name)
        if len(stub) != STUB_TEX_DEC_LEN:
            raise RuntimeError(f"{stub_name} must stay a 16×16 stub, got {len(stub)}")
    return patched


def read_named_tex_from_pkg(pkg_raw: bytes, name: str) -> bytes:
    names = _pkg_names(pkg_raw)
    for i, _entry_off, parsed in _iter_pack_entries(pkg_raw):
        typ, dec_len, _dec_off, _flags, is_cmp, cmp_len, cmp_off = parsed
        if names[i] != name or typ != b"TEX ":
            continue
        if not is_cmp:
            raise RuntimeError(f"{name} TEX is not compressed")
        tex = zlib.decompress(pkg_raw[cmp_off : cmp_off + cmp_len])
        if len(tex) != dec_len:
            raise RuntimeError(f"{name} decompressed {len(tex)} != {dec_len}")
        return tex
    raise RuntimeError(f"{name} TEX not found")


def patch_cesa_package_with_companion(
    pkg_raw: bytes,
    cesa_png: Path,
    companion_png: Path,
) -> bytes:
    return rebuild_pkg90_with_companion(
        pkg_raw,
        encode_cesa_tex(Image.open(cesa_png)),
        encode_cesa_companion_tex(Image.open(companion_png)),
    )


def patch_img_bin_tex(
    src_img: Path,
    tex: bytes,
    dst_img: Path,
    work: Path | None = None,
) -> Path:
    """Splice package 90 with a new decompressed TEX blob."""
    _ensure_nlpp_path()
    from img import Image as ImgBin

    src_img = Path(src_img).resolve()
    dst_img = Path(dst_img).resolve()
    if work is None:
        work = dst_img.parent / "cesa_img_work"
    work.mkdir(parents=True, exist_ok=True)

    im = ImgBin(str(src_img))
    im.parse(False)
    res = im.entries[CESA_PKG_INDEX]
    if res is None:
        raise RuntimeError(f"img.bin missing package {CESA_PKG_INDEX}")

    base = res.fw.base_offset
    pkg_len = res.fw.len()
    pkg_raw = res.fw.read()
    if len(pkg_raw) != pkg_len:
        raise RuntimeError("package read length mismatch")

    patched_pkg = patch_cesa_package_inplace_tex(pkg_raw, tex)
    if len(patched_pkg) != pkg_len:
        raise RuntimeError(
            f"in-place patch changed package size {pkg_len} -> {len(patched_pkg)}"
        )

    (work / f"{CESA_PKG_INDEX:04d}.bin").write_bytes(pkg_raw)
    (work / f"{CESA_PKG_INDEX:04d}_patched.bin").write_bytes(patched_pkg)

    if dst_img.resolve() != src_img.resolve():
        shutil.copy2(src_img, dst_img)
    data = bytearray(dst_img.read_bytes())
    data[base : base + pkg_len] = patched_pkg
    dst_img.write_bytes(data)

    im2 = ImgBin(str(dst_img))
    im2.parse(False)
    for i, (a, b) in enumerate(zip(im.entries, im2.entries)):
        if a is None and b is None:
            continue
        da = a.fw.read() if a else None
        db = b.fw.read() if b else None
        if i == CESA_PKG_INDEX:
            if da == db:
                raise RuntimeError("package 90 did not change")
            # Verify TEX round-trips to the intended bytes.
            got = read_cesa_tex_from_pkg(db)
            if got != tex:
                raise RuntimeError("patched package TEX mismatch after splice")
            continue
        if da != db:
            raise RuntimeError(f"unexpected diff at package {i}")

    return dst_img


def patch_img_bin_with_companion(
    src_img: Path,
    cesa_png: Path,
    companion_png: Path,
    dst_img: Path,
    work: Path | None = None,
    vanilla_img: Path | None = None,
) -> Path:
    """Splice rebuilt pkg 90 (CESA + logo_white blurb) at the same img.bin offset.

    ``vanilla_img`` supplies a clean pkg 90 so a previous wrong-slot grow is
    reverted. Dest is only the splice target (and idx-table update). Never
    copies that vanilla img over ``dst_img`` (would wipe later EN packages).
    """
    _ensure_nlpp_path()
    from img import Image as ImgBin

    src_img = Path(src_img).resolve()
    dst_img = Path(dst_img).resolve()
    extract_from = Path(vanilla_img).resolve() if vanilla_img is not None else src_img
    if work is None:
        work = dst_img.parent / "cesa_img_work"
    work.mkdir(parents=True, exist_ok=True)

    cesa_tex = encode_cesa_tex(Image.open(cesa_png))
    companion_tex = encode_cesa_companion_tex(Image.open(companion_png))

    def _load_pkg90_meta(path: Path) -> tuple[int, int, bytes]:
        im = ImgBin(str(path))
        im.parse(False)
        try:
            res = im.entries[CESA_PKG_INDEX]
            if res is None:
                raise RuntimeError(f"img.bin missing package {CESA_PKG_INDEX}")
            base = res.fw.base_offset
            pkg_len = res.fw.len()
            pkg_raw = res.fw.read()
            if len(pkg_raw) != pkg_len:
                raise RuntimeError("package read length mismatch")
            return base, pkg_len, pkg_raw
        finally:
            im.fh.close()

    _ebase, _elen, pkg_raw = _load_pkg90_meta(extract_from)
    dest_base, dest_len, _dest_pkg = _load_pkg90_meta(dst_img)
    if dest_len != len(pkg_raw):
        raise RuntimeError(
            f"pkg 90 length {len(pkg_raw)} from {extract_from} != dest slot {dest_len}"
        )

    patched_pkg = rebuild_pkg90_with_companion(pkg_raw, cesa_tex, companion_tex)
    if len(patched_pkg) != dest_len:
        raise RuntimeError(
            f"rebuild changed package size {dest_len} -> {len(patched_pkg)}"
        )

    (work / f"{CESA_PKG_INDEX:04d}.bin").write_bytes(pkg_raw)
    (work / f"{CESA_PKG_INDEX:04d}_patched.bin").write_bytes(patched_pkg)

    from img import Package

    pack_dec_len = Package.parse_header(patched_pkg[:ENTRY_SIZE])[5]
    base = dest_base
    pkg_len = dest_len

    # Never copy extract/vanilla over dest — splice pkg 90 + idx only.
    with dst_img.open("r+b") as fh:
        mm = mmap.mmap(fh.fileno(), 0)
        try:
            mm[base : base + pkg_len] = patched_pkg
            old_idx = set_img_idx_dec_len(mm, CESA_PKG_INDEX, pack_dec_len)
            mm.flush()
        finally:
            mm.close()
    if old_idx != pack_dec_len:
        print(
            f"[cesa] img idx pkg90 dec_len {old_idx} -> {pack_dec_len} "
            "(boot arena; must match PACK header)",
            flush=True,
        )
    with dst_img.open("rb") as fh:
        mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            if read_img_idx_dec_len(mm, CESA_PKG_INDEX) != pack_dec_len:
                raise RuntimeError("img idx pkg90 dec_len did not stick")
            if mm[base : base + pkg_len] != patched_pkg:
                raise RuntimeError("package 90 splice did not stick")
        finally:
            mm.close()

    got = read_named_tex_from_pkg(patched_pkg, CESA_TEX_NAME)
    if got != cesa_tex:
        raise RuntimeError("patched CESA TEX mismatch after splice")
    got_c = read_named_tex_from_pkg(patched_pkg, CESA_COMPANION_TEX_NAME)
    if got_c != companion_tex:
        raise RuntimeError("patched companion TEX mismatch after splice")

    return dst_img


def patch_img_bin(
    src_img: Path,
    png: Path,
    dst_img: Path,
    work: Path | None = None,
) -> Path:
    """Splice patched package 90 into a copy of img.bin (byte-identical elsewhere)."""
    return patch_img_bin_tex(src_img, encode_cesa_tex(Image.open(png)), dst_img, work)


def _load_pkg90(src_img: Path) -> bytes:
    _ensure_nlpp_path()
    from img import Image as ImgBin

    im = ImgBin(str(src_img))
    im.parse(False)
    res = im.entries[CESA_PKG_INDEX]
    if res is None:
        raise RuntimeError(f"img.bin missing package {CESA_PKG_INDEX}")
    pkg = res.fw.read()
    im.fh.close()
    return pkg


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch CESA boot warning texture in img.bin")
    ap.add_argument("--img", type=Path, default=DEFAULT_IMG, help="Source img.bin")
    ap.add_argument("--png", type=Path, default=DEFAULT_ASSET, help="English 240x400 PNG")
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output img.bin (default: out/cesa_patch/img.bin)",
    )
    ap.add_argument("--work", type=Path, default=None, help="Scratch directory")
    ap.add_argument(
        "--inplace",
        action="store_true",
        help="Patch --img in place (makes a .bak first)",
    )
    ap.add_argument(
        "--decode",
        action="store_true",
        help="Decode current CESA texture from --img to --png",
    )
    ap.add_argument(
        "--recompress-only",
        action="store_true",
        help="Test 1: recompress original TEX bytes with no pixel changes",
    )
    ap.add_argument(
        "--roundtrip-jp",
        action="store_true",
        help="Test 2: decode JP then re-encode (black padding) and splice",
    )
    ap.add_argument(
        "--deploy-azahar",
        action="store_true",
        help="Copy --out to Azahar LayeredFS romfs/img.bin",
    )
    args = ap.parse_args()

    if args.decode:
        pkg_raw = _load_pkg90(args.img)
        tex = read_cesa_tex_from_pkg(pkg_raw)
        out_png = args.png
        out_png.parent.mkdir(parents=True, exist_ok=True)
        decode_cesa_tex(tex).save(out_png)
        print(f"[cesa] decoded -> {out_png}")
        return 0

    if args.inplace:
        bak = args.img.with_suffix(args.img.suffix + ".bak")
        if not bak.is_file():
            shutil.copy2(args.img, bak)
            print(f"[cesa] backup -> {bak}")
        out = args.img
    else:
        out = args.out or (ROOT / "out" / "cesa_patch" / "img.bin")

    work = args.work or (Path(out).parent / "work")
    pkg_raw = _load_pkg90(args.img)
    stock_tex = read_cesa_tex_from_pkg(pkg_raw)

    if args.recompress_only:
        print(f"[cesa] Test1 recompress-only {args.img} -> {out}")
        patch_img_bin_tex(args.img, stock_tex, out, work=work)
        mode = "recompress-only"
    elif args.roundtrip_jp:
        print(f"[cesa] Test2 roundtrip-jp {args.img} -> {out}")
        jp = decode_cesa_tex(stock_tex)
        rt = encode_cesa_tex(jp)
        if rt != stock_tex:
            # Visible region must match; report padding-only diffs if any.
            vis_diff = sum(
                1
                for a, b in zip(
                    encode_cesa_tex(jp),  # already have rt
                    stock_tex,
                )
                if a != b
            )
            print(f"[cesa] warn: roundtrip byte diffs vs stock: {vis_diff}")
        patch_img_bin_tex(args.img, rt, out, work=work)
        # Save preview
        preview = Path(work) / "roundtrip_jp.png"
        preview.parent.mkdir(parents=True, exist_ok=True)
        jp.save(preview)
        mode = "roundtrip-jp"
    else:
        if not args.png.is_file():
            print(f"[-] missing PNG: {args.png}", file=sys.stderr)
            return 1
        print(f"[cesa] {args.img} + {args.png} -> {out}")
        patch_img_bin(args.img, args.png, out, work=work)
        mode = "png"

    print(f"[cesa] wrote {out} ({out.stat().st_size:,} bytes) [{mode}]")

    if args.deploy_azahar:
        az = Path(
            r"C:\Users\Zepse\AppData\Roaming\Azahar\load\mods\00040000000F4E00\romfs\img.bin"
        )
        az.parent.mkdir(parents=True, exist_ok=True)
        # Never deploy a code.bin overlay from this tool.
        shutil.copy2(out, az)
        print(f"[cesa] deployed -> {az}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
