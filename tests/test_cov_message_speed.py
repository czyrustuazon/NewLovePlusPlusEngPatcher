"""Branch coverage for patch_message_speed: every site state, apply/revert, main().

Synthetic code.bin: zero bytes plus the Options delays, TalkWindow table,
talk-cap hook and preview sample at their real offsets.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import nlpp_paths
import patch_message_speed as ms
from conftest import SRC, load_module

FULL = max(ms._TALK_NEED, ms._CAP_NEED, ms._SAMPLE_NEED)


def _vanilla(size: int = FULL) -> bytearray:
    data = bytearray(size)
    data[ms.ADDR_FN : ms.ADDR_FN + 4] = ms.VANILLA_HEAD
    for off, vanilla, _p, _n in ms._SITES:
        data[off : off + 4] = vanilla
    if size >= ms._TALK_NEED:
        data[ms.TALK_TABLE_OFF : ms.TALK_TABLE_OFF + len(ms.TALK_VANILLA_BYTES)] = ms.TALK_VANILLA_BYTES
    if size >= ms.TALK_HOOK_OFF + 4:
        data[ms.TALK_HOOK_OFF : ms.TALK_HOOK_OFF + 4] = ms.TALK_HOOK_VANILLA
    if size >= ms._SAMPLE_NEED:
        data[ms.SAMPLE_OFF : ms.SAMPLE_OFF + ms.SAMPLE_SLOT] = ms.SAMPLE_JP
    return data


def test_module_adds_src_to_path(monkeypatch):
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p).resolve() != SRC])
    mod = load_module("patch_message_speed_fresh", SRC / "patch_message_speed.py")
    assert str(SRC) in sys.path
    assert mod.TALK_PATCHED == ms.TALK_PATCHED


def test_helpers_reject_bad_input(monkeypatch):
    with pytest.raises(ValueError, match="imm8"):
        ms._mov_eq_r0(256)
    with pytest.raises(ValueError, match="leaves .text"):
        ms.build_talk_cap_cave(cave=ms.TEXT_PAGE_END)
    monkeypatch.setattr(ms, "TALK_CAP_CAVE_LEN", 4)
    with pytest.raises(ValueError, match="talk cap cave"):
        ms.build_talk_cap_cave()


def test_full_apply_then_revert_round_trip(capsys):
    data = _vanilla()
    assert ms.is_vanilla(data) and ms.is_talk_cap_vanilla(data)
    assert ms.apply_patch(data) is True
    assert ms.is_patched(data) and ms.is_fully_patched(data)
    assert ms.apply_patch(data) is False
    out = capsys.readouterr().out
    assert "already patched" in out and "talk cap already patched" in out and "already EN" in out

    assert ms.is_talk_cap_vanilla(data) is False
    assert ms.revert_patch(data) is True
    assert data == _vanilla()
    assert ms.revert_patch(data) is False
    out = capsys.readouterr().out
    assert "already vanilla" in out and "already JP" in out


def test_is_fully_patched_reports_each_missing_part():
    data = _vanilla()
    assert not ms.is_fully_patched(data)  # options vanilla
    ms.apply_patch(data)
    for part in ("talk", "cap", "sample"):
        broken = bytearray(data)
        if part == "talk":
            broken[ms.TALK_TABLE_OFF] ^= 1
        elif part == "cap":
            broken[ms.TALK_HOOK_OFF] ^= 1
        else:
            broken[ms.SAMPLE_OFF : ms.SAMPLE_OFF + ms.SAMPLE_SLOT] = ms.SAMPLE_JP
        assert not ms.is_fully_patched(broken), part


def test_short_blob_skips_talk_cap_and_sample(capsys):
    data = _vanilla(ms.OFF_LV4 + 4)
    data[ms.TALK_HOOK_OFF : ms.TALK_HOOK_OFF + 4] = b"\x00" * 4  # hook not in this build
    data[ms.SAMPLE_OFF : ms.SAMPLE_OFF + ms.SAMPLE_SLOT] = bytes(ms.SAMPLE_SLOT)  # nor the sample
    assert not ms.is_talk_patched(data)
    assert not ms.is_talk_vanilla(data)
    assert not ms.is_talk_legacy(data)
    assert not ms.is_talk_cap_patched(data)
    assert not ms.is_talk_cap_vanilla(data)
    assert not ms.is_sample_patched(data)
    assert not ms.is_sample_vanilla(data)
    assert ms.apply_patch(data) is True
    assert ms.is_fully_patched(data)
    assert ms.revert_talk_cap(data) is False
    assert ms.revert_patch(data) is True


def test_tiny_blob_has_nothing():
    assert not ms._has_sample(b"")
    assert not ms.is_talk_cap_vanilla(b"")


def test_talk_cap_vanilla_without_cave_region():
    data = _vanilla(ms.TALK_HOOK_OFF + 4)
    assert ms.is_talk_cap_vanilla(data)
    data[ms.TALK_HOOK_OFF] ^= 1
    assert not ms.is_talk_cap_vanilla(data)


def test_options_errors():
    data = _vanilla()
    data[ms.ADDR_FN] = 0
    with pytest.raises(ValueError, match="unexpected FUN_005d1e18 head"):
        ms.apply_patch(data)
    data = _vanilla()
    data[ms.OFF_LV2] = 0x77
    with pytest.raises(ValueError, match="unexpected message-speed delays"):
        ms.apply_patch(data)
    with pytest.raises(ValueError, match="cannot revert: options"):
        ms.revert_patch(data)


def test_talk_table_legacy_and_errors(capsys):
    data = _vanilla()
    data[ms.TALK_TABLE_OFF : ms.TALK_TABLE_OFF + len(ms.TALK_LEGACY_BYTES)] = ms.TALK_LEGACY_BYTES
    assert ms.is_talk_legacy(data)
    assert ms._apply_talk(data) is True
    assert "10/18/22/28/55 ->" in capsys.readouterr().out

    data[ms.TALK_TABLE_OFF] = 0x7F
    with pytest.raises(ValueError, match="unexpected talk delay table"):
        ms._apply_talk(data)
    with pytest.raises(ValueError, match="cannot revert: talk delay"):
        ms._revert_talk(data)


def test_talk_cap_states(capsys):
    data = _vanilla()
    data[ms.TALK_HOOK_OFF : ms.TALK_HOOK_OFF + 4] = b"\x00" * 4
    assert ms._apply_talk_cap(data) is False  # hook not in this build
    assert ms._revert_talk_cap(data) is False

    data[ms.TALK_HOOK_OFF] = 0x99
    with pytest.raises(ValueError, match="unexpected talk-cap hook"):
        ms._apply_talk_cap(data)
    with pytest.raises(ValueError, match="cannot revert: talk-cap"):
        ms._revert_talk_cap(data)

    data = _vanilla()
    data[ms.ADDR_TALK_CAP_CAVE] = 1
    with pytest.raises(ValueError, match="not empty pad"):
        ms._apply_talk_cap(data)
    data = _vanilla()
    data[ms.ADDR_TALK_CAP_CAVE : ms.ADDR_TALK_CAP_CAVE + ms.TALK_CAP_CAVE_LEN] = ms.TALK_CAP_CAVE_BYTES
    assert ms.is_talk_cap_vanilla(data)  # cave written, hook not yet
    assert ms._revert_talk_cap(data) is False
    assert "talk cap already vanilla" in capsys.readouterr().out


def test_sample_foreign_slot(monkeypatch):
    data = _vanilla()
    data[ms.SAMPLE_OFF] = 0x41
    # Neither JP nor EN: _has_sample is False, both sides skip.
    assert ms._apply_sample(data) is False
    assert ms._revert_sample(data) is False
    monkeypatch.setattr(ms, "_has_sample", lambda d: True)
    with pytest.raises(ValueError, match="unexpected message-speed sample"):
        ms._apply_sample(data)
    with pytest.raises(ValueError, match="cannot revert: message-speed sample"):
        ms._revert_sample(data)


def test_main(monkeypatch, tmp_path, capsys):
    assert ms.main(["--dry-run"]) == 0
    assert "TalkWindow" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="--deploy-azahar"):
        ms.main([])

    root = tmp_path / "mods"
    dest = root / "exefs" / "code.bin"
    monkeypatch.setattr(nlpp_paths, "AZAHAR_MOD_CODE", dest)
    monkeypatch.setattr(nlpp_paths, "AZAHAR_MOD_ROOT", root)
    with pytest.raises(SystemExit, match="missing"):
        ms.main(["--deploy-azahar"])

    dest.parent.mkdir(parents=True)
    dest.write_bytes(bytes(_vanilla()))
    assert ms.main(["--deploy-azahar"]) == 0
    assert ms.is_fully_patched((root / "code.bin").read_bytes())
    assert ms.main(["--deploy-azahar", "--revert"]) == 0
    assert dest.read_bytes() == bytes(_vanilla())
    assert (dest.parent / "code.bin.bak_pre_msg_speed").is_file()
