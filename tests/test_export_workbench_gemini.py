"""Gemini lines sit beside Japanese in the workbench embed, not instead of it."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import TOOLS, load_module

export = load_module(
    "export_workbench_gemini", TOOLS / "export_workbench_gemini.py"
)

SCRIPT_HTML = """<!DOCTYPE html>
<script type="application/json" id="embedded-workkit">{"schema":1,"kind":"nlpp-workkit","stats":{},"items":[{"kind":"script","stem":"a001","baseline_dialogs":["こんにちは","stay"],"dialog_count":2},{"kind":"script","stem":"t001","baseline_dialogs":["まま"]}]}</script>
"""

STRINGS_HTML = """<!DOCTYPE html>
<script type="application/json" id="embedded-strings">{"schema":1,"kind":"nlpp-strings-workkit","stats":{},"items":[{"kind":"sms","heroine":"nene","index":0,"key":"0xffffc6fdffffff01","baseline":"体育って好き？","text":"体育って好き？"},{"kind":"sms","heroine":"nene","index":1,"key":"0xffffc6fdffffff01","baseline":"腕を伸ばす","text":"腕を伸ばす"},{"kind":"trb","stri_index":1,"baseline":"まま","text":"まま"}]}</script>
"""

GEMINI_XML = """<?xml version="1.0" encoding="utf-8"?>
<DBIN2><Entries><Entry><SDL2 Key="1"><Dialogs>
<Dialog>Hello</Dialog>
<Dialog>stay &amp; put</Dialog>
</Dialogs></SDL2></Entry></Entries></DBIN2>
"""

SMS_XML = """<?xml version="1.0" encoding="utf-8"?>
<Dictionary>
<Entry><JapaneseText hex="FFFFC6FDFFFFFF01">Do you like P.E.?</JapaneseText></Entry>
<Entry><JapaneseText hex="FFFFC6FDFFFFFF01">Gonna sneak in a quick arm stretch.</JapaneseText></Entry>
</Dictionary>
"""


def _embed(html: str, element_id: str) -> dict:
    marker = f'id="{element_id}">'
    start = html.find(marker) + len(marker)
    end = html.find("</script>", start)
    return json.loads(html[start:end])


def test_attach_keeps_japanese_and_adds_gemini(tmp_path: Path):
    workbench = tmp_path / "workbench"
    kit = workbench / "kit"
    kit.mkdir(parents=True)
    (kit / "NLPP_Translate.html").write_text(SCRIPT_HTML, encoding="utf-8")
    (kit / "NLPP_Translate_Strings.html").write_text(STRINGS_HTML, encoding="utf-8")
    gemini = tmp_path / "gemini"
    xml = gemini / "xml"
    xml.mkdir(parents=True)
    (xml / "a001.xml").write_text(GEMINI_XML, encoding="utf-8")
    sms = gemini / "sms"
    sms.mkdir()
    (sms / "maildic_n.en.xml").write_text(SMS_XML, encoding="utf-8")

    counts = export.export_gemini(workbench, gemini)
    assert counts["scripts"] == 1
    assert counts["sms"] == 2

    scripts = _embed((kit / "NLPP_Translate.html").read_text(encoding="utf-8"), "embedded-workkit")
    nene, manaka = scripts["items"]
    assert nene["baseline_dialogs"] == ["こんにちは", "stay"]
    assert nene["gemini_dialogs"] == ["Hello", "stay & put"]
    assert "gemini_dialogs" not in manaka
    assert "dialogs" not in nene

    strings = _embed(
        (kit / "NLPP_Translate_Strings.html").read_text(encoding="utf-8"),
        "embedded-strings",
    )
    pe, stretch, trb = strings["items"]
    assert pe["baseline"] == "体育って好き？"
    assert pe["text"] == "体育って好き？"
    assert pe["gemini"] == "Do you like P.E.?"
    assert stretch["gemini"] == "Gonna sneak in a quick arm stretch."
    assert "gemini" not in trb

    again = export.export_gemini(workbench, gemini)
    assert again == counts


def test_script_pack_dbin_wins_over_a_stale_xml(tmp_path: Path):
    workbench = tmp_path / "workbench"
    kit = workbench / "kit"
    kit.mkdir(parents=True)
    (kit / "NLPP_Translate.html").write_text(SCRIPT_HTML, encoding="utf-8")
    (kit / "NLPP_Translate_Strings.html").write_text(STRINGS_HTML, encoding="utf-8")
    gemini = tmp_path / "gemini"
    xml_dir = gemini / "xml"
    xml_dir.mkdir(parents=True)
    shipped_xml = """<?xml version="1.0" encoding="utf-8"?>
<DBIN2 Key="1" Unknown="1">
  <Entries>
    <Entry Unknown0="1" Unknown1="2">
      <SDL2 Key="3">
        <Unknown><Entry><Values /><Value0>1</Value0><Value1>2</Value1></Entry></Unknown>
        <Dialogs>
          <Dialog>Hello</Dialog>
          <Dialog>stay &amp; put</Dialog>
        </Dialogs>
      </SDL2>
    </Entry>
  </Entries>
</DBIN2>
"""
    xml_path = xml_dir / "a001.xml"
    xml_path.write_text(shipped_xml, encoding="utf-8")
    sms = gemini / "sms"
    sms.mkdir()
    (sms / "maildic_n.en.xml").write_text(SMS_XML, encoding="utf-8")
    rebuild = load_module("rebuild_dbin2_from_xml", TOOLS / "rebuild_dbin2_from_xml.py")
    key, unknown, entries = rebuild.xml_to_entries(xml_path)
    dest = gemini / "dbin2" / "script" / "a001.dbin2"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(rebuild.build_dbin2(key, unknown, entries))
    xml_path.write_text(shipped_xml.replace("Hello", "Goodbye"), encoding="utf-8")

    export.export_gemini(workbench, gemini)
    scripts = _embed((kit / "NLPP_Translate.html").read_text(encoding="utf-8"), "embedded-workkit")
    assert scripts["items"][0]["gemini_dialogs"] == ["Hello", "stay & put"]


def test_stamp_bumps_the_build_every_page_compares(tmp_path: Path):
    workbench = tmp_path / "workbench"
    (workbench / "kit" / "NLPP_Translate_Images").mkdir(parents=True)
    page = '<html><head><meta charset="utf-8" />\n</head><body></body></html>'
    for rel in export.PAGES:
        (workbench / rel).write_text(page, encoding="utf-8")
    (workbench / "version.json").write_text('{"build": 1}\n', encoding="utf-8")
    export.stamp_build(workbench, export.read_build(workbench) + 1)
    assert json.loads((workbench / "version.json").read_text(encoding="utf-8"))["build"] == 2
    for rel in export.PAGES:
        text = (workbench / rel).read_text(encoding="utf-8")
        assert 'name="nlpp-workbench-build" content="2"' in text
