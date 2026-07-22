#!/usr/bin/env python3
"""Extract vanilla romfs/img.bin (+ TextResource TRBs) from a .cia / .3ds / .cci.

Used when sibling New Love Plus Plus/extracted/ is absent — e.g. a clone that
only has the EngPatcher tree and the ROM the user dropped on the bat.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from nlpp_paths import CACHE, find_vanilla_img  # noqa: E402
from patch_cia import (  # noqa: E402
    PatchError,
    _require_tools,
    detect_rom_kind,
    ensure_romfs_dir,
    prepare_cxi_from_rom,
    split_cxi,
)

VANILLA_ROOT = CACHE / "vanilla_from_rom"
VANILLA_ROMFS = VANILLA_ROOT / "romfs"
VANILLA_IMG = VANILLA_ROMFS / "img.bin"
VANILLA_MAIN_TRB = (
    VANILLA_ROMFS / "SystemData" / "TextResource" / "textresource_jpn.trb"
)
MARKER = VANILLA_ROOT / ".source_rom.txt"

# Keep these after extract so rebuild/deploys work without a multi-GB full tree
# sitting forever. Full tree is left in place when present (faster reuse).
KEEP_RELATIVE = (
    Path("img.bin"),
    Path("SystemData") / "TextResource" / "textresource_jpn.trb",
    Path("SystemData") / "TextResource" / "textresource_resident_jpn.trb",
    Path("SystemData") / "TextResource" / "textresource_config.trb",
)


def _rom_fingerprint(rom: Path) -> str:
    st = rom.stat()
    return f"{rom.resolve()}|{st.st_size}|{st.st_mtime_ns}"


def vanilla_cache_ready(rom: Path | None = None) -> bool:
    if not VANILLA_IMG.is_file() or not VANILLA_MAIN_TRB.is_file():
        return False
    if rom is None or not MARKER.is_file():
        return True
    return MARKER.read_text(encoding="utf-8").strip() == _rom_fingerprint(rom)


def ensure_vanilla_from_rom(
    rom: Path,
    *,
    force: bool = False,
    slim: bool = False,
) -> Path:
    """Decrypt/extract rom → cache/vanilla_from_rom/romfs; return img.bin path."""
    rom = rom.resolve()
    if not rom.is_file():
        raise FileNotFoundError(f"ROM not found: {rom}")

    if not force and vanilla_cache_ready(rom):
        print(f"[vanilla] reusing cached extract: {VANILLA_IMG}", flush=True)
        return VANILLA_IMG.resolve()

    _require_tools()
    kind = detect_rom_kind(rom)
    print(
        f"[vanilla] extracting img.bin + TextResource from {rom.name} ({kind}) ...",
        flush=True,
    )
    print(
        "[vanilla] first extract can take several minutes and needs a few GB free.",
        flush=True,
    )

    work = ROOT / "out" / "extract_vanilla_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    cxi, _manual, _ver = prepare_cxi_from_rom(rom, work / "decrypt", kind=kind)
    parts = split_cxi(cxi, work / "ncch_parts")

    if VANILLA_ROOT.exists():
        shutil.rmtree(VANILLA_ROOT)
    VANILLA_ROOT.mkdir(parents=True, exist_ok=True)

    romfs_dir = ensure_romfs_dir(parts["romfs"], VANILLA_ROMFS, reuse=None)
    img = romfs_dir / "img.bin"
    trb = romfs_dir / "SystemData" / "TextResource" / "textresource_jpn.trb"
    if not img.is_file():
        raise PatchError(f"RomFS extract missing img.bin under {romfs_dir}")
    if not trb.is_file():
        raise PatchError(
            f"RomFS extract missing textresource_jpn.trb under {romfs_dir}"
        )

    if slim:
        _slim_romfs(romfs_dir)

    MARKER.write_text(_rom_fingerprint(rom), encoding="utf-8")
    print(f"[vanilla] wrote {img} ({img.stat().st_size:,} bytes)", flush=True)
    print(f"[vanilla] wrote {trb.name}", flush=True)
    return img.resolve()


def _slim_romfs(romfs_dir: Path) -> None:
    """Drop everything except img.bin + TextResource TRBs to save disk."""
    staging = romfs_dir.parent / "_slim_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    for rel in KEEP_RELATIVE:
        src = romfs_dir / rel
        if not src.is_file():
            continue
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"[vanilla] keep {rel.as_posix()}", flush=True)
    shutil.rmtree(romfs_dir)
    staging.rename(romfs_dir)


def resolve_vanilla_img(*, rom: Path | None = None, force: bool = False) -> Path:
    """Prefer existing dump / env; else extract from rom when provided."""
    existing = find_vanilla_img()
    if existing is not None and not force:
        return existing
    if rom is None:
        raise FileNotFoundError(
            "vanilla romfs/img.bin not found.\n"
            "Provide one of:\n"
            "  • Drop a .cia / .3ds / .cci and pass --rom <path>\n"
            "  • Set NLPP_VANILLA_IMG to a vanilla img.bin\n"
            "  • Place a dump at sibling:\n"
            "      ../New Love Plus Plus/extracted/romfs/img.bin"
        )
    return ensure_vanilla_from_rom(rom, force=force)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--rom",
        type=Path,
        required=True,
        help="input .cia / .3ds / .cci (encrypted or decrypted)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="re-extract even if cache/vanilla_from_rom looks ready",
    )
    ap.add_argument(
        "--slim",
        action="store_true",
        help="keep only img.bin + TextResource TRBs (saves disk; not usable as --romfs)",
    )
    args = ap.parse_args(argv)
    try:
        img = ensure_vanilla_from_rom(
            args.rom, force=args.force, slim=args.slim
        )
    except (PatchError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {img}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
