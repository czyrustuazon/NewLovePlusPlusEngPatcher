#!/usr/bin/env python3
"""Download gold bake, name-input code.bin, and romfs_overlay from GitHub Releases.

Gold Releases are published from the public **nlpp-gold-maker** repo (not this
EngPatcher remote). The default is ``czyrustuazon/nlpp-gold-maker``. Override
with ``--repo`` or ``NLPP_GITHUB_REPO``. The rolling bake from EngPatcher
``main`` is Release tag ``gold``.

Examples:
  python tools/fetch_release_bake.py --tag gold
  python tools/fetch_release_bake.py --repo czyrustuazon/nlpp-gold-maker --tag latest
  python tools/fetch_release_bake.py --tag gold --force
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
# Public gold-bake Releases. A zip of EngPatcher has no git remote, so Drop
# cannot infer this from origin. Env / --repo still override it.
DEFAULT_GOLD_REPO = "czyrustuazon/nlpp-gold-maker"


def _default_gold_repo() -> str:
    """Public nlpp-gold-maker Release repo.

    ``NLPP_GITHUB_REPO`` / ``NLPP_GOLD_REPO`` override the baked-in repo.
    A git remote is not required (zip downloads have none).
    """
    for key in ("NLPP_GITHUB_REPO", "NLPP_GOLD_REPO"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return DEFAULT_GOLD_REPO


def github_reachable(timeout: float = 5.0) -> bool:
    """True when github.com:443 accepts a TCP connection."""
    import socket

    try:
        with socket.create_connection(("github.com", 443), timeout=timeout):
            return True
    except OSError:
        return False


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
    if meta.get("message") and not meta.get("assets"):
        raise LookupError(meta["message"])
    by_name = {a["name"]: a["browser_download_url"] for a in meta.get("assets", [])}
    need = ("bake_img.bin", "romfs_overlay.zip")
    optional = ("name_input_code.bin",)
    missing = [n for n in need if n not in by_name]
    if missing:
        raise LookupError(
            f"Release {tag!r} on {repo} missing assets {missing} "
            f"(have: {sorted(by_name) or 'none'})"
        )
    found = {n: by_name[n] for n in need}
    for name in optional:
        if name in by_name:
            found[name] = by_name[name]
    return found


def try_fetch_gold(
    *,
    repo: str | None,
    tag: str,
    token: str | None,
    out_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Return (ok, message). ok=True when bake+overlay are ready under out_dir."""
    out = out_dir.resolve()
    bake = out / "bake_img.bin"
    overlay_dir = out / "romfs_overlay"

    if bake.is_file() and overlay_dir.is_dir() and not force:
        return True, f"already present: {bake}"

    if not repo:
        return False, "no gold repo (set NLPP_GITHUB_REPO or clone from GitHub)"

    if not github_reachable():
        return False, "no internet (github.com:443 unreachable); build the bake locally"

    print(f"[fetch] polling GitHub Release {repo} @ {tag!r}", flush=True)
    try:
        urls = _github_asset_urls(repo, tag, token)
        overlay_zip = out / "romfs_overlay.zip"
        code = out / "name_input_code.bin"
        _download(urls["bake_img.bin"], bake, token, dry_run=dry_run)
        _download(urls["romfs_overlay.zip"], overlay_zip, token, dry_run=dry_run)
        if "name_input_code.bin" in urls:
            _download(urls["name_input_code.bin"], code, token, dry_run=dry_run)
        else:
            print(
                "[fetch] Release has no name_input_code.bin "
                "(older gold bake; Drop will rebuild that file locally)",
                flush=True,
            )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, f"no Release {tag!r} on {repo} (404)"
        return False, f"GitHub HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return False, f"network error: {exc.reason}"
    except LookupError as exc:
        return False, str(exc)
    except OSError as exc:
        return False, str(exc)

    if dry_run:
        return True, "dry-run OK"

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
    return True, f"downloaded gold bake -> {bake}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--repo",
        default=_default_gold_repo(),
        help=(
            "OWNER/nlpp-gold-maker "
            f"(default: {DEFAULT_GOLD_REPO}, or NLPP_GITHUB_REPO)"
        ),
    )
    ap.add_argument(
        "--tag",
        default=os.environ.get("NLPP_GOLD_TAG", "gold"),
        help="Release tag (default: gold rolling bake, or NLPP_GOLD_TAG)",
    )
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
    ap.add_argument(
        "--best-effort",
        action="store_true",
        help="For Drop CIA: exit 0 on success, exit 1 quietly when CI bake absent "
        "(caller falls back to local rebuild)",
    )
    args = ap.parse_args(argv)

    ok, msg = try_fetch_gold(
        repo=args.repo,
        tag=args.tag,
        token=args.token,
        out_dir=args.out_dir,
        force=args.force,
        dry_run=args.dry_run,
    )
    if ok:
        print(f"[fetch] {msg}", flush=True)
        return 0
    print(f"[fetch] unavailable: {msg}", flush=True)
    if args.best_effort:
        return 1
    raise SystemExit(msg)


if __name__ == "__main__":
    raise SystemExit(main())
