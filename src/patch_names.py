#!/usr/bin/env python3
"""
English heroine-name patches for New Love Plus+.

Two active layers:

1. **`.dbin2` / `assets/scripts` XML** — dialogue keeps nickname markers.
   Manaka's family slot is ``Takane`` (same 6 bytes as 高嶺), so her marker
   is ``▲Takane＊＊▲``. Nene's marker is ``▲Anegasaki＊▲`` (9-byte surname
   plus one ＊). Rinko's family slot is ``Kobayaka`` (8 bytes plus a NUL),
   so her marker is ``▲Kobayaka＊▲``. Other English words inside markers
   (``▲Protagonist＊▲``) are not tokens.

2. **`textresource_resident_jpn.trb`** + **`img.bin` name table** — Nene's
   visible surname and her nickname key are the exact C strings in
   ``NENE_SURNAME_SLOTS``. Do not substring-replace 姉ヶ崎; that rewrites
   the inside of the marker.

Fixed-width slots in (2): English must fit the original UTF-8 byte budget;
shorter strings are NUL-padded at the end of the span.

Legacy ``--strip-dialog-tokens`` still expands tokens to plain English in dbin2
(breaks nicknames — avoid on gold-path builds).
"""
from __future__ import annotations

import argparse
import re
import struct
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Dialog script tokens → plain English (no ▲ / ＊ wrappers)
# ---------------------------------------------------------------------------

DBIN_REPLACEMENTS: list[tuple[str, str]] = [
    ("▲高嶺＊＊▲", "Takane"),
    ("▲Takane＊＊▲", "Takane"),
    ("▲高嶺＊＊", "Takane"),  # rare truncated forms (missing closing ▲)
    ("▲Takane＊＊", "Takane"),
    ("▲小早川＊▲", "Rinko"),
    ("▲Rinko＊▲", "Rinko"),
    ("▲小早川＊", "Rinko"),
    ("▲Rinko＊", "Rinko"),
    ("▲姉ヶ崎＊▲", "Anegasaki"),
    ("▲Anegasaki＊▲", "Anegasaki"),
    ("▲姉ヶ崎＊", "Anegasaki"),
    ("▲Anegasaki＊", "Anegasaki"),
    ("▲Nene＊▲", "Anegasaki"),
    ("▲Nene＊", "Anegasaki"),
]

TRAILING_PAD_RE = re.compile(
    r"(Takane|Rinko|Nene) {1,8}(?=[！？!?.\)\]\，\。,]|$)"
)

# ---------------------------------------------------------------------------
# Resident / img.bin fixed-width name table
# ---------------------------------------------------------------------------

# Each heroine marker is its own exact slot, matched to the English
# family-name bytes.
TOKEN_REPLACEMENTS: list[tuple[str, str]] = []

NAME_REPLACEMENTS: list[tuple[str, str]] = [
    # Spaced "family given］" rows (save-select / cast) — must run before short
    # family/given replaces, or 小早川→Kobayaka leaves a stray byte and breaks 凛子.
    ("高嶺 愛花］", "Takane Manaka］"),
    ("小早川 凛子］", "Kobayakawa Rinko］"),
    ("高嶺 愛花", "Takane Manaka"),
    ("小早川 凛子", "Kobayakawa Rinko"),
    # Compact full names (no space). Nene's surname is exact-slot only —
    # see NENE_SURNAME_SLOTS. A substring swap would rewrite the ▲姉ヶ崎＊▲ key.
    ("高嶺愛花", "ManakaTakane"),
    ("小早川凛子", "Rinko Kobayaka"),
    ("高嶺ちゃん", "Takane-chan"),
    ("高嶺さん", "Takane-san"),
    ("高嶺くん", "Takane-kun"),
    ("高嶺選手", "Takane"),
    ("高嶺様", "Takane"),
]

# Whole C strings only. A substring swap of 高嶺 / 小早川 rewrites the inside
# of ▲高嶺＊＊▲ / ▲小早川＊▲ and the line shows the marker.
EXACT_NAME_REPLACEMENTS: list[tuple[str, str]] = [
    # 小早川 is 9 UTF-8 bytes → "Kobayaka\0". 姉ヶ崎 is NENE_SURNAME_SLOTS.
    ("小早川", "Kobayaka"),
    ("高嶺", "Takane"),
    ("愛花", "Manaka"),
    ("凛子", "Rinko"),
    ("寧々", "Nene"),
]

