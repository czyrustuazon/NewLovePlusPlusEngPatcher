#!/usr/bin/env python3
"""Combine Bleeding-Edge gold bake UI with the verified Profile name-input stack.

LayeredFS layout written:

  romfs/img.bin              <- release/bake_img.bin   (EN chrome)
  romfs/.../textresource_*   <- name-kanji TRB          (keeps gojūon JP)
  exefs/code.bin             <- release/name_input_code.bin (romaji stack)

This is the isolated a/b name-input proof + bake UI — not bake TRB alone
(full EN TRB blanks the Profile keyboard).

  # Roaming Azahar
  python tools/deploy_bleeding_edge_name_input.py

  # Instance A / B (same as make.ps1)
  set NLPP_AZAHAR_USER_DIR=...\\out\\azahar_instances\\a\\user
  python tools/deploy_bleeding_edge_name_input.py

  # Rebuild name_input_code.bin / namekanji TRB first if stale:
  python tools/deploy_bleeding_edge_name_input.py --refresh-artifacts
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nlpp_paths import (  # noqa: E402
    AZAHAR_MOD_CODE,
    AZAHAR_MOD_IMG,
    AZAHAR_MOD_ROOT,
    AZAHAR_MOD_TRB_DIR,
    BAKE_IMG,
    NAME_INPUT_CODE,
    TEXTRESOURCE,
    find_vanilla_code,
)


def _run(argv: list[str]) -> None:
    print("\n==>", " ".join(argv), flush=True)
    subprocess.run(argv, check=True, cwd=str(ROOT))


def refresh_artifacts(*, vanilla_code: Path | None) -> None:
    """Rebuild name_input_code.bin + name-kanji TRB into release/."""
    from extract_vanilla_from_rom import ensure_vanilla_code_from_rom  # noqa: PLC0415

    src = vanilla_code or find_vanilla_code()
    bak = (
        ROOT.parent
        / "New Love Plus Plus"
        / "extracted"
        / "exefs"
        / "code.bin.bak"
    )
    if bak.is_file():
        src = bak
    if src is None or not Path(src).is_file():
        raise SystemExit(
            "vanilla code.bin / code.bin.bak not found for name-input rebuild"
        )

    _run(
        [
            sys.executable,
            str(ROOT / "tools" / "deploy_name_input_en.py"),
            "--src",
            str(src),
            "--out",
            str(NAME_INPUT_CODE),
        ]
    )
    _run([sys.executable, str(ROOT / "tools" / "deploy_name_kanji_trb.py")])
    namekanji = ROOT / "out" / "textresource_jpn_namekanji.trb"
    cfg = ROOT / "out" / "textresource_config_namekanji.trb"
    TEXTRESOURCE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(namekanji, TEXTRESOURCE / "textresource_jpn.trb")
    if cfg.is_file():
        shutil.copy2(cfg, TEXTRESOURCE / "textresource_config.trb")
    # RomFS overlay used by drop-bat / patch_cia
    overlay = ROOT / "release" / "romfs_overlay" / "SystemData" / "TextResource"
    overlay.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEXTRESOURCE / "textresource_jpn.trb", overlay / "textresource_jpn.trb")
    if (TEXTRESOURCE / "textresource_config.trb").is_file():
        shutil.copy2(
            TEXTRESOURCE / "textresource_config.trb",
            overlay / "textresource_config.trb",
        )
    print(f"[combine] refreshed {NAME_INPUT_CODE.name} + name-kanji TRB", flush=True)


def deploy_combined(*, also_code_bak: bool = True) -> None:
    if not BAKE_IMG.is_file():
        raise SystemExit(f"missing gold bake: {BAKE_IMG}\nRun rebuild_bake_img.py first.")
    if not NAME_INPUT_CODE.is_file():
        raise SystemExit(
            f"missing {NAME_INPUT_CODE}\n"
            "Run with --refresh-artifacts or rebuild_bake_img.py"
        )
    trb = TEXTRESOURCE / "textresource_jpn.trb"
    namekanji = ROOT / "out" / "textresource_jpn_namekanji.trb"
    if namekanji.is_file():
        src_trb = namekanji
    elif trb.is_file():
        src_trb = trb
    else:
        raise SystemExit(
            "missing name-kanji TRB (out/textresource_jpn_namekanji.trb). "
            "Run --refresh-artifacts."
        )

    mod = AZAHAR_MOD_ROOT
    exefs = mod / "exefs"
    romfs = mod / "romfs"
    trb_dir = AZAHAR_MOD_TRB_DIR
    exefs.mkdir(parents=True, exist_ok=True)
    romfs.mkdir(parents=True, exist_ok=True)
    trb_dir.mkdir(parents=True, exist_ok=True)

    dest_img = AZAHAR_MOD_IMG
    if dest_img.is_file():
        bak = dest_img.with_name(dest_img.name + ".bak_pre_combine_name_input")
        if not bak.is_file():
            shutil.copy2(dest_img, bak)
            print(f"[combine] bak img -> {bak.name}", flush=True)
    shutil.copy2(BAKE_IMG, dest_img)
    print(f"[combine] img <- bake ({BAKE_IMG.stat().st_size:,} bytes)", flush=True)

    dest_code = AZAHAR_MOD_CODE
    if also_code_bak and dest_code.is_file():
        bak = dest_code.with_name(dest_code.name + ".bak_pre_combine_name_input")
        if not bak.is_file():
            shutil.copy2(dest_code, bak)
            print(f"[combine] bak code -> {bak.name}", flush=True)
    shutil.copy2(NAME_INPUT_CODE, dest_code)
    # Azahar also loads mods/<tid>/code.bin (mod root). Stale root with scrapped
    # 0x006FC000 caves blanks the Profile keyboard while exefs looks fine.
    root_code = mod / "code.bin"
    shutil.copy2(NAME_INPUT_CODE, root_code)
    print(f"[combine] code <- {NAME_INPUT_CODE.name} (exefs + mod root)", flush=True)

    dest_trb = trb_dir / "textresource_jpn.trb"
    if dest_trb.is_file():
        bak = dest_trb.with_suffix(dest_trb.suffix + ".bak_pre_combine_name_input")
        if not bak.is_file():
            shutil.copy2(dest_trb, bak)
    shutil.copy2(src_trb, dest_trb)
    cfg_src = ROOT / "out" / "textresource_config_namekanji.trb"
    if not cfg_src.is_file():
        cfg_src = TEXTRESOURCE / "textresource_config.trb"
    if cfg_src.is_file():
        shutil.copy2(cfg_src, trb_dir / "textresource_config.trb")
    print(f"[combine] TRB <- name-kanji ({src_trb.name})", flush=True)

    print(f"[combine] OK -> {mod}", flush=True)
    print("Launch this Azahar user dir; open Profile → First Name.", flush=True)
    print(
        "Expect: bake EN chrome + Hepburn/ABC keys (not empty checkerboard).",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--refresh-artifacts",
        action="store_true",
        help="rebuild name_input_code.bin + name-kanji TRB before deploy",
    )
    ap.add_argument(
        "--vanilla-code",
        type=Path,
        default=None,
        help="vanilla code.bin (default: extracted code.bin.bak)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print target paths only",
    )
    args = ap.parse_args(argv)

    print(f"[combine] Azahar mod root: {AZAHAR_MOD_ROOT}")
    print(f"[combine] NLPP_AZAHAR_USER_DIR={os.environ.get('NLPP_AZAHAR_USER_DIR', '')!r}")
    if args.dry_run:
        print(f"  would write img  <- {BAKE_IMG}")
        print(f"  would write code <- {NAME_INPUT_CODE}")
        print(f"  would write TRB  <- name-kanji")
        return 0

    if args.refresh_artifacts:
        refresh_artifacts(vanilla_code=args.vanilla_code)

    deploy_combined()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
