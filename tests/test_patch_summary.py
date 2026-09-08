"""Tests for patch_cia end-of-run PATCH SUMMARY (OK / SKIPPED)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from conftest import SRC, load_module

patch_cia = load_module("patch_cia", SRC / "patch_cia.py")


def _args(**kwargs) -> argparse.Namespace:
    base = dict(
        no_images=False,
        with_images=True,
        inject_code=None,
        patch_code=False,
        skip_name_patches=False,
        skip_hash=False,
    )
    base.update(kwargs)
    return argparse.Namespace(**base)


def test_summary_marks_ui_skipped_when_no_images(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", tmp_path / "bake.bin")
    lines = patch_cia.build_patch_summary(
        out_cia=None,
        packed_img=None,
        layered_img=None,
        layeredfs_out=None,
        romfs_overlay=None,
        args=_args(no_images=True, inject_code=str(tmp_path / "code.bin")),
        eng_patch=None,
    )
    text = "\n".join(lines)
    assert "PATCH SUMMARY" in text
    assert "[SKIPPED] UI img.bin" in text
    assert "menus stay JP" in text
    assert "Name-input ON but UI img OFF" in text


def test_summary_ok_for_gold_bake_with_eng(tmp_path: Path, monkeypatch):
    bake = tmp_path / "release" / "bake_img.bin"
    bake.parent.mkdir(parents=True)
    bake.write_bytes(b"gold")
    code = tmp_path / "name_input_code.bin"
    code.write_bytes(b"code")
    out = tmp_path / "out" / "NewLovePlusPlus-EN.cia"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"cia")
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", bake)

    lines = patch_cia.build_patch_summary(
        out_cia=out,
        packed_img=bake,
        layered_img=bake,
        layeredfs_out=None,
        romfs_overlay=None,
        args=_args(inject_code=str(code)),
        eng_patch=True,
    )
    text = "\n".join(lines)
    assert "[OK]      UI img.bin" in text
    assert "gold bake" in text
    assert "[OK]      Eng Patch title badge" in text
    assert "[OK]      Profile name-input code.bin" in text
    assert "Name-input ON but UI img OFF" not in text


def test_summary_includes_time_to_finish(tmp_path: Path, monkeypatch):
    bake = tmp_path / "bake.bin"
    bake.write_bytes(b"gold")
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", bake)
    lines = patch_cia.build_patch_summary(
        out_cia=None,
        packed_img=bake,
        layered_img=bake,
        layeredfs_out=None,
        romfs_overlay=None,
        args=_args(),
        eng_patch=True,
        elapsed="4m32s",
        started_at="2026-09-08 00:12:03",
    )
    text = "\n".join(lines)
    assert "[OK]      Time to finish: 4m32s  (started 2026-09-08 00:12:03)" in text


def test_summary_warns_if_eng_missing_despite_img(tmp_path: Path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(b"x")
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", tmp_path / "other.bin")
    lines = patch_cia.build_patch_summary(
        out_cia=None,
        packed_img=img,
        layered_img=img,
        layeredfs_out=None,
        romfs_overlay=None,
        args=_args(),
        eng_patch=False,
    )
    text = "\n".join(lines)
    assert "[WARN]    Eng Patch title badge" in text
    assert "MISSING" in text


def test_drop_bat_mentions_patch_summary():
    bat = (SRC.parent / "Drop CIA or 3DS Here to Patch.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "PATCH SUMMARY" in bat
    assert "incomplete patches abort" in bat
    assert "Time to finish" in bat
    assert "NLPP_T0" in bat
    assert "run_timer.py" in bat


def test_patch_cia_requires_name_input_for_ui_inject():
    src = (SRC / "patch_cia.py").read_text(encoding="utf-8")
    assert "Profile name-input code.bin is required for a full UI patch" in src


def test_rebuild_always_builds_name_input():
    text = (SRC.parent / "tools" / "rebuild_bake_img.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "skip-name-input-code" not in text
    assert "required release/name_input_code.bin failed after 3 attempts" in text
    assert "name-input] skip" not in text


def test_vanilla_extract_requires_code_bin():
    text = (SRC.parent / "src" / "extract_vanilla_from_rom.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "warning: code.bin extract failed" not in text
    assert "ExeFS code.bin extract" in text
    assert "VANILLA_CODE.is_file()" in text
