"""Eng Patch badge: keep 14px version glyphs, add 16px project URL row."""

from __future__ import annotations

from PIL import Image

from conftest import TOOLS, load_module

deploy = load_module("deploy_title_engpatch_en", TOOLS / "deploy_title_engpatch_en.py")


def test_eng_patch_canvas_is_14_plus_16():
    assert deploy.ENG_LINE_H == 14
    assert deploy.URL_H == 16
    assert deploy.SITE_LINE == "newloveplus.loc.moe"
    assert deploy.ENG_PATCH_H == 30


def test_compose_eng_patch_does_not_scale_version_row():
    version = Image.new("RGBA", (218, 14), (255, 0, 0, 255))
    version.putpixel((3, 5), (0, 255, 0, 255))
    out = deploy.compose_eng_patch(version, 218)
    assert out.size == (218, 30)
    assert out.getpixel((3, 5)) == (0, 255, 0, 255)
    assert out.getpixel((10, 10)) == (255, 0, 0, 255)
    # Extra 16px is not a stretch of the red row.
    assert out.getpixel((10, 14)) != (255, 0, 0, 255)
