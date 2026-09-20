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


def test_build_azahar_applies_openlinkfile_patch():
    make = (ROOT / "ab_test" / "make.ps1").read_text(encoding="utf-8")
    assert "Ensure-AzaharOpenLinkFile" in make
    assert "azahar-openlinkfile.patch" in make
    assert "Copy-AzaharToInstances" in make
    assert "clone offset=" in make
