#!/usr/bin/env python3
"""Turn Options password serial holes into shared Love Plus-themed codes.

Pack ``0xb000`` (INDX cat 176 sub 0) is strcmp'd by ``FUN_00132d40`` for
slots 0..52. Magazine codes already fill most slots. Empty holes all point
at the shared placeholder ``なし`` (STRI 24550):

  24-26  VISAカード     → Your Nickname (per girl)
  27-29  ラブプラスぴあ → Pia muffler (per girl)
  33-40  内部           → eight internal unlocks
  (ウリボー傘 has no vanilla 0xb000 slot. UriboKasa* occupy 33–35; the
  present grant is ``patch_password_uribo.py`` so those bits add item
  ids 465–467 instead of 内部 flags.)

Do **not** rewrite STRI 24550 globally. Append unique UTF-8 STRI rows and
retarget those INDX slots. Idempotent if the slots already hold these codes.
"""

from __future__ import annotations

import struct

from patch_textresource import iter_entries, parse_chunks

PASSWORD_CAT = 176
PASSWORD_SUB = 0

# slot → ASCII code (ABC keyboard; mixed case like vanilla magazine passwords)
SHARED_SERIALS: tuple[tuple[int, str, str], ...] = (
    # VISA / 十羽野 student ID → Your Nickname
    (24, "JuhanoManaka", "VISA nickname Manaka"),
    (25, "JuhanoRinko", "VISA nickname Rinko"),
    (26, "JuhanoNene", "VISA nickname Nene"),
    # ラブプラスぴあ muffler
    (27, "PiaMufflerM", "Pia muffler Manaka"),
    (28, "PiaMufflerR", "Pia muffler Rinko"),
    (29, "PiaMufflerN", "Pia muffler Nene"),
    # ウリボー傘 (grant via patch_password_uribo.py, not vanilla 内部)
    (33, "UriboKasaM", "Uribo umbrella Manaka"),
    (34, "UriboKasaR", "Uribo umbrella Rinko"),
    (35, "UriboKasaN", "Uribo umbrella Nene"),
    (36, "SpecGallery", "internal special gallery"),
    (37, "MeishiPaper", "internal card templates"),
    (38, "MeishiSeal", "internal card stickers"),
    (39, "AllCostumes", "internal all costumes"),
    (40, "KiseVoice", "internal all voice messages"),
)


def _pack_trb(chunks: dict) -> bytes:
    out = bytearray()
    for name in chunks["_order"]:
        body = chunks[name]
        out += name.encode("ascii")
        out += struct.pack("<I", len(body))
        out += body
    if "_tail" in chunks:
        out += chunks["_tail"]
    return bytes(out)


def _sub_u16_off(indx: bytes, cat: int, sub: int) -> tuple[int, int]:
    """Return (offset of first u16 STRI index, slot_count) for cat/sub."""
    if len(indx) < 0x400:
        raise ValueError("INDX too small")
    cat_off = struct.unpack_from("<I", indx, cat * 4)[0]
    if cat_off == 0 or cat_off >= len(indx):
        raise ValueError(f"INDX cat {cat} missing")
    sub_count = struct.unpack_from("<I", indx, cat_off)[0]
    if sub >= sub_count:
        raise ValueError(f"INDX cat {cat} has no sub {sub}")
    rel = struct.unpack_from("<I", indx, cat_off + 4 + sub * 4)[0]
    sub_off = cat_off + rel
    slot_count = struct.unpack_from("<I", indx, sub_off)[0]
    return sub_off + 4, slot_count


def _strb_used(stri: bytes, strb: bytes) -> int:
    last = None
    for _idx, _off, stringindex, bytelength, flag in iter_entries(stri):
        last = (stringindex, bytelength, flag)
    if last is None:
        return 0
    stringindex, bytelength, flag = last
    if flag == 2:
        return stringindex
    return min(len(strb), stringindex + bytelength + 1)


def _slot_text(stri: bytes, strb: bytes, stri_idx: int) -> tuple[int, str]:
    entries = list(iter_entries(stri))
    if not (0 <= stri_idx < len(entries)):
        return -1, ""
    _idx, _off, stringindex, _bl, flag = entries[stri_idx]
    if flag != 1:
        return flag, ""
    end = strb.find(b"\x00", stringindex)
    if end < 0:
        end = len(strb)
    return flag, strb[stringindex:end].decode("ascii", errors="replace")


def apply_shared_serial_passwords(data: bytes) -> tuple[bytes, list[str]]:
    """Append unique UTF-8 codes and retarget pack 0xb000 serial holes."""
    chunks = parse_chunks(data)
    stri = bytearray(chunks["STRI"])
    strb = bytearray(chunks["STRB"])
    indx = bytearray(chunks["INDX"])
    u16_off, slot_count = _sub_u16_off(indx, PASSWORD_CAT, PASSWORD_SUB)
    logs: list[str] = []
    n_entries = sum(1 for _ in iter_entries(stri))
    used = _strb_used(stri, strb)
    strb = strb[:used]
    changed = False

    for slot, code, label in SHARED_SERIALS:
        if slot >= slot_count:
            raise ValueError(f"password slot {slot} >= {slot_count}")
        cur_idx = struct.unpack_from("<H", indx, u16_off + slot * 2)[0]
        flag, text = _slot_text(stri, strb, cur_idx)
        if flag == 1 and text == code:
            logs.append(f"slot {slot} already {code} ({label})")
            continue
        payload = code.encode("ascii")
        new_idx = n_entries
        stri += struct.pack("<IHH", len(strb), len(payload), 1)
        strb += payload + b"\x00"
        n_entries += 1
        struct.pack_into("<H", indx, u16_off + slot * 2, new_idx)
        logs.append(f"slot {slot} -> {code} ({label}) stri={new_idx}")
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
