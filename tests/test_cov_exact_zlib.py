"""Branch coverage for exact_zlib's fallbacks.

The zopfli / gap-tune search is steered with fakes: a zopfli whose output
length depends on how much gap salt went in, and stand-ins for the empty-block
builders. Each test runs in milliseconds; the real compressors are covered by
test_exact_zlib*.py.
"""

from __future__ import annotations

import types
import zlib

import pytest

import exact_zlib as ez

GAPPY = b"A" * 16 + bytes(32) + b"B" * 16 + bytes(32) + b"C"  # cap = 64


def _salt(data: bytes) -> int:
    """Nonzero bytes in GAPPY's two zero runs."""
    return sum(1 for b in data[16:48] + data[64:96] if b)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(ez, "_zlib_progress", lambda *a, **k: None)
    # Gap salt with no zero bytes, so _salt() counts every salted byte.
    monkeypatch.setattr(ez.os, "urandom", lambda n: b"\x01" * n)


def _fake_zlib(**over):
    ns = types.SimpleNamespace(**{k: getattr(zlib, k) for k in dir(zlib) if not k.startswith("__")})
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def test_apply_gap_pad_more_than_the_gaps_hold():
    out = ez.apply_gap_pad(GAPPY, 500, b"\x01" * 500)
    assert _salt(out) == 64


def test_bit_reader_align_on_boundary():
    r = ez._BitReader(b"\xff\xff")
    r.byte_align()
    assert r.pos == 0
    r.bits(3)
    r.byte_align()
    assert r.pos == 8


def test_skip_dynamic_rejects_bad_code_lengths(monkeypatch):
    for sym, msg in ((16, "bad repeat"), (19, "bad code-length symbol")):
        monkeypatch.setattr(ez, "_huff_decode", lambda reader, count, symbol, s=sym: s)
        with pytest.raises(ValueError, match=msg):
            ez._skip_dynamic(ez._BitReader(bytes(16)))


def test_pad_closed_stream_rejects():
    reserved = b"\x78\x9c" + b"\x07" + b"\x00" * 4  # BTYPE 3
    assert ez.pad_closed_zlib_stream(reserved, len(reserved) + 20) is None
    one = zlib.compress(b"ab" * 8, 6)
    assert ez.pad_closed_zlib_stream(one, len(one) + 1) is None  # no empty block fits
    s = zlib.compress(b"abc")
    bad_adler = s[:-1] + bytes([s[-1] ^ 1])
    assert ez.pad_closed_zlib_stream(bad_adler, len(s) + 20) is None


def test_pad_closed_stream_many_lengths():
    """Byte-aligned EOBs and stored blocks that need no alignment pad."""
    aligned = zlib.compress(b"ab" * 12, 6)
    assert ez._walk_deflate(ez._split_zlib(aligned)[1])[1] % 8 == 0
    for k in range(1, 40):
        data = b"ab" * k
        s = zlib.compress(data, 6)
        for extra in range(2, 24):
            out = ez.pad_closed_zlib_stream(s, len(s) + extra, expected=data)
            assert out is None or (len(out) == len(s) + extra and zlib.decompress(out) == data)


def test_interfile_gaps_adjacent_darc_files():
    import fake_img as fi

    # No gap between the two files: the DARC pass finds nothing and the raw
    # zero-run scan (header padding) answers instead.
    arc = fi.darc({"a/A.bin": b"x" * 4, "a/B.bin": b"y" * 4}, align=4)
    runs = ez.interfile_zero_gaps(arc)
    assert runs and all(arc[po : po + sz] == bytes(sz) for sz, po in runs)


# ---------------------------------------------------------------------------
# compress_exact_empty_blocks
# ---------------------------------------------------------------------------


class _Co:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def compress(self, data):
        return self.body

    def flush(self, mode):
        return b""


def test_empty_blocks_skips_bodies_that_do_not_decode(monkeypatch):
    # 00 02 00 and 01 00 01 share an Adler-32, so a body for the second one
    # decodes cleanly to the wrong data. 0xff.. is not deflate at all.
    data, twin = b"\x00\x02\x00", b"\x01\x00\x01"
    assert zlib.adler32(data) == zlib.adler32(twin)
    co = zlib.compressobj(9, wbits=-15)
    wrong = co.compress(twin) + co.flush(zlib.Z_SYNC_FLUSH)
    bodies = iter([wrong, b"\xff\xff\xff\xff\xff"] * 50)
    monkeypatch.setattr(ez, "zlib", _fake_zlib(compressobj=lambda *a, **k: _Co(next(bodies))))
    assert ez.compress_exact_empty_blocks(data, 6 + len(wrong) + 5) is None


