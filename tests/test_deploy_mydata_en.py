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
        {
            "mcmn_tex_todo_RGBA4",
            "mcmn_tex_status_RGBA4",
            "mcmn_tex_item_RGBA4",
            "mcmn_tex_camera_RGBA4",
        }
    )


def test_zhoumaru_menu_masters_match_bclim_canvas():
    root = ROOT / "assets" / "images" / "Myroom.check" / "timg"
    expected = {
        "mcmn_tex_todo_RGBA4.png": (108, 18),
        "mcmn_tex_status_RGBA4.png": (92, 18),
        "mcmn_tex_item_RGBA4.png": (120, 18),
        "mcmn_tex_camera_RGBA4.png": (90, 18),
    }
    for name, size in expected.items():
        png = root / name
        assert png.is_file(), png
        with Image.open(png) as im:
            assert im.size == size


def test_mydata_header_renders_gray_like_options_menu():
    """5575 last-writer paints My Data in the gray header ink, not blue M+."""
    sched = load_module(
        "deploy_schedule_header_en", TOOLS / "deploy_schedule_header_en.py"
    )
    assert ("timg/mydata_toptex_RGBA4.bclim", "My Data") in sched.LABELS
    assert "mydata_toptex_RGBA4" in sched.SKIP_UI_PNG
    im = sched.render_gray_header(128, 16, "My Data")
    opaque = {px[:3] for px in im.getdata() if px[3] > 128}
    assert opaque == {sched.ZHOUMARU_HEADER_INK}


def test_myroom_headers_pack_gray_zhoumaru_masters():
    """Every other 5575 header ships its gray Zhoumaru master, not a render."""
    sched = load_module(
        "deploy_schedule_header_en", TOOLS / "deploy_schedule_header_en.py"
    )
    for path, en in sched.LABELS:
        stem = path.rsplit("/", 1)[-1].removesuffix(".bclim")
        if stem in sched.SKIP_UI_PNG:
            continue
        im, how = sched.header_rgba(stem, en, 128, 16)
        assert how == f"{stem}.png", (stem, how)
        opaque = {px[:3] for px in im.convert("RGBA").getdata() if px[3] > 128}
        assert opaque == {sched.ZHOUMARU_HEADER_INK}, stem


def test_album_header_renders_instead_of_inbox_master():
    sched = load_module(
        "deploy_schedule_header_en", TOOLS / "deploy_schedule_header_en.py"
    )
    assert ("timg/album_top_tex.bclim", "Album") in sched.LABELS
    assert "album_top_tex" in sched.SKIP_UI_PNG
