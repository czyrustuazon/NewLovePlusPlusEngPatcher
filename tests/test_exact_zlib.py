"""Tests for exact-length zlib helpers (exact_zlib.py)."""

from __future__ import annotations

import zlib

from exact_zlib import apply_gap_pad, compress_exact_empty_blocks, interfile_zero_gaps


def test_interfile_zero_gaps_finds_zero_runs():
    data = b"abc\x00\x00\x00\x00def\x00\x00ghi"
    runs = interfile_zero_gaps(data, min_len=2)
    assert runs
    assert all(size >= 2 for size, _off in runs)


def test_apply_gap_pad_fills_gaps():
    data = b"AA\x00\x00\x00\x00BB"
    padded = apply_gap_pad(data, 2, b"\x11\x22\x33\x44")
    assert padded != data
    assert padded[2:4] == b"\x11\x22"


def test_compress_exact_empty_blocks_roundtrip():
    payload = b"Hello NLPP exact zlib slot test payload."
    slot = None
    for exact_len in range(len(payload) + 40, len(payload) + 200):
        slot = compress_exact_empty_blocks(payload, exact_len)
        if slot is not None:
            break
    assert slot is not None
    assert len(slot) == exact_len
    dec = zlib.decompress(slot)
    assert dec == payload
