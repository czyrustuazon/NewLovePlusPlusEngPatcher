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


def test_love_plus_matches_youth_story_pill():
    """Same lettering as Zhoumaru's Youth Story pill: gray 47, ~9 px caps."""
    import numpy as np

    rgba = deploy_myroom_main_en.render_menu_label(
        58,
        16,
        "Love Plus",
        cap_px=deploy_myroom_main_en.LOVE_CAP_PX,
        weight=deploy_myroom_main_en.LOVE_WEIGHT,
    )
    assert rgba.size == (58, 16)
    arr = np.array(rgba)
    opaque = arr[:, :, 3] > 64
    assert tuple(int(x) for x in arr[opaque][:, :3].mean(0)) == (47, 47, 47)
    ys, _xs = np.where(opaque)
    assert 8 <= ys.max() - ys.min() + 1 <= 10
