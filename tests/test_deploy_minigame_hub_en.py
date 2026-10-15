"""In-room Mini-game hub labels packed by deploy_minigame_hub_en."""

from __future__ import annotations

import numpy as np
from PIL import Image

from conftest import ROOT, TOOLS, load_module

deploy_minigame_hub_en = load_module(
    "deploy_minigame_hub_en", TOOLS / "deploy_minigame_hub_en.py"
)


def test_minigame_hub_jobs_cover_title_and_rows():
    by_path = {
        path: (pkg, en) for pkg, _folder, path, en in deploy_minigame_hub_en.JOBS
    }
    assert by_path["timg/game_text_title_RGBA4.bclim"] == (5575, "Mini-Game")
    assert by_path["timg/game_text_puzzle_RGBA4.bclim"] == (5380, "Puzzle-dama")
    assert by_path["timg/game_text_twinbe_RGBA4.bclim"] == (5380, "TwinBee+")
    assert by_path["timg/game_text_kanfu_RGBA4.bclim"] == (5380, "Yie Ar Kung-Fu+")
    assert "game_text_puzzle_RGBA4" in deploy_minigame_hub_en.SKIP_UI_PNG


def test_zhoumaru_minigame_hub_masters_exist():
    expected = {
        ROOT
        / "assets"
        / "images"
        / "MyroomHeader.check"
        / "timg"
        / "game_text_title_RGBA4.png": (128, 16),
        ROOT
        / "assets"
        / "images"
        / "Myroom.check"
        / "timg"
        / "game_text_puzzle_RGBA4.png": (96, 18),
        ROOT
        / "assets"
        / "images"
        / "Myroom.check"
        / "timg"
        / "game_text_twinbe_RGBA4.png": (110, 18),
        ROOT
        / "assets"
        / "images"
        / "Myroom.check"
        / "timg"
        / "game_text_kanfu_RGBA4.png": (166, 18),
    }
    for png, size in expected.items():
        assert png.is_file(), png
        with Image.open(png) as im:
            assert im.size == size


def test_render_game_text_row_matches_zhoumaru_weight():
    """Puzzle-dama should be ink-47 and ~TwinBee glyph height, not header-aa."""
    twin = Image.open(
        ROOT
        / "assets"
        / "images"
        / "Myroom.check"
        / "timg"
        / "game_text_twinbe_RGBA4.png"
    ).convert("RGBA")
    tarr = np.array(twin)
    tys, txs = np.where(tarr[:, :, 3] > 32)
    twin_h = int(tys.max() - tys.min() + 1)

    im = deploy_minigame_hub_en.render_game_text_row(96, 18, "Puzzle-dama")
    arr = np.array(im)
    opaque = arr[:, :, 3] > 32
    assert opaque.any()
    assert tuple(int(x) for x in arr[opaque][:, :3].mean(0).round()) == (47, 47, 47)
    ys, xs = np.where(opaque)
    glyph_h = int(ys.max() - ys.min() + 1)
    assert glyph_h >= twin_h - 1
    assert glyph_h <= twin_h + 2
