"""A/B make.ps1 installs an existing bake and refuses to start one."""

from __future__ import annotations

from conftest import ROOT

MAKE = ROOT / "ab_test" / "make.ps1"


def test_ab_installs_post_bake_and_prompts_when_missing():
    text = MAKE.read_text(encoding="utf-8")
    assert "function Require-PostBake" in text
    assert "function Install-PostBake" in text
    assert "A bake should be done first." in text
    assert "release\\bake_img.bin" in text
    assert "release\\name_input_code.bin" in text
    assert "release\\romfs_overlay" in text
    assert '"seed-a" = { Install-PostBake "a" }' in text
    assert '"deploy-a" = { Deploy-NameInput "a" }' in text
    install = text.split("function Install-PostBake", 1)[1].split("function Restore-NameInput", 1)[0]
    assert "VanillaDump" not in install
    assert "bake_img.bin" in install
    assert "name_input_code.bin" in install
    assert "function Seed-Instance" not in text
    assert 'src\\script_inject.py", "--layeredfs"' in text
