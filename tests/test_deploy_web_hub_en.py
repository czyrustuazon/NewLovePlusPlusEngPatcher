"""In-room WEB hub pills packed by deploy_web_hub_en."""

from __future__ import annotations

from PIL import Image

from conftest import ROOT, TOOLS, load_module

deploy_web_hub_en = load_module("deploy_web_hub_en", TOOLS / "deploy_web_hub_en.py")


def test_web_hub_jobs_cover_net_and_watcher():
    paths = {path: en for _folder, path, en in deploy_web_hub_en.JOBS}
    assert paths["timg/web_tex_net_RGBA4.bclim"] == "TOWANO.NET"
    assert paths["timg/web_tex_watcher_RGBA4.bclim"] == "Towano Watcher"
    assert deploy_web_hub_en.PKG == 5380


def test_zhoumaru_web_hub_masters_exist():
    root = ROOT / "assets" / "images" / "Myroom.check" / "timg"
    expected = {
        "web_tex_net_RGBA4.png": (152, 16),
        "web_tex_watcher_RGBA4.png": (152, 18),
    }
    for name, size in expected.items():
        png = root / name
        assert png.is_file(), png
        with Image.open(png) as im:
            assert im.size == size
