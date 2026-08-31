#!/usr/bin/env python3
"""Restore Profile name-input baseline in Azahar LayeredFS.

Uses backups beside the live files when present; otherwise copies vanilla
exefs/code.bin from the dump. Honors NLPP_AZAHAR_USER_DIR / AZAHAR_USER_DIR.

  python tools/restore_name_input_baseline.py
  $env:NLPP_AZAHAR_USER_DIR = '...\\out\\azahar_instances\\a\\user'
  python tools/restore_name_input_baseline.py
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nlpp_paths import (  # noqa: E402
    AZAHAR_MOD_CODE,
    AZAHAR_MOD_ROOT,
    AZAHAR_MOD_TRB_DIR,
    require_vanilla_code,
)

TRB_RESTORES = (
    ("textresource_jpn.trb", ".bak_pre_namekanji"),
    ("textresource_config.trb", ".bak_pre_namekanji"),
)


def _trb_backup(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".bak_pre_namekanji")


def restore_code(*, dry_run: bool = False) -> None:
    dest = AZAHAR_MOD_CODE
    candidates = [
        dest.with_name("code.bin.bak_pre_name_input_en"),
        dest.with_name("code.bin.bak_pre_kana_direct"),
    ]
    src = next((p for p in candidates if p.is_file()), None)
    if src is None:
        src = require_vanilla_code()
        print(f"[restore] no backup — using vanilla {src}")
    else:
        print(f"[restore] code.bin <= {src}")
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    shutil.copy2(src, AZAHAR_MOD_ROOT / "code.bin")


def restore_trbs(*, dry_run: bool = False) -> None:
    for name, _suffix in TRB_RESTORES:
        dest = AZAHAR_MOD_TRB_DIR / name
        bak = _trb_backup(dest)
        if not bak.is_file():
            if dest.is_file():
                print(f"[skip] no backup for {dest.name}")
            continue
        print(f"[restore] {name} <= {bak}")
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bak, dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--code-only", action="store_true")
    args = ap.parse_args(argv)
    restore_code(dry_run=args.dry_run)
    if not args.code_only:
        restore_trbs(dry_run=args.dry_run)
    if not args.dry_run:
        print("Restored. Relaunch Azahar to pick up LayeredFS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
