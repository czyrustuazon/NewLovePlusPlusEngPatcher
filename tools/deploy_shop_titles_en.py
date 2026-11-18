#!/usr/bin/env python3
"""EN shop title bars: raw ETC1A4 textures in img.bin pkg **5789**.

Each shop and restaurant screen shows a 128×32 title (``Shop_TitTxt00``-``39``).
Most already read ``Menu`` / ``MENU``; these still said 商品一覧 ("Item List")
or メニュー / お品書き / おしながき ("Menu"):

  00  商品一覧, white / teal outline  shared by 00-03 and 05-16 (one stream)
  04  商品一覧, plain white
  17  ・メニュー・, crimson / white outline, dots
  18, 22  おしながき, dark grey
  21  お品書き, thin dark grey
  25  お品書き, amber
  26  お品書き, light grey / black outline
  29  メニュー, thin translucent purple
  30  メニュー, red / white outline       shared by 30 and 31
  39  商品一覧, teal / pale glow

Masters ``assets/images/shop_titles/Shop_TitTxtNN.png`` redraw the English in
each original's colours (``work/render_shop_titles.py`` made them). Each is
encoded with the vanilla payload as ``keep`` and spliced into its own zlib
slot, like ``deploy_trip_mes_en.py``; a master that does not fit is an error.
Titles that share a stream are listed in ``SHARED`` and checked, so an
English title can never be overwritten through a shared stream. No other
deploy writes this package (``Shop.arc``'s own 120×24 copies of 00 / 04 are
in pkg 5258).

Titles in ``FLAT`` (29) are one ETC1 colour block repeated over the whole
texture with the lettering only in alpha, which is why their slots are tiny
(261 bytes). For those only the master's alpha is used and every block keeps
the vanilla colour block, as the original does.

  python tools/deploy_shop_titles_en.py
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import encode_etc1a4_pixels
from deploy_common import maybe_backup_img, resolve_img_paths
from deploy_minigame_textures_en import _deploy_targets, _vanilla_src, try_compress_to_slot
from img import FileWindow, Package
from img import Image as ImgBin
from pack_images import PackError, splice_packages_into_img

MOD_IMG, _FALLBACK_VANILLA = resolve_img_paths()
MASTERS = ROOT / "assets" / "images" / "shop_titles"
OUT = ROOT / "out" / "shop_titles_en"
PKG = 5789
SIZE = (128, 32)
JOBS = ["00", "04", "17", "18", "21", "22", "25", "26", "29", "30", "39"]
FLAT = {"29"}
SHARED = {"00": ["00", "01", "02", "03", *[f"{n:02d}" for n in range(5, 17)]], "30": ["30", "31"]}


def tex_entries(pkg_raw: bytes, pkg_path: Path) -> dict[str, tuple[int, int, int, int]]:
    """``{NN: (dec_len, is_cmp, cmp_len, cmp_off)}`` for every Shop_TitTxtNN TEX
    element, by entry position (TEXI and TEX share each name)."""
    pkg = Package(FileWindow(str(pkg_path)), 0)
    pkg.parse(False)
    out = {}
    for i, elem in enumerate(pkg.entries):
        if elem.typ != b"TEX " or not elem.fn.startswith("Shop_TitTxt"):
            continue
        off = Package.ENTRY_SIZE * (i + 1)
        _typ, dec_len, _do, _fl, is_cmp, cmp_len, cmp_off = Package.parse_entry(pkg_raw[off : off + Package.ENTRY_SIZE])
        out[elem.fn[len("Shop_TitTxt") : -len(".texi")]] = (dec_len, is_cmp, cmp_len, cmp_off)
    return out


def flat_colour(new: bytes, old: bytes, job: str) -> bytes:
    """``new`` with every block's colour half set to ``old``'s single colour block."""
    colours = {old[i + 8 : i + 16] for i in range(0, len(old), 16)}
    if len(colours) != 1:
        raise SystemExit(f"Shop_TitTxt{job}: vanilla has {len(colours)} colour blocks, expected 1")
    (colour,) = colours
    out = bytearray(new)
    for i in range(0, len(out), 16):
        out[i + 8 : i + 16] = colour
    return bytes(out)


def patch_package(pkg_raw: bytes, pkg_path: Path, masters: Path = MASTERS) -> bytes:
    """Return ``pkg_raw`` with each job's title stream replaced at the same cmp_len."""
    entries = tex_entries(pkg_raw, pkg_path)
    blob = bytearray(pkg_raw)
    for job in JOBS:
        if job not in entries:
            raise SystemExit(f"pkg {PKG}: Shop_TitTxt{job} missing")
        dec_len, is_cmp, cmp_len, cmp_off = entries[job]
        sharers = sorted(n for n, e in entries.items() if e[3] == cmp_off)
        if sharers != SHARED.get(job, [job]):
            raise SystemExit(f"Shop_TitTxt{job}: stream shared by {sharers}, expected {SHARED.get(job, [job])}")
        if not is_cmp or dec_len != SIZE[0] * SIZE[1]:
            raise SystemExit(f"Shop_TitTxt{job}: unexpected TEX entry (cmp={is_cmp}, dec_len={dec_len})")
        im = Image.open(masters / f"Shop_TitTxt{job}.png").convert("RGBA")
        if im.size != SIZE:
            raise SystemExit(f"Shop_TitTxt{job}.png is {im.size}, expected {SIZE}")
        old = zlib.decompress(pkg_raw[cmp_off : cmp_off + cmp_len])
        new = encode_etc1a4_pixels(im, *SIZE, keep=old)
        if job in FLAT:
            new = flat_colour(new, old, job)
        slot = try_compress_to_slot(new, cmp_len)
        if slot is None:
            raise SystemExit(f"Shop_TitTxt{job}.png does not fit its {cmp_len}-byte zlib slot")
        blob[cmp_off : cmp_off + cmp_len] = slot
        print(f"OK Shop_TitTxt{job} (slot {cmp_len}, {len(sharers)} title(s))", flush=True)
    return bytes(blob)


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    bak = maybe_backup_img(MOD_IMG, "shop_titles")
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    src_img = _vanilla_src()
    raw = src_img.read_bytes()
    img = ImgBin(str(src_img))
    img.parse(False)
    res = img.entries[PKG]
    if res is None:
        raise SystemExit(f"pkg {PKG} missing")
    pkg_raw = raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
    src = pkg_dir / f"vanilla_{PKG:04d}"
    src.write_bytes(pkg_raw)
    (pkg_dir / f"new_{PKG:04d}").write_bytes(patch_package(pkg_raw, src))

    try:
        for dest in _deploy_targets():
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
            print("spliced", PKG, "->", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed shop titles EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
