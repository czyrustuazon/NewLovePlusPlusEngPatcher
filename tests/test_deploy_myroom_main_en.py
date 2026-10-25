"""Myroom main labels packed by deploy_myroom_main_en."""

from __future__ import annotations

from conftest import TOOLS, load_module

deploy_myroom_main_en = load_module(
    "deploy_myroom_main_en", TOOLS / "deploy_myroom_main_en.py"
)


def test_myroom_main_includes_love_plus_badge():
    paths = {path: en for path, en in deploy_myroom_main_en.LABELS}
    assert paths["timg/main_tex_love_RGBA4.bclim"] == "Love Plus"
    assert deploy_myroom_main_en.LOVE_STEM == "main_tex_love_RGBA4"


def test_love_plus_matches_youth_story_pill():
    """Same lettering as Zhoumaru's Youth Story pill: gray 47, ~9 px caps."""
    import numpy as np

    rgba = deploy_myroom_main_en.render_menu_label(
        58,
        16,
        "Love Plus",
        cap_px=deploy_myroom_main_en.LOVE_CAP_PX,
        weight=deploy_myroom_main_en.LOVE_WEIGHT,
    )
    assert rgba.size == (58, 16)
    arr = np.array(rgba)
    opaque = arr[:, :, 3] > 64
    assert tuple(int(x) for x in arr[opaque][:, :3].mean(0)) == (47, 47, 47)
    ys, _xs = np.where(opaque)
    assert 8 <= ys.max() - ys.min() + 1 <= 10


def _gapped_darc() -> tuple[bytes, list[tuple[int, int]]]:
    """DARC with zero pads after each file; returns (data, file spans)."""
    import fake_img as fi
    from darcutil import DarcArchive

    data = fi.darc({"a.bin": b"a" * 5, "b.bin": b"b" * 5}) + bytes(8)
    spans = sorted((e.offset, e.offset + e.length) for e in DarcArchive(data).files)
    return data, spans


def test_render_label_fits_and_refuses_overflow():
    import pytest

    im = deploy_myroom_main_en.render_label(64, 16, "Back")
    assert im.size == (64, 16) and im.getchannel("A").getbbox() is not None
    with pytest.raises(RuntimeError, match="cannot fit"):
        deploy_myroom_main_en.render_label(8, 8, "Far too long")


def test_gap_pad_fills_largest_zero_gaps_first():
    mr = deploy_myroom_main_en
    data, spans = _gapped_darc()
    (_a0, a1), (b0, b1) = spans
    gaps = mr.interfile_zero_gaps(data)
    assert gaps == sorted([(b0 - a1, a1), (len(data) - b1, b1)], reverse=True)
    rng = bytes(range(1, 256))
    padded = mr.apply_gap_pad(data, 3, rng)
    big_size, big_off = gaps[0]
    assert padded[big_off : big_off + 3] == rng[:3]
    assert padded[:big_off] == data[:big_off] and padded[big_off + 3 :] == data[big_off + 3 :]
    assert mr.apply_gap_pad(data, 0, rng) == data
    # Asking for more than the first gap spills into the next one.
    spill = mr.apply_gap_pad(data, big_size + 2, rng)
    assert mr.interfile_zero_gaps(spill) == []
    # Salted pads are no longer zero gaps; zero_all_darc_pads restores them.
    assert mr.zero_all_darc_pads(spill) == data


def test_compress_exact_empty_blocks_hits_a_reachable_length():
    import zlib

    mr = deploy_myroom_main_en
    data = b"myroom" * 50
    base = len(zlib.compress(data, 9)) + 20
    hit = next(n for n in range(base, base + 10) if mr.compress_exact_empty_blocks(data, n))
    slot = mr.compress_exact_empty_blocks(data, hit)
    assert len(slot) == hit and zlib.decompress(slot) == data
    assert mr.compress_exact_empty_blocks(data, 4) is None


def test_compress_exact_with_gap_tune(monkeypatch):
    import pytest

    mr = deploy_myroom_main_en
    data, _spans = _gapped_darc()
    monkeypatch.setattr(mr, "compress_exact_empty_blocks", lambda d, n: b"slot" if d != data else None)
    cand, slot = mr.compress_exact_with_gap_tune(data, 99)
    assert slot == b"slot" and cand != data
    monkeypatch.setattr(mr, "compress_exact_empty_blocks", lambda d, n: None)
    with pytest.raises(SystemExit, match="could not build"):
        mr.compress_exact_with_gap_tune(data, 99)
