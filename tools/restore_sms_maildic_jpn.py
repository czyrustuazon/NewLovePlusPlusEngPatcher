#!/usr/bin/env python3
"""Restore Japanese SMS maildic (package 92) from vanilla img.bin.

Use after removing English SMS translation to audit nickname placeholders
(▲高嶺＊＊▲ etc.) in in-game text messages.
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
from deploy_common import (  # noqa: E402
    find_vanilla_img,
    iter_deploy_targets,
    resolve_img_paths,
)

PKG = 92
STEMS = ("maildic_m", "maildic_n", "maildic_r")
BAK_NAME = "img.bin.bak_pre_sms_restore_jpn"


def load_pkg92(img_path: Path):
    im = ImgBin(str(img_path))
    im.parse(recursive=False)
    pak = im.entries[PKG]
    if pak is None:
        raise SystemExit(f"package {PKG} missing in {img_path}")
    pak.parse(recursive=False)
    return pak


def restore_maildic(vanilla_img: Path, target_img: Path) -> int:
    vpak = load_pkg92(vanilla_img)
    tpak = load_pkg92(target_img)
    vby = {e.fn: e for e in vpak.entries}
    data = bytearray(target_img.read_bytes())
    n = 0
    for stem in STEMS:
        fn = f"{stem}.mdc"
        if fn not in vby:
            raise SystemExit(f"{fn} missing in vanilla {vanilla_img}")
        te = next((e for e in tpak.entries if e.fn == fn), None)
        if te is None:
            raise SystemExit(f"{fn} missing in target {target_img}")
        blob = vby[fn].read()
        if len(blob) > te.fw.wlen:
            raise SystemExit(f"{fn}: vanilla {len(blob)} > slot {te.fw.wlen}")
        padded = blob + b"\xff" * (te.fw.wlen - len(blob))
        off = te.fw.base_offset
        data[off : off + te.fw.wlen] = padded
        print(f"  {fn}: {len(blob)} bytes -> {target_img.name} @ {off}")
        n += 1
    target_img.write_bytes(data)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vanilla", type=Path, default=None, help="vanilla img.bin")
    ap.add_argument("--img", type=Path, default=None, help="target img.bin")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument(
        "--all-targets",
        action="store_true",
        help="also restore bake + Azahar when distinct from --img",
    )
    args = ap.parse_args()

    vanilla = args.vanilla or find_vanilla_img()
    if vanilla is None or not vanilla.is_file():
        raise SystemExit("vanilla img.bin not found (set --vanilla or NLPP_VANILLA_IMG)")

    if args.img is None:
        primary, _ = resolve_img_paths()
        img_path = primary
    else:
        img_path = args.img.resolve()
    if not img_path.is_file():
        raise SystemExit(f"target img.bin not found: {img_path}")

    targets = [img_path]
    if args.all_targets:
        for t in iter_deploy_targets(img_path):
            if t not in targets:
                targets.append(t)

    print(f"vanilla: {vanilla}")
    for dest in targets:
        bak = dest.parent / BAK_NAME
        if not args.no_backup and not bak.is_file():
            print(f"backup -> {bak}")
            shutil.copy2(dest, bak)
        print(f"restore JP maildic in {dest}")
        restore_maildic(vanilla, dest)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
