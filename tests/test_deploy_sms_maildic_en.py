"""SMS maildic XML -> MDC: both dictionary layouts reach the right records."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from conftest import ROOT, TOOLS, load_module

mdcutil = load_module("mdcutil", TOOLS / "mdcutil.py")
deploy = load_module("deploy_sms_maildic_en", TOOLS / "deploy_sms_maildic_en.py")

GEMINI_SMS = ROOT / "assets" / "gemini_heroines" / "sms"


def _write_xml(path, rows):
    root = ET.Element("Dictionary")
    for hex_id, text in rows:
        entry = ET.SubElement(root, "Entry")
        jt = ET.SubElement(entry, "JapaneseText", {"hex": hex_id})
        jt.text = text
    ET.ElementTree(root).write(path, encoding="utf-8")


def _base(*keys):
    return [mdcutil.MdcEntry(k, 0, "jp") for k in keys]


def test_one_entry_per_record_matches_by_position_with_repeated_keys(tmp_path):
    """Gemini layout: odd counts are fine and repeated keys stay in order."""
    xml = tmp_path / "maildic_m.en.xml"
    _write_xml(xml, [("FFFFC1FFFFFFFF00", "a"), ("FFFFC1FFFFFFFF00", "b"), ("01", "c")])
    texts = mdcutil.texts_from_dictionary_xml(xml, _base(0xFFFFC1FFFFFFFF00, 0xFFFFC1FFFFFFFF00, 1))
    assert texts == ["a", "b", "c"]


def test_one_entry_per_record_rejects_a_key_out_of_order(tmp_path):
    xml = tmp_path / "maildic_m.en.xml"
    _write_xml(xml, [("02", "a"), ("01", "b")])
    with pytest.raises(ValueError, match="Entry 0 hex"):
        mdcutil.texts_from_dictionary_xml(xml, _base(1, 2))


def test_legacy_paired_layout_still_takes_every_second_entry(tmp_path):
    xml = tmp_path / "maildic_m.en.xml"
    _write_xml(xml, [("00", ""), ("11", "first"), ("00", ""), ("22", "second")])
    assert mdcutil.texts_from_dictionary_xml(xml, _base(5, 6)) == ["first", "second"]
    assert mdcutil.texts_from_dictionary_xml(xml) == ["first", "second"]


@pytest.mark.parametrize("stem", deploy.STEMS)
def test_shipped_gemini_sms_builds_an_mdc(stem, tmp_path, monkeypatch):
    """Drop's Gemini SMS splice failed with "odd Entry count 599" on maildic_m."""
    keys = [
        int(e.find("JapaneseText").get("hex"), 16)
        for e in ET.parse(GEMINI_SMS / f"{stem}.en.xml").getroot().findall("Entry")
    ]
    jp = mdcutil.pack_mdc([mdcutil.MdcEntry(k, 0, "ja") for k in keys])
    slot = len(jp) * 4
    elem = SimpleNamespace(fn=f"{stem}.mdc", read=lambda: jp, fw=SimpleNamespace(wlen=slot))
    others = [
        SimpleNamespace(fn=f"{s}.mdc", read=lambda: jp, fw=SimpleNamespace(wlen=slot))
        for s in deploy.STEMS
        if s != stem
    ]
    monkeypatch.setattr(deploy, "OUT", tmp_path / "out")
    monkeypatch.setattr(deploy, "CONTRIB_SMS_DIR", tmp_path / "no_contrib")
    # Every stem must resolve; point the others at this stem's file.
    for s in deploy.STEMS:
        if s != stem:
            (tmp_path / f"{s}.en.xml").write_bytes((GEMINI_SMS / f"{stem}.en.xml").read_bytes())
    (tmp_path / f"{stem}.en.xml").write_bytes((GEMINI_SMS / f"{stem}.en.xml").read_bytes())
    built = deploy.build_en_mdcs(SimpleNamespace(entries=[elem, *others]), tmp_path)
    records = mdcutil.parse_mdc(built[f"{stem}.mdc"])
    assert [r.key for r in records] == keys
    assert len(built[f"{stem}.mdc"]) == slot


