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


GITIGNORE = b"out/\ncache/\ntools/*\n!tools/fetch_main_tree.py\n*.cia\n"
BAT = b"@echo off\n"


def _make_zipball(files: dict[str, bytes], *, folder: str = "NewLovePlusPlusEngPatcher-main") -> bytes:
    files = {".gitignore": GITIGNORE, **files}
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


def _sync(patcher_root: Path, files: dict[str, bytes], sha: str):
    zip_bytes = _make_zipball(files)

    def fake_read(url: str, _token):
        return json.dumps({"sha": sha}).encode()

    def fake_download(url, dest, token, *, dry_run):
        dest.write_bytes(zip_bytes)

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_read_url", fake_read),
        patch.object(fetch_mod, "_download_file", fake_download),
    ):
        return fetch_mod.try_fetch_main_tree(
            repo="owner/repo", ref="main", token=None, root=patcher_root
        )


def test_current_when_stamp_and_files_match(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    files = {"Drop CIA or 3DS Here to Patch.bat": BAT, "src/drop_zone.ps1": b"# old\n"}
    assert _sync(patcher_root, files, "abc123def4567890")[0] == "updated"

    status, msg = _sync(patcher_root, files, "abc123def4567890")
    assert status == "current"
    assert "already at" in msg


def test_prunes_files_removed_from_main(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    status, _ = _sync(
        patcher_root,
        {
            "Drop CIA or 3DS Here to Patch.bat": BAT,
            "src/keep.py": b"# keep\n",
            "assets/scripts/old/t999.xml": b"<old/>",
        },
        "aaaa000000000001",
    )
    assert status == "updated"

    status, msg = _sync(
        patcher_root,
        {"Drop CIA or 3DS Here to Patch.bat": BAT, "src/keep.py": b"# keep 2\n"},
        "aaaa000000000002",
    )
    assert status == "updated"
    assert "removed 1" in msg
    assert not (patcher_root / "assets").exists()
    assert (patcher_root / "src" / "keep.py").read_text(encoding="utf-8") == "# keep 2\n"
    manifest = fetch_mod._read_manifest(patcher_root)
    assert manifest == {".gitignore", "Drop CIA or 3DS Here to Patch.bat", "src/keep.py"}


def test_first_sync_mirrors_release_zip_leftovers(patcher_root: Path, monkeypatch):
    """A Release zip has no manifest; files main dropped since then still go."""
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    status, msg = _sync(
        patcher_root, {"Drop CIA or 3DS Here to Patch.bat": BAT}, "bbbb000000000001"
    )
    assert status == "updated"
    assert "removed 1" in msg
    assert not (patcher_root / "src").exists()


def test_mirror_keeps_ignored_and_protected_files(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    (patcher_root / "tools" / "3dstool.exe").write_bytes(b"MZ")
    (patcher_root / "game.cia").write_bytes(b"CIA")
    (patcher_root / "out").mkdir()
    (patcher_root / "out" / "x.bin").write_bytes(b"OUT")
    (patcher_root / ".ruff_cache").mkdir()
    (patcher_root / ".ruff_cache" / ".gitignore").write_text("*\n", encoding="utf-8")
    (patcher_root / ".ruff_cache" / "blob").write_bytes(b"R")
    (patcher_root / "src" / "mine.py").write_text("# stray\n", encoding="utf-8")

    status, _ = _sync(
        patcher_root,
        {"Drop CIA or 3DS Here to Patch.bat": BAT, "tools/fetch_main_tree.py": b"#\n"},
        "cccc000000000001",
    )
    assert status == "updated"
    assert (patcher_root / "tools" / "3dstool.exe").is_file()
    assert (patcher_root / "game.cia").is_file()
    assert (patcher_root / "out" / "x.bin").is_file()
    assert (patcher_root / ".ruff_cache" / "blob").is_file()
    assert not (patcher_root / "src" / "mine.py").exists()
    assert not (patcher_root / "src" / "drop_zone.ps1").exists()


def test_forced_sync_into_git_checkout_keeps_untracked(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    monkeypatch.setenv("NLPP_FORCE_SOURCE_FETCH", "1")
    (patcher_root / ".git").mkdir()
    (patcher_root / "src" / "wip.py").write_text("# uncommitted\n", encoding="utf-8")

    status, _ = _sync(
        patcher_root, {"Drop CIA or 3DS Here to Patch.bat": BAT}, "dddd000000000001"
    )
    assert status == "updated"
    assert (patcher_root / "src" / "wip.py").is_file()
    assert (patcher_root / "src" / "drop_zone.ps1").is_file()


def _edit_a(root: Path) -> None:
    (root / "src" / "a.py").write_text("# edited\n", encoding="utf-8")


def _delete_a(root: Path) -> None:
    (root / "src" / "a.py").unlink()


def _add_stray(root: Path) -> None:
    (root / "src" / "stray.py").write_text("#\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("damage", "reason"),
    [(_edit_a, "1 changed"), (_delete_a, "1 changed"), (_add_stray, "1 extra")],
)
def test_drift_at_same_sha_resyncs(patcher_root: Path, monkeypatch, capsys, damage, reason):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    files = {"Drop CIA or 3DS Here to Patch.bat": BAT, "src/a.py": b"# a\n"}
    assert _sync(patcher_root, files, "eeee000000000001")[0] == "updated"
    damage(patcher_root)

    status, _ = _sync(patcher_root, files, "eeee000000000001")
    assert status == "updated"
    assert reason in capsys.readouterr().out
    assert (patcher_root / "src" / "a.py").read_text(encoding="utf-8") == "# a\n"
    assert not (patcher_root / "src" / "stray.py").exists()
    assert fetch_mod.tree_drift(patcher_root) is None


def test_bare_path_manifest_counts_as_drift(patcher_root: Path):
    (patcher_root / fetch_mod.MANIFEST_NAME).write_text("src/drop_zone.ps1\n", encoding="utf-8")
    assert fetch_mod._read_manifest(patcher_root) == {"src/drop_zone.ps1"}
    assert fetch_mod.tree_drift(patcher_root) == "file manifest predates hashes"


def test_zipball_without_gitignore_is_refused(patcher_root: Path, monkeypatch):
    monkeypatch.delenv("NLPP_SKIP_SOURCE_FETCH", raising=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("NewLovePlusPlusEngPatcher-main/Drop CIA or 3DS Here to Patch.bat", BAT)

    def fake_read(url: str, _token):
        return json.dumps({"sha": "ffff000000000001"}).encode()

    def fake_download(url, dest, token, *, dry_run):
        dest.write_bytes(buf.getvalue())

    with (
        patch.object(fetch_mod, "github_reachable", return_value=True),
        patch.object(fetch_mod, "_read_url", fake_read),
        patch.object(fetch_mod, "_download_file", fake_download),
    ):
        status, msg = fetch_mod.try_fetch_main_tree(
            repo="owner/repo", ref="main", token=None, root=patcher_root
        )
    assert status == "unavailable"
    assert ".gitignore" in msg
    assert (patcher_root / "src" / "drop_zone.ps1").is_file()


def test_prune_never_touches_protected_paths(patcher_root: Path):
    (patcher_root / "release").mkdir()
    (patcher_root / "release" / "bake_img.bin").write_bytes(b"BAKE")
    removed = fetch_mod.prune_removed(
        patcher_root, {"release/bake_img.bin", "../outside.txt"}, set()
    )
    assert removed == []
    assert (patcher_root / "release" / "bake_img.bin").is_file()


def _ignore(text: str, base: str = ""):
    ign = fetch_mod.GitIgnore()
    ign.add(base, text)
    return ign


def test_gitignore_negated_folder_under_star():
    ign = _ignore("tools/*\n!tools/cia/\n!tools/cia/**\ntools/cia/*.partial\n")
    assert ign.is_ignored("tools/3dstool.exe")
    assert not ign.is_ignored("tools/cia/makerom.exe")
    assert ign.is_ignored("tools/cia/x.partial")


def test_gitignore_file_under_ignored_folder_stays_ignored():
    ign = _ignore("ab_test/*\n!ab_test/make.ps1\nab_test/saves/\n!ab_test/saves/keep\n")
    assert not ign.is_ignored("ab_test/make.ps1")
    assert ign.is_ignored("ab_test/saves/keep")


def test_gitignore_unanchored_and_nested():
    ign = _ignore("__pycache__/\n*.cia\n")
    ign.add("tools/nlpp-tools", "img_data\n")
    assert ign.is_ignored("src/__pycache__/x.pyc")
    assert ign.is_ignored("deep/dir/game.cia")
    assert ign.is_ignored("tools/nlpp-tools/sub/img_data", is_dir=True)
    assert not ign.is_ignored("img_data")
