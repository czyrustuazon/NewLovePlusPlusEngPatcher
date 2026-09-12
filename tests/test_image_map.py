"""Tests for assets/images folder → package mapping."""

from __future__ import annotations

from image_map import IMAGE_MAP, normalize_folder_key, resolve_folder


def test_normalize_folder_key_strips_suffixes():
    assert normalize_folder_key("Title.check") == "title"
    assert normalize_folder_key("NCommonIcon.arc") == "ncommonicon"
    assert normalize_folder_key("  Option  ") == "option"


def test_resolve_folder_known_packages():
    assert resolve_folder("title") == (5261, "Title.arc")
    assert resolve_folder("ncommonicon") == (5238, "NCommonIcon.arc")
    assert resolve_folder("ncommonmsel(3)") == (5245, "NCommonMSel.arc")


def test_resolve_folder_unknown():
    assert resolve_folder("not_a_real_folder_xyz") is None


def test_image_map_has_menu_chrome_keys():
    for key in ("title", "ncommonmsel(3)", "ncommonmsel(4)", "ncommonicon", "option"):
        assert key in IMAGE_MAP


def test_image_map_community_pack_packages():
    assert resolve_folder("ncommon") == (5237, "NCommon.arc")
    assert resolve_folder("ncommonmsel(5)") == (5243, "NCommonMSel.arc")
    assert resolve_folder("ncommonmsel(9)") == (5239, "NCommonMSel.arc")
    assert resolve_folder("optionlock") == (5250, "OptionLock.arc")
    assert resolve_folder("camera_btn00") == (5322, "Camera_Btn00.arc")
    assert resolve_folder("haircatalog") == (5395, "HairCatalog.arc")
