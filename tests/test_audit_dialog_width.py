"""The width audit reads the file the patcher ships and holds buttons to 28."""

from __future__ import annotations

import io
import sys

import pytest

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


def test_a_pack_identical_to_the_one_before_is_read_once(tmp_path):
    roots = {"contrib": tmp_path / "c", "gemini": tmp_path / "g", "eng": tmp_path / "e"}
    blob = _script(["Hi"], [])
    for pack in audit.PACKS:
        (roots["eng"] / pack).mkdir(parents=True)
        (roots["eng"] / pack / "t001.dbin2").write_bytes(blob)
    results = audit.audit_stem("t001", **roots)
    assert [(path.parent.name, found) for path, found in results] == [("script", [])]


def test_the_tool_puts_src_on_the_path_when_run_on_its_own(monkeypatch):
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(audit.SRC)])
    load_module("audit_dialog_width_alone", TOOLS / "audit_dialog_width.py")
    assert str(audit.SRC) in sys.path


def _project(tmp_path, monkeypatch):
    roots = {"contrib": tmp_path / "c", "gemini": tmp_path / "g", "eng": tmp_path / "e"}
    (roots["contrib"] / "script").mkdir(parents=True)
    (roots["eng"] / "script").mkdir(parents=True)
    (roots["contrib"] / "script" / "k007.dbin2").write_bytes(_script(["x" * 31, "fine"], []))
    (roots["eng"] / "script" / "t001.dbin2").write_bytes(_script(["fine"], []))
    real = audit.audit_stem
    monkeypatch.setattr(audit, "audit_stem", lambda stem: real(stem, **roots))
    monkeypatch.setattr(audit, "CONTRIB", roots["contrib"])


def test_main_lists_each_too_wide_line_and_fails(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    assert audit.main(["t001", "zzz", "--contrib"]) == 1
    out = capsys.readouterr().out
    assert "[width] t001 (e/script): ok" in out
    assert "[width] zzz: no shipped script" in out
    assert "[width] k007 (c/script): 1 line(s) too wide" in out
    assert "#1 talk 30 max, line 1: 31" in out
    assert "[width] 1 line(s) too wide" in out


def test_main_passes_when_everything_fits(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert audit.main(["t001"]) == 0
    assert "[width] 0 line(s) too wide" in sys.stdout.getvalue()


def test_main_needs_a_stem(capsys):
    with pytest.raises(SystemExit):
        audit.main([])
    assert "name at least one stem" in capsys.readouterr().err
