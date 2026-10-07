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


def test_default_gold_repo_is_public_without_git(tmp_path, monkeypatch):
    """Zip downloads have no origin. The public gold repo is still the default."""
    monkeypatch.delenv("NLPP_GITHUB_REPO", raising=False)
    monkeypatch.delenv("NLPP_GOLD_REPO", raising=False)
    with patch.object(fetch_mod, "ROOT", tmp_path):
        assert fetch_mod._default_gold_repo() == "czyrustuazon/nlpp-gold-maker"
        assert fetch_mod.DEFAULT_GOLD_REPO == "czyrustuazon/nlpp-gold-maker"


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


def test_try_fetch_gold_offline_skips_download(release_dir: Path):
    def fail_urlopen(_url, _token):
        raise AssertionError("offline fetch must not call GitHub")

    with (
        patch.object(fetch_mod, "github_reachable", return_value=False),
        patch.object(fetch_mod, "_urlopen", fail_urlopen),
    ):
        ok, msg = fetch_mod.try_fetch_gold(
            repo="owner/nlpp-gold",
            tag="gold",
            token=None,
            out_dir=release_dir,
        )
    assert ok is False
    assert "no internet" in msg
    assert not (release_dir / "bake_img.bin").exists()


def test_try_fetch_gold_404_falls_back(release_dir: Path):
    def raise_404(_url, _token):
        raise urllib.error.HTTPError(
            "https://api.github.com/x", 404, "Not Found", hdrs=None, fp=None
        )

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_urlopen", raise_404),
    ):
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

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_urlopen", fake_urlopen),
    ):
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
    assert not (release_dir / "name_input_code.bin").exists()


def test_try_fetch_gold_downloads_name_input_when_published(release_dir: Path):
    overlay_payload = io.BytesIO()
    with zipfile.ZipFile(overlay_payload, "w") as zf:
        zf.writestr("romfs_overlay/marker.txt", b"ok")
    overlay_bytes = overlay_payload.getvalue()
    urls = {
        "bake_img.bin": "https://example.test/bake_img.bin",
        "romfs_overlay.zip": "https://example.test/romfs_overlay.zip",
        "name_input_code.bin": "https://example.test/name_input_code.bin",
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
        if url.endswith("name_input_code.bin"):
            return b"NAME_CODE"
        raise AssertionError(f"unexpected url: {url}")

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_urlopen", fake_urlopen),
    ):
        ok, msg = fetch_mod.try_fetch_gold(
            repo="owner/nlpp-gold",
            tag="gold",
            token=None,
            out_dir=release_dir,
            force=True,
        )

    assert ok is True
    assert "downloaded" in msg
    assert (release_dir / "name_input_code.bin").read_bytes() == b"NAME_CODE"


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

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_urlopen", raise_404),
    ):
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

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_urlopen", raise_404),
    ):
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


def _gold_urlopen(body: str | None):
    overlay_payload = io.BytesIO()
    with zipfile.ZipFile(overlay_payload, "w") as zf:
        zf.writestr("romfs_overlay/marker.txt", b"ok")
    overlay_bytes = overlay_payload.getvalue()
    urls = {
        "bake_img.bin": "https://example.test/bake_img.bin",
        "romfs_overlay.zip": "https://example.test/romfs_overlay.zip",
    }

    def fake_urlopen(url, _token):
        if "releases" in url:
            assets = [{"name": k, "browser_download_url": v} for k, v in urls.items()]
            return json.dumps({"assets": assets, "body": body}).encode()
        if url.endswith("bake_img.bin"):
            return b"GOLD_BAKE"
        if url.endswith("romfs_overlay.zip"):
            return overlay_bytes
        raise AssertionError(f"unexpected url: {url}")

    return fake_urlopen


GOLD_BODY = (
    "Rolling gold bake from EngPatcher.\r\n"
    "engpatcher_sha: 6993c00fedd7c49131516cf64ede698ca7f40bc3\r\n"
    "pack: full"
)


def _fetch(release_dir: Path, body: str | None, expected_sha: str | None):
    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_urlopen", _gold_urlopen(body)),
    ):
        return fetch_mod.try_fetch_gold(
            repo="owner/nlpp-gold",
            tag="gold",
            token=None,
            out_dir=release_dir,
            force=True,
            expected_sha=expected_sha,
        )


def test_gold_accepted_when_engpatcher_sha_matches(release_dir: Path):
    ok, msg = _fetch(release_dir, GOLD_BODY, "6993c00fedd7c49131516cf64ede698ca7f40bc3")
    assert ok is True
    assert (release_dir / "bake_img.bin").read_bytes() == b"GOLD_BAKE"


def test_gold_refused_when_engpatcher_sha_differs(release_dir: Path):
    ok, msg = _fetch(release_dir, GOLD_BODY, "1f288df0000000000000000000000000000000aa")
    assert ok is False
    assert "6993c00fedd7" in msg and "1f288df00000" in msg
    assert not (release_dir / "bake_img.bin").exists()


def test_gold_refused_when_release_has_no_sha(release_dir: Path):
    ok, msg = _fetch(release_dir, "no sha here", "6993c00fedd7c49131516cf64ede698ca7f40bc3")
    assert ok is False
    assert "does not record engpatcher_sha" in msg
    assert not (release_dir / "bake_img.bin").exists()


def test_gold_unchecked_without_local_stamp(release_dir: Path):
    ok, _ = _fetch(release_dir, None, None)
    assert ok is True


def test_main_reads_stamp_and_any_sha_overrides(release_dir: Path, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("NLPP_GOLD_ANY_SHA", raising=False)
    stamp = tmp_path / ".nlpp_main_sha"
    stamp.write_text("1f288df0000000000000000000000000000000aa\n", encoding="utf-8")
    args = ["--best-effort", "--force", "--out-dir", str(release_dir), "--repo", "owner/nlpp-gold"]
    with (
        patch.object(fetch_mod, "MAIN_SHA_STAMP", stamp),
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_urlopen", _gold_urlopen(GOLD_BODY)),
    ):
        assert fetch_mod.main(args) == 1
        assert fetch_mod.main(args + ["--any-sha"]) == 0
