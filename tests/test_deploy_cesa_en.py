"""CESA boot-warning deploy wrapper (pkg 90) — vanilla source + bake tail."""

from __future__ import annotations

from pathlib import Path

from conftest import TOOLS, load_module

cesa = load_module("deploy_cesa_en", TOOLS / "deploy_cesa_en.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")


def test_cesa_is_bake_tail():
    assert rebuild.DEPLOY_SCRIPTS[-1] == "deploy_cesa_en.py"


def test_vanilla_pkg90_src_prefers_vanilla_over_dest(tmp_path: Path, monkeypatch):
    dest = tmp_path / "live" / "img.bin"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"live")
    vanilla = tmp_path / "vanilla" / "img.bin"
    vanilla.parent.mkdir(parents=True)
    vanilla.write_bytes(b"vanilla")
    bak = dest.with_suffix(".bin.bak_pre_cesa")
    bak.write_bytes(b"bak")

    monkeypatch.setattr(cesa, "find_vanilla_img", lambda: vanilla)
    monkeypatch.setattr(cesa, "_FALLBACK_VANILLA", tmp_path / "fallback" / "img.bin")
    assert cesa._vanilla_pkg90_src(dest) == vanilla.resolve()


def test_vanilla_pkg90_src_falls_back_to_bak_pre(tmp_path: Path, monkeypatch):
    dest = tmp_path / "live" / "img.bin"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"live")
    bak = dest.with_suffix(".bin.bak_pre_cesa")
    bak.write_bytes(b"bak")

    monkeypatch.setattr(cesa, "find_vanilla_img", lambda: None)
    monkeypatch.setattr(cesa, "_FALLBACK_VANILLA", dest)  # same as dest → skip
    assert cesa._vanilla_pkg90_src(dest) == bak.resolve()


def test_vanilla_pkg90_src_never_returns_dest(tmp_path: Path, monkeypatch):
    dest = tmp_path / "img.bin"
    dest.write_bytes(b"live")
    monkeypatch.setattr(cesa, "find_vanilla_img", lambda: dest)
    monkeypatch.setattr(cesa, "_FALLBACK_VANILLA", dest)
    try:
        cesa._vanilla_pkg90_src(dest)
    except SystemExit as exc:
        assert "vanilla img.bin" in str(exc)
    else:
        raise AssertionError("expected SystemExit when only dest exists")
