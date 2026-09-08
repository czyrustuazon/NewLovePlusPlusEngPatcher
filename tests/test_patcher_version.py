"""Bake stamp / RC from-scratch identity."""

from __future__ import annotations

from pathlib import Path

from patcher_version import (
    PATCHER_RELEASE,
    bake_stamp_matches,
    write_bake_stamp,
)


def test_patcher_release_is_rc():
    assert PATCHER_RELEASE.startswith("v")
    assert "rc" in PATCHER_RELEASE.lower()


def test_bake_stamp_roundtrip(tmp_path: Path):
    stamp = tmp_path / "bake_stamp.txt"
    assert bake_stamp_matches(stamp) is False
    write_bake_stamp(stamp)
    assert stamp.read_text(encoding="utf-8").strip() == PATCHER_RELEASE
    assert bake_stamp_matches(stamp) is True
    stamp.write_text("v0.0.0-old\n", encoding="utf-8")
    assert bake_stamp_matches(stamp) is False
