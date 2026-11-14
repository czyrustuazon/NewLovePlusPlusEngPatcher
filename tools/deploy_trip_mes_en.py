#!/usr/bin/env python3
"""EN trip date-picker message — raw ETC1A4 texture in img.bin pkg **5792**.

When an outing (旅行) is booked, the date picker shows a white box with
「旅行に行く日を選んでください。デートの予定が入っている日を選ぶとデートを
キャンセルして旅行に行く事ができます。」 baked into a texture, not the TRB.

  pkg 5792  TripMes_text00.texi  TEXI (82-byte meta) + TEX 256×128 ETC1A4
            (32768 bytes, zlib slot 4351)

The master ``assets/images/trip/TripMes_text00.png`` keeps the vanilla box
and redraws the text in English. It is encoded with the vanilla payload as
``keep`` (untouched 8×8 tiles stay byte-identical) and spliced at the same
``cmp_len``, like ``deploy_minigame_textures_en.py``; a master that does not
fit is an error. No other deploy writes this package.

  python tools/deploy_trip_mes_en.py
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

from bclimutil import encode_etc1a4_pixels  # noqa: E402
from img import Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import maybe_backup_img, resolve_img_paths  # noqa: E402
from deploy_minigame_textures_en import (  # noqa: E402
    _deploy_targets,
    _vanilla_src,
    try_compress_to_slot,
)

MOD_IMG, _FALLBACK_VANILLA = resolve_img_paths()
MASTER = ROOT / "assets" / "images" / "trip" / "TripMes_text00.png"
OUT = ROOT / "out" / "trip_mes_en"
PKG = 5792
NAME = "TripMes_text00.texi"
SIZE = (256, 128)


def _tex_entry(pkg_raw: bytes) -> tuple[int, tuple]:
    """(entry-table offset, parsed entry) of the package's only TEX element."""
    cnt = Package.parse_header(pkg_raw[: Package.ENTRY_SIZE])[1]
    hits = []
    for i in range(cnt):
        off = Package.ENTRY_SIZE * (1 + i)
        ent = Package.parse_entry(pkg_raw[off : off + Package.ENTRY_SIZE])
        if ent[0] == b"TEX ":
            hits.append((off, ent))
    if len(hits) != 1:
        raise SystemExit(f"pkg {PKG}: expected one TEX element, found {len(hits)}")
    return hits[0]


def encode_master(vanilla_tex: bytes, master: Path = MASTER) -> bytes:
    im = Image.open(master).convert("RGBA")
    if im.size != SIZE:
        raise SystemExit(f"{master.name} is {im.size}, expected {SIZE}")
    return encode_etc1a4_pixels(im, *SIZE, keep=vanilla_tex)


def patch_package(pkg_raw: bytes, master: Path = MASTER) -> bytes:
    """Return ``pkg_raw`` with the TEX payload replaced at the same cmp_len."""
    _off, (_typ, dec_len, _do, _fl, is_cmp, cmp_len, cmp_off) = _tex_entry(pkg_raw)
    if not is_cmp or dec_len != SIZE[0] * SIZE[1]:
        raise SystemExit(f"pkg {PKG}: unexpected TEX entry (cmp={is_cmp}, dec_len={dec_len})")
    old = zlib.decompress(pkg_raw[cmp_off : cmp_off + cmp_len])
    new = encode_master(old, master)
    slot = try_compress_to_slot(new, cmp_len)
    if slot is None:
        raise SystemExit(f"{master.name} does not fit the {cmp_len}-byte zlib slot")
    blob = bytearray(pkg_raw)
    blob[cmp_off : cmp_off + cmp_len] = slot
    d = zlib.decompressobj()
    if d.decompress(bytes(blob[cmp_off : cmp_off + cmp_len])) != new or d.unused_data or not d.eof:
        raise SystemExit("zlib slot not exact")
    return bytes(blob)


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    bak = maybe_backup_img(MOD_IMG, "trip_mes")
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
    print(f"pkg {PKG} from {src_img}", flush=True)
    (pkg_dir / f"new_{PKG:04d}").write_bytes(patch_package(pkg_raw))

    try:
        for dest in _deploy_targets():
            splice_packages_into_img(dest, pkg_dir, [PKG], dest)
            print("spliced", PKG, "->", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed trip message EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
