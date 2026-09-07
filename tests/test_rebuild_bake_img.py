"""Tests for gold bake rebuild pipeline configuration."""

from __future__ import annotations

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
    ]
    for name in required:
        assert name in scripts, f"missing deploy script: {name}"


def test_rebuild_name_input_is_required_not_optional():
    text = (TOOLS / "rebuild_bake_img.py").read_text(encoding="utf-8", errors="replace")
    assert "--skip-name-input-code" not in text
    assert "build_name_input_code" in text
    assert "required name-input missing" in text


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
