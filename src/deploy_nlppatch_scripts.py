#!/usr/bin/env python3
"""Deploy community (ex-NLPPATCH) English .dbin2 scripts to Azahar LayeredFS.

Source of truth (integrated into EngPatcher):
  rebuild_dbin2/script/*.dbin2 stems listed in assets/nlppatch/stems.json

Legacy fallback: vendor/NLPPATCH/release/romfs/script/bin/script/*.dbin2

Community scripts only cover the ``script`` pack (not NLP_01 / NLP_02).
After copy, dialog tokens are kept (nickname slots). Use ``--strip-dialog-tokens``
only for legacy testing.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from patch_names import patch_dbin2_tree  # noqa: F401 — legacy --strip-dialog-tokens
from script_inject import community_stems  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REBUILD = ROOT / "rebuild_dbin2" / "script"
LEGACY_SRC = (
    ROOT / "vendor" / "NLPPATCH" / "release" / "romfs" / "script" / "bin" / "script"
)
DEFAULT_SRC = DEFAULT_REBUILD
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


def resolve_src(src: Path) -> Path:
    if src.is_dir() and any(src.glob("*.dbin2")):
        return src
    if LEGACY_SRC.is_dir() and any(LEGACY_SRC.glob("*.dbin2")):
        return LEGACY_SRC
    raise SystemExit(
        "community scripts missing — expected rebuild_dbin2/script stems from "
        "assets/nlppatch/stems.json (or legacy vendor/NLPPATCH). "
        "Run: python tools/integrate_nlppatch_into_rebuild.py"
    )


def deploy(src_dir: Path, dest_dir: Path) -> int:
    src_dir = resolve_src(src_dir)
    allow = community_stems()
    files = sorted(src_dir.glob("*.dbin2"))
    if allow:
        files = [f for f in files if f.stem in allow]
    if not files:
        raise SystemExit(f"no community .dbin2 files in {src_dir}")
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
    print(f"[deploy] {n} community scripts -> {args.azahar}")

    if args.strip_dialog_tokens:
        touched, repl = patch_dbin2_tree(args.azahar.resolve(), strip_tokens=True)
        print(f"[names] strip: {touched} files, {repl} token replacements")
    else:
        print("[names] kept dialog tokens (nickname slots)")

    print("[done] Fully quit Azahar and relaunch to load new scripts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
