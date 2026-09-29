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


def _nintendo_blob(word: bytes) -> bytearray:
    data = bytearray(pc.ADDR_NINTENDO_LOGO_TEX_ID + 4)
    data[pc.ADDR_NINTENDO_LOGO_TEX_ID : pc.ADDR_NINTENDO_LOGO_TEX_ID + 4] = word
    return data


def test_nintendo_logo_clears_shared_thank_id():
    data = _nintendo_blob(pc.ORIG_NINTENDO_LOGO_TEX_ID)
    assert pc.patch_nintendo_logo_skip_thank_flash(data) is True
    assert (
        data[pc.ADDR_NINTENDO_LOGO_TEX_ID : pc.ADDR_NINTENDO_LOGO_TEX_ID + 4]
        == pc.PATCH_NINTENDO_LOGO_TEX_ID
    )
    assert pc.patch_nintendo_logo_skip_thank_flash(data) is False


def test_nintendo_logo_rejects_unknown_id():
    data = _nintendo_blob(b"\x02\x00\x5a\x00")
    try:
        pc.patch_nintendo_logo_skip_thank_flash(data)
    except ValueError as exc:
        assert "NintendoLogo" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_nintendo_logo_vanilla_dump_applies():
    import sys

    sys.path.insert(0, str(SRC))
    from nlpp_paths import find_vanilla_code

    src = find_vanilla_code()
    if src is None:
        return
    data = bytearray(src.read_bytes())
    assert (
        data[pc.ADDR_NINTENDO_LOGO_TEX_ID : pc.ADDR_NINTENDO_LOGO_TEX_ID + 4]
        == pc.ORIG_NINTENDO_LOGO_TEX_ID
    )
    assert pc.patch_nintendo_logo_skip_thank_flash(data) is True
    # CesaLogo's own logo_white id stays so the right pane still gets the banner.
    assert data[0x16F3C4 : 0x16F3C8] == pc.ORIG_NINTENDO_LOGO_TEX_ID


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
