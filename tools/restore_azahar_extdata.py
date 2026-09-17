#!/usr/bin/env python3
"""Backup / restore Azahar extra data + NLPP title save.

Reinstalling a CIA can empty NAND save while leftover extra data looks corrupt.
This copies the emulator trees (not real-3DS SD extra data — use Checkpoint).

  python tools/restore_azahar_extdata.py backup
  python tools/restore_azahar_extdata.py restore          # latest snapshot
  python tools/restore_azahar_extdata.py restore --from out/extdata_backup/20260913_133000
  python tools/restore_azahar_extdata.py list

Paths (under Azahar user dir, override with --user-dir / NLPP_AZAHAR_USER_DIR):

  sdmc/Nintendo 3DS/<ID0>/<ID1>/extdata/00000000/00000f4e/   title extra data
  sdmc/Nintendo 3DS/<ID0>/<ID1>/extdata/00000000/00000321/   SpotPass boss
  nand/data/<ID0>/title/00040000/000f4e00/data/              title save

Fully quit Azahar before restore so it reloads the files.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nlpp_paths import TITLE_ID, azahar_user_dir  # noqa: E402

TITLE_HIGH = TITLE_ID[:8].lower()  # 00040000
TITLE_LOW = TITLE_ID[8:].lower()  # 000f4e00
# Extra Data ID = UniqueId = (low title ID >> 8), 8 hex digits → 00000f4e.
# 0000f4e0 is a mistaken shift some listings use; keep it as an alias.
# 00000321 is SpotPass BOSS.
UNIQUE_ID = (int(TITLE_LOW, 16) >> 8) & 0xFFFFF
EXTDATA_IDS = frozenset(
    {
        f"{UNIQUE_ID:08x}",
        "0000f4e0",
        "00000321",
    }
)
NAND_SAVE_REL = f"title/{TITLE_HIGH}/{TITLE_LOW}/data"
DEFAULT_BACKUP_ROOT = ROOT / "out" / "extdata_backup"
MANIFEST_NAME = "manifest.json"


def _norm_rel(path: Path) -> str:
    return path.as_posix()


def discover_nlpp_trees(user_dir: Path) -> list[Path]:
    """Extra-data archives + NAND title save that belong to NLPP."""
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen or not path.is_dir():
            return
        seen.add(resolved)
        found.append(path)

    sdmc = user_dir / "sdmc" / "Nintendo 3DS"
    if sdmc.is_dir():
        for archive in sdmc.glob("*/*/extdata/00000000/*"):
            if archive.name.lower() in EXTDATA_IDS:
                add(archive)

    nand_data = user_dir / "nand" / "data"
    if nand_data.is_dir():
        for archive in nand_data.glob("*/extdata/00000000/*"):
            if archive.name.lower() in EXTDATA_IDS:
                add(archive)
        for save in nand_data.glob(f"*/{NAND_SAVE_REL}"):
            add(save)

    found.sort(key=lambda p: str(p).lower())
    return found


def iter_files(root: Path) -> list[Path]:
    files = [p for p in root.rglob("*") if p.is_file()]
    files.sort()
    return files


def backup_trees(
    user_dir: Path,
    dest: Path,
    *,
    trees: list[Path] | None = None,
) -> dict:
    user_dir = user_dir.resolve()
    roots = trees if trees is not None else discover_nlpp_trees(user_dir)
    if not roots:
        raise FileNotFoundError(
            f"No NLPP extra data or title save under {user_dir}.\n"
            "Run the game once in Azahar (or pass --user-dir for an a/b instance)."
        )
    dest.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, int | str]] = []
    for src_root in roots:
        rel = src_root.relative_to(user_dir)
        dst_root = dest / rel
        if dst_root.exists():
            shutil.rmtree(dst_root)
        shutil.copytree(src_root, dst_root)
        for src_file in iter_files(src_root):
            rel_file = src_file.relative_to(user_dir)
            records.append(
                {
                    "rel": _norm_rel(rel_file),
                    "bytes": src_file.stat().st_size,
                }
            )
    manifest = {
        "title_id": TITLE_ID,
        "user_dir": str(user_dir),
        "created": datetime.now().isoformat(timespec="seconds"),
        "trees": [_norm_rel(p.relative_to(user_dir)) for p in roots],
        "files": records,
    }
    (dest / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def latest_backup(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    dirs = sorted(
        p
        for p in root.iterdir()
        if p.is_dir() and (p / MANIFEST_NAME).is_file()
    )
    return dirs[-1] if dirs else None


def load_manifest(backup: Path) -> dict:
    path = backup / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"missing {MANIFEST_NAME} in {backup}")
    return json.loads(path.read_text(encoding="utf-8"))


def restore_trees(backup: Path, user_dir: Path) -> int:
    backup = backup.resolve()
    user_dir = user_dir.resolve()
    manifest = load_manifest(backup)
    n = 0
    for entry in manifest.get("files") or []:
        rel = str(entry["rel"]).replace("\\", "/")
        src = backup / rel
        if not src.is_file():
            raise FileNotFoundError(f"backup file missing: {src}")
        dst = user_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    return n


def _print_trees(user_dir: Path, trees: list[Path]) -> None:
    if not trees:
        print(f"No NLPP extra data / title save under {user_dir}")
        return
    print(f"Azahar user dir: {user_dir}")
    for tree in trees:
        nfiles = len(iter_files(tree))
        rel = tree.relative_to(user_dir)
        print(f"  {rel}  ({nfiles} file(s))")


def cmd_list(user_dir: Path, backup_root: Path) -> int:
    trees = discover_nlpp_trees(user_dir)
    _print_trees(user_dir, trees)
    latest = latest_backup(backup_root)
    if latest is None:
        print(f"No snapshots in {backup_root}")
    else:
        print(f"Latest snapshot: {latest}")
    return 0


def cmd_backup(user_dir: Path, backup_root: Path, stamp: str | None) -> int:
    trees = discover_nlpp_trees(user_dir)
    _print_trees(user_dir, trees)
    name = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_root / name
    if dest.exists():
        raise SystemExit(f"backup folder already exists: {dest}")
    manifest = backup_trees(user_dir, dest, trees=trees)
    n = len(manifest["files"])
    print(f"Wrote {n} file(s) -> {dest}")
    return 0


def cmd_restore(user_dir: Path, backup_root: Path, source: Path | None) -> int:
    backup = source.resolve() if source else latest_backup(backup_root)
    if backup is None:
        raise SystemExit(
            f"No snapshot under {backup_root}. Run backup first, or pass --from."
        )
    if not backup.is_dir():
        raise SystemExit(f"backup not found: {backup}")
    n = restore_trees(backup, user_dir)
    print(f"Restored {n} file(s) from {backup}")
    print(f"into {user_dir}")
    print("Fully quit Azahar so extra data reloads.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "command",
        choices=("backup", "restore", "list"),
        help="backup = snapshot Azahar extra data; restore = copy a snapshot back",
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
        help=f"Snapshot folder (default: {DEFAULT_BACKUP_ROOT})",
    )
    p.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=None,
        help="Snapshot to restore (default: latest under --backup-root)",
    )
    p.add_argument(
        "--stamp",
        default=None,
        help="Backup folder name (default: local YYYYMMDD_HHMMSS)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    user_dir = (
        args.user_dir.expanduser().resolve()
        if args.user_dir
        else azahar_user_dir()
    )
    backup_root = args.backup_root.expanduser().resolve()
    try:
        if args.command == "list":
            return cmd_list(user_dir, backup_root)
        if args.command == "backup":
            return cmd_backup(user_dir, backup_root, args.stamp)
        return cmd_restore(user_dir, backup_root, args.source)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
