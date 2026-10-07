"""OpenLinkFile clone patch is vendored and wired into build-azahar."""

from __future__ import annotations

from conftest import ROOT


def test_openlinkfile_patch_clones_session_slot():
    patch = ROOT / "ab_test" / "patches" / "azahar-openlinkfile.patch"
    text = patch.read_text(encoding="utf-8")
    assert patch.is_file()
    assert "clone offset=" in text
    assert "slot->offset = offset" in text
    assert "slot->size = size" in text
    assert "slot->subfile = subfile" in text
    assert "leaving backend open" in text
    assert "slot->size = backend->GetSize()" in text


def test_build_azahar_uses_fork_or_applies_both_patches():
    make = (ROOT / "ab_test" / "make.ps1").read_text(encoding="utf-8")
    # Defaults to the azahar-3ds-accurate fork (CLAUDE.md hard requirement).
    assert '"azahar-3ds-accurate"' in make
    assert "Ensure-AzaharNlppChanges" in make
    # A plain upstream checkout still gets the OpenLinkFile + NLPP_EMU exports.
    assert "azahar-openlinkfile.patch" in make
    assert "azahar-nlpp-emu.patch" in make
    assert "Copy-AzaharToInstances" in make
