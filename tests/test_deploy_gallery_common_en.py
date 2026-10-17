"""Gallery Common Options strips reuse Profile Called As: copy."""

from __future__ import annotations

from conftest import TOOLS, load_module

deploy = load_module("deploy_gallery_common_en", TOOLS / "deploy_gallery_common_en.py")


def test_gallery_options_called_as_and_playback_speed():
    assert deploy.PKG == 5153
    by_path = dict(deploy.LABELS)
    assert by_path["timg/Gallery_txt09.bclim"] == "Called As:"
    assert by_path["timg/Gallery_txt08.bclim"] == "Playback Speed"
    assert "Gallery_txt09" in deploy.ZHOUMARU_STEMS
    assert "Gallery_txt08" in deploy.ZHOUMARU_STEMS
    # Wrong Zhoumaru Fitness paint — do not ship txt07.
    assert "Gallery_txt07" not in deploy.ZHOUMARU_STEMS
    assert not any(p.endswith("Gallery_txt07.bclim") for p, _ in deploy.LABELS)


def test_gallery_common_on_bake_chrome_list():
    text = (TOOLS / "rebuild_bake_img.py").read_text(encoding="utf-8")
    assert "deploy_gallery_common_en.py" in text
