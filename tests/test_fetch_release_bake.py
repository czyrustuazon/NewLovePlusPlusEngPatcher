"""Tests for CI gold-bake fetch + best-effort fallback."""

from __future__ import annotations

import io
import json
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import TOOLS, load_module

fetch_mod = load_module("fetch_release_bake", TOOLS / "fetch_release_bake.py")


@pytest.fixture
def release_dir(tmp_path: Path) -> Path:
    out = tmp_path / "release"
    out.mkdir()
    return out


def test_default_gold_repo_from_env(monkeypatch):
    monkeypatch.setenv("NLPP_GITHUB_REPO", "acme/nlpp-gold")
    monkeypatch.delenv("NLPP_GOLD_REPO", raising=False)
    assert fetch_mod._default_gold_repo() == "acme/nlpp-gold"


def test_default_gold_repo_derives_owner_from_git(tmp_path, monkeypatch):
    monkeypatch.delenv("NLPP_GITHUB_REPO", raising=False)
    monkeypatch.delenv("NLPP_GOLD_REPO", raising=False)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:myowner/NewLovePlusPlusEngPatcher.git\n',
        encoding="utf-8",
    )
    with patch.object(fetch_mod, "ROOT", tmp_path):
        assert fetch_mod._default_gold_repo() == "myowner/nlpp-gold"


def test_github_asset_urls_requires_both_assets():
    meta = {
        "assets": [{"name": "bake_img.bin", "browser_download_url": "https://x/bake"}]
    }

    def fake_urlopen(_url, _token):
        return json.dumps(meta).encode()

    with patch.object(fetch_mod, "_urlopen", fake_urlopen):
        with pytest.raises(LookupError, match="romfs_overlay.zip"):
            fetch_mod._github_asset_urls("owner/nlpp-gold", "gold", None)


def test_try_fetch_gold_already_present(release_dir: Path):
    bake = release_dir / "bake_img.bin"
    overlay = release_dir / "romfs_overlay"
    bake.write_bytes(b"bake")
    overlay.mkdir()
    (overlay / "SystemData").mkdir()

    ok, msg = fetch_mod.try_fetch_gold(
        repo="owner/nlpp-gold",
        tag="gold",
        token=None,
        out_dir=release_dir,
    )
    assert ok is True
    assert "already present" in msg


def test_try_fetch_gold_no_repo(release_dir: Path):
    ok, msg = fetch_mod.try_fetch_gold(
        repo=None,
        tag="gold",
        token=None,
        out_dir=release_dir,
    )
    assert ok is False
    assert "no gold repo" in msg


def test_try_fetch_gold_404_falls_back(release_dir: Path):
    def raise_404(_url, _token):
        raise urllib.error.HTTPError(
            "https://api.github.com/x", 404, "Not Found", hdrs=None, fp=None
        )

    with patch.object(fetch_mod, "_urlopen", raise_404):
        ok, msg = fetch_mod.try_fetch_gold(
            repo="owner/nlpp-gold",
            tag="gold",
            token=None,
            out_dir=release_dir,
        )
    assert ok is False
    assert "404" in msg
    assert not (release_dir / "bake_img.bin").exists()


def test_try_fetch_gold_downloads_and_extracts_overlay(release_dir: Path):
    overlay_payload = io.BytesIO()
    with zipfile.ZipFile(overlay_payload, "w") as zf:
        zf.writestr(
            "romfs_overlay/SystemData/TextResource/textresource_jpn.trb",
            b"trb",
        )
    overlay_bytes = overlay_payload.getvalue()

    urls = {
        "bake_img.bin": "https://example.test/bake_img.bin",
        "romfs_overlay.zip": "https://example.test/romfs_overlay.zip",
    }

    def fake_urlopen(url, _token):
        if "releases" in url:
            assets = [
                {"name": k, "browser_download_url": v} for k, v in urls.items()
            ]
            return json.dumps({"assets": assets}).encode()
        if url.endswith("bake_img.bin"):
            return b"GOLD_BAKE"
        if url.endswith("romfs_overlay.zip"):
            return overlay_bytes
        raise AssertionError(f"unexpected url: {url}")

    with patch.object(fetch_mod, "_urlopen", fake_urlopen):
        ok, msg = fetch_mod.try_fetch_gold(
            repo="owner/nlpp-gold",
            tag="gold",
            token=None,
            out_dir=release_dir,
            force=True,
        )

    assert ok is True
    assert "downloaded" in msg
    assert (release_dir / "bake_img.bin").read_bytes() == b"GOLD_BAKE"
    trb = (
        release_dir
        / "romfs_overlay"
        / "SystemData"
        / "TextResource"
        / "textresource_jpn.trb"
    )
    assert trb.is_file()


def test_main_best_effort_exits_0_on_success(release_dir: Path):
    bake = release_dir / "bake_img.bin"
    overlay = release_dir / "romfs_overlay"
    bake.write_bytes(b"x")
    overlay.mkdir()

    rc = fetch_mod.main(
        ["--best-effort", "--out-dir", str(release_dir), "--repo", "owner/nlpp-gold"]
    )
    assert rc == 0


def test_main_best_effort_exits_1_when_ci_missing(release_dir: Path):
    def raise_404(_url, _token):
        raise urllib.error.HTTPError(
            "https://api.github.com/x", 404, "Not Found", hdrs=None, fp=None
        )

    with patch.object(fetch_mod, "_urlopen", raise_404):
        rc = fetch_mod.main(
            [
                "--best-effort",
                "--force",
                "--out-dir",
                str(release_dir),
                "--repo",
                "owner/nlpp-gold",
            ]
        )
    assert rc == 1


def test_main_without_best_effort_raises_on_missing(release_dir: Path):
    def raise_404(_url, _token):
        raise urllib.error.HTTPError(
            "https://api.github.com/x", 404, "Not Found", hdrs=None, fp=None
        )

    with patch.object(fetch_mod, "_urlopen", raise_404):
        with pytest.raises(SystemExit, match="404"):
            fetch_mod.main(
                [
                    "--force",
                    "--out-dir",
                    str(release_dir),
                    "--repo",
                    "owner/nlpp-gold",
                ]
            )
