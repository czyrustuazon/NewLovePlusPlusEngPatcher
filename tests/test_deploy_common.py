"""Tests for deploy script shared helpers."""

from __future__ import annotations

from pathlib import Path

from conftest import TOOLS, load_module

deploy_common = load_module("deploy_common", TOOLS / "deploy_common.py")


def test_resolve_img_paths_prefers_bake(tmp_path: Path, monkeypatch):
    bake = tmp_path / "release" / "bake_img.bin"
    vanilla = tmp_path / "vanilla.img.bin"
    bake.parent.mkdir(parents=True)
    bake.write_bytes(b"bake")
    vanilla.write_bytes(b"vanilla")
    monkeypatch.setattr(deploy_common, "BAKE_IMG", bake)
    monkeypatch.setattr(deploy_common, "AZAHAR_MOD_IMG", tmp_path / "azahar.img.bin")
    monkeypatch.setenv("NLPP_DEPLOY_IMG", "")
    monkeypatch.setattr(deploy_common, "find_vanilla_img", lambda: vanilla)

    primary, van = deploy_common.resolve_img_paths()
    assert primary == bake.resolve()
    assert van == vanilla.resolve()


def test_resolve_img_paths_env_override(tmp_path: Path, monkeypatch):
    custom = tmp_path / "custom.img.bin"
    custom.write_bytes(b"x")
    monkeypatch.setenv("NLPP_DEPLOY_IMG", str(custom))
    monkeypatch.setattr(deploy_common, "find_vanilla_img", lambda: custom)

    primary, van = deploy_common.resolve_img_paths()
    assert primary == custom.resolve()


def test_iter_deploy_targets_includes_primary_and_bake(tmp_path: Path, monkeypatch):
    primary = tmp_path / "primary.img.bin"
    bake = tmp_path / "release" / "bake_img.bin"
    bake.parent.mkdir(parents=True)
    primary.write_bytes(b"p")
    bake.write_bytes(b"b")
    monkeypatch.setattr(deploy_common, "BAKE_IMG", bake)
    monkeypatch.setattr(deploy_common, "AZAHAR_MOD_IMG", tmp_path / "missing.img.bin")
    monkeypatch.setenv("NLPP_ALSO_AZAHAR", "0")

    targets = deploy_common.iter_deploy_targets(primary)
    assert primary.resolve() in targets
    assert bake.resolve() in targets


def test_iter_deploy_targets_includes_ab_instances(tmp_path: Path, monkeypatch):
    primary = tmp_path / "primary.img.bin"
    primary.write_bytes(b"p")
    inst = (
        tmp_path
        / "ab_test"
        / "azahar_instances"
        / "a"
        / "user"
        / "load"
        / "mods"
        / "00040000000F4E00"
        / "romfs"
        / "img.bin"
    )
    inst.parent.mkdir(parents=True)
    inst.write_bytes(b"inst")
    monkeypatch.setattr(deploy_common, "BAKE_IMG", tmp_path / "missing-bake.img.bin")
    monkeypatch.setattr(deploy_common, "AZAHAR_MOD_IMG", tmp_path / "missing.img.bin")
    monkeypatch.setattr(deploy_common, "AZAHAR_INSTANCES", tmp_path / "ab_test" / "azahar_instances")
    monkeypatch.delenv("NLPP_ALSO_AZAHAR", raising=False)

    targets = deploy_common.iter_deploy_targets(primary)
    assert inst.resolve() in targets


def test_azahar_instances_live_outside_out():
    inst = deploy_common.AZAHAR_INSTANCES
    assert inst.parent.name == "ab_test"
    assert inst.name == "azahar_instances"
    assert "out" not in inst.parts[-2:]


def test_find_ui_png_fits_mismatched_size(tmp_path, monkeypatch):
    from PIL import Image

    assets = tmp_path / "assets" / "images" / "Title.check" / "timg"
    assets.mkdir(parents=True)
    png = assets / "Eng_Patch.png"
    Image.new("RGBA", (50, 10), (255, 0, 0, 255)).save(png)

    monkeypatch.setattr(deploy_common, "ROOT", tmp_path)
    got = deploy_common.find_ui_png(("Title.check",), "Eng_Patch", (218, 14))
    assert got != png
    with Image.open(png) as im:
        assert im.size == (50, 10)
    with Image.open(got) as im:
        assert im.size == (218, 14)


def test_find_ui_png_fills_small_strip_glyphs(tmp_path, monkeypatch):
    from PIL import Image

    assets = tmp_path / "assets" / "images" / "NCommon.check" / "timg"
    assets.mkdir(parents=True)
    png = assets / "Com_M_Sel_Plate_Text02_01_01.png"
    src = Image.new("RGBA", (192, 16), (0, 0, 0, 0))
    # 8px-tall ink, same as Zhoumaru's 192×16 Confession Memories master.
    for y in range(4, 12):
        for x in range(55, 137):
            src.putpixel((x, y), (255, 255, 255, 255))
    src.save(png)

    monkeypatch.setattr(deploy_common, "ROOT", tmp_path)
    got = deploy_common.find_ui_png(
        ("NCommon.check",), "Com_M_Sel_Plate_Text02_01_01", (144, 28)
    )
    assert got != png
    with Image.open(png) as im:
        assert im.size == (192, 16)
    with Image.open(got) as im:
        assert im.size == (144, 28)
        bbox = im.getchannel("A").getbbox()
    assert bbox is not None
    gh = bbox[3] - bbox[1]
    # 144×28 plate is width-limited for "Confession Memories"; 14px matches
    # sibling Event Gallery (~15px) instead of the 8px letterboxed strip.
    assert gh >= 12, f"glyph height {gh} still letterboxed"


