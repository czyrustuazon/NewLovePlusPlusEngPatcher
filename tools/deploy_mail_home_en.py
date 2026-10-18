#!/usr/bin/env python3
"""EN Mail home: Mail buttons and Mail.arc chrome (Mail 5207).

The Mail header (``mail_toptex_RBGA4`` @ MyroomHeader 5575) belongs to
``deploy_schedule_header_en.py``, which rebuilds 5575 later in the bake.

Buttons: Inbox / New Message / Ringtone Settings (着信音設定) / Play (再生).
All use the Zhoumaru masters ``Mail.check/timg/mail_tex_{jyusin,shinki,chak}_RGBA4.png``
(flat gray like vanilla) and ``C_Btn_Play_{Off,On}.png``.

Inbox category rows ``Sel_Tex_ma02_01..05`` (カノジョのメール … 謎メール) are
font-rendered here — Zhoumaru left 01 in JP and mistranslated 05.

Mail.arc is rebuilt from vanilla, so ``ZHOUMARU_ONLY`` lists every other good
``Mail.check`` master (compose tabs, emoji names, phone menu, Check/Reply,
OK). Without it they shipped Japanese.
"""
from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

import zopfli.zlib as zopfli_zlib
from PIL import Image, ImageDraw, ImageFont

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
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    HEISEI_W5,
    UI_FONT,
    find_ui_png,
    maybe_backup_img,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "mail_home_en"
FONT = UI_FONT  # bundled OFL (assets/fonts/MPLUS1p-Regular.ttf)
# Dark-blue ink on transparent (white button / patterned header behind).
INK = (70, 110, 160)
# Vanilla Sel_Tex_ma02 rows are flat gray (85) RGBA4444 on transparent.
CATEGORY_INK = (85, 85, 85)


BUTTON_PKG = 5207
BUTTON_LABELS = [
    ("timg/mail_tex_jyusin_RGBA4.bclim", "Inbox"),
    ("timg/mail_tex_shinki_RGBA4.bclim", "New Message"),  # 新規作成; Zhoumaru wording
    ("timg/mail_tex_chak_RGBA4.bclim", "Ringtone Settings"),
    ("timg/C_Btn_Play_Off.bclim", "Play"),  # 再生
    ("timg/C_Btn_Play_On.bclim", "Play"),
]
# Inbox categories — always render (do not pack Zhoumaru ma02 masters).
CATEGORY_LABELS = [
    ("timg/Sel_Tex_ma02_01.bclim", "Girlfriend Mail"),  # カノジョのメール
    ("timg/Sel_Tex_ma02_02.bclim", "Friend Mail"),  # 友達のメール
    ("timg/Sel_Tex_ma02_03.bclim", "Contact Mail"),  # 連絡メール
    ("timg/Sel_Tex_ma02_04.bclim", "Info Mail"),  # 情報メール
    ("timg/Sel_Tex_ma02_05.bclim", "Mystery Mail"),  # 謎メール
]
# Packed straight from Mail.check (fmt 8 or ETC1A4). Not listed: the 1x1
# Sel_Tex_ma15_* / te05 stubs, and C_Com_icon_Repry2 (送信 "Send"), which
# Zhoumaru mislabeled "Reply".
ZHOUMARU_ONLY = [
    ("timg/C_Com_Win01_Btn02_Ok_Off.bclim", "OK"),
    ("timg/C_Com_Win01_Btn02_Ok_Press.bclim", "OK"),
    ("timg/C_Com_icon_Confirm.bclim", "Check"),  # 確認
    ("timg/C_Com_icon_Repry1.bclim", "Reply"),  # 返信
    ("timg/Mail_PopTxt03.bclim", "Select Emoji"),
    ("timg/Mail_SendType_T01.bclim", "Greeting"),  # 挨拶
    ("timg/Mail_SendType_T02.bclim", "Love Words"),  # 愛の言葉
    ("timg/Mail_SendType_T03.bclim", "Send Mood"),  # 気分送信
    ("timg/Mail_SendType_T04.bclim", "Special"),  # 特殊
    ("timg/Sel_Tex_na01.bclim", "Manaka Takane"),
    ("timg/Sel_Tex_na02.bclim", "Rinko Kobayakawa"),
    ("timg/Sel_Tex_na03.bclim", "Nene Anegasaki"),
    ("timg/Sel_Tex_te01.bclim", "Call Log"),
    ("timg/Sel_Tex_te02.bclim", "Date Reservation"),
    ("timg/Sel_Tex_te03.bclim", "Premium Date R."),
    ("timg/Sel_Tex_te04.bclim", "Call Out"),
    ("timg/Sel_Tex_te06.bclim", "Cancel Date"),
    ("timg/Sel_Tex_te07.bclim", "Change Date & Time"),
    ("timg/Sel_Tex_te08.bclim", "Latest Call"),
    ("timg/Sel_Tex_te09.bclim", "Play Voicemail"),
    ("timg/Sel_Tex_te10.bclim", "Date M D ( )"),
    ("timg/Sel_Tex_te11.bclim", "Change Travel Date"),
    ("timg/Tel_PlayBtn_Off.bclim", "Play Voicemail"),
    ("timg/Tel_PlayBtn_On.bclim", "Play Voicemail"),
] + [(f"timg/Emoji_Name_{i:02d}.bclim", "emoji") for i in range(1, 25)]
ZHOUMARU_ONLY_STEMS = frozenset(Path(p).stem for p, _en in ZHOUMARU_ONLY)

