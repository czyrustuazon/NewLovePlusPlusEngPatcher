"""Tests for PNG/BCLIM/zlib pack cache (img_pack_cache.py)."""

from __future__ import annotations

import zlib

from img_pack_cache import ImgPackCache, _zlib_slot_ok


def test_bclim_cache_hit_miss(tmp_path):
    cache = ImgPackCache(tmp_path / "img_pack")
    png = b"png-bytes"
    orig = b"\x00" * 64
    encoded = b"\x01" * 64

    assert cache.get_bclim(png, orig) is None
    cache.put_bclim(png, orig, encoded)
    assert cache.get_bclim(png, orig) == encoded
    assert cache.stats.bclim_hit == 1
    assert cache.stats.bclim_miss == 1


def test_bclim_cache_rejects_wrong_length(tmp_path):
    cache = ImgPackCache(tmp_path / "img_pack")
    png = b"x"
    orig = b"\x00" * 8
    cache.put_bclim(png, orig, b"\x01" * 8)
    cache.put_bclim(png, orig, b"\x02" * 4)  # ignored (wrong len)
    assert cache.get_bclim(png, orig) == b"\x01" * 8


def test_zlib_cache_roundtrip(tmp_path):
    cache = ImgPackCache(tmp_path / "img_pack")
    data = b"arc payload for zlib slot"
    slot = zlib.compress(data, 9)
    exact_len = len(slot) + 20  # pad with empty blocks if needed — use natural len
    exact_len = len(slot)

    cache.put_zlib(data, exact_len, slot, fine_tune=False)
    hit = cache.get_zlib(data, exact_len, fine_tune=False)
    assert hit == slot
    assert _zlib_slot_ok(slot, len(data))
