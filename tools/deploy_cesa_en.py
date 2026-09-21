#!/usr/bin/env python3
"""EN boot CESA warning + second-screen thank-you — img.bin package 90.

CESA_240X400.texi is the portrait warning. The white pane beside it is
CesaLogo +0x64 → logo_white.texi (constructor ID 0x5A0008, vanilla 16×16
white stub). CESA_400X240 / Bottom_Thank / ProductionLogo_320X240 stay stubs.

Rebuild pkg 90 from vanilla so a previous companion grow is undone.
Gold path splices a same-size PACK into release/bake_img.bin.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from patch_cesa import (  # noqa: E402
    patch_img_bin_with_companion,
    sync_img_pkg90_idx_to_pack,
)
from nlpp_paths import find_vanilla_img  # noqa: E402

from deploy_common import maybe_backup_img, iter_deploy_targets, resolve_img_paths  # noqa: E402
from render_cesa_en import render_cesa_companion_en, render_cesa_en  # noqa: E402

MOD_IMG, _FALLBACK_VANILLA = resolve_img_paths()
CESA_PNG = ROOT / "assets" / "images" / "cesa" / "CESA_240X400.png"
COMPANION_PNG = ROOT / "assets" / "images" / "cesa" / "logo_white.png"
OUT = ROOT / "out" / "cesa_en"


def _vanilla_pkg90_src(dest: Path) -> Path:
    """Vanilla pkg 90 — not dest, which may still have the old Bottom_Thank fill."""
    vanilla = find_vanilla_img()
    if vanilla is not None and vanilla.resolve() != dest.resolve():
        return vanilla.resolve()
    bak = dest.with_suffix(".bin.bak_pre_cesa")
    if bak.is_file() and bak.resolve() != dest.resolve():
        return bak.resolve()
    if _FALLBACK_VANILLA.resolve() != dest.resolve():
        return _FALLBACK_VANILLA.resolve()
    raise SystemExit(
        "CESA companion rebuild needs a vanilla img.bin "
        "(NLPP_VANILLA_IMG) so leftover companion slots can return to stubs."
    )


def _refresh_pngs() -> None:
    """Rebuild CESA + logo_white masters from NLPPPATCH Heisei Gothic."""
    try:
        im = render_cesa_en()
        CESA_PNG.parent.mkdir(parents=True, exist_ok=True)
        im.save(CESA_PNG)
        print(f"[cesa] rendered {CESA_PNG}", flush=True)
        companion = render_cesa_companion_en()
        companion.save(COMPANION_PNG)
        print(f"[cesa] rendered {COMPANION_PNG}", flush=True)
    except (SystemExit, OSError, RuntimeError) as exc:
        if CESA_PNG.is_file() and COMPANION_PNG.is_file():
            print(f"[cesa] render skipped ({exc}); using existing PNGs", flush=True)
            return
        raise


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    _refresh_pngs()
    if not CESA_PNG.is_file() or not COMPANION_PNG.is_file():
        print("[warn] missing CESA PNGs — skipping CESA EN", flush=True)
        return 0

    bak = maybe_backup_img(MOD_IMG, "cesa")

    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "work"
    work.mkdir(parents=True, exist_ok=True)

    vanilla = find_vanilla_img()
    if vanilla is None:
        print("[cesa] no vanilla img.bin; rebuilding from dest (dirty TEXIs possible)", flush=True)

    # Fast: if the companion PACK is already in place, only the idx arena was
    # stale (boot heap smash). Sync that before the slower zopfli rebuild.
    for dest in iter_deploy_targets(MOD_IMG):
        sync_img_pkg90_idx_to_pack(dest)

    # Patch each deploy target in place (bake first). Rebuild from vanilla
    # pkg 90 so logo_white gets the blurb and other stubs stay stubs.
    for dest in iter_deploy_targets(MOD_IMG):
        vanilla = _vanilla_pkg90_src(dest)
        print(f"[cesa] patching {dest} (pkg90 from {vanilla})", flush=True)
        patch_img_bin_with_companion(
            dest,
            CESA_PNG,
            COMPANION_PNG,
            dest,
            work=work / dest.stem,
            vanilla_img=vanilla,
        )

    print("deployed CESA EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    print("Fully quit Azahar after testing — wrong zlib used to white-boot.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
