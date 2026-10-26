"""apply_patch / main of patch_input_call_romaji on a synthetic code.bin.

The real lookup bodies are hashed in MATCH_REGIONS; here they are filled with
a marker byte and the hashes swapped for that, so no game data is needed.
"""

from __future__ import annotations

import hashlib

import pytest

import patch_input_call_romaji as cr
from patch_input_cave_map import TEXT_PAGE_END


@pytest.fixture
def code(monkeypatch) -> bytearray:
    data = bytearray(TEXT_PAGE_END)
    regions = {}
    for start, (end, _sha) in cr.MATCH_REGIONS.items():
        data[start:end] = b"\x5a" * (end - start)
        regions[start] = (end, hashlib.sha256(bytes(data[start:end])).hexdigest())
    monkeypatch.setattr(cr, "MATCH_REGIONS", regions)
    return data


def test_apply_patch_writes_matcher(code, capsys):
    before = bytes(code)
    assert cr.apply_patch(code) is True
    assert len(code) == TEXT_PAGE_END
    assert cr.is_patched(code)
    for start, piece in cr.MATCH_PIECES:
        assert bytes(code[start : start + len(piece)]) == piece
    # Nothing outside the lookup bodies changes: a miss takes the vanilla
    # branch to the suggestion list, and the tap handlers keep their strncpy.
    written = bytearray(before)
    for start, piece in cr.MATCH_PIECES:
        written[start : start + len(piece)] = piece
    assert bytes(code) == bytes(written)
    assert "romaji matcher" in capsys.readouterr().out
    # Second run is a no-op.
    assert cr.apply_patch(code) is False
    assert "already patched" in capsys.readouterr().out


def test_apply_patch_rejects_region_table_drift(code, monkeypatch):
    monkeypatch.setattr(cr, "MATCH_REGIONS", dict(list(cr.MATCH_REGIONS.items())[:2]))
    with pytest.raises(ValueError, match="regions do not match"):
        cr.apply_patch(code)


def test_apply_patch_rejects_piece_overrun(code, monkeypatch):
    start, piece = cr.MATCH_PIECES[0]
    regions = dict(cr.MATCH_REGIONS)
    regions[start] = (start + len(piece) - 4, regions[start][1])
    monkeypatch.setattr(cr, "MATCH_REGIONS", regions)
    with pytest.raises(ValueError, match="overruns"):
        cr.apply_patch(code)


def test_apply_patch_rejects_non_vanilla_body(code):
    start = cr.MATCH_PIECES[1][0]
    code[start + 8] ^= 0xFF
    with pytest.raises(ValueError, match="is not vanilla"):
        cr.apply_patch(code)


def test_main_dry_run_and_apply_hint(capsys):
    assert cr.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "matcher 0x147b3c" in out
    with pytest.raises(SystemExit, match="deploy_name_input_en"):
        cr.main([])
