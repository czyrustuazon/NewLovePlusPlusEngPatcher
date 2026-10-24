"""Communication Battle MSel rows (pkg 5241) + MultiWin header (5237).

Session pills ``対戦相手を募集`` / ``対戦参加`` are A8 BCLIMs. Zhoumaru
``NCommonMSel(7).check`` ships Find Battle Opponent / Join Battle; the home
row and white bar use Communication Battle (not Wireless Battle).
"""

from __future__ import annotations

from PIL import Image

from conftest import ROOT, TOOLS, load_module

msel = load_module("deploy_msel_menus_en", TOOLS / "deploy_msel_menus_en.py")
multiwin = load_module(
    "deploy_multiwin_headers_en", TOOLS / "deploy_multiwin_headers_en.py"
)
deploy_common = load_module("deploy_common", TOOLS / "deploy_common.py")

BATTLE_FOLDER = "NCommonMSel(7).check"
# Live A8 pill size for Com_M_Sel_Btn_Text04_* @ 5241.
BTN_SIZE = (246, 48)
BATTLE_STEMS = {
    "Com_M_Sel_Btn_Text04_03_00": "Communication Battle",
    "Com_M_Sel_Btn_Text04_03_01": "Find Battle Opponent",
    "Com_M_Sel_Btn_Text04_03_02": "Join Battle",
}
PLATE_BATTLE = ("Com_M_Sel_Plate_Text04_03_00.bclim", "Communication Battle")
MULTIWIN_BATTLE = "timg/Com_MultiWin_W01_Text04_03_00.bclim"


def test_msel_5241_battle_labels():
    by_base = dict(msel.PKG_LABELS[5241])
    for stem, en in BATTLE_STEMS.items():
        assert by_base[f"{stem}.bclim"] == en
    assert by_base[PLATE_BATTLE[0]] == PLATE_BATTLE[1]
    # Do not regress to the old shorthand on these stems.
    for base, en in by_base.items():
        if "Text04_03" in base:
            assert en != "Wireless Battle", base


def test_multiwin_battle_header_is_communication_battle():
    header = dict(multiwin.HEADER_LABELS)
    extras = dict(multiwin.EXTRA_LABELS)
    assert header[MULTIWIN_BATTLE] == "Communication Battle"
    assert extras[MULTIWIN_BATTLE] == "Communication Battle"
    assert header[MULTIWIN_BATTLE] != "Wireless Battle"


def test_zhoumaru_battle_masters_exist():
    """Zhoumaru pack canvases match the live A8 BCLIM pill size."""
    root = ROOT / "assets" / "images" / BATTLE_FOLDER / "timg"
    for stem in BATTLE_STEMS:
        png = root / f"{stem}.png"
        assert png.is_file(), png
        with Image.open(png) as im:
            assert im.size == BTN_SIZE, f"{stem}: {im.size} != {BTN_SIZE}"
            rgba = im.convert("RGBA")
            assert any(px[3] > 32 for px in rgba.getdata()), stem


def test_find_ui_png_prefers_zhoumaru_battle_pills():
    """Deploy must resolve Zhoumaru masters, not font-render the battle rows."""
    folders = (
        "NCommonMSel(3).check",
        "NCommonMSel(4).check",
        "NCommonMSel(6).check",
        "NCommonMSel(7).check",
        "NCommonMSel(8).check",
        "NCommonMSel(9).check",
    )
    for stem in BATTLE_STEMS:
        master = deploy_common.find_ui_png(folders, stem, BTN_SIZE)
        assert master is not None, stem
        assert master.name == f"{stem}.png"
        assert BATTLE_FOLDER in master.parts
        assert stem not in msel.SKIP_UI_PNG
        assert stem not in msel.FONT_BTN_H


def test_msel_menus_on_bake_chrome_list():
    text = (TOOLS / "rebuild_bake_img.py").read_text(encoding="utf-8")
    assert "deploy_msel_menus_en.py" in text
    assert "deploy_multiwin_headers_en.py" in text


def test_flatten_ink_keeps_alpha_and_uses_master_ink():
    im = Image.new("RGBA", (8, 4), (0, 0, 0, 0))
    im.putpixel((1, 1), (51, 51, 51, 255))
    im.putpixel((2, 1), (200, 10, 10, 119))
    out = msel.flatten_ink(im)
    assert out.getchannel("A").tobytes() == im.getchannel("A").tobytes()
    assert {px[:3] for px in out.getdata()} == {(51, 51, 51)}


def test_zhoumaru_plate_keeps_vanilla_etc1a4(tmp_path):
    """A8 drops the Zhoumaru ink; the Communication Menu plate went light gray."""
    import pytest

    try:
        vanilla = msel.pick_vanilla()
    except SystemExit:  # CI has no img.bin
        vanilla = None
    if vanilla is None or not vanilla.is_file():
        pytest.skip("no vanilla img.bin")
    from darcutil import DarcArchive
    from img import ARC, FileWindow, Image as ImgBin, Package

    img = ImgBin(str(vanilla))
    img.parse(False)
    res = img.entries[5241]
    pkg = Package(FileWindow(str(vanilla), res.fw.base_offset, res.fw.len()), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    darc = DarcArchive(bytearray(arc.parsed()))
    stem = "Com_M_Sel_Plate_Text04_01_00"
    raw = darc.extract_file(darc.find(f"timg/{stem}.bclim"))
    assert msel.parse_bclim(raw)[3] == 0xB
    new = msel.make_en_bclim(raw, "Communication Menu", tmp_path, hard=False, salt=0.0, stem=stem)
    assert len(new) == len(raw)
    assert msel.parse_bclim(new)[3] == 0xB
