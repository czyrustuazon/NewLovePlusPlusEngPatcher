"""Myroom main labels packed by deploy_myroom_main_en."""

from __future__ import annotations

from conftest import TOOLS, load_module

deploy_myroom_main_en = load_module(
    "deploy_myroom_main_en", TOOLS / "deploy_myroom_main_en.py"
)


def test_myroom_main_includes_love_plus_badge():
    paths = {path: en for path, en in deploy_myroom_main_en.LABELS}
    assert paths["timg/main_tex_love_RGBA4.bclim"] == "Love Plus"
    assert deploy_myroom_main_en.LOVE_STEM == "main_tex_love_RGBA4"


def test_love_plus_fits_badge_canvas():
    rgba = deploy_myroom_main_en.render_label(
        58, 16, "Love Plus", ink=deploy_myroom_main_en.HEADER_INK
    )
    assert rgba.size == (58, 16)
