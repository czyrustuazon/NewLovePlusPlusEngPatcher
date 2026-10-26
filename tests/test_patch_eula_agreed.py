"""StreetPass can be turned on without the offline terms-of-use check."""

from __future__ import annotations

import pytest

from conftest import SRC, load_module

eula = load_module("patch_eula_agreed", SRC / "patch_eula_agreed.py")


def _image(heads=None) -> bytearray:
    data = bytearray(max(s for s, *_ in eula.SITES) + 0x20)
    for i, (site, vanilla, _p, _l) in enumerate(eula.SITES):
        head = vanilla if heads is None else heads[i]
        data[site : site + len(head)] = head
    return data


def test_both_checks_pass():
    data = _image()
    assert eula.apply_patch(data) is True
    assert eula.is_patched(data)
    assert eula.apply_patch(data) is False


def test_stub_return_values():
    by_label = {label: patched for _s, _v, patched, label in eula.SITES}
    assert by_label["IsEulaAgreed"] == bytes.fromhex("0100a0e3" "1eff2fe1")  # true
    assert by_label["CecCheckEula"] == bytes.fromhex("0000a0e3" "1eff2fe1")  # success
    assert by_label["CecGateEulaFlag"] == bytes.fromhex("00f020e3")  # nop the beq


def test_half_patched_image_is_completed():
    # An image with only one stub (an earlier build) gets the other one too.
    site, _v, patched, _l = eula.SITES[0]
    data = _image()
    data[site : site + len(patched)] = patched
    assert eula.apply_patch(data) is True
    assert eula.is_patched(data)


def test_unexpected_head_is_refused():
    with pytest.raises(ValueError):
        eula.apply_patch(_image([bytes(8)] * len(eula.SITES)))
