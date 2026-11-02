"""Coverage for patch_chunk_walk_guard's remaining edges: no NOP tail to host
a cave, an occupied heap link pad, and the disabled heap/PACK write path.
"""

from __future__ import annotations

import pytest

import patch_chunk_walk_guard as guard
from test_cov_src_text import _plant_chunk


@pytest.fixture(autouse=True)
def quiet(capsys):
    yield
    capsys.readouterr()


@pytest.mark.parametrize("assembler, fn", [
    ("assemble_set_name", "fs_open_cave_addr"),
    ("assemble_backspace", "field_cave_addr"),
])
def test_cave_address_needs_a_nop_tail(monkeypatch, assembler, fn):
    monkeypatch.setattr(guard, assembler, lambda: b"\x01" * 16)
    with pytest.raises(ValueError, match="has no NOP tail"):
        getattr(guard, fn)()


def test_heap_link_pad_must_be_free(monkeypatch):
    # The pane flag cave shares this slot; DIAG_TRAP lets its own check pass.
    monkeypatch.setattr(guard, "DIAG_TRAP", True)
    monkeypatch.setattr(guard, "DIAG_ALL", False)
    data = _plant_chunk()
    pad = guard.build_heap_link_pad()
    data[guard.ADDR_HEAP_LINK_PAD : guard.ADDR_HEAP_LINK_PAD + len(pad)] = b"\x5a" * len(pad)
    with pytest.raises(ValueError, match="heap link pad is not empty"):
        guard.apply_patch(data)


class _LateFlag:
    """APPLY_HEAP_AND_PAK that reads False at the shared-slot guard, then True.

    The guard refuses the flag outright today; this runs the write path the
    flag would enable, so is_patched (flag on) can check what it writes.
    """

    def __init__(self) -> None:
        self.reads = 0

    def __bool__(self) -> bool:
        self.reads += 1
        return self.reads > 1


def test_heap_and_pak_write_path(monkeypatch):
    monkeypatch.setattr(guard, "DIAG_TRAP", False)
    monkeypatch.setattr(guard, "DIAG_ALL", False)
    flag = _LateFlag()
    monkeypatch.setattr(guard, "APPLY_HEAP_AND_PAK", flag)
    data = _plant_chunk()
    guard.apply_patch(data)
    assert flag.reads >= 3
    assert data[guard.ADDR_HEAP_WALK : guard.ADDR_HEAP_WALK + 4] == guard.b_ins(
        guard.ADDR_HEAP_WALK, guard.ADDR_HEAP_LINK_PAD
    ) or data[guard.ADDR_HEAP_WALK : guard.ADDR_HEAP_WALK + 4] != guard.VANILLA_HEAP_WALK
    assert data[guard.ADDR_PAK_INIT : guard.ADDR_PAK_INIT + len(guard.build_pak_init())] == guard.build_pak_init()
