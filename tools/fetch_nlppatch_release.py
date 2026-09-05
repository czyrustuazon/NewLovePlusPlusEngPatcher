#!/usr/bin/env python3
"""Fetch LovePlusProject NLPPPATCH.2017.08.15 release into vendor/.

Extracts ``release/romfs/script/bin/script/*.dbin2`` (~168 scripts) for the
28% community layer. Manaka ``t*`` still comes from ``rebuild_dbin2/``.

  python tools/fetch_nlppatch_release.py
  python tools/fetch_nlppatch_release.py --zip path\\to\\NLPPPATCH.2017.08.15.zip
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "NLPPPATCH"
SCRIPT_OUT = (
    VENDOR / "release" / "romfs" / "script" / "bin" / "script"
)
RELEASE_URLS = (
    "https://github.com/LovePlusProject/NLPPPATCH/releases/download/v1.0/NLPPATCH.2017.08.15.zip",
    "https://github.com/LovePlusProject/NLPPPATCH/releases/download/NLPPPATCH.2017.08.15/NLPPATCH.2017.08.15.zip",
)


NLPPCTR_SCRIPT_API = (
    "https://api.github.com/repos/LovePlusProject/NLPPCTR/contents/"
    "MODs/%5BENGLISH.PATCH%5D/%5BNLPPCTR%5D_ENGLISH_PATCH_251030/"
    "mods/00040000000F4E00/romfs/script/bin/script?ref=main"
)
NLPPCTR_SCRIPT_RAW = (
    "https://raw.githubusercontent.com/LovePlusProject/NLPPCTR/main/"
    "MODs/%5BENGLISH.PATCH%5D/%5BNLPPCTR%5D_ENGLISH_PATCH_251030/"
    "mods/00040000000F4E00/romfs/script/bin/script/{name}"
)


def _api_asset_url() -> str | None:
    for api in (
        "https://api.github.com/repos/LovePlusProject/NLPPPATCH/releases/tags/v1.0",
        "https://api.github.com/repos/LovePlusProject/NLPPPATCH/releases/latest",
    ):
        try:
            req = urllib.request.Request(
                api,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "NLPP-EngPatcher"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.load(resp)
        except OSError:
            continue
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".zip") and "NLPPPATCH" in name:
                return asset["browser_download_url"]
    return None


def download_zip(dest: Path) -> None:
    urls = list(RELEASE_URLS)
    api = _api_asset_url()
    if api:
        urls.insert(0, api)
    last_err: Exception | None = None
    for url in urls:
        try:
            print(f"[fetch] {url}")
            with urllib.request.urlopen(url, timeout=180) as resp:
                dest.write_bytes(resp.read())
            print(f"[fetch] wrote {dest} ({dest.stat().st_size:,} bytes)")
            return
        except OSError as exc:
            print(f"[fetch] failed: {exc}")
            last_err = exc
    raise SystemExit(
        "could not download NLPPPATCH zip — place NLPPPATCH.2017.08.15.zip manually "
        "and pass --zip"
    ) from last_err


def extract_scripts(zip_path: Path) -> int:
    SCRIPT_OUT.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            norm = name.replace("\\", "/")
            if not norm.endswith(".dbin2"):
                continue
            if "/script/bin/script/" not in norm:
                continue
            stem = Path(norm).name
            out = SCRIPT_OUT / stem
            out.write_bytes(zf.read(name))
            count += 1
    return count


def fetch_from_nlppctr() -> int:
    """Download ~168 NLPPPATCH-era scripts from NLPPCTR English patch on GitHub."""
    SCRIPT_OUT.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        NLPPCTR_SCRIPT_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "NLPP-EngPatcher"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        items = json.load(resp)
    count = 0
    for item in items:
        name = item.get("name", "")
        if not name.endswith(".dbin2"):
            continue
        url = item.get("download_url") or NLPPCTR_SCRIPT_RAW.format(name=name)
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "NLPP-EngPatcher"}),
            timeout=120,
        ) as resp:
            (SCRIPT_OUT / name).write_bytes(resp.read())
        count += 1
        if count % 25 == 0:
            print(f"[fetch] {count} scripts ...")
    return count


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", type=Path, help="local NLPPPATCH.2017.08.15.zip")
    ap.add_argument(
        "--keep-zip",
        type=Path,
        default=VENDOR / "NLPPPATCH.2017.08.15.zip",
        help="where to save downloaded zip",
    )
    args = ap.parse_args(argv)

    if args.zip:
        zip_path = args.zip.resolve()
        if not zip_path.is_file():
            raise SystemExit(f"zip not found: {zip_path}")
        n = extract_scripts(zip_path)
    else:
        zip_path = args.keep_zip.resolve()
        if zip_path.is_file():
            n = extract_scripts(zip_path)
        else:
            print("[fetch] no local zip — trying NLPPPATCH release URLs ...")
            try:
                zip_path.parent.mkdir(parents=True, exist_ok=True)
                download_zip(zip_path)
                n = extract_scripts(zip_path)
            except SystemExit:
                print("[fetch] zip unavailable — falling back to NLPPCTR script pack ...")
                n = fetch_from_nlppctr()

    print(f"[fetch] extracted {n} scripts -> {SCRIPT_OUT}")
    if n < 100:
        print("[warn] expected ~168 scripts — zip may be incomplete", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