def test_empty_blocks_thorough_sweep(monkeypatch):
    calls = []

    def compressobj(*args, **kw):
        calls.append(args)
        if len(args) < 5:
            return _Co(b"\xff" * 5)  # fast pass: never decodes
        if args[3] == 1:  # memLevel 1 "fails"
            raise zlib.error("bad memLevel")
        return zlib.compressobj(*args, **kw)

    monkeypatch.setattr(ez, "zlib", _fake_zlib(compressobj=compressobj))
    data = b"hello hello hello"
    co = zlib.compressobj(9, zlib.DEFLATED, -15, 2, zlib.Z_DEFAULT_STRATEGY)
    body = co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH)
    target = 2 + len(body) + 5 + 4
    out = ez.compress_exact_empty_blocks(data, target, thorough=True)
    assert out is not None and zlib.decompress(out) == data
    assert any(len(a) == 5 for a in calls)


# ---------------------------------------------------------------------------
# compress_exact_with_gap_tune / try_fast_exact_slot / compress_to_exact_slot
# ---------------------------------------------------------------------------


def test_gap_tune_thorough_hit_near_preferred(monkeypatch):
    monkeypatch.setattr(
        ez, "compress_exact_empty_blocks", lambda data, n, thorough=False: b"SLOT" if thorough else None
    )
    tuned, slot = ez.compress_exact_with_gap_tune(GAPPY, 99, preferred_pad=4)
    assert slot == b"SLOT" and tuned == GAPPY  # pad 0 is tried first


