"""Message Speed delay table: vanilla 18/12/6/0 → patched 14/8/2/0."""

from __future__ import annotations

from conftest import SRC, load_module

ms = load_module("patch_message_speed", SRC / "patch_message_speed.py")


def _blob(delays: tuple[bytes, bytes, bytes]) -> bytearray:
    data = bytearray(ms.ADDR_FN + 0x40)
    data[ms.ADDR_FN : ms.ADDR_FN + 4] = ms.VANILLA_HEAD
    data[ms.OFF_LV1 : ms.OFF_LV1 + 4] = delays[0]
    data[ms.OFF_LV2 : ms.OFF_LV2 + 4] = delays[1]
    data[ms.OFF_LV3 : ms.OFF_LV3 + 4] = delays[2]
    data[ms.OFF_LV4 : ms.OFF_LV4 + 4] = ms.VANILLA_LV4
    return data


def test_message_speed_patch_rewrites_three_delays():
    data = _blob((ms.VANILLA_LV1, ms.VANILLA_LV2, ms.VANILLA_LV3))
    assert ms.is_vanilla(data)
    assert not ms.is_patched(data)
    assert ms.apply_patch(data) is True
    assert data[ms.OFF_LV1 : ms.OFF_LV1 + 4] == ms.PATCHED_LV1
    assert data[ms.OFF_LV2 : ms.OFF_LV2 + 4] == ms.PATCHED_LV2
    assert data[ms.OFF_LV3 : ms.OFF_LV3 + 4] == ms.PATCHED_LV3
    assert data[ms.OFF_LV4 : ms.OFF_LV4 + 4] == ms.VANILLA_LV4
    assert ms.is_patched(data)
    assert ms.apply_patch(data) is False


def test_message_speed_revert_restores_vanilla():
    data = _blob((ms.PATCHED_LV1, ms.PATCHED_LV2, ms.PATCHED_LV3))
    assert ms.revert_patch(data) is True
    assert ms.is_vanilla(data)
    assert ms.revert_patch(data) is False


def test_message_speed_rejects_unknown_bytes():
    data = _blob((ms.VANILLA_LV1, ms.VANILLA_LV2, ms.VANILLA_LV3))
    data[ms.OFF_LV1] = 0x99
    try:
        ms.apply_patch(data)
    except ValueError as exc:
        assert "unexpected message-speed delays" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_message_speed_vanilla_dump_applies():
    import sys

    sys.path.insert(0, str(SRC))
    from nlpp_paths import find_vanilla_code

    src = find_vanilla_code()
    if src is None:
        return
    data = bytearray(src.read_bytes())
    assert data[ms.ADDR_FN : ms.ADDR_FN + 4] == ms.VANILLA_HEAD
    if ms.is_patched(data):
        return
    assert ms.is_vanilla(data)
    assert ms.apply_patch(data) is True
    assert ms.is_patched(data)
