#!/usr/bin/env python3
"""Web weather dates and day names in ASCII: 10/20 Tue, Su Mo Tu We Th Fr Sa.

The weather string builder (code.bin 0x5cc680) is the only reader of
packs 0xD000–0xD002 (INDX cat 0xD0 subs 0–2). It glues dates together
from vanilla full-width pieces, and full-width glyphs are one em wide,
so ``１０／２０`` and ``Ｔｕｅ`` draw with gaps between every character.

- 0xD000 slots 0–1: date formats ``%s%s／%s%s`` and ``…～…``.
- 0xD001 slots 0–6: bare weekday kanji 日 月 火 … for the forecast row.
  Slots 7–13: （日）… for today's date (translated to ``Ｓｕｎ``…).
  Those STRI rows are shared with the day counter and the month unit,
  whose English is " Day(s)" / "Month" / "fire" / ….
- 0xD002 slots 0–31: ``０``–``３１``, the date digits and day numbers.

Append one ASCII row per slot and retarget only these INDX slots, so the
shared STRI rows keep their text everywhere else.
"""
from __future__ import annotations

import struct

from patch_password_serials import _pack_trb, _slot_text, _strb_used, _sub_u16_off

WEEKDAY_CAT = 0xD0
FORMAT_SUB = 0
WEEKDAY_SUB = 1
DIGIT_SUB = 2
DATE_FORMATS: tuple[str, ...] = ("%s%s/%s%s", "%s%s/%s%s-%s%s/%s%s")
# Slot 0 is Sunday. The forecast walks the calendar, so Tuesday is slot 2.
WEEKDAY_LABELS: tuple[str, ...] = ("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")
TODAY_LABELS: tuple[str, ...] = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
DIGIT_LABELS: tuple[str, ...] = tuple(str(n) for n in range(32))

# (sub, first slot, labels)
_ROWS: tuple[tuple[int, int, tuple[str, ...]], ...] = (
    (FORMAT_SUB, 0, DATE_FORMATS),
    (WEEKDAY_SUB, 0, WEEKDAY_LABELS),
    (WEEKDAY_SUB, 7, TODAY_LABELS),
    (DIGIT_SUB, 0, DIGIT_LABELS),
)


def apply_weather_weekdays(data: bytes) -> tuple[bytes, list[str]]:
    """Append one ASCII label per weather slot and retarget those slots."""
    chunks = parse_needed(data)
    stri = bytearray(chunks["STRI"])
    strb = bytearray(chunks["STRB"])
    indx = bytearray(chunks["INDX"])
    logs: list[str] = []
    n_entries = sum(1 for _ in iter_stri(stri))
    used = _strb_used(stri, strb)
    strb = strb[:used]
    changed = False

    for sub, first, labels in _ROWS:
        u16_off, slot_count = _sub_u16_off(indx, WEEKDAY_CAT, sub)
        if slot_count < first + len(labels):
            raise ValueError(
                f"pack {WEEKDAY_CAT:02x}{sub:02x} slots {slot_count} < {first + len(labels)}"
            )
        for slot, label in enumerate(labels, start=first):
            cur_idx = struct.unpack_from("<H", indx, u16_off + slot * 2)[0]
            flag, text = _slot_text(stri, strb, cur_idx)
            tag = f"{WEEKDAY_CAT:02x}{sub:02x}[{slot}]"
            if flag == 1 and text == label:
                logs.append(f"{tag} already {label}")
                continue
            payload = label.encode("ascii")
            new_idx = n_entries
            stri += struct.pack("<IHH", len(strb), len(payload), 1)
            strb += payload + b"\x00"
            n_entries += 1
            struct.pack_into("<H", indx, u16_off + slot * 2, new_idx)
            logs.append(f"{tag} -> {label} stri={new_idx}")
            changed = True

    if not changed:
        return data, logs

    pad = (4 - (len(strb) % 4)) % 4
    if pad:
        strb += b"\xc9" * pad
    chunks["STRI"] = bytes(stri)
    chunks["STRB"] = bytes(strb)
    chunks["INDX"] = bytes(indx)
    return _pack_trb(chunks), logs


def parse_needed(data: bytes) -> dict:
    from patch_textresource import parse_chunks

    return parse_chunks(data)


def iter_stri(stri: bytes):
    from patch_textresource import iter_entries

    return iter_entries(stri)
