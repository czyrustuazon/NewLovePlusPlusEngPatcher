#!/usr/bin/env python3
"""Import NLPP English UI Buttons bundle into EngPatcher assets.

Source: ``NLPP_English_UI_Buttons_only.zip`` (LovePlusProject / NLPPPATCH community).
Contains 49 named PNGs + ``manifest.json`` + ``trb_buttons_en.csv``.

Typical flow::

  python tools/import_ui_buttons_bundle.py import
  python tools/import_ui_buttons_bundle.py status
  python tools/deploy_ui_buttons_en.py

Bundle search order (``import``):
  1. ``--zip`` path
  2. ``NLPP_UI_BUTTONS_ZIP`` env
  3. ``cache/ui_buttons_only/`` (already extracted)
  4. ``~/Downloads/NLPP_English_UI_Buttons_only*.zip``
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "images"
IMPORT_DIR = ROOT / "cache" / "ui_buttons" / "import"
MANIFEST_PATH = IMPORT_DIR / "applied.json"
TRB_CSV_DST = ROOT / "assets" / "textresource" / "ui_buttons_en.csv"


@dataclass(frozen=True)
class CopyTarget:
    """One bundle graphics group → EngPatcher asset folder(s)."""

    bundle_dir: str
    folder_keys: tuple[str, ...]
    asset_names: tuple[str, ...]
    package: int | None = None
    warning: str = ""


# manifest.json groups → pack_images folder keys (image_map.py)
TARGETS: tuple[CopyTarget, ...] = (
    CopyTarget(
        "graphics/package_5190_InputC_and_InputN_shared",
        ("inputctexture", "inputntexture"),
        ("InputCTexture.check", "InputNTexture.check"),
        5190,
        "Same nine PNGs go into InputC + InputN ARCs. Layout-sensitive.",
    ),
    CopyTarget(
        "graphics/package_5259_SysPopup",
        ("syspopup",),
        ("SysPopup.check",),
        5259,
        "Do not modify SysPopup node 94.",
    ),
    CopyTarget(
        "graphics/package_5380_Myroom_Back",
        ("myroomback",),
        ("MyroomBack.check",),
        5380,
        "Only three Back textures; use --only myroomback to avoid full Myroom repack.",
    ),
    CopyTarget(
        "graphics/Album_Delete",
        ("album",),
        ("Album.check",),
        4149,
        "Album.arc delete / delete-all buttons.",
    ),
)


def _find_bundle_root(extracted: Path) -> Path:
    if (extracted / "manifest.json").is_file():
        return extracted
    for child in extracted.iterdir():
        if child.is_dir() and (child / "manifest.json").is_file():
            return child
    raise SystemExit(f"manifest.json not found under {extracted}")


def _find_zip(explicit: Path | None) -> Path:
    if explicit is not None:
        p = explicit.expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"zip not found: {p}")
        return p

    env = os.environ.get("NLPP_UI_BUTTONS_ZIP")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_file():
            return p
        raise SystemExit(f"NLPP_UI_BUTTONS_ZIP not found: {p}")

    cache = ROOT / "cache" / "ui_buttons_only"
    if (cache / "manifest.json").is_file() or any(
        (cache / d / "manifest.json").is_file() for d in cache.iterdir() if d.is_dir()
    ):
        raise SystemExit(
            f"already extracted at {cache}; run: python {Path(__file__).name} import --extracted {cache}"
        )

    downloads = Path.home() / "Downloads"
    hits = sorted(downloads.glob("NLPP_English_UI_Buttons_only*.zip"))
    if not hits:
        raise SystemExit(
            "NLPP_English_UI_Buttons_only.zip not found.\n"
            "Place it in Downloads or pass --zip PATH"
        )
    return hits[-1].resolve()


def _extract_zip(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    return _find_bundle_root(dest)


def _copy_pngs(src_dir: Path, dst_dir: Path) -> list[str]:
    timg = dst_dir / "timg"
    timg.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for png in sorted(src_dir.glob("*.png")):
        out = timg / png.name
        shutil.copy2(png, out)
        copied.append(png.name)
    return copied


def cmd_import(args: argparse.Namespace) -> int:
    if args.extracted:
        bundle_root = _find_bundle_root(Path(args.extracted).resolve())
    else:
        zip_path = _find_zip(Path(args.zip) if args.zip else None)
        print(f"[import] zip: {zip_path}", flush=True)
        extract_to = ROOT / "cache" / "ui_buttons_only"
        bundle_root = _extract_zip(zip_path, extract_to)

    manifest_src = bundle_root / "manifest.json"
    manifest = json.loads(manifest_src.read_text(encoding="utf-8"))
    print(f"[import] bundle: {bundle_root.name} ({manifest.get('png_assets', '?')} PNGs)", flush=True)

    applied: list[dict] = []
    for target in TARGETS:
        src = bundle_root / target.bundle_dir
        if not src.is_dir():
            print(f"[skip] missing {target.bundle_dir}", flush=True)
            continue
        pngs = sorted(src.glob("*.png"))
        if not pngs:
            print(f"[skip] no PNGs in {target.bundle_dir}", flush=True)
            continue

        entry_files: list[str] = []
        for asset_name in target.asset_names:
            dst = ASSETS / asset_name
            names = _copy_pngs(src, dst)
            entry_files.extend(names)
            print(f"  -> {asset_name}/timg/ ({len(names)} png)", flush=True)

        applied.append(
            {
                "bundle_dir": target.bundle_dir,
                "folder_keys": list(target.folder_keys),
                "asset_dirs": list(target.asset_names),
                "package": target.package,
                "png_count": len(pngs),
                "png_files": [p.name for p in pngs],
                "warning": target.warning,
            }
        )

    trb_src = bundle_root / "trb_buttons_en.csv"
    if trb_src.is_file():
        TRB_CSV_DST.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(trb_src, TRB_CSV_DST)
        print(f"[import] TRB reference -> {TRB_CSV_DST.relative_to(ROOT)}", flush=True)

    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(applied, indent=2) + "\n", encoding="utf-8")
    print(f"[import] wrote {MANIFEST_PATH.relative_to(ROOT)}", flush=True)
    print(
        "[import] deploy: python tools/deploy_ui_buttons_en.py "
        "(or --only input for keyboard only)",
        flush=True,
    )
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    if not MANIFEST_PATH.is_file():
        print("Not imported. Run: python tools/import_ui_buttons_bundle.py import")
        return 1

    applied = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(f"Import manifest: {MANIFEST_PATH}")
    for entry in applied:
        keys = ", ".join(entry["folder_keys"])
        pkg = entry.get("package")
        pkg_s = f"{pkg:>4}" if isinstance(pkg, int) else "   ?"
        print(f"  pkg {pkg_s}  keys=[{keys}]  pngs={entry['png_count']}")
        if entry.get("warning"):
            print(f"           warn: {entry['warning']}")
    if TRB_CSV_DST.is_file():
        rows = sum(1 for _ in TRB_CSV_DST.read_text(encoding="utf-8").splitlines() if _.strip())
        print(f"  TRB rows: {TRB_CSV_DST.relative_to(ROOT)} ({rows} lines)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import", help="Copy bundle PNGs into assets/images/*.check/timg/")
    p_import.add_argument("--zip", help="Path to NLPP_English_UI_Buttons_only.zip")
    p_import.add_argument(
        "--extracted",
        help="Use an already-extracted bundle directory (contains manifest.json)",
    )

    sub.add_parser("status", help="Show import manifest")

    args = parser.parse_args()
    if args.cmd == "import":
        return cmd_import(args)
    if args.cmd == "status":
        return cmd_status(args)
    raise SystemExit(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
