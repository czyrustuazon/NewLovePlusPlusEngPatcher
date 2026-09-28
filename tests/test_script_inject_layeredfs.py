"""LayeredFS dialog inject matches the CIA .dbin2 picker."""

from __future__ import annotations

from pathlib import Path

import pytest

import script_inject


def _write(root: Path, rel: str, payload: bytes = b"EN") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_layeredfs_inject_creates_dirs_and_skips_japanese(tmp_path: Path, monkeypatch):
    eng = tmp_path / "rebuild_dbin2"
    _write(eng, "NLP_01/t001.dbin2", b"manaka")
    _write(eng, "NLP_01/a001.dbin2", b"skip-pack")
    _write(eng, "NLP_02/p010.dbin2", b"common")
    _write(eng, "script/t002.dbin2", b"manaka-script")
    _write(eng, "script/a900.dbin2", b"community")
    _write(eng, "script/a901.dbin2", b"still-jp")
    monkeypatch.setattr(script_inject, "community_stems", lambda: {"a900"})

    romfs = tmp_path / "romfs"
    count = script_inject.inject_scripts(romfs, eng, create_dirs=True)

    assert count == 4
    assert (romfs / "script/bin/NLP_01/t001.dbin2").read_bytes() == b"manaka"
    assert (romfs / "script/bin/NLP_02/p010.dbin2").read_bytes() == b"common"
    assert (romfs / "script/bin/script/t002.dbin2").read_bytes() == b"manaka-script"
    assert (romfs / "script/bin/script/a900.dbin2").read_bytes() == b"community"
    assert not (romfs / "script/bin/NLP_01/a001.dbin2").exists()
    assert not (romfs / "script/bin/script/a901.dbin2").exists()


def test_cia_inject_still_requires_existing_pack_dirs(tmp_path: Path):
    eng = tmp_path / "rebuild_dbin2"
    for pack in ("NLP_01", "NLP_02", "script"):
        _write(eng, f"{pack}/t001.dbin2")
    with pytest.raises(script_inject.ScriptInjectError, match="missing script pack folder"):
        script_inject.inject_scripts(tmp_path / "romfs", eng, create_dirs=False)
