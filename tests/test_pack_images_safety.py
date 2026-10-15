"""Source ratchets: never ship full Image.write / --full-repack on bake paths."""

from __future__ import annotations

from conftest import ROOT, TOOLS


def test_rebuild_and_drop_never_pass_full_repack():
    rebuild = (TOOLS / "rebuild_bake_img.py").read_text(encoding="utf-8")
    assert "--full-repack" not in rebuild
    bat = (ROOT / "Drop CIA or 3DS Here to Patch.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "--full-repack" not in bat
    assert "full_repack" not in bat


def test_deploy_scripts_never_call_image_write():
    """Full Image.write rebuilds black-screen boots; deploys must splice only."""
    bad = []
    for path in sorted(TOOLS.glob("deploy_*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.split("#", 1)[0]
            if "Image.write" in stripped:
                bad.append(f"{path.name}: {line.strip()}")
    assert not bad, "\n".join(bad)
