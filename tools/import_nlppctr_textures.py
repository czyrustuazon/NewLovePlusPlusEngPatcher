#!/usr/bin/env python3
"""Import polished NLPPCTR Citra textures into EngPatcher assets/images.

NLPPCTR ships hash-named PNGs for Citra custom textures. This tool:

  1. Downloads (or reads) those PNGs
  2. Matches each to a BCLIM stem via MAD on alpha silhouettes against:
       - existing assets/images PNG masters, and/or
       - BCLIMs decoded from vanilla img.bin (--img-bin)
  3. Writes a review manifest (cache/nlppctr/import/manifest.json)
  4. Optionally copies winners into assets/images/<Folder>.check/timg/<stem>.png

Matching is heuristic — always review manifest before --apply.

Usage:
  python tools/import_nlppctr_textures.py scan
  python tools/import_nlppctr_textures.py scan --img-bin path/to/vanilla/img.bin
  python tools/import_nlppctr_textures.py review
  python tools/import_nlppctr_textures.py apply-winners
  python tools/import_nlppctr_textures.py apply --min-score 0.70 --min-gap 0.10 --unique-target
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bclimutil import parse_bclim  # noqa: E402
from image_map import IMAGE_MAP, normalize_folder_key, resolve_folder  # noqa: E402
from pack_images import ASSETS_IMAGES, prefer_asset_folders  # noqa: E402

NLPPCTR_TEX_API = (
    "https://api.github.com/repos/LovePlusProject/NLPPCTR/contents/"
    "MODs/%5BENGLISH.PATCH%5D/%5BNLPPCTR%5D_ENGLISH_PATCH_251030/"
    "textures/00040000000F4E00?ref=main"
)
NLPPCTR_TEX_RAW = (
    "https://raw.githubusercontent.com/LovePlusProject/NLPPCTR/main/"
    "MODs/%5BENGLISH.PATCH%5D/%5BNLPPCTR%5D_ENGLISH_PATCH_251030/"
    "textures/00040000000F4E00/{name}"
)

IMPORT_DIR = ROOT / "cache" / "nlppctr" / "import"
MANIFEST_PATH = IMPORT_DIR / "manifest.json"
OVERRIDES_PATH = IMPORT_DIR / "overrides.json"
PNG2BCLIM = ROOT / "tools" / "nlpp-tools" / "opt" / "bin" / "png2bclim.exe"

def load_overrides() -> dict[str, tuple[str, str]]:
    """Manual hash -> (folder_key, stem) overrides."""
    if not OVERRIDES_PATH.is_file():
        return {}
    data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    out: dict[str, tuple[str, str]] = {}
    for tex_hash, spec in data.items():
        if isinstance(spec, dict):
            out[tex_hash.upper()] = (spec["folder"], spec["stem"])
        elif isinstance(spec, (list, tuple)) and len(spec) == 2:
            out[tex_hash.upper()] = (spec[0], spec[1])
    return out


TEX1_RE = re.compile(
    r"^tex1_(?P<w>\d+)x(?P<h>\d+)_(?P<hash>[0-9A-Fa-f]+)_(?P<fmt>\d+)_mip0\.png$"
)

# UI packages most likely to hold menu chrome (same set as rebuild_bake deploys + pack_images).
UI_PACKAGE_KEYS: tuple[str, ...] = (
    "ncommonicon",
    "ncommonmsel(3)",
    "ncommonmsel(4)",
    "ncommonmsel(6)",
    "ncommonmsel(7)",
    "ncommonmsel(8)",
    "option",
    "option06",
    "title",
    "myroom",
    "myroomheader",
    "profile",
    "quest",
    "mail",
    "syspopup",
    "introcommon",
    "inputctexture",
    "inputntexture",
    "fileselect",
    "gallery_common",
)

# Verified dump hash → (folder_key, bclim_stem) from technical.md (seed hints).
KNOWN_HASHES: dict[str, tuple[str, str]] = {
    "F305C9338867CC37": ("ncommonicon", "Com_btn_m01_b"),
    "4352FF452CC91909": ("ncommonicon", "Com_btn_t01_b"),
}


@dataclass
class MatchResult:
    citra_name: str
    width: int
    height: int
    hash: str
    citra_fmt: int
    local_path: str
    best_folder: str | None
    best_stem: str | None
    best_score: float
    second_score: float | None
    source: str  # assets | bclim | known
    dest_relpath: str | None
    pkg: int | None = None


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "EngPatcher"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def parse_tex1(name: str) -> tuple[int, int, str, int] | None:
    m = TEX1_RE.match(name)
    if not m:
        return None
    return int(m["w"]), int(m["h"]), m["hash"].upper(), int(m["fmt"])


def composite_rgba(img: Image.Image, bg: tuple[int, int, int] = (240, 240, 240)) -> np.ndarray:
    src = img.convert("RGBA")
    w, h = src.size
    base = Image.new("RGB", (w, h), bg)
    base.paste(src, mask=src.split()[3])
    return np.asarray(base, dtype=np.float32)


def alpha_mask(img: Image.Image, thresh: int = 16) -> np.ndarray:
    return np.asarray(img.convert("RGBA"))[:, :, 3] > thresh


def score_pair(a: Image.Image, b: Image.Image, *, alpha_only: bool = False) -> float:
    """Higher = better. Combines alpha IoU and optional RGB MAD on shared bbox."""
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.NEAREST)
    ma = alpha_mask(a)
    mb = alpha_mask(b)
    union = ma | mb
    if not union.any():
        return 0.0
    inter = ma & mb
    iou = inter.sum() / union.sum()
    if alpha_only:
        return float(iou)
    ca = composite_rgba(a)
    cb = composite_rgba(b)
    mad = float(np.abs(ca - cb).mean()) / 255.0
    rgb_score = max(0.0, 1.0 - mad)
    return 0.55 * iou + 0.45 * rgb_score


def iter_asset_pngs() -> list[tuple[Path, str, str]]:
    """Yield (path, folder_key, stem) for PNG masters under assets/images."""
    folders = prefer_asset_folders(ASSETS_IMAGES)
    out: list[tuple[Path, str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_png(png: Path, folder_key: str) -> None:
        stem = png.stem
        if "_jpn" in stem.lower() or "(2)" in stem:
            return
        key = (folder_key, stem)
        if key in seen:
            return
        seen.add(key)
        out.append((png, folder_key, stem))

    for folder_key, folder in folders.items():
        timg = folder / "timg"
        if timg.is_dir():
            for png in sorted(timg.glob("*.png")):
                add_png(png, folder_key)

    # Also index Images-Done and loose Title/ folders (common polish sources).
    for extra in ASSETS_IMAGES.rglob("*.png"):
        rel = extra.relative_to(ASSETS_IMAGES)
        parts = rel.parts
        if "timg" in parts:
            continue
        if any(x.lower() == "images-done" for x in parts):
            folder_key = parts[1].lower() if len(parts) > 1 else "images-done"
        elif len(parts) >= 2 and resolve_folder(parts[0]):
            folder_key = normalize_folder_key(parts[0])
        else:
            continue
        if resolve_folder(folder_key) is None and folder_key not in IMAGE_MAP:
            # Allow Title/, Option/ etc. under Images-Done/<ArcName>/
            if len(parts) >= 2:
                folder_key = normalize_folder_key(parts[1])
            if resolve_folder(folder_key) is None:
                continue
        add_png(extra, folder_key)

    return out


def index_assets_by_size() -> dict[tuple[int, int], list[tuple[Path, str, str]]]:
    idx: dict[tuple[int, int], list[tuple[Path, str, str]]] = {}
    for path, folder, stem in iter_asset_pngs():
        try:
            with Image.open(path) as im:
                size = im.size
        except OSError:
            continue
        idx.setdefault(size, []).append((path, folder, stem))
    return idx


def bclim_to_png_bytes(data: bytes, dest: Path) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    bclim_path = dest.with_suffix(".bclim")
    bclim_path.write_bytes(data)
    if not PNG2BCLIM.is_file():
        return None
    proc = subprocess.run(
        [str(PNG2BCLIM), bclim_path.name],
        cwd=str(bclim_path.parent),
        capture_output=True,
        text=True,
    )
    out_png = bclim_path.with_suffix(".png")
    bclim_path.unlink(missing_ok=True)
    if proc.returncode != 0 or not out_png.is_file():
        return None
    if out_png != dest:
        shutil.move(str(out_png), str(dest))
    return dest


def _extract_arc_from_img(img_bin: Path, pkg_idx: int, work: Path):
    sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))
    from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402

    raw = img_bin.read_bytes()
    img = ImgBin(str(img_bin))
    img.parse(False)
    res = img.entries[pkg_idx]
    src_pkg = work / f"{pkg_idx:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])
    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    return arc.parsed()


def index_bclims_from_img(img_bin: Path, work: Path) -> dict[tuple[int, int], list[tuple[Path, str, str, int]]]:
    """Decode UI-package BCLIMs to temp PNGs; return same-size index with pkg."""
    from darcutil import DarcArchive  # noqa: E402

    decoded = work / "decoded"
    decoded.mkdir(parents=True, exist_ok=True)
    extract_cache = work / "pkg_cache"
    extract_cache.mkdir(parents=True, exist_ok=True)

    idx: dict[tuple[int, int], list[tuple[Path, str, str, int]]] = {}
    seen_pkg: set[int] = set()
    for folder_key in UI_PACKAGE_KEYS:
        resolved = resolve_folder(folder_key)
        if resolved is None:
            continue
        pkg_idx, arc_name = resolved
        if pkg_idx in seen_pkg:
            continue
        seen_pkg.add(pkg_idx)
        try:
            arc_bytes = _extract_arc_from_img(img_bin, pkg_idx, extract_cache)
            darc = DarcArchive(arc_bytes)
        except Exception as exc:
            print(f"[bclim] skip pkg {pkg_idx}: {exc}", flush=True)
            continue
        for entry in darc.files:
            if not entry.name.endswith(".bclim"):
                continue
            stem = Path(entry.name).stem
            try:
                raw = darc.extract_file(entry)
                _pix, w, h, _fmt, _ft = parse_bclim(raw)
            except ValueError:
                continue
            # Map folder_key per bclim: re-resolve all keys sharing this pkg.
            keys_for_pkg = [k for k in UI_PACKAGE_KEYS if resolve_folder(k) and resolve_folder(k)[0] == pkg_idx]
            out_folder = folder_key if folder_key in keys_for_pkg else keys_for_pkg[0]
            out_png = decoded / out_folder / f"{stem}.png"
            if bclim_to_png_bytes(raw, out_png) is None:
                continue
            for fk in keys_for_pkg:
                target = decoded / fk / f"{stem}.png"
                if fk != out_folder:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.is_file():
                        shutil.copy2(out_png, target)
                idx.setdefault((w, h), []).append((target, fk, stem, pkg_idx))
    return idx


def dest_relpath(folder_key: str, stem: str) -> str:
    # pack_images prefers .check folders — write there when possible.
    check = ASSETS_IMAGES / f"{folder_key}.check" / "timg" / f"{stem}.png"
    if check.parent.is_dir() or (ASSETS_IMAGES / f"{folder_key}.check").is_dir():
        return str(check.relative_to(ROOT))
    plain = ASSETS_IMAGES / folder_key / "timg" / f"{stem}.png"
    if plain.parent.is_dir():
        return str(plain.relative_to(ROOT))
    return str((ASSETS_IMAGES / f"{folder_key}.check" / "timg" / f"{stem}.png").relative_to(ROOT))


def download_textures(dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    items = json.loads(_http_get(NLPPCTR_TEX_API).decode())
    paths: list[Path] = []
    for item in items:
        name = item["name"]
        if not name.endswith(".png"):
            continue
        out = dest / name
        if not out.is_file() or out.stat().st_size != item.get("size", -1):
            print(f"[download] {name}", flush=True)
            out.write_bytes(_http_get(NLPPCTR_TEX_RAW.format(name=name)))
        paths.append(out)
    return paths


def match_one(
    citra_path: Path,
    asset_idx: dict[tuple[int, int], list[tuple[Path, str, str]]],
    bclim_idx: dict[tuple[int, int], list[tuple[Path, str, str, int]]] | None,
) -> MatchResult:
    parsed = parse_tex1(citra_path.name)
    if parsed is None:
        raise ValueError(f"not a tex1 PNG: {citra_path.name}")
    w, h, tex_hash, citra_fmt = parsed
    with Image.open(citra_path) as citra_img:
        citra_img = citra_img.convert("RGBA")

    if tex_hash in KNOWN_HASHES:
        folder, stem = KNOWN_HASHES[tex_hash]
        source = "known"
    elif tex_hash in load_overrides():
        folder, stem = load_overrides()[tex_hash]
        source = "override"
    else:
        folder = stem = None
        source = ""

    if folder and stem:
        return MatchResult(
            citra_name=citra_path.name,
            width=w,
            height=h,
            hash=tex_hash,
            citra_fmt=citra_fmt,
            local_path=str(citra_path.relative_to(ROOT)),
            best_folder=folder,
            best_stem=stem,
            best_score=1.0,
            second_score=None,
            source=source or "known",
            dest_relpath=dest_relpath(folder, stem),
            pkg=resolve_folder(folder)[0] if resolve_folder(folder) else None,
        )

    candidates: list[tuple[float, str, str, str, int | None]] = []

    for path, folder, stem in asset_idx.get((w, h), []):
        try:
            with Image.open(path) as cand:
                s = score_pair(citra_img, cand)
        except OSError:
            continue
        candidates.append((s, folder, stem, "assets", None))

    if bclim_idx:
        for path, folder, stem, pkg in bclim_idx.get((w, h), []):
            try:
                with Image.open(path) as cand:
                    s = score_pair(citra_img, cand)
            except OSError:
                continue
            candidates.append((s + 0.03, folder, stem, "bclim", pkg))

    candidates.sort(key=lambda x: -x[0])
    best = candidates[0] if candidates else None
    second = candidates[1][0] if len(candidates) > 1 else None

    if best is None:
        return MatchResult(
            citra_name=citra_path.name,
            width=w,
            height=h,
            hash=tex_hash,
            citra_fmt=citra_fmt,
            local_path=str(citra_path.relative_to(ROOT)),
            best_folder=None,
            best_stem=None,
            best_score=0.0,
            second_score=None,
            source="none",
            dest_relpath=None,
        )

    score, folder, stem, source, pkg = best
    return MatchResult(
        citra_name=citra_path.name,
        width=w,
        height=h,
        hash=tex_hash,
        citra_fmt=citra_fmt,
        local_path=str(citra_path.relative_to(ROOT)),
        best_folder=folder,
        best_stem=stem,
        best_score=round(score, 4),
        second_score=round(second, 4) if second is not None else None,
        source=source,
        dest_relpath=dest_relpath(folder, stem),
        pkg=pkg,
    )


def cmd_scan(args: argparse.Namespace) -> int:
    tex_dir = IMPORT_DIR / "textures"
    if args.refresh or not any(tex_dir.glob("tex1_*.png")):
        download_textures(tex_dir)
    else:
        print(f"[scan] using cached textures in {tex_dir}", flush=True)

    asset_idx = index_assets_by_size()
    print(f"[scan] asset index: {sum(len(v) for v in asset_idx.values())} PNGs", flush=True)

    bclim_idx = None
    bclim_work = IMPORT_DIR / "bclim_work"
    if args.img_bin:
        img_bin = Path(args.img_bin).resolve()
        if not img_bin.is_file():
            raise SystemExit(f"--img-bin not found: {img_bin}")
        print(f"[scan] decoding UI BCLIMs from {img_bin} ...", flush=True)
        bclim_idx = index_bclims_from_img(img_bin, bclim_work)
        print(f"[scan] bclim index: {sum(len(v) for v in bclim_idx.values())} decoded", flush=True)

    results: list[MatchResult] = []
    for png in sorted(tex_dir.glob("tex1_*.png")):
        mr = match_one(png, asset_idx, bclim_idx)
        results.append(mr)
        flag = "OK" if mr.best_score >= args.min_score and mr.best_stem else "??"
        target = f"{mr.best_folder}/{mr.best_stem}" if mr.best_stem else "-"
        print(
            f"  [{flag}] {mr.citra_name} -> {target} "
            f"score={mr.best_score:.3f} ({mr.source})",
            flush=True,
        )

    manifest = {
        "source": "LovePlusProject/NLPPCTR ENGLISH_PATCH_251030",
        "min_score_suggested": args.min_score,
        "img_bin": str(args.img_bin) if args.img_bin else None,
        "matches": [asdict(r) for r in results],
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    good = sum(1 for r in results if r.best_score >= args.min_score and r.best_stem)
    print(f"\n[scan] {good}/{len(results)} matches >= {args.min_score}", flush=True)
    print(f"\n[scan] manifest -> {MANIFEST_PATH}", flush=True)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Export side-by-side PNGs for visual verification before apply."""
    manifest_path = Path(args.manifest).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_dir = IMPORT_DIR / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for row in data["matches"]:
        if row.get("best_score", 0) < args.min_score or not row.get("dest_relpath"):
            continue
        src = ROOT / row["local_path"]
        dest = ROOT / row["dest_relpath"]
        if not src.is_file():
            continue
        citra = Image.open(src).convert("RGBA")
        w, h = citra.size
        panel = Image.new("RGBA", (w * 2 + 8, h + 40), (32, 32, 32, 255))
        panel.paste(citra, (0, 20))
        if dest.is_file():
            cur = Image.open(dest).convert("RGBA")
            if cur.size != citra.size:
                cur = cur.resize(citra.size, Image.Resampling.NEAREST)
            panel.paste(cur, (w + 8, 20))
        label = f"{row['best_folder']}/{row['best_stem']} score={row['best_score']}"
        safe = row["citra_name"].replace(".png", "")
        out_path = out_dir / f"{safe}__{row['best_stem']}.png"
        panel.save(out_path)
        (out_dir / f"{safe}.txt").write_text(label + "\n", encoding="utf-8")
        count += 1
    print(f"[review] {count} panels -> {out_dir}", flush=True)
    print("[review] Left=NLPPCTR, Right=current asset (if present)", flush=True)
    return 0


