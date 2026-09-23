#!/usr/bin/env python3
"""EN MultiWin header strips — pkg 5237 ETC1A4 (FUN_00255a18 table).

Girlfriend Comm / Communication submenus bind Com_MultiWin_W01_Text04_* via
FUN_00255a18, NOT the MSel Plate_Text04_* A8 assets (those are home plates).

Also keeps Delete Save Data Text05_01 so a vanilla rebuild of 5237 does not
wipe the earlier datadelete header patch.
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import parse_bclim, png_to_bclim_etc1a4_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_exact_zopfli, try_fast_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    AZAHAR_INSTANCES,
    UI_FONT,
    maybe_backup_img,
    find_ui_png,
    iter_deploy_targets,
    render_header_aa,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "multiwin_headers_en"
FONT = UI_FONT
PKG = 5237

# FUN_00255a18 idx → MultiWin text (table @ ~0x6c3f9c)
HEADER_LABELS = [
    # Gallery (Text02)
    ("timg/Com_MultiWin_W01_Text02_00_00.bclim", "Gallery"),  # 0x0
    ("timg/Com_MultiWin_W01_Text02_01_00.bclim", "Event Gallery"),  # 0x1
    ("timg/Com_MultiWin_W01_Text02_01_01.bclim", "Confession Memories"),
    ("timg/Com_MultiWin_W01_Text02_01_02.bclim", "After the Dream"),
    ("timg/Com_MultiWin_W01_Text02_01_03.bclim", "Trip Memories"),
    ("timg/Com_MultiWin_W01_Text02_01_04.bclim", "Youthful Page"),
    ("timg/Com_MultiWin_W01_Text02_02_00.bclim", "Illustration Gallery"),  # 0x7
    ("timg/Com_MultiWin_W01_Text02_02_01.bclim", "Dream Gallery"),  # 0x8
    ("timg/Com_MultiWin_W01_Text02_02_02.bclim", "Special Gallery"),  # 0x9
    ("timg/Com_MultiWin_W01_Text02_01_05.bclim", "Gallery Options"),  # 0x6
    # Options password entry (Text03) — Lyt_Pass_Info_Display white bar
    ("timg/Com_MultiWin_W01_Text03_05_00.bclim", "Password Input"),
    # Communication (Text04)
    ("timg/Com_MultiWin_W01_Text04_00_00.bclim", "Communication"),  # 0x11
    ("timg/Com_MultiWin_W01_Text04_01_00.bclim", "Heart to Heart"),  # 0x12 カノジョ通信
    ("timg/Com_MultiWin_W01_Text04_02_00.bclim", "Business Card"),  # 0x16
    ("timg/Com_MultiWin_W01_Text04_03_00.bclim", "Wireless Battle"),  # 0x17
    # Data Management
    ("timg/Com_MultiWin_W01_Text05_01_00.bclim", "Delete Save Data"),  # 0x1a
]
# Incremental: Communication substrips on the live ARC only.
# Vanilla+zopfli of extras together with the Gallery --full pass is a bad
# compress path; the Communications *loading* hang was Azahar OpenLinkFile (§10.1).
# Text04_01_00 is the カノジョ通信 white bar. Zhoumaru MultiWin 01_00 is Network;
# 01_01 PNG is a cramped 8px strip — skip both and font-render "Heart to Heart".
EXTRA_LABELS = [
    ("timg/Com_MultiWin_W01_Text02_01_01.bclim", "Confession Memories"),
    ("timg/Com_MultiWin_W01_Text02_01_02.bclim", "After the Dream"),
    ("timg/Com_MultiWin_W01_Text02_01_03.bclim", "Trip Memories"),
    ("timg/Com_MultiWin_W01_Text02_01_04.bclim", "Youthful Page"),
    ("timg/Com_MultiWin_W01_Text04_00_00.bclim", "Communication"),
    ("timg/Com_MultiWin_W01_Text04_01_00.bclim", "Heart to Heart"),
    ("timg/Com_MultiWin_W01_Text04_01_01.bclim", "Heart to Heart"),
    ("timg/Com_MultiWin_W01_Text04_01_02.bclim", "Introduction"),
    ("timg/Com_MultiWin_W01_Text04_01_03.bclim", "Double Date"),
    ("timg/Com_MultiWin_W01_Text04_02_00.bclim", "Business Card"),
    ("timg/Com_MultiWin_W01_Text04_03_00.bclim", "Wireless Battle"),
    ("timg/Com_MultiWin_W01_Text04_04_00.bclim", "Communication Settings"),
    ("timg/Com_MultiWin_W01_Text03_05_00.bclim", "Password Input"),
]
# MultiWin Text02_01_01 PNG is "Friend's Memory"; keep that painted strip
# rather than stretching MSel "Confession Memories" to fill 192×16.
# カノジョ通信 header: skip Zhoumaru 01_00 (Network) and 01_01 (8px strip).
PNG_STEM_OVERRIDE: dict[str, str] = {}
SKIP_UI_PNG = {
    "Com_MultiWin_W01_Text04_01_00",
    "Com_MultiWin_W01_Text04_01_01",
}
UI_PNG_FOLDERS = ("NCommon.check", "NCommonMSel(4).check", "NCommonMSel(7).check")

VANILLA_CANDIDATES = [
    VANILLA,
    Path(r"C:\Users\Zepse\nlpp_work\romfs\img.bin"),
]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size=size)


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
    t = bytearray(data)
    for g0, g1 in all_interfile_gaps(data):
        t[g0:g1] = b"\x00" * (g1 - g0)
    return bytes(t)


def exact_slot(data: bytes, exact_len: int, *, zero_gaps: bool) -> tuple[bytes, bytes]:
    """Fit 5237 ARC to the img.bin slot. Prefer zlib; pad short zopfli (no salt loop)."""
    if zero_gaps:
        data = zero_interfile_gaps(data)
    fast = try_fast_exact_slot(data, exact_len)
    if fast is not None:
        print("  hit exact-zlib fast-path", flush=True)
        return fast
    print("  escalating to zopfli + empty-block pad", flush=True)
    return compress_exact_zopfli(data, exact_len)


def render_header_label(w: int, h: int, text: str, *, max_size: int | None = None) -> Image.Image:
    """White alpha text for MultiWin ETC1A4 header strip."""
    top = max_size if max_size is not None else min(15, h + 2)
    for size in range(top, 7, -1):
        scale = 2
        big = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
        dr = ImageDraw.Draw(big)
        f = font(size * scale)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w * scale - 8:
            continue
        x = (w * scale - tw) // 2 - b[0]
        y = (h * scale - th) // 2 - b[1]
        dr.text((x, y), text, font=f, fill=(255, 255, 255, 255))
        return big.resize((w, h), Image.Resampling.BILINEAR)
    raise RuntimeError(f"cannot fit header {text!r} into {w}x{h}")


def pick_vanilla() -> Path:
    for p in VANILLA_CANDIDATES:
        if p.is_file():
            return p
    raise SystemExit("no vanilla img.bin found")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--full",
        action="store_true",
        help="Rebuild all MultiWin headers from vanilla (gold bake). "
        "Default: patch only extra Communication substrips onto live 5237.",
    )
    args = ap.parse_args()

    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

    bak = maybe_backup_img(MOD_IMG, "multiwin_headers")

    if args.full:
        src_img = pick_vanilla()
        labels = HEADER_LABELS
        print("vanilla ARC source:", src_img, flush=True)
    else:
        src_img = MOD_IMG
        labels = EXTRA_LABELS
        print("live ARC source (extras only):", src_img, flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    vraw = src_img.read_bytes()
    vimg = ImgBin(str(src_img))
    vimg.parse(False)

    res = vimg.entries[PKG]
    if res is None:
        raise SystemExit(f"pkg {PKG} missing")
    src_pkg = pkg_dir / f"{PKG:04d}"
    src_pkg.write_bytes(
        vraw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
    )

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc_elem.fw.len()
    print(
        f"\n=== PKG {PKG} MultiWin headers dec={len(arc_elem.parsed())} "
        f"slot={cmp_len} ===",
        flush=True,
    )

    darc = DarcArchive(bytearray(arc_elem.parsed()))
    for path, en in labels:
        entry = darc.find(path) or darc.find(Path(path).name)
        if entry is None:
            raise SystemExit(f"missing {path}")
        raw = darc.extract_file(entry)
        _pix, w, h, fmt, _ft = parse_bclim(raw)
        if fmt != 0xB:
            raise SystemExit(f"{path} fmt {fmt:#x} not ETC1A4")
        png = tmp / f"{Path(path).stem}.png"
        orig = tmp / f"{Path(path).stem}.bclim"
        orig.write_bytes(raw)
        stem = Path(path).stem
        master = None
        if stem not in SKIP_UI_PNG:
            master = find_ui_png(
                UI_PNG_FOLDERS, PNG_STEM_OVERRIDE.get(stem, stem), (w, h)
            )
            # MultiWin bars are 192×16 pixel paint. Scaled `_ui_png_fit` copies
            # come out deep-fried after ETC1A4.
            if master is not None:
                fitted = "_ui_png_fit" in Path(master).parts
                with Image.open(master) as im:
                    native = im.size == (w, h)
                if fitted or not native:
                    print(f"  skip scaled {master.name} for {stem}", flush=True)
                    master = None
        if stem in SKIP_UI_PNG:
            print(f"  font-render-aa {stem} {en!r}", flush=True)
            rgba = render_header_aa(w, h, en)
        elif master is not None:
            rgba = Image.open(master).convert("RGBA")
        else:
            print(f"  font-render {stem} {en!r}", flush=True)
            rgba = render_header_label(w, h, en)
        rgba.save(png)
        new = png_to_bclim_etc1a4_same_size(png, orig)
        rgba.save(OUT / f"{Path(path).stem}_en.png")
        darc.replace_same_size(entry, new)
        print(f"  OK {path} -> {en!r}", flush=True)

    patched = bytes(darc.data)
    tuned, slot = exact_slot(patched, cmp_len, zero_gaps=args.full)
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
    print("  DMST unchanged OK", flush=True)

    try:
        targets = list(iter_deploy_targets(MOD_IMG))
        inst_root = AZAHAR_INSTANCES
        seen = {p.resolve() for p in targets}
        for img in inst_root.glob("*/user/load/mods/00040000000F4E00/romfs/img.bin"):
            rp = img.resolve()
            if rp.is_file() and rp not in seen:
                targets.append(rp)
                seen.add(rp)
        for _dest in targets:
            splice_packages_into_img(_dest, pkg_dir, [PKG], _dest)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("\ndeployed MultiWin EN pkg", PKG, "->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    print("Re-open Girlfriend Communication to reload pkg 5237.", flush=True)


if __name__ == "__main__":
    main()
