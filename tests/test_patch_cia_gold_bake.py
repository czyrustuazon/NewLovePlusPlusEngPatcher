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


def test_pack_ui_images_uses_gold_bake_without_png_pack(paths, tmp_path: Path):
    bake, _cache = paths
    bake.write_bytes(b"gold")

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
