#!/usr/bin/env python3
"""Weekly forecast day names: S M T W Th F Sa.

Pack 0xD001 (INDX cat 0xD0 sub 1) slots 0–6 are the bare weekday kanji
日 月 火 水 木 金 土. Those STRI rows are shared with the day counter and
the month unit, whose English is " Day(s)" / "Month" / "fire" / …. The
forecast draws slots 0–6, so retarget only those slots. Slots 7–13 are
the parenthesized names already used by the day counter.
"""
from __future__ import annotations

import struct

from patch_password_serials import _pack_trb, _slot_text, _strb_used, _sub_u16_off

WEEKDAY_CAT = 0xD0
WEEKDAY_SUB = 1
# Slot 0 is Sunday. The forecast walks the calendar, so Tuesday is slot 2.
WEEKDAY_LABELS: tuple[str, ...] = ("S", "M", "T", "W", "Th", "F", "Sa")


def apply_weather_weekdays(data: bytes) -> tuple[bytes, list[str]]:
    """Append one UTF-8 label per weekday and retarget slots 0–6."""
    chunks = parse_needed(data)
    stri = bytearray(chunks["STRI"])
    strb = bytearray(chunks["STRB"])
    indx = bytearray(chunks["INDX"])
    u16_off, slot_count = _sub_u16_off(indx, WEEKDAY_CAT, WEEKDAY_SUB)
    if slot_count < len(WEEKDAY_LABELS):
        raise ValueError(f"weekday slots {slot_count} < {len(WEEKDAY_LABELS)}")
    logs: list[str] = []
    n_entries = sum(1 for _ in iter_stri(stri))
    used = _strb_used(stri, strb)
    strb = strb[:used]
    changed = False

    for slot, label in enumerate(WEEKDAY_LABELS):
        cur_idx = struct.unpack_from("<H", indx, u16_off + slot * 2)[0]
        flag, text = _slot_text(stri, strb, cur_idx)
        if flag == 1 and text == label:
            logs.append(f"slot {slot} already {label}")
            continue
        payload = label.encode("ascii")
        new_idx = n_entries
        stri += struct.pack("<IHH", len(strb), len(payload), 1)
        strb += payload + b"\x00"
        n_entries += 1
        struct.pack_into("<H", indx, u16_off + slot * 2, new_idx)
        logs.append(f"slot {slot} -> {label} stri={new_idx}")
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
