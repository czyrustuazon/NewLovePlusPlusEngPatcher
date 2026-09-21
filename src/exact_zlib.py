"""Exact-length zlib helpers for NLPP img.bin package elements.

Game slots require ``unused_data == 0`` and exact compressed length — trailing
NUL padding after a short zlib stream soft-locks UI.

Cold-build order (fast → slow):
  1. SYNC_FLUSH + empty stored blocks (stdlib zlib) when the body fits
  2. Gap-salt + empty-block (still zlib-speed)
  3. Zero DARC pads then retry empty-block (large-ARC playbook)
  4. Zopfli only when zlib cannot fit under the slot
  5. If zopfli is *short*, pad the closed stream at EOB with empty deflate
     blocks (do not wait on 256 near-miss trials for a 50-byte undershoot)
"""
from __future__ import annotations

import os
import struct
import sys
import threading
import time
import zlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import zopfli.zlib as zopfli_zlib
except ImportError:  # pragma: no cover
    zopfli_zlib = None  # type: ignore


def _min_empty_block_stream_len(data: bytes, *, level: int = 9) -> int:
    """Lower bound on an empty-block zlib stream (hdr + SYNC_FLUSH body + final + adler)."""
    co = zlib.compressobj(level, wbits=-15)
    body = co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH)
    return 2 + len(body) + 5 + 4


def zlib_body_fits_slot(data: bytes, exact_len: int) -> bool:
    """True when level-9 SYNC_FLUSH empty-block could possibly reach exact_len."""
    return _min_empty_block_stream_len(data) <= exact_len


def interfile_zero_gaps(data: bytes, min_len: int = 4) -> list[tuple[int, int]]:
    """Return (size, offset) zero pads between DARC files (fallback: raw zero runs)."""
    try:
        from darcutil import DarcArchive

        darc = DarcArchive(data)
        spans = sorted((e.offset, e.offset + e.length) for e in darc.files)
        gaps: list[tuple[int, int]] = []
        for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
            if b0 > a1:
                gaps.append((a1, b0))
        if spans and spans[-1][1] < len(data):
            gaps.append((spans[-1][1], len(data)))
        out: list[tuple[int, int]] = []
        for g0, g1 in gaps:
            chunk = data[g0:g1]
            if len(chunk) >= min_len and chunk == b"\x00" * len(chunk):
                out.append((g1 - g0, g0))
        out.sort(reverse=True)
        if out:
            return out
    except Exception:
        pass

    runs: list[tuple[int, int]] = []
    i = 0
    n = len(data)
    while i < n:
        if data[i] != 0:
            i += 1
            continue
        j = i
        while j < n and data[j] == 0:
            j += 1
        if j - i >= min_len:
            runs.append((j - i, i))
        i = j
    runs.sort(reverse=True)
    return runs


def apply_gap_pad(data: bytes, n_bytes: int, pad_rng: bytes) -> bytes:
    if n_bytes <= 0 or not pad_rng:
        return data
    runs = interfile_zero_gaps(data)
    t = bytearray(data)
    left = n_bytes
    off = 0
    for sz, po in runs:
        take = min(left, sz)
        if take:
            t[po : po + take] = pad_rng[off : off + take]
        left -= take
        off += sz
        if left <= 0:
            break
    return bytes(t)


