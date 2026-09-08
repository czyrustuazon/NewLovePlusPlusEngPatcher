"""Regression tests for Drop CIA.bat gold-bake workflow (CI poll → local rebuild)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAT = ROOT / "Drop CIA or 3DS Here to Patch.bat"


def _bat_text() -> str:
    assert BAT.is_file(), f"missing {BAT}"
    return BAT.read_text(encoding="utf-8", errors="replace")


def test_requirements_include_nlpp_tools_yaml():
    """Gold unpack (`ie`) imports yaml; drop-bat pip must install PyYAML."""
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "PyYAML" in req
    setup = (ROOT / "src" / "setup_tools.py").read_text(encoding="utf-8")
    assert '("yaml", "PyYAML")' in setup


def test_bat_defaults_packed_img_to_release_bake():
    text = _bat_text()
    assert 'set "PACKED_IMG=%~dp0release\\bake_img.bin"' in text
    # Regression: must not default normal path to PNG scratch cache.
    assert not text.strip().startswith('set "PACKED_IMG=%~dp0cache\\new_img.bin"')


def test_bat_polls_ci_before_local_rebuild():
    text = _bat_text()
    fetch_idx = text.index("fetch_release_bake.py")
    # Full rebuild when bake is missing (not the --skip-pack recovery path).
    rebuild_idx = text.index("running tools\\rebuild_bake_img.py")
    assert fetch_idx < rebuild_idx
    assert "--best-effort" in text


def test_bat_rc_ignores_leftover_bake_without_matching_stamp():
    text = _bat_text()
    assert "patcher_version.py" in text
    assert "BAKE_STALE" in text
    assert "NLPP_REUSE_BAKE" in text
    assert "NLPP_USE_PACK_CACHE" in text
    assert "from scratch" in text.lower() or "from-scratch" in text
    # Reuse leftover bake is opt-in; default is stamp-check then rebuild.
    stale_idx = text.index("BAKE_STALE")
    inject_idx = text.index("Injecting gold bake")
    assert stale_idx < inject_idx


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


def test_bat_finishes_incomplete_bake_missing_eng_patch():
    """PNG-seeded bake without Eng_Patch must --skip-pack before inject."""
    text = _bat_text()
    assert "_title_pkg_has_eng_patch" in text
    assert "--skip-pack" in text
    assert "name_input_code.bin" in text
    check_idx = text.index("_title_pkg_has_eng_patch")
    inject_idx = text.index("Injecting gold bake")
    assert check_idx < inject_idx
    assert text.index("--skip-pack") < inject_idx


def test_bat_requires_name_input_and_rejects_images_off():
    text = _bat_text()
    assert "NLPP_WITH_IMAGES=0 is not allowed" in text
    assert "name_input_code.bin still missing after rebuild" in text
    assert "INJECT_CODE=--inject-code" in text
    assert "Scripts-only patch" not in text
