"""Tests for patch_cia helpers beyond gold-bake resolution."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from conftest import SRC, load_module

patch_cia = load_module("patch_cia", SRC / "patch_cia.py")


def test_sha1_file(tmp_path: Path):
    p = tmp_path / "blob.bin"
    data = b"test payload for sha1"
    p.write_bytes(data)
    assert patch_cia.sha1_file(p) == hashlib.sha1(data).hexdigest()


def test_detect_rom_kind_by_extension(tmp_path: Path):
    cia = tmp_path / "game.cia"
    cia.write_bytes(b"\x00" * 64)
    assert patch_cia.detect_rom_kind(cia) == "cia"
    assert patch_cia.detect_rom_kind(tmp_path / "game.3ds") == "cci"
    assert patch_cia.detect_rom_kind(tmp_path / "game.cci") == "cci"


def test_resolve_romfs_overlay_explicit(tmp_path: Path, monkeypatch):
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    monkeypatch.setattr(patch_cia, "DEFAULT_ROMFS_OVERLAY", tmp_path / "release")
    monkeypatch.setattr(patch_cia, "_LEGACY_ROMFS_OVERLAY", tmp_path / "cache")
    args = argparse.Namespace(romfs_overlay=str(overlay))
    assert patch_cia.resolve_romfs_overlay(args) == overlay.resolve()


def test_resolve_romfs_overlay_default_release(tmp_path: Path, monkeypatch):
    release = tmp_path / "release" / "romfs_overlay"
    release.mkdir(parents=True)
    monkeypatch.setattr(patch_cia, "DEFAULT_ROMFS_OVERLAY", release)
    monkeypatch.setattr(patch_cia, "_LEGACY_ROMFS_OVERLAY", tmp_path / "cache")
    args = argparse.Namespace(romfs_overlay=None)
    assert patch_cia.resolve_romfs_overlay(args) == release.resolve()


def test_apply_romfs_overlay_copies_files(tmp_path: Path):
    overlay = tmp_path / "overlay"
    trb = overlay / "SystemData" / "TextResource"
    trb.mkdir(parents=True)
    (trb / "textresource_jpn.trb").write_bytes(b"trb")
    romfs = tmp_path / "romfs"
    romfs.mkdir()
    n = patch_cia.apply_romfs_overlay(romfs, overlay)
    assert n == 1
    assert (romfs / "SystemData" / "TextResource" / "textresource_jpn.trb").is_file()


def test_allowed_dump_sha1_is_lowercase_hex():
    for h in patch_cia.ALLOWED_DUMP_SHA1:
        assert len(h) == 40
        assert h == h.lower()
        int(h, 16)


def test_next_cia_title_version_bumps_from_dump_and_stamp(tmp_path: Path):
    stamp = tmp_path / "cia_title_ver.txt"
    first = patch_cia.next_cia_title_version(0, stamp_path=stamp)
    assert first == 1
    assert stamp.read_text(encoding="utf-8").strip() == "1"
    second = patch_cia.next_cia_title_version(0, stamp_path=stamp)
    assert second == 2
    assert patch_cia.next_cia_title_version(5, stamp_path=stamp) == 6


def test_next_cia_title_version_explicit_and_keep(tmp_path: Path):
    stamp = tmp_path / "cia_title_ver.txt"
    assert patch_cia.next_cia_title_version(0, stamp_path=stamp, explicit=20) == 20
    assert patch_cia.next_cia_title_version(0, stamp_path=stamp) == 21
    assert patch_cia.next_cia_title_version(3, stamp_path=stamp, keep_source=True) == 3
    # keep_source still records the dump version so a later auto bump stays higher
    assert patch_cia.read_title_ver_stamp(stamp) == 21


def test_next_cia_title_version_caps_at_16_bit(tmp_path: Path):
    stamp = tmp_path / "cia_title_ver.txt"
    stamp.write_text(str(patch_cia.TITLE_VER_MAX), encoding="utf-8")
    assert (
        patch_cia.next_cia_title_version(0, stamp_path=stamp)
        == patch_cia.TITLE_VER_MAX
    )


def test_resolve_cia_title_version_rejects_both_flags(tmp_path: Path):
    args = argparse.Namespace(title_ver=4, keep_title_ver=True)
    try:
        patch_cia.resolve_cia_title_version(args, 0)
        raise AssertionError("expected PatchError")
    except patch_cia.PatchError as exc:
        assert "--title-ver" in str(exc)
        assert "--keep-title-ver" in str(exc)
