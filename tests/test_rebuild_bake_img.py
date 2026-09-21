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
        "deploy_myroom_options_en.py",
    ]
    for name in required:
        assert name in scripts, f"missing deploy script: {name}"


def test_msel_menus_include_event_gallery_rows():
    text = (TOOLS / "deploy_msel_menus_en.py").read_text(encoding="utf-8")
    for stem in (
        "Com_M_Sel_Btn_Text02_01_01",
        "Com_M_Sel_Btn_Text02_01_02",
        "Com_M_Sel_Btn_Text02_01_03",
        "Com_M_Sel_Btn_Text02_01_04",
        "Com_M_Sel_Btn_Text02_02_00",
        "Com_M_Sel_Plate_Text02_01_01",
        "Com_M_Sel_Plate_Text02_01_03",
        "Com_M_Sel_Plate_Text02_01_04",
        "Com_M_Sel_Plate_Text04_01_01",
        "Com_M_Sel_Btn_Text04_01_04",
        "Com_M_Sel_Btn_Text04_01_05",
        "Com_M_Sel_Btn_Text04_01_06",
        "Com_M_Sel_Btn_Text04_01_07",
        "Com_M_Sel_Btn_Text04_01_08",
        "Com_M_Sel_Btn_Text04_01_09",
        "Com_M_Sel_Btn_Text04_01_10",
    ):
        assert stem in text
    assert "Find Two-Person Chat" in text
    assert "Find Three-Person Chat" in text
    assert "Join Chat" in text
    assert "Introduce Girlfriend" in text
    assert "Get Introduced" in text
    assert "Find Couple" in text
    assert "Join Double Date" in text
    assert "Heart to Heart" in text
    assert "SKIP_UI_PNG" in text
    assert "Com_M_Sel_Plate_Text04_01_01" in text.split("SKIP_UI_PNG")[1]
    assert "GF_COMM_PLATE_FROM_MULTIWIN" not in text
    assert '"Com_M_Sel_Plate_Text04_01_00": "Com_M_Sel_Plate_Text04_01_01"' not in text


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
    deploy = (TOOLS / "deploy_name_input_en.py").read_text(encoding="utf-8")
    assert "apply_message_speed" in deploy
    assert "message_speed_already" in deploy


def test_softkey_deploy_after_confirm():
    scripts = rebuild.DEPLOY_SCRIPTS
    confirm = scripts.index("deploy_confirm_btn_en.py")
    softkey = scripts.index("deploy_softkey_back_next_en.py")
    quit_sk = scripts.index("deploy_softkey_quit_en.py")
    defaults = scripts.index("deploy_softkey_defaults_en.py")
    assert softkey > confirm
    assert quit_sk > softkey
    assert defaults > quit_sk


def test_multiwin_after_datadelete():
    scripts = rebuild.DEPLOY_SCRIPTS
    assert scripts.index("deploy_multiwin_headers_en.py") > scripts.index(
        "deploy_datadelete_en.py"
    )


def test_multiwin_bake_runs_full_then_extras():
    text = (TOOLS / "rebuild_bake_img.py").read_text(encoding="utf-8", errors="replace")
    assert '["--full"] if name == "deploy_multiwin_headers_en.py"' in text
    assert "deploy_multiwin_headers_en.py extras" in text


def test_myroom_options_after_shared_arc_writers():
    scripts = rebuild.DEPLOY_SCRIPTS
    opts = scripts.index("deploy_myroom_options_en.py")
    assert opts > scripts.index("deploy_schedule_header_en.py")
    last_ui = max(i for i, n in enumerate(scripts) if n == "deploy_ui_buttons_en.py")
    assert opts > last_ui
    text = (TOOLS / "deploy_myroom_options_en.py").read_text(encoding="utf-8")
    for stem in (
        "optn_tex_optionmenu_RGBA4",
        "optn_tex_optionhyouji_RGBA4",
        "optn_tex_optionsound_RGBA4",
        "optn_tex_optionmenu_01",
        "optn_tex_optionmenu_02",
    ):
        assert stem in text
    skip_block = text.split("SKIP_UI_PNG", 1)[1].split("JOBS", 1)[0]
    assert "optn_tex_optionkabegami_RGBA4" in skip_block
    assert "MOD_IMG.read_bytes" in text
    assert "_zero_all_darc_pads" in text
    assert "unsalted pads" in text


