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
    for site, orig in (
        (cr.SITE_MISS01, cr.ORIG_MISS01),
        (cr.SITE_MISS02, cr.ORIG_MISS02),
        (cr.SITE_PICK01, cr.ORIG_PICK01),
        (cr.SITE_PICK02, cr.ORIG_PICK02),
    ):
        data[site : site + 4] = orig
    return data


def test_apply_patch_writes_matcher_cave_and_hooks(code, capsys):
    base = cr.cave_addr()
    blob, labs = cr.build_blob(base=base)
    assert cr.apply_patch(code) is True
    assert len(code) == TEXT_PAGE_END
    assert cr.is_patched(code)
    assert bytes(code[base : base + len(blob)]) == blob
    for start, piece in cr.MATCH_PIECES:
        assert bytes(code[start : start + len(piece)]) == piece
    assert bytes(code[cr.SITE_MISS01 : cr.SITE_MISS01 + 4]) == cr.b_cond(0, cr.SITE_MISS01, labs["typed01"])
    assert bytes(code[cr.SITE_PICK02 : cr.SITE_PICK02 + 4]) == cr.bl(cr.SITE_PICK02, cr.NLPP_CALL_PICK)
    assert "romaji matcher" in capsys.readouterr().out
    # Second run is a no-op.
    assert cr.apply_patch(code) is False
    assert "already patched" in capsys.readouterr().out


def test_apply_patch_rejects_cave_over_commu_header(code, monkeypatch):
    monkeypatch.setattr(cr, "ADDR_COMMU_HEADER_CAVE", cr.cave_addr())
    with pytest.raises(ValueError, match="overlaps commu header"):
        cr.apply_patch(code)


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


def test_apply_patch_rejects_unexpected_called_list_code(code):
    code[cr.SITE_PICK01] ^= 0xFF
    with pytest.raises(ValueError, match="unexpected Called list code"):
        cr.apply_patch(code)


def test_apply_patch_rejects_dirty_cave(code):
    code[cr.cave_addr() + 4] = 1
    with pytest.raises(ValueError, match="not empty pad"):
        cr.apply_patch(code)


def test_assemble_rejects_unknown_item():
    with pytest.raises(ValueError):
        cr._assemble(0x1000, [("bogus",)])


def test_main_dry_run_and_apply_hint(capsys):
    assert cr.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "call-romaji" in out and "matcher 0x147b3c" in out
    with pytest.raises(SystemExit, match="deploy_name_input_en"):
        cr.main([])
