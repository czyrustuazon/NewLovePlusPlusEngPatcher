#!/usr/bin/env python3
"""EN Title.arc pkg 5261 — hub labels + independent Eng Patch container.

Runtime copyright chrome is ``Pts_Copyright`` bound under ``Pos_Copyright_*``
(``MenuTitleCopyright.dmst``), not the ``Lyt_Copyright`` pic1 panes. Eng Patch
must be wired in the Parts layout.

Separate ``timg/Eng_Patch.bclim`` + pic under ``Nul_Copyright``, taller Nul so
the Eng strip is not clipped. Konami stays on vanilla ``Copyright.bclim``.
Eng strip stays a separate BCLIM (not merged into Copyright). Main Menu is a
white column — soft white-on-white vanishes; use white glyphs + strong black
outline (Aug 2026 confirm) so it stays readable above Konami.

Usage:
  python tools/deploy_title_engpatch_en.py
  python tools/deploy_title_engpatch_en.py --bisect-tex0   # Eng mats → Copyright tex
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
import zlib
from pathlib import Path

import zopfli.zlib as zopfli_zlib
from PIL import Image, ImageChops, ImageDraw, ImageFont

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
from exact_zlib import compress_exact_zopfli, _force_zero_gaps  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    UI_FONT,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "title_engpatch_en"
ASSET = ROOT / "assets" / "images" / "Title"
PKG = 5261

ENG_PATCH_LINE = "Eng Patch v1.0.0-rc1"
ENG_PATCH_REL = "timg/Eng_Patch.bclim"
ENG_PATCH_BCLIM_NAME = "Eng_Patch.bclim"

# Pts_Copyright: copyright at local Y=0 (218×14); Eng strip above with gap.
ENG_PANE_TY = 20.0
# Grow Nul so Eng at ty=20 ±7 stays inside (was height 40 → clip at ±20).
NUL_H = 56.0
POS_H_TY = -104.0  # Lyt Pos_Copyright_H: keep bottom edge near vanilla (-112)

LABELS: list[tuple[str, str]] = [
    ("timg/Title_btn02_t01.bclim", "Options"),
    ("timg/Title_btn02_t02.bclim", "Game Start"),
    ("timg/Title_btn02_t03.bclim", "Gallery"),
    ("timg/Title_btn02_t04.bclim", "Data Management"),
    ("timg/Title_btn02_t05.bclim", "Communication"),
    ("timg/Title_btn02_t06.bclim", "Anywhere Date"),
]


def render_label(text: str, w: int = 100, h: int = 20) -> Image.Image:
    for size in range(13, 8, -1):
        scale = 2
        big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
        dr = ImageDraw.Draw(big)
        font = ImageFont.truetype(str(UI_FONT), size * scale)
        b = dr.textbbox((0, 0), text, font=font)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w * scale - 4:
            continue
        x = (w * scale - tw) // 2 - b[0]
        y = (h * scale - th) // 2 - b[1]
        dr.text((x, y), text, font=font, fill=(0, 0, 0, 255))
        return big.resize((w, h), Image.Resampling.BILINEAR)
    raise RuntimeError(f"cannot fit {text!r}")


def render_eng_strip(w: int, h: int) -> Image.Image:
    """Standalone Eng line: white fill + thick black outline (Main Menu readable).

    Soft copyright-matched white-only fringe vanishes on the Main Menu white
    column. Aug 2026 confirm used a strong black outline on a separate
    ``Eng_Patch.bclim`` — keep that; do not dual-line into Copyright.
    """
    fill_rgb = (255, 255, 255)
    outline_rgb = (0, 0, 0)

    def _etc1a4_alpha(a: int) -> int:
        if a < 12:
            return 0
        return min(255, ((a + 8) // 17) * 17)

    for size in range(10, 6, -1):
        font = ImageFont.truetype(str(UI_FONT), size)
        probe = ImageDraw.Draw(Image.new("RGBA", (w, h)))
        b = probe.textbbox((0, 0), ENG_PATCH_LINE, font=font)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w - 4 or th > h - 2:
            continue
        x = (w - tw) // 2 - b[0]
        y = (h - th) // 2 - b[1]

        omask = Image.new("L", (w, h), 0)
        fmask = Image.new("L", (w, h), 0)
        od = ImageDraw.Draw(omask)
        fd = ImageDraw.Draw(fmask)
        # Thick outline ring (cardinals + diagonals + 2px cardinals).
        for ox, oy in (
            (-2, 0),
            (2, 0),
            (0, -2),
            (0, 2),
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
            (-2, -1),
            (-2, 1),
            (2, -1),
            (2, 1),
            (-1, -2),
            (1, -2),
            (-1, 2),
            (1, 2),
        ):
            od.text((x + ox, y + oy), ENG_PATCH_LINE, font=font, fill=255)
        fd.text((x, y), ENG_PATCH_LINE, font=font, fill=255)
        fbody = fmask.point(lambda p: 255 if p >= 64 else 0)
        omask = ImageChops.subtract(omask, fbody)

        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        outline = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        op = outline.load()
        om = omask.load()
        for yy in range(h):
            for xx in range(w):
                a = _etc1a4_alpha(om[xx, yy])
                if a:
                    op[xx, yy] = (*outline_rgb, a)
        im = Image.alpha_composite(im, outline)
        im.paste(Image.new("RGBA", (w, h), (*fill_rgb, 255)), (0, 0), fbody)
        px = im.load()
        for yy in range(h):
            for xx in range(w):
                r, g, b, a = px[xx, yy]
                a2 = _etc1a4_alpha(a)
                px[xx, yy] = (0, 0, 0, 0) if a2 == 0 else (r, g, b, a2)
        return im
    raise RuntimeError(f"cannot fit {ENG_PATCH_LINE!r}")


def _pad_name(name: str, n: int) -> bytes:
    raw = name.encode("ascii")
    if len(raw) >= n:
        raise ValueError(f"name too long for {n} bytes: {name!r}")
    return raw + b"\x00" * (n - len(raw))


def _build_txl1(names: list[str]) -> bytes:
    name_blob = bytearray()
    offsets: list[int] = []
    # Offsets are relative to the start of the offset table (after count).
    base = 4 * len(names)
    for name in names:
        offsets.append(base + len(name_blob))
        name_blob.extend(name.encode("ascii") + b"\x00")
    while len(name_blob) % 4:
        name_blob.append(0)
    body = struct.pack("<I", len(names))
    body += b"".join(struct.pack("<I", o) for o in offsets)
    body += bytes(name_blob)
    return b"txl1" + struct.pack("<I", 8 + len(body)) + body


def _make_pic1(template: bytes, name: str, mat_id: int, ty: float) -> bytes:
    """Clone a pic1; keep W/H from template (Pts uses 218×14)."""
    if template[:4] != b"pic1" or len(template) != 128:
        raise ValueError("expected 128-byte pic1 template")
    out = bytearray(template)
    body = memoryview(out)[8:]
    body[4:28] = _pad_name(name, 24)
    struct.pack_into("<f", out, 8 + 32, ty)
    struct.pack_into("<H", out, 0x5C, mat_id)
    return bytes(out)


def _iter_sections(orig: bytes) -> tuple[int, int, list[bytes]]:
    if orig[:4] != b"CLYT":
        raise ValueError("not CLYT")
    _magic, _bom, header_size, revision, _file_size, section_count = struct.unpack_from(
        "<4sHHIII", orig, 0
    )
    sections: list[bytes] = []
    off = header_size
    for _ in range(section_count):
        size = struct.unpack_from("<I", orig, off + 4)[0]
        sections.append(orig[off : off + size])
        off += size
    return header_size, revision, sections


def _rebuild_clyt(header_size: int, revision: int, sections: list[bytes]) -> bytes:
    out = bytearray()
    out += struct.pack(
        "<4sHHIII",
        b"CLYT",
        0xFEFF,
        header_size,
        revision,
        0,
        len(sections),
    )
    if len(out) < header_size:
        out.extend(b"\x00" * (header_size - len(out)))
    for sec in sections:
        out.extend(sec)
    struct.pack_into("<I", out, 0x0C, len(out))
    return bytes(out)


def patch_lyt_copyright(orig: bytes) -> bytes:
    """Nudge Pos_Copyright_H only — draw path is Pts_Copyright, not Lyt pics."""
    header_size, revision, sections = _iter_sections(orig)
    new_sections: list[bytes] = []
    for sec in sections:
        if sec.startswith(b"pan1"):
            out = bytearray(sec)
            name = out[12:36].split(b"\x00", 1)[0].decode("ascii", "ignore")
            if name == "Pos_Copyright_H":
                struct.pack_into("<f", out, 8 + 32, POS_H_TY)
            new_sections.append(bytes(out))
        else:
            new_sections.append(sec)
    return _rebuild_clyt(header_size, revision, new_sections)


def patch_pts_copyright(orig: bytes, *, eng_tex_index: int = 1) -> bytes:
    """Independent Eng strip inside Pts_Copyright (DMST-bound Parts)."""
    header_size, revision, sections = _iter_sections(orig)
    mat1 = next(s for s in sections if s.startswith(b"mat1"))
    n_mat = struct.unpack_from("<I", mat1, 8)[0]
    mat_off0 = struct.unpack_from("<I", mat1, 12)[0]
    template_mat = mat1[mat_off0 : mat_off0 + 0x50]
    pic_template = next(s for s in sections if s.startswith(b"pic1"))

    new_sections: list[bytes] = []
    inserted_eng = False

    for sec in sections:
        tag = sec[:4]
        if tag == b"txl1":
            new_sections.append(_build_txl1(["Copyright.bclim", ENG_PATCH_BCLIM_NAME]))
            continue
        if tag == b"mat1":
            n = n_mat + 1
            blob = bytearray()
            data_start = 8 + 4 + 4 * n
            offsets = [data_start + i * 0x50 for i in range(n)]
            blob += struct.pack("<I", n)
            for o in offsets:
                blob += struct.pack("<I", o)
            for i in range(n_mat):
                mo = struct.unpack_from("<I", mat1, 12 + 4 * i)[0]
                blob += mat1[mo : mo + 0x50]
            eng = bytearray(template_mat)
            eng[0:0x14] = _pad_name("Pic_EngPatch", 0x14)
            struct.pack_into("<H", eng, 0x34, eng_tex_index)
            blob += eng
            new_sections.append(b"mat1" + struct.pack("<I", 8 + len(blob)) + bytes(blob))
            continue
        if tag == b"pan1":
            out = bytearray(sec)
            name = out[12:36].split(b"\x00", 1)[0].decode("ascii", "ignore")
            if name == "Nul_Copyright":
                struct.pack_into("<f", out, 8 + 64, NUL_H)
            new_sections.append(bytes(out))
            continue
        if tag == b"pic1" and not inserted_eng:
            # Eng above Konami; both under Nul_Copyright (inherits BCLAN show/hide).
            new_sections.append(
                _make_pic1(pic_template, "Pic_EngPatch", mat_id=n_mat, ty=ENG_PANE_TY)
            )
            new_sections.append(sec)
            inserted_eng = True
            continue
        new_sections.append(sec)

    if not inserted_eng:
        raise RuntimeError("Pts_Copyright missing pic1")
    return _rebuild_clyt(header_size, revision, new_sections)


def _verify_pts(lyt: bytes, *, eng_tex_index: int) -> None:
    if ENG_PATCH_BCLIM_NAME.encode() not in lyt:
        raise SystemExit("Pts missing Eng_Patch.bclim")
    if b"Pic_EngPatch" not in lyt:
        raise SystemExit("Pts missing Pic_EngPatch")
    off = 20
    sc = struct.unpack_from("<I", lyt, 0x10)[0]
    eng_mat = None
    eng_tex = None
    nul_h = None
    for _ in range(sc):
        tag = lyt[off : off + 4]
        size = struct.unpack_from("<I", lyt, off + 4)[0]
        if tag == b"mat1":
            n = struct.unpack_from("<I", lyt, off + 8)[0]
            for j in range(n):
                mo = struct.unpack_from("<I", lyt, off + 12 + 4 * j)[0]
                name = lyt[off + mo : off + mo + 0x14].split(b"\x00", 1)[0]
                if name == b"Pic_EngPatch":
                    eng_mat = j
                    eng_tex = struct.unpack_from("<H", lyt, off + mo + 0x34)[0]
        elif tag == b"pan1":
            name = lyt[off + 12 : off + 36].split(b"\x00", 1)[0]
            if name == b"Nul_Copyright":
                nul_h = struct.unpack_from("<f", lyt, off + 8 + 64)[0]
        elif tag == b"pic1":
            name = lyt[off + 12 : off + 36].split(b"\x00", 1)[0]
            if name == b"Pic_EngPatch":
                mat = struct.unpack_from("<H", lyt, off + 0x5C)[0]
                ty = struct.unpack_from("<f", lyt, off + 8 + 32)[0]
                if mat != eng_mat:
                    raise SystemExit(f"Eng pic mat {mat} != mat index {eng_mat}")
                if abs(ty - ENG_PANE_TY) > 0.01:
                    raise SystemExit(f"Eng ty {ty} expected {ENG_PANE_TY}")
        off += size
    if eng_tex != eng_tex_index:
        raise SystemExit(f"Eng tex {eng_tex} expected {eng_tex_index}")
    if nul_h is None or abs(nul_h - NUL_H) > 0.01:
        raise SystemExit(f"Nul_Copyright h={nul_h} expected {NUL_H}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--bisect-tex0",
        action="store_true",
        help="Point Eng material at Copyright.bclim (tex 0) to test pane visibility",
    )
    args = ap.parse_args()
    eng_tex = 0 if args.bisect_tex0 else 1

    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    if not UI_FONT.is_file():
        raise SystemExit(f"missing UI font {UI_FONT}")

    bak = MOD_IMG.with_suffix(".bin.bak_pre_title_engpatch")
    if not bak.is_file():
        bak.write_bytes(MOD_IMG.read_bytes())
        print("created", bak, flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    ASSET.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)
    extract_dir = OUT / "title_arc_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)

    # Prefer bak_pre_title_engpatch / vanilla so we rebuild from clean Title.arc.
    src_img = VANILLA if VANILLA.is_file() else MOD_IMG
    bak_title = MOD_IMG.with_suffix(".bin.bak_pre_title_engpatch")
    if bak_title.is_file():
        # Extract clean package from bak when available (avoids stacking on prior Eng).
        src_for_pkg = bak_title
    else:
        src_for_pkg = src_img
    print(f"Title ARC source: {src_for_pkg}", flush=True)
    raw = src_for_pkg.read_bytes()
    img = ImgBin(str(src_for_pkg))
    img.parse(False)
    res = img.entries[PKG]
    src_pkg = pkg_dir / f"{PKG:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc.fw.len()
    van_dec = len(arc.parsed())
    print(f"pkg {PKG} slot={cmp_len} arc={van_dec}", flush=True)

    darc = DarcArchive(bytearray(arc.parsed()))
    darc.extract_all(extract_dir)

    for path, en in LABELS:
        if darc.find(path) is None:
            raise SystemExit(f"missing {path}")
        raw_b = (extract_dir / path).read_bytes()
        rgba = render_label(en)
        png = tmp / f"{Path(path).stem}.png"
        orig = tmp / f"{Path(path).stem}.bclim"
        rgba.save(png)
        rgba.save(ASSET / f"{Path(path).stem}.png")
        rgba.save(OUT / f"{Path(path).stem}_en.png")
        orig.write_bytes(raw_b)
        (extract_dir / path).write_bytes(png_to_bclim_rgba4444_same_size(png, orig))
        print(f"OK {Path(path).name} -> {en!r}", flush=True)

    # Vanilla Copyright.bclim stays single-line Konami (from extract).
    cpath = extract_dir / "timg" / "Copyright.bclim"
    _pix, cw, ch, cfmt, _ft = parse_bclim(cpath.read_bytes())
    if cfmt != 0xB:
        raise SystemExit(f"Copyright fmt {cfmt:#x} expected ETC1A4")
    print(f"OK Copyright.bclim vanilla {cw}x{ch} (Konami only)", flush=True)

    eng_rgba = render_eng_strip(cw, ch)
    eng_png = tmp / "Eng_Patch.png"
    eng_rgba.save(eng_png)
    eng_rgba.save(ASSET / "Eng_Patch.png")
    eng_rgba.save(OUT / "Eng_Patch_en.png")
    eng_rgba.resize((cw * 4, ch * 4), Image.Resampling.NEAREST).save(
        OUT / "Eng_Patch_en_x4.png"
    )
    eng_bclim = png_to_bclim_etc1a4_same_size(eng_png, cpath)
    (extract_dir / ENG_PATCH_REL).write_bytes(eng_bclim)
    print(f"OK {ENG_PATCH_REL} {cw}x{ch} ({len(eng_bclim)} B) -> {ENG_PATCH_LINE!r}", flush=True)

    lyt_path = extract_dir / "blyt" / "Lyt_Copyright.bclyt"
    patched_lyt = patch_lyt_copyright(lyt_path.read_bytes())
    lyt_path.write_bytes(patched_lyt)
    (OUT / "Lyt_Copyright.bclyt").write_bytes(patched_lyt)
    print(f"OK Lyt_Copyright.bclyt Pos_Copyright_H.ty={POS_H_TY}", flush=True)

    pts_path = extract_dir / "blyt" / "Pts_Copyright.bclyt"
    patched_pts = patch_pts_copyright(pts_path.read_bytes(), eng_tex_index=eng_tex)
    pts_path.write_bytes(patched_pts)
    (OUT / "Pts_Copyright.bclyt").write_bytes(patched_pts)
    print(
        f"OK Pts_Copyright.bclyt {len(patched_pts)} B "
        f"(Eng ty={ENG_PANE_TY}, Nul h={NUL_H}, tex={eng_tex}"
        f"{' BISECT' if args.bisect_tex0 else ''})",
        flush=True,
    )

    if darc.find(ENG_PATCH_REL) is None:
        darc.insert_file_entry(ENG_PATCH_REL, after_rel="timg/Copyright.bclim")
    rebuilt = OUT / "Title_rebuilt.arc"
    darc.rebuild_from_dir(extract_dir, rebuilt, align_mode="absolute")
    cand = _force_zero_gaps(rebuilt.read_bytes())
    print(f"rebuilt ARC dec={len(cand)} (was {van_dec})", flush=True)

    check = DarcArchive(bytearray(cand))
    if check.find(ENG_PATCH_REL) is None:
        raise SystemExit("Eng_Patch.bclim missing after rebuild")
    pts = check.extract_file(check.find("blyt/Pts_Copyright.bclyt"))  # type: ignore[arg-type]
    _verify_pts(pts, eng_tex_index=eng_tex)
    bad = [f for f in check.files if f.name.lower().endswith(".bclim") and f.offset % 0x80]
    if bad:
        raise SystemExit(f"BCLIM not 0x80-aligned: {bad[0].name} @ {bad[0].offset:#x}")
    print("Eng_Patch in Pts OK; abs-align OK", flush=True)

    z0 = len(zopfli_zlib.compress(cand))
    print(f"  zopfli={z0} slot={cmp_len}", flush=True)
    if z0 > cmp_len:
        raise SystemExit(f"Title ARC zopfli {z0} exceeds slot {cmp_len}")

    try:
        tuned, slot = compress_exact_zopfli(cand, cmp_len)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned or do.unused_data or not do.eof:
        raise SystemExit("zlib verify failed")
    print(f"ARC exact {len(slot)}", flush=True)

    blob = bytearray(src_pkg.read_bytes())
    entry_off = Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp or slot_len != cmp_len:
        raise SystemExit("ARC entry mismatch")
    if len(tuned) != dec_len:
        delta = len(tuned) - dec_len
        print(f"updating ARC dec_len {dec_len} -> {len(tuned)}", flush=True)
        struct.pack_into("<I", blob, entry_off + 8, len(tuned))
        hdr_dec = struct.unpack_from("<I", blob, 20)[0]
        struct.pack_into("<I", blob, 20, hdr_dec + delta)
        print(f"pkg dec_len {hdr_dec} -> {hdr_dec + delta}", flush=True)
    blob[cmp_off : cmp_off + cmp_len] = slot
    new_pkg = pkg_dir / f"new_{PKG:04d}"
    new_pkg.write_bytes(blob)
    (pkg_dir / f"{PKG:04d}").write_bytes(new_pkg.read_bytes())

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

    print("deployed Title + Pts Eng Patch container ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
