#!/usr/bin/env python3
"""Rebuild out/NewLovePlusPlus-EN.cia from the verified name-input stack.

Typical loop:

  1. python tools/deploy_name_input_en.py   # or .\\make.ps1 deploy-a
  2. Test in Azahar LayeredFS
  3. python tools/rebuild_test_cia.py
  4. Install out/NewLovePlusPlus-EN.cia via FBI

ROM path (first match): --rom, NLPP_ROM env, release/source_rom.txt, sibling CIA.

  python tools/rebuild_test_cia.py
  python tools/rebuild_test_cia.py --rom "path\\to\\game.cia"
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
    BAKE_IMG,
    require_vanilla_code,
)
from patch_input_candidate_nullguard import apply_patch as apply_cand_nullguard  # noqa: E402
from patch_input_candmode_fillflag_reset import apply_patch as apply_fillflag  # noqa: E402
from patch_input_kana_direct_insert import (  # noqa: E402
    apply_patch as apply_kana_direct,
    restore_bind_sites,
)
from patch_input_pane_registry_nullguard import apply_patch as apply_pane_nullguard  # noqa: E402
from patch_input_romaji import patch_input_romaji  # noqa: E402

OUT_CIA = ROOT / "out" / "NewLovePlusPlus-EN.cia"
SOURCE_ROM_FILE = ROOT / "release" / "source_rom.txt"
NAME_INPUT_CODE = ROOT / "release" / "name_input_code.bin"
PATCH_CIA = ROOT / "src" / "patch_cia.py"

DEFAULT_ROM_CANDIDATES = (
    ROOT.parent
    / "New Love Plus Plus"
    / "New-Love-Plus-Plus by headmasta [9F86E7DC].cia",
    ROOT.parent / "New Love Plus Plus" / "NewLovePlusPlus-decrypted.cia",
)


def resolve_rom(explicit: Path | None) -> Path:
    if explicit is not None:
        p = explicit.resolve()
        if not p.is_file():
            raise SystemExit(f"--rom not found: {p}")
        return p

    env = os.environ.get("NLPP_ROM")
    if env:
        p = Path(env).resolve()
        if p.is_file():
            return p

    if SOURCE_ROM_FILE.is_file():
        line = SOURCE_ROM_FILE.read_text(encoding="utf-8").strip()
        if line:
            p = Path(line).expanduser().resolve()
            if p.is_file():
                return p

    for c in DEFAULT_ROM_CANDIDATES:
        if c.is_file():
            return c.resolve()

    raise SystemExit(
        "no ROM found — pass --rom path\\to\\game.cia|.3ds|.cci\n"
        f"or save the path in {SOURCE_ROM_FILE}"
    )


def resolve_img() -> Path:
    """Prefer live Azahar mod img (latest splices), else gold bake."""
    if AZAHAR_MOD_IMG.is_file():
        if not BAKE_IMG.is_file() or AZAHAR_MOD_IMG.stat().st_mtime >= BAKE_IMG.stat().st_mtime:
            print(f"[img] using Azahar mod {AZAHAR_MOD_IMG}")
            return AZAHAR_MOD_IMG.resolve()
    if BAKE_IMG.is_file():
        print(f"[img] using bake {BAKE_IMG}")
        return BAKE_IMG.resolve()
    raise SystemExit(f"no img.bin — deploy UI packages or create {BAKE_IMG}")


def _patch_vanilla_code() -> bytes:
    src = require_vanilla_code()
    print(f"[code] patching vanilla {src}")
    data = bytearray(src.read_bytes())
    apply_pane_nullguard(data)
    apply_cand_nullguard(data)
    apply_fillflag(data)
    if not patch_input_romaji(data, force=True):
        raise SystemExit("romaji patch failed")
    restore_bind_sites(data)
    apply_kana_direct(data)
    return bytes(data)


def build_name_input_code(out: Path, *, from_vanilla: bool = False) -> None:
    """Prefer deployed Azahar mod code.bin; else patch vanilla."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if not from_vanilla and AZAHAR_MOD_CODE.is_file():
        print(f"[code] copying deployed mod {AZAHAR_MOD_CODE}")
        shutil.copy2(AZAHAR_MOD_CODE, out)
        return
    out.write_bytes(_patch_vanilla_code())
    print(f"[code] wrote {out}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=None, help="source .cia / .3ds / .cci")
    ap.add_argument("--out", type=Path, default=OUT_CIA, help="output CIA path")
    ap.add_argument("--skip-hash", action="store_true", help="pass --skip-hash to patch_cia")
    ap.add_argument(
        "--rebuild-code",
        action="store_true",
        help="always patch from vanilla (ignore Azahar mod code.bin)",
    )
    args = ap.parse_args(argv)

    rom = resolve_rom(args.rom)
    SOURCE_ROM_FILE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_ROM_FILE.write_text(str(rom) + "\n", encoding="utf-8")
    print(f"[rom] {rom}")

    build_name_input_code(NAME_INPUT_CODE, from_vanilla=args.rebuild_code)
    if not NAME_INPUT_CODE.is_file():
        raise SystemExit(f"missing {NAME_INPUT_CODE}")
    img = resolve_img()
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(PATCH_CIA),
        "--cia",
        str(rom),
        "--out",
        str(out),
        "--inject-code",
        str(NAME_INPUT_CODE),
        "--packed-img",
        str(img),
        "--layeredfs-out",
        str(ROOT / "out" / "luma"),
    ]
    if args.skip_hash:
        cmd.append("--skip-hash")

    print("[cia] rebuilding (several minutes) ...")
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    subprocess.check_call(cmd, cwd=ROOT, env=env)
    print(f"\n[done] {out}")
    print("Install with FBI in Azahar, then launch the CIA title.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
