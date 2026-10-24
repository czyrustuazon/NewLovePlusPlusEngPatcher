"""SMS maildic XML -> MDC: both dictionary layouts reach the right records."""

from __future__ import annotations

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
