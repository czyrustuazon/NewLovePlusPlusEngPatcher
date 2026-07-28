"""Content-addressed cache for PNG→BCLIM encode and exact-zlib package slots.

Speeds up repeated ``pack_images`` / gold rebuilds when assets are unchanged.
Layout (under ``cache/img_pack/`` by default)::

    bclim/<aa>/<bb>/<sha256>   # exact-size BCLIM bytes
    zlib/<aa>/<bb>/<sha256>    # exact-length zlib slot (length = file size)

Keys hash inputs only — gap-salted zlib payloads are reusable as long as they
decompress cleanly to the same decompressed length with unused_data == 0.
"""

from __future__ import annotations

import hashlib
import os
import threading
import zlib
from dataclasses import dataclass, field
from pathlib import Path


CACHE_VERSION = b"v1"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@dataclass
class ImgPackCacheStats:
    bclim_hit: int = 0
    bclim_miss: int = 0
    zlib_hit: int = 0
    zlib_miss: int = 0

    def summary(self) -> str:
        return (
            f"bclim hit/miss={self.bclim_hit}/{self.bclim_miss} "
            f"zlib hit/miss={self.zlib_hit}/{self.zlib_miss}"
        )


@dataclass
class ImgPackCache:
    root: Path
    stats: ImgPackCacheStats = field(default_factory=ImgPackCacheStats)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, kind: str, digest: str) -> Path:
        return self.root / kind / digest[:2] / digest[2:4] / digest

    @staticmethod
    def bclim_key(png_bytes: bytes, orig_bclim: bytes) -> str:
        h = hashlib.sha256()
        h.update(b"bclim-")
        h.update(CACHE_VERSION)
        h.update(b"\0")
        h.update(hashlib.sha256(png_bytes).digest())
        h.update(hashlib.sha256(orig_bclim).digest())
        return h.hexdigest()

    @staticmethod
    def zlib_key(data: bytes, exact_len: int, *, fine_tune: bool) -> str:
        h = hashlib.sha256()
        h.update(b"zlib-")
        h.update(CACHE_VERSION)
        h.update(b"\0")
        h.update(b"1" if fine_tune else b"0")
        h.update(exact_len.to_bytes(4, "little"))
        h.update(hashlib.sha256(data).digest())
        return h.hexdigest()

    def get_bclim(self, png_bytes: bytes, orig_bclim: bytes) -> bytes | None:
        key = self.bclim_key(png_bytes, orig_bclim)
        path = self._blob_path("bclim", key)
        if not path.is_file():
            with self._lock:
                self.stats.bclim_miss += 1
            return None
        data = path.read_bytes()
        if len(data) != len(orig_bclim):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            with self._lock:
                self.stats.bclim_miss += 1
            return None
        with self._lock:
            self.stats.bclim_hit += 1
        return data

    def put_bclim(self, png_bytes: bytes, orig_bclim: bytes, encoded: bytes) -> None:
        if len(encoded) != len(orig_bclim):
            return
        key = self.bclim_key(png_bytes, orig_bclim)
        _atomic_write(self._blob_path("bclim", key), encoded)

    def get_zlib(
        self, data: bytes, exact_len: int, *, fine_tune: bool
    ) -> bytes | None:
        key = self.zlib_key(data, exact_len, fine_tune=fine_tune)
        path = self._blob_path("zlib", key)
        if not path.is_file():
            with self._lock:
                self.stats.zlib_miss += 1
            return None
        slot = path.read_bytes()
        if len(slot) != exact_len or not _zlib_slot_ok(slot, len(data)):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            with self._lock:
                self.stats.zlib_miss += 1
            return None
        with self._lock:
            self.stats.zlib_hit += 1
        return slot

    def put_zlib(
        self, data: bytes, exact_len: int, slot: bytes, *, fine_tune: bool
    ) -> None:
        if len(slot) != exact_len or not _zlib_slot_ok(slot, len(data)):
            return
        key = self.zlib_key(data, exact_len, fine_tune=fine_tune)
        _atomic_write(self._blob_path("zlib", key), slot)


def _zlib_slot_ok(slot: bytes, expected_dec_len: int) -> bool:
    """Accept any gap-salted payload of the right decompressed length."""
    try:
        d = zlib.decompressobj()
        got = d.decompress(slot)
        if d.unused_data or not d.eof:
            return False
        return len(got) == expected_dec_len
    except zlib.error:
        return False


def compress_to_exact_slot_cached(
    data: bytes,
    exact_len: int,
    *,
    fine_tune: bool = False,
    cache: ImgPackCache | None = None,
) -> bytes:
    """Like ``exact_zlib.compress_to_exact_slot`` with optional disk cache."""
    if cache is not None:
        hit = cache.get_zlib(data, exact_len, fine_tune=fine_tune)
        if hit is not None:
            print(
                f"  [exact-zlib] cache hit slot={exact_len}",
                flush=True,
            )
            return hit

    from exact_zlib import compress_to_exact_slot

    slot = compress_to_exact_slot(data, exact_len, fine_tune=fine_tune)
    if cache is not None:
        cache.put_zlib(data, exact_len, slot, fine_tune=fine_tune)
    return slot
