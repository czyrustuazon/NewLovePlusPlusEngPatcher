"""Gallery Common Options + Called-As girl list (pkg 5153).

``Gallery_txt09`` is one BCLIM shared by the Gallery Options strip and
``Lyt_Gal_Plate01`` (the three-girl Called As rows). Both must stay
Zhoumaru ``Called As:`` — not JP ``呼ばれ方：`` and not TRB ``Name calling``.
"""

from __future__ import annotations

from PIL import Image

from conftest import ROOT, TOOLS, load_module

deploy = load_module("deploy_gallery_common_en", TOOLS / "deploy_gallery_common_en.py")
deploy_common = load_module("deploy_common", TOOLS / "deploy_common.py")


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


def test_called_as_label_not_trb_name_calling_or_jp():
    """Plate01 / Options chrome is BCLIM copy, not the TRB gloss."""
    by_path = dict(deploy.LABELS)
    assert by_path["timg/Gallery_txt09.bclim"] != "Name calling"
    assert "呼ばれ" not in by_path["timg/Gallery_txt09.bclim"]
    assert by_path["timg/Gallery_txt09.bclim"].endswith(":")


def test_zhoumaru_called_as_and_playback_masters_exist():
    """Zhoumaru pack canvases match the live BCLIM sizes (ETC1A4 strips)."""
    root = ROOT / "assets" / "images" / "Gallery_Common.check" / "timg"
    expected = {
        "Gallery_txt09.png": (64, 16),  # Called As: — Options + Plate01 rows
        "Gallery_txt08.png": (80, 16),  # Playback Speed
    }
    for name, size in expected.items():
        png = root / name
        assert png.is_file(), png
        with Image.open(png) as im:
            assert im.size == size, f"{name}: {im.size} != {size}"


def test_find_ui_png_prefers_zhoumaru_called_as():
    """Deploy must resolve the Zhoumaru master, not fall back to Heisei render."""
    assert "Gallery_Common.check" in deploy.FOLDERS
    master = deploy_common.find_ui_png(
        deploy.FOLDERS, "Gallery_txt09", (64, 16)
    )
    assert master is not None
    assert master.name == "Gallery_txt09.png"
    assert "Gallery_Common.check" in master.parts
    with Image.open(master) as im:
        rgba = im.convert("RGBA")
        assert rgba.size == (64, 16)
        # Alpha glyphs present (Zhoumaru paint, not an empty slot).
        assert any(px[3] > 32 for px in rgba.getdata())


def test_gallery_common_on_bake_chrome_list():
    text = (TOOLS / "rebuild_bake_img.py").read_text(encoding="utf-8")
    assert "deploy_gallery_common_en.py" in text
    # Keep pkg comment so bake order reviewers still see 5153.
    assert "5153" in text.split("deploy_gallery_common_en.py", 1)[1][:80]
