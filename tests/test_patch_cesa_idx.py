"""img.bin idx-table dec_len must match PACK header when CESA companion grows."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from patch_cesa import (  # noqa: E402
    CESA_PKG_INDEX,
    img_idx_entry_off,
    read_img_idx_dec_len,
    set_img_idx_dec_len,
)

VANILLA_PKG90_DEC_LEN = 1182976
COMPANION_PKG90_DEC_LEN = VANILLA_PKG90_DEC_LEN + 256 * 512 * 3


def _fake_img_with_pkg90_idx(dec_len: int = VANILLA_PKG90_DEC_LEN) -> bytearray:
    buf = bytearray(img_idx_entry_off(CESA_PKG_INDEX) + 0x14)
    struct.pack_into(
        "=4s4x2I2xBB",
        buf,
        img_idx_entry_off(CESA_PKG_INDEX),
        b"PAK ",
        dec_len,
        2480,
        128,
        0x30,
    )
    return buf


def test_set_img_idx_dec_len_preserves_other_fields():
    buf = _fake_img_with_pkg90_idx()
    assert read_img_idx_dec_len(buf, CESA_PKG_INDEX) == VANILLA_PKG90_DEC_LEN
    old = set_img_idx_dec_len(buf, CESA_PKG_INDEX, COMPANION_PKG90_DEC_LEN)
    assert old == VANILLA_PKG90_DEC_LEN
    assert read_img_idx_dec_len(buf, CESA_PKG_INDEX) == COMPANION_PKG90_DEC_LEN
    typ, n1, n2, n3, n4 = struct.unpack_from(
        "=4s4x2I2xBB", buf, img_idx_entry_off(CESA_PKG_INDEX)
    )
    assert (typ, n1, n2, n3, n4) == (b"PAK ", COMPANION_PKG90_DEC_LEN, 2480, 128, 0x30)


def test_set_img_idx_dec_len_rejects_non_pak():
    buf = _fake_img_with_pkg90_idx()
    off = img_idx_entry_off(CESA_PKG_INDEX)
    buf[off : off + 4] = b"ARC "
    with pytest.raises(RuntimeError, match="not PAK"):
        set_img_idx_dec_len(buf, CESA_PKG_INDEX, COMPANION_PKG90_DEC_LEN)


def test_companion_pkg90_dec_len_is_vanilla_plus_one_tex():
    assert COMPANION_PKG90_DEC_LEN == 1576192
