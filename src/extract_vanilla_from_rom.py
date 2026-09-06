#!/usr/bin/env python3
"""Extract vanilla romfs/img.bin (+ TextResource TRBs + ExeFS code.bin) from a ROM.

Used when sibling New Love Plus Plus/extracted/ is absent — e.g. a clone that
only has the EngPatcher tree and the ROM the user dropped on the bat.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from nlpp_paths import (  # noqa: E402
    CACHE,
    CACHE_VANILLA_CODE,
    CACHE_VANILLA_EXEFS,
    find_vanilla_code,
    find_vanilla_img,
)
from patch_cia import (  # noqa: E402
    PatchError,
    _blz_uncompress,
    _require_tools,
    _unpack_exefs,
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
VANILLA_CODE = CACHE_VANILLA_CODE
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
    """True when img + main TRB + decompressed ExeFS code.bin are present."""
    if (
        not VANILLA_IMG.is_file()
        or not VANILLA_MAIN_TRB.is_file()
        or not VANILLA_CODE.is_file()
    ):
        return False
    if rom is None or not MARKER.is_file():
        return True
    return MARKER.read_text(encoding="utf-8").strip() == _rom_fingerprint(rom)


def _retry(op, *, attempts: int = 3, delay_s: float = 2.0, what: str):
    """Run ``op`` until it succeeds; raise after ``attempts`` failures."""
    last: BaseException | None = None
    for i in range(1, attempts + 1):
        try:
            return op()
        except (PatchError, OSError, FileNotFoundError, RuntimeError) as exc:
            last = exc
            print(
                f"[retry] {what} attempt {i}/{attempts} failed: {exc}",
                flush=True,
            )
            if i < attempts:
                time.sleep(delay_s * i)
    raise PatchError(f"{what} failed after {attempts} attempts: {last}") from last


def _write_decompressed_code(exefs_bin: Path, work: Path) -> Path:
    """Unpack ExeFS .code, BLZ-decompress → cache/vanilla_from_rom/exefs/code.bin."""
    exefs_dir = work / "exefs_unpack"
    code_cmp, _header = _unpack_exefs(exefs_bin, exefs_dir)
    CACHE_VANILLA_EXEFS.mkdir(parents=True, exist_ok=True)
    dest = VANILLA_CODE
    if dest.exists():
        dest.unlink()
    _blz_uncompress(code_cmp, dest)
    if not dest.is_file():
        raise PatchError(f"failed to write decompressed code.bin: {dest}")
    print(
        f"[vanilla] wrote {dest} ({dest.stat().st_size:,} bytes, BLZ-decompressed)",
        flush=True,
    )
    return dest.resolve()


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

    # ExeFS code.bin is required (Profile name-input). Keep retrying — never soft-skip.
    _retry(
        lambda: _write_decompressed_code(parts["exefs"], work),
        what="ExeFS code.bin extract",
    )
    if not VANILLA_CODE.is_file():
        raise PatchError(f"vanilla code.bin missing after extract: {VANILLA_CODE}")

    if slim:
        _slim_romfs(romfs_dir)

    MARKER.write_text(_rom_fingerprint(rom), encoding="utf-8")
    print(f"[vanilla] wrote {img} ({img.stat().st_size:,} bytes)", flush=True)
    print(f"[vanilla] wrote {trb.name}", flush=True)
    return img.resolve()


def ensure_vanilla_code_from_rom(rom: Path, *, force: bool = False) -> Path:
    """Return decompressed vanilla code.bin, extracting from ROM if needed."""
    rom = rom.resolve()
    fp = _rom_fingerprint(rom)

    if VANILLA_CODE.is_file() and not force:
        if not MARKER.is_file() or MARKER.read_text(encoding="utf-8").strip() == fp:
            return VANILLA_CODE.resolve()

    existing = find_vanilla_code()
    if existing is not None and not force and existing.resolve() != VANILLA_CODE.resolve():
        # Sibling dump / NLPP_VANILLA_CODE — fine for bake without re-extract.
        return existing

    if not VANILLA_IMG.is_file() or force:
        ensure_vanilla_from_rom(rom, force=force)
        if VANILLA_CODE.is_file():
            return VANILLA_CODE.resolve()

    # RomFS cache may predate ExeFS extract — pull code only.
    _require_tools()
    kind = detect_rom_kind(rom)
    work = ROOT / "out" / "extract_vanilla_code_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    cxi, _manual, _ver = prepare_cxi_from_rom(rom, work / "decrypt", kind=kind)
    parts = split_cxi(cxi, work / "ncch_parts")
    return _retry(
        lambda: _write_decompressed_code(parts["exefs"], work),
        what="ExeFS code.bin extract",
    )


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
        help="input decrypted .cia / .3ds / .cci",
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