# Exact C strings only. A substring swap of 姉ヶ崎 would rewrite the inside of
# the nickname marker. Longer rows are listed first so a short slot cannot be
# applied to a longer one if a caller uses replace_all.
# The marker is 18 bytes either way: ▲ + 9-byte surname + ＊ + ▲.
# 姉ヶ崎先輩 is 15 bytes; "Anegasaki-senpai" is 16 and does not fit.
NENE_SURNAME_SLOTS: list[tuple[str, str]] = [
    ("▲姉ヶ崎＊▲", "▲Anegasaki＊▲"),
    ("「青春の１ページ：姉ヶ崎寧々」", '"A Page of Youth: Anegasaki Nene"'),
    ("［姉ヶ崎 菜々子］", "［Anegasaki Nanako］"),
    ("［姉ヶ崎 寧々］", "［Anegasaki Nene］"),
    ("姉ヶ崎の誕生日", "Nene's BD"),
    ("姉ヶ崎ちゃん", "Anegasaki-chan"),
    ("姉ヶ崎寧々", "Anegasaki Nene"),
    ("姉ヶ崎さん", "Anegasaki-san"),
    ("姉ヶ崎先輩", "Nene-senpai"),
    ("姉ヶ崎女史", "Ms Anegasaki"),
    ("姉ヶ崎", "Anegasaki"),
]

# Exact C strings. 高嶺 and Takane are both 6 bytes, and ▲高嶺＊＊▲ and
# ▲Takane＊＊▲ are both 18. The compact TOP高嶺愛花 slot is 15 bytes, so the
# full name there is TOPTakaneManaka with no space. ［高嶺 愛花］ already
# has a space and holds ［Takane Manaka］. 高嶺様 is 9 bytes; Takane-sama
# is 11 and does not fit. Longer rows are listed first.
MANAKA_SURNAME_SLOTS: list[tuple[str, str]] = [
    ("「青春の１ページ：高嶺愛花」", '"A Page of Youth: Takane Manaka"'),
    ("TOP［高嶺 愛花］", "TOP［Takane Manaka］"),
    ("［高嶺 珠深］", "［Takane Tamami］"),
    ("［高嶺 愛花］", "［Takane Manaka］"),
    ("高嶺の誕生日", "Manaka's BD"),
    ("▲高嶺＊＊▲", "▲Takane＊＊▲"),
    ("TOP高嶺愛花", "TOPTakaneManaka"),
    ("［高嶺 仁］", "［Takane Jin］"),
    ("高嶺ちゃん", "Takane-chan"),
    ("高嶺選手", "Takane"),
    ("高嶺さん", "Takane-san"),
    ("高嶺くん", "Takane-kun"),
    ("TOP高嶺", "TOPTakane"),
    ("高嶺様", "Takane"),
    ("高嶺", "Takane"),
]

# Exact C strings. Kobayakawa is 11 bytes and does not fit the 9-byte family
# slot. Kobayaka is 8, so the slot is NUL-padded. The marker is 17 bytes
# (▲ + Kobayaka + ＊ + ▲) and fits the 18-byte ▲小早川＊▲ slot the same way.
# Longer rows are listed first.
RINKO_SURNAME_SLOTS: list[tuple[str, str]] = [
    ("「青春の１ページ：小早川凛子」", '"A Page of Youth: Kobayakawa Rinko"'),
    ("［小早川 漂介］", "［Kobayaka Hyosuke］"),
    ("［小早川 潔美］", "［Kobayaka Kiyomi］"),
    ("［小早川 凛子］", "［Kobayaka Rinko］"),
    ("小早川の誕生日", "Rinko's BD"),
    ("▲小早川＊▲", "▲Kobayaka＊▲"),
    ("TOP小早川", "TOPKobayaka"),
    ("小早川ちゃん", "Kobayaka-chan"),
    ("［小早川 快］", "［Kobayaka Kai］"),
    ("小早川さん", "Kobayaka-san"),
    ("小早川くん", "Kobayaka-kun"),
    ("小早川凛子", "Kobayaka Rinko"),
    ("小早川氏", "Kobayaka"),
    ("小早川", "Kobayaka"),
]