def compress_exact_empty_blocks(
    data: bytes,
    exact_len: int,
    *,
    thorough: bool = False,
) -> bytes | None:
    """Build a zlib stream of exactly exact_len via sync-flush + empty stored blocks.

    Fast path (default): zlib levels 0–9 only.
    ``thorough=True`` also sweeps memLevel/strategy (much slower on large ARCs).
    """
    adler = struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF)
    strategies = (
        zlib.Z_DEFAULT_STRATEGY,
        zlib.Z_FILTERED,
        zlib.Z_HUFFMAN_ONLY,
        zlib.Z_RLE,
        zlib.Z_FIXED,
    )
    hdrs = (b"\x78\x9c", b"\x78\xda", b"\x78\x5e", b"\x78\x01")

    def try_body(body: bytes) -> bytes | None:
        for hdr in hdrs:
            remain = exact_len - len(hdr) - 4 - len(body)
            if remain < 5 or remain % 5 != 0:
                continue
            n_empty = remain // 5
            out = (
                hdr
                + body
                + b"\x00\x00\x00\xff\xff" * (n_empty - 1)
                + b"\x01\x00\x00\xff\xff"
                + adler
            )
            if len(out) != exact_len:
                continue
            d = zlib.decompressobj()
            try:
                got = d.decompress(out)
            except zlib.error:
                continue
            if got == data and not d.unused_data and d.eof:
                return out
        return None

    for level in range(10):
        co = zlib.compressobj(level, wbits=-15)
        hit = try_body(co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH))
        if hit is not None:
            return hit
    if not thorough:
        return None
    for level in range(10):
        for mem in range(1, 10):
            for strat in strategies:
                try:
                    co = zlib.compressobj(level, zlib.DEFLATED, -15, mem, strat)
                    hit = try_body(co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH))
                except zlib.error:
                    continue
                if hit is not None:
                    return hit
    return None


def _empty_block_candidates(cap: int, preferred_pad: int | None) -> list[int]:
    """Prefer zopfli binary-search pad, then coarse scan — avoid O(cap) full sweeps."""
    ordered: list[int] = []
    seen: set[int] = set()

    def add(p: int) -> None:
        if 0 <= p <= cap and p not in seen:
            seen.add(p)
            ordered.append(p)

    if preferred_pad is not None:
        base = max(0, min(cap, preferred_pad))
        for d in range(0, 96):
            add(base - d)
            add(base + d)
    add(0)
    step = max(1, cap // 80) if cap else 1
    for p in range(cap, -1, -step):
        add(p)
    # Tiny gap budgets can afford a full sweep; large ones cannot.
    if cap and cap <= 512:
        for p in range(cap, -1, -1):
            add(p)
    return ordered


def compress_exact_with_gap_tune(
    data: bytes,
    exact_len: int,
    *,
    preferred_pad: int | None = None,
) -> tuple[bytes, bytes]:
    runs = interfile_zero_gaps(data)
    cap = sum(sz for sz, _ in runs)
    pad_rng = os.urandom(cap) if cap else b""

    _zlib_progress("empty-block try (no gap pad, fast)…")
    slot = compress_exact_empty_blocks(data, exact_len, thorough=False)
    if slot is not None:
        _zlib_progress(f"empty-block hit (no pad) slot={exact_len}", newline=True)
        return data, slot

    candidates = _empty_block_candidates(cap, preferred_pad)
    total = len(candidates)
    t0 = time.monotonic()
    _zlib_progress(
        f"empty-block scan {total} pads "
        f"(preferred={preferred_pad} cap={cap}; fast path)…",
        newline=True,
    )

    for i, n in enumerate(candidates, 1):
        elapsed = time.monotonic() - t0
        frac = i / max(1, total)
        width = 24
        filled = int(width * frac)
        bar = "#" * filled + "-" * (width - filled)
        _zlib_progress(
            f"empty-block [{bar}] {i}/{total} pad={n}/{cap} "
            f"{_format_secs(elapsed)} slot={exact_len}"
        )
        cand = apply_gap_pad(data, n, pad_rng) if cap else data
        slot = compress_exact_empty_blocks(cand, exact_len, thorough=False)
        if slot is not None:
            _zlib_progress(
                f"empty-block hit pad={n} slot={exact_len}", newline=True
            )
            return cand, slot

    # Few thorough retries around the preferred pad only (slow nested zlib).
    thorough_pads: list[int] = []
    if preferred_pad is not None:
        base = max(0, min(cap, preferred_pad))
        thorough_pads = [base + d for d in range(-16, 17) if 0 <= base + d <= cap]
    thorough_pads = list(dict.fromkeys([0, *thorough_pads]))
    _zlib_progress(
        f"empty-block thorough retry ({len(thorough_pads)} pads)…", newline=True
    )
    for i, n in enumerate(thorough_pads, 1):
        _zlib_progress(
            f"empty-block thorough {i}/{len(thorough_pads)} pad={n} slot={exact_len}"
        )
        cand = apply_gap_pad(data, n, pad_rng) if (cap and n) else data
        slot = compress_exact_empty_blocks(cand, exact_len, thorough=True)
        if slot is not None:
            _zlib_progress(
                f"empty-block hit (thorough) pad={n} slot={exact_len}",
                newline=True,
            )
            return cand, slot

    print(flush=True)
    raise RuntimeError(
        f"could not build exact zlib stream (len={len(data)} slot={exact_len})"
    )


def _zlib_progress(msg: str, *, newline: bool = False) -> None:
    # cp1252 consoles raise UnicodeEncodeError on "→" / "…" and pack_images
    # treated that as a failed compress (left the ARC Japanese).
    text = f"\r  [exact-zlib] {msg}".ljust(96)
    end = "" if not newline else "\n"
    try:
        print(text, end=end, flush=True)
    except UnicodeEncodeError:
        safe = text.encode(sys.stdout.encoding or "ascii", errors="replace").decode(
            sys.stdout.encoding or "ascii", errors="replace"
        )
        print(safe, end=end, flush=True)


def _format_secs(sec: float) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec}s"
    return f"{sec // 60}m{sec % 60:02d}s"


