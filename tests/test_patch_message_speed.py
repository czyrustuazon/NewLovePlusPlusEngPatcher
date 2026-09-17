"""Message Speed: Options 14/8/2/0, TalkWindow ÷4, voice/script cap."""

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


def test_talk_table_patch_rewrites_five_dwords():
    data = bytearray(ms.TALK_TABLE_OFF + 32)
    data[ms.TALK_TABLE_OFF : ms.TALK_TABLE_OFF + len(ms.TALK_VANILLA_BYTES)] = (
        ms.TALK_VANILLA_BYTES
    )
    data[ms.ADDR_FN : ms.ADDR_FN + 4] = ms.VANILLA_HEAD
    data[ms.OFF_LV1 : ms.OFF_LV1 + 4] = ms.VANILLA_LV1
    data[ms.OFF_LV2 : ms.OFF_LV2 + 4] = ms.VANILLA_LV2
    data[ms.OFF_LV3 : ms.OFF_LV3 + 4] = ms.VANILLA_LV3
    data[ms.OFF_LV4 : ms.OFF_LV4 + 4] = ms.VANILLA_LV4
    assert ms.is_talk_vanilla(data)
    assert not ms.is_talk_patched(data)
    assert ms.apply_patch(data) is True
    assert ms.is_talk_patched(data)
    assert ms.is_options_patched(data)
    assert data[ms.TALK_TABLE_OFF : ms.TALK_TABLE_OFF + len(ms.TALK_PATCHED_BYTES)] == (
        ms.TALK_PATCHED_BYTES
    )
    assert ms.apply_patch(data) is False


def test_talk_table_revert_restores_vanilla():
    data = bytearray(ms.TALK_TABLE_OFF + 32)
    data[ms.TALK_TABLE_OFF : ms.TALK_TABLE_OFF + len(ms.TALK_PATCHED_BYTES)] = (
        ms.TALK_PATCHED_BYTES
    )
    data[ms.ADDR_FN : ms.ADDR_FN + 4] = ms.VANILLA_HEAD
    data[ms.OFF_LV1 : ms.OFF_LV1 + 4] = ms.PATCHED_LV1
    data[ms.OFF_LV2 : ms.OFF_LV2 + 4] = ms.PATCHED_LV2
    data[ms.OFF_LV3 : ms.OFF_LV3 + 4] = ms.PATCHED_LV3
    data[ms.OFF_LV4 : ms.OFF_LV4 + 4] = ms.VANILLA_LV4
    assert ms.revert_patch(data) is True
    assert ms.is_talk_vanilla(data)
    assert ms.is_options_vanilla(data)
    assert ms.revert_patch(data) is False


def test_message_speed_vanilla_dump_applies():
    import sys

    sys.path.insert(0, str(SRC))
    from nlpp_paths import find_vanilla_code

    src = find_vanilla_code()
    if src is None:
        return
    data = bytearray(src.read_bytes())
    assert data[ms.ADDR_FN : ms.ADDR_FN + 4] == ms.VANILLA_HEAD
    assert ms.is_talk_vanilla(data)
    if ms.is_fully_patched(data):
        return
    assert ms.is_vanilla(data)
    assert ms.apply_patch(data) is True
    assert ms.is_patched(data)
    assert ms.is_talk_patched(data)
    assert ms.is_fully_patched(data)
    assert ms.is_talk_cap_patched(data)
    assert data[ms.TALK_HOOK_OFF : ms.TALK_HOOK_OFF + 4] == ms.TALK_HOOK_PATCHED
    assert (
        data[ms.ADDR_TALK_CAP_CAVE : ms.ADDR_TALK_CAP_CAVE + ms.TALK_CAP_CAVE_LEN]
        == ms.TALK_CAP_CAVE_BYTES
    )


def _cap_blob() -> bytearray:
    data = bytearray(ms.ADDR_TALK_CAP_CAVE + ms.TALK_CAP_CAVE_LEN)
    data[ms.ADDR_FN : ms.ADDR_FN + 4] = ms.VANILLA_HEAD
    data[ms.OFF_LV1 : ms.OFF_LV1 + 4] = ms.VANILLA_LV1
    data[ms.OFF_LV2 : ms.OFF_LV2 + 4] = ms.VANILLA_LV2
    data[ms.OFF_LV3 : ms.OFF_LV3 + 4] = ms.VANILLA_LV3
    data[ms.OFF_LV4 : ms.OFF_LV4 + 4] = ms.VANILLA_LV4
    data[ms.TALK_HOOK_OFF : ms.TALK_HOOK_OFF + 4] = ms.TALK_HOOK_VANILLA
    return data


def test_talk_cap_cave_is_rx_and_hooks_cpy():
    blob = ms.build_talk_cap_cave()
    assert len(blob) == ms.TALK_CAP_CAVE_LEN
    assert blob[-4:] == (ms.TALK_TABLE_OFF + 0x100000).to_bytes(4, "little")
    w = int.from_bytes(ms.TALK_HOOK_PATCHED, "little")
    assert (w >> 24) == 0xEB
    off = w & 0xFFFFFF
    if off & 0x800000:
        off -= 0x1000000
    target = ms.TALK_HOOK_OFF + 8 + (off << 2)
    assert target == ms.ADDR_TALK_CAP_CAVE


def test_talk_cap_patch_rewrites_hook():
    data = _cap_blob()
    assert ms.is_talk_cap_vanilla(data)
    assert not ms.is_talk_cap_patched(data)
    assert ms.apply_patch(data) is True
    assert ms.is_talk_cap_patched(data)
    assert ms.is_options_patched(data)
    assert ms.apply_patch(data) is False
    assert ms.revert_talk_cap(data) is True
    assert ms.is_talk_cap_vanilla(data)
    assert ms.is_options_patched(data)
    assert ms.revert_talk_cap(data) is False
