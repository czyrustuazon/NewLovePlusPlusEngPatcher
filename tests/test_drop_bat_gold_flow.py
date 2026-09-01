"""Regression tests for Drop CIA.bat gold-bake workflow (CI poll → local rebuild)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAT = ROOT / "Drop CIA or 3DS Here to Patch.bat"


def _bat_text() -> str:
    assert BAT.is_file(), f"missing {BAT}"
    return BAT.read_text(encoding="utf-8", errors="replace")


def test_bat_defaults_packed_img_to_release_bake():
    text = _bat_text()
    assert 'set "PACKED_IMG=%~dp0release\\bake_img.bin"' in text
    # Regression: must not default normal path to PNG scratch cache.
    assert not text.strip().startswith('set "PACKED_IMG=%~dp0cache\\new_img.bin"')


def test_bat_polls_ci_before_local_rebuild():
    text = _bat_text()
    fetch_idx = text.index("fetch_release_bake.py")
    rebuild_idx = text.index("rebuild_bake_img.py")
    assert fetch_idx < rebuild_idx
    assert "--best-effort" in text


def test_bat_fetch_is_automatic_not_opt_in():
    text = _bat_text()
    assert "NLPP_FETCH_GOLD" not in text
    assert "NLPP_SKIP_GOLD_FETCH" in text


def test_bat_aborts_when_gold_bake_still_missing():
    text = _bat_text()
    assert "No gold bake available" in text
    assert "English menus need release\\bake_img.bin" in text


def test_bat_requires_packed_img_before_patch():
    text = _bat_text()
    assert "Gold bake path missing" in text
    assert "Injecting gold bake" in text
