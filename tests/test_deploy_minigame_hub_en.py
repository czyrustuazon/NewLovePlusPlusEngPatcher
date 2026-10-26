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


def test_puzzle_row_matches_zhoumaru_weight():
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

    im, src = deploy_minigame_hub_en._rgba_for(
        "Myroom.check", "game_text_puzzle_RGBA4", "Puzzle-dama", 96, 18
    )
    assert src == "render menu:Puzzle-dama"
    arr = np.array(im)
    opaque = arr[:, :, 3] > 32
    assert opaque.any()
    assert tuple(int(x) for x in arr[opaque][:, :3].mean(0).round()) == (47, 47, 47)
    # Smooth edges, not the old hard-threshold (deep-fried) mask.
    assert ((arr[:, :, 3] > 0) & (arr[:, :, 3] < 255)).sum() > 0
    ys, xs = np.where(opaque)
    glyph_h = int(ys.max() - ys.min() + 1)
    assert glyph_h >= twin_h - 1
    assert glyph_h <= twin_h + 2


def _hub_bclim(fmt: int = 0xB) -> bytes:
    """Noise pixels, so the zlib slot is as roomy as real artwork's."""
    import random

    import fake_img as fi
    from bclimutil import parse_bclim

    size = len(parse_bclim(fi.bclim(128, 32, fmt))[0])
    return fi.bclim(128, 32, fmt, pixels=random.Random(fmt).randbytes(size))


def _hub_img(tmp_path, fmt: int = 0xB):
    import fake_img as fi

    arcs: dict[int, dict[str, bytes]] = {}
    for pkg, _folder, path, _en in deploy_minigame_hub_en.JOBS:
        arcs.setdefault(pkg, {})[path] = _hub_bclim(fmt)
    pkgs = {
        pkg: fi.package([(f"P{pkg}.arc", fi.darc(files)), ("note.txt", b"note", b"TXT ", False)])
        for pkg, files in arcs.items()
    }
    return fi.img(pkgs)


def _hub_env(tmp_path, monkeypatch, fmt: int = 0xB):
    import fake_img as fi

    hub = deploy_minigame_hub_en
    paths = fi.use_paths(monkeypatch, tmp_path, hub)
    img = tmp_path / "img.bin"
    img.write_bytes(_hub_img(tmp_path, fmt))
    monkeypatch.setattr(hub, "MOD_IMG", img)
    inst = paths["AZAHAR_INSTANCES"] / "b" / "user/load/mods/00040000000F4E00/romfs/img.bin"
    inst.parent.mkdir(parents=True)
    inst.write_bytes(img.read_bytes())
    return img, inst


def test_main_packs_every_job_into_each_target(tmp_path, monkeypatch):
    import fake_img as fi
    from darcutil import DarcArchive

    img, inst = _hub_env(tmp_path, monkeypatch)
    before = fi.read_package(img, 5380)
    assert deploy_minigame_hub_en.main() == 0
    for target in (img, inst):
        for pkg, _folder, path, _en in deploy_minigame_hub_en.JOBS:
            arc = DarcArchive(fi.read_element(fi.read_package(target, pkg), f"P{pkg}.arc", tmp_path))
            assert arc.extract_file(arc.find(path)) != _hub_bclim(), (target, path)
        assert fi.read_element(fi.read_package(target, 5380), "note.txt", tmp_path) == b"note"
    assert fi.read_package(img, 5380) != before
    assert (deploy_minigame_hub_en.OUT / "game_text_puzzle_RGBA4_en.png").is_file()


def test_main_errors(tmp_path, monkeypatch):
    import pytest

    hub = deploy_minigame_hub_en
    img, _inst = _hub_env(tmp_path, monkeypatch, fmt=8)
    with pytest.raises(SystemExit, match="not ETC1A4"):
        hub.main()
    with pytest.raises(SystemExit, match="missing timg/none.bclim"):
        hub._patch_arc(fi_darc_one(), [("Myroom.check", "timg/none.bclim", "x")], tmp_path)

    img.write_bytes(_hub_img(tmp_path))

    def fail(*_a):
        raise hub.PackError("grew")

    monkeypatch.setattr(hub, "splice_packages_into_img", fail)
    with pytest.raises(SystemExit, match="splice failed: grew"):
        hub.main()

    monkeypatch.setattr(hub, "MOD_IMG", tmp_path / "none.bin")
    with pytest.raises(SystemExit, match="missing"):
        hub.main()


def fi_darc_one() -> bytes:
    import fake_img as fi

    return fi.darc({"timg/a.bclim": fi.bclim(8, 8, 0xB)})


def test_compress_slot_falls_back_to_unsalted_pads(monkeypatch):
    import fake_img as fi
    import pytest

    hub = deploy_minigame_hub_en
    from darcutil import DarcArchive

    clean = fi.darc({"a.bin": b"a" * 5, "b.bin": b"b" * 5}) + bytes(4)
    a = DarcArchive(clean).find("a.bin")
    arc = bytearray(clean)
    arc[a.offset + a.length] = 1  # urandom gap-salt between the files
    arc[-1] = 2  # and past the last file
    salted = bytes(arc)
    zeroed = hub._zero_all_darc_pads(salted)
    assert zeroed == clean

    tried = []
    monkeypatch.setattr(hub, "try_fast_exact_slot", lambda data, n: None)

    def zopfli(data, n):
        tried.append(data)
        if len(tried) == 1:
            raise RuntimeError("miss")
        return data, b"slot"

    monkeypatch.setattr(hub, "compress_exact_zopfli", zopfli)
    assert hub._compress_slot(salted, 10) == (zeroed, b"slot")
    assert tried == [salted, zeroed]

    monkeypatch.setattr(hub, "compress_exact_zopfli", lambda d, n: (_ for _ in ()).throw(RuntimeError("no")))
    with pytest.raises(RuntimeError, match="no"):
        hub._compress_slot(salted, 10)
    monkeypatch.setattr(hub, "try_fast_exact_slot", lambda data, n: (data, b"fast"))
    assert hub._compress_slot(salted, 10) == (salted, b"fast")
