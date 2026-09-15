"""Layered script inject: Gemini Nene a* plus community k* allowlist."""

from __future__ import annotations

from pathlib import Path

from conftest import SRC, load_module

si = load_module("script_inject", SRC / "script_inject.py")


def test_gemini_nene_a141_is_allowlisted_and_injects():
    assert "a141" in si.community_stems()
    path, tag = si.resolve_script_source("script", "a141", si.DEFAULT_ENG_DBIN)
    assert tag == "nlppatch"
    assert path is not None
    assert path.is_file()


def test_nene_allowlist_injects_nlp01_when_pack_file_exists():
    nlp01 = si.DEFAULT_ENG_DBIN / "NLP_01" / "a141.dbin2"
    path, tag = si.resolve_script_source("NLP_01", "a141", si.DEFAULT_ENG_DBIN)
    if nlp01.is_file():
        assert tag == "nlppatch"
        assert path == nlp01
    else:
        assert tag == "jp"
        assert path is None


def test_unlisted_nene_stem_stays_japanese(tmp_path: Path):
    eng = tmp_path / "rebuild_dbin2"
    slot = eng / "script"
    slot.mkdir(parents=True)
    (slot / "a888.dbin2").write_bytes(b"x")
    path, tag = si.resolve_script_source("script", "a888", eng)
    assert path is None
    assert tag == "jp"


def test_rinko_community_stem_still_injects():
    assert "k000" in si.community_stems()
    path, tag = si.resolve_script_source("script", "k000", si.DEFAULT_ENG_DBIN)
    assert tag == "nlppatch"
    assert path is not None and path.is_file()
