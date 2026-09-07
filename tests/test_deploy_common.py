"""Tests for deploy script shared helpers."""

from __future__ import annotations

from pathlib import Path

from conftest import TOOLS, load_module

deploy_common = load_module("deploy_common", TOOLS / "deploy_common.py")


def test_resolve_img_paths_prefers_bake(tmp_path: Path, monkeypatch):
    bake = tmp_path / "release" / "bake_img.bin"
    vanilla = tmp_path / "vanilla.img.bin"
    bake.parent.mkdir(parents=True)
    bake.write_bytes(b"bake")
    vanilla.write_bytes(b"vanilla")
    monkeypatch.setattr(deploy_common, "BAKE_IMG", bake)
    monkeypatch.setattr(deploy_common, "AZAHAR_MOD_IMG", tmp_path / "azahar.img.bin")
    monkeypatch.setenv("NLPP_DEPLOY_IMG", "")
    monkeypatch.setattr(deploy_common, "find_vanilla_img", lambda: vanilla)

    primary, van = deploy_common.resolve_img_paths()
    assert primary == bake.resolve()
    assert van == vanilla.resolve()


def test_resolve_img_paths_env_override(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom.img.bin"
    custom.write_bytes(b"x")
    monkeypatch.setenv("NLPP_DEPLOY_IMG", str(custom))
    monkeypatch.setattr(deploy_common, "find_vanilla_img", lambda: custom)

    primary, van = deploy_common.resolve_img_paths()
    assert primary == custom.resolve()


def test_iter_deploy_targets_includes_primary_and_bake(tmp_path: Path, monkeypatch):
    primary = tmp_path / "primary.img.bin"
    bake = tmp_path / "release" / "bake_img.bin"
    bake.parent.mkdir(parents=True)
    primary.write_bytes(b"p")
    bake.write_bytes(b"b")
    monkeypatch.setattr(deploy_common, "BAKE_IMG", bake)
    monkeypatch.setattr(deploy_common, "AZAHAR_MOD_IMG", tmp_path / "missing.img.bin")
    monkeypatch.setenv("NLPP_ALSO_AZAHAR", "0")

    targets = deploy_common.iter_deploy_targets(primary)
    assert primary.resolve() in targets
    assert bake.resolve() in targets


def test_ui_font_missing_exits(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(deploy_common, "UI_FONT", tmp_path / "missing.ttf")
    try:
        deploy_common.ui_font(12)
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "missing UI font" in str(exc)