# Seconds per MB from the last finished zopfli call (calibrates to this machine).
_ZOPFLI_SEC_PER_MB: float | None = None


def _zopfli_compress(data: bytes, *, label: str) -> bytes:
    """Run zopfli.compress with a live elapsed/heartbeat bar (API has no %)."""
    global _ZOPFLI_SEC_PER_MB
    if zopfli_zlib is None:
        raise RuntimeError("zopfli not installed")

    mb = max(0.05, len(data) / (1024 * 1024))
    # First call: no machine calibration yet — show elapsed only.
    # Later calls: ETA = size_MB × measured sec/MB from prior compress on this run.
    eta = (mb * _ZOPFLI_SEC_PER_MB) if _ZOPFLI_SEC_PER_MB else None
    spin = "|/-\\"
    result: list[bytes] = []
    err: list[BaseException] = []

    def _run() -> None:
        try:
            result.append(zopfli_zlib.compress(data))
        except BaseException as exc:  # noqa: BLE001 — surface to caller
            err.append(exc)

    t0 = time.monotonic()
    th = threading.Thread(target=_run, name="zopfli-compress", daemon=True)
    th.start()
    i = 0
    while th.is_alive():
        elapsed = time.monotonic() - t0
        width = 24
        if eta and eta > 0:
            frac = min(0.95, elapsed / eta)
            filled = int(width * frac)
            bar = "#" * filled + "-" * (width - filled)
            eta_txt = f" ~{_format_secs(eta)} left-ish"
        else:
            # Pulse a 3-cell block so it still looks alive with no ETA.
            pos = i % (width - 2)
            bar = "-" * pos + "###" + "-" * max(0, width - pos - 3)
            bar = bar[:width]
            eta_txt = " (calibrating speed…)"
        _zlib_progress(
            f"{label} {spin[i % 4]} [{bar}] {_format_secs(elapsed)} "
            f"{mb:.1f}MB{eta_txt}"
        )
        i += 1
        th.join(timeout=0.25)
    th.join()
    if err:
        print(flush=True)
        raise err[0]
    out = result[0]
    elapsed = time.monotonic() - t0
    # EMA so one weird pass doesn't lock the ETA forever.
    sample = elapsed / mb
    if _ZOPFLI_SEC_PER_MB is None:
        _ZOPFLI_SEC_PER_MB = sample
    else:
        _ZOPFLI_SEC_PER_MB = 0.6 * _ZOPFLI_SEC_PER_MB + 0.4 * sample
    _zlib_progress(
        f"{label} done [{ '#' * 24 }] {_format_secs(elapsed)} -> {len(out)} bytes "
        f"({_ZOPFLI_SEC_PER_MB:.1f}s/MB)",
        newline=True,
    )
    return out


def _force_zero_gaps(data: bytes) -> bytes:
    """Ensure DARC inter-file pads are raw zeros (undo prior urandom gap salt)."""
    t = bytearray(data)
    for sz, po in interfile_zero_gaps(data, min_len=1):
        t[po : po + sz] = b"\x00" * sz
    return bytes(t)


