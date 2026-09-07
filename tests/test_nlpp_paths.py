"""Tests for canonical path resolution (nlpp_paths.py)."""

from __future__ import annotations

from pathlib import Path

import nlpp_paths as paths


def test_title_id_constant():
    assert paths.TITLE_ID == "00040000000F4E00"


def test_azahar_user_dir_from_env(monkeypatch, tmp_path: Path):
    custom = tmp_path / "azahar-user"
    custom.mkdir()
    monkeypatch.setenv("NLPP_AZAHAR_USER_DIR", str(custom))
    assert paths.azahar_user_dir() == custom.resolve()


def test_azahar_mod_root():
    user = Path("/tmp/nlpp-test-user")
    mod = paths.azahar_mod_root(user_dir=user)
    assert mod == user / "load" / "mods" / paths.TITLE_ID


def test_find_vanilla_img_env_and_cache(tmp_path: Path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(b"vanilla")
    monkeypatch.setenv("NLPP_VANILLA_IMG", str(img))
    assert paths.find_vanilla_img() == img.resolve()


def test_find_vanilla_img_missing(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("NLPP_VANILLA_IMG", raising=False)
    monkeypatch.setattr(paths, "DEFAULT_VANILLA_IMG", tmp_path / "missing.img")
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "CACHE_VANILLA_IMG", tmp_path / "cache" / "img.bin")
    assert paths.find_vanilla_img() is None


def test_require_vanilla_img_raises(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("NLPP_VANILLA_IMG", raising=False)
    monkeypatch.setattr(paths, "DEFAULT_VANILLA_IMG", tmp_path / "nope")
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "CACHE_VANILLA_IMG", tmp_path / "nope2")
    try:
        paths.require_vanilla_img()
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "vanilla romfs/img.bin" in str(exc)


def test_find_translations_json_prefers_assets(tmp_path: Path, monkeypatch):
    assets = tmp_path / "assets" / "textresource" / "translations.json"
    assets.parent.mkdir(parents=True)
    assets.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths, "TRANSLATIONS_JSON", assets)
    monkeypatch.setattr(paths, "TEXTRESOURCE", tmp_path / "release" / "textresource")
    monkeypatch.setattr(
        paths, "OVERLAY_TRB_DIR", tmp_path / "release" / "romfs_overlay" / "SystemData" / "TextResource"
    )
    assert paths.find_translations_json() == assets.resolve()


def test_find_vanilla_code_env(tmp_path: Path, monkeypatch):
    code = tmp_path / "code.bin"
    code.write_bytes(b"code")
    monkeypatch.setenv("NLPP_VANILLA_CODE", str(code))
    assert paths.find_vanilla_code() == code.resolve()
