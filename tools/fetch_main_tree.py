#!/usr/bin/env python3
"""Best-effort sync of this EngPatcher tree from GitHub ``main`` (no git).

End users typically start from a Release zip
(``NewLovePlusPlusEngPatcher-main.zip``). Drop CIA then overlays the tip of
``main`` via the public zipball so they pick up script/asset fixes without
installing git.

Never touches ``out/``, ``release/``, ``cache/``, ``.env``, local a/b paths,
or a ``.git`` checkout (contributors keep using git). Offline / 404 / errors
are soft under ``--best-effort``.

The tree is mirrored to ``main`` the way git sees it: any file that is not in
the zipball and not ignored by its ``.gitignore`` files is deleted, so a script
removed on ``main`` (or one left over from an older Release zip) does not
linger. Ignored paths (downloaded tools, ``paths.local.*``, dumps) are kept.

``.nlpp_main_files`` stores a SHA-256 per synced file. When the stamp already
matches ``main``, the tree is still checked against it; an edited, missing or
extra file triggers a fresh sync instead of reporting ``current``.

Examples:
  python tools/fetch_main_tree.py --best-effort
  python tools/fetch_main_tree.py --force
  set NLPP_SKIP_SOURCE_FETCH=1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP_NAME = ".nlpp_main_sha"
MANIFEST_NAME = ".nlpp_main_files"
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
        MANIFEST_NAME,
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


def _read_manifest_hashes(root: Path) -> dict[str, str | None] | None:
    """``{rel: sha256}``. Older manifests list bare paths (hash ``None``)."""
    path = root / MANIFEST_NAME
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, str | None] = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        digest, sep, rel = ln.partition("\t")
        if sep:
            out[rel] = digest
        else:
            out[ln] = None
    return out


def _read_manifest(root: Path) -> set[str] | None:
    hashes = _read_manifest_hashes(root)
    return None if hashes is None else set(hashes)


def _write_manifest(root: Path, hashes: dict[str, str]) -> None:
    body = "".join(f"{hashes[rel]}\t{rel}\n" for rel in sorted(hashes))
    (root / MANIFEST_NAME).write_text(body, encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _glob_to_regex(pat: str) -> str:
    """Translate one gitignore glob (no leading ``/``) to a regex body."""
    out: list[str] = []
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 == len(pat):
            out.append("/.*")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        elif pat[i] == "[":
            end = pat.find("]", i + 1)
            if end < 0:
                out.append(re.escape("["))
                i += 1
            else:
                body = pat[i + 1 : end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = end + 1
        elif pat[i] == "\\" and i + 1 < len(pat):
            out.append(re.escape(pat[i + 1]))
            i += 2
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return "".join(out)


class GitIgnore:
    """Enough of gitignore(5) for this repo's ignore files (stdlib only;
    this runs before Drop CIA installs requirements).

    Rules are ``(base, regex, negate, dir_only)``; ``base`` is the folder of
    the ``.gitignore`` they came from. Last match wins, and a file inside an
    ignored folder stays ignored, as in git.
    """

    def __init__(self) -> None:
        self.rules: list[tuple[str, re.Pattern[str], bool, bool]] = []

    @classmethod
    def from_tree(cls, root: Path, rels: list[str]) -> GitIgnore:
        ign = cls()
        files = [r for r in rels if r.rsplit("/", 1)[-1] == ".gitignore"]
        for rel in sorted(files, key=lambda r: (r.count("/"), r)):
            base = rel.rsplit("/", 1)[0] if "/" in rel else ""
            text = (root / Path(*rel.split("/"))).read_text(
                encoding="utf-8", errors="replace"
            )
            ign.add(base, text)
        return ign

    def add(self, base: str, text: str) -> None:
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!")
            if negate:
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            if not line:
                continue
            anchored = "/" in line
            line = line.lstrip("/")
            body = _glob_to_regex(line)
            if not anchored:
                body = "(?:.*/)?" + body
            self.rules.append((base, re.compile(body + r"\Z", re.S), negate, dir_only))

    def _match(self, rel: str, is_dir: bool) -> bool:
        ignored = False
        for base, rx, negate, dir_only in self.rules:
            if dir_only and not is_dir:
                continue
            if base:
                if not rel.startswith(base + "/"):
                    continue
                sub = rel[len(base) + 1 :]
            else:
                sub = rel
            if rx.match(sub):
                ignored = not negate
        return ignored

    def is_ignored(self, rel: str, *, is_dir: bool = False) -> bool:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            if self._match("/".join(parts[:i]), True):
                return True
        return self._match(rel, is_dir)


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


def overlay_tree(src_root: Path, dst_root: Path, *, dry_run: bool) -> list[str]:
    """Copy files from extracted zip root onto dst. Returns rel paths written."""
    written: list[str] = []
    for path in src_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src_root).as_posix()
        if _is_protected(rel):
            continue
        written.append(rel)
        if dry_run:
            continue
        dest = dst_root / Path(*rel.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return written


def prune_removed(root: Path, previous: set[str], current: set[str]) -> list[str]:
    """Delete files an earlier sync wrote that ``main`` no longer ships.

    Only paths listed in the previous manifest are candidates, so files the
    user added are never touched. Emptied parent folders are removed too.
    """
    root = root.resolve()
    removed: list[str] = []
    for rel in sorted(previous - current):
        if _is_protected(rel) or ".." in rel.split("/"):
            continue
        path = root / Path(*rel.split("/"))
        if not path.is_file():
            continue
        path.unlink()
        removed.append(rel)
        _rmdir_empty_parents(root, path)
    return removed


def _rmdir_empty_parents(root: Path, path: Path) -> None:
    parent = path.parent
    while parent != root and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def find_untracked(root: Path, shipped: set[str], ignore: GitIgnore) -> list[str]:
    """Files under ``root`` that ``main`` does not ship and does not ignore.

    Like git, a local ``.gitignore`` (``.ruff_cache/`` writes one) also counts.
    """
    root = root.resolve()
    ignore_local = GitIgnore()
    ignore_local.rules = list(ignore.rules)
    ignore = ignore_local
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        local_rel = f"{rel_dir}/.gitignore" if rel_dir else ".gitignore"
        if ".gitignore" in filenames and local_rel not in shipped:
            text = (Path(dirpath) / ".gitignore").read_text(encoding="utf-8", errors="replace")
            ignore.add(rel_dir, text)
        keep_dirs = []
        for name in dirnames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if _is_protected(rel) or ignore.is_ignored(rel, is_dir=True):
                continue
            keep_dirs.append(name)
        dirnames[:] = keep_dirs
        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if rel in shipped or _is_protected(rel) or ignore.is_ignored(rel):
                continue
            found.append(rel)
    return sorted(found)


def remove_untracked(root: Path, shipped: set[str], ignore: GitIgnore) -> list[str]:
    """Delete what :func:`find_untracked` reports; returns the deleted paths."""
    root = root.resolve()
    removed = find_untracked(root, shipped, ignore)
    for rel in removed:
        path = root / Path(*rel.split("/"))
        path.unlink()
        _rmdir_empty_parents(root, path)
    return removed


def tree_drift(root: Path) -> str | None:
    """Why the tree no longer matches the last sync, or ``None`` when it does.

    Hashes every synced file and looks for extra files git would see as
    untracked. Old bare-path manifests always count as drift so the next
    run upgrades them.
    """
    root = root.resolve()
    hashes = _read_manifest_hashes(root)
    if not hashes:
        return "no file manifest from an earlier sync"
    if any(digest is None for digest in hashes.values()):
        return "file manifest predates hashes"
    changed = 0
    for rel, digest in hashes.items():
        path = root / Path(*rel.split("/"))
        if not path.is_file() or _sha256(path) != digest:
            changed += 1
    extra = 0
    if not (root / ".git").exists():
        ignore = GitIgnore.from_tree(root, [r for r in hashes if (root / r).is_file()])
        extra = len(find_untracked(root, set(hashes), ignore))
    if not changed and not extra:
        return None
    return f"{changed} changed or missing, {extra} extra file(s)"


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
        drift = tree_drift(root)
        if drift is None:
            return "current", f"already at {sha[:12]}"
        print(f"[fetch] local tree differs from {sha[:12]} ({drift}) - resyncing", flush=True)

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
            if not (inner / ".gitignore").is_file():
                return "unavailable", f"zipball missing .gitignore under {inner}"
            previous = _read_manifest(root)
            written = overlay_tree(inner, root, dry_run=False)
            shipped = set(written)
            removed: list[str] = []
            if previous is not None:
                removed = prune_removed(root, previous, shipped)
            # A forced sync into a git checkout must not delete uncommitted work.
            if not (root / ".git").exists():
                ignore = GitIgnore.from_tree(inner, written)
                removed += remove_untracked(root, shipped, ignore)
            for rel in removed:
                print(f"[fetch] removed (not on {ref}): {rel}", flush=True)
            _write_manifest(
                root, {rel: _sha256(inner / Path(*rel.split("/"))) for rel in written}
            )
            _write_stamp(root, sha)
            note = f", removed {len(removed)}" if removed else ""
            return (
                "updated",
                f"synced {len(written)} files{note} from {repo}@{ref} ({sha[:12]})",
            )
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
