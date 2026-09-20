"""Bake stamp / RC from-scratch identity."""

from __future__ import annotations

from pathlib import Path

import patcher_version as pv
from patcher_version import (
    CIA_TITLE_VERSION,
    PATCHER_RELEASE,
    bake_stamp_matches,
    write_bake_stamp,
)


def test_patcher_release_is_rc():
    assert PATCHER_RELEASE.startswith("v")
    assert "rc" in PATCHER_RELEASE.lower()
    assert PATCHER_RELEASE.endswith("-NENE")


def test_cia_title_version_is_pinned_int():
    """Manual RC pin — must increase on merge to main, never reset per clone."""
    assert isinstance(CIA_TITLE_VERSION, int)
    assert 1 <= CIA_TITLE_VERSION <= 0xFFFF


def test_bake_stamp_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pv, "ui_png_fingerprint", lambda: "deadbeefcafebabe")
    stamp = tmp_path / "bake_stamp.txt"
    assert bake_stamp_matches(stamp) is False
    write_bake_stamp(stamp)
    text = stamp.read_text(encoding="utf-8")
    assert text.splitlines()[0] == PATCHER_RELEASE
    assert "ui-png:deadbeefcafebabe" in text
    assert bake_stamp_matches(stamp) is True
    stamp.write_text("v0.0.0-old\n", encoding="utf-8")
    assert bake_stamp_matches(stamp) is False


def test_oneline_rc_stamp_is_stale(tmp_path: Path, monkeypatch):
    """rc2 wrote PATCHER_RELEASE-only after --skip-pack; that must not reuse bake."""
    monkeypatch.setattr(pv, "ui_png_fingerprint", lambda: "deadbeefcafebabe")
    stamp = tmp_path / "bake_stamp.txt"
    stamp.write_text(PATCHER_RELEASE + "\n", encoding="utf-8")
    assert bake_stamp_matches(stamp) is False


def test_skip_pack_does_not_claim_changed_pngs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pv, "ui_png_fingerprint", lambda: "aaaaaaaaaaaaaaaa")
    stamp = tmp_path / "bake_stamp.txt"
    write_bake_stamp(stamp, packed_assets=True)
    monkeypatch.setattr(pv, "ui_png_fingerprint", lambda: "bbbbbbbbbbbbbbbb")
    write_bake_stamp(stamp, packed_assets=False)
    assert "aaaaaaaaaaaaaaaa" in stamp.read_text(encoding="utf-8")
    assert bake_stamp_matches(stamp) is False


def test_skip_pack_refreshes_when_pngs_unchanged(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(pv, "ui_png_fingerprint", lambda: "cccccccccccccccc")
    stamp = tmp_path / "bake_stamp.txt"
    write_bake_stamp(stamp, packed_assets=True)
    write_bake_stamp(stamp, packed_assets=False)
    assert bake_stamp_matches(stamp) is True