def bclim_size_from_img(img_bin: Path, pkg_idx: int, stem: str) -> tuple[int, int] | None:
    """Look up WxH for timg/<stem>.bclim inside a package ARC."""
    from darcutil import DarcArchive  # noqa: E402

    work = IMPORT_DIR / "size_lookup"
    try:
        arc_bytes = _extract_arc_from_img(img_bin, pkg_idx, work)
        darc = DarcArchive(arc_bytes)
        entry = darc.find(f"timg/{stem}.bclim") or darc.find(f"{stem}.bclim")
        if entry is None:
            return None
        _pix, w, h, _fmt, _ft = parse_bclim(darc.extract_file(entry))
        return w, h
    except Exception:
        return None


def expected_size(row: dict, img_bin: Path | None) -> tuple[int, int] | None:
    dest = row.get("dest_relpath")
    if dest:
        dest_path = ROOT / dest
        if dest_path.is_file():
            with Image.open(dest_path) as im:
                return im.size
    pkg = row.get("pkg")
    stem = row.get("best_stem")
    folder = row.get("best_folder")
    if img_bin and pkg and stem:
        got = bclim_size_from_img(img_bin, int(pkg), stem)
        if got:
            return got
    decoded = IMPORT_DIR / "bclim_work" / "decoded" / str(folder) / f"{stem}.png"
    if decoded.is_file():
        with Image.open(decoded) as im:
            return im.size
    return None