# Prefer Zhoumaru masters for these stems (home buttons + Play pill chrome).
ZHOUMARU_BUTTONS = frozenset(
    {
        "mail_tex_jyusin_RGBA4",
        "mail_tex_shinki_RGBA4",
        "mail_tex_chak_RGBA4",
        "C_Btn_Play_Off",
        "C_Btn_Play_On",
    }
) | ZHOUMARU_ONLY_STEMS


def font(size: int, face: Path = FONT) -> ImageFont.FreeTypeFont:
    # Heisei W5 is a TTC — P-face at index 1 (same as MultiWin bars).
    idx = 1 if face == HEISEI_W5 else 0
    return ImageFont.truetype(str(face), size=size, index=idx)


def render_label(
    w: int,
    h: int,
    text: str,
    *,
    ink: tuple[int, int, int] = INK,
    face: Path = FONT,
) -> Image.Image:
    for size in range(min(16, h + 2), 8, -1):
        scale = 2
        big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
        dr = ImageDraw.Draw(big)
        f = font(size * scale, face)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w * scale - 4:
            continue
        x = (w * scale - tw) // 2 - b[0]
        y = (h * scale - th) // 2 - b[1]
        dr.text((x, y), text, font=f, fill=ink + (255,))
        return big.resize((w, h), Image.Resampling.BILINEAR)
    raise RuntimeError(f"cannot fit {text!r} in {w}x{h}")


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
    pad_rng = os.urandom(cap) if cap else b""
    print(f"  gap capacity={cap}; tuning…", flush=True)
    step = max(1, cap // 400) if cap else 1
    for n in list(range(cap, -1, -step)) + list(range(cap, -1, -1)):
        cand = apply_gap_pad(data, n, pad_rng) if cap else data
        slot = compress_exact_empty_blocks(cand, exact_len)
        if slot is not None:
            print(f"  hit pad_bytes={n}", flush=True)
            return cand, slot
    raise SystemExit("could not build exact zlib stream")


def compress_exact_zopfli(data: bytes, target: int) -> tuple[bytes, bytes]:
    z0 = len(zopfli_zlib.compress(data))
    if z0 > target:
        # fall back — empty blocks need leaner data first
        raise SystemExit(f"zopfli {z0} exceeds slot {target}")
    if z0 == target:
        return data, zopfli_zlib.compress(data)
    runs = interfile_zero_gaps(data, min_len=8)
    cap = sum(sz for sz, _ in runs)
    rng = os.urandom(cap) if cap else b""
    lo, hi = 0, cap
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = apply_gap_pad(data, mid, rng) if cap else data
        z = zopfli_zlib.compress(cand)
        if len(z) == target:
            return cand, z
        if len(z) < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return compress_exact_with_gap_tune(data, target)


def replace_labels(
    darc: DarcArchive,
    labels: list[tuple[str, str]],
    tmp: Path,
    *,
    fmt: int | None,
) -> None:
    """``fmt=None`` accepts fmt 8 or ETC1A4 per stem (``ZHOUMARU_ONLY``)."""
    for path, en in labels:
        entry = darc.find(path) or darc.find(Path(path).name)
        if entry is None:
            raise SystemExit(f"missing {path}")
        raw = darc.extract_file(entry)
        _pix, w, h, got, _ft = parse_bclim(raw)
        if fmt is not None and got != fmt or got not in (8, 0xB):
            raise SystemExit(f"{path} fmt {got} != {fmt}")
        stem = Path(path).stem
        master = (
            find_ui_png(("Mail.check", "Mail"), stem, (w, h))
            if stem in ZHOUMARU_BUTTONS
            else None
        )
        if master is not None:
            with Image.open(master) as im:
                rgba = im.convert("RGBA")
            if rgba.size != (w, h):
                rgba = rgba.resize((w, h), Image.Resampling.LANCZOS)
            src = master.name
        elif stem in ZHOUMARU_ONLY_STEMS:
            raise SystemExit(f"{path}: missing Zhoumaru master")
        elif stem.startswith("Sel_Tex_ma02_"):
            rgba = render_label(
                w, h, en, ink=CATEGORY_INK, face=HEISEI_W5
            )
            src = "render Heisei"
        else:
            rgba = render_label(w, h, en)
            src = "render"
        png = tmp / "t.png"
        orig = tmp / "o.bclim"
        rgba.save(png)
        rgba.save(OUT / f"{stem}_en.png")
        orig.write_bytes(raw)
        if got == 0xB:
            new = png_to_bclim_etc1a4_same_size(png, orig)
        else:
            new = png_to_bclim_rgba4444_same_size(png, orig)
        darc.replace_same_size(entry, new)
        print(f"OK {path} -> {en!r} ({src})", flush=True)


def patch_package(
    pkg_id: int,
    labels: list[tuple[str, str]],
    *,
    fmt: int | None,
    use_zopfli: bool,
) -> None:
    vanilla = VANILLA if VANILLA.is_file() else MOD_IMG
    vraw = vanilla.read_bytes()
    vimg = ImgBin(str(vanilla))
    vimg.parse(False)
    res = vimg.entries[pkg_id]
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    src_pkg = pkg_dir / f"{pkg_id:04d}"
    src_pkg.write_bytes(vraw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc_elem.fw.len()
    print(f"pkg {pkg_id} ARC dec={len(arc_elem.parsed())} slot={cmp_len}", flush=True)

    tmp = OUT / f"_fit_{pkg_id}"
    tmp.mkdir(parents=True, exist_ok=True)
    darc = DarcArchive(bytearray(arc_elem.parsed()))
    replace_labels(darc, labels, tmp, fmt=fmt)
    patched = bytes(darc.data)

    if use_zopfli:
        try:
            tuned, slot = compress_exact_zopfli(patched, cmp_len)
        except SystemExit:
            tuned, slot = compress_exact_with_gap_tune(patched, cmp_len)
    else:
        tuned, slot = compress_exact_with_gap_tune(patched, cmp_len)
    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned or do.unused_data or not do.eof:
        raise SystemExit(f"pkg {pkg_id} zlib verify failed")
    print(f"  ARC exact {len(slot)}", flush=True)

    blob = bytearray(src_pkg.read_bytes())
    entry_off = Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp or slot_len != cmp_len or len(tuned) != dec_len:
        raise SystemExit(f"pkg {pkg_id} ARC entry mismatch")
    blob[cmp_off : cmp_off + cmp_len] = slot
    new_pkg = pkg_dir / f"new_{pkg_id:04d}"
    new_pkg.write_bytes(blob)

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC):
            if b.parsed() != tuned:
                raise SystemExit(f"pkg {pkg_id} ARC mismatch")
        elif a.parsed() != b.parsed():
            raise SystemExit(f"pkg {pkg_id} DMST changed")
    print("  DMST OK", flush=True)

    expect = new_pkg.read_bytes()
    for _dest in iter_deploy_targets(MOD_IMG):
        splice_packages_into_img(_dest, pkg_dir, [pkg_id], _dest)
        vimg = ImgBin(str(_dest))
        vimg.parse(False)
        slot = vimg.entries[pkg_id]
        got = _dest.read_bytes()[
            slot.fw.base_offset : slot.fw.base_offset + slot.fw.len()
        ]
        if got != expect:
            raise SystemExit(
                f"post-splice mismatch pkg {pkg_id} on {_dest} "
                f"(img still has old package — is Azahar locking img.bin?)"
            )


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    bak = maybe_backup_img(MOD_IMG, "mail_home")
    OUT.mkdir(parents=True, exist_ok=True)

    patch_package(
        BUTTON_PKG,
        BUTTON_LABELS + CATEGORY_LABELS + ZHOUMARU_ONLY,
        fmt=None,
        use_zopfli=False,
    )
    print("deployed Mail home EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)


if __name__ == "__main__":
    main()
