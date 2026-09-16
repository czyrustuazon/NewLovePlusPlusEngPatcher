#!/usr/bin/env python3
"""Gold-bake A/B for the CESA thank-you pane.

A = current gold bake (English CESA + CESA_400X240 + idx 1576192)
B = same bake, pkg 90 restored to English CESA only (blank right pane, idx vanilla)

Both instances get vanilla code.bin so CesaLogo is not skipped.
Launch with: .\\make.ps1 launch-a   /   .\\make.ps1 launch-b
"""
from __future__ import annotations

import mmap
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from img import Image as ImgBin  # noqa: E402
from img import Package  # noqa: E402
from nlpp_paths import (  # noqa: E402
    BAKE_IMG,
    TITLE_ID,
    azahar_mod_root,
    find_vanilla_code,
    find_vanilla_img,
)
from patch_cesa import (  # noqa: E402
    BOTTOM_THANK_TEX_NAME,
    CESA_COMPANION_TEX_NAME,
    CESA_PKG_INDEX,
    CESA_TEX_NAME,
    COMPANION_TEX_H,
    COMPANION_TEX_W,
    ENTRY_SIZE,
    STUB_TEX_DEC_LEN,
    VANILLA_PKG90_DEC_LEN,
    _load_pkg90,
    patch_cesa_package_inplace,
    read_img_idx_dec_len,
    read_named_tex_from_pkg,
    set_img_idx_dec_len,
)

CESA_PNG = ROOT / "assets" / "images" / "cesa" / "CESA_240X400.png"
INSTANCES = ROOT / "out" / "azahar_instances"
COMPANION_DEC_LEN = VANILLA_PKG90_DEC_LEN + COMPANION_TEX_W * COMPANION_TEX_H * 3


def _instance_mod(letter: str) -> Path:
    user = INSTANCES / letter / "user"
    return azahar_mod_root(TITLE_ID, user_dir=user)


def _pkg90_slot(img_path: Path) -> tuple[int, int]:
    im = ImgBin(str(img_path))
    im.parse(False)
    try:
        res = im.entries[CESA_PKG_INDEX]
        if res is None:
            raise RuntimeError(f"{img_path} missing pkg {CESA_PKG_INDEX}")
        return res.fw.base_offset, res.fw.len()
    finally:
        im.fh.close()


def _splice_pkg90(dst: Path, pkg: bytes, idx_dec_len: int) -> None:
    base, slot = _pkg90_slot(dst)
    if len(pkg) != slot:
        raise RuntimeError(f"pkg 90 {len(pkg)} != dest slot {slot}")
    pack_dec = Package.parse_header(pkg[:ENTRY_SIZE])[5]
    if pack_dec != idx_dec_len:
        raise RuntimeError(f"PACK dec_len {pack_dec} != requested idx {idx_dec_len}")
    with dst.open("r+b") as fh:
        mm = mmap.mmap(fh.fileno(), 0)
        try:
            mm[base : base + slot] = pkg
            set_img_idx_dec_len(mm, CESA_PKG_INDEX, idx_dec_len)
            mm.flush()
        finally:
            mm.close()


def _copy_bake(dest_img: Path) -> None:
    dest_img.parent.mkdir(parents=True, exist_ok=True)
    print(f"[cesa-ab] copy bake -> {dest_img}", flush=True)
    shutil.copy2(BAKE_IMG, dest_img)


def _seed_vanilla_code(mod: Path, vanilla_code: Path) -> None:
    exefs = mod / "exefs"
    exefs.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vanilla_code, exefs / "code.bin")
    print(f"[cesa-ab] vanilla code.bin -> {exefs / 'code.bin'}", flush=True)


def _summarize(img_path: Path, label: str) -> None:
    idx = read_img_idx_dec_len(img_path.read_bytes(), CESA_PKG_INDEX)
    pkg = _load_pkg90(img_path)
    pack_dec = Package.parse_header(pkg[:ENTRY_SIZE])[5]
    cesa = read_named_tex_from_pkg(pkg, CESA_TEX_NAME)
    thank = read_named_tex_from_pkg(pkg, CESA_COMPANION_TEX_NAME)
    stub = read_named_tex_from_pkg(pkg, BOTTOM_THANK_TEX_NAME)
    print(
        f"[cesa-ab] {label}: idx={idx} pack={pack_dec} match={idx == pack_dec} "
        f"CESA={len(cesa)} CESA_400X240={len(thank)} "
        f"Bottom_Thank={len(stub)}",
        flush=True,
    )


def main() -> int:
    if not BAKE_IMG.is_file():
        raise SystemExit(f"missing gold bake: {BAKE_IMG}")
    vanilla_img = find_vanilla_img()
    if vanilla_img is None:
        raise SystemExit("vanilla img.bin not found (NLPP_VANILLA_IMG / extracted dump)")
    vanilla_code = find_vanilla_code()
    if vanilla_code is None:
        raise SystemExit("vanilla code.bin not found")
    if not CESA_PNG.is_file():
        raise SystemExit(f"missing {CESA_PNG}")
    if not (INSTANCES / "a" / "Launch-a.bat").is_file():
        raise SystemExit(
            "Azahar instances missing. From repo root run:\n"
            "  .\\make.ps1 instances"
        )

    mod_a = _instance_mod("a")
    mod_b = _instance_mod("b")
    img_a = mod_a / "romfs" / "img.bin"
    img_b = mod_b / "romfs" / "img.bin"

    _copy_bake(img_a)
    _seed_vanilla_code(mod_a, vanilla_code)
    _summarize(img_a, "A (bake + thank)")
    idx_a = read_img_idx_dec_len(img_a.read_bytes(), CESA_PKG_INDEX)
    pkg_a = _load_pkg90(img_a)
    thank_a = read_named_tex_from_pkg(pkg_a, CESA_COMPANION_TEX_NAME)
    stub_a = read_named_tex_from_pkg(pkg_a, BOTTOM_THANK_TEX_NAME)
    companion_tex = COMPANION_TEX_W * COMPANION_TEX_H * 3
    if idx_a != COMPANION_DEC_LEN or len(thank_a) != companion_tex:
        raise SystemExit(
            f"A bake is not the companion build (idx={idx_a}, CESA_400X240={len(thank_a)})"
        )
    if len(stub_a) != STUB_TEX_DEC_LEN:
        raise SystemExit(f"A Bottom_Thank should stay a stub, got {len(stub_a)}")

    _copy_bake(img_b)
    vanilla_pkg = _load_pkg90(vanilla_img)
    cesa_only = patch_cesa_package_inplace(vanilla_pkg, CESA_PNG)
    _splice_pkg90(img_b, cesa_only, VANILLA_PKG90_DEC_LEN)
    _seed_vanilla_code(mod_b, vanilla_code)
    _summarize(img_b, "B (CESA EN only)")
    thank_b = read_named_tex_from_pkg(_load_pkg90(img_b), CESA_COMPANION_TEX_NAME)
    if len(thank_b) != STUB_TEX_DEC_LEN:
        raise SystemExit(f"B CESA_400X240 should stay a stub, got {len(thank_b)}")

    print(
        "\nA/B ready. Boot both — A should show Thanks on the right pane; "
        "B should boot with English CESA and a blank white right pane.\n"
        "  .\\make.ps1 launch-a\n"
        "  .\\make.ps1 launch-b\n",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
