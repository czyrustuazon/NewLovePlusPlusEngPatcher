"""Tests for gold bake rebuild pipeline configuration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from conftest import TOOLS, load_module

rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")


def test_deploy_scripts_include_menu_chrome():
    scripts = rebuild.DEPLOY_SCRIPTS
    required = [
        "deploy_msel_menus_en.py",
        "deploy_msel_options_en.py",
        "deploy_confirm_btn_en.py",
        "deploy_title_engpatch_en.py",
        "deploy_display_settings_en.py",
        "deploy_optionpassword_en.py",
    ]
    for name in required:
        assert name in scripts, f"missing deploy script: {name}"


def test_rebuild_rc_pack_is_from_scratch_by_default():
    text = (TOOLS / "rebuild_bake_img.py").read_text(encoding="utf-8", errors="replace")
    assert "--use-cache" in text
    assert "no_cache=(not args.use_cache) or args.no_cache" in text
    assert "write_bake_stamp" in text
    assert "packed_assets=not args.skip_pack" in text
    assert "PATCHER_RELEASE" in text
    assert "write_rebuild_log" in text
    assert "format_rebuild_ok_lines" in text


def test_rebuild_name_input_is_required_not_optional():
    text = (TOOLS / "rebuild_bake_img.py").read_text(encoding="utf-8", errors="replace")
    assert "--skip-name-input-code" not in text
    assert "build_name_input_code" in text
    assert "required name-input missing" in text
    assert "--keep-work" in text
    assert "cleanup_rebuild_scratch" in text


def test_softkey_deploy_after_confirm():
    scripts = rebuild.DEPLOY_SCRIPTS
    confirm = scripts.index("deploy_confirm_btn_en.py")
    softkey = scripts.index("deploy_softkey_back_next_en.py")
    assert softkey > confirm


def test_multiwin_after_datadelete():
    scripts = rebuild.DEPLOY_SCRIPTS
    assert scripts.index("deploy_multiwin_headers_en.py") > scripts.index(
        "deploy_datadelete_en.py"
    )


def test_rebuild_ok_lines_include_elapsed(tmp_path: Path):
    lines = rebuild.format_rebuild_ok_lines(
        bake=tmp_path / "release" / "bake_img.bin",
        cache_new=None,
        main_trb=tmp_path / "release" / "textresource" / "textresource_jpn.trb",
        overlay=tmp_path / "release" / "romfs_overlay",
        name_code=tmp_path / "release" / "name_input_code.bin",
        stamp=tmp_path / "release" / "bake_stamp.txt",
        elapsed="1h02m18s",
        started_at="2026-09-17 00:02:00",
    )
    text = "\n".join(lines)
    assert text.startswith("[rebuild] OK")
    assert "time:          1h02m18s  (started 2026-09-17 00:02:00)" in text
    assert "gold bake:" in text
    assert "PNG optional:" not in text


def test_write_rebuild_log_includes_total_time(tmp_path: Path):
    lines = rebuild.format_rebuild_ok_lines(
        bake=tmp_path / "bake_img.bin",
        cache_new=tmp_path / "new_img.bin",
        main_trb=tmp_path / "textresource_jpn.trb",
        overlay=tmp_path / "overlay",
        name_code=tmp_path / "name_input_code.bin",
        stamp=tmp_path / "bake_stamp.txt",
        elapsed="3m05s",
        started_at="2026-09-17 01:00:00",
    )
    logs = tmp_path / "logs"
    path = rebuild.write_rebuild_log(
        lines,
        elapsed="3m05s",
        started_at="2026-09-17 01:00:00",
        logs_dir=logs,
        when=datetime(2026, 9, 17, 1, 3, 5),
    )
    assert path == logs / "rebuild_20260917_010305.txt"
    text = path.read_text(encoding="utf-8")
    assert "Gold rebuild" in text
    assert "Time:    3m05s" in text
    assert "Started: 2026-09-17 01:00:00" in text
    assert "time:          3m05s  (started 2026-09-17 01:00:00)" in text
    latest = logs / "rebuild_latest.txt"
    assert latest.read_text(encoding="utf-8") == text
