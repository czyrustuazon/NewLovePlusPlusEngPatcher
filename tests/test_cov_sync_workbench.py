"""sync_workbench: line rules, XML alignment, and the full kit rebuild."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import SRC, TOOLS, load_module
from patch_names import DbinEntry, SDL2Data, build_dbin2

sync = load_module("sync_workbench", TOOLS / "sync_workbench.py")


def _entries(lines: list[str]) -> list[DbinEntry]:
    return [DbinEntry(0, 0, SDL2Data(1, [], list(lines)))]


def _blob(lines: list[str]) -> bytes:
    return build_dbin2(1, 0, _entries(lines))


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _xml(path: Path, lines: list[str]) -> Path:
    return _write(path, sync.entries_to_xml(1, 0, _entries(lines)).encode("utf-8"))


def _map(gemini: Path, table: object) -> Path:
    path = gemini / "translations.json"
    path.write_text(
        json.dumps({"translations": table}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


@pytest.mark.parametrize("folder", [str(SRC), str(TOOLS)])
def test_importing_puts_src_and_tools_on_the_path(monkeypatch, folder):
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != folder])
    load_module("sync_workbench_path", TOOLS / "sync_workbench.py")
    assert folder in sys.path


@pytest.mark.parametrize(
    ("text", "locked"),
    [
        ("", False),
        ("plain", False),
        ("▲高嶺＊＊▲", True),
        ("▲高嶺＊＊▲！", True),
        ("▲苗字▲", True),
        ("▲x", False),
        ("▲高嶺＊＊", True),
        ("▲苗字▲ Yes", True),
        ("▲苗字▲ 好きです", False),
        ("○○○", True),
        ("……！", True),
    ],
)
def test_locked_lines(text, locked):
    assert sync.is_locked(text) is locked


@pytest.mark.parametrize(
    ("text", "needed"),
    [
        ("こんにちは", True),
        ("Hello", False),
        ("○○○", False),
        ("▲苗字▲……！？ そ", True),
        ("▲苗字▲ …… ▼", False),
        ("▲苗字▲♪", False),
        ("ー・ー", False),
    ],
)
def test_scripts_kit_translation_rule(text, needed):
    assert sync.needs_translation(text) is needed


def test_strings_kit_treats_punctuation_as_finished():
    assert sync.string_needs_translation("……") is False
    assert sync.string_needs_translation("体育") is True
    assert sync.string_needs_translation("Gym") is False
    assert sync.is_punct_only_string("") is False


def test_a_suggestion_must_keep_tokens_and_marks():
    assert sync.safe_suggestion("▲苗字▲は好き", "▲苗字▲ likes it")
    assert not sync.safe_suggestion("▲苗字▲", "Name")  # locked line
    assert not sync.safe_suggestion("▲苗字▲は好き", "likes it")
    assert not sync.safe_suggestion("好き▼", "Likes it")
    assert not sync.safe_suggestion("好き※", "Likes it")
    assert sync.tokens_in(None) == []


def test_seeded_dialogs_ignore_a_gemini_pass_of_the_wrong_length():
    assert sync.seeded_dialogs(["好き"], ["Likes", "extra"]) == ["好き"]
    assert sync.seeded_dialogs(["好き", "▲苗字▲"], ["Likes", "Name"]) == ["Likes", "▲苗字▲"]


def test_held_lines_need_review_and_bad_indexes_drop():
    item = {"kind": "script", "stem": "k007", "unreviewed": [9]}
    sync.fill_script_item(
        item,
        vanilla=["好き", "嫌い"],
        working=["Likes", "Hates"],
        gemini=["Likes", "Hates"],
        layer="contrib",
        unreviewed=[1, 1, 7, -1, "2"],
    )
    assert item["unreviewed"] == [1]
    assert item["jp_dialogs"] == 2  # both still equal the Gemini pass
    sync.fill_script_item(item, vanilla=None, working=["Hi"], gemini=None, layer="manaka")
    assert "unreviewed" not in item
    assert "gemini_dialogs" not in item
    assert item["jp_dialogs"] == 0


def test_a_short_gemini_list_is_dropped():
    item = {"kind": "script", "stem": "a001", "gemini_dialogs": ["x"]}
    sync.fill_script_item(
        item, vanilla=["好き", "嫌い"], working=["好き", "Hates"], gemini=["x"], layer="gemini"
    )
    assert "gemini_dialogs" not in item
    assert item["jp_dialogs"] == 1


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"translations": {"a": "A", "n": 1}}, {"a": "A"}),
        ({"a": "A"}, {"a": "A"}),
        ({"translations": []}, {}),
        ([], {}),
    ],
)
def test_translation_keys(tmp_path: Path, body, expected):
    path = tmp_path / "t.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    assert sync.translation_keys(path) == expected


def test_key_forms_treat_the_game_newline_as_a_newline():
    assert sync._key_forms("plain") == ("plain",)
    assert sync.already_translated("a\nb", {"a◙b": "x"})
    assert sync.already_translated("a◙b", {"a\nb": "x"})
    assert not sync.already_translated("a", {})


def test_refresh_trb_items_counts_every_drop():
    items = [
        {"kind": "sms", "index": 0},
        {"kind": "trb", "stri_index": "x"},
        {"kind": "trb"},
        {"kind": "trb", "stri_index": 99},
        {"kind": "trb", "stri_index": 1},
        {"kind": "trb", "stri_index": 2},
        {"kind": "trb", "stri_index": 3, "baseline": "体育", "jp_key": "体育", "gemini": "Gym"},
    ]
    kept, stats = sync.refresh_trb_items(
        items, {1: "翻訳済み", 2: "……", 3: "体育"}, {"翻訳済み": "Done"}
    )
    assert [item.get("stri_index") for item in kept] == [None, 3]
    assert "gemini" not in kept[1]
    assert stats == {
        "trb_kept": 1,
        "trb_dropped": 5,
        "trb_refreshed": 0,
        "trb_missing_from_vanilla": 1,
    }


def test_patcher_working_falls_through_each_layer(tmp_path: Path, monkeypatch):
    gemini = tmp_path / "gemini"
    eng = tmp_path / "eng"
    vanilla = tmp_path / "vanilla"
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    kwargs = {"vanilla_dir": vanilla, "eng_root": eng, "gemini_root": gemini}
    monkeypatch.setattr(sync, "resolve_script_source", lambda _p, _s, _r: (None, "jp"))

    assert sync.patcher_working("t001", **kwargs) == (None, "missing")
    assert sync.patcher_working("t001", vanilla_dir=None, eng_root=eng, gemini_root=gemini) == (
        None,
        "missing",
    )
    _write(vanilla / "t001.dbin2", _blob(["日本語"]))
    assert sync.patcher_working("t001", **kwargs) == (["日本語"], "jp")

    picked = _write(eng / "script" / "t001.dbin2", _blob(["Rebuilt"]))
    monkeypatch.setattr(sync, "resolve_script_source", lambda _p, _s, _r: (picked, "manaka"))
    assert sync.patcher_working("t001", **kwargs) == (["Rebuilt"], "manaka")

    # A t* stem never reads the Gemini pass. An a* stem does.
    _write(gemini / "dbin2" / "script" / "t001.dbin2", _blob(["Machine"]))
    assert sync.patcher_working("t001", **kwargs) == (["Rebuilt"], "manaka")
    _write(gemini / "dbin2" / "script" / "a001.dbin2", _blob(["Machine"]))
    assert sync.patcher_working("a001", **kwargs) == (["Machine"], "gemini")

    _write(
        tmp_path / "assets" / "script_contrib" / "dbin2" / "script" / "a001.dbin2",
        _blob(["Reviewed"]),
    )
    assert sync.patcher_working("a001", **kwargs) == (["Reviewed"], "contrib")


def test_align_makes_xml_map_and_manifest_match_the_shipped_dbin(tmp_path: Path):
    gemini = tmp_path / "gemini"
    script = gemini / "dbin2" / "script"
    vanilla = tmp_path / "vanilla"
    _write(script / "a001.dbin2", _blob(["New one", "Same"]))
    _xml(gemini / "xml" / "a001.xml", ["Old one", "Same"])
    _write(script / "a002.dbin2", _blob(["Lagged", "behind"]))
    _xml(gemini / "xml" / "a002.xml", ["Different length"])
    _write(script / "a003.dbin2", _blob(["Created"]))
    _write(script / "a004.dbin2", _blob(["In sync"]))
    _xml(gemini / "xml" / "a004.xml", ["In sync"])
    _write(script / "a005.dbin2", _blob(["No vanilla"]))
    _xml(gemini / "xml" / "a005.xml", ["No vanilla"])
    _write(script / "a006.dbin2", _blob(["Wrong", "count"]))
    _xml(gemini / "xml" / "a006.xml", ["Wrong", "count"])
    _write(vanilla / "a001.dbin2", _blob(["古い", "同じ"]))
    _write(vanilla / "a006.dbin2", _blob(["古い"]))
    map_path = _map(gemini, {"古い": "Old one", "同じ": "Same", "未使用": "Unused"})
    (gemini / "stems.json").write_text(
        json.dumps({"stems": ["a001"], "count": 1}), encoding="utf-8"
    )

    report = sync.align_gemini_xml(gemini, vanilla)

    assert report == {
        "xml_updated": 1,
        "xml_created": 1,
        "xml_created_stems": ["a003"],
        "map_keys": 1,
        "map_conflicts": 0,
        "xml_length_mismatch": ["a002"],
    }
    assert sync._xml_dialogs(gemini / "xml" / "a001.xml") == ["New one", "Same"]
    assert sync._xml_dialogs(gemini / "xml" / "a003.xml") == ["Created"]
    assert b"\r\n" in (gemini / "xml" / "a003.xml").read_bytes()
    assert json.loads(map_path.read_text(encoding="utf-8"))["translations"] == {
        "古い": "New one",
        "同じ": "Same",
        "未使用": "Unused",
    }
    stems = json.loads((gemini / "stems.json").read_text(encoding="utf-8"))
    assert stems == {"stems": ["a001", "a003"], "count": 2}


def test_align_keeps_existing_crlf_output(tmp_path: Path, monkeypatch):
    gemini = tmp_path / "gemini"
    _write(gemini / "dbin2" / "script" / "a001.dbin2", _blob(["Hi"]))
    monkeypatch.setattr(sync, "entries_to_xml", lambda *_a: "<x>\r\n</x>\r\n")
    assert sync.align_gemini_xml(gemini, None)["xml_created"] == 1
    assert (gemini / "xml" / "a001.xml").read_bytes() == b"<x>\r\n</x>\r\n"


def test_align_without_a_map_or_vanilla_only_touches_xml(tmp_path: Path):
    gemini = tmp_path / "gemini"
    _write(gemini / "dbin2" / "script" / "a001.dbin2", _blob(["Hi"]))
    report = sync.align_gemini_xml(gemini, None)
    assert report["xml_created"] == 1 and report["map_keys"] == 0
    assert not (gemini / "translations.json").exists()


def test_align_ignores_a_map_that_is_not_a_table(tmp_path: Path):
    gemini = tmp_path / "gemini"
    _write(gemini / "dbin2" / "script" / "a001.dbin2", _blob(["Hi"]))
    _xml(gemini / "xml" / "a001.xml", ["Hi"])
    _write(tmp_path / "vanilla" / "a001.dbin2", _blob(["やあ"]))
    _map(gemini, ["not", "a", "table"])
    assert sync.align_gemini_xml(gemini, tmp_path / "vanilla")["map_keys"] == 0


def test_a_map_value_written_differently_is_left_alone(tmp_path: Path):
    gemini = tmp_path / "gemini"
    _write(gemini / "dbin2" / "script" / "a001.dbin2", _blob(["New"]))
    _xml(gemini / "xml" / "a001.xml", ["New"])
    _write(tmp_path / "vanilla" / "a001.dbin2", _blob(["古い"]))
    path = gemini / "translations.json"
    raw = '{"translations": {"古い":"Old"}}\n'  # no space: the splice cannot find it
    path.write_text(raw, encoding="utf-8")
    assert sync.align_gemini_xml(gemini, tmp_path / "vanilla")["map_keys"] == 0
    assert path.read_text(encoding="utf-8") == raw


def test_pointing_the_map_updates_every_key_form():
    jp = "一\n二"
    mapping = {jp: "Old", "一◙二": "Old", "別": "Other"}
    text = json.dumps(mapping, ensure_ascii=False)
    text, mapping, wrote = sync._point_map_at_shipped(text, mapping, jp, "New")
    assert wrote == 2
    assert json.loads(text)[jp] == "New" and json.loads(text)["一◙二"] == "New"
    _text, _mapping, wrote = sync._point_map_at_shipped(text, mapping, jp, "New")
    assert wrote == 0
    assert sync._point_map_at_shipped("{}", {"別": "x"}, "無い", "New")[2] == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, set()),
        ("{broken", set()),
        ("[]", set()),
        ('{"stems": "a001"}', set()),
        ('{"stems": ["a001", 2]}', {"a001", "2"}),
    ],
)
def test_proofread_manifest(tmp_path: Path, monkeypatch, raw, expected):
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    if raw is not None:
        _write(tmp_path / "assets" / "gemini_heroines" / "proofread.json", raw.encode("utf-8"))
    assert sync._proofread_stems() == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, {}),
        ("{broken", {}),
        ("[]", {}),
        ('{"k007": [1, "x", 2], "a000": "all"}', {"k007": [1, 2]}),
    ],
)
def test_unreviewed_manifest(tmp_path: Path, monkeypatch, raw, expected):
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    if raw is not None:
        _write(tmp_path / "assets" / "script_contrib" / "unreviewed.json", raw.encode("utf-8"))
    assert sync._unreviewed_map() == expected


def _kit_project(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    def rebuilt(_pack: str, stem: str, root: Path) -> tuple[Path | None, str]:
        path = root / "script" / f"{stem}.dbin2"
        return (path, "manaka") if path.is_file() else (None, "jp")

    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "resolve_script_source", rebuilt)
    gemini = tmp_path / "gemini"
    eng = tmp_path / "eng"
    vanilla = tmp_path / "vanilla"
    machine = gemini / "dbin2" / "script"
    contrib = tmp_path / "assets" / "script_contrib" / "dbin2" / "script"
    _write(machine / "a001.dbin2", _blob(["Machine"]))
    _write(vanilla / "a001.dbin2", _blob(["機械"]))
    _write(machine / "a002.dbin2", _blob(["Machine two"]))
    _write(contrib / "a002.dbin2", _blob(["Human two"]))
    _write(vanilla / "a002.dbin2", _blob(["機械"]))
    _write(contrib / "a003.dbin2", _blob(["Signed off"]))
    _write(machine / "a003.dbin2", _blob(["Machine three"]))
    _write(vanilla / "a003.dbin2", _blob(["機械"]))
    _write(eng / "script" / "t001.dbin2", _blob(["Rebuilt", "extra"]))
    _write(vanilla / "t001.dbin2", _blob(["一行"]))
    _write(contrib / "a004.dbin2", _blob(["Contrib no gemini"]))
    _write(eng / "script" / "t002.dbin2", _blob(["No vanilla"]))
    _write(tmp_path / "assets" / "gemini_heroines" / "proofread.json", b'{"stems": ["a003"]}')
    _write(
        tmp_path / "assets" / "script_contrib" / "unreviewed.json",
        b'{"a002": [0], "a003": [0]}',
    )
    return {"gemini": gemini, "eng": eng, "vanilla": vanilla}


def test_script_embed_tracks_layers_and_review_state(tmp_path: Path, monkeypatch):
    paths = _kit_project(tmp_path, monkeypatch)
    stems = ["a001", "a002", "a003", "a004", "t001", "t002", "gone"]
    data = {
        "items": [{"kind": "script", "stem": s} for s in stems] + ["stray row", {"kind": "other"}]
    }
    counts = sync.sync_script_embed(
        data, vanilla_dir=paths["vanilla"], eng_root=paths["eng"], gemini_root=paths["gemini"]
    )
    by_stem = {
        item["stem"]: item for item in data["items"] if isinstance(item, dict) and "stem" in item
    }
    assert by_stem["a002"]["gemini_dialogs"] == ["Machine two"]
    assert by_stem["a002"]["unreviewed"] == [0]
    assert "gemini_dialogs" not in by_stem["a003"]  # proofread
    assert "unreviewed" not in by_stem["a003"]
    assert "gemini_dialogs" not in by_stem["a004"]
    assert counts["missing"] == 1
    assert counts["unaligned"] == 3  # a004, t001, t002
    assert counts["layer_gemini"] == 1
    assert counts["layer_contrib"] == 3
    assert counts["layer_manaka"] == 2
    assert counts["scripts"] == 7
    assert data["stats"]["scripts"] == 7
    assert data["stats"]["jp_dialogs"] >= 1
    assert data["synced"].endswith("Z")


def test_script_embed_tolerates_a_stats_field_that_is_not_a_box(tmp_path: Path, monkeypatch):
    paths = _kit_project(tmp_path, monkeypatch)
    data = {"items": [], "stats": []}
    counts = sync.sync_script_embed(
        data, vanilla_dir=None, eng_root=paths["eng"], gemini_root=paths["gemini"]
    )
    assert counts["scripts"] == 0


def test_script_embed_counts_edit_boxes_new_and_old(tmp_path: Path, monkeypatch):
    paths = _kit_project(tmp_path, monkeypatch)
    data = {"items": [{"kind": "script", "stem": "a002", "dialogs": ["stale"]}]}
    counts = sync.sync_script_embed(
        data, vanilla_dir=paths["vanilla"], eng_root=paths["eng"], gemini_root=paths["gemini"]
    )
    assert counts["embedded_dialogs"] == 1
    assert data["items"][0]["dialogs"] == ["Human two"]


def test_script_embed_needs_an_items_list():
    with pytest.raises(SystemExit, match="no items list"):
        sync.sync_script_embed({}, vanilla_dir=None, eng_root=Path("."), gemini_root=Path("."))


def test_vanilla_lookups_handle_a_missing_folder(tmp_path: Path):
    assert sync._vanilla_dialogs(None, "a001") is None
    assert sync._vanilla_dialogs(tmp_path, "a001") is None
    assert sync._gemini_script(tmp_path, "a001") is None


def _fake_trb(monkeypatch, tmp_path: Path) -> Path:
    import patch_textresource

    monkeypatch.setattr(patch_textresource, "load_lookup", lambda _p: [])
    monkeypatch.setattr(
        patch_textresource,
        "dump_entries",
        lambda _d, _l: [{"idx": 1, "text": "翻訳済み"}, {"idx": 2, "text": "体育"}],
    )
    return _write(tmp_path / "main.trb", b"trb")


def test_string_embed_recounts_after_dropping_rows(tmp_path: Path, monkeypatch):
    trb = _fake_trb(monkeypatch, tmp_path)
    table = tmp_path / "t.json"
    table.write_text(json.dumps({"翻訳済み": "Done"}, ensure_ascii=False), encoding="utf-8")
    data = {
        "items": [
            {"kind": "sms", "index": 0},
            {"kind": "trb", "stri_index": 1},
            {"kind": "trb", "stri_index": 2},
        ]
    }
    counts = sync.sync_string_embed(data, trb, table)
    assert counts["sms"] == 1 and counts["trb_kept"] == 1 and counts["trb_dropped"] == 1
    assert data["stats"] == {"sms": 1, "trb": 1, "total": 2, "jp_left": 2}

    assert sync.sync_string_embed({"items": [], "stats": []}, trb, table)["sms"] == 0
    with pytest.raises(SystemExit, match="no items list"):
        sync.sync_string_embed({}, trb, table)


SCRIPT_KIT = (
    '<script type="application/json" id="embedded-workkit">'
    '{"items":[{"kind":"script","stem":"a001"}]}</script>\n'
)
STRING_KIT = (
    '<script type="application/json" id="embedded-strings">'
    '{"items":[{"kind":"trb","stri_index":2}]}</script>\n'
)


def _workbench(tmp_path: Path) -> Path:
    workbench = tmp_path / "wb"
    (workbench / "kit").mkdir(parents=True)
    (workbench / "kit" / "NLPP_Translate.html").write_text(SCRIPT_KIT, encoding="utf-8")
    (workbench / "kit" / "NLPP_Translate_Strings.html").write_text(STRING_KIT, encoding="utf-8")
    return workbench


def test_sync_rebuilds_both_kits_and_finds_vanilla(tmp_path: Path, monkeypatch):
    paths = _kit_project(tmp_path, monkeypatch)
    trb = _fake_trb(monkeypatch, tmp_path)
    workbench = _workbench(tmp_path)
    monkeypatch.setattr(sync, "find_vanilla_script_dir", lambda: paths["vanilla"])
    monkeypatch.setattr(sync, "find_vanilla_main_trb", lambda: trb)
    table = tmp_path / "t.json"
    table.write_text("{}", encoding="utf-8")
    report = sync.sync(
        workbench, gemini_root=paths["gemini"], eng_root=paths["eng"], translations_path=table
    )
    assert report["gemini_xml"]["xml_created"] == 3
    assert report["scripts"]["layer_gemini"] == 1
    assert report["strings"]["trb_kept"] == 1
    assert "patcher:gemini" in (workbench / "kit" / "NLPP_Translate.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("trb", [None, Path("gone.trb")])
def test_sync_stops_without_the_vanilla_text_table(tmp_path: Path, monkeypatch, trb):
    paths = _kit_project(tmp_path, monkeypatch)
    monkeypatch.setattr(sync, "find_vanilla_main_trb", lambda: None)
    with pytest.raises(SystemExit, match="textresource_jpn.trb not found"):
        sync.sync(
            _workbench(tmp_path),
            gemini_root=paths["gemini"],
            eng_root=paths["eng"],
            vanilla_dir=paths["vanilla"],
            trb_path=trb,
            align_xml=False,
        )


def test_main_bumps_the_build_each_run(tmp_path: Path, monkeypatch, capsys):
    paths = _kit_project(tmp_path, monkeypatch)
    trb = _fake_trb(monkeypatch, tmp_path)
    workbench = _workbench(tmp_path)
    table = tmp_path / "t.json"
    table.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sync, "find_vanilla_script_dir", lambda: paths["vanilla"])
    monkeypatch.setattr(sync, "find_vanilla_main_trb", lambda: trb)
    monkeypatch.setitem(sync.sync.__kwdefaults__, "translations_path", table)
    argv = [
        "--workbench",
        str(workbench),
        "--gemini-root",
        str(paths["gemini"]),
        "--eng-root",
        str(paths["eng"]),
    ]
    assert sync.main(argv) == 0
    assert sync.main([*argv, "--no-align-xml"]) == 0
    assert json.loads((workbench / "version.json").read_text(encoding="utf-8"))["build"] == 2
    assert "[workbench] synced build=2" in capsys.readouterr().out
