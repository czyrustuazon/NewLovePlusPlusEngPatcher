"""rebuild_test_cia must prefer gold bake over stale Azahar/luma imgs."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import TOOLS, load_module

rebuild = load_module("rebuild_test_cia", TOOLS / "rebuild_test_cia.py")


@pytest.fixture
def img_paths(tmp_path: Path, monkeypatch):
    bake = tmp_path / "release" / "bake_img.bin"
    azahar = tmp_path / "azahar" / "img.bin"
    bake.parent.mkdir(parents=True)
    azahar.parent.mkdir(parents=True)
    monkeypatch.setattr(rebuild, "BAKE_IMG", bake)
    monkeypatch.setattr(rebuild, "AZAHAR_MOD_IMG", azahar)
    return bake, azahar


def test_resolve_img_prefers_bake_even_when_azahar_newer(img_paths):
    bake, azahar = img_paths
    bake.write_bytes(b"bake-with-eng")
    azahar.write_bytes(b"stale-luma")
    # Newer mtime on Azahar must not win (Sep 2026 regression).
    azahar.touch()
    assert rebuild.resolve_img() == bake.resolve()


def test_resolve_img_falls_back_to_azahar_when_bake_missing(img_paths):
    _bake, azahar = img_paths
    azahar.write_bytes(b"mod-only")
    assert rebuild.resolve_img() == azahar.resolve()


def test_resolve_img_errors_when_neither_exists(img_paths):
    with pytest.raises(SystemExit, match="no img.bin"):
        rebuild.resolve_img()
