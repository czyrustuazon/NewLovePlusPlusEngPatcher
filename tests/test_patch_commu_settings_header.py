"""Communication Settings header is DrawText, not the already-EN MultiWin strip."""

from __future__ import annotations

from conftest import SRC, load_module

hdr = load_module(
    "patch_commu_settings_header", SRC / "patch_commu_settings_header.py"
)


def _image() -> bytearray:
    data = bytearray(hdr.ADDR_COMMU_HEADER_CAVE + hdr.COMMU_HEADER_CAVE_LEN)
    data[hdr.SITE : hdr.SITE + 4] = hdr.VANILLA_SITE
    return data


def test_commu_header_cave_points_at_the_title():
    cave = hdr.build_cave()
    assert cave.endswith(hdr.TITLE)
    assert hdr.bl(hdr.SITE, hdr.ADDR_COMMU_HEADER_CAVE)
    # add r1, pc, #8 at cave+4 lands on the title (cave+20).
    assert cave[20:] == hdr.TITLE
    assert len(cave) <= hdr.COMMU_HEADER_CAVE_LEN


def test_commu_header_apply_is_idempotent():
    data = _image()
    assert hdr.apply_patch(data) is True
    assert hdr.is_patched(data)
    assert data[hdr.SITE : hdr.SITE + 4] == hdr.bl(hdr.SITE, hdr.ADDR_COMMU_HEADER_CAVE)
    assert data[hdr.ADDR_COMMU_HEADER_CAVE : hdr.ADDR_COMMU_HEADER_CAVE + 20 + len(hdr.TITLE)].endswith(
        hdr.TITLE
    )
    assert hdr.apply_patch(data) is False