def _bounded_near_miss_tune(
    data: bytes,
    target: int,
    preferred_pad: int,
    rng: bytes,
    cap: int,
    *,
    max_tries: int = 256,
    workers: int | None = None,
) -> tuple[bytes, bytes] | None:
    """Close a small undershoot (e.g. 42515→42517) via parallel single-byte flips."""
    if zopfli_zlib is None or cap <= 0:
        return None
    if workers is None:
        # Keep modest — package ProcessPool already multiplies concurrency.
        workers = max(1, min(4, (os.cpu_count() or 4) // 2))
    base = apply_gap_pad(data, preferred_pad, rng)
    z0 = zopfli_zlib.compress(base)
    if len(z0) == target:
        return base, z0
    if len(z0) > target:
        return None
    deficit = target - len(z0)

    # Independent candidates: each flips one gap byte on a copy of ``base``.
    candidates: list[bytes] = []
    for sz, po in interfile_zero_gaps(base):
        for i in range(sz):
            if base[po + i] != 0:
                continue
            t = bytearray(base)
            t[po + i] = rng[(po + i) % len(rng)] if rng else (1 + (len(candidates) % 254))
            candidates.append(bytes(t))
            if len(candidates) >= max_tries:
                break
        if len(candidates) >= max_tries:
            break
    if not candidates:
        return None

    workers = max(1, min(workers, len(candidates)))
    _zlib_progress(
        f"near-miss +{deficit}B: {len(candidates)} trials, {workers} workers…",
        newline=True,
    )
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(zopfli_zlib.compress, cand): cand for cand in candidates
        }
        for fut in as_completed(futures):
            cand = futures[fut]
            z = fut.result()
            done += 1
            if done == 1 or done % 4 == 0 or len(z) == target:
                _zlib_progress(
                    f"near-miss [{done}/{len(candidates)}] zopfli={len(z)} "
                    f"slot={target}"
                )
            if len(z) == target:
                # Cancel the rest — best-effort.
                for other in futures:
                    other.cancel()
                _zlib_progress(
                    f"near-miss hit at trial {done}/{len(candidates)}",
                    newline=True,
                )
                return cand, z
    _zlib_progress(
        f"near-miss miss ({len(candidates)} trials, still short)",
        newline=True,
    )
    return None


# --- Closed-stream empty-block pad (zopfli undershoot) ---------------------
#
# Finished zlib/zopfli blobs have BFINAL already set, so you cannot append
# ``00 00 00 ff ff`` onto the byte string. Walk to EOB, clear BFINAL, then
# emit empty fixed-Huffman / stored blocks from that *bit* offset. Leftover
# zero padding after EOB would otherwise be read as a stored-block header.

_LEN_EXTRA = (
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3,
    4, 4, 4, 4, 5, 5, 5, 5, 0,
)
_DIST_EXTRA = (
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7,
    8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13,
)
_CLEN_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)


class _BitReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def bit(self) -> int:
        i, b = divmod(self.pos, 8)
        if i >= len(self.data):
            raise ValueError("truncated deflate")
        v = (self.data[i] >> b) & 1
        self.pos += 1
        return v

    def bits(self, n: int) -> int:
        v = 0
        for i in range(n):
            v |= self.bit() << i
        return v

    def byte_align(self) -> None:
        rem = self.pos % 8
        if rem:
            self.pos += 8 - rem


class _BitWriter:
    def __init__(self, data: bytearray, pos: int) -> None:
        self.data = data
        self.pos = pos

    def _ensure(self, nbits: int) -> None:
        need = (self.pos + nbits + 7) // 8
        if len(self.data) < need:
            self.data.extend(b"\x00" * (need - len(self.data)))

    def write(self, value: int, nbits: int) -> None:
        self._ensure(nbits)
        for i in range(nbits):
            bit = (value >> i) & 1
            byte_i, b = divmod(self.pos, 8)
            if bit:
                self.data[byte_i] |= 1 << b
            else:
                self.data[byte_i] &= ~(1 << b)
            self.pos += 1