IMG_NAME_REGION = (0x298FF000, 0x29908000)

# Machine translation rewrote control tokens into English words inside ▲ ▲.
# The protagonist still matches the Japanese marker. Manaka's family slot
# is Takane, Nene's is Anegasaki, and Rinko's is Kobayaka, so their markers
# follow those bytes.
CONTROL_TOKEN_RESTORES: dict[str, str] = {
    "▲the\nprotagonist＊▲": "▲主人公＊▲",
    "▲the protagonist＊▲": "▲主人公＊▲",
    "▲Main character＊▲": "▲主人公＊▲",
    "▲Protagonist＊▲": "▲主人公＊▲",
    "▲protagonist＊▲": "▲主人公＊▲",
    "▲Protagonist▲": "▲主人公＊▲",
    "▲Takamine ＊＊▲": "▲Takane＊＊▲",
    "▲高嶺＊＊▲": "▲Takane＊＊▲",
    "▲Kobayakawa＊▲": "▲Kobayaka＊▲",
    "▲小早川＊▲": "▲Kobayaka＊▲",
    "▲姉ヶ崎＊▲": "▲Anegasaki＊▲",
    "▲Anesaki＊▲": "▲Anegasaki＊▲",
    "▲Girlfriend＊＊▲": "▲彼女＊＊▲",
    "▲New protagonist▲": "▲新主人公▲",
    "▲Rinko's▲": "▲凛▲'s",
    "▲Rinko▲": "▲凛▲",
    "▲Rin▲": "▲凛▲",
    "▲Last Name▲": "▲苗字▲",
    "▲Last name▲": "▲苗字▲",
    "▲First Name▲": "▲名前▲",
    "▲Name▲": "▲名前▲",
    "▲Current day of the week▲": "▲現在曜日▲",
    "▲Day of the week▲": "▲曜日▲",
    "▲Current month▲": "▲現在月▲",
    "▲Current date▲": "▲現在日▲",
    "▲Current time▲": "▲現在時刻▲",
    "▲Meeting place▲": "▲待ち合わせ場所▲",
    "▲Date Location▲": "▲デート場所▲",
    "▲Date location▲": "▲デート場所▲",
    "▲Date place▲": "▲デート場所▲",
    "▲Introduced friend name▲": "▲紹介友達名▲",
    "▲Number of people▲": "▲人数▲",
    "▲Live house▲": "▲ライブハウス▲",
    "▲Event Hall▲": "▲イベントホール▲",
    "▲Event hall▲": "▲イベントホール▲",
    "▲Book name＊＊＊＊＊＊▲": "▲本の名前＊＊＊＊＊＊▲",
    "▲Restaurant＊＊＊＊＊▲": "▲飲食店＊＊＊＊＊▲",
    "▲Special date item**▲": "▲特別デートアイテム＊＊▲",
    "▲Spot name＊＊＊＊＊＊▲": "▲スポット名＊＊＊＊＊＊▲",
    "▲Cooking genre▲": "▲料理ジャンル▲",
    "▲Item name▲": "▲アイテム名▲",
    "▲HN＊＊＊＊▲": "▲ＨＮ＊＊＊＊▲",
    "▲Band＊▲": "▲バンド＊▲",
    "▲Subject▲": "▲教科▲",
    "▲Menu▲": "▲メニュー▲",
    "▲Moon▲": "▲月▲",
    "▲Day▲": "▲日▲",
    "▲Time▲": "▲時刻▲",
    "▲Area▲": "▲エリア▲",
}

_CONTROL_TOKEN_RE = re.compile(r"▲[^▲]*▲", re.DOTALL)


def restore_control_tokens(text: str) -> str:
    """Put English ▲…▲ placeholders back to the engine's Japanese tokens."""

    def repl(match: re.Match[str]) -> str:
        return CONTROL_TOKEN_RESTORES.get(match.group(0), match.group(0))

    return _CONTROL_TOKEN_RE.sub(repl, text)

PACKS = ("NLP_01", "NLP_02", "script")


