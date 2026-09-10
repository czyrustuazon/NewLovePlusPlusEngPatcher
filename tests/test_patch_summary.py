"""Tests for patch_cia end-of-run PATCH SUMMARY (OK / SKIPPED)."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

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
    assert "out\\logs\\latest.txt" in bat
    assert "Patch log" in bat


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


def test_summary_status_counts_tallies_rows():
    lines = [
        "  PATCH SUMMARY",
        "  [OK]      Dialog scripts (.dbin2): injected",
        "  [SKIPPED] Input CIA SHA-1 check: --skip-hash",
        "  [WARN]    Eng Patch title badge: MISSING",
        "  [OFF]     Output CIA: LayeredFS-only mode",
        "  [OK]      Time to finish: 3s",
    ]
    counts = patch_cia.summary_status_counts(lines)
    assert counts == {"OK": 2, "SKIPPED": 1, "OFF": 1, "WARN": 1}


def test_format_patch_log_includes_summary_and_counts(tmp_path: Path):
    lines = patch_cia.build_patch_summary(
        out_cia=None,
        packed_img=None,
        layered_img=None,
        layeredfs_out=None,
        romfs_overlay=None,
        args=_args(no_images=True),
        elapsed="12s",
        started_at="2026-09-10 19:00:00",
    )
    text = patch_cia.format_patch_log(
        lines,
        rom_in=tmp_path / "game.cia",
        out_cia=None,
        when=datetime(2026, 9, 10, 19, 21, 0),
    )
    assert "PATCH SUMMARY" in text
    assert "[SKIPPED] UI img.bin" in text
    assert "Result:" in text
    assert "SKIPPED" in text.split("Result:", 1)[1].splitlines()[0]
    assert "Input:" in text
    assert "game.cia" in text
    assert patch_cia.PATCHER_RELEASE in text


def test_write_patch_summary_log_timestamped_and_latest(tmp_path: Path):
    logs = tmp_path / "logs"
    path = logs / "patch_20260910_192100.txt"
    lines = ["", "=" * 60, "  PATCH SUMMARY — read this before testing", "=" * 60, ""]
    written = patch_cia.write_patch_summary_log(
        path,
        lines,
        rom_in=tmp_path / "in.cia",
        when=datetime(2026, 9, 10, 19, 21, 0),
    )
    assert written == path
    assert path.is_file()
    latest = logs / "latest.txt"
    assert latest.is_file()
    assert "PATCH SUMMARY" in path.read_text(encoding="utf-8")
    assert latest.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


def test_write_patch_summary_log_skips_latest_outside_logs_dir(tmp_path: Path):
    path = tmp_path / "custom_summary.txt"
    written = patch_cia.write_patch_summary_log(
        path, ["  PATCH SUMMARY"], when=datetime(2026, 9, 10, 19, 21, 0)
    )
    assert written == path
    assert path.is_file()
    assert not (tmp_path / "latest.txt").exists()


def test_resolve_patch_log_path_default_and_flags(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(patch_cia, "ROOT", tmp_path)
    when = datetime(2026, 9, 10, 19, 21, 0)
    default = patch_cia.default_patch_log_path(when=when)
    assert default == tmp_path / "out" / "logs" / "patch_20260910_192100.txt"

    custom = tmp_path / "my.log"
    assert patch_cia.resolve_patch_log_path(
        argparse.Namespace(log=str(custom), no_log=False)
    ) == custom.resolve()

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    resolved = patch_cia.resolve_patch_log_path(
        argparse.Namespace(log=str(logs_dir), no_log=False)
    )
    assert resolved.parent == logs_dir.resolve()
    assert resolved.name.startswith("patch_")
    assert resolved.suffix == ".txt"

    assert (
        patch_cia.resolve_patch_log_path(
            argparse.Namespace(log=str(custom), no_log=True)
        )
        is None
    )
    monkeypatch.setenv("NLPP_NO_LOG", "1")
    assert (
        patch_cia.resolve_patch_log_path(argparse.Namespace(log=None, no_log=False))
        is None
    )


def test_cleanup_out_dir_keeps_logs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(patch_cia, "ROOT", tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "scratch.bin").write_bytes(b"x")
    logs = out / "logs"
    logs.mkdir()
    (logs / "latest.txt").write_text("summary\n", encoding="utf-8")
    cia = out / "NewLovePlusPlus-EN.cia"
    cia.write_bytes(b"cia")
    luma = out / "luma"
    luma.mkdir()
    patch_cia.cleanup_out_dir(out_cia=cia)
    assert cia.is_file()
    assert luma.is_dir()
    assert (logs / "latest.txt").is_file()
    assert not (out / "scratch.bin").exists()


def test_parser_has_log_flags():
    p = patch_cia.build_parser()
    args = p.parse_args(["--cia", "game.cia"])
    assert args.log is None
    assert args.no_log is False
    args = p.parse_args(["--cia", "game.cia", "--log", "out/mylog.txt"])
    assert args.log == "out/mylog.txt"
    args = p.parse_args(["--cia", "game.cia", "--no-log"])
    assert args.no_log is True
