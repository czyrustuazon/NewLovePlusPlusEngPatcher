"""My Camera list shows the Restore Default softkey alongside Back."""

from __future__ import annotations

from conftest import SRC, load_module

cam = load_module("patch_camera_restore_default", SRC / "patch_camera_restore_default.py")


def _image() -> bytearray:
    data = bytearray(cam.ADDR_CAMERA_DEFAULTS_CAVE + cam.CAMERA_DEFAULTS_CAVE_LEN)
    for site, _ in cam.SITES:
        data[site : site + 4] = cam.bl(site, cam.ADDR_SET_SOFTKEY)
    return data


def test_cave_fits_before_fillcand_tail():
    assert len(cam.build_cave()) <= cam.CAMERA_DEFAULTS_CAVE_LEN
    assert cam.ADDR_CAMERA_DEFAULTS_CAVE + cam.CAMERA_DEFAULTS_CAVE_LEN == 0x0068FFCC


def test_cave_sets_slot3_spot_then_calls_slot2_and_slot3():
    import struct

    cave = cam.build_cave()
    base = cam.ADDR_CAMERA_DEFAULTS_CAVE
    # slot 3 = mgr + 0x6C + 3 * 0x34; drawn base +0xC, saved hSy spot +0x24.
    assert (cam.OFF_ACTIVE_POS, cam.OFF_HOLD_POS) == (0x114, 0x12C)
    assert cave[24:28] == bytes.fromhex("142184e5")  # str r2, [r4, #0x114]
    assert cave[36:40] == bytes.fromhex("303184e5")  # str r3, [r4, #0x130]
    assert cave[48:52] == cam.bl(base + 48, cam.ADDR_SET_SOFTKEY)
    assert cave[56:60] == bytes.fromhex("0310a0e3")  # mov r1, #3
    # hide (on=0) puts the vanilla spot back, show (on=1) moves it up.
    assert struct.unpack("<4f", cave[-16:]) == (*cam.VANILLA_POS, *cam.CAMERA_POS)


def test_apply_is_idempotent():
    data = _image()
    assert cam.apply_patch(data) is True
    assert cam.is_patched(data)
    assert cam.apply_patch(data) is False
