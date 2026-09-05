#!/usr/bin/env python3
"""Deploy vendored NLPPATCH English .dbin2 scripts to Azahar LayeredFS.

Source of truth (offline copy):
  vendor/NLPPATCH/release/romfs/script/bin/script/*.dbin2

NLPPATCH only translated the ``script`` pack (not NLP_01 / NLP_02).
After copy, dialog tokens are kept (nickname slots). Use ``--strip-dialog-tokens``
only for legacy testing.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from patch_names import patch_dbin2_tree  # noqa: F401 — legacy --strip-dialog-tokens

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = (
    ROOT / "vendor" / "NLPPATCH" / "release" / "romfs" / "script" / "bin" / "script"
)
AZAHAR_SCRIPT = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "Azahar"
    / "load"
    / "mods"
    / "00040000000F4E00"
    / "romfs"
    / "script"
    / "bin"
    / "script"
)


def deploy(src_dir: Path, dest_dir: Path) -> int:
    if not src_dir.is_dir():
        raise SystemExit(f"vendored NLPPATCH scripts missing: {src_dir}")
    files = sorted(src_dir.glob("*.dbin2"))
    if not files:
        raise SystemExit(f"no .dbin2 files in {src_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in files:
        shutil.copy2(src, dest_dir / src.name)
    return len(files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--azahar", type=Path, default=AZAHAR_SCRIPT)
    ap.add_argument(
        "--strip-dialog-tokens",
        action="store_true",
        help="legacy: expand ▲高嶺＊＊▲ to plain Takane after copy (breaks nicknames)",
    )
    args = ap.parse_args(argv)

    n = deploy(args.src.resolve(), args.azahar.resolve())
    print(f"[deploy] {n} scripts -> {args.azahar}")

    if args.strip_dialog_tokens:
        touched, repl = patch_dbin2_tree(args.azahar.resolve(), strip_tokens=True)
        print(f"[names] strip: {touched} files, {repl} token replacements")
    else:
        print("[names] kept dialog tokens (nickname slots)")

    print("[done] Fully quit Azahar and relaunch to load new scripts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
