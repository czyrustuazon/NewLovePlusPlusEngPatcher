"""Branch coverage for patch_spotpass_skip's site checks and upgrade paths.

The vanilla / patched predicates are long chains of "this site must hold X".
Each one is covered by flipping a single byte at every address the module
names and checking the predicate rejects the copy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import SRC, load_module
from test_patch_spotpass_skip import _blob, sp


def _addresses() -> list[int]:
    """Every code.bin offset the module names (constants, site tuples, JT slots)."""
    out: set[int] = set()
    for name, value in vars(sp).items():
        if name.startswith("_") or not name.isupper():
            continue
        if isinstance(value, int) and 0x1000 <= value < 0x700000:
            out.add(value)
        elif isinstance(value, (tuple, list, dict, frozenset, set)):
            out.update(v for v in value if isinstance(v, int) and 0x1000 <= v < 0x700000)
    out.update(sp._title_jt_off(s) for s in sp.TITLE_JT_SLOTS)
    out.update(sp._14ed_jt_off(s) for s in sp._14ED_APPLY_SLOTS)
    return sorted(out)


def _vanilla() -> bytearray:
    return _blob(sp.VANILLA_MOVEQ)


def _patched() -> bytearray:
    data = _vanilla()
    assert sp.apply_patch(data)
    return data


@pytest.fixture(autouse=True)
def quiet(capsys):
    yield
    capsys.readouterr()


@pytest.mark.parametrize("pred, build", [
    (sp._title_vanilla, _vanilla),
    (sp._title_patched, _patched),
    (sp._14ed_vanilla, _vanilla),
    (sp._14ed_patched, _patched),
])
def test_predicates_reject_any_changed_site(pred, build):
    base = build()
    assert pred(base)
    rejected = 0
    for addr in _addresses():
        if addr >= len(base):
            continue
        data = bytearray(base)
        data[addr] ^= 0xFF
        rejected += not pred(data)
    assert rejected > 10


def test_module_adds_src_to_path(monkeypatch):
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p).resolve() != SRC])
    fresh = load_module("patch_spotpass_skip_fresh", SRC / "patch_spotpass_skip.py")
    assert str(SRC) in sys.path and fresh.NOP == sp.NOP


@pytest.mark.parametrize("const, builder, msg", [
    ("STATE0_LEN", "build_state0_hide", "state0 hide"),
    ("TITLE_STUB_LEN", "build_title_dismiss_stub", "title dismiss stub"),
    ("MGR_RELEASE_LEN", "build_title_mgr_release", "title manager release"),
    ("TITLE_LOCK_RELEASE_LEN", "build_title_lock_release", "lock"),
])
def test_cave_builders_check_their_length(monkeypatch, const, builder, msg):
    monkeypatch.setattr(sp, const, 1)
    with pytest.raises(ValueError, match=msg):
        getattr(sp, builder)()


def test_short_blob_is_neither():
    assert not sp.is_vanilla(b"\0" * 16)
    assert not sp.is_patched(b"\0" * 16)


def test_restore_namecard_setup_needs_a_patched_rest():
    data = _vanilla()
    data[sp.ADDR_14ED_ST1_DATA : sp.ADDR_14ED_ST1_DATA + 4] = sp.OLD_14ED_ST1_SKIP
    assert sp._restore_namecard_setup(data) is False  # the rest is vanilla


def test_upgrade_namecard_bars():
    data = _patched()
    data[0x0014EFE8 : 0x0014EFE8 + 4] = sp.PATCHED_14ED_TO_APPLY
    assert sp.apply_patch(data) is True
    assert data[0x0014EFE8 : 0x0014EFE8 + 4] == sp.PATCHED_14ED_NAMECARD
    vanilla = _vanilla()
    vanilla[0x0014EFE8 : 0x0014EFE8 + 4] = sp.PATCHED_14ED_TO_APPLY
    assert sp._upgrade_namecard_bars(vanilla) is False


def test_upgrade_title_home_lock_rejects_unknown_lock():
    data = _patched()
    data[sp.ADDR_TITLE_ST8_LOCK : sp.ADDR_TITLE_ST8_LOCK + 4] = b"\x12\x34\x56\x78"
    assert sp._upgrade_title_home_lock(data) is False


def test_upgrade_title_mgr_release_guards():
    data = _patched()
    data[sp.ADDR_TITLE_STUB : sp.ADDR_TITLE_STUB + sp.TITLE_STUB_LEN] = sp.OLD_TITLE_STUB
    assert sp._upgrade_title_mgr_release(data) is False  # manager cave is not the old one
    data[sp.ADDR_TITLE_MGR_RELEASE : sp.ADDR_TITLE_MGR_RELEASE + sp.MGR_RELEASE_LEN] = sp.OLD_TITLE_HIDE_CAVE
    data[sp.ADDR_JT0] ^= 0xFF  # and the rest is not patched either
    assert sp._upgrade_title_mgr_release(data) is False


def test_apply_finishes_a_skip_without_open_warn():
    data = _patched()
    data[sp.ADDR_OPEN_WARN : sp.ADDR_OPEN_WARN + 4] = sp.VANILLA_OPEN_WARN
    assert sp.apply_patch(data) is True
    assert sp.is_patched(data)


def test_revert_rejects_unknown_bytes():
    data = _vanilla()
    data[sp.ADDR_MOVEQ] ^= 0xFF
    with pytest.raises(ValueError, match="cannot revert"):
        sp.revert_patch(data)
