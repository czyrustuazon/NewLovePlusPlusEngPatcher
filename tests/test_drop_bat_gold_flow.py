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
    req = (ROOT / "dev" / "requirements.txt").read_text(encoding="utf-8")
    assert "PyYAML" in req
    root_req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "-r dev/requirements.txt" in root_req
    text = _bat_text()
    assert 'pip install -r "%~dp0requirements.txt"' in text
    # Deps install before the drop window and before any patch step.
    install_idx = text.index('pip install -r "%~dp0requirements.txt"')
    assert install_idx < text.index("goto :run_patch")
    assert install_idx < text.index("setup_tools.py")
    assert "NLPP_PY_DEPS" in text
    setup = (ROOT / "src" / "setup_tools.py").read_text(encoding="utf-8")
    assert '("yaml", "PyYAML")' in setup
    assert "pip" in setup and "install" in setup


def test_bat_wipes_out_and_release_before_build():
    text = _bat_text()
    wipe_idx = text.index("--wipe-cia-build")
    assert "Wiping out\\, release\\, and cache\\" in text
    assert "scratch_cleanup.py" in text
    assert wipe_idx < text.index("Using gold bake")
    assert wipe_idx < text.index("Injecting scripts + UI")
    # From-scratch deletes cache/ (slim vanilla_from_rom must not survive).
    assert "cache\\ is left as-is" not in text
    assert "--preserve-rom" in text
    # A/B Azahar copies live outside out/ so this wipe does not delete them.
    assert "ab_test\\azahar_instances\\ is left as-is" in text


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
    assert "building locally from the dropped ROM" in text
    assert "NLPP_GITHUB_BAKE=1" in text
    assert "1;95" in text


def test_bat_rc_ignores_leftover_bake_without_matching_stamp():
    text = _bat_text()
    assert "patcher_version.py" in text
    assert "BAKE_STALE" in text
    assert "NLPP_REUSE_BAKE" in text
    assert "FETCHED_GOLD" in text
    assert "NLPP_USE_PACK_CACHE is ignored" in text
    assert 'set "PACK_CACHE=--use-cache"' not in text
    assert "from scratch" in text.lower() or "from-scratch" in text
    # A GitHub download is used even when the wiped stamp would look stale.
    assert "if not defined BAKE_STALE if /i not" not in text
    fetch_idx = text.index("fetch_release_bake.py")
    assert fetch_idx < text.index("BAKE_STALE")
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
    assert 'INJECT_CODE=--inject-code "%~dp0release\\name_input_code.bin"' in text
    # Unquoted %~dp0 paths split on spaces (E:\zip game\...) and argparse
    # reports the leftover as unrecognized arguments: ...\name_input_code.bin
    # LayeredFS is off (white screen on hardware). The CIA sits directly in out\.
    assert 'set "LAYEREDFS="' in text
    assert "--layeredfs-out" not in text.split('set "LAYEREDFS="')[1].split("\n")[0]
    assert text.count("!LAYEREDFS!") == 2
    assert r'out\NewLovePlusPlus-EN.cia' in text
    assert "1_[Either use this-CIA]" not in text
    assert "Copy that folder to SD:/luma/titles/" not in text
    assert "Scripts-only patch" not in text


def test_bat_stops_when_drop_zone_script_is_missing():
    """A lone bat pauses. Sync needs an extracted Release zip first."""
    text = _bat_text()
    missing = text.index("Cannot find src\\drop_zone.ps1")
    assert missing < text.index("goto :run_patch")
    assert "Extract the entire archive / repo first" in text
    # Source sync runs only after Python is found and the tree already exists.
    assert missing < text.index("fetch_main_tree.py")
    assert "ensure_patcher_tree" not in text


def test_bat_best_effort_syncs_main_sources_before_deps():
    """Release-zip users overlay tip of main (no git); failure never hard-stops."""
    text = _bat_text()
    sync_idx = text.index("fetch_main_tree.py")
    deps_idx = text.index('pip install -r "%~dp0requirements.txt"')
    assert sync_idx < deps_idx
    assert "--best-effort" in text
    assert "NLPP_SKIP_SOURCE_FETCH" in text
    assert "NLPP_SOURCE_SYNCED" in text
    assert "restarting Drop CIA once" in text
    # Exit 2 from the helper means re-exec; other codes continue.
    assert 'if "!NLPP_SOURCE_RC!"=="2"' in text


def test_bat_drop_timer_avoids_for_f_python_quoting():
    """cmd FOR /F '"%PYTHON%" -c "import' treats python.exe\" -c \"import as the exe."""
    text = _bat_text()
    assert "run_timer.py" in text
    assert "--now" in text
    assert "nlpp_t0.txt" in text
    assert "nlpp_elapsed.txt" in text
    assert "Time to finish" in text
    assert "STARTED_UNIX" in text
    assert "--started-unix" in text
    # Drop start must reach patch_cia.py (PATCH SUMMARY), not only the bat echo.
    assert "!STARTED_UNIX!" in text
    # The broken start-clock line (and the matching elapsed FOR /F).
    assert "import time; print(int(time.time()))" not in text
    assert "for /f %%T in" not in text
    assert 'for /f "delims=" %%E in' not in text