def _words(*rows):
    return mdcutil.pack_worddic([mdcutil.WordEntry(bytes([n]) * 15, w) for n, w in rows])


def _word_elem(fn, blob, slot):
    return SimpleNamespace(fn=fn, read=lambda: blob, fw=SimpleNamespace(wlen=slot))


def test_worddic_codec_round_trips_and_rejects_bad_records():
    blob = _words((1, "春"), (2, "。"))
    entries = mdcutil.parse_worddic(blob)
    assert [(e.head, e.text) for e in entries] == [(b"\x01" * 15, "春"), (b"\x02" * 15, "。")]
    assert mdcutil.pack_worddic(entries) == blob
    with pytest.raises(ValueError, match="too small"):
        mdcutil.parse_worddic(b"\x01")
    with pytest.raises(ValueError, match="truncated"):
        mdcutil.parse_worddic(blob[:10])
    with pytest.raises(ValueError, match="bad text"):
        mdcutil.parse_worddic(blob[:-1])
    with pytest.raises(ValueError, match="bad worddic record"):
        mdcutil.pack_worddic([mdcutil.WordEntry(b"\x00" * 7, "x")])


def test_build_en_worddics_swaps_words_and_keeps_heads(tmp_path, monkeypatch):
    words = tmp_path / "worddic.en.json"
    words.write_text('{"春": "spring", "。": "."}', encoding="utf-8")
    monkeypatch.setattr(deploy, "WORDS_JSON", words)
    jp = _words((1, "春"), (2, "。"))
    pak = SimpleNamespace(entries=[_word_elem("worddic_m.mdc", jp, len(jp) + 4), _word_elem("maildic_m.mdc", b"", 0)])
    built = deploy.build_en_worddics(pak)
    assert list(built) == ["worddic_m.mdc"]
    blob = built["worddic_m.mdc"]
    assert len(blob) == len(jp) + 4
    entries = mdcutil.parse_worddic(blob)
    assert [(e.head, e.text) for e in entries] == [(b"\x01" * 15, "spring"), (b"\x02" * 15, ".")]
    assert blob.endswith(b"\xff")

    words.write_text('{"春": "spring and then some more", "。": "."}', encoding="utf-8")
    with pytest.raises(SystemExit, match="grew past slot"):
        deploy.build_en_worddics(pak)
    # A re-run over English output keeps the English words.
    words.write_text('{"春": "spring", "。": "."}', encoding="utf-8")
    again = SimpleNamespace(entries=[_word_elem("worddic_m.mdc", blob, len(blob))])
    assert deploy.build_en_worddics(again)["worddic_m.mdc"] == blob
    words.write_text('{"春": "spring"}', encoding="utf-8")
    with pytest.raises(SystemExit, match="no English in worddic.en.json"):
        deploy.build_en_worddics(pak)


CONTRIB_SMS = ROOT / "assets" / "sms_contrib"
# Slot words that are lower-case English (season, weather, illness).
LOWER_SLOTS = ("[19]", "[22]", "[24]")


@pytest.mark.parametrize("stem", deploy.STEMS)
def test_contrib_templates_read_with_english_slot_words(stem):
    import re

    texts = [
        jt.text or ""
        for jt in ET.parse(CONTRIB_SMS / f"{stem}.en.xml").getroot().iter("JapaneseText")
    ]
    for text in texts:
        # [32] adds ".", "▼" or "...": never right after other punctuation.
        assert not re.search(r"[.!?！？~～]\[32\]", text), text
        for slot in LOWER_SLOTS:
            assert not re.search(r"(^|(?<!\.)[.!?！？] )" + re.escape(slot), text), text


@pytest.mark.local_data
def test_vanilla_worddics_all_have_english_that_fits():
    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    _im, pak = deploy.load_pkg92(vanilla)
    built = deploy.build_en_worddics(pak)
    assert sorted(built) == [f"{s}.mdc" for s in deploy.WORD_STEMS]
    for blob in built.values():
        assert not any(re.search(r"[぀-ヿ一-鿿]", e.text) for e in mdcutil.parse_worddic(blob))