def _huffman_from_lengths(lengths: list[int]) -> tuple[list[int], list[int]]:
    """Puff-style (count[len], symbols-sorted-by-length) tables."""
    maxb = max(lengths) if lengths else 0
    count = [0] * (maxb + 1)
    for length in lengths:
        if length < 0 or (maxb and length > maxb):
            raise ValueError("bad code length")
        count[length] += 1
    left = 1
    for nbits in range(1, maxb + 1):
        left <<= 1
        left -= count[nbits]
        if left < 0:
            raise ValueError("over-subscribed Huffman tree")
    offs = [0] * (maxb + 1)
    for nbits in range(1, maxb):
        offs[nbits + 1] = offs[nbits] + count[nbits]
    symbol = [0] * len(lengths)
    for sym, length in enumerate(lengths):
        if length:
            symbol[offs[length]] = sym
            offs[length] += 1
    return count, symbol


def _huff_decode(reader: _BitReader, count: list[int], symbol: list[int]) -> int:
    code = 0
    first = 0
    index = 0
    for length in range(1, len(count)):
        code |= reader.bit()
        n = count[length]
        if code - n < first:
            return symbol[index + (code - first)]
        index += n
        first += n
        first <<= 1
        code <<= 1
    raise ValueError("invalid Huffman code")


def _skip_huffman(
    reader: _BitReader,
    lit: tuple[list[int], list[int]],
    dist: tuple[list[int], list[int]],
) -> None:
    lit_count, lit_sym = lit
    dist_count, dist_sym = dist
    while True:
        sym = _huff_decode(reader, lit_count, lit_sym)
        if sym < 256:
            continue
        if sym == 256:
            return
        extra_i = sym - 257
        if extra_i >= len(_LEN_EXTRA):
            raise ValueError("bad length symbol")
        reader.bits(_LEN_EXTRA[extra_i])
        dsym = _huff_decode(reader, dist_count, dist_sym)
        if dsym >= len(_DIST_EXTRA):
            raise ValueError("bad distance symbol")
        reader.bits(_DIST_EXTRA[dsym])


_FIXED_LIT: tuple[list[int], list[int]] | None = None
_FIXED_DIST: tuple[list[int], list[int]] | None = None


