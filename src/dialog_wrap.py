"""Break English script lines at spaces before the game breaks them mid-word.

The talk window and the choice buttons run their text through
``FUN_005bf750`` (file ``0x005BF750``) after name markers are filled in.
It walks the string by codepoint: below U+0080 is one column, anything else
is two (``？``, ``…``, ``「``), and ``\\n`` resets the count. When a line
passes the width it puts a ``\\n`` in front of the character that crossed
it. The only look-back is the Japanese kinsoku table, so English is cut
wherever the column lands: "for exa\\nmple".

    caller        width   text
    0x0013BC40    30      talk window (also 0x0013E7F4)
    0x00140EA4    28      choice buttons, four 0x80-byte slots

A choice option is named by an SDL2 command whose first word is
``0x0001NNNN`` with an empty value list, NNNN being the dialog index
(``まあいいか`` / ``自分でやれって`` in k142 are ``0x10007`` / ``0x10008``).
Talk commands carry the index as ``N << 16`` instead. Choice options are
held to 28 columns and everything else to 30. A dialog whose lines already
fit is left alone.

Markers are filled in at run time, so they are budgeted at a fixed width.
Names use ``NAME_COLUMNS``; a longer name than that can still be cut.
Dialogs with kana or kanji are left to the game's own kinsoku wrap.

Before the wrap, ``fit_font`` swaps characters the dialog font cannot draw.
The talk font is the game's own bitmap set (``img.bin`` entries 5370/5371,
``FNTB``), not the system font. It has all printable ASCII and the Japanese
punctuation but no em dash, en dash, wave dash, or accented Latin letters,
so "presents—just" would draw as "presentsjust". Vanilla Japanese uses
nothing outside it.
"""
from __future__ import annotations

import re
import struct
import unicodedata

from patch_names import DbinEntry, SDL2Data, build_dbin2, parse_dbin2

TALK_COLUMNS = 30
CHOICE_COLUMNS = 28

NAME_COLUMNS = 8
OTHER_MARKER_COLUMNS = 16
MARKER_COLUMNS: dict[str, int] = {
    "●": NAME_COLUMNS,
    "▲主人公＊▲": NAME_COLUMNS,
    "▲新主人公▲": NAME_COLUMNS,
    "▲彼女＊＊▲": NAME_COLUMNS,
    "▲苗字▲": NAME_COLUMNS,
    "▲名前▲": NAME_COLUMNS,
    "▲ＨＮ＊＊＊＊▲": NAME_COLUMNS,
    "▲月▲": 9,  # September
    "▲現在月▲": 9,
    "▲日▲": 4,  # 31st
    "▲現在日▲": 4,
    "▲曜日▲": 9,  # Wednesday
    "▲現在曜日▲": 9,
    "▲時▲": 5,
    "▲時刻▲": 8,  # 12:30 PM
    "▲現在時刻▲": 8,
}
# Heroine nickname keys: the family-name slot padded with ＊ (English or JP).
_NICKNAME_RE = re.compile(r"▲(?:Takane|Kobayaka|Anegasaki|高嶺|小早川|姉ヶ崎)＊+▲")
_MARKER_RE = re.compile(r"▲[^▲\n]*▲|●")
_WORD_RE = re.compile(r"(?:▲[^▲]*▲|\S)+")
_JAPANESE_RE = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")
_HYPHEN_END_RE = re.compile(r"[A-Za-z]-$")

# Not in the FNTB set -> the nearest glyph it has. ― (U+2015) is the dash the
# hand-made scripts already use.
FONT_SUBSTITUTES = str.maketrans({"—": "―", "–": "-", "〜": "～"})
# Accented Latin letters (Latin-1 to Latin Extended-B, minus × and ÷).
_ACCENTED_RE = re.compile(r"[À-ÖØ-öø-ɏ]")
# A line break the translation typed out as backslash + n.
_TYPED_BREAK_RE = re.compile(r"\\n")


def fit_font(text: str) -> str:
    """Swap glyphs the dialog font lacks; turn a typed-out ``\\n`` into a break."""
    text = text.translate(FONT_SUBSTITUTES)
    if _TYPED_BREAK_RE.search(text):
        text = _TYPED_BREAK_RE.sub("\n", text).strip("\n")
    return _ACCENTED_RE.sub(
        lambda m: unicodedata.normalize("NFKD", m.group(0))[0], text
    )


def marker_columns(marker: str) -> int:
    if _NICKNAME_RE.fullmatch(marker):
        return NAME_COLUMNS
    return MARKER_COLUMNS.get(marker, OTHER_MARKER_COLUMNS)


def columns(text: str) -> int:
    """Columns the game counts for one line, with markers at their budget."""
    total = 0
    pos = 0
    for m in _MARKER_RE.finditer(text):
        total += sum(1 if ord(c) < 0x80 else 2 for c in text[pos : m.start()])
        total += marker_columns(m.group(0))
        pos = m.end()
    return total + sum(1 if ord(c) < 0x80 else 2 for c in text[pos:])


def game_would_break(text: str, width: int = TALK_COLUMNS) -> bool:
    return any(columns(line) > width for line in text.split("\n"))


def choice_dialogs(sdl2: SDL2Data) -> set[int]:
    """Dialog indexes this entry shows as choice buttons."""
    return {
        cmd.value0 & 0xFFFF
        for cmd in sdl2.unknown
        if cmd.value0 >> 16 == 1 and not cmd.values and cmd.value0 & 0xFFFF
    }


def _join_lines(lines: list[str]) -> str:
    """One paragraph. A hand-hyphenated "spring-\\ntime" stays "spring-time"."""
    out = lines[0].rstrip()
    for line in lines[1:]:
        line = line.strip()
        if _HYPHEN_END_RE.search(out) and line[:1].isalpha():
            out += line
        else:
            out += " " + line
    return out


def wrap_dialog(text: str, width: int = TALK_COLUMNS) -> str:
    """Re-flow ``text`` at spaces to ``width`` if the game would cut it."""
    if _JAPANESE_RE.search(_MARKER_RE.sub("", text)) or not game_would_break(text, width):
        return text
    words = _WORD_RE.findall(_join_lines(text.split("\n")))
    if not words:
        return text
    lines: list[str] = []
    cur = words[0]
    used = columns(cur)
    for word in words[1:]:
        w = columns(word)
        if used + 1 + w > width:
            lines.append(cur)
            cur, used = word, w
        else:
            cur += " " + word
            used += 1 + w
    lines.append(cur)
    return "\n".join(lines)


def wrap_dbin2(data: bytes) -> bytes:
    """Fit and re-flow every dialog in a ``.dbin2``. Unchanged files keep their bytes."""
    try:
        key, unknown, entries = parse_dbin2(data)
    except (ValueError, IndexError, UnicodeDecodeError, struct.error):
        return data
    changed = False
    out: list[DbinEntry] = []
    for entry in entries:
        choices = choice_dialogs(entry.sdl2)
        dialogs = [
            wrap_dialog(fit_font(d), CHOICE_COLUMNS if i in choices else TALK_COLUMNS)
            for i, d in enumerate(entry.sdl2.dialogs)
        ]
        changed |= dialogs != entry.sdl2.dialogs
        sdl2 = SDL2Data(entry.sdl2.key, entry.sdl2.unknown, dialogs)
        out.append(DbinEntry(entry.unknown0, entry.unknown1, sdl2))
    return build_dbin2(key, unknown, out) if changed else data
