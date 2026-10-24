"""Mail home button list includes Zhoumaru Play (再生)."""

from __future__ import annotations

from conftest import TOOLS, load_module

deploy = load_module("deploy_mail_home_en", TOOLS / "deploy_mail_home_en.py")


def test_mail_home_play_buttons():
    assert deploy.BUTTON_PKG == 5207
    paths = [p for p, _en in deploy.BUTTON_LABELS]
    assert "timg/C_Btn_Play_Off.bclim" in paths
    assert "timg/C_Btn_Play_On.bclim" in paths
    assert dict(deploy.BUTTON_LABELS)["timg/C_Btn_Play_Off.bclim"] == "Play"
    assert "C_Btn_Play_Off" in deploy.ZHOUMARU_BUTTONS
    assert "C_Btn_Play_On" in deploy.ZHOUMARU_BUTTONS
    assert "mail_tex_chak_RGBA4" in deploy.ZHOUMARU_BUTTONS
    assert "mail_tex_jyusin_RGBA4" in deploy.ZHOUMARU_BUTTONS
    assert "mail_tex_shinki_RGBA4" in deploy.ZHOUMARU_BUTTONS


def test_mail_arc_lists_good_zhoumaru_masters():
    """Mail.arc rebuilds from vanilla; unlisted masters (compose tabs) ship JP."""
    from conftest import ROOT

    stems = {p.rsplit("/", 1)[-1].removesuffix(".bclim") for p, _en in deploy.ZHOUMARU_ONLY}
    assert {f"Mail_SendType_T0{i}" for i in range(1, 5)} <= stems
    assert "C_Com_icon_Repry2" not in stems  # 送信, mislabeled "Reply"
    for stem in stems:
        assert (ROOT / "assets" / "images" / "Mail.check" / "timg" / f"{stem}.png").is_file()
    assert stems <= deploy.ZHOUMARU_BUTTONS


def test_category_rows_render_menu_row_style():
    """Inbox rows use the Zhoumaru menu-row lettering (Arimo, gray 47)."""
    assert deploy.MENU_FONT.is_file()
    for _path, en in deploy.CATEGORY_LABELS:
        im = deploy.render_menu_label(142, 18, en)
        assert im.size == (142, 18)
        assert im.split()[3].getbbox() is not None