def _fixed_tables() -> tuple[
    tuple[list[int], list[int]], tuple[list[int], list[int]]
]:
    global _FIXED_LIT, _FIXED_DIST
    if _FIXED_LIT is None or _FIXED_DIST is None:
        _FIXED_LIT = _huffman_from_lengths(
            [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
        )
        _FIXED_DIST = _huffman_from_lengths([5] * 32)
    return _FIXED_LIT, _FIXED_DIST


def _skip_dynamic(reader: _BitReader) -> None:
    hlit = reader.bits(5) + 257
    hdist = reader.bits(5) + 1
    hclen = reader.bits(4) + 4
    clen = [0] * 19
    for i in range(hclen):
        clen[_CLEN_ORDER[i]] = reader.bits(3)
    cl_tab = _huffman_from_lengths(clen)
    lengths: list[int] = []
    total = hlit + hdist
    while len(lengths) < total:
        sym = _huff_decode(reader, cl_tab[0], cl_tab[1])
        if sym < 16:
            lengths.append(sym)
        elif sym == 16:
            if not lengths:
                raise ValueError("bad repeat")
            lengths.extend([lengths[-1]] * (reader.bits(2) + 3))
        elif sym == 17:
            lengths.extend([0] * (reader.bits(3) + 3))
        elif sym == 18:
            lengths.extend([0] * (reader.bits(7) + 11))
        else:
            raise ValueError("bad code-length symbol")
    lengths = lengths[:total]
    lit = _huffman_from_lengths(lengths[:hlit])
    dist = _huffman_from_lengths(lengths[hlit:])
    _skip_huffman(reader, lit, dist)


def _walk_deflate(deflate: bytes) -> tuple[int, int]:
    """Return (last_block_start_bit, bit_offset_after_EOB)."""
    reader = _BitReader(deflate)
    last_start = 0
    bfinal = 0
    while not bfinal:
        last_start = reader.pos
        bfinal = reader.bit()
        btype = reader.bits(2)
        if btype == 0:
            reader.byte_align()
            ln = reader.bits(16)
            nlen = reader.bits(16)
            if (ln ^ 0xFFFF) & 0xFFFF != nlen:
                raise ValueError("bad stored block lengths")
            reader.pos += ln * 8
            if reader.pos > len(deflate) * 8:
                raise ValueError("truncated stored block")
        elif btype == 1:
            _skip_huffman(reader, *_fixed_tables())
        elif btype == 2:
            _skip_dynamic(reader)
        else:
            raise ValueError("reserved BTYPE")
    return last_start, reader.pos


def _split_zlib(stream: bytes) -> tuple[bytes, bytes, bytes] | None:
    if len(stream) < 6:
        return None
    cmf, flg = stream[0], stream[1]
    if (cmf & 0x0F) != 8:
        return None
    if (cmf * 256 + flg) % 31 != 0:
        return None
    if flg & 0x20:
        return None
    return stream[:2], stream[2:-4], stream[-4:]


def _stored_empty_bits(pos: int) -> int:
    pad = (8 - ((pos + 3) % 8)) % 8
    return 3 + pad + 32


def _plan_empty_block_bits(end_bit: int, c_max: int) -> list[str] | None:
    """Kinds of empty blocks whose bit length is in [c_max-7, c_max]."""
    if c_max < 10:
        return None
    want_lo = max(10, c_max - 7)
    want_hi = c_max
    parent: dict[int, tuple[int, str] | None] = {0: None}
    q: deque[int] = deque([0])
    found: int | None = None
    while q:
        used = q.popleft()
        if want_lo <= used <= want_hi:
            found = used
            break
        pos = end_bit + used
        for kind, size in (("fixed", 10), ("stored", _stored_empty_bits(pos))):
            nxt = used + size
            if nxt > want_hi or nxt in parent:
                continue
            parent[nxt] = (used, kind)
            q.append(nxt)
    if found is None:
        return None
    kinds: list[str] = []
    cur = found
    while cur:
        prev, kind = parent[cur]  # type: ignore[misc]
        kinds.append(kind)
        cur = prev
    kinds.reverse()
    return kinds or None


def _write_empty_blocks(writer: _BitWriter, kinds: list[str]) -> None:
    for i, kind in enumerate(kinds):
        final = i == len(kinds) - 1
        if kind == "fixed":
            writer.write(1 if final else 0, 1)
            writer.write(1, 2)  # BTYPE = 01
            writer.write(0, 7)  # EOB
        else:
            writer.write(1 if final else 0, 1)
            writer.write(0, 2)  # BTYPE = 00
            pad = (8 - (writer.pos % 8)) % 8
            if pad:
                writer.write(0, pad)
            writer.write(0, 16)
            writer.write(0xFFFF, 16)


def pad_closed_zlib_stream(
    stream: bytes,
    target: int,
    *,
    expected: bytes | None = None,
) -> bytes | None:
    """Grow a finished zlib stream to ``target`` with empty deflate blocks.

    Uncompressed payload is unchanged (Adler32 stays). Returns None when the
    undershoot is too small to encode (typically 1 byte) or the stream cannot
    be parsed.
    """
    if len(stream) == target:
        return stream
    if len(stream) > target or target - len(stream) > 1_000_000:
        return None
    split = _split_zlib(stream)
    if split is None:
        return None
    hdr, deflate, adler = split
    need = target - len(stream)
    try:
        last_start, end_bit = _walk_deflate(deflate)
    except ValueError:
        return None
    if last_start >= len(deflate) * 8 or end_bit > len(deflate) * 8:
        return None

    new_len = len(deflate) + need
    c_max = new_len * 8 - end_bit
    kinds = _plan_empty_block_bits(end_bit, c_max)
    if not kinds:
        return None

    buf = bytearray(deflate[: (end_bit + 7) // 8])
    bi, bt = divmod(last_start, 8)
    buf[bi] &= ~(1 << bt)
    used = end_bit % 8
    if used:
        buf[-1] &= (1 << used) - 1

    writer = _BitWriter(buf, end_bit)
    _write_empty_blocks(writer, kinds)
    pad = (8 - (writer.pos % 8)) % 8
    if pad:
        writer.write(0, pad)
    if len(buf) != new_len or writer.pos != new_len * 8:
        return None
    out = hdr + bytes(buf[:new_len]) + adler
    if len(out) != target:
        return None
    d = zlib.decompressobj()
    try:
        got = d.decompress(out)
    except zlib.error:
        return None
    if d.unused_data or not d.eof:
        return None
    if expected is not None and got != expected:
        return None
    try:
        orig = zlib.decompress(stream)
    except zlib.error:
        return None
    if got != orig:
        return None
    return out


def compress_exact_zopfli(
    data: bytes,
    target: int,
    *,
    fine_tune: bool = False,
) -> tuple[bytes, bytes]:
    if zopfli_zlib is None:
        _zlib_progress("gap-tune (no zopfli)…", newline=True)
        return compress_exact_with_gap_tune(data, target)

    z_blob = _zopfli_compress(
        data, label=f"zopfli pass 1 (dec={len(data)} slot={target})"
    )
    z0 = len(z_blob)
    if z0 > target:
        _zlib_progress(f"zopfli={z0} > slot={target}; gap-tune…", newline=True)
        return compress_exact_with_gap_tune(data, target)
    if z0 == target:
        _zlib_progress(f"exact hit zopfli={z0}", newline=True)
        return data, z_blob

    padded = pad_closed_zlib_stream(z_blob, target, expected=data)
    if padded is not None:
        _zlib_progress(
            f"zopfli empty-block pad {z0}->{target}", newline=True
        )
        return data, padded

    runs = interfile_zero_gaps(data, min_len=8)
    cap = sum(sz for sz, _ in runs)
    rng = os.urandom(cap) if cap else b""
    lo, hi = 0, cap
    steps = 0
    est = max(1, (cap.bit_length() + 2) if cap else 1)
    best_under_pad: int | None = None
    best_under_len = -1
    best_under_blob: bytes | None = None
    best_under_data: bytes | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = apply_gap_pad(data, mid, rng) if cap else data
        steps += 1
        z = _zopfli_compress(
            cand,
            label=f"binary-search {steps}/~{est} pad={mid}/{cap} slot={target}",
        )
        if len(z) == target:
            return cand, z
        if len(z) < target:
            padded = pad_closed_zlib_stream(z, target, expected=cand)
            if padded is not None:
                _zlib_progress(
                    f"zopfli empty-block pad {len(z)}->{target} (salt={mid})",
                    newline=True,
                )
                return cand, padded
            if len(z) > best_under_len:
                best_under_len = len(z)
                best_under_pad = mid
                best_under_blob = z
                best_under_data = cand
            lo = mid + 1
        else:
            hi = mid - 1

    preferred = best_under_pad if best_under_pad is not None else max(hi, 0)
    if best_under_blob is not None and best_under_data is not None:
        padded = pad_closed_zlib_stream(
            best_under_blob, target, expected=best_under_data
        )
        if padded is not None:
            _zlib_progress(
                f"zopfli empty-block pad {best_under_len}->{target}",
                newline=True,
            )
            return best_under_data, padded

    # Auto near-miss: a few bytes under the slot (e.g. 42515 vs 42517). Much
    # cheaper than full fine-tune; empty-block often cannot close a 1–4B gap.
    if (
        best_under_len >= 0
        and 0 < (target - best_under_len) <= 64
        and cap > 0
    ):
        hit = _bounded_near_miss_tune(
            data, target, preferred, rng, cap, max_tries=512
        )
        if hit is not None:
            return hit

    # Opt-in full per-byte fine-tune (hours on large gap runs).
    if fine_tune and len(data) <= 200_000:
        base_n = preferred
        t = bytearray(apply_gap_pad(data, base_n, rng) if cap else data)
        runs2 = interfile_zero_gaps(bytes(t))
        fine = 0
        fine_cap = sum(sz for sz, _ in runs2) or 1
        _zlib_progress(
            f"fine-tune enabled ({fine_cap} gap bytes; slow)…", newline=True
        )
        for sz, po in runs2:
            for i in range(sz):
                if t[po + i] != 0:
                    continue
                t[po + i] = rng[po % len(rng)] if rng else 1
                fine += 1
                z = _zopfli_compress(
                    bytes(t),
                    label=f"fine-tune {fine}/{fine_cap} slot={target}",
                )
                if len(z) == target:
                    return bytes(t), z
                if len(z) > target:
                    t[po + i] = 0
    elif fine_tune and len(data) > 200_000:
        _zlib_progress(
            f"fine-tune skipped (ARC {len(data)} bytes > 200KB)…", newline=True
        )

    _zlib_progress(
        f"falling back to empty-block pad (preferred_pad={preferred}"
        f"{f', best_zopfli={best_under_len}' if best_under_len >= 0 else ''})…",
        newline=True,
    )
    try:
        return compress_exact_with_gap_tune(
            data, target, preferred_pad=preferred
        )
    except RuntimeError:
        pass

    # Second chance: clear gap salt, then empty-block (large-ARC playbook).
    zeroed = _force_zero_gaps(data)
    _zlib_progress("empty-block retry on zeroed DARC gaps…", newline=True)
    try:
        return compress_exact_with_gap_tune(zeroed, target, preferred_pad=0)
    except RuntimeError:
        pass

    # New random salt + short near-miss from pad=0 / preferred.
    if cap > 0 and best_under_len >= 0 and (target - best_under_len) <= 64:
        rng2 = os.urandom(cap)
        for pad in (preferred, 0, max(0, preferred - 1), preferred + 1):
            if pad > cap:
                continue
            hit = _bounded_near_miss_tune(
                data, target, pad, rng2, cap, max_tries=256
            )
            if hit is not None:
                return hit

    raise RuntimeError(
        f"could not build exact zlib stream (len={len(data)} slot={target})"
    )


def _verify_exact_slot(tuned: bytes, slot: bytes, exact_len: int) -> bytes:
    d = zlib.decompressobj()
    got = d.decompress(slot)
    if got != tuned or d.unused_data or not d.eof:
        raise RuntimeError("exact zlib verify failed")
    if len(slot) != exact_len:
        raise RuntimeError(f"exact zlib length {len(slot)} != {exact_len}")
    return slot


def try_fast_exact_slot(
    data: bytes,
    exact_len: int,
) -> tuple[bytes, bytes] | None:
    """Try zlib empty-block / gap-tune only (no zopfli). Returns (tuned, slot) or None."""
    if zlib_body_fits_slot(data, exact_len):
        _zlib_progress("fast-path empty-block (no zopfli)…")
        slot = compress_exact_empty_blocks(data, exact_len, thorough=False)
        if slot is not None:
            _zlib_progress(f"fast-path hit slot={exact_len}", newline=True)
            return data, slot
        try:
            _zlib_progress("fast-path gap-tune empty-block…", newline=True)
            return compress_exact_with_gap_tune(data, exact_len)
        except RuntimeError:
            pass
    else:
        _zlib_progress(
            f"fast-path skip (zlib body too large for slot={exact_len})…",
            newline=True,
        )

    zeroed = _force_zero_gaps(data)
    if zeroed != data and zlib_body_fits_slot(zeroed, exact_len):
        try:
            _zlib_progress(
                "fast-path empty-block on zeroed DARC gaps…", newline=True
            )
            return compress_exact_with_gap_tune(zeroed, exact_len, preferred_pad=0)
        except RuntimeError:
            pass
    return None


def compress_to_exact_slot(
    data: bytes,
    exact_len: int,
    *,
    fine_tune: bool = False,
) -> bytes:
    """Return a zlib stream of length exact_len that decompresses to data (or tuned).

    Prefers stdlib zlib + empty-block padding; escalates to zopfli only when the
    zlib body cannot fit under the slot (typical cold-build speedup).
    """
    fast = try_fast_exact_slot(data, exact_len)
    if fast is not None:
        tuned, slot = fast
        out = _verify_exact_slot(tuned, slot, exact_len)
        _zlib_progress(f"done slot={exact_len} (fast-path)", newline=True)
        return out

    _zlib_progress(
        "escalating to zopfli (zlib cannot fit / congruence miss)…",
        newline=True,
    )
    tuned, slot = compress_exact_zopfli(data, exact_len, fine_tune=fine_tune)
    out = _verify_exact_slot(tuned, slot, exact_len)
    _zlib_progress(f"done slot={exact_len}", newline=True)
    return out
