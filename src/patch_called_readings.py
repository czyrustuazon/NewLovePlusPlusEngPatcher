#!/usr/bin/env python3
"""Romaji for the Called-name reading dictionary (TRB pack 0x7200).

The romaji Called lookup (src/call_romaji_match.c) lists pack 0x7200 entries
by their text, and a chosen entry's text becomes the player's Called name.
rebuild_trb translates by Japanese text, so short readings picked up the
dialogue meaning of the same word: いま "now", うみ "sea", えび "shrimp".
Others came out as OOTake, Kuni masa, HaruYuki, or with a Cyrillic о.

This pass rewrites a reading with Hepburn generated from the vanilla kana
when the current text is not a clean Title-case name or does not spell that
kana, long vowels included: curated Kato for かとう becomes Katou, so every
reading spells its vowel length the same way (Kudou, Yuuki, Ryuuji).
Only entries used by packs 0x71xx / 0x72xx alone are touched: quiz answers
(さくら in 0xa000), forms of address (ハニー in 0x202) and the 0x70xx
name-input keyboard share some strings and keep their text.
"""
from __future__ import annotations

import re
import struct

from patch_password_serials import _pack_trb, _strb_used, _sub_u16_off
from patch_textresource import decode_entry, iter_entries, parse_chunks

PACK = 0x7200
OWN_CATS = (0x71, 0x72)

# Pack 0x718a slots 0 / 1 are the honorifics the Gallery ("Called As:") and
# the heroine's form of the Called name append to it: くん / ちゃん. Dialogue
# translation made them "Kun" / "Chan", so "Naka" + "Kun" read "NakaKun".
# ちゃん's string is shared with Called readings (0x7200 4880 / 4974, where
# "Chan" is a name on its own), so the suffix slots get new entries instead.
SUFFIX_PACK = 0x718A
SUFFIXES = ((0, "くん", "-kun"), (1, "ちゃん", "-chan"))

_BASE = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "o", "ん": "n", "ゔ": "vu",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
}
_YOON = {"ゃ": "a", "ゅ": "u", "ょ": "o"}
_SMALL_VOWEL = {"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o"}
KANA_RE = re.compile(r"[ぁ-ゖァ-ヺー]+")
CLEAN_RE = re.compile(r"[A-Z][a-z]*")


def _hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def hepburn(kana: str) -> str:
    """Hepburn with long vowels spelled out: no macrons or apostrophes,
    おう → ou, おお → oo, うう → uu, ー repeats the vowel before it (o → ou),
    っ doubles the next consonant, Title case. Vowel length tells names
    apart (ゆき Yuki / ゆうき Yuuki, さと Sato / さとう Satou), so a reading
    never drops it."""
    s = _hira(kana)
    syl: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if c == "っ" or c == "ー":
            syl.append(c)
        elif c in _BASE and nxt in _YOON and c not in "あいうえおやゆよわん":
            stem = _BASE[c][:-1]  # き -> k, し -> sh, ち -> ch, じ -> j
            syl.append(stem + ("" if stem.endswith(("sh", "ch", "j")) else "y") + _YOON[nxt])
            i += 1
        elif c in _BASE and nxt in _SMALL_VOWEL and _BASE[c][-1:] in "aiueo" and len(_BASE[c]) > 1:
            syl.append(_BASE[c][:-1] + _SMALL_VOWEL[nxt])  # ふぁ -> fa, てぃ -> ti
            i += 1
        elif c in _BASE:
            syl.append(_BASE[c])
        else:
            raise ValueError(f"not kana: {kana!r}")
        i += 1
    out = ""
    for k, part in enumerate(syl):
        if part == "ー":
            if out and out[-1] in "aiueo":
                out += "u" if out[-1] == "o" else out[-1]
            continue
        if part == "っ":
            nxt = next((p for p in syl[k + 1 :] if p not in ("っ", "ー")), "")
            if nxt[:1] and nxt[0] not in "aiueon":
                out += "t" if nxt.startswith("ch") else nxt[0]
            continue
        out += part
    return out[:1].upper() + out[1:]


def needs_fix(current: str, kana: str) -> bool:
    return not CLEAN_RE.fullmatch(current) or current.lower() != hepburn(kana).lower()


def _pack_slots(indx: bytes) -> dict[int, list[int]]:
    """INDX pack id -> STRI indices."""
    out: dict[int, list[int]] = {}
    for cat in range(256):
        co = struct.unpack_from("<I", indx, cat * 4)[0]
        if not co or co >= len(indx):
            continue
        for sub in range(struct.unpack_from("<I", indx, co)[0]):
            so = co + struct.unpack_from("<I", indx, co + 4 + sub * 4)[0]
            n = struct.unpack_from("<I", indx, so)[0]
            out[(cat << 8) | sub] = list(struct.unpack_from(f"<{n}H", indx, so + 4))
    return out


