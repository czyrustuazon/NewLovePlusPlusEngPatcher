"""Mini-game l2mgtex screens: hold-sideways (94/95) and Puzzle-dama (116/117/120/125)."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from conftest import TOOLS, load_module

import l2mgtex

attention = load_module(
    "deploy_minigame_textures_en", TOOLS / "deploy_minigame_textures_en.py"
)
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")

SIZES = {
    "AttentionStart_005.png": (256, 64),
    "AttentionStart_006.png": (512, 32),
    "AttentionStart_007.png": (256, 64),
    "AttentionStart_008.png": (512, 256),
    "AttentionEnd_005.png": (256, 32),
    "InstCard_Puzzle.png": (512, 256),
    "InstCard_TwinBee.png": (512, 256),
    "InstCard_KungFu.png": (512, 256),
    "PuzzleTitle_006.png": (64, 64),
    "PuzzleTitle_007.png": (64, 64),
    "PuzzleTitle_008.png": (64, 64),
    "PuzzleTitle_009.png": (512, 128),
    "PuzzleTitle_010.png": (128, 128),
    "PuzzleTitle_011.png": (256, 128),
    **{f"PuzzleSelect_{n:03d}.png": (128, 32) for n in (*range(137, 148), *range(149, 160))},
    "PuzzleSelect_070.png": (256, 64),
    "PuzzleSelect_071.png": (256, 64),
    "PuzzleSelect_015.png": (256, 64),
    "PuzzleSelect_122.png": (64, 32),
    "PuzzleSelect_123.png": (64, 32),
    **{f"PuzzleGame_{n}.png": (128, 64) for n in ("043", "044", "125", "126")},
    "PuzzleResult_004.png": (256, 64),
    "PuzzleBadge_easy.png": (32, 32),
    "PuzzleBadge_hard.png": (32, 32),
}


def test_masters_match_vanilla_texture_sizes():
    names = {png for jobs in attention.JOBS.values() for png in jobs.values()}
    assert names == set(SIZES)
    for name, size in SIZES.items():
        assert Image.open(attention.MASTERS / name).size == size, name


def test_winlose_shadows_are_flat_gray():
    """Vanilla 044/126 are one RGB on every texel; that is what lets them fit ~470 bytes."""
    for name in ("PuzzleGame_044.png", "PuzzleGame_126.png"):
        px = np.array(Image.open(attention.MASTERS / name).convert("RGBA"))
        rgb = px[px[..., 3] > 0, :3]
        assert rgb.size, name
        assert len(np.unique(rgb, axis=0)) == 1, name


def test_winlose_text_keeps_a_vertical_gradient():
    """LOSE / WIN keep the mockup gradient (no flat-colour fill to make the slots)."""
    for name in ("PuzzleGame_043.png", "PuzzleGame_125.png"):
        px = np.array(Image.open(attention.MASTERS / name).convert("RGBA"))
        rgb = px[px[..., 3] > 80, :3]
        assert len(np.unique(rgb, axis=0)) >= 8, name


def test_l2mgtex_round_trip_keeps_header():
    im = Image.new("RGBA", (16, 8), (255, 0, 0, 255))
    header = bytearray(l2mgtex.HEADER_LEN)
    header[0:16] = np.array([16, 8, l2mgtex.FMT_ETC1A4, 16 * 8], "<u4").tobytes()
    orig = bytes(header) + bytes(16 * 8)
    new = l2mgtex.encode_like(orig, im)
    assert new[: l2mgtex.HEADER_LEN] == orig[: l2mgtex.HEADER_LEN]
    assert l2mgtex.parse_header(new) == (16, 8, l2mgtex.FMT_ETC1A4, 128)
    px = np.array(l2mgtex.decode(new).convert("RGBA"))
    assert (px[..., 3] == 255).all()
    assert abs(int(px[..., 0].mean()) - 255) < 8


def test_rgba8_round_trip_is_byte_exact():
    rng = np.random.default_rng(0)
    px = rng.integers(0, 256, (16, 16, 4), dtype=np.uint8)
    header = bytearray(l2mgtex.HEADER_LEN)
    header[0:16] = np.array([16, 16, l2mgtex.FMT_RGBA8, 16 * 16 * 4], "<u4").tobytes()
    orig = bytes(header) + bytes(16 * 16 * 4)
    new = l2mgtex.encode_like(orig, Image.fromarray(px, "RGBA"))
    got = np.array(l2mgtex.decode(new))
    keep = px[..., 3] > 0
    assert (got[keep] == px[keep]).all()
    assert l2mgtex.encode_like(new, l2mgtex.decode(new)) == new


def test_rgba4444_round_trip_is_byte_exact():
    rng = np.random.default_rng(1)
    px = (rng.integers(0, 16, (16, 16, 4), dtype=np.uint8) * 17).astype(np.uint8)
    header = bytearray(l2mgtex.HEADER_LEN)
    header[0:16] = np.array([16, 16, l2mgtex.FMT_RGBA4444, 16 * 16 * 2], "<u4").tobytes()
    orig = bytes(header) + bytes(16 * 16 * 2)
    new = l2mgtex.encode_like(orig, Image.fromarray(px, "RGBA"))
    got = np.array(l2mgtex.decode(new))
    keep = px[..., 3] > 0
    assert (got[keep] == px[keep]).all()
    assert l2mgtex.encode_like(new, l2mgtex.decode(new)) == new


def test_bake_runs_attention_before_cesa():
    scripts = rebuild.DEPLOY_SCRIPTS
    assert "deploy_minigame_textures_en.py" in scripts
    assert scripts.index("deploy_minigame_textures_en.py") < scripts.index("deploy_cesa_en.py")


@pytest.mark.local_data
def test_vanilla_packages_take_en_masters_at_same_size():
    from img import Image as ImgBin
    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    raw = vanilla.read_bytes()
    img = ImgBin(str(vanilla))
    img.parse(False)
    for pkg_id, jobs in attention.JOBS.items():
        res = img.entries[pkg_id]
        pkg_raw = raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
        new = attention.patch_package(pkg_raw, jobs)
        assert len(new) == len(pkg_raw)

        src = attention.OUT / "_pkg" / "new.pkg"
        from img import FileWindow, Package

        old = Package(FileWindow(str(attention.OUT / "_pkg" / "src.pkg")), 0)
        old.parse(False)
        pkg = Package(FileWindow(str(src)), 0)
        pkg.parse(False)
        for before, elem in zip(old.entries, pkg.entries):
            if elem.fn not in jobs:
                continue
            master = Image.open(attention.MASTERS / jobs[elem.fn])
            assert elem.parsed() == l2mgtex.encode_like(before.parsed(), master), elem.fn
            # Alpha survives the 4-bit ETC1A4 nibble.
            got = np.array(l2mgtex.decode(elem.parsed()).convert("RGBA")).astype(int)
            want = np.array(master).astype(int)
            assert np.abs(got[..., 3] - want[..., 3]).max() <= 17, elem.fn
