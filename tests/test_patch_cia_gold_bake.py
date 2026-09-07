"""Tests for patch_cia gold-bake injection resolution."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from conftest import SRC, load_module

patch_cia = load_module("patch_cia", SRC / "patch_cia.py")


@pytest.fixture
def paths(tmp_path: Path, monkeypatch):
    bake = tmp_path / "release" / "bake_img.bin"
    cache = tmp_path / "cache" / "new_img.bin"
    bake.parent.mkdir(parents=True)
    cache.parent.mkdir(parents=True)
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", bake)
    monkeypatch.setattr(patch_cia, "DEFAULT_PACKED_IMG", cache)
    return bake, cache


def test_resolve_inject_img_prefers_gold_bake_over_png_cache(paths):
    bake, cache = paths
    bake.write_bytes(b"gold")
    cache.write_bytes(b"png-only")

    args = argparse.Namespace(
        packed_img=str(cache),
        repack_images=False,
    )
    assert patch_cia.resolve_inject_img(args) == bake.resolve()


def test_resolve_inject_img_uses_explicit_gold_path_when_bake_missing(paths):
    bake, cache = paths
    cache.write_bytes(b"png-only")

    args = argparse.Namespace(
        packed_img=str(bake),
        repack_images=False,
    )
    assert patch_cia.resolve_inject_img(args) == bake.resolve()


def test_resolve_inject_img_repack_images_ignores_gold_bake(paths):
    bake, cache = paths
    bake.write_bytes(b"gold")
    cache.write_bytes(b"png-only")

    args = argparse.Namespace(
        packed_img=None,
        repack_images=True,
    )
    assert patch_cia.resolve_inject_img(args) == cache.resolve()


def test_pack_ui_images_uses_gold_bake_without_png_pack(paths, tmp_path: Path, monkeypatch):
    bake, _cache = paths
    bake.write_bytes(b"gold")
    monkeypatch.setattr(patch_cia, "_title_pkg_has_eng_patch", lambda *_a, **_k: True)

    args = argparse.Namespace(
        packed_img=str(bake),
        repack_images=False,
        reuse_packed_img=False,
        images=str(tmp_path / "assets"),
        img_bin=None,
        image_workers=None,
        image_fine_tune=False,
    )
    work = tmp_path / "work"
    work.mkdir()

    out = patch_cia.pack_ui_images(args, work)
    assert out == bake.resolve()


def test_pack_ui_images_rejects_gold_bake_without_eng_patch(paths, tmp_path: Path, monkeypatch):
    bake, _cache = paths
    bake.write_bytes(b"gold-no-eng")
    monkeypatch.setattr(patch_cia, "_title_pkg_has_eng_patch", lambda *_a, **_k: False)

    args = argparse.Namespace(
        packed_img=str(bake),
        repack_images=False,
        reuse_packed_img=False,
        images=str(tmp_path / "assets"),
        img_bin=None,
        image_workers=None,
        image_fine_tune=False,
    )
    with pytest.raises(patch_cia.PatchError, match="Eng_Patch"):
        patch_cia.pack_ui_images(args, tmp_path / "work")


def test_pack_ui_images_rejects_stale_packed_img_without_eng_patch(paths, tmp_path: Path, monkeypatch):
    """Explicit --packed-img (luma/Azahar) must not skip the Eng Patch guard."""
    _bake, cache = paths
    stale = tmp_path / "stale_luma_img.bin"
    stale.write_bytes(b"stale-en-menus-no-badge")
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", tmp_path / "missing_bake.bin")
    monkeypatch.setattr(patch_cia, "_title_pkg_has_eng_patch", lambda *_a, **_k: False)

    args = argparse.Namespace(
        packed_img=str(stale),
        repack_images=False,
        reuse_packed_img=True,
        images=str(tmp_path / "assets"),
        img_bin=None,
        image_workers=None,
        image_fine_tune=False,
    )
    with pytest.raises(patch_cia.PatchError, match="Eng_Patch"):
        patch_cia.pack_ui_images(args, tmp_path / "work")


def test_require_eng_patch_ok_and_fail(tmp_path: Path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(b"x")
    monkeypatch.setattr(patch_cia, "_title_pkg_has_eng_patch", lambda *_a, **_k: True)
    patch_cia._require_eng_patch(img, context="ok")
    monkeypatch.setattr(patch_cia, "_title_pkg_has_eng_patch", lambda *_a, **_k: False)
    with pytest.raises(patch_cia.PatchError, match="missing Title Eng_Patch"):
        patch_cia._require_eng_patch(img, context="bad")


def test_image_pack_failure_must_not_become_scripts_only():
    """Regression: JP menus + working name-input = scripts-only after swallowed PackError."""
    src = (SRC / "patch_cia.py").read_text(encoding="utf-8")
    assert "continuing scripts-only (no img.bin inject)" not in src
    # Still allow explicit opt-out.
    assert "skipped (--no-images)" in src