def plan(data: bytes, vanilla: bytes, lookup: list[str]) -> dict[int, tuple[str, str, str]]:
    """STRI index -> (vanilla kana, current text, new text) for readings to fix."""
    chunks, vchunks = parse_chunks(data), parse_chunks(vanilla)
    entries, ventries = list(iter_entries(chunks["STRI"])), list(iter_entries(vchunks["STRI"]))
    # Later passes append entries (shared serial passwords) and retarget
    # their own slots; vanilla entries keep their indices.
    if len(entries) < len(ventries):
        raise ValueError("TRB has fewer entries than vanilla")
    packs = _pack_slots(chunks["INDX"])
    if packs[PACK] != _pack_slots(vchunks["INDX"])[PACK]:
        raise ValueError(f"pack {PACK:#x} slots differ from vanilla")
    users: dict[int, set[int]] = {}
    for pid, slots in packs.items():
        for si in slots:
            users.setdefault(si, set()).add(pid >> 8)
    fixes: dict[int, tuple[str, str, str]] = {}
    for si in packs[PACK]:
        if not users[si] <= set(OWN_CATS):
            continue
        _i, _o, vs, _vb, vf = ventries[si]
        _i, _o, cs, _cb, cf = entries[si]
        if vf == 2 or cf == 2:
            continue
        kana = decode_entry(vchunks["STRB"], vs, vf, lookup)[0]
        if not KANA_RE.fullmatch(kana):
            continue
        current = decode_entry(chunks["STRB"], cs, cf, lookup)[0]
        if needs_fix(current, kana):
            fixes[si] = (kana, current, hepburn(kana))
    return fixes


def apply_called_readings(data: bytes, vanilla: bytes, lookup: list[str]) -> tuple[bytes, list[str]]:
    """Rewrite the planned 0x7200 readings. Other entries keep their bytes."""
    fixes = plan(data, vanilla, lookup)
    if not fixes:
        return data, []
    chunks = parse_chunks(data)
    strb = chunks["STRB"]
    new_stri, new_strb = bytearray(), bytearray()
    for idx, _off, stringindex, bytelength, flag in iter_entries(chunks["STRI"]):
        if flag == 2:
            new_stri += struct.pack("<IHH", len(new_strb), 0, 2)
            continue
        if idx in fixes:
            payload = fixes[idx][2].encode("utf-8")
            new_stri += struct.pack("<IHH", len(new_strb), len(payload), 1)
            new_strb += payload + b"\x00"
            continue
        # Same copy as rebuild_trb's kept path.
        _text, raw = decode_entry(strb, stringindex, flag, lookup)
        new_stri += struct.pack("<IHH", len(new_strb), bytelength, flag)
        new_strb += (raw or b"") + b"\x00"
    pad = (4 - (len(new_strb) % 4)) % 4
    new_strb += b"\xc9" * pad
    chunks["STRI"], chunks["STRB"] = bytes(new_stri), bytes(new_strb)
    logs = [f"{v[0]} {v[1]!r} -> {v[2]}" for v in fixes.values()]
    return _pack_trb(chunks), logs


def apply_honorific_suffixes(
    data: bytes, vanilla: bytes, lookup: list[str]
) -> tuple[bytes, list[str]]:
    """Point pack 0x718a's honorific slots at their own "-kun" / "-chan"
    entries. Idempotent; other entries and slots keep their bytes."""
    chunks = parse_chunks(data)
    vchunks = parse_chunks(vanilla)
    stri, strb, indx = bytearray(chunks["STRI"]), bytearray(chunks["STRB"]), bytearray(chunks["INDX"])
    entries = list(iter_entries(stri))
    ventries = list(iter_entries(vchunks["STRI"]))
    u16_off, count = _sub_u16_off(indx, SUFFIX_PACK >> 8, SUFFIX_PACK & 0xFF)
    v_off, _v_count = _sub_u16_off(vchunks["INDX"], SUFFIX_PACK >> 8, SUFFIX_PACK & 0xFF)
    strb = strb[: _strb_used(stri, strb)]
    n = len(entries)
    logs: list[str] = []
    for slot, kana, text in SUFFIXES:
        if slot >= count:
            raise ValueError(f"pack {SUFFIX_PACK:#x} has no slot {slot}")
        vsi = struct.unpack_from("<H", vchunks["INDX"], v_off + 2 * slot)[0]
        _i, _o, vs, _vb, vf = ventries[vsi]
        if decode_entry(vchunks["STRB"], vs, vf, lookup)[0] != kana:
            raise ValueError(f"pack {SUFFIX_PACK:#x} slot {slot} is not {kana} in vanilla")
        si = struct.unpack_from("<H", indx, u16_off + 2 * slot)[0]
        _i, _o, cs, _cb, cf = entries[si]
        if cf == 1 and decode_entry(strb, cs, cf, lookup)[0] == text:
            continue
        payload = text.encode("utf-8")
        stri += struct.pack("<IHH", len(strb), len(payload), 1)
        strb += payload + b"\x00"
        struct.pack_into("<H", indx, u16_off + 2 * slot, n)
        logs.append(f"{SUFFIX_PACK:#x}[{slot}] -> {text} stri={n}")  # ASCII: cp1252 consoles
        n += 1
    if not logs:
        return data, logs
    strb += b"\xc9" * ((4 - len(strb) % 4) % 4)
    chunks["STRI"], chunks["STRB"], chunks["INDX"] = bytes(stri), bytes(strb), bytes(indx)
    return _pack_trb(chunks), logs
