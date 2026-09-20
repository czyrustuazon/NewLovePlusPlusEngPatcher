"""Eng Patch badge: keep 14px version glyphs, site URL underneath."""

from __future__ import annotations

from PIL import Image

from conftest import ROOT, TOOLS, load_module

deploy = load_module("deploy_title_engpatch_en", TOOLS / "deploy_title_engpatch_en.py")


def test_eng_patch_canvas_crops_empty_under_url():
    assert deploy.ENG_LINE_H == 14
    assert deploy.URL_H == 16
    assert deploy.LINE_GAP == 0
    assert deploy.BOTTOM_PAD == 0
    assert deploy.SITE_LINE == "newloveplus.loc.moe"
    assert deploy.ENG_PATCH_H == 26
    assert deploy.ENG_PANE_TY == 17.0
    assert deploy.POS_H_TY == -95.0
    assert deploy.ENG_PATCH_LINE.endswith("-NENE")
    assert "rc3-NENE" in deploy.ENG_PATCH_LINE
    strip = deploy.render_eng_strip(218)
    assert strip.size == (218, deploy.ENG_LINE_H)


def test_compose_eng_patch_does_not_scale_version_row():
    version = Image.new("RGBA", (218, 14), (255, 0, 0, 255))
    version.putpixel((3, 5), (0, 255, 0, 255))
    out = deploy.compose_eng_patch(version, 218)
    assert out.size == (218, deploy.ENG_PATCH_H)
    assert out.getpixel((3, 5)) == (0, 255, 0, 255)
    assert out.getpixel((10, 10)) == (255, 0, 0, 255)
    # Extra canvas is not a stretch of the red row.
    assert out.getpixel((10, 14)) != (255, 0, 0, 255)


def test_compose_eng_patch_site_is_3px_closer():
    version = deploy.render_eng_strip(218)
    out = deploy.compose_eng_patch(version, 218)
    px = out.load()
    solid = [
        y
        for y in range(out.height)
        if sum(1 for x in range(out.width) if px[x, y][3] >= 64) >= 20
    ]
    runs: list[list[int]] = []
    for y in solid:
        if not runs or y != runs[-1][-1] + 1:
            runs.append([y])
        else:
            runs[-1].append(y)
    if len(runs) == 1:
        gap = 0
    else:
        assert len(runs) == 2, runs
        gap = runs[1][0] - runs[0][-1] - 1
    assert gap == deploy.LINE_GAP
    last_ink = max(
        y for y in range(out.height) if any(px[x, y][3] > 0 for x in range(out.width))
    )
    # No extra canvas pad; site line may not fill the last rows (no descenders).
    assert out.height - 1 - last_ink >= deploy.BOTTOM_PAD
    assert last_ink >= deploy.ENG_LINE_H


def test_title_engpatch_rebuilds_title_arc_from_vanilla():
    """bak_pre_title_engpatch is packed MOD — using it as ARC source garbles the hub header."""
    text = (TOOLS / "deploy_title_engpatch_en.py").read_text(encoding="utf-8")
    assert "src_for_pkg = bak_title" not in text
    assert "src_for_pkg = VANILLA if VANILLA.is_file() else MOD_IMG" in text
    assert '("timg/Title_menu_word.bclim", "Main Menu")' in text
    assert "Title_menu_word.bclim kept vanilla" not in text


def test_title_menu_word_png_rgb_matches_glyphs():
    """Zhoumaru Title_menu_word dump had swizzled RGB; opaque pixels must stay gray."""
    png = ROOT / "assets" / "images" / "Title.check" / "timg" / "Title_menu_word.png"
    if not png.is_file():
        return
    im = Image.open(png).convert("RGBA")
    opaque = [p[:3] for p in im.getdata() if p[3] >= 32]
    assert opaque, "Title_menu_word.png has no glyphs"
    chroma = sum(abs(r - g) + abs(g - b) for r, g, b in opaque) / len(opaque)
    assert chroma < 8, f"Title_menu_word RGB dump noise chroma={chroma:.1f}"
    magenta = sum(1 for r, g, b in opaque if r > 200 and g < 40 and b > 200)
    assert magenta == 0, "Title_menu_word probe magenta must not ship"
