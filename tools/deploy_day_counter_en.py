#!/usr/bin/env python3
"""EN play-day counter suffix: 日目 → ' Day  ' in resident TRB + img.bin pkg 5508.

HUD format is: {n} + 日目 + (weekday)  e.g. 18日目(月) → 18 Day  (Mon)

Weekday slots ((Mon)/(Tue)/…) are already EN in the resident TRB;
pkg 5508 is a raw duplicate of that TRB inside img.bin and must stay in sync.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from img import Image as ImgBin  # noqa: E402
from pack_images import splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    OVERLAY_TRB_DIR,
    TEXTRESOURCE,
    iter_deploy_targets,
    resolve_img_paths,
    resolve_resident_trb,
)

MOD_IMG, _VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "day_counter_en"  # scratch only

# Same-size TOP slot at 0x674 (UTF-8 日目 is 6 bytes).
DAY_SUFFIX_OFF = 0x674
DAY_SUFFIX_JP = "日目".encode("utf-8")
DAY_SUFFIX_EN = b" Day  "  # → "18 Day  (Mon)"
assert len(DAY_SUFFIX_JP) == len(DAY_SUFFIX_EN) == 6

RESIDENT_PKG = 5508
DURABLE_TRBS = [
    TEXTRESOURCE / "textresource_resident_jpn.trb",
    OVERLAY_TRB_DIR / "textresource_resident_jpn.trb",
]


def patch_trb_bytes(data: bytearray) -> bool:
    if data[DAY_SUFFIX_OFF : DAY_SUFFIX_OFF + 6] == DAY_SUFFIX_EN:
        return False
    if data[DAY_SUFFIX_OFF : DAY_SUFFIX_OFF + 6] != DAY_SUFFIX_JP:
        raise SystemExit(
            f"unexpected bytes at 0x674: {bytes(data[DAY_SUFFIX_OFF:DAY_SUFFIX_OFF+6])!r}"
        )
    data[DAY_SUFFIX_OFF : DAY_SUFFIX_OFF + 6] = DAY_SUFFIX_EN
    return True


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

    src_trb = resolve_resident_trb()
    bak_trb = src_trb.with_suffix(".trb.bak_pre_day_suffix")
    if not bak_trb.is_file():
        bak_trb.write_bytes(src_trb.read_bytes())
        print("created", bak_trb, flush=True)

    blob = bytearray(src_trb.read_bytes())
    if patch_trb_bytes(blob):
        src_trb.write_bytes(blob)
        print(f"patched resident TRB 日目 -> ' Day  ' ({src_trb})", flush=True)
    else:
        print(f"resident TRB already has Day suffix ({src_trb})", flush=True)

    trb_live = src_trb.read_bytes()
    for p in DURABLE_TRBS:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(trb_live)
        print("wrote", p, flush=True)

    bak_img = MOD_IMG.with_suffix(".bin.bak_pre_day_counter")
    if not bak_img.is_file():
        bak_img.write_bytes(MOD_IMG.read_bytes())
        print("created", bak_img, flush=True)

    if len(trb_live) != 223280:
        raise SystemExit(f"unexpected resident TRB size {len(trb_live)}")
    if trb_live[DAY_SUFFIX_OFF : DAY_SUFFIX_OFF + 6] != DAY_SUFFIX_EN:
        raise SystemExit("TRB missing Day suffix after patch")

    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / f"{RESIDENT_PKG:04d}").write_bytes(trb_live)
    (pkg_dir / f"new_{RESIDENT_PKG:04d}").write_bytes(trb_live)
    for dest in iter_deploy_targets(MOD_IMG):
        splice_packages_into_img(dest, pkg_dir, [RESIDENT_PKG], dest)

    raw = MOD_IMG.read_bytes()
    img = ImgBin(str(MOD_IMG))
    img.parse(False)
    ent = img.entries[RESIDENT_PKG]
    got = raw[ent.fw.base_offset : ent.fw.base_offset + ent.fw.len()]
    if got[DAY_SUFFIX_OFF : DAY_SUFFIX_OFF + 6] != DAY_SUFFIX_EN:
        raise SystemExit("img.bin pkg 5508 verify failed")
    print(
        f"deployed day counter EN -> pkg {RESIDENT_PKG} + resident TRB",
        flush=True,
    )
    print("Rollback TRB:", bak_trb, flush=True)
    print("Rollback img:", bak_img, flush=True)


if __name__ == "__main__":
    main()
