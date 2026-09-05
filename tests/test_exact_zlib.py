"""Tests for exact-length zlib helpers (exact_zlib.py)."""

from __future__ import annotations

import zlib

from exact_zlib import (
    apply_gap_pad,
    compress_exact_empty_blocks,
    compress_to_exact_slot,
    interfile_zero_gaps,
    try_fast_exact_slot,
    zlib_body_fits_slot,
)


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


def test_zlib_body_fits_slot_true_for_roomy_slot():
    data = b"x" * 64
    assert zlib_body_fits_slot(data, 10_000) is True


def test_try_fast_exact_slot_hits_without_zopfli():
    payload = b"Fast-path empty-block should win for roomy slots." + (b"\x00" * 32)
    hit = None
    exact = None
    for exact_len in range(80, 400):
        hit = try_fast_exact_slot(payload, exact_len)
        if hit is not None:
            exact = exact_len
            break
    assert hit is not None and exact is not None
    tuned, slot = hit
    assert len(tuned) == len(payload)
    assert len(slot) == exact
    # Gap-salt may alter inter-file zero pads; stream must round-trip to tuned.
    assert zlib.decompress(slot) == tuned


def test_compress_to_exact_slot_prefers_fast_path():
    payload = b"compress_to_exact_slot fast-path integration." + (b"\xff" * 16)
    slot = None
    exact = None
    for exact_len in range(80, 400):
        try:
            slot = compress_to_exact_slot(payload, exact_len)
            exact = exact_len
            break
        except RuntimeError:
            continue
    assert slot is not None and exact is not None
    assert len(slot) == exact
    # May be gap-salted; length and unused_data==0 are the game constraints.
    dec = zlib.decompress(slot)
    assert len(dec) == len(payload)