# ---------------------------------------------------------------------------
# XOR helpers (NLPTextTool EncryptedBinary)
# ---------------------------------------------------------------------------

def _decrypt_byte(pos: int, value: int, key: int) -> int:
    kb = [key & 0xFF, (key >> 8) & 0xFF, (key >> 16) & 0xFF]
    seed = (key >> 24) & 0xFF
    return (value ^ ((kb[pos % 3] + (seed * (pos // 3))) & 0xFF)) & 0xFF


def _xor_u8(buf: bytearray, pos: int, key: int, value: int) -> None:
    buf[pos] = _decrypt_byte(pos, value & 0xFF, key)


def _xor_u16be(buf: bytearray, pos: int, key: int, value: int) -> None:
    _xor_u8(buf, pos, key, (value >> 8) & 0xFF)
    _xor_u8(buf, pos + 1, key, value & 0xFF)


def _xor_u32be(buf: bytearray, pos: int, key: int, value: int) -> None:
    _xor_u8(buf, pos, key, (value >> 24) & 0xFF)
    _xor_u8(buf, pos + 1, key, (value >> 16) & 0xFF)
    _xor_u8(buf, pos + 2, key, (value >> 8) & 0xFF)
    _xor_u8(buf, pos + 3, key, value & 0xFF)


def _read_u32be_xor(data: bytes, off: int, key: int) -> int:
    return (
        (_decrypt_byte(off, data[off], key) << 24)
        | (_decrypt_byte(off + 1, data[off + 1], key) << 16)
        | (_decrypt_byte(off + 2, data[off + 2], key) << 8)
        | _decrypt_byte(off + 3, data[off + 3], key)
    )


def _read_u16be_xor(data: bytes, off: int, key: int) -> int:
    return (_decrypt_byte(off, data[off], key) << 8) | _decrypt_byte(
        off + 1, data[off + 1], key
    )


def _read_utf8_xor(data: bytes, off: int, key: int) -> tuple[str, int]:
    length = _read_u16be_xor(data, off, key)
    raw = bytes(
        _decrypt_byte(off + 2 + i, data[off + 2 + i], key) for i in range(length)
    )
    return raw.decode("utf-8"), 2 + length


@dataclass
class SectionAEntry:
    value0: int
    value1: int


@dataclass
class UnknownEntry:
    values: list[SectionAEntry]
    value0: int
    value1: int


@dataclass
class SDL2Data:
    key: int
    unknown: list[UnknownEntry]
    dialogs: list[str]


@dataclass
class DbinEntry:
    unknown0: int
    unknown1: int
    sdl2: SDL2Data


def parse_sdl2(buf: bytes) -> SDL2Data:
    if buf[:4] != b"SDL2":
        raise ValueError("SDL2 signature missing")
    key = struct.unpack_from("<I", buf, 4)[0]
    table0 = _read_u16be_xor(buf, 8, key)
    dialogs_count = _read_u16be_xor(buf, 10, key)
    unknown: list[UnknownEntry] = []
    pos = 12
    for _ in range(table0):
        section_b = _read_u32be_xor(buf, pos, key)
        section_a = _read_u32be_xor(buf, pos + 4, key)
        pos += 8
        entries_n = _read_u32be_xor(buf, section_a, key)
        values = []
        a_off = section_a + 4
        for _ in range(entries_n):
            values.append(
                SectionAEntry(
                    _read_u32be_xor(buf, a_off, key),
                    _read_u32be_xor(buf, a_off + 4, key),
                )
            )
            a_off += 8
        unknown.append(
            UnknownEntry(
                values,
                _read_u32be_xor(buf, section_b, key),
                _read_u32be_xor(buf, section_b + 4, key),
            )
        )
    dialogs: list[str] = []
    for _ in range(dialogs_count):
        dialog_off = _read_u32be_xor(buf, pos, key)
        pos += 4
        text, _ = _read_utf8_xor(buf, dialog_off, key)
        dialogs.append(text)
    return SDL2Data(key, unknown, dialogs)


def build_sdl2(data: SDL2Data) -> bytes:
    section_a_length = len(data.unknown) * 4
    for entry in data.unknown:
        section_a_length += len(entry.values) * 8
    section_a_offset = 0xC + len(data.unknown) * 8 + len(data.dialogs) * 4
    section_b_offset = section_a_offset + section_a_length
    dialogs_offset = section_b_offset + len(data.unknown) * 8

    buf = bytearray(
        dialogs_offset + sum(len(d.encode("utf-8")) + 6 for d in data.dialogs) + 64
    )
    buf[0:4] = b"SDL2"
    struct.pack_into("<I", buf, 4, data.key)
    key = data.key
    _xor_u16be(buf, 8, key, len(data.unknown))
    _xor_u16be(buf, 10, key, len(data.dialogs))

    pos = 12
    cur_a = section_a_offset
    cur_b = section_b_offset
    for entry in data.unknown:
        _xor_u32be(buf, pos, key, cur_b)
        _xor_u32be(buf, pos + 4, key, cur_a)
        pos += 8

        _xor_u32be(buf, cur_a, key, len(entry.values))
        cur_a += 4
        for v in entry.values:
            _xor_u32be(buf, cur_a, key, v.value0)
            _xor_u32be(buf, cur_a + 4, key, v.value1)
            cur_a += 8

        _xor_u32be(buf, cur_b, key, entry.value0)
        _xor_u32be(buf, cur_b + 4, key, entry.value1)
        cur_b += 8

    cur_d = dialogs_offset
    for text in data.dialogs:
        _xor_u32be(buf, pos, key, cur_d)
        pos += 4
        raw = text.encode("utf-8")
        if len(raw) > 0xFFFF:
            raise ValueError("dialog too long")
        _xor_u16be(buf, cur_d, key, len(raw))
        for i, b in enumerate(raw):
            _xor_u8(buf, cur_d + 2 + i, key, b)
        cur_d += 2 + len(raw)
        while cur_d & 3:
            _xor_u8(buf, cur_d, key, 0)
            cur_d += 1

    return bytes(buf[:cur_d])


def parse_dbin2(data: bytes) -> tuple[int, int, list[DbinEntry]]:
    if data[:4] != b"DBN2":
        raise ValueError("DBN2 signature missing")
    key = struct.unpack_from("<I", data, 4)[0]
    entries_n = _read_u32be_xor(data, 8, key)
    unknown = _read_u32be_xor(data, 12, key)
    entries: list[DbinEntry] = []
    for i in range(entries_n):
        base = 0x10 + i * 0x10
        unk0 = _read_u32be_xor(data, base, key)
        unk1 = _read_u32be_xor(data, base + 4, key)
        off = _read_u32be_xor(data, base + 8, key)
        length = _read_u32be_xor(data, base + 12, key)
        sdl2 = parse_sdl2(data[off : off + length])
        entries.append(DbinEntry(unk0, unk1, sdl2))
    return key, unknown, entries


def build_dbin2(key: int, unknown: int, entries: list[DbinEntry]) -> bytes:
    data_offset = 0x10 + len(entries) * 0x10
    sdl2_bufs = [build_sdl2(e.sdl2) for e in entries]
    total = data_offset + sum(len(b) + 7 for b in sdl2_bufs)
    out = bytearray(total)
    out[0:4] = b"DBN2"
    struct.pack_into("<I", out, 4, key)
    _xor_u32be(out, 8, key, len(entries))
    _xor_u32be(out, 12, key, unknown)

    cur = data_offset
    for i, (entry, buf) in enumerate(zip(entries, sdl2_bufs)):
        base = 0x10 + i * 0x10
        _xor_u32be(out, base, key, entry.unknown0)
        _xor_u32be(out, base + 4, key, entry.unknown1)
        _xor_u32be(out, base + 8, key, cur)
        _xor_u32be(out, base + 12, key, len(buf))
        out[cur : cur + len(buf)] = buf
        cur += len(buf)
        while cur & 7:
            _xor_u8(out, cur, key, 0)
            cur += 1
    return bytes(out[:cur])


def replace_dialog_tokens(text: str) -> tuple[str, int]:
    n = 0
    for old, new in DBIN_REPLACEMENTS:
        c = text.count(old)
        if c:
            text = text.replace(old, new)
            n += c
    text2, m = TRAILING_PAD_RE.subn(r"\1", text)
    return text2, n + m


def rewrite_nene_token_text(text: str) -> str:
    """Point Nene's nickname marker at the live Anegasaki surname slot."""
    if "▲姉ヶ崎＊" not in text:
        return text
    return text.replace("▲姉ヶ崎＊▲", "▲Anegasaki＊▲").replace("▲姉ヶ崎＊", "▲Anegasaki＊")


def _rewrite_nene_dbin2(data: bytes, *, speakers: bool) -> bytes:
    if len(data) < 4 or data[:4] != b"DBN2":
        return data
    key, unknown, entries = parse_dbin2(data)
    changed = False
    for entry in entries:
        dialogs = entry.sdl2.dialogs
        for i, text in enumerate(dialogs):
            new = rewrite_nene_token_text(text)
            if speakers and new == "姉ヶ崎":
                new = "Anegasaki"
            if new != text:
                dialogs[i] = new
                changed = True
    if not changed:
        return data
    return build_dbin2(key, unknown, entries)


def rewrite_nene_nickname_tokens(data: bytes) -> bytes:
    """Swap ▲姉ヶ崎＊▲ for ▲Anegasaki＊▲. Nameplates are left as they are."""
    return _rewrite_nene_dbin2(data, speakers=False)


def rewrite_manaka_token_text(text: str) -> str:
    """Point Manaka's nickname marker at the live Takane surname slot."""
    if "▲高嶺＊＊" not in text:
        return text
    return text.replace("▲高嶺＊＊▲", "▲Takane＊＊▲").replace("▲高嶺＊＊", "▲Takane＊＊")


def _rewrite_manaka_dbin2(data: bytes, *, speakers: bool) -> bytes:
    if len(data) < 4 or data[:4] != b"DBN2":
        return data
    key, unknown, entries = parse_dbin2(data)
    changed = False
    for entry in entries:
        dialogs = entry.sdl2.dialogs
        for i, text in enumerate(dialogs):
            new = rewrite_manaka_token_text(text)
            if speakers and new == "高嶺":
                new = "Takane"
            if new != text:
                dialogs[i] = new
                changed = True
    if not changed:
        return data
    return build_dbin2(key, unknown, entries)


def rewrite_manaka_nickname_tokens(data: bytes) -> bytes:
    """Swap ▲高嶺＊＊▲ for ▲Takane＊＊▲. Nameplates are left as they are."""
    return _rewrite_manaka_dbin2(data, speakers=False)


def rewrite_manaka_surname_speakers(data: bytes) -> bytes:
    """Nameplate dialog that is exactly 高嶺 becomes Takane.

    The nickname marker becomes ▲Takane＊＊▲. Anything that is not a DBN2
    script is returned unchanged.
    """
    return _rewrite_manaka_dbin2(data, speakers=True)


def rewrite_rinko_token_text(text: str) -> str:
    """Point Rinko's nickname marker at the live Kobayaka surname slot."""
    if "▲小早川＊" not in text:
        return text
    return text.replace("▲小早川＊▲", "▲Kobayaka＊▲").replace("▲小早川＊", "▲Kobayaka＊")


def _rewrite_rinko_dbin2(data: bytes, *, speakers: bool) -> bytes:
    if len(data) < 4 or data[:4] != b"DBN2":
        return data
    key, unknown, entries = parse_dbin2(data)
    changed = False
    for entry in entries:
        dialogs = entry.sdl2.dialogs
        for i, text in enumerate(dialogs):
            new = rewrite_rinko_token_text(text)
            if speakers and new == "小早川":
                new = "Kobayaka"
            if new != text:
                dialogs[i] = new
                changed = True
    if not changed:
        return data
    return build_dbin2(key, unknown, entries)


def rewrite_rinko_nickname_tokens(data: bytes) -> bytes:
    """Swap ▲小早川＊▲ for ▲Kobayaka＊▲. Nameplates are left as they are."""
    return _rewrite_rinko_dbin2(data, speakers=False)


def rewrite_rinko_surname_speakers(data: bytes) -> bytes:
    """Nameplate dialog that is exactly 小早川 becomes Kobayaka.

    The nickname marker becomes ▲Kobayaka＊▲. Anything that is not a DBN2
    script is returned unchanged.
    """
    return _rewrite_rinko_dbin2(data, speakers=True)


def rewrite_nene_surname_speakers(data: bytes) -> bytes:
    """Nameplate dialog that is exactly 姉ヶ崎 becomes Anegasaki.

    The nickname marker becomes ▲Anegasaki＊▲ so it matches the live
    family-name slot. Anything that is not a DBN2 script is returned unchanged.
    """
    return _rewrite_nene_dbin2(data, speakers=True)


def patch_dbin2_file(path: Path, *, strip_tokens: bool = False) -> int:
    if not strip_tokens:
        return 0
    key, unknown, entries = parse_dbin2(path.read_bytes())
    total = 0
    for entry in entries:
        for i, dialog in enumerate(entry.sdl2.dialogs):
            new, n = replace_dialog_tokens(dialog)
            if n:
                entry.sdl2.dialogs[i] = new
                total += n
    if total:
        path.write_bytes(build_dbin2(key, unknown, entries))
    return total


def patch_dbin2_tree(root: Path, *, strip_tokens: bool = False) -> tuple[int, int]:
    """Patch NLP_01/NLP_02/script under root (or a flat tree of *.dbin2)."""
    if not strip_tokens:
        return 0, 0
    files: list[Path] = []
    for pack in PACKS:
        pack_dir = root / pack
        if pack_dir.is_dir():
            files.extend(sorted(pack_dir.glob("*.dbin2")))
    if not files:
        files = sorted(root.rglob("*.dbin2"))
    touched = 0
    replacements = 0
    for path in files:
        n = patch_dbin2_file(path, strip_tokens=True)
        if n:
            touched += 1
            replacements += n
    return touched, replacements


def replace_all(data: bytearray, old: str, new: str) -> int:
    old_b = old.encode("utf-8")
    new_b = new.encode("utf-8")
    if len(new_b) > len(old_b):
        raise ValueError(
            f"{new!r} is {len(new_b)} bytes but slot for {old!r} is only {len(old_b)}"
        )
    padded = new_b + b"\x00" * (len(old_b) - len(new_b))
    count = 0
    start = 0
    while True:
        i = data.find(old_b, start)
        if i < 0:
            break
        data[i : i + len(old_b)] = padded
        count += 1
        start = i + len(old_b)
    return count


def replace_exact_cstring(data: bytearray, old: str, new: str) -> int:
    """Replace ``old`` only when it is a whole NUL-terminated string.

    Shorter English is padded with NULs inside the original byte span.
    A hit inside a longer string (the nickname marker) is left alone.
    The markers themselves are exact slots in MANAKA_SURNAME_SLOTS,
    NENE_SURNAME_SLOTS, and RINKO_SURNAME_SLOTS.
    """
    old_b = old.encode("utf-8")
    new_b = new.encode("utf-8")
    if not old_b:
        raise ValueError("empty C string")
    if len(new_b) > len(old_b):
        raise ValueError(
            f"{new!r} is {len(new_b)} bytes but slot for {old!r} is only {len(old_b)}"
        )
    padded = new_b + b"\x00" * (len(old_b) - len(new_b))
    count = 0
    start = 0
    while True:
        i = data.find(old_b, start)
        if i < 0:
            break
        end = i + len(old_b)
        prev_ok = i == 0 or data[i - 1] == 0
        next_ok = end < len(data) and data[end] == 0
        if prev_ok and next_ok:
            data[i:end] = padded
            count += 1
            start = end
        else:
            start = i + 1
    return count


def patch_nene_surname_bytes(data: bytearray) -> int:
    """English display for Nene's surname and her ▲Anegasaki＊▲ marker."""
    total = 0
    for old, new in NENE_SURNAME_SLOTS:
        total += replace_exact_cstring(data, old, new)
    return total


def patch_rinko_surname_bytes(data: bytearray) -> int:
    """English display for Rinko's surname and her ▲Kobayaka＊▲ marker."""
    total = 0
    for old, new in RINKO_SURNAME_SLOTS:
        total += replace_exact_cstring(data, old, new)
    return total


def patch_manaka_surname_bytes(data: bytearray) -> int:
    """English display for Manaka's surname and her ▲Takane＊＊▲ marker."""
    total = 0
    for old, new in MANAKA_SURNAME_SLOTS:
        total += replace_exact_cstring(data, old, new)
    return total


def patch_name_table_bytes(data: bytearray) -> int:
    # Surname slots first. 寧々 → Nene would otherwise NUL-truncate
    # 姉ヶ崎寧々 and the cast-list rows that contain it.
    total = patch_nene_surname_bytes(data)
    total += patch_rinko_surname_bytes(data)
    total += patch_manaka_surname_bytes(data)
    for old, new in TOKEN_REPLACEMENTS + NAME_REPLACEMENTS:
        total += replace_all(data, old, new)
    for old, new in EXACT_NAME_REPLACEMENTS:
        total += replace_exact_cstring(data, old, new)
    return total


def patch_resident_file(path: Path) -> int:
    data = bytearray(path.read_bytes())
    total = patch_name_table_bytes(data)
    if total:
        path.write_bytes(data)
    return total


def patch_img_name_table(path: Path) -> int:
    start, end = IMG_NAME_REGION
    data = bytearray(path.read_bytes())
    if end > len(data):
        raise ValueError(f"{path}: file too small for name table region")
    window = bytearray(data[start:end])
    total = patch_name_table_bytes(window)
    if total:
        data[start:end] = window
        path.write_bytes(data)
    return total


def apply_romfs_name_patches(
    romfs_dir: Path,
    *,
    strip_dialog_tokens: bool = False,
) -> dict[str, int]:
    """Patch resident TRB + img.bin; optionally legacy dbin2 token stripping."""
    stats = {"dbin_files": 0, "dbin_repl": 0, "resident": 0, "img": 0}
    script_root = romfs_dir / "script" / "bin"
    if script_root.is_dir() and strip_dialog_tokens:
        touched, repl = patch_dbin2_tree(script_root, strip_tokens=True)
        stats["dbin_files"] = touched
        stats["dbin_repl"] = repl
        print(f"[names] dbin2 (strip): {touched} files, {repl} replacements")
    elif script_root.is_dir():
        print("[names] dbin2: kept dialog tokens (nickname slots)")

    resident = (
        romfs_dir / "SystemData" / "TextResource" / "textresource_resident_jpn.trb"
    )
    if resident.is_file():
        stats["resident"] = patch_resident_file(resident)
        print(f"[names] resident TRB: {stats['resident']} replacements")
    else:
        print(f"[names] resident TRB not found under {romfs_dir}")

    img = romfs_dir / "img.bin"
    if img.is_file():
        stats["img"] = patch_img_name_table(img)
        print(f"[names] img.bin name table: {stats['img']} replacements")
    else:
        print(f"[names] img.bin not found under {romfs_dir}")
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--romfs",
        type=Path,
        help="Extracted RomFS root — patch script/bin + resident + img.bin",
    )
    ap.add_argument(
        "--dbin",
        type=Path,
        help="Folder with NLP_01/NLP_02/script *.dbin2 (or any tree of .dbin2)",
    )
    ap.add_argument("--resident", type=Path, help="textresource_resident_jpn.trb")
    ap.add_argument("--img", type=Path, help="img.bin")
    ap.add_argument(
        "--strip-dialog-tokens",
        action="store_true",
        help="legacy: expand ▲高嶺＊＊▲ to plain Takane in dbin2 (breaks nicknames)",
    )
    args = ap.parse_args(argv)

    did = False
    if args.romfs:
        apply_romfs_name_patches(
            args.romfs.resolve(),
            strip_dialog_tokens=args.strip_dialog_tokens,
        )
        did = True
    if args.dbin:
        touched, repl = patch_dbin2_tree(
            args.dbin.resolve(),
            strip_tokens=args.strip_dialog_tokens,
        )
        if args.strip_dialog_tokens:
            print(f"[names] dbin2: {touched} files, {repl} replacements")
        else:
            print("[names] dbin2: no changes (pass --strip-dialog-tokens to expand)")
        did = True
    if args.resident:
        n = patch_resident_file(args.resident.resolve())
        print(f"[names] resident: {n} replacements")
        did = True
    if args.img:
        n = patch_img_name_table(args.img.resolve())
        print(f"[names] img.bin: {n} replacements")
        did = True
    if not did:
        ap.error("pass at least one of --romfs / --dbin / --resident / --img")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