def test_find_ui_png_same_size_strip_not_stretched(tmp_path, monkeypatch):
    from PIL import Image

    assets = tmp_path / "assets" / "images" / "NCommon.check" / "timg"
    assets.mkdir(parents=True)
    png = assets / "Com_MultiWin_W01_Text04_01_01.png"
    src = Image.new("RGBA", (192, 16), (0, 0, 0, 0))
    for y in range(4, 12):
        for x in range(55, 137):
            src.putpixel((x, y), (255, 255, 255, 255))
    src.save(png)

    monkeypatch.setattr(deploy_common, "ROOT", tmp_path)
    got = deploy_common.find_ui_png(
        ("NCommon.check",), "Com_MultiWin_W01_Text04_01_01", (192, 16)
    )
    assert got == png


def test_find_ui_png_does_not_upscale_onto_multiwin_bar(tmp_path, monkeypatch):
    from PIL import Image

    assets = tmp_path / "assets" / "images" / "NCommonMSel(7).check" / "timg"
    assets.mkdir(parents=True)
    png = assets / "Com_M_Sel_Plate_Text04_01_01.png"
    src = Image.new("RGBA", (144, 28), (0, 0, 0, 0))
    for y in range(10, 18):
        for x in range(20, 120):
            src.putpixel((x, y), (255, 255, 255, 255))
    src.save(png)

    monkeypatch.setattr(deploy_common, "ROOT", tmp_path)
    got = deploy_common.find_ui_png(
        ("NCommonMSel(7).check",), "Com_M_Sel_Plate_Text04_01_01", (192, 16)
    )
    assert got is None


def test_contain_no_upscale_does_not_blow_up_strip(tmp_path):
    from PIL import Image

    png = tmp_path / "strip.png"
    src = Image.new("RGBA", (192, 16), (0, 0, 0, 0))
    for y in range(4, 12):
        for x in range(40, 150):
            src.putpixel((x, y), (255, 255, 255, 255))
    src.save(png)
    got = deploy_common.contain_no_upscale(png, (144, 28))
    assert got.size == (144, 28)
    bbox = got.getchannel("A").getbbox()
    assert bbox is not None
    gh = bbox[3] - bbox[1]
    assert gh <= 16, f"glyph height {gh} was upscaled onto 144x28"


def test_ui_font_missing_exits(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(deploy_common, "UI_FONT", tmp_path / "missing.ttf")
    try:
        deploy_common.ui_font(12)
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "missing UI font" in str(exc)


def test_profile_header_glyph_height_matches_heart_to_heart():
    import numpy as np
    import pytest

    if not deploy_common.HEISEI_W5.is_file():
        pytest.skip("Heisei W5 reference font missing")
    h2h = deploy_common.render_header_aa(192, 16, "Heart to Heart")
    prof = deploy_common.render_header_aa(144, 16, "Profile")

    def glyph_h(im) -> int:
        a = np.array(im.getchannel("A"))
        ys, _ = np.where(a > 20)
        return int(ys.max() - ys.min() + 1)

    assert abs(glyph_h(h2h) - glyph_h(prof)) <= 1
    assert 11 <= glyph_h(prof) <= 14
    assert h2h.size == (192, 16)
    assert prof.size == (144, 16)


def test_skip_full_img_backup_for_gold_bake(tmp_path: Path, monkeypatch):
    bake = tmp_path / "release" / "bake_img.bin"
    bake.parent.mkdir(parents=True)
    bake.write_bytes(b"bake")
    other = tmp_path / "img.bin"
    other.write_bytes(b"mod")
    monkeypatch.setattr(deploy_common, "BAKE_IMG", bake)
    monkeypatch.delenv("NLPP_NO_IMG_BACKUP", raising=False)
    assert deploy_common.skip_full_img_backup(bake) is True
    assert deploy_common.skip_full_img_backup(other) is False
    monkeypatch.setenv("NLPP_NO_IMG_BACKUP", "1")
    assert deploy_common.skip_full_img_backup(other) is True


def test_maybe_backup_img_skips_gold_bake(tmp_path: Path, monkeypatch, capsys):
    bake = tmp_path / "release" / "bake_img.bin"
    bake.parent.mkdir(parents=True)
    bake.write_bytes(b"bake-bytes")
    monkeypatch.setattr(deploy_common, "BAKE_IMG", bake)
    monkeypatch.delenv("NLPP_NO_IMG_BACKUP", raising=False)
    bak = deploy_common.maybe_backup_img(bake, "confirm_btn")
    assert bak == bake.with_suffix(".bin.bak_pre_confirm_btn")
    assert not bak.is_file()
    assert "skip img backup" in capsys.readouterr().out


def test_maybe_backup_img_copies_layeredfs(tmp_path: Path, monkeypatch):
    bake = tmp_path / "release" / "bake_img.bin"
    bake.parent.mkdir(parents=True)
    img = tmp_path / "azahar" / "img.bin"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"layeredfs")
    monkeypatch.setattr(deploy_common, "BAKE_IMG", bake)
    monkeypatch.delenv("NLPP_NO_IMG_BACKUP", raising=False)
    bak = deploy_common.maybe_backup_img(img, "confirm_btn")
    assert bak.is_file()
    assert bak.read_bytes() == b"layeredfs"
