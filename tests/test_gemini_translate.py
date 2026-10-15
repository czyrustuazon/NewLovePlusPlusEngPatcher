"""Placeholder protection + skip rules for the Gemini heroine pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import SRC, TOOLS, load_module

gt = load_module("gemini_translate", SRC / "gemini_translate.py")
rebuild = load_module("rebuild_dbin2_from_xml", TOOLS / "rebuild_dbin2_from_xml.py")


def test_protect_restore_player_and_control_markers():
    src = "おはよう、▲主人公＊▲※▼\n待ってて●"
    protected, markers = gt.protect_markers(src)
    assert "▲" not in protected
    assert "※" not in protected
    assert markers == ["▲主人公＊▲", "※", "▼", "●"]
    model_out = "Morning, " + "".join(f"@@M{i}@@" for i in range(len(markers)))
    restored = gt.restore_markers(model_out, markers)
    ok, missing = gt.markers_preserved(src, restored)
    assert ok, missing
    assert restored == "Morning, ▲主人公＊▲※▼●"


def test_dropped_marker_is_rejected():
    src = "ねえ、▲主人公＊▲※"
    item = gt.prepare_items([src])[0]
    res = gt.finalize_item(item, "Hey, you")
    assert res.english is None
    assert res.error == "dropped_marker"
    assert "▲主人公＊▲" in res.missing_markers
    assert "※" in res.missing_markers


def test_kept_sentinels_restore():
    src = "ねえ、▲姉ヶ崎＊▲、▲主人公＊▲！"
    item = gt.prepare_items([src])[0]
    assert item.need
    res = gt.finalize_item(item, "Hey, @@M0@@, @@M1@@!")
    assert res.english == "Hey, ▲姉ヶ崎＊▲, ▲主人公＊▲!"
    assert res.error == ""


def test_skip_placeholder_and_punct_only():
    assert gt.should_skip_line("○○○○○○○○")
    assert gt.should_skip_line("？")
    assert gt.should_skip_line("…")
    assert not gt.needs_translation("○○○○○○○○")
    assert gt.needs_translation("おはよう、▲主人公＊▲")
    assert not gt.needs_translation("Morning, ▲主人公＊▲")


def test_chunk_size_splits_gemini_calls(monkeypatch):
    calls: list[int] = []

    def fake_gen(client, model, user, **kwargs):
        payload = json.loads(user.split("\n")[-1])
        need = [x for x in payload if x.get("need")]
        calls.append(len(need))
        return json.dumps(
            {"items": [{"i": x["i"], "t": f"EN{x['i']}"} for x in need]},
            ensure_ascii=False,
        )

    monkeypatch.setattr(gt, "gemini_generate_json", fake_gen)
    texts = [f"おはよう{i}" for i in range(90)]
    items = gt.prepare_items(texts)
    results = gt.translate_prepared(
        None, "model", items, heroine="nene", chunk_size=40, repair=False
    )
    assert calls == [40, 40, 10]
    assert results[0].english == "EN0"
    assert results[89].english == "EN89"


def test_parse_items_json_wrapper():
    raw = '{"items":[{"i":2,"t":"Hi @@M0@@"}]}'
    assert gt.parse_items_json(raw)[2] == "Hi @@M0@@"


def test_load_gemini_key_from_dotenv(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key-xyz\n", encoding="utf-8")
    monkeypatch.setattr(gt, "ROOT", tmp_path)
    assert gt.load_gemini_api_key() == "test-key-xyz"
    assert gt.load_gemini_model() == gt.DEFAULT_GEMINI_MODEL


def test_entries_to_xml_roundtrip(tmp_path: Path):
    key, unknown = 42, 4
    entries = [
        rebuild.DbinEntry(
            1,
            2,
            rebuild.SDL2Data(
                99,
                [
                    rebuild.UnknownEntry([], 147456, 65536),
                    rebuild.UnknownEntry(
                        [rebuild.SectionAEntry(5197, 0)], 147458, 196608
                    ),
                ],
                ["○○○○", "おはよう、▲主人公＊▲※\n二行目"],
            ),
        )
    ]
    xml_text = rebuild.entries_to_xml(key, unknown, entries)
    path = tmp_path / "a000.xml"
    path.write_text(xml_text, encoding="utf-8")
    got_key, got_unknown, got = rebuild.xml_to_entries(path)
    assert (got_key, got_unknown) == (key, unknown)
    assert got[0].sdl2.dialogs[1] == "おはよう、▲主人公＊▲※\n二行目"
    assert "▲主人公＊▲" in xml_text
    assert "※" in xml_text
