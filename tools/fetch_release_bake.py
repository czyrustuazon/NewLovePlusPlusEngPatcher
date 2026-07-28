#!/usr/bin/env python3
"""Download gold bake + romfs_overlay from GitHub Releases.

Gold Releases are published from the **nlpp-gold** repo (not this EngPatcher
remote). Pass ``--repo OWNER/nlpp-gold`` or set ``NLPP_GITHUB_REPO``.
The rolling bake from EngPatcher ``main`` is Release tag ``gold``.

Examples:
  python tools/fetch_release_bake.py --repo OWNER/nlpp-gold --tag gold
  python tools/fetch_release_bake.py --repo OWNER/nlpp-gold --tag latest
  python tools/fetch_release_bake.py --repo OWNER/nlpp-gold --tag gold --force
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"


def _repo_from_git() -> str | None:
    git = ROOT / ".git" / "config"
    if not git.is_file():
        return None
    text = git.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if "github.com" not in line.lower():
            continue
        if "github.com:" in line:
            part = line.split("github.com:", 1)[1]
        elif "github.com/" in line:
            part = line.split("github.com/", 1)[1]
        else:
            continue
        part = part.removesuffix(".git").strip().strip("/")
        if part.count("/") == 1:
            return part
    return None


def _urlopen(url: str, token: str | None) -> bytes:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "nlpp-fetch-release-bake")
    if token and "github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
        if "api.github.com" in url:
            req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read()


def _download(url: str, dest: Path, token: str | None, *, dry_run: bool) -> None:
    print(f"[fetch] {url}", flush=True)
    print(f"     -> {dest}", flush=True)
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = _urlopen(url, token)
    tmp = dest.with_name(dest.name + ".partial")
    tmp.write_bytes(data)
    tmp.replace(dest)
    print(f"[fetch] wrote {dest.stat().st_size:,} bytes", flush=True)


def _github_asset_urls(repo: str, tag: str, token: str | None) -> dict[str, str]:
    if tag == "latest":
        api = f"https://api.github.com/repos/{repo}/releases/latest"
    else:
        api = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    raw = _urlopen(api, token)
    meta = json.loads(raw.decode("utf-8"))
    by_name = {a["name"]: a["browser_download_url"] for a in meta.get("assets", [])}
    need = ("bake_img.bin", "romfs_overlay.zip")
    missing = [n for n in need if n not in by_name]
    if missing:
        raise SystemExit(
            f"Release {tag} on {repo} missing assets {missing}. "
            f"Have: {sorted(by_name)}"
        )
    return {n: by_name[n] for n in need}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--repo",
        default=os.environ.get("NLPP_GITHUB_REPO") or _repo_from_git(),
        help="OWNER/REPO (default: origin github remote or NLPP_GITHUB_REPO)",
    )
    ap.add_argument("--tag", default="latest", help="Release tag or 'latest'")
    ap.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
        help="Optional GitHub token (private repos / higher rate limits)",
    )
    ap.add_argument("--out-dir", type=Path, default=RELEASE)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Redownload even if bake_img.bin already exists",
    )
    args = ap.parse_args(argv)

    if not args.repo:
        raise SystemExit("Pass --repo OWNER/REPO or set NLPP_GITHUB_REPO")

    out = args.out_dir.resolve()
    bake = out / "bake_img.bin"
    overlay_zip = out / "romfs_overlay.zip"
    overlay_dir = out / "romfs_overlay"

    if bake.is_file() and overlay_dir.is_dir() and not args.force:
        print(f"[fetch] already present: {bake} (use --force to replace)", flush=True)
        return 0

    print(f"[fetch] GitHub {args.repo} @ {args.tag}", flush=True)
    urls = _github_asset_urls(args.repo, args.tag, args.token)

    try:
        _download(urls["bake_img.bin"], bake, args.token, dry_run=args.dry_run)
        _download(
            urls["romfs_overlay.zip"], overlay_zip, args.token, dry_run=args.dry_run
        )
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"download failed: {exc}") from exc

    if args.dry_run:
        return 0

    if overlay_dir.exists():
        shutil.rmtree(overlay_dir)
    extract_root = out / "_overlay_extract"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    with zipfile.ZipFile(overlay_zip, "r") as zf:
        zf.extractall(extract_root)
    candidate = extract_root / "romfs_overlay"
    if candidate.is_dir():
        shutil.move(str(candidate), str(overlay_dir))
    else:
        overlay_dir.mkdir(parents=True, exist_ok=True)
        for child in extract_root.iterdir():
            shutil.move(str(child), str(overlay_dir / child.name))
    shutil.rmtree(extract_root, ignore_errors=True)
    overlay_zip.unlink(missing_ok=True)
    print(f"[fetch] overlay -> {overlay_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
