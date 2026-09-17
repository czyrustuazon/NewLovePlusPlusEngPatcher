"""Patcher release id + gold-bake stamp.

During RC, Drop ignores leftover ``release/bake_img.bin`` unless
``release/bake_stamp.txt`` matches **both** ``PATCHER_RELEASE`` and the
current UI PNG fingerprint. A same-RC stamp that was written after
``--skip-pack`` (or before a community PNG import) must not keep
yesterday's menus.

When merging an RC into **main**, bump these together:

- ``PATCHER_RELEASE`` — Eng Patch badge / bake stamp
- ``CIA_TITLE_VERSION`` — 16-bit CIA title version (must **increase**; never reuse)

All Drop CIA builds of this RC share ``CIA_TITLE_VERSION``. Do not auto-increment
per local build: a fresh clone would reset and collide with already-installed
CIAs (FBI then asks to delete the title and extra data breaks).
"""
from __future__ import annotations

import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from image_map import normalize_folder_key, resolve_folder  # noqa: E402

PATCHER_RELEASE = "v1.0.0-rc3"
# makerom -ver. Vanilla NLPP is 0. Increase on each RC → main merge.
CIA_TITLE_VERSION = 3
BAKE_STAMP = ROOT / "release" / "bake_stamp.txt"
ENG_PATCH_LINE = f"Eng Patch {PATCHER_RELEASE}"
ASSETS_IMAGES = ROOT / "assets" / "images"
_SKIP_PNG_RE = re.compile(r"(\(2\)|_jpn|_bak|copy)", re.I)
_SKIP_DIR_RE = re.compile(r"(timg\s*-\s*copy|__pycache__|\.git)", re.I)
_STAMP_FP_PREFIX = "ui-png:"


def _prefer_image_folders(images_root: Path) -> dict[str, Path]:
    """Same ranking as pack_images.prefer_asset_folders (.check > plain > .arc)."""
    if not images_root.is_dir():
        return {}
    by_map: dict[str, list[tuple[int, Path]]] = defaultdict(list)
    for path in sorted(images_root.iterdir()):
        if not path.is_dir():
            continue
        if resolve_folder(path.name) is None:
            continue
        key = normalize_folder_key(path.name)
        name = path.name.lower()
        if name.endswith(".check"):
            rank = 0
        elif name.endswith(".arc"):
            rank = 2
        else:
            rank = 1
        by_map[key].append((rank, path))
    chosen: dict[str, Path] = {}
    for key, items in by_map.items():
        items.sort(key=lambda t: (t[0], t[1].name.lower()))
        chosen[key] = items[0][1]
    return chosen


def ui_png_fingerprint(images_root: Path | None = None) -> str:
    """Stable id of the PNG masters gold bake would pack."""
    root = images_root if images_root is not None else ASSETS_IMAGES
    h = hashlib.sha1()
    folders = _prefer_image_folders(root)
    for key in sorted(folders):
        folder = folders[key]
        h.update(key.encode("utf-8"))
        h.update(b"\n")
        pngs: list[Path] = []
        for png in folder.rglob("*.png"):
            rel_parts = png.relative_to(folder).parts
            if any(_SKIP_DIR_RE.search(p) for p in rel_parts):
                continue
            if _SKIP_PNG_RE.search(png.stem):
                continue
            pngs.append(png)
        for png in sorted(pngs, key=lambda p: p.as_posix().lower()):
            rel = png.relative_to(folder).as_posix().lower()
            st = png.stat()
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(str(st.st_size).encode("ascii"))
            h.update(b"\0")
            with png.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            h.update(b"\n")
    return h.hexdigest()[:16]


def _stamp_text(fingerprint: str) -> str:
    return f"{PATCHER_RELEASE}\n{_STAMP_FP_PREFIX}{fingerprint}\n"


def _parse_stamp(text: str) -> tuple[str, str | None]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    release = lines[0] if lines else ""
    fp = None
    if len(lines) >= 2 and lines[1].startswith(_STAMP_FP_PREFIX):
        fp = lines[1][len(_STAMP_FP_PREFIX) :].strip()
    return release, fp


def bake_stamp_matches(path: Path | None = None) -> bool:
    p = path if path is not None else BAKE_STAMP
    if not p.is_file():
        return False
    release, fp = _parse_stamp(p.read_text(encoding="utf-8"))
    if release != PATCHER_RELEASE or not fp:
        return False
    return fp == ui_png_fingerprint()


def write_bake_stamp(
    path: Path | None = None, *, packed_assets: bool = True
) -> Path:
    """Write RC + UI PNG fingerprint.

    ``packed_assets=True`` (full PNG pack): stamp matches this tree.
    ``packed_assets=False`` (``--skip-pack``): only refresh the RC line when the
    fingerprint already matches. If PNGs changed since the last pack, leave the
    stamp stale so Drop will from-scratch pack instead of claiming the old bake.
    """
    p = path if path is not None else BAKE_STAMP
    p.parent.mkdir(parents=True, exist_ok=True)
    current_fp = ui_png_fingerprint()
    if packed_assets:
        p.write_text(_stamp_text(current_fp), encoding="utf-8")
        return p

    existing_fp = None
    if p.is_file():
        _rel, existing_fp = _parse_stamp(p.read_text(encoding="utf-8"))
    if existing_fp == current_fp:
        p.write_text(_stamp_text(current_fp), encoding="utf-8")
        return p
    print(
        "[stamp] UI PNG masters changed since last pack (or stamp has no "
        "fingerprint) — leaving bake_stamp stale so Drop will from-scratch pack.",
        flush=True,
    )
    return p


if __name__ == "__main__":
    # Drop bat: exit 0 if leftover bake belongs to this RC + current PNGs, else 2.
    raise SystemExit(0 if bake_stamp_matches() else 2)
