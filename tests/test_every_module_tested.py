"""Every patch_* and deploy_* module must be named by at least one test.

UNTESTED is a ratchet: it lists modules that had no test when this check
was added. Add a test, then remove the name here. Never add new names.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import ROOT, SRC, TOOLS

UNTESTED = {
    "deploy_bleeding_edge_name_input",
    "deploy_cesa_en",
    "deploy_commu_option_en",
    "deploy_gallery_common_en",
    "deploy_input_keyboard_en",
    "deploy_mail_home_en",
    "deploy_mydata_en",
    "deploy_myroom_main_en",
    "deploy_sms_maildic_en",
    "deploy_sound_settings_en",
    "deploy_status_stats_en",
    "deploy_todo_en",
    "deploy_todo_hist_en",
    "deploy_watcher_issue28_en",
}


def _modules() -> list[str]:
    paths = [*SRC.glob("patch_*.py"), *TOOLS.glob("deploy_*.py")]
    return sorted(p.stem for p in paths)


def _test_text() -> str:
    me = Path(__file__).name
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "tests").glob("*.py")
        if p.name != me
    )


def test_every_module_is_named_by_a_test():
    text = _test_text()
    missing = [m for m in _modules() if m not in text and m not in UNTESTED]
    assert not missing, f"add a test that exercises: {missing}"


def test_tested_modules_are_not_gitignored():
    """tools/ is an allowlist in .gitignore; a new script must be added there
    or it never reaches CI or the gold runner."""
    text = _test_text()
    paths = [
        p.relative_to(ROOT).as_posix()
        for p in [*SRC.glob("*.py"), *TOOLS.glob("*.py")]
        if p.stem in text
    ]
    proc = subprocess.run(
        ["git", "check-ignore", "--no-index", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    ignored = proc.stdout.split()
    assert not ignored, f"tested but gitignored (add !path to .gitignore): {ignored}"


def test_untested_list_only_shrinks():
    text = _test_text()
    mods = set(_modules())
    stale = sorted(m for m in UNTESTED if m not in mods or m in text)
    assert not stale, f"remove from UNTESTED (now tested or deleted): {stale}"
