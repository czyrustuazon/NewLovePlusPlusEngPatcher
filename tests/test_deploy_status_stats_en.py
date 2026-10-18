"""Status stat labels and 所持リッチ pack the Zhoumaru masters."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from conftest import ROOT, TOOLS, load_module

deploy = load_module("deploy_status_stats_en", TOOLS / "deploy_status_stats_en.py")


def test_every_label_has_a_zhoumaru_master():
    """Both packages rebuild from vanilla; a missing master ships Japanese."""
    for pkg, labels in deploy.PKG_LABELS:
        (folder,) = deploy.UI_PNG_FOLDERS[pkg]
        for path, _en in labels:
            png = ROOT / "assets" / "images" / folder / "timg" / f"{Path(path).stem}.png"
            assert png.is_file(), png


def test_status_lists_owned_rich_and_exchange():
    paths = dict(next(labels for pkg, labels in deploy.PKG_LABELS if pkg == 5255))
    assert paths["timg/Scd_Result_Rich_Text.bclim"] == "Owned Rich:"
    assert "timg/Scd_Result_Btn_Exchange_Text.bclim" in paths


def test_stat_pills_keep_their_color():
    """Vanilla Scd_Status_Tit_* are colored pills, not plain ink."""
    for stem in ("Scd_Status_Tit_M", "Scd_Status_Tit_K", "Scd_Status_Tit_S", "Scd_Status_Tit_C"):
        png = ROOT / "assets" / "images" / "ScdStatus.check" / "timg" / f"{stem}.png"
        with Image.open(png) as im:
            opaque = [px[:3] for px in im.convert("RGBA").getdata() if px[3] > 200]
        assert any(max(rgb) - min(rgb) > 60 for rgb in opaque), stem
