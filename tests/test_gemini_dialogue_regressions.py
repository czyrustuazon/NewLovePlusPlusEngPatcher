"""Fixes in the shipped Gemini text stay fixed.

This file stays separate from the text it checks. A snapshot of the text would
conflict in the same merge and get resolved the same way, which is how merge
1bd0b64 lost 164 lines with every test green.
"""

from __future__ import annotations

import json
import re

from conftest import ROOT, TOOLS, load_module

th = load_module("translate_heroines_gemini", TOOLS / "translate_heroines_gemini.py")
ingest = load_module("ingest_pack", TOOLS / "ingest_pack.py")

GEMINI = ROOT / "assets" / "gemini_heroines"
XML = GEMINI / "xml"
DBIN = GEMINI / "dbin2"

# Spoken lines that still name the heroine where English says "you". This can
# only go down. It was 168 while the fix-address lines were missing.
ADDRESS_LINES_LEFT = 48


def _xml_text() -> dict[str, str]:
    return {path.stem: path.read_text(encoding="utf-8") for path in sorted(XML.glob("*.xml"))}


def test_lines_spoken_to_the_heroine_only_get_better():
    targets = th.address_targets(XML, ["nene", "rinko"])
    left = sum(len(rows) for rows in targets.values())
    assert left <= ADDRESS_LINES_LEFT, (
        f"{left} spoken lines name the heroine as 'she'; a merge or rerun undid fix-address"
    )


def test_the_player_pronoun_never_comes_back():
    assert th.pronoun_targets(XML, ["nene", "rinko"]) == {}


def test_the_cafe_keeps_its_name():
    wrong = {stem for stem, text in _xml_text().items() if re.search(r"Dexy|Dixies\b", text)}
    assert wrong == set()


def test_an_agreement_stays_an_agreement():
    table = json.loads((GEMINI / "translations.json").read_text(encoding="utf-8"))["translations"]
    assert table["うん、もちろん。"] == "Yeah, of course."


def test_xml_and_the_shipped_scripts_tell_the_same_story():
    stale = [
        path.stem
        for path in sorted((DBIN / "script").glob("*.dbin2"))
        if (XML / f"{path.stem}.xml").is_file()
        and ingest._xml_dialogs(XML / f"{path.stem}.xml") != ingest._dbin_dialogs(path)
    ]
    assert stale == []


def test_every_pack_ships_the_same_text_for_a_script():
    split: list[str] = []
    for path in sorted((DBIN / "script").glob("*.dbin2")):
        shipped = path.read_bytes()
        for pack in ("NLP_01", "NLP_02"):
            copy = DBIN / pack / path.name
            if copy.is_file() and copy.read_bytes() != shipped:
                split.append(f"{pack}/{path.stem}")
    assert split == []
