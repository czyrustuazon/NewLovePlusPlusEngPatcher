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
