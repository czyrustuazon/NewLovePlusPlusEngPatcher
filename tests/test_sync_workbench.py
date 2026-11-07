"""Workbench rows follow the patcher text, not the September snapshot."""

from __future__ import annotations

from conftest import TOOLS, load_module

sync = load_module("sync_workbench", TOOLS / "sync_workbench.py")


def test_shipped_english_is_the_edit_box_and_japanese_stays_the_baseline():
    item = {"kind": "script", "stem": "t000", "baseline_dialogs": ["old english"], "original_dialogs": ["stale"]}
    sync.fill_script_item(
        item,
        vanilla=["高嶺"],
        working=["Takane"],
        gemini=None,
        layer="manaka",
    )
    assert item["baseline_dialogs"] == ["高嶺"]
    assert item["dialogs"] == ["Takane"]
    assert "original_dialogs" not in item
    assert item["source"] == "patcher:manaka"
    assert item["jp_dialogs"] == 0


def test_a_safe_gemini_line_stays_beside_japanese_without_a_second_copy():
    item = {"kind": "script", "stem": "a001", "baseline_dialogs": ["old"]}
    sync.fill_script_item(
        item,
        vanilla=["こんにちは"],
        working=["Hello"],
        gemini=["Hello"],
        layer="gemini",
    )
    assert item["baseline_dialogs"] == ["こんにちは"]
    assert item["gemini_dialogs"] == ["Hello"]
    assert "dialogs" not in item
    assert item["jp_dialogs"] == 1


def test_a_token_change_is_still_the_shipped_gemini_line():
    item = {"kind": "script", "stem": "a953"}
    jp = "▲姉ヶ崎＊▲"
    en = "▲Anegasaki＊▲"
    sync.fill_script_item(
        item,
        vanilla=[jp],
        working=[en],
        gemini=[en],
        layer="gemini",
    )
    assert item["dialogs"] == [en]
    assert item["gemini_dialogs"] == [en]
    assert item["baseline_dialogs"] == [jp]


def test_a_different_line_count_uses_the_shipped_text_for_both():
    item = {"kind": "script", "stem": "t912"}
    sync.fill_script_item(
        item,
        vanilla=["a", "b"],
        working=["only"],
        gemini=None,
        layer="manaka",
    )
    assert item["baseline_dialogs"] == ["only"]
    assert "dialogs" not in item


def test_translated_trb_rows_drop_and_a_truncated_key_is_restored():
    items = [
        {"kind": "sms", "baseline": "おはよう", "text": "おはよう"},
        {"kind": "trb", "stri_index": 1, "baseline": "まま", "text": "まま", "jp_key": "まま"},
        {
            "kind": "trb",
            "stri_index": 7009,
            "baseline": "必ず",
            "text": "必ず",
            "jp_key": "必ず",
        },
        {"kind": "trb", "stri_index": 9, "baseline": "未訳", "text": "未訳", "jp_key": "未訳"},
    ]
    vanilla = {1: "まま", 7009: "必ず成果は", 9: "未訳"}
    table = {"まま": "Still", "必ず成果は": "Keep going"}
    kept, stats = sync.refresh_trb_items(items, vanilla, table)
    assert [item.get("kind") for item in kept] == ["sms", "trb"]
    assert kept[1]["baseline"] == "未訳"
    assert kept[1]["jp_key"] == "未訳"
    assert stats["trb_dropped"] == 2
    assert stats["trb_kept"] == 1


def test_a_contributor_review_wins_over_the_gemini_pass(tmp_path):
    from patch_names import DbinEntry, SDL2Data, build_dbin2

    def blob(dialogs):
        return build_dbin2(1, 0, [DbinEntry(0, 0, SDL2Data(1, [], dialogs))])

    contrib = tmp_path / "contrib" / "dbin2" / "script"
    gemini = tmp_path / "gemini" / "dbin2" / "script"
    contrib.mkdir(parents=True)
    gemini.mkdir(parents=True)
    (contrib / "a000.dbin2").write_bytes(blob(["Reviewed"]))
    (gemini / "a000.dbin2").write_bytes(blob(["Machine"]))
    dialogs, layer = sync.patcher_working(
        "a000",
        vanilla_dir=None,
        eng_root=tmp_path / "eng",
        gemini_root=tmp_path / "gemini",
        contrib_root=tmp_path / "contrib",
    )
    assert layer == "contrib"
    assert dialogs == ["Reviewed"]
    item = {"kind": "script", "stem": "a000"}
    sync.fill_script_item(
        item,
        vanilla=["姉ヶ崎"],
        working=dialogs,
        gemini=None,
        layer=layer,
    )
    assert item["dialogs"] == ["Reviewed"]
    assert "gemini_dialogs" not in item
    assert item["jp_dialogs"] == 0


def test_two_shipped_wordings_do_not_overwrite_the_phrase_map(tmp_path):
    from patch_names import DbinEntry, SDL2Data, build_dbin2

    jp = "個人的にはちょっと……"
    kept = "I think it's no good..."
    gemini = tmp_path / "gemini"
    script = gemini / "dbin2" / "script"
    xml = gemini / "xml"
    vanilla = tmp_path / "vanilla"
    script.mkdir(parents=True)
    xml.mkdir()
    vanilla.mkdir()
    blob = lambda dialogs: build_dbin2(1, 0, [DbinEntry(0, 0, SDL2Data(1, [], dialogs))])
    (script / "a007.dbin2").write_bytes(blob([kept, "This is no good..."]))
    (vanilla / "a007.dbin2").write_bytes(blob([jp, jp]))
    from rebuild_dbin2_from_xml import entries_to_xml

    (xml / "a007.xml").write_bytes(
        entries_to_xml(1, 0, [DbinEntry(0, 0, SDL2Data(1, [], [kept, "This is no good..."]))]).encode(
            "utf-8"
        )
    )
    table = {"translations": {jp: kept}}
    (gemini / "translations.json").write_text(
        __import__("json").dumps(table, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = sync.align_gemini_xml(gemini, vanilla)
    saved = __import__("json").loads((gemini / "translations.json").read_text(encoding="utf-8"))
    assert saved["translations"][jp] == kept
    assert report["map_keys"] == 0
    assert report["map_conflicts"] == 1
