"""NLPP MDC (maildic_*.mdc) codec — SMS / mail dictionary blobs in img.bin pkg 92.

On-disk layout (exact round-trip verified against vanilla maildic_{m,n,r}.mdc):

  u16le  count
  repeat count times:
    u64be  key
    u64be  meta          # flags / category; often 0
    u8     strlen        # includes trailing NUL
    utf-8 bytes + 0x00

Not related to romfs/dictionary/all2_u.bin (NintendoWare IME dict).
Not the experimental NLPMAIL1 container in nlp_loc.sms_pack.
"""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MdcEntry:
    key: int
    meta: int
    text: str


def parse_mdc(data: bytes) -> list[MdcEntry]:
    if len(data) < 2:
        raise ValueError("MDC too small")
    (count,) = struct.unpack_from("<H", data, 0)
    out: list[MdcEntry] = []
    i = 2
    for n in range(count):
        if i + 17 > len(data):
            raise ValueError(f"truncated MDC header at record {n} off={i}")
        key = int.from_bytes(data[i : i + 8], "big")
        meta = int.from_bytes(data[i + 8 : i + 16], "big")
        strlen = data[i + 16]
        end = i + 17 + strlen
        if end > len(data):
            raise ValueError(f"truncated MDC text at record {n}")
        text_b = data[i + 17 : end]
        if not text_b.endswith(b"\x00"):
            raise ValueError(f"MDC record {n} missing NUL (strlen={strlen})")
        out.append(MdcEntry(key, meta, text_b[:-1].decode("utf-8")))
        i = end
    return out


def pack_mdc(entries: list[MdcEntry]) -> bytes:
    out = bytearray()
    out += struct.pack("<H", len(entries))
    for e in entries:
        payload = e.text.encode("utf-8") + b"\x00"
        if len(payload) > 255:
            raise ValueError(
                f"SMS too long for u8 strlen: {len(payload)} bytes key={e.key:#x}"
            )
        out += e.key.to_bytes(8, "big")
        out += e.meta.to_bytes(8, "big")
        out += bytes([len(payload)])
        out += payload
    return bytes(out)


def pad_to_size(blob: bytes, size: int, pad: bytes = b"\xff") -> bytes:
    if len(blob) > size:
        raise ValueError(f"MDC grew past slot: {len(blob)} > {size}")
    if len(blob) == size:
        return blob
    if len(pad) != 1:
        raise ValueError("pad must be 1 byte")
    return blob + pad * (size - len(blob))


def texts_from_dictionary_xml(path: Path | str) -> list[str]:
    """Read maildic_*.xml / *.en.xml produced by the legacy NLP dumper.

    That XML pairs (junk_key_or_count, empty) with (strlen_or_flags, text).
    We take every odd <Entry>'s JapaneseText body in order — index-aligned with
    the real MDC record list (not the broken hex attributes).
    """
    root = ET.parse(path).getroot()
    if root.tag != "Dictionary":
        raise ValueError(f"{path}: expected <Dictionary>, got <{root.tag}>")
    entries = list(root.findall("Entry"))
    if len(entries) % 2:
        raise ValueError(f"{path}: odd Entry count {len(entries)}")
    texts: list[str] = []
    for i in range(1, len(entries), 2):
        jt = entries[i].find("JapaneseText")
        if jt is None:
            raise ValueError(f"{path}: Entry {i} missing JapaneseText")
        texts.append((jt.text or "").replace("\r\n", "\n").replace("\r", "\n"))
    return texts


def apply_texts(base: list[MdcEntry], texts: list[str]) -> list[MdcEntry]:
    if len(texts) != len(base):
        raise ValueError(f"text count {len(texts)} != MDC records {len(base)}")
    return [MdcEntry(e.key, e.meta, t) for e, t in zip(base, texts)]
