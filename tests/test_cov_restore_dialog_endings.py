"""restore_dialog_endings: edge cases, file rewrites, and the CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import SRC, TOOLS, load_module
from patch_names import DbinEntry, SDL2Data, build_dbin2

endings = load_module("restore_dialog_endings", TOOLS / "restore_dialog_endings.py")


def _blob(*groups: list[str]) -> bytes:
    return build_dbin2(1, 0, [DbinEntry(0, 0, SDL2Data(1, [], list(lines))) for lines in groups])


def _xml(lines: list[str], newline: str = "\n") -> bytes:
    body = newline.join(f"<Dialog>{line}</Dialog>" for line in lines)
    return f"<Dialogs>{newline}{body}{newline}</Dialogs>{newline}".encode("utf-8")


def test_importing_puts_src_on_the_path(monkeypatch):
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(SRC)])
    load_module("restore_dialog_endings_path", TOOLS / "restore_dialog_endings.py")
    assert sys.path[0] == str(SRC)


def test_a_closing_bracket_hides_the_japanese_ending():
    assert endings.restored_ending("「好きだ！」", "I like it") == "I like it！"


@pytest.mark.parametrize("jp", ["", "」", "▲名前▲"])
def test_japanese_with_no_text_has_no_ending_to_restore(jp):
    assert endings.restored_ending(jp, "I like it") is None


def test_a_continue_mark_is_not_part_of_the_tail():
    assert endings._tail("Hello there ▲") == "Hello there"
    assert endings._last_content("▲") == ""


@pytest.mark.parametrize(
    ("jp", "en"),
    [
        ("好き。", "Takane"),  # one word is a name or label
        ("好き。", "1 2"),  # no English to speak of
        ("好き。", "こんにちは そう"),  # still Japanese
        ("好き。", "Go on ▼"),
        ("好き。", "See note ※"),
        ("好き。", "*door slams*"),
        ("好き。", "Wait a--"),
        ("好き。", "Soooo long～"),
        ("好き。", "It ended."),
        ("好き", "No ending in the Japanese"),
    ],
)
def test_lines_that_stay_put(jp, en):
    assert endings.restored_ending(jp, en) is None


def test_a_final_comma_becomes_the_full_stop_only():
    assert endings.restored_ending("同じ気持ち。", "We feel the same,") == "We feel the same."
    assert endings.restored_ending("同じ気持ち！", "We feel the same,") is None


def test_a_comma_inside_a_quote_is_left_alone():
    assert endings.restored_ending("同じ気持ち。", 'He said "wait,"') is None


def test_an_ellipsis_earlier_in_the_japanese_softens_a_full_stop():
    assert endings.restored_ending("そう……だね。", "I guess so") == "I guess so..."


def test_rewriting_a_dbin_keeps_its_entries(tmp_path: Path):
    path = tmp_path / "a001.dbin2"
    path.write_bytes(_blob(["one", "two"], ["three"]))
    endings._write_dbin(path, ["ONE", "TWO", "THREE"])
    assert endings._dialogs_of(path) == ["ONE", "TWO", "THREE"]
    assert path.read_bytes() == _blob(["ONE", "TWO"], ["THREE"])


def test_a_dbin_that_does_not_round_trip_is_left_alone(tmp_path: Path):
    path = tmp_path / "a001.dbin2"
    raw = _blob(["one"]) + b"trailing"
    path.write_bytes(raw)
    with pytest.raises(RuntimeError, match="does not round-trip"):
        endings._write_dbin(path, ["ONE"])
    assert path.read_bytes() == raw


def test_rewriting_xml_keeps_untouched_bytes_and_crlf(tmp_path: Path):
    path = tmp_path / "a001.xml"
    path.write_bytes(_xml(["keep\r\nthis", "change me"], "\r\n"))
    assert endings._xml_dialogs(path) == ["keep\nthis", "change me"]
    endings._write_xml(path, ["keep\nthis", "new\nline"])
    assert path.read_bytes() == _xml(["keep\r\nthis", "new\r\nline"], "\r\n")


def test_a_lone_cr_counts_as_a_newline():
    assert endings._norm("a\rb") == "a\nb"


def test_xml_with_the_wrong_dialog_count_is_refused(tmp_path: Path):
    path = tmp_path / "a001.xml"
    path.write_bytes(_xml(["one"]))
    with pytest.raises(RuntimeError, match="dialog count"):
        endings._write_xml(path, ["one", "two"])


def test_a_line_count_mismatch_plans_nothing(tmp_path: Path):
    path = tmp_path / "a001.xml"
    path.write_bytes(_xml(["I like it"]))
    assert endings.plan_file(path, ["好き。", "嫌い。"]) == []
    assert endings.apply_file(path, ["好き。", "嫌い。"]) == []


def test_only_english_folders_are_scanned(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(endings, "ROOT", tmp_path)
    keep = tmp_path / "assets" / "scripts" / "t001.xml"
    gem = tmp_path / "assets" / "gemini_heroines" / "dbin2" / "a001.dbin2"
    skip = tmp_path / "assets" / "other" / "t002.xml"
    for path in (keep, gem, skip):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    assert endings._english_files() == sorted([gem, keep])


def _project(tmp_path: Path, monkeypatch) -> Path:
    """English under a fake repo root, Japanese under ``vanilla``."""
    monkeypatch.setattr(endings, "ROOT", tmp_path)
    vanilla = tmp_path / "vanilla"
    vanilla.mkdir()
    (vanilla / "a001.dbin2").write_bytes(_blob([f"行{n}。" for n in range(10)]))
    (vanilla / "a002.dbin2").write_bytes(_blob(["好き。"]))
    gem = tmp_path / "assets" / "gemini_heroines"
    (gem / "dbin2").mkdir(parents=True)
    (gem / "xml").mkdir()
    (gem / "dbin2" / "a001.dbin2").write_bytes(_blob([f"Line number {n}" for n in range(10)]))
    (gem / "xml" / "a001.xml").write_bytes(_xml(["Line number 0", *[f"Done {n}." for n in range(9)]]))
    (gem / "xml" / "a002.xml").write_bytes(_xml(["Already finished."]))
    (gem / "xml" / "z999.xml").write_bytes(_xml(["No vanilla for this"]))
    return vanilla


def test_dry_run_reports_without_writing(tmp_path: Path, monkeypatch, capsys):
    vanilla = _project(tmp_path, monkeypatch)
    dbin = tmp_path / "assets" / "gemini_heroines" / "dbin2" / "a001.dbin2"
    before = dbin.read_bytes()
    assert endings.main(["--vanilla", str(vanilla)]) == 0
    out = capsys.readouterr().out
    assert dbin.read_bytes() == before
    assert "… 2 more" in out
    assert "[endings] would change 11 line(s) in 2 file(s)" in out


def test_apply_writes_both_formats(tmp_path: Path, monkeypatch, capsys):
    vanilla = _project(tmp_path, monkeypatch)
    gem = tmp_path / "assets" / "gemini_heroines"
    assert endings.main(["--apply", "--vanilla", str(vanilla)]) == 0
    assert "[endings] wrote 11 line(s) in 2 file(s)" in capsys.readouterr().out
    assert endings._dialogs_of(gem / "dbin2" / "a001.dbin2")[0] == "Line number 0."
    assert endings._xml_dialogs(gem / "xml" / "a001.xml")[0] == "Line number 0."
    assert endings.main(["--apply", "--vanilla", str(vanilla)]) == 0
    assert "[endings] wrote 0 line(s) in 0 file(s)" in capsys.readouterr().out


def test_missing_vanilla_scripts_are_an_error(tmp_path: Path, capsys):
    assert endings.main(["--vanilla", str(tmp_path / "gone")]) == 1
    assert "vanilla scripts missing" in capsys.readouterr().err