def cmd_apply_winners(args: argparse.Namespace) -> int:
    """Copy one NLPPCTR PNG per destination (best score), with size validation."""
    manifest_path = Path(args.manifest).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    img_bin = Path(args.img_bin).resolve() if args.img_bin else None
    if img_bin is None:
        azahar = Path(os.environ.get("APPDATA", "")) / "Azahar" / "load" / "mods" / "00040000000F4E00" / "romfs" / "img.bin"
        if azahar.is_file():
            img_bin = azahar

    from collections import defaultdict

    by_dest: dict[str, list[dict]] = defaultdict(list)
    for row in data["matches"]:
        dest = row.get("dest_relpath")
        if not dest or row.get("best_score", 0) < args.min_score:
            continue
        by_dest[dest].append(row)

    applied_log: list[dict] = []
    applied = skipped = 0
    for dest, rows in sorted(by_dest.items()):
        best = max(rows, key=lambda r: r["best_score"])
        src = ROOT / best["local_path"]
        if not src.is_file():
            skipped += 1
            continue
        with Image.open(src) as citra_im:
            citra_size = citra_im.size
        exp = expected_size(best, img_bin)
        if exp and citra_size != exp:
            print(
                f"[skip] size {citra_size} != {exp} for {best['best_stem']} ({best['citra_name']})",
                flush=True,
            )
            skipped += 1
            continue
        dest_path = ROOT / dest
        if args.dry_run:
            print(f"[dry-run] {best['citra_name']} -> {dest_path.relative_to(ROOT)}", flush=True)
            applied += 1
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)
        folder, stem = best["best_folder"], best["best_stem"]
        for alt in (
            ASSETS_IMAGES / "Images-Done" / folder.title() / f"{stem}.png",
            ASSETS_IMAGES / folder.title() / f"{stem}.png",
            ASSETS_IMAGES / "Title" / f"{stem}.png",
        ):
            if alt.parent.is_dir() and alt != dest_path:
                shutil.copy2(src, alt)
        print(f"[apply] {dest_path.relative_to(ROOT)} <- {best['citra_name']}", flush=True)
        applied_log.append(
            {
                "citra": best["citra_name"],
                "dest": dest,
                "folder": folder,
                "stem": stem,
                "pkg": best.get("pkg"),
                "score": best["best_score"],
            }
        )
        applied += 1

    log_path = IMPORT_DIR / "applied.json"
    if not args.dry_run:
        log_path.write_text(json.dumps(applied_log, indent=2), encoding="utf-8")
    pkgs = sorted({r["pkg"] for r in applied_log if r.get("pkg")})
    print(f"\n[apply-winners] {applied} copied, {skipped} skipped", flush=True)
    if applied_log and not args.dry_run:
        print(f"[apply-winners] log -> {log_path}", flush=True)
        keys = sorted({r["folder"] for r in applied_log})
        print(f"[apply-winners] image_map keys touched: {', '.join(keys)}", flush=True)
        if pkgs:
            print(
                "[apply-winners] next: python tools/rebuild_bake_img.py --skip-pack "
                "(or full bake) to splice into release/bake_img.bin",
                flush=True,
            )
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    applied = skipped = 0

    dest_users: dict[str, str] = {}
    if args.unique_target:
        for row in data["matches"]:
            dest = row.get("dest_relpath")
            if dest and row.get("best_score", 0) >= args.min_score:
                dest_users.setdefault(dest, row["citra_name"])

    for row in data["matches"]:
        score = row.get("best_score", 0.0)
        dest = row.get("dest_relpath")
        src = row.get("local_path")
        if not dest or not src or score < args.min_score:
            skipped += 1
            continue
        if args.unique_target and dest_users.get(dest) != row["citra_name"]:
            print(f"[skip] duplicate target {dest} for {row['citra_name']}")
            skipped += 1
            continue
        if row.get("second_score") is not None and row["second_score"] > score - args.min_gap:
            print(f"[skip] ambiguous {row['citra_name']} ({score:.3f} vs {row['second_score']:.3f})")
            skipped += 1
            continue
        src_path = ROOT / src
        dest_path = ROOT / dest
        if args.dry_run:
            print(f"[dry-run] {src_path.name} -> {dest_path}")
            applied += 1
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        print(f"[apply] {dest_path.relative_to(ROOT)}", flush=True)
        applied += 1
    print(f"\n[apply] {applied} copied, {skipped} skipped", flush=True)
    if applied and not args.dry_run:
        print(
            "\nNext: rebuild affected packages, e.g.\n"
            "  python src/pack_images.py --only ncommonicon --img-bin <vanilla> --out cache/new_img.bin\n"
            "or rerun tools/rebuild_bake_img.py after reviewing PNGs.",
            flush=True,
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="Download NLPPCTR textures and match to assets/BCLIMs")
    scan.add_argument("--refresh", action="store_true", help="Re-download textures")
    scan.add_argument("--img-bin", type=Path, help="Vanilla img.bin for BCLIM decode matching")
    scan.add_argument("--min-score", type=float, default=0.45, help="Score threshold for OK flag")

    apply_p = sub.add_parser("apply", help="Copy matched textures into assets/images")
    apply_p.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    apply_p.add_argument("--min-score", type=float, default=0.70)
    apply_p.add_argument("--min-gap", type=float, default=0.10, help="Require best - second >= this")
    apply_p.add_argument("--unique-target", action="store_true", default=True)
    apply_p.add_argument("--allow-duplicate-targets", action="store_true")
    apply_p.add_argument("--dry-run", action="store_true")

    review_p = sub.add_parser("review", help="Export side-by-side comparison PNGs")
    review_p.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    review_p.add_argument("--min-score", type=float, default=0.45)

    winners_p = sub.add_parser(
        "apply-winners",
        help="Best NLPPCTR PNG per BCLIM dest (size-checked, one winner per slot)",
    )
    winners_p.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    winners_p.add_argument("--img-bin", type=Path, help="img.bin for BCLIM size lookup")
    winners_p.add_argument("--min-score", type=float, default=0.45)
    winners_p.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "review":
        return cmd_review(args)
    if args.cmd == "apply-winners":
        return cmd_apply_winners(args)
    if args.cmd == "apply":
        if getattr(args, "allow_duplicate_targets", False):
            args.unique_target = False
        return cmd_apply(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
