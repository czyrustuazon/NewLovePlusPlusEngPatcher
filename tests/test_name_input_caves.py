"""Name-input caves must sit in .text RX pages (real 3DS NX)."""

from __future__ import annotations

from conftest import SRC, load_module

cave_map = load_module("patch_input_cave_map", SRC / "patch_input_cave_map.py")
romaji = load_module("patch_input_romaji", SRC / "patch_input_romaji.py")
cand = load_module(
    "patch_input_candidate_nullguard", SRC / "patch_input_candidate_nullguard.py"
)
pane = load_module(
    "patch_input_pane_registry_nullguard",
    SRC / "patch_input_pane_registry_nullguard.py",
)
fill = load_module(
    "patch_input_candmode_fillflag_reset",
    SRC / "patch_input_candmode_fillflag_reset.py",
)


def test_name_input_caves_are_inside_text_rx():
    """Regression: Luma prefetch abort PC 0x007E6A78 was the old .rodata pad."""
    end = cave_map.TEXT_PAGE_END
    assert cave_map.ADDR_SHARED_PAD < end
    assert cave_map.ADDR_ROMAJI_CAVE < end
    assert cand.CAVE1 < end and cand.CAVE2 + 0x18 <= end
    assert pane.CAVE + pane.CAVE_LEN <= end
    assert fill.CAVE + fill.CAVE_LEN <= end
    blob = romaji.build_romaji_blob()
    assert romaji.ADDR_CAVE + len(blob) <= end
    assert cave_map.OLD_RODATA_SHARED_PAD >= end
    assert cave_map.OLD_RODATA_ROMAJI_CAVE >= end


def test_name_input_caves_do_not_overlap():
    ranges = [
        (cand.CAVE1, cand.CAVE1 + 0x18),
        (cand.CAVE2, cand.CAVE2 + 0x18),
        (pane.CAVE, pane.CAVE + pane.CAVE_LEN),
        (fill.CAVE, fill.CAVE + fill.CAVE_LEN),
        (romaji.ADDR_CAVE, romaji.ADDR_CAVE + len(romaji.build_romaji_blob())),
    ]
    for i, (a0, a1) in enumerate(ranges):
        for b0, b1 in ranges[i + 1 :]:
            assert a1 <= b0 or b1 <= a0, hex(a0)
