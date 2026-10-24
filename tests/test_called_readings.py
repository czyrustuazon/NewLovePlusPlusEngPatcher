"""Hepburn for the Called-name reading dictionary (TRB pack 0x7200)."""

from __future__ import annotations

import pytest

from conftest import ROOT, SRC, load_module

cr = load_module("patch_called_readings", SRC / "patch_called_readings.py")


@pytest.mark.parametrize(
    "kana,romaji",
    [
        ("あきこ", "Akiko"),
        ("しんいち", "Shinichi"),
        ("かとう", "Kato"),
        ("おおたけ", "Otake"),
        ("ゆうき", "Yuki"),
        ("はっとり", "Hattori"),
        ("まっちゃん", "Matchan"),
        ("じゅんいちろう", "Junichiro"),
        ("きょー", "Kyo"),
        ("ろっしー", "Rosshi"),
        ("ふぁみ", "Fami"),
        ("こんの", "Konno"),
        ("いいづか", "Iizuka"),
        ("マナカ", "Manaka"),
        ("あっ", "A"),
    ],
)
def test_hepburn(kana, romaji):
    assert cr.hepburn(kana) == romaji


@pytest.mark.parametrize(
    "current,kana,fix",
    [
        ("Kato", "かとう", False),  # curated style kept
        ("Kudou", "くどう", False),
        ("Junichirou", "じゅんいちろう", False),
        ("sea", "うみ", True),  # dialogue meaning of the same word
        ("Leo", "れお", True),
        ("OOTake", "おおたけ", True),
        ("Kuni masa", "くにまさ", True),
        ("HaruYuki", "はるゆき", True),
        ("Hōjō", "ほうじょう", True),
        ("Mamikо", "まみこ", True),  # Cyrillic о
        ("Shunsuke", "しんすけ", True),
    ],
)
def test_needs_fix(current, kana, fix):
    assert cr.needs_fix(current, kana) is fix


def test_not_kana_raises():
    with pytest.raises(ValueError):
        cr.hepburn("先生")


@pytest.mark.local_data
def test_shipped_trb_readings_are_clean_after_the_pass():
    from nlpp_paths import find_vanilla_main_trb
    from patch_textresource import LOOKUP_PATH, decode_entry, iter_entries, load_lookup, parse_chunks

    vanilla = find_vanilla_main_trb()
    trb = ROOT / "release" / "textresource" / "textresource_jpn.trb"
    if vanilla is None or not trb.is_file():
        pytest.skip("no vanilla or release TRB")
    lookup = load_lookup(LOOKUP_PATH)
    van = vanilla.read_bytes()
    out, _logs = cr.apply_called_readings(trb.read_bytes(), van, lookup)
    assert cr.plan(out, van, lookup) == {}, "pass is not idempotent"
    chunks, vchunks = parse_chunks(out), parse_chunks(van)
    entries, ventries = list(iter_entries(chunks["STRI"])), list(iter_entries(vchunks["STRI"]))
    packs = cr._pack_slots(chunks["INDX"])
    users: dict[int, set[int]] = {}
    for pid, slots in packs.items():
        for si in slots:
            users.setdefault(si, set()).add(pid >> 8)
    checked = 0
    for si in packs[cr.PACK]:
        kana = decode_entry(vchunks["STRB"], ventries[si][2], ventries[si][4], lookup)[0]
        if users[si] <= set(cr.OWN_CATS) and cr.KANA_RE.fullmatch(kana):
            text = decode_entry(chunks["STRB"], entries[si][2], entries[si][4], lookup)[0]
            assert cr.CLEAN_RE.fullmatch(text), (kana, text)
            checked += 1
    assert checked > 3000


@pytest.mark.local_data
def test_release_trb_has_the_readings_pass():
    """release/ is what deploy-a and the CIA ship. Stale after a rebuild of
    translations without tools/deploy_name_kanji_trb.py."""
    from nlpp_paths import find_vanilla_main_trb
    from patch_textresource import LOOKUP_PATH, load_lookup

    vanilla = find_vanilla_main_trb()
    trb = ROOT / "release" / "textresource" / "textresource_jpn.trb"
    if vanilla is None or not trb.is_file():
        pytest.skip("no vanilla or release TRB")
    assert cr.plan(trb.read_bytes(), vanilla.read_bytes(), load_lookup(LOOKUP_PATH)) == {}


def test_name_kanji_trb_applies_honorific_suffixes():
    text = (ROOT / "tools" / "deploy_name_kanji_trb.py").read_text(encoding="utf-8")
    assert "apply_honorific_suffixes(rebuilt, vanilla_trb.read_bytes(), lookup)" in text
    assert [s for _slot, _kana, s in cr.SUFFIXES] == ["-kun", "-chan"]


def _suffix_texts(data: bytes, lookup) -> list[str]:
    import struct

    from patch_password_serials import _sub_u16_off
    from patch_textresource import decode_entry, iter_entries, parse_chunks

    c = parse_chunks(data)
    entries = list(iter_entries(c["STRI"]))
    off, n = _sub_u16_off(c["INDX"], cr.SUFFIX_PACK >> 8, cr.SUFFIX_PACK & 0xFF)
    out = []
    for slot in range(n):
        si = struct.unpack_from("<H", c["INDX"], off + 2 * slot)[0]
        _i, _o, s, _b, f = entries[si]
        out.append(decode_entry(c["STRB"], s, f, lookup)[0])
    return out


@pytest.mark.local_data
def test_honorific_suffixes_get_their_own_entries():
    """Naka + -kun, not NakaKun; the shared "Chan" Called readings stay."""
    from nlpp_paths import find_vanilla_main_trb
    from patch_textresource import LOOKUP_PATH, load_lookup

    vanilla = find_vanilla_main_trb()
    trb = ROOT / "release" / "textresource" / "textresource_jpn.trb"
    if vanilla is None or not trb.is_file():
        pytest.skip("no vanilla or release TRB")
    lookup = load_lookup(LOOKUP_PATH)
    van = vanilla.read_bytes()
    out, logs = cr.apply_honorific_suffixes(trb.read_bytes(), van, lookup)
    texts = _suffix_texts(out, lookup)
    assert texts[:2] == ["-kun", "-chan"]
    assert texts[2:] == _suffix_texts(trb.read_bytes(), lookup)[2:]
    assert cr.apply_honorific_suffixes(out, van, lookup)[1] == []  # idempotent
    assert cr.plan(out, van, lookup) == {}  # readings pass still clean


@pytest.mark.local_data
def test_release_trb_has_honorific_suffixes():
    from patch_textresource import LOOKUP_PATH, load_lookup

    trb = ROOT / "release" / "textresource" / "textresource_jpn.trb"
    if not trb.is_file():
        pytest.skip("no release TRB")
    assert _suffix_texts(trb.read_bytes(), load_lookup(LOOKUP_PATH))[:2] == ["-kun", "-chan"]
