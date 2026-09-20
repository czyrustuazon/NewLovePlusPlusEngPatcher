#!/usr/bin/env python3
"""Install a Checkpoint / Azahar NLPP title save into an Azahar user dir.

NLPP's playable slot is SD save data (not NAND .sav, not extra data):

  sdmc/Nintendo 3DS/<ID0>/<ID1>/title/00040000/000f4e00/data/00000001/savedata*

Packs live under ab_test/saves/<id>/ (extracted). A zip with the same
00000001/savedata* layout also works.

  python tools/import_azahar_save.py --list
  python tools/import_azahar_save.py --pack nene
  python tools/import_azahar_save.py --pack nene --user-dir out/azahar_instances/a/user
  python tools/import_azahar_save.py --zip path/to/save.zip

Existing title-save files (only) are snapshotted under out/extdata_backup/
unless --no-backup. Extra data / DLC caches are left alone.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from nlpp_paths import TITLE_ID, azahar_user_dir  # noqa: E402
from restore_azahar_extdata import (  # noqa: E402
    DEFAULT_BACKUP_ROOT,
    TITLE_HIGH,
    TITLE_LOW,
    backup_trees,
    discover_sd_title_saves,
)

DEFAULT_SAVES_ROOT = ROOT / "ab_test" / "saves"
DEFAULT_PACK = "nene"
AZAHAR_DEFAULT_ID = "0" * 32
SAVE_DIR_NAME = "00000001"
METADATA_NAME = "00000001.metadata"
SAVEDATA0 = "savedata0"
# Live Azahar format for this title: 256 KiB, 1 dir, 81 files, duplicate_data=1.
DEFAULT_METADATA = bytes.fromhex("00000400010000005100000001000000")


def find_save_slot(root: Path) -> Path:
    """Directory that contains savedata0 (usually 00000001/)."""
    direct = root / SAVEDATA0
    if direct.is_file():
        return root
    nested = root / SAVE_DIR_NAME / SAVEDATA0
    if nested.is_file():
        return nested.parent
    hits = sorted(p.parent for p in root.rglob(SAVEDATA0) if p.is_file())
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise FileNotFoundError(f"no {SAVEDATA0} under {root}")
    raise FileNotFoundError(
        f"multiple {SAVEDATA0} under {root}: " + ", ".join(str(p) for p in hits)
    )


def iter_savedata_files(slot: Path) -> list[Path]:
    files = [
        p
        for p in slot.iterdir()
        if p.is_file() and p.name.startswith("savedata") and not p.name.endswith(".bak")
    ]
    files.sort(key=lambda p: p.name)
    if not files:
        raise FileNotFoundError(f"no savedata* files in {slot}")
    return files


def load_pack_manifest(pack_dir: Path) -> dict:
    path = pack_dir / "manifest.json"
    if not path.is_file():
        return {"id": pack_dir.name}
    return json.loads(path.read_text(encoding="utf-8"))


def list_packs(saves_root: Path) -> list[Path]:
    if not saves_root.is_dir():
        return []
    packs = []
    for child in sorted(saves_root.iterdir()):
        if not child.is_dir():
            continue
        try:
            find_save_slot(child)
        except FileNotFoundError:
            continue
        packs.append(child)
    return packs


def extract_zip(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    return find_save_slot(dest)


def nintendo_3ds_ids(user_dir: Path) -> tuple[str, str]:
    """Reuse the instance's ID0/ID1 when present; else Azahar's all-zero defaults."""
    sdmc = user_dir / "sdmc" / "Nintendo 3DS"
    if not sdmc.is_dir():
        return AZAHAR_DEFAULT_ID, AZAHAR_DEFAULT_ID
    id0s = sorted(p for p in sdmc.iterdir() if p.is_dir() and len(p.name) == 32)
    preferred: list[tuple[str, str]] = []
    others: list[tuple[str, str]] = []
    for id0 in id0s:
        id1s = sorted(p for p in id0.iterdir() if p.is_dir() and len(p.name) == 32)
        for id1 in id1s:
            pair = (id0.name, id1.name)
            title = id1 / "title" / TITLE_HIGH / TITLE_LOW
            (preferred if title.is_dir() else others).append(pair)
    if preferred:
        return preferred[0]
    if others:
        return others[0]
    return AZAHAR_DEFAULT_ID, AZAHAR_DEFAULT_ID


def sd_title_data_dir(user_dir: Path, id0: str, id1: str) -> Path:
    return (
        user_dir
        / "sdmc"
        / "Nintendo 3DS"
        / id0
        / id1
        / "title"
        / TITLE_HIGH
        / TITLE_LOW
        / "data"
    )


def resolve_metadata(pack_dir: Path | None, slot: Path, dest_data: Path) -> bytes:
    candidates = []
    if pack_dir is not None:
        candidates.append(pack_dir / METADATA_NAME)
    candidates.append(slot.parent / METADATA_NAME)
    candidates.append(dest_data / METADATA_NAME)
    for path in candidates:
        if path.is_file() and path.stat().st_size >= 16:
            return path.read_bytes()[:16]
    return DEFAULT_METADATA


def backup_existing_title_save(user_dir: Path, pack_id: str, backup_root: Path) -> Path | None:
    trees = discover_sd_title_saves(user_dir)
    trees = [t for t in trees if any(iter_or_empty(t))]
    if not trees:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + f"_pre_{pack_id}"
    dest = backup_root / stamp
    n = 1
    while dest.exists():
        dest = backup_root / f"{stamp}_{n}"
        n += 1
    backup_trees(user_dir, dest, trees=trees)
    return dest


def iter_or_empty(root: Path):
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def install_slot(
    slot: Path,
    dest_data: Path,
    *,
    metadata: bytes,
) -> int:
    dest_slot = dest_data / SAVE_DIR_NAME
    if dest_slot.exists():
        shutil.rmtree(dest_slot)
    dest_slot.mkdir(parents=True, exist_ok=True)
    n = 0
    for src in iter_savedata_files(slot):
        shutil.copy2(src, dest_slot / src.name)
        n += 1
    (dest_data / METADATA_NAME).write_bytes(metadata)
    return n


def import_save(
    *,
    user_dir: Path,
    pack_id: str,
    slot: Path,
    pack_dir: Path | None,
    backup_root: Path,
    do_backup: bool,
) -> dict:
    user_dir = user_dir.resolve()
    id0, id1 = nintendo_3ds_ids(user_dir)
    dest_data = sd_title_data_dir(user_dir, id0, id1)
    backup = None
    if do_backup:
        backup = backup_existing_title_save(user_dir, pack_id, backup_root)
    metadata = resolve_metadata(pack_dir, slot, dest_data)
    n = install_slot(slot, dest_data, metadata=metadata)
    dest_slot = dest_data / SAVE_DIR_NAME
    return {
        "pack": pack_id,
        "files": n,
        "user_dir": str(user_dir),
        "dest": str(dest_slot),
        "backup": str(backup) if backup else None,
    }


def cmd_list(saves_root: Path) -> int:
    packs = list_packs(saves_root)
    if not packs:
        print(f"No save packs under {saves_root}")
        return 0
    print(f"Save packs in {saves_root}:")
    for pack in packs:
        slot = find_save_slot(pack)
        n = len(iter_savedata_files(slot))
        manifest = load_pack_manifest(pack)
        heroine = manifest.get("heroine") or pack.name
        print(f"  {pack.name:12}  {n:3} files  {heroine}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--pack",
        default=None,
        help=f"Named pack under --saves-root (default: {DEFAULT_PACK})",
    )
    p.add_argument(
        "--zip",
        dest="zip_path",
        type=Path,
        default=None,
        help="Checkpoint/Azahar zip with 00000001/savedata*",
    )
    p.add_argument(
        "--saves-root",
        type=Path,
        default=DEFAULT_SAVES_ROOT,
        help=f"Pack folder (default: {DEFAULT_SAVES_ROOT})",
    )
    p.add_argument(
        "--user-dir",
        type=Path,
        default=None,
        help="Azahar user dir (default: NLPP_AZAHAR_USER_DIR or %%AppData%%/Azahar)",
    )
    p.add_argument(
        "--backup-root",
        type=Path,
        default=DEFAULT_BACKUP_ROOT,
        help=f"Existing-save snapshot folder (default: {DEFAULT_BACKUP_ROOT})",
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not snapshot the current title save before overwrite",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List packs and exit",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    saves_root = args.saves_root.expanduser().resolve()
    if args.list:
        return cmd_list(saves_root)

    tmp: tempfile.TemporaryDirectory[str] | None = None
    pack_dir: Path | None = None
    pack_id = args.pack or DEFAULT_PACK
    try:
        if args.zip_path is not None:
            zip_path = args.zip_path.expanduser().resolve()
            if not zip_path.is_file():
                raise SystemExit(f"zip not found: {zip_path}")
            tmp = tempfile.TemporaryDirectory(prefix="nlpp_save_")
            slot = extract_zip(zip_path, Path(tmp.name))
            pack_id = args.pack or zip_path.stem
        else:
            pack_dir = saves_root / pack_id
            if not pack_dir.is_dir():
                known = ", ".join(p.name for p in list_packs(saves_root)) or "(none)"
                raise SystemExit(f"unknown save pack {pack_id!r}. Known: {known}")
            slot = find_save_slot(pack_dir)

        user_dir = (
            args.user_dir.expanduser().resolve()
            if args.user_dir
            else azahar_user_dir()
        )
        result = import_save(
            user_dir=user_dir,
            pack_id=pack_id,
            slot=slot,
            pack_dir=pack_dir,
            backup_root=args.backup_root.expanduser().resolve(),
            do_backup=not args.no_backup,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if tmp is not None:
            tmp.cleanup()

    print(f"Installed {result['files']} file(s) from pack {result['pack']!r}")
    print(f"into {result['dest']}")
    if result["backup"]:
        print(f"previous title save -> {result['backup']}")
    print(f"title {TITLE_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
