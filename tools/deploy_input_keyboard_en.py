#!/usr/bin/env python3
"""EN keyboard mode labels in InputC/InputNTexture (pkg 5190).

Vanilla JP uses short dark-ink plates (漢字/かな/カナ/小文字/英数/記号/削除)
on 48x24 RGBA4444. The prior EN set was light outlined ALL-CAPS
(KANJI/HIRAGANA/…) which muddies into the light button chrome.

This rebuilds short dark labels matching JP length + ink, writes them into
assets/images/Input{C,N}Texture.check/timg/, then exact-zlib splices both
ARCs into live img.bin.
"""
from __future__ import annotations

import shutil
import sys
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import parse_bclim, png_to_bclim_rgba4444_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import (  # noqa: E402
    _force_zero_gaps,
    compress_exact_empty_blocks,
    compress_exact_zopfli,
)
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402


from deploy_common import (  # noqa: E402
    UI_FONT,
    iter_deploy_targets,
    resolve_img_paths,
)

MOD_IMG, VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "input_keyboard_en"
ASSETS = ROOT / "assets" / "images"
ASSET_DIRS = (
    ASSETS / "InputCTexture.check" / "timg",
    ASSETS / "InputNTexture.check" / "timg",
)
ARCS = ("InputCTexture.arc", "InputNTexture.arc")
PKG = 5190
INK = (51, 51, 51)  # match vanilla dark plate ink

# stem → EN. Short forms match JP 2–3 glyph length so 48x24 stays legible.
# Clear_* keep existing EN chrome from assets (same as deploy_ui_buttons_en).
LABELS: list[tuple[str, str]] = [
    ("Profile_Btn_Com01_Text01", "Kanji"),  # 漢字
    ("Profile_Btn_Com01_Text02", "Hira"),  # かな
    ("Profile_Btn_Com01_Text03", "Kata"),  # カナ
    ("Profile_Btn_Com01_Text04", "Small"),  # 小文字
    ("Profile_Btn_Com01_Text05", "ABC"),  # 英数
    ("Profile_Btn_Com01_Text06", "Sym"),  # 記号
    ("Profile_Btn_Com01_Text07", "Erase"),  # 削除
]
CLEAR_STEMS = ("Profile_Btn_Clear_Off", "Profile_Btn_Clear_On")


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(UI_FONT), size=size)


def render_label(w: int, h: int, text: str) -> Image.Image:
    """Dark centered label — hard edges (compresses into the tight InputN slot)."""
    for size in range(min(14, h), 7, -1):
        # Draw 1:1; soft supersample blows zlib past InputN's 18856 slot.
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        f = font(size)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w - 2 or th > h - 1:
            continue
        x = (w - tw) // 2 - b[0]
        y = (h - th) // 2 - b[1]
        # Mask → hard alpha so RGBA4444 stays sparse like vanilla JP.
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).text((x, y), text, font=f, fill=255)
        mask = mask.point(lambda p: 255 if p >= 128 else 0)
        ink = Image.new("RGBA", (w, h), INK + (255,))
        im.paste(ink, (0, 0), mask)
        return im
    raise RuntimeError(f"cannot fit {text!r} in {w}x{h}")


def write_asset_pngs(w: int = 48, h: int = 24) -> None:
    sheet_rows: list[Image.Image] = []
    for stem, text in LABELS:
        existing = next((d / f"{stem}.png" for d in ASSET_DIRS if (d / f"{stem}.png").is_file()), None)
        if existing is not None:
            im = Image.open(existing).convert("RGBA")
            if im.size != (w, h):
                im = render_label(w, h, text)
            print(f"  keep {stem} -> {text!r}", flush=True)
        else:
            im = render_label(w, h, text)
            print(f"  render {stem} -> {text!r}", flush=True)
        for d in ASSET_DIRS:
            d.mkdir(parents=True, exist_ok=True)
            dest = d / f"{stem}.png"
            if not dest.is_file():
                im.save(dest)
        preview = Image.new("RGBA", (w, h), (245, 245, 245, 255))
        preview.alpha_composite(im)
        sheet_rows.append(preview)
        im.save(OUT / f"{stem}_en.png")

    gap = 4
    sheet = Image.new(
        "RGBA",
        (w, h * len(sheet_rows) + gap * (len(sheet_rows) - 1)),
        (200, 200, 200, 255),
    )
    y = 0
    for row in sheet_rows:
        sheet.paste(row, (0, y))
        y += h + gap
    sheet.save(OUT / "keyboard_labels_sheet.png")
    sheet.resize((sheet.width * 4, sheet.height * 4), Image.Resampling.NEAREST).save(
        OUT / "keyboard_labels_sheet_x4.png"
    )


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


