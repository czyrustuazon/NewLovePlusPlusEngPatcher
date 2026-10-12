"""My Data home buttons packed by deploy_mydata_en."""

from __future__ import annotations

from PIL import Image

from conftest import ROOT, TOOLS, load_module

deploy_mydata_en = load_module("deploy_mydata_en", TOOLS / "deploy_mydata_en.py")


def test_mydata_menu_includes_item_list_and_my_camera():
    rows = [
        pair
        for pkg, labels, _source in deploy_mydata_en.JOBS
        if pkg == 5380
        for pair in labels
    ]
    assert ("timg/mcmn_tex_item_RGBA4.bclim", "Item List") in rows
    assert ("timg/mcmn_tex_camera_RGBA4.bclim", "My Camera") in rows
    assert deploy_mydata_en.ZHOUMARU_BUTTONS == frozenset(
        {"mcmn_tex_item_RGBA4", "mcmn_tex_camera_RGBA4"}
    )


def test_zhoumaru_item_and_camera_masters_match_bclim_canvas():
    root = ROOT / "assets" / "images" / "Myroom.check" / "timg"
    expected = {
        "mcmn_tex_item_RGBA4.png": (120, 18),
        "mcmn_tex_camera_RGBA4.png": (90, 18),
    }
    for name, size in expected.items():
        png = root / name
        assert png.is_file(), png
        with Image.open(png) as im:
            assert im.size == size
