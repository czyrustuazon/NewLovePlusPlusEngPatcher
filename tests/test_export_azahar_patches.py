"""ab_test/patches must match the azahar-3ds-accurate fork (CLAUDE.md rule).

Runs where the fork is checked out (../azahar-3ds-accurate or NLPP_AZAHAR_FORK); CI skips.
Fix a failure with: python tools/export_azahar_patches.py
"""

from __future__ import annotations

import subprocess

import pytest

from conftest import TOOLS, load_module

export = load_module("export_azahar_patches", TOOLS / "export_azahar_patches.py")


def test_patches_match_fork_main():
    fork = export.fork_dir()
    if not (fork / ".git").exists():
        pytest.skip(f"no azahar-3ds-accurate checkout at {fork}")
    try:
        bad = export.stale(fork)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"fork checkout has no {export.BRANCH} / {export.UPSTREAM}: {exc.stderr.strip()}")
    assert not bad, (
        f"stale vs fork {export.BRANCH}: {bad}. Commit to the fork (the owner pushes), then run "
        "python tools/export_azahar_patches.py"
    )


def test_body_ignores_header_and_line_endings():
    a = "header one\r\nBase: x\r\n\r\ndiff --git a/f b/f\r\n+x\r\n"
    b = "other header\n\ndiff --git a/f b/f\n+x\n"
    assert export._body(a) == export._body(b)
    assert export._body(a) != export._body(b + "+y\n")
