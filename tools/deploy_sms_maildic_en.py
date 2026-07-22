#!/usr/bin/env python3
"""Install English SMS maildic into LayeredFS img.bin (package 92).

Game storage (NOT romfs/dictionary/all2_u.bin — that is an IME font dict):

  img.bin package index **92** (uncompressed PACK, 142080 bytes)
    maildic_m.mdc  / maildic_n.mdc  / maildic_r.mdc   (MDC type)
    worddic_m.mdc  / worddic_n.mdc  / worddic_r.mdc   (left alone)

EN sources: assets/sms_en/maildic_{m,n,r}.en.xml (index-aligned with vanilla MDC).

Same-size: each MDC is rebuilt then padded with 0xFF back to the original
element length, then spliced in-place into the live LayeredFS img.bin.
No package rebuild / no zlib (elements are uncompressed).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))
sys.path.insert(0, str(ROOT / "src"))

from img import Image as ImgBin  # noqa: E402
from mdcutil import (  # noqa: E402
    apply_texts,
    pack_mdc,
    pad_to_size,
    parse_mdc,
    texts_from_dictionary_xml,
)
from deploy_common import (  # noqa: E402
    find_vanilla_img,
    iter_deploy_targets,
    resolve_img_paths,
)

PKG = 92
STEMS = ("maildic_m", "maildic_n", "maildic_r")
EN_DIR = ROOT / "assets" / "sms_en"
OUT = ROOT / "out" / "sms_mdc_en"
BAK_NAME = "img.bin.bak_pre_sms_maildic"


def load_pkg92(img_path: Path):
    im = ImgBin(str(img_path))
    im.parse(recursive=False)
    pak = im.entries[PKG]
    if pak is None:
        raise SystemExit(f"package {PKG} missing in {img_path}")
    pak.parse(recursive=False)
    return im, pak


def build_en_mdcs(pak) -> dict[str, bytes]:
    by_name = {e.fn: e for e in pak.entries}
    built: dict[str, bytes] = {}
    OUT.mkdir(parents=True, exist_ok=True)
    for stem in STEMS:
        fn = f"{stem}.mdc"
        elem = by_name[fn]
        jp_blob = elem.read()
        base = parse_mdc(jp_blob)
        en_xml = EN_DIR / f"{stem}.en.xml"
        if not en_xml.is_file():
            raise SystemExit(f"missing {en_xml}")
        texts = texts_from_dictionary_xml(en_xml)
        en_entries = apply_texts(base, texts)
        packed = pack_mdc(en_entries)
        padded = pad_to_size(packed, elem.fw.wlen, b"\xff")
        # verify parse of logical prefix
        assert len(parse_mdc(packed)) == len(base)
        out_path = OUT / fn
        out_path.write_bytes(padded)
        built[fn] = padded
        print(
            f"{fn}: jp={len(jp_blob)} en_raw={len(packed)} "
            f"padded={len(padded)} records={len(base)}"
        )
    return built


def splice_inplace(img_path: Path, built: dict[str, bytes], pak) -> None:
    data = bytearray(img_path.read_bytes())
    for elem in pak.entries:
        if elem.fn not in built:
            continue
        blob = built[elem.fn]
        off = elem.fw.base_offset
        ln = elem.fw.wlen
        if len(blob) != ln:
            raise SystemExit(f"{elem.fn}: len {len(blob)} != slot {ln}")
        data[off : off + ln] = blob
        print(f"  wrote {elem.fn} @ {off} ({ln} bytes)")
    img_path.write_bytes(data)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--img",
        type=Path,
        default=None,
        help="img.bin to patch (default: release bake / NLPP_DEPLOY_IMG)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="build padded MDCs only; do not write img.bin",
    )
    ap.add_argument(
        "--no-backup",
        action="store_true",
        help="skip img.bin.bak_pre_sms_maildic",
    )
    ap.add_argument(
        "--all-targets",
        action="store_true",
        help="also mirror into bake/Azahar when distinct from --img",
    )
    args = ap.parse_args()
    if args.img is None:
        primary, _ = resolve_img_paths()
        img_path = primary
    else:
        img_path = args.img.resolve()
    if not img_path.is_file():
        raise SystemExit(f"img.bin not found: {img_path}")

    vanilla = find_vanilla_img()
    # Prefer vanilla structure for JP base keys/meta when target already patched
    src_for_parse = vanilla if vanilla is not None else img_path
    print(f"reading package {PKG} from {src_for_parse}")
    _im, pak = load_pkg92(src_for_parse)
    built = build_en_mdcs(pak)

    if args.dry_run:
        print("dry-run: not writing img.bin")
        return

    targets = [img_path]
    if args.all_targets:
        for t in iter_deploy_targets(img_path):
            if t not in targets:
                targets.append(t)

    for dest in targets:
        _im2, pak2 = load_pkg92(dest)
        for e in pak.entries:
            if e.fn not in built:
                continue
            e2 = next(x for x in pak2.entries if x.fn == e.fn)
            if e2.fw.wlen != e.fw.wlen or e2.fw.base_offset != e.fw.base_offset:
                raise SystemExit(
                    f"offset/size mismatch for {e.fn} between parse src and {dest}"
                )

        bak = dest.parent / BAK_NAME
        if not args.no_backup and not bak.is_file():
            print(f"backup -> {bak}")
            shutil.copy2(dest, bak)
        elif bak.is_file():
            print(f"backup exists: {bak}")

        print(f"splicing into {dest}")
        splice_inplace(dest, built, pak2)
    print("done.")


if __name__ == "__main__":
    main()
