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
        ("かとう", "Katou"),
        ("おおたけ", "Ootake"),
        ("ゆうき", "Yuuki"),
        ("ゆき", "Yuki"),
        ("りゅうじ", "Ryuuji"),
        ("はっとり", "Hattori"),
        ("まっちゃん", "Matchan"),
        ("じゅんいちろう", "Junichirou"),
        ("きょー", "Kyou"),
        ("ろっしー", "Rosshii"),
        ("あー", "Aa"),
        ("ふぁみ", "Fami"),
        ("こんの", "Konno"),
        ("いいづか", "Iizuka"),
        ("マナカ", "Manaka"),
        ("あっ", "A"),
        ("ーあ", "A"),  # leading long mark has nothing to lengthen
    ],
)
def test_hepburn(kana, romaji):
    assert cr.hepburn(kana) == romaji


@pytest.mark.parametrize(
    "current,kana,fix",
    [
        ("Kato", "かとう", True),  # drops the long vowel: Katou
        ("Kudou", "くどう", False),
        ("Junichirou", "じゅんいちろう", False),
        ("Ayuu", "あゆ", True),  # adds one
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


def _trb(texts: list[str | None], packs: dict[int, list[int]]) -> bytes:
    """Tiny UTF-8 TRB: one STRI entry per text (None = flag 2), INDX packs."""
    import struct

    stri, strb = bytearray(), bytearray()
    for text in texts:
        if text is None:
            stri += struct.pack("<IHH", len(strb), 0, 2)
            continue
        payload = text.encode("utf-8")
        stri += struct.pack("<IHH", len(strb), len(payload), 1)
        strb += payload + b"\x00"
    strb += b"\xc9" * ((4 - len(strb) % 4) % 4)
    indx = bytearray(0x400)
    for cat in sorted({pid >> 8 for pid in packs}):
        subs = [packs.get((cat << 8) | sub, []) for sub in range(max(p & 0xFF for p in packs if p >> 8 == cat) + 1)]
        co = len(indx)
        struct.pack_into("<I", indx, cat * 4, co)
        indx += struct.pack("<I", len(subs)) + bytes(4 * len(subs))
        for sub, slots in enumerate(subs):
            struct.pack_into("<I", indx, co + 4 + sub * 4, len(indx) - co)
            indx += struct.pack(f"<I{len(slots)}H", len(slots), *slots)
            indx += bytes((4 - len(indx) % 4) % 4)
    out = bytearray()
    for name, body in (("STRI", stri), ("STRB", strb), ("INDX", indx)):
        out += name.encode("ascii") + struct.pack("<I", len(body)) + body
    return bytes(out)


_PACKS = {cr.PACK: [0, 1, 2, 3, 4], 0x1000: [4], cr.SUFFIX_PACK: [5, 6, 7]}
_VANILLA = ["かとう", "くどう", "先生", None, "うみ", "くん", "ちゃん", "さん"]
_CURRENT = ["Kato", "Kudou", "Teacher", None, "sea", "Kun", "Chan", "San"]


def _texts(data: bytes) -> list[str]:
    from patch_textresource import decode_entry, iter_entries, parse_chunks

    c = parse_chunks(data)
    return [decode_entry(c["STRB"], s, f, [])[0] for _i, _o, s, _b, f in iter_entries(c["STRI"])]


def test_plan_fixes_only_own_kana_readings():
    """Skips non-kana, flag-2 and entries other packs share (うみ = "sea")."""
    van, cur = _trb(_VANILLA, _PACKS), _trb(_CURRENT, _PACKS)
    assert cr.plan(cur, van, []) == {0: ("かとう", "Kato", "Katou")}


def test_apply_called_readings_rewrites_and_is_idempotent():
    van, cur = _trb(_VANILLA, _PACKS), _trb(_CURRENT, _PACKS)
    out, logs = cr.apply_called_readings(cur, van, [])
    assert logs == ["かとう 'Kato' -> Katou"]
    assert _texts(out) == ["Katou", *_texts(cur)[1:]]
    assert cr.apply_called_readings(out, van, []) == (out, [])


def test_plan_refuses_a_trb_that_does_not_match_vanilla():
    van = _trb(_VANILLA, _PACKS)
    with pytest.raises(ValueError, match="fewer entries"):
        cr.plan(_trb(_CURRENT[:-1], _PACKS), van, [])
    with pytest.raises(ValueError, match="differ from vanilla"):
        cr.plan(_trb(_CURRENT, {**_PACKS, cr.PACK: [0, 1, 2, 3]}), van, [])


def test_apply_honorific_suffixes_on_a_synthetic_trb():
    van, cur = _trb(_VANILLA, _PACKS), _trb(_CURRENT, _PACKS)
    out, logs = cr.apply_honorific_suffixes(cur, van, [])
    assert len(logs) == 2
    assert _suffix_texts(out, []) == ["-kun", "-chan", "San"]
    assert _texts(out)[: len(_CURRENT)] == _texts(cur)  # old entries keep their bytes
    assert cr.apply_honorific_suffixes(out, van, []) == (out, [])


def test_apply_honorific_suffixes_refuses_unexpected_slots():
    with pytest.raises(ValueError, match="no slot 1"):
        packs = {**_PACKS, cr.SUFFIX_PACK: [5]}
        cr.apply_honorific_suffixes(_trb(_CURRENT, packs), _trb(_VANILLA, packs), [])
    with pytest.raises(ValueError, match="is not くん"):
        van = _trb(_VANILLA[:5] + ["さん", "ちゃん", "さん"], _PACKS)
        cr.apply_honorific_suffixes(_trb(_CURRENT, _PACKS), van, [])
