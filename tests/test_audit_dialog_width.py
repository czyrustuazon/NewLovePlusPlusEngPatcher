"""The width audit reads the file the patcher ships and holds buttons to 28."""

from __future__ import annotations

import patch_names as names
from conftest import TOOLS, load_module

audit = load_module("audit_dialog_width", TOOLS / "audit_dialog_width.py")


def _script(dialogs: list[str], choices: list[int]) -> bytes:
    cmds = [names.UnknownEntry([], 0x24002, 1 << 16)]
    cmds += [names.UnknownEntry([], 0x10000 | i, 0x24002) for i in choices]
    return names.build_dbin2(1, 0, [names.DbinEntry(0, 0, names.SDL2Data(2, cmds, dialogs))])


def test_contrib_wins_and_a_choice_is_held_to_28(tmp_path):
    roots = {"contrib": tmp_path / "c", "gemini": tmp_path / "g", "eng": tmp_path / "e"}
    for root in roots.values():
        (root / "script").mkdir(parents=True)
    button = "Got it. Guess I have no choic"  # 29 columns
    talk = "x" * 30
    (roots["contrib"] / "script" / "k142.dbin2").write_bytes(_script(["Rinko", talk, button], [2]))
    (roots["gemini"] / "script" / "k142.dbin2").write_bytes(_script(["Rinko", "y" * 40, "ok"], [2]))
    results = audit.audit_stem("k142", **roots)
    assert [path.parent.parent.name for path, _ in results] == ["c"]
    hits = results[0][1]
    assert [(h["n"], h["width"], h["over"]) for h in hits] == [(3, 28, [(1, 29)])]
    assert hits[0]["fits"] == "Got it. Guess I have no\nchoic"


def test_gemini_is_only_read_for_nene_and_rinko(tmp_path):
    roots = {"contrib": tmp_path / "c", "gemini": tmp_path / "g", "eng": tmp_path / "e"}
    (roots["gemini"] / "script").mkdir(parents=True)
    (roots["gemini"] / "script" / "t001.dbin2").write_bytes(_script(["z" * 40], []))
    assert audit.audit_stem("t001", **roots) == []
