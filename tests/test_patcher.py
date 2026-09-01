"""Tests for patcher.py helpers."""

from __future__ import annotations

from pathlib import Path

from conftest import SRC, load_module

patcher = load_module("patcher", SRC / "patcher.py")


def test_jp_re_detects_japanese():
    assert patcher.JP_RE.search("こんにちは")
    assert not patcher.JP_RE.search("Hello Takane")


def test_dialog_texts_from_xml(tmp_path: Path):
    xml = tmp_path / "sample.xml"
    xml.write_text(
        '<?xml version="1.0"?><root><Dialog>Line A</Dialog><Dialog>Line B</Dialog></root>',
        encoding="utf-8",
    )
    assert patcher._dialog_texts(xml) == ["Line A", "Line B"]
