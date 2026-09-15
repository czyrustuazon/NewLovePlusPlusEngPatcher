"""Tests for exact-length zlib helpers (exact_zlib.py)."""

from __future__ import annotations

import zlib

from exact_zlib import (
    _zlib_progress,
    apply_gap_pad,
    compress_exact_empty_blocks,
    compress_exact_zopfli,
    compress_to_exact_slot,
    interfile_zero_gaps,
    pad_closed_zlib_stream,
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


def _assert_pad(stream: bytes, extra: int, payload: bytes) -> None:
    target = len(stream) + extra
    out = pad_closed_zlib_stream(stream, target, expected=payload)
    assert out is not None, f"pad failed extra={extra} src={len(stream)}"
    assert len(out) == target
    d = zlib.decompressobj()
    got = d.decompress(out)
    assert got == payload
    assert d.unused_data == b""
    assert d.eof


def test_pad_closed_zlib_stream_fixed_and_dynamic():
    import zopfli.zlib as zopfli_zlib

    small = b"hello world " * 20
    big = bytes(range(256)) * 40 + b"NLPP exact zlib pad test" * 30
    for payload, extra in (
        (small, 3),
        (small, 5),
        (small, 8),
        (small, 56),
        (big, 2),
        (big, 56),
        (big, 64),
        (big, 100),
    ):
        _assert_pad(zlib.compress(payload, 9), extra, payload)
        _assert_pad(zopfli_zlib.compress(payload), extra, payload)


def test_compress_exact_zopfli_pads_56_byte_undershoot():
    import zopfli.zlib as zopfli_zlib

    payload = bytes(range(256)) * 50 + b"\x00" * 64
    z0 = zopfli_zlib.compress(payload)
    target = len(z0) + 56
    tuned, slot = compress_exact_zopfli(payload, target)
    assert tuned == payload
    assert len(slot) == target
    d = zlib.decompressobj()
    assert d.decompress(slot) == payload
    assert d.unused_data == b""
    assert d.eof


def test_pad_closed_zlib_stream_large_payload_56():
    """Reproduce the gold-rebuild miss: ~280KB uncompressed, 56B short of slot."""
    payload = bytes(range(256)) * (279848 // 256)
    stream = zlib.compress(payload, 9)
    _assert_pad(stream, 56, payload)


def test_zlib_progress_survives_cp1252_stdout(monkeypatch):
    """Windows consoles used to abort exact-zlib when progress printed '→'."""

    class Cp1252:
        encoding = "cp1252"

        def write(self, s: str) -> int:
            s.encode("cp1252")  # raises UnicodeEncodeError on arrows
            return len(s)

        def flush(self) -> None:
            return None

    monkeypatch.setattr("sys.stdout", Cp1252())
    _zlib_progress("zopfli pass 1 done -> 12 bytes (calibrating speed…)", newline=True)