"""Business Card field-label stickers Seal_T000..T004 (pkgs 4315–4319)."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from conftest import ROOT, TOOLS, load_module
from image_map import resolve_folder
from pack_images import iter_asset_pngs, png_to_bclim_candidates, prefer_asset_folders

seal = load_module("render_card_seal_labels_en", TOOLS / "render_card_seal_labels_en.py")

# Straight tab top ends at x≈86; past that is the slant and the field below.
TAB_BOX = (9, 15, 87, 30)


def _fake_plate() -> Image.Image:
    """Striped 160×64 tab: rows alternate, colour ramps left to right."""
    a = np.zeros((64, 160, 4), dtype=np.uint8)
    for y in range(64):
        for x in range(160):
            v = 200 + (x % 40) + (10 if y % 2 else 0)
            a[y, x] = (v - 20, v - 10, min(v, 255), 255)
    return Image.fromarray(a, "RGBA")


def _ink_mask(sticker: Image.Image, plate: Image.Image) -> np.ndarray:
    a = np.asarray(sticker, dtype=int)
    b = np.asarray(plate, dtype=int)
    return np.abs(a - b).max(axis=2) > 12


def test_labels_cover_t000_to_t004_in_package_order():
    assert [(pkg, name) for pkg, name, *_ in seal.LABELS] == [
        (4315 + n, f"Seal_T{n:03d}") for n in range(5)
    ]
    assert [en for _p, _n, en, *_ in seal.LABELS] == [
        "Name",
        "She Calls Me",
        "Hometown",
        "I Call Her",
        "Girlfriend's Name",
    ]


def test_wipe_glyphs_interpolates_rows_and_leaves_the_rest():
    plate = _fake_plate()
    # Paint a "glyph" the wipe must remove.
    dirty = plate.copy()
    for x in range(12, 30):
        for y in range(19, 27):
            dirty.putpixel((x, y), (20, 60, 100, 255))
    out = np.asarray(seal.wipe_glyphs(dirty, 30), dtype=int)
    src = np.asarray(plate, dtype=int)
    y0, y1 = seal.WIPE_Y
    x1 = 30 + 3
    # Glyph gone: every wiped pixel lies between the two anchor columns.
    for y in range(y0, y1):
        lo = np.minimum(src[y, seal.LEFT_X], src[y, x1])
        hi = np.maximum(src[y, seal.LEFT_X], src[y, x1])
        seg = out[y, seal.LEFT_X : x1 + 1]
        assert (seg >= lo - 1).all() and (seg <= hi + 1).all()
    # Nothing outside the wipe band moves.
    assert (out[:y0] == src[:y0]).all()
    assert (out[y1:] == src[y1:]).all()
    assert (out[:, x1 + 1 :] == src[:, x1 + 1 :]).all()


def test_wipe_never_reaches_past_the_straight_tab_top():
    """T004's JP ran to x=82; the right anchor must stay on the tab."""
    plate = _fake_plate()
    out = np.asarray(seal.wipe_glyphs(plate, 200), dtype=int)
    src = np.asarray(plate, dtype=int)
    assert (out[:, seal.TEXT_X1 + 2 :] == src[:, seal.TEXT_X1 + 2 :]).all()


@pytest.mark.skipif(not seal.FONT.is_file(), reason="Chubu Maru Gothic not present")
@pytest.mark.parametrize("pkg,name,en,jp_end,ink", seal.LABELS)
def test_english_ink_stays_inside_the_tab(pkg, name, en, jp_end, ink):
    plate = _fake_plate()
    out = seal.render_sticker(plate.copy(), en, jp_end, ink)
    assert out.size == (160, 64) and out.mode == "RGBA"
    ys, xs = np.nonzero(_ink_mask(seal.render_text(en, ink).convert("RGBA"), Image.new("RGBA", (160, 64))))
    assert len(xs) > 40, f"{name}: no text drawn"
    x0, y0, x1, y1 = TAB_BOX
    assert xs.min() >= x0 and xs.max() < x1, f"{name}: x {xs.min()}..{xs.max()}"
    assert ys.min() >= y0 and ys.max() < y1, f"{name}: y {ys.min()}..{ys.max()}"
    # The field the player writes in stays untouched.
    assert (np.asarray(out)[32:] == np.asarray(plate)[32:]).all()


@pytest.mark.skipif(not seal.FONT.is_file(), reason="Chubu Maru Gothic not present")
def test_text_uses_the_sticker_ink():
    layer = np.asarray(seal.render_text("Name", (36, 78, 112)))
    solid = layer[layer[..., 3] == 255][:, :3]
    assert len(solid)
    assert tuple(solid[0]) == (36, 78, 112)


@pytest.mark.parametrize("pkg,name,en,jp_end,ink", seal.LABELS)
def test_committed_png_is_packed_into_its_package(pkg, name, en, jp_end, ink):
    png = seal.asset_path(name)
    assert png.is_file(), f"run tools/render_card_seal_labels_en.py ({png})"
    with Image.open(png) as im:
        assert im.size == (160, 64)
        assert im.mode == "RGBA"
    folder = png.parents[1]
    assert resolve_folder(folder.name) == (pkg, f"{folder.name}.arc")
    assert prefer_asset_folders(ROOT / "assets" / "images")[folder.name.lower()] == folder
    assert iter_asset_pngs(folder) == [png]
    assert png_to_bclim_candidates(png)[0] == f"timg/{name}.bclim"


@pytest.mark.local_data
@pytest.mark.parametrize("pkg,name,en,jp_end,ink", seal.LABELS)
def test_committed_png_matches_a_fresh_render(pkg, name, en, jp_end, ink):
    if not seal.VANILLA_IMG.is_file():
        pytest.skip("no vanilla img.bin")
    vanilla = seal.load_vanilla(pkg, name)
    fresh = seal.render_sticker(vanilla.copy(), en, jp_end, ink)
    with Image.open(seal.asset_path(name)) as im:
        committed = np.asarray(im.convert("RGBA"))
    assert (np.asarray(fresh) == committed).all(), f"{name}: re-run the renderer"
    # Only the tab label area differs from vanilla.
    diff = np.nonzero(_ink_mask(fresh, vanilla))
    if len(diff[0]):
        assert diff[0].min() >= TAB_BOX[1] and diff[0].max() < TAB_BOX[3]
        assert diff[1].min() >= TAB_BOX[0] and diff[1].max() < TAB_BOX[2]
