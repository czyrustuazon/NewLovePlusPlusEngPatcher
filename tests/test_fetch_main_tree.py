"""Tests for best-effort EngPatcher main zipball sync (no git)."""

from __future__ import annotations

import io
import json
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import TOOLS, load_module

fetch_mod = load_module("fetch_main_tree", TOOLS / "fetch_main_tree.py")


def _make_zipball(files: dict[str, bytes], *, folder: str = "NewLovePlusPlusEngPatcher-main") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for rel, data in files.items():
            zf.writestr(f"{folder}/{rel}", data)
    return buf.getvalue()


@pytest.fixture
def patcher_root(tmp_path: Path) -> Path:
    root = tmp_path / "eng"
    (root / "src").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "Drop CIA or 3DS Here to Patch.bat").write_text("@echo off\n", encoding="utf-8")
    (root / "src" / "drop_zone.ps1").write_text("# old\n", encoding="utf-8")
    return root


def test_default_source_repo_from_env(monkeypatch):
    monkeypatch.setenv("NLPP_SOURCE_REPO", "acme/EngPatcher")
    monkeypatch.delenv("NLPP_ENG_PATCHER_REPO", raising=False)
    assert fetch_mod._default_source_repo() == "acme/EngPatcher"


def test_default_source_repo_public(monkeypatch):
    monkeypatch.delenv("NLPP_SOURCE_REPO", raising=False)
    monkeypatch.delenv("NLPP_ENG_PATCHER_REPO", raising=False)
    assert fetch_mod._default_source_repo() == "czyrustuazon/NewLovePlusPlusEngPatcher"


def test_skips_git_checkout(patcher_root: Path, monkeypatch):
    (patcher_root / ".git").mkdir()
    monkeypatch.delenv("NLPP_FORCE_SOURCE_FETCH", raising=False)
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)

    with patch.object(fetch_mod, "github_reachable", return_value=True):
        status, msg = fetch_mod.try_fetch_main_tree(
            repo="owner/repo",
            ref="main",
            token=None,
            root=patcher_root,
        )
    assert status == "skipped"
    assert "git checkout" in msg


def test_skips_when_env_set(patcher_root: Path, monkeypatch):
    monkeypatch.setenv("NLPP_SKIP_SOURCE_FETCH", "1")
    status, msg = fetch_mod.try_fetch_main_tree(
        repo="owner/repo",
        ref="main",
        token=None,
        root=patcher_root,
    )
    assert status == "skipped"
    assert "NLPP_SKIP_SOURCE_FETCH" in msg


def test_unavailable_offline(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    monkeypatch.delenv("NLPP_FORCE_SOURCE_FETCH", raising=False)

    def fail_urlopen(*_a, **_k):
        raise AssertionError("offline must not call GitHub")

    with (
        patch.object(fetch_mod, "github_reachable", return_value=False),
        patch.object(fetch_mod, "_urlopen", fail_urlopen),
    ):
        status, msg = fetch_mod.try_fetch_main_tree(
            repo="owner/repo",
            ref="main",
            token=None,
            root=patcher_root,
        )
    assert status == "unavailable"
    assert "no internet" in msg


def test_current_when_stamp_matches(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    sha = "abc123def4567890"
    (patcher_root / fetch_mod.STAMP_NAME).write_text(sha + "\n", encoding="utf-8")

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "remote_head_sha", return_value=sha),
    ):
        status, msg = fetch_mod.try_fetch_main_tree(
            repo="owner/repo",
            ref="main",
            token=None,
            root=patcher_root,
        )
    assert status == "current"
    assert "already at" in msg


def test_overlay_protects_out_release_cache_and_env(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    sha = "deadbeef01234567"
    (patcher_root / "out").mkdir()
    (patcher_root / "out" / "keep.txt").write_text("local-out", encoding="utf-8")
    (patcher_root / "release").mkdir()
    (patcher_root / "release" / "bake_img.bin").write_bytes(b"BAKE")
    (patcher_root / "cache").mkdir()
    (patcher_root / "cache" / "x.bin").write_bytes(b"CACHE")
    (patcher_root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (patcher_root / "ab_test").mkdir()
    (patcher_root / "ab_test" / "paths.local.ps1").write_text("$local=1\n", encoding="utf-8")

    zip_bytes = _make_zipball(
        {
            "Drop CIA or 3DS Here to Patch.bat": b"@echo off\nREM new\n",
            "src/drop_zone.ps1": b"# new\n",
            "src/patch_cia.py": b"# patched\n",
            "out/keep.txt": b"ZIP-OUT",
            "release/bake_img.bin": b"ZIP-BAKE",
            "cache/x.bin": b"ZIP-CACHE",
            ".env": b"SECRET=zip\n",
            "ab_test/paths.local.ps1": b"$zip=1\n",
        }
    )

    def fake_read(url: str, _token):
        if "commits" in url:
            return json.dumps({"sha": sha}).encode()
        raise AssertionError(url)

    def fake_download(url, dest, token, *, dry_run):
        assert "codeload.github.com" in url
        assert not dry_run
        dest.write_bytes(zip_bytes)

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_read_url", fake_read),
        patch.object(fetch_mod, "_download_file", fake_download),
    ):
        status, msg = fetch_mod.try_fetch_main_tree(
            repo="owner/repo",
            ref="main",
            token=None,
            root=patcher_root,
            force=True,
        )

    assert status == "updated"
    assert "synced" in msg
    assert (patcher_root / "src" / "drop_zone.ps1").read_text(encoding="utf-8") == "# new\n"
    assert (patcher_root / "src" / "patch_cia.py").read_text(encoding="utf-8") == "# patched\n"
    assert (patcher_root / "out" / "keep.txt").read_text(encoding="utf-8") == "local-out"
    assert (patcher_root / "release" / "bake_img.bin").read_bytes() == b"BAKE"
    assert (patcher_root / "cache" / "x.bin").read_bytes() == b"CACHE"
    assert (patcher_root / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert (patcher_root / "ab_test" / "paths.local.ps1").read_text(encoding="utf-8") == "$local=1\n"
    assert (patcher_root / fetch_mod.STAMP_NAME).read_text(encoding="utf-8").strip() == sha


def test_404_is_unavailable(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)

    def raise_404(url, _token):
        raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_read_url", raise_404),
    ):
        status, msg = fetch_mod.try_fetch_main_tree(
            repo="owner/repo",
            ref="main",
            token=None,
            root=patcher_root,
        )
    assert status == "unavailable"
    assert "404" in msg


def test_main_best_effort_exit_codes(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    monkeypatch.setenv("NLPP_SKIP_SOURCE_FETCH", "1")
    assert fetch_mod.main(["--best-effort", "--root", str(patcher_root)]) == 0

    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    sha = "1111222233334444"
    zip_bytes = _make_zipball(
        {
            "Drop CIA or 3DS Here to Patch.bat": b"@echo off\n",
            "src/drop_zone.ps1": b"#\n",
        }
    )

    def fake_read(url: str, _token):
        return json.dumps({"sha": sha}).encode()

    def fake_download(url, dest, token, *, dry_run):
        dest.write_bytes(zip_bytes)

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_read_url", fake_read),
        patch.object(fetch_mod, "_download_file", fake_download),
    ):
        rc = fetch_mod.main(
            ["--best-effort", "--force", "--root", str(patcher_root), "--repo", "owner/repo"]
        )
    assert rc == 2

    with (
        patch.object(fetch_mod, "github_reachable", return_value=False),
    ):
        rc = fetch_mod.main(
            ["--best-effort", "--force", "--root", str(patcher_root), "--repo", "owner/repo"]
        )
    assert rc == 0