def test_try_fast_exact_slot_fallbacks(monkeypatch):
    calls = []

    def gap_tune(data, n, preferred_pad=None):
        calls.append(preferred_pad)
        if len(calls) == 1:
            raise RuntimeError("miss")
        return data, b"Z"

    monkeypatch.setattr(ez, "compress_exact_empty_blocks", lambda *a, **k: None)
    monkeypatch.setattr(ez, "compress_exact_with_gap_tune", gap_tune)
    monkeypatch.setattr(ez, "zlib_body_fits_slot", lambda data, n: True)
    # Salted gaps: zeroing them gives a second, zero-pad try.
    salted = ez.apply_gap_pad(GAPPY, 64, b"\x07" * 64)
    monkeypatch.setattr(ez, "interfile_zero_gaps", lambda data, min_len=4: [(32, 16), (32, 64)])
    assert ez.try_fast_exact_slot(salted, 50) == (GAPPY, b"Z")
    assert calls == [None, 0]

    calls.clear()
    monkeypatch.setattr(ez, "compress_exact_with_gap_tune", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    assert ez.try_fast_exact_slot(salted, 50) is None


def test_compress_to_exact_slot_escalates_to_zopfli(monkeypatch):
    data = b"payload"
    slot = zlib.compress(data, 9)
    monkeypatch.setattr(ez, "try_fast_exact_slot", lambda d, n: None)
    monkeypatch.setattr(ez, "compress_exact_zopfli", lambda d, n, fine_tune=False: (d, slot))
    assert ez.compress_to_exact_slot(data, len(slot)) == slot


# ---------------------------------------------------------------------------
# _bounded_near_miss_tune
# ---------------------------------------------------------------------------


class _Zopfli:
    """zopfli.zlib stand-in: length = base + salt bytes // step."""

    def __init__(self, base: int, step: int = 1) -> None:
        self.base, self.step = base, step

    def compress(self, data: bytes) -> bytes:
        return b"z" * (self.base + _salt(data) // self.step)


def test_near_miss_misses_and_skips_salted_bytes(monkeypatch):
    monkeypatch.setattr(ez, "zopfli_zlib", _Zopfli(100, step=1000))  # flips never change length
    rng = bytes(range(1, 65))
    assert ez._bounded_near_miss_tune(GAPPY, 103, 8, rng, 64, max_tries=20, workers=2) is None


# ---------------------------------------------------------------------------
# compress_exact_zopfli
# ---------------------------------------------------------------------------


def _zopfli_seq(monkeypatch, fn):
    monkeypatch.setattr(ez, "zopfli_zlib", object())  # "installed"
    monkeypatch.setattr(ez, "_zopfli_compress", lambda data, label: fn(data))


def test_zopfli_binary_search_pads_an_undershoot(monkeypatch):
    # Pass 1 is 10 under; every pad try is under too. The second pad try pads.
    _zopfli_seq(monkeypatch, lambda d: b"z" * (90 + _salt(d) // 16))
    tries = []

    def pad(stream, target, expected=None):
        tries.append(len(stream))
        return b"P" * target if len(tries) == 3 else None

    monkeypatch.setattr(ez, "pad_closed_zlib_stream", pad)
    tuned, slot = ez.compress_exact_zopfli(GAPPY, 100)
    assert slot == b"P" * 100 and len(tries) == 3


def test_zopfli_salted_tries_over_then_gap_tune(monkeypatch):
    # Pass 1 is under (pads fail), every salted try is over: the search walks
    # down to pad 0, and gap-tune gets that as its preferred pad.
    _zopfli_seq(monkeypatch, lambda d: b"z" * (30 if _salt(d) == 0 else 200))
    monkeypatch.setattr(ez, "pad_closed_zlib_stream", lambda *a, **k: None)
    seen = {}

    def gap_tune(data, n, preferred_pad=None):
        seen["pad"] = preferred_pad
        return data, b"G"

    monkeypatch.setattr(ez, "compress_exact_with_gap_tune", gap_tune)
    assert ez.compress_exact_zopfli(GAPPY, 100) == (GAPPY, b"G")
    assert seen["pad"] == 0


def test_zopfli_best_under_pads_after_search(monkeypatch):
    _zopfli_seq(monkeypatch, lambda d: b"z" * (50 + _salt(d) // 8))
    calls = []

    def pad(stream, target, expected=None):
        calls.append(len(stream))
        return None if len(calls) < 8 else b"B" * target

    monkeypatch.setattr(ez, "pad_closed_zlib_stream", pad)
    tuned, slot = ez.compress_exact_zopfli(GAPPY, 100)
    assert slot == b"B" * 100


def test_zopfli_fine_tune_walks_gap_bytes(monkeypatch):
    # Only the fine-tune pass can reach 100: each fresh salt byte adds one,
    # and a byte that overshoots is put back to zero.
    state = {"phase": "search"}

    def zop(d):
        s = _salt(d)
        if state["phase"] == "search":
            return b"z" * 60
        return b"z" * (100 if s == 40 else (200 if s % 7 == 0 else 60 + s))

    _zopfli_seq(monkeypatch, zop)
    monkeypatch.setattr(ez, "pad_closed_zlib_stream", lambda *a, **k: None)

    def near_miss(*a, **k):
        state["phase"] = "fine"
        return None

    monkeypatch.setattr(ez, "_bounded_near_miss_tune", near_miss)
    tuned, slot = ez.compress_exact_zopfli(GAPPY, 100, fine_tune=True)
    assert len(slot) == 100


def test_zopfli_fine_tune_skipped_for_big_arcs_then_retries(monkeypatch):
    big = GAPPY + bytes(200_001)
    # Under at every pad, best at full salt: preferred pad == cap, so the
    # retry loop skips preferred + 1.
    _zopfli_seq(monkeypatch, lambda d: b"z" * (50 + _salt(d) // 8))
    monkeypatch.setattr(ez, "pad_closed_zlib_stream", lambda *a, **k: None)
    monkeypatch.setattr(ez, "interfile_zero_gaps", lambda data, min_len=4: [(32, 16), (32, 64)])
    gap_calls = []

    def gap_tune(data, n, preferred_pad=None):
        gap_calls.append(preferred_pad)
        raise RuntimeError("miss")

    monkeypatch.setattr(ez, "compress_exact_with_gap_tune", gap_tune)
    hits = iter([None, None, None, ("T", "S")])  # auto, then pads 64, 0, 63
    monkeypatch.setattr(ez, "_bounded_near_miss_tune", lambda *a, **k: next(hits))
    assert ez.compress_exact_zopfli(big, 100, fine_tune=True) == ("T", "S")
    assert len(gap_calls) == 2


def test_stored_empty_block_already_aligned():
    writer = ez._BitWriter(bytearray(), 5)  # header ends on a byte boundary
    ez._write_empty_blocks(writer, ["stored"])
    assert writer.pos == 8 + 32


def test_zopfli_gives_up(monkeypatch):
    # Best undershoot at full salt (pad == cap): the last retry skips cap + 1.
    _zopfli_seq(monkeypatch, lambda d: b"z" * (50 + _salt(d) // 8))
    monkeypatch.setattr(ez, "pad_closed_zlib_stream", lambda *a, **k: None)
    monkeypatch.setattr(ez, "compress_exact_with_gap_tune", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(ez, "_bounded_near_miss_tune", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="could not build exact zlib stream"):
        ez.compress_exact_zopfli(GAPPY, 100)
