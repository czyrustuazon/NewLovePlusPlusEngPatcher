"""Day counter suffix 日目 → ' Day  ' in the resident TRB and img.bin pkg 5508."""

from __future__ import annotations

from pathlib import Path

import pytest

import fake_img as fi
from conftest import TOOLS, load_module

day = load_module("deploy_day_counter_en", TOOLS / "deploy_day_counter_en.py")
OFF = day.DAY_SUFFIX_OFF
SIZE = 223280


def _trb(suffix: bytes = day.DAY_SUFFIX_JP, size: int = SIZE) -> bytes:
    data = bytearray(size)
    data[OFF : OFF + 6] = suffix
    return bytes(data)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    paths = fi.use_paths(monkeypatch, tmp_path, day)
    img = tmp_path / "img.bin"
    img.write_bytes(fi.img({}, raw={day.RESIDENT_PKG: _trb()}))
    trb = tmp_path / "resident.trb"
    trb.write_bytes(_trb())
    durable = [tmp_path / "release" / "r.trb", tmp_path / "overlay" / "r.trb"]
    monkeypatch.setattr(day, "MOD_IMG", img)
    monkeypatch.setattr(day, "DURABLE_TRBS", durable)
    monkeypatch.setenv("NLPP_RESIDENT_TRB", str(trb))
    return {"img": img, "trb": trb, "durable": durable, **paths}


def _pkg_suffix(img: Path) -> bytes:
    return fi.read_package(img, day.RESIDENT_PKG)[OFF : OFF + 6]


def test_patch_trb_bytes():
    data = bytearray(_trb())
    assert day.patch_trb_bytes(data) is True
    assert data[OFF : OFF + 6] == day.DAY_SUFFIX_EN
    assert day.patch_trb_bytes(data) is False
    with pytest.raises(SystemExit, match="unexpected bytes"):
        day.patch_trb_bytes(bytearray(_trb(b"??????")))


def test_main_patches_trb_copies_and_img(env):
    day.main()
    assert env["trb"].read_bytes()[OFF : OFF + 6] == day.DAY_SUFFIX_EN
    assert env["trb"].with_suffix(".trb.bak_pre_day_suffix").read_bytes() == _trb()
    for p in env["durable"]:
        assert p.read_bytes() == env["trb"].read_bytes()
    assert _pkg_suffix(env["img"]) == day.DAY_SUFFIX_EN

    # Second run: already patched, backup kept.
    day.main()
    assert env["trb"].with_suffix(".trb.bak_pre_day_suffix").read_bytes() == _trb()


def test_main_needs_img(env, monkeypatch, tmp_path):
    monkeypatch.setattr(day, "MOD_IMG", tmp_path / "none.bin")
    with pytest.raises(SystemExit, match="missing"):
        day.main()


def test_main_rejects_wrong_trb_size(env):
    env["trb"].write_bytes(_trb(size=SIZE - 4))
    with pytest.raises(SystemExit, match="unexpected resident TRB size"):
        day.main()


def test_main_verifies_trb_after_patch(env, monkeypatch):
    monkeypatch.setattr(day, "patch_trb_bytes", lambda data: False)
    with pytest.raises(SystemExit, match="TRB missing Day suffix"):
        day.main()


def test_main_verifies_img_after_splice(env, monkeypatch):
    monkeypatch.setattr(day, "splice_packages_into_img", lambda *a: None)
    with pytest.raises(SystemExit, match="pkg 5508 verify failed"):
        day.main()
