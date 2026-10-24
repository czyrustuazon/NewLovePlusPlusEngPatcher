"""Text entry hides Kanji / Kana 1 / Kana 2 / S. Kana and the pencil/grid tab (§17.9).

Two copies of the input layouts exist: ``Input.arc`` in pkg 5190 (name input)
and ``Profile.arc`` in pkg 5252 (Profile, Called). Both must be hidden, and the
pencil glyph blanked, or the screen shows buttons the code ignores.

The local_data checks on ``release/bake_img.bin`` catch a stale bake: on
2026-10-17 a bake from before 44914de reached Azahar A through deploy-a and
both screens showed the buttons again.
"""

from __future__ import annotations

import re
import struct
import sys

import pytest

from conftest import TOOLS, load_module

sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "nlpp-tools"))

keyboard = load_module("deploy_input_keyboard_en", TOOLS / "deploy_input_keyboard_en.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")

HIDDEN = {
    "blyt/Lyt_Prf_Btn_ML.bclyt": (
        "Pos_Btn_C01_01",  # Kanji
        "Pos_Btn_C01_02",  # Kana 1
        "Pos_Btn_C01_03",  # Kana 2
        "Pos_Btn_C01_04",  # S. Kana
    ),
    "blyt/Lyt_Prf_Btn_Change.bclyt": ("Pos_Btn_Change",),  # pencil / grid tab
}
KEPT = {"blyt/Lyt_Prf_Btn_ML.bclyt": ("Pos_Btn_C01_05", "Pos_Btn_C01_06", "Pos_Btn_Del")}
# (pkg, layout ARC, ARCs holding Profile_Btn_Change_Obj)
COPIES = (
    (5190, "Input.arc", ("InputCTexture.arc", "InputNTexture.arc")),
    (5252, "Profile.arc", ("Profile.arc",)),
)
PENCIL = f"timg/{keyboard.PENCIL_STEM}.bclim"


def pane_flags(layout: bytes) -> dict[str, int]:
    header_size = struct.unpack_from("<H", layout, 6)[0]
    count = struct.unpack_from("<I", layout, 0x10)[0]
    off, out = header_size, {}
    for _ in range(count):
        tag = layout[off : off + 4]
        size = struct.unpack_from("<I", layout, off + 4)[0]
        if tag in (b"pan1", b"pic1"):
            name = layout[off + 12 : off + 36].split(b"\0", 1)[0].decode("ascii")
            out[name] = layout[off + 8] & 1
        off += size
    return out


def arcs_in(img_path, pkg_id: int, names) -> dict:
    from darcutil import DarcArchive
    from img import ARC, FileWindow, Image as ImgBin, Package

    img = ImgBin(str(img_path))
    img.parse(False)
    res = img.entries[pkg_id]
    pkg = Package(FileWindow(str(img_path), res.fw.base_offset, res.fw.len()), 0)
    pkg.parse(False)
    out = {
        e.fn: DarcArchive(bytearray(e.parsed()))
        for e in pkg.entries
        if isinstance(e, ARC) and e.fn in names
    }
    assert set(out) == set(names), f"pkg {pkg_id} missing {set(names) - set(out)}"
    return out


def assert_hidden(darc, where: str) -> None:
    for lyt, panes in HIDDEN.items():
        flags = pane_flags(darc.extract_file(darc.find(lyt)))
        shown = [p for p in panes if flags[p]]
        assert not shown, f"{where} {lyt}: still visible {shown}"
    for lyt, panes in KEPT.items():
        flags = pane_flags(darc.extract_file(darc.find(lyt)))
        hidden = [p for p in panes if not flags[p]]
        assert not hidden, f"{where} {lyt}: ABC/Symbols/Delete hidden {hidden}"


def assert_pencil_blank(darc, where: str) -> None:
    from bclimutil import blank_texels_left_of

    raw = darc.extract_file(darc.find(PENCIL))
    assert blank_texels_left_of(raw, keyboard.PENCIL_X_END) == raw, f"{where}: pencil drawn"


def test_hide_list_is_kanji_kana_and_tab_only():
    assert dict(keyboard.HIDE_PANES) == HIDDEN
    assert keyboard.LAYOUT_ARC == "Input.arc"


def test_profile_deploy_hides_its_own_copy():
    text = (TOOLS / "deploy_profile_en.py").read_text(encoding="utf-8")
    assert "from deploy_input_keyboard_en import blank_pencil, hide_input_panes" in text
    assert "hide_input_panes(darc)" in text
    assert "blank_pencil(darc)" in text


def test_hide_writers_are_last_on_their_packages():
    """A later script that rebuilds pkg 5190 / 5252 from vanilla would undo the hide."""
    scripts = rebuild.DEPLOY_SCRIPTS
    profile = scripts.index("deploy_profile_en.py")
    keyboard_idx = len(scripts) - 1 - scripts[::-1].index("deploy_input_keyboard_en.py")
    for i, name in enumerate(scripts):
        text = (TOOLS / name).read_text(encoding="utf-8", errors="replace")
        if i > profile and name != "deploy_profile_en.py":
            assert not re.search(r"\b5252\b|Profile\.arc", text), f"{name} writes 5252 after Profile"
        if i > keyboard_idx:
            assert not re.search(r"\b5190\b|Input\.arc", text), f"{name} writes 5190 after keyboard"


@pytest.mark.local_data
def test_hide_input_panes_on_vanilla_layouts():
    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    for pkg_id, layout_arc, _tex in COPIES:
        darc = arcs_in(vanilla, pkg_id, (layout_arc,))[layout_arc]
        flags = pane_flags(darc.extract_file(darc.find("blyt/Lyt_Prf_Btn_Change.bclyt")))
        assert flags["Pos_Btn_Change"] == 1  # vanilla shows it; the deploy must hide it
        keyboard.hide_input_panes(darc)
        assert_hidden(darc, f"vanilla+hide pkg {pkg_id}")


@pytest.mark.local_data
@pytest.mark.parametrize("pkg_id,layout_arc,tex_arcs", COPIES)
def test_release_bake_hides_input_panes(pkg_id, layout_arc, tex_arcs):
    from nlpp_paths import BAKE_IMG

    if not BAKE_IMG.is_file():
        pytest.skip("no release/bake_img.bin")
    arcs = arcs_in(BAKE_IMG, pkg_id, {layout_arc, *tex_arcs})
    where = f"release/bake_img.bin pkg {pkg_id} (stale bake? rebuild or re-run the deploy)"
    assert_hidden(arcs[layout_arc], where)
    for name in tex_arcs:
        assert_pencil_blank(arcs[name], f"{where} {name}")
