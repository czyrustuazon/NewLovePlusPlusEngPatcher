"""CesaLogo logo_white 400×400 stub scale → native TEXI size."""

from __future__ import annotations

from conftest import SRC, load_module

pc = load_module("patch_code", SRC / "patch_code.py")


def _blob(insn: bytes) -> bytearray:
    data = bytearray(pc.ADDR_CESA_LOGO_WHITE_BNE + 4)
    data[pc.ADDR_CESA_LOGO_WHITE_BNE : pc.ADDR_CESA_LOGO_WHITE_BNE + 4] = insn
    return data


def test_logo_white_native_size_rewrites_bne():
    data = _blob(pc.ORIG_CESA_LOGO_WHITE_BNE)
    assert pc.patch_cesa_logo_white_native_size(data) is True
    assert (
        data[pc.ADDR_CESA_LOGO_WHITE_BNE : pc.ADDR_CESA_LOGO_WHITE_BNE + 4]
        == pc.PATCH_CESA_LOGO_WHITE_B
    )
    assert pc.patch_cesa_logo_white_native_size(data) is False


def test_logo_white_native_size_rejects_unknown_bytes():
    data = _blob(b"\x00\x00\x00\x00")
    try:
        pc.patch_cesa_logo_white_native_size(data)
    except ValueError as exc:
        assert "logo_white branch" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_logo_white_native_size_vanilla_dump_applies():
    import sys

    sys.path.insert(0, str(SRC))
    from nlpp_paths import find_vanilla_code

    src = find_vanilla_code()
    if src is None:
        return
    data = bytearray(src.read_bytes())
    assert (
        data[pc.ADDR_CESA_LOGO_WHITE_BNE : pc.ADDR_CESA_LOGO_WHITE_BNE + 4]
        == pc.ORIG_CESA_LOGO_WHITE_BNE
    )
    assert pc.patch_cesa_logo_white_native_size(data) is True
    assert (
        data[pc.ADDR_CESA_LOGO_WHITE_BNE : pc.ADDR_CESA_LOGO_WHITE_BNE + 4]
        == pc.PATCH_CESA_LOGO_WHITE_B
    )
