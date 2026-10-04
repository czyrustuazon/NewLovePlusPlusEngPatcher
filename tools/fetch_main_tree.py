#!/usr/bin/env python3
"""Best-effort sync of this EngPatcher tree from GitHub ``main`` (no git).

End users typically start from a Release zip
(``NewLovePlusPlusEngPatcher-main.zip``). Drop CIA then overlays the tip of
``main`` via the public zipball so they pick up script/asset fixes without
installing git.

Never touches ``out/``, ``release/``, ``cache/``, ``.env``, local a/b paths,
or a ``.git`` checkout (contributors keep using git). Offline / 404 / errors
are soft under ``--best-effort``.

Examples:
  python tools/fetch_main_tree.py --best-effort
  python tools/fetch_main_tree.py --force
  set NLPP_SKIP_SOURCE_FETCH=1
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP_NAME = ".nlpp_main_sha"
DEFAULT_SOURCE_REPO = "czyrustuazon/NewLovePlusPlusEngPatcher"
DEFAULT_REF = "main"

# Top-level names we never replace from the zipball.
PROTECTED_TOP = frozenset(
    {
        "out",
        "release",
        "cache",
        ".git",
        ".venv",
        "venv",
        ".env",
        STAMP_NAME,
        ".mcp.json",
        "ghidra_nlpp",
        "__pycache__",
        ".pytest_cache",
        "conversation-archive",
    }
)

def _default_source_repo() -> str:
    for key in ("NLPP_SOURCE_REPO", "NLPP_ENG_PATCHER_REPO"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return DEFAULT_SOURCE_REPO


def github_reachable(timeout: float = 5.0) -> bool:
    """True when github.com:443 accepts a TCP connection."""
    import socket

    try:
        with socket.create_connection(("github.com", 443), timeout=timeout):
            return True
    except OSError:
        return False


def _urlopen(url: str, token: str | None):
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "nlpp-fetch-main-tree")
    if token and "github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
        if "api.github.com" in url:
            req.add_header("Accept", "application/vnd.github+json")
    return urllib.request.urlopen(req, timeout=600)


def _read_url(url: str, token: str | None) -> bytes:
    with _urlopen(url, token) as resp:
        return resp.read()


def _download_file(url: str, dest: Path, token: str | None, *, dry_run: bool) -> None:
    print(f"[fetch] {url}", flush=True)
    print(f"     -> {dest}", flush=True)
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    try:
        with _urlopen(url, token) as resp, tmp.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    print(f"[fetch] wrote {dest.stat().st_size:,} bytes", flush=True)


def remote_head_sha(repo: str, ref: str, token: str | None) -> str:
    """Resolve ``ref`` to a full commit SHA via the GitHub API."""
    api = f"https://api.github.com/repos/{repo}/commits/{ref}"
    meta = json.loads(_read_url(api, token).decode("utf-8"))
    sha = meta.get("sha")
    if not sha or not isinstance(sha, str):
        raise LookupError(f"no commit sha for {repo}@{ref}")
    return sha


def _read_stamp(root: Path) -> str | None:
    path = root / STAMP_NAME
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text or None


def _write_stamp(root: Path, sha: str) -> None:
    (root / STAMP_NAME).write_text(sha + "\n", encoding="utf-8")


def _is_protected(rel_posix: str) -> bool:
    if not rel_posix or rel_posix in (".",):
        return True
    top = rel_posix.split("/", 1)[0]
    if top in PROTECTED_TOP:
        return True
    if rel_posix == ".env" or rel_posix.endswith("/.env"):
        return True
    name = rel_posix.rsplit("/", 1)[-1]
    if name in {"__pycache__", ".pytest_cache"} or name.endswith(".pyc"):
        return True
    if rel_posix.startswith("ab_test/azahar_instances/"):
        return True
    if rel_posix.startswith("ab_test/saves/"):
        return True
    if rel_posix == "ab_test/paths.local.ps1":
        return True
    return False


def _zip_inner_root(extract_dir: Path) -> Path:
    kids = [p for p in extract_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if len(kids) == 1:
        return kids[0]
    return extract_dir


def overlay_tree(src_root: Path, dst_root: Path, *, dry_run: bool) -> int:
    """Copy files from extracted zip root onto dst. Returns files written."""
    written = 0
    for path in src_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src_root).as_posix()
        if _is_protected(rel):
            continue
        dest = dst_root / Path(*rel.split("/"))
        if dry_run:
            written += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        written += 1
    return written


def try_fetch_main_tree(
    *,
    repo: str | None,
    ref: str,
    token: str | None,
    root: Path,
    force: bool = False,
    dry_run: bool = False,
    skip_git_checkout: bool = True,
) -> tuple[str, str]:
    """Return (status, message).

    status is one of: ``updated``, ``current``, ``skipped``, ``unavailable``.
    """
    root = root.resolve()
    if skip_git_checkout and (root / ".git").exists():
        if os.environ.get("NLPP_FORCE_SOURCE_FETCH", "").strip() not in (
            "1",
            "true",
            "yes",
        ):
            return (
                "skipped",
                "git checkout present — skip zip sync "
                "(set NLPP_FORCE_SOURCE_FETCH=1 to override)",
            )

    if os.environ.get("NLPP_SKIP_SOURCE_FETCH", "").strip() in ("1", "true", "yes"):
        return "skipped", "NLPP_SKIP_SOURCE_FETCH=1"

    if not repo:
        return "unavailable", "no source repo (set NLPP_SOURCE_REPO)"

    if not github_reachable():
        return "unavailable", "no internet (github.com:443 unreachable)"

    print(f"[fetch] checking {repo} @{ref}", flush=True)
    try:
        sha = remote_head_sha(repo, ref, token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "unavailable", f"no commit {ref!r} on {repo} (404)"
        return "unavailable", f"GitHub HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return "unavailable", f"network error: {exc.reason}"
    except (LookupError, OSError, json.JSONDecodeError, UnicodeError) as exc:
        return "unavailable", str(exc)

    local = _read_stamp(root)
    if local and local.lower() == sha.lower() and not force:
        return "current", f"already at {sha[:12]}"

    zip_url = f"https://codeload.github.com/{repo}/zip/refs/heads/{ref}"
    print(f"[fetch] downloading EngPatcher sources ({sha[:12]})…", flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="nlpp_main_") as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "main.zip"
            _download_file(zip_url, zip_path, token, dry_run=dry_run)
            if dry_run:
                return "updated", f"dry-run would sync to {sha[:12]}"
            extract_dir = tmp_path / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
            inner = _zip_inner_root(extract_dir)
            if not (inner / "Drop CIA or 3DS Here to Patch.bat").is_file() and not (
                inner / "src"
            ).is_dir():
                return "unavailable", f"zipball missing EngPatcher root under {inner}"
            n = overlay_tree(inner, root, dry_run=False)
            _write_stamp(root, sha)
            return "updated", f"synced {n} files from {repo}@{ref} ({sha[:12]})"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "unavailable", f"zipball 404 for {repo}@{ref}"
        return "unavailable", f"GitHub HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return "unavailable", f"network error: {exc.reason}"
    except (OSError, zipfile.BadZipFile) as exc:
        return "unavailable", str(exc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--repo",
        default=_default_source_repo(),
        help=(
            "OWNER/NewLovePlusPlusEngPatcher "
            f"(default: {DEFAULT_SOURCE_REPO}, or NLPP_SOURCE_REPO)"
        ),
    )
    ap.add_argument(
        "--ref",
        default=os.environ.get("NLPP_SOURCE_REF", DEFAULT_REF),
        help="Branch or commit-ish (default: main, or NLPP_SOURCE_REF)",
    )
    ap.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
        help="Optional GitHub token (higher rate limits)",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="EngPatcher root to overlay (default: this repo)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Redownload even when .nlpp_main_sha matches tip",
    )
    ap.add_argument(
        "--best-effort",
        action="store_true",
        help=(
            "For Drop CIA: exit 0 when current/skipped/unavailable; "
            "exit 2 when the tree was updated (caller re-execs once)"
        ),
    )
    args = ap.parse_args(argv)

    status, msg = try_fetch_main_tree(
        repo=args.repo,
        ref=args.ref,
        token=args.token,
        root=args.root,
        force=args.force,
        dry_run=args.dry_run,
    )
    print(f"[fetch] {status}: {msg}", flush=True)

    if status == "updated":
        return 2 if args.best_effort else 0
    if status in ("current", "skipped"):
        return 0
    # unavailable
    if args.best_effort:
        return 0
    raise SystemExit(msg)


if __name__ == "__main__":
    raise SystemExit(main())