def test_msel_options_omits_quit_azahar_prompt():
    text = (TOOLS / "deploy_msel_options_en.py").read_text(encoding="utf-8")
    assert "Fully quit Azahar" not in text
    assert "Com_M_Sel_Plate_Text03_05_00" in text
    assert "add_password_input_plate" in text
    assert "--plate-only" in text
    assert "Com_M_Sel_Plate_Text04_04_00" in text
    plates = (TOOLS / "deploy_msel_opt_plates_en.py").read_text(encoding="utf-8")
    assert "Com_M_Sel_Plate_Text04_04_00" in plates
    assert "Communication Settings" in plates


def test_multiwin_girlfriend_comm_self_renders():
    text = (TOOLS / "deploy_multiwin_headers_en.py").read_text(encoding="utf-8")
    common = (TOOLS / "deploy_common.py").read_text(encoding="utf-8")
    assert "Com_MultiWin_W01_Text04_01_00" in text
    assert "SKIP_UI_PNG" in text
    skip_block = text.split("SKIP_UI_PNG")[1].split("UI_PNG_FOLDERS")[0]
    assert "Com_MultiWin_W01_Text04_01_00" in skip_block
    assert "Com_MultiWin_W01_Text04_01_01" in skip_block
    assert '"Com_MultiWin_W01_Text04_01_00": "Com_MultiWin_W01_Text04_01_01"' not in text
    assert "Heart to Heart" in text
    assert "render_header_aa" in text
    assert "HEADER_INK" in common
    assert "df-heiseigothic-w5.ttc" in common
    assert "Confession Memories" in text
    assert "Trip Memories" in text
    assert "Youthful Page" in text
    assert "Com_MultiWin_W01_Text03_05_00" in text
    assert "Password Input" in text


def test_profile_deploy_includes_hometown_regions():
    text = (TOOLS / "deploy_profile_en.py").read_text(encoding="utf-8")
    assert "REGION_BUTTONS" in text
    assert "patch_region_buttons" in text
    assert "png_to_bclim_rgba4444_same_size" in text
    assert "Profile_Btn_Com02_Text" in text
    assert "range(1, 9)" in text
    assert "Profile.check" in text
    assert "fit_region_png" in text
    assert "REGION_PAD_X" in text
    assert "REGION_PAD_Y" in text


def test_profile_header_uses_heisei_heart_to_heart_chrome():
    text = (TOOLS / "deploy_profile_en.py").read_text(encoding="utf-8")
    assert "render_header_aa" in text
    assert "HEADER_CORE_PX" in text
    assert "HEADER_STRIP_H" in text
    assert "Com_M_Sel_Plate_Text01_00_00" in text
    assert "slot_len" in text
    assert "1651" not in text


def test_profile_call01_labels_use_heisei_chroma_aa():
    text = (TOOLS / "deploy_profile_en.py").read_text(encoding="utf-8")
    assert '(1, 14, 48, 192, "Last Name")' in text
    assert '(77, 89, 48, 192, "First Name")' in text
    assert "CALL_LABEL_SIZE = HEADER_CORE_PX" in text
    assert "ATLAS_LABEL_SIZE = HEADER_CORE_PX" in text
    assert "CALL_PALETTE" in text
    hard_fn = text.split("def render_hard_label")[1].split("def paste_label")[0]
    assert "chrome_font" in hard_fn
    assert "BILINEAR" in hard_fn
    assert "CALL_PALETTE" in hard_fn or "_quantize_chroma" in hard_fn
    call_fn = text.split("def render_call_label")[1].split("def make_call_en")[0]
    assert "render_hard_label" in call_fn
    assert "Resampling.NEAREST" not in call_fn
    from PIL import Image, ImageDraw, ImageFont

    hei = TOOLS.parent / "assets" / "fonts" / "reference" / "nlppatch-2025" / "df-heiseigothic-w5.ttc"
    font = ImageFont.truetype(str(hei), 15, index=1)
    dr = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    # Inclusive box widths in CALL01_LABELS after the wide-header change.
    for label, width in (
        ("Last Name", 145),
        ("First Name", 145),
        ("Written", 62),
        ("Called", 62),
    ):
        b = dr.textbbox((0, 0), label, font=font)
        assert b[2] - b[0] <= width - 1, f"{label} {b[2]-b[0]}px > {width}px box"


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
