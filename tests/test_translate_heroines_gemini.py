"""fix-pronoun re-translates Gemini lines that kept ● (the player's "I")."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import TOOLS, load_module

th = load_module("translate_heroines_gemini", TOOLS / "translate_heroines_gemini.py")
names = th.parse_dbin2.__globals__  # patch_names module namespace


def _entries(dialogs: list[str]):
    sdl2 = names["SDL2Data"](key=2, unknown=[], dialogs=dialogs)
    return [names["DbinEntry"](0, 0, sdl2)]


def _setup(tmp_path: Path, jp: list[str], en: list[str], packs=("NLP_01", "script")):
    vanilla = tmp_path / "vanilla"
    vanilla.mkdir(parents=True)
    (vanilla / "k093.dbin2").write_bytes(th.build_dbin2(1, 0, _entries(jp)))
    out = tmp_path / "gemini"
    (out / "xml").mkdir(parents=True)
    (out / "xml" / "k093.xml").write_text(
        th.entries_to_xml(1, 0, _entries(en)), encoding="utf-8"
    )
    for pack in packs:
        slot = out / "dbin2" / pack / "k093.dbin2"
        slot.parent.mkdir(parents=True)
        slot.write_bytes(b"old")
    return vanilla, out


JP = ["●は好きじゃないな", "そうなんだ。", "●？", "●が悪かったよ"]
EN = ["●'s not a fan.", "I see.", "●？", "● was in the wrong."]


def test_targets_are_lines_whose_english_kept_the_pronoun(tmp_path: Path):
    _vanilla, out = _setup(tmp_path, JP, EN)
    assert th.pronoun_targets(out / "xml", ["rinko"]) == {"k093": [(0, 0), (0, 2), (0, 3)]}
    assert th.pronoun_targets(out / "xml", ["nene"]) == {}


def test_fix_pronoun_rewrites_xml_and_every_shipped_pack(tmp_path: Path, monkeypatch, capsys):
    vanilla, out = _setup(tmp_path, JP, EN)
    sent: list[list[tuple[str, bool]]] = []

    def fake_translate(client, model, items, **kwargs):
        sent.append([(it.source, it.need) for it in items])
        fixed = {"●は好きじゃないな": "I'm not a fan.", "●が悪かったよ": None}
        return [
            th.TranslateResult(
                it.index,
                it.source,
                fixed[it.source] if it.need else it.source,
                error="kept_pronoun" if it.need and fixed[it.source] is None else "",
            )
            for it in items
        ]

    monkeypatch.setattr(th, "translate_prepared", fake_translate)
    monkeypatch.setattr(th, "make_gemini_client", lambda key: None)
    monkeypatch.setattr(th, "load_gemini_api_key", lambda key=None: "k")
    args = th.build_parser().parse_args(
        ["fix-pronoun", "--out", str(out), "--vanilla-script", str(vanilla), "--heroine", "rinko"]
    )
    assert args.func(args) == 1  # one line rejected

    # JP for the targets the model can translate; English context for the rest.
    assert sent == [
        [
            ("●は好きじゃないな", True),
            ("I see.", False),
            ("●？", False),
            ("●が悪かったよ", True),
        ]
    ]
    _k, _u, entries = th.xml_to_entries(out / "xml" / "k093.xml")
    assert entries[0].sdl2.dialogs == ["I'm not a fan.", "I see.", "Me？", "● was in the wrong."]
    for pack in ("NLP_01", "script"):
        blob = (out / "dbin2" / pack / "k093.dbin2").read_bytes()
        assert th.parse_dbin2(blob)[2][0].sdl2.dialogs == entries[0].sdl2.dialogs
    assert not (out / "dbin2" / "NLP_02").exists()
    mapping = th.load_translation_map(out / "translations.json")
    assert mapping == {"●は好きじゃないな": "I'm not a fan."}
    rejected = json.loads((out / "pronoun_rejected.json").read_text(encoding="utf-8"))
    assert rejected == [{"stem": "k093", "jp": "●が悪かったよ", "error": "kept_pronoun"}]
    assert "fixed=2 rejected=1" in capsys.readouterr().out


def test_fix_pronoun_dry_run_and_limit(tmp_path: Path, capsys):
    vanilla, out = _setup(tmp_path, JP, EN)
    args = th.build_parser().parse_args(
        ["fix-pronoun", "--out", str(out), "--dry-run", "--limit", "1"]
    )
    assert args.func(args) == 0
    text = capsys.readouterr().out
    assert "lines with ●: 3 in 1 scripts" in text
    assert "k093: 3 lines" in text
    assert "dry-run" in text


def test_fix_pronoun_reports_a_misaligned_script(tmp_path: Path, monkeypatch, capsys):
    vanilla, out = _setup(tmp_path, JP[:2], EN)
    monkeypatch.setattr(th, "make_gemini_client", lambda key: None)
    monkeypatch.setattr(th, "load_gemini_api_key", lambda key=None: "k")
    args = th.build_parser().parse_args(
        ["fix-pronoun", "--out", str(out), "--vanilla-script", str(vanilla)]
    )
    assert args.func(args) == 1
    assert "do not line up" in capsys.readouterr().out
    assert (out / "dbin2" / "script" / "k093.dbin2").read_bytes() == b"old"


def test_fix_pronoun_with_nothing_to_do(tmp_path: Path):
    vanilla, out = _setup(tmp_path, ["そうなんだ。"], ["I see."])
    args = th.build_parser().parse_args(["fix-pronoun", "--out", str(out)])
    assert args.func(args) == 0
    with pytest.raises(SystemExit):
        th.cmd_fix_pronoun(
            th.build_parser().parse_args(
                ["fix-pronoun", "--out", str(_setup(tmp_path / "b", JP, EN)[1]),
                 "--vanilla-script", str(tmp_path / "missing")]
            )
        )


def test_save_json_retries_a_locked_target(tmp_path: Path, monkeypatch):
    calls: list[int] = []
    real = th.os.replace

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise OSError(22, "Invalid argument")
        real(src, dst)

    monkeypatch.setattr(th.os, "replace", flaky)
    monkeypatch.setattr(th.time, "sleep", lambda s: None)
    target = tmp_path / "translations.json"
    th.save_json(target, {"translations": {"a": "b"}})
    assert json.loads(target.read_text(encoding="utf-8")) == {"translations": {"a": "b"}}
    assert not (tmp_path / "translations.json.tmp").exists()

    monkeypatch.setattr(th.os, "replace", lambda s, d: (_ for _ in ()).throw(OSError(22, "x")))
    with pytest.raises(OSError):
        th.save_json(target, {}, attempts=2)