def _patch_arc(arc_bytes: bytes, src_dir: Path, tmp: Path) -> bytes:
    darc = DarcArchive(bytearray(arc_bytes))
    stems: list[tuple[str, str | None]] = [(s, t) for s, t in LABELS]
    stems.extend((s, None) for s in CLEAR_STEMS)
    for stem, text in stems:
        path = f"timg/{stem}.bclim"
        entry = darc.find(path) or darc.find(f"{stem}.bclim")
        if entry is None:
            raise SystemExit(f"missing BCLIM {path}")
        raw = darc.extract_file(entry)
        _pix, w, h, fmt, _ = parse_bclim(raw)
        if fmt != 8:
            raise SystemExit(f"{stem} expected RGBA4444 fmt=8, got {fmt}")
        png_src = src_dir / f"{stem}.png"
        if not png_src.is_file():
            raise SystemExit(f"missing PNG {png_src}")
        im = Image.open(png_src).convert("RGBA")
        if im.size != (w, h):
            print(f"  resize {stem}: {im.size} -> {w}x{h}", flush=True)
            im = im.resize((w, h), Image.Resampling.LANCZOS)
        work_png = tmp / f"{stem}.png"
        work_bclim = tmp / f"{stem}.bclim"
        im.save(work_png)
        work_bclim.write_bytes(raw)
        new = png_to_bclim_rgba4444_same_size(work_png, work_bclim)
        if len(new) != len(raw):
            raise SystemExit(f"size change {stem}: {len(raw)} -> {len(new)}")
        darc.replace_same_size(entry, new)
        note = f" -> {text!r}" if text else " (asset)"
        print(f"  OK {stem} {w}x{h}{note}", flush=True)
    return bytes(darc.data)


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing deploy img: {MOD_IMG}")
    if not VANILLA.is_file():
        raise SystemExit(f"missing vanilla img: {VANILLA}")

    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    print("=== render keyboard labels ===", flush=True)
    write_asset_pngs()

    bak = MOD_IMG.with_suffix(".bin.bak_pre_input_keyboard")
    if not bak.is_file():
        bak.write_bytes(MOD_IMG.read_bytes())
        print("created", bak, flush=True)

    # Virgin ARCs — prior live EN Clear/text + gap salt can push InputN over slot.
    base_img = VANILLA
    print(f"\n=== pkg {PKG} from {base_img.name} (vanilla ARCs) ===", flush=True)

    raw = base_img.read_bytes()
    img = ImgBin(str(base_img))
    img.parse(False)
    res = img.entries[PKG]
    src_pkg = pkg_dir / f"{PKG:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    blob = bytearray(src_pkg.read_bytes())

    wanted = {n.lower() for n in ARCS}
    patched_any = False
    for i, elem in enumerate(pkg.entries):
        if not isinstance(elem, ARC):
            continue
        if elem.fn.lower() not in wanted:
            continue
        cmp_len = elem.fw.len()
        # Prefer matching asset dir (C vs N); both get the same renders.
        use_dir = ASSET_DIRS[0]
        for arc_name, ad in zip(ARCS, ASSET_DIRS):
            if arc_name.lower() == elem.fn.lower():
                use_dir = ad
                break
        print(f"ARC {elem.fn} slot={cmp_len} dec={len(elem.parsed())}", flush=True)
        tuned = _patch_arc(bytes(elem.parsed()), use_dir, tmp)
        tuned = _force_zero_gaps(tuned)
        # InputN slot is tight — empty-block first (seconds) before zopfli search
        # (can hang for many minutes on near-miss binary search).
        eb = compress_exact_empty_blocks(tuned, cmp_len)
        if eb is not None:
            tuned2, slot = tuned, eb
            print(f"  exact zlib empty-block {len(slot)}", flush=True)
        else:
            print("  empty-block miss; trying zopfli…", flush=True)
            tuned2, slot = compress_exact_zopfli(tuned, cmp_len)
            print(f"  exact zlib zopfli {len(slot)}", flush=True)
        do = zlib.decompressobj()
        got = do.decompress(slot)
        if got != tuned2 or do.unused_data or not do.eof:
            raise SystemExit(f"zlib verify failed for {elem.fn}")
        _write_arc_slot(blob, i, tuned2, slot)
        patched_any = True

    if not patched_any:
        raise SystemExit(f"no matching ARCs in pkg {PKG}")

    new_pkg = pkg_dir / f"new_{PKG:04d}"
    new_pkg.write_bytes(blob)

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC) and a.fn.lower() in wanted:
            continue
        if a.parsed() != b.parsed():
            raise SystemExit(f"non-target changed: {getattr(a, 'fn', type(a))}")
    print(f"pkg {PKG} non-target entries OK", flush=True)

    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
            print(f"spliced [{PKG}] -> {dest}", flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("deployed keyboard labels EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    print("Preview:", OUT / "keyboard_labels_sheet_x4.png", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
