#!/usr/bin/env python3
"""Python 3 DARC (NintendoWare) extract / same-size inject / rebuild."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DarcFile:
    name: str  # relative path using /
    offset: int
    length: int
    index_pos: int


def _align(value: int, alignment: int) -> int:
    if alignment <= 1:
        return value
    rem = value % alignment
    return value if rem == 0 else value + (alignment - rem)


def _read_utf16z(data: bytes, offset: int, endian: str) -> str:
    chars: list[str] = []
    pos = offset
    while pos + 1 < len(data):
        (unit,) = struct.unpack_from(endian + "H", data, pos)
        pos += 2
        if unit == 0:
            break
        chars.append(chr(unit))
    return "".join(chars)


def _write_utf16z(name: str, endian: str) -> bytes:
    enc = "utf-16le" if endian == "<" else "utf-16be"
    return name.encode(enc) + b"\x00\x00"


class DarcArchive:
    def __init__(self, data: bytes):
        if data[:4] != b"darc":
            raise ValueError("not a darc archive")
        bom = data[4:6]
        if bom == b"\xff\xfe":
            endian = "<"
        elif bom == b"\xfe\xff":
            endian = ">"
        else:
            raise ValueError("bad DARC BOM")
        self.endian = endian
        self.data = bytearray(data)
        (self.header_size,) = struct.unpack_from(endian + "H", data, 6)
        (
            self.version,
            self.file_size,
            self.table_offset,
            self.table_size,
            self.data_offset,
        ) = struct.unpack_from(endian + "IIIII", data, 8)

        name_off0, _file_off0, file_len0 = struct.unpack_from(
            endian + "III", data, self.table_offset
        )
        is_dir0 = (name_off0 & 0x01000000) != 0
        count = file_len0 if is_dir0 else 1
        name_table = self.table_offset + count * 0xC

        self.entries: list[dict] = []
        files: list[DarcFile] = []
        dir_name = ""
        for i in range(count):
            pos = self.table_offset + i * 0xC
            raw_name_off, file_off, file_len = struct.unpack_from(endian + "III", data, pos)
            is_dir = (raw_name_off & 0x01000000) != 0
            name_off = name_table + (raw_name_off & 0x00FFFFFF)
            name = _read_utf16z(data, name_off, endian)
            if is_dir:
                dir_name = "" if name in (".", "") else name
                self.entries.append(
                    {
                        "isdir": True,
                        "name": name,
                        "dir": dir_name,
                        "file_off": file_off,  # parent index
                        "file_len": file_len,  # end index
                    }
                )
                continue
            rel = f"{dir_name}/{name}" if dir_name else name
            rel = rel.replace("\\", "/")
            entry = DarcFile(rel, file_off, file_len, pos)
            files.append(entry)
            self.entries.append(
                {
                    "isdir": False,
                    "name": name,
                    "dir": dir_name,
                    "rel": rel,
                    "file": entry,
                }
            )
        self.files = files
        self._by_name = {f.name.lower(): f for f in files}
        self._by_base: dict[str, list[DarcFile]] = {}
        for f in files:
            base = Path(f.name).name.lower()
            self._by_base.setdefault(base, []).append(f)

    @classmethod
    def load(cls, path: Path) -> DarcArchive:
        return cls(path.read_bytes())

    def find(self, rel_or_base: str) -> DarcFile | None:
        key = rel_or_base.replace("\\", "/").lower().lstrip("/")
        if key in self._by_name:
            return self._by_name[key]
        base = Path(key).name
        hits = self._by_base.get(base, [])
        if len(hits) == 1:
            return hits[0]
        timg = [h for h in hits if h.name.lower().startswith("timg/")]
        if len(timg) == 1:
            return timg[0]
        return None

    def extract_file(self, entry: DarcFile) -> bytes:
        return bytes(self.data[entry.offset : entry.offset + entry.length])

    def extract_all(self, out_dir: Path) -> int:
        count = 0
        for entry in self.files:
            dest = out_dir / entry.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.extract_file(entry))
            count += 1
        return count

    def replace_same_size(self, entry: DarcFile, new_data: bytes) -> None:
        if len(new_data) != entry.length:
            raise ValueError(
                f"size mismatch for {entry.name}: new {len(new_data)} != old {entry.length}"
            )
        self.data[entry.offset : entry.offset + entry.length] = new_data

    def insert_file_entry(self, rel: str, after_rel: str) -> None:
        """Insert a new file slot in the entry table (payload supplied via rebuild_from_dir).

        Used by Title Eng Patch: add ``timg/Eng_Patch.bclim`` after Copyright, then
        ``rebuild_from_dir`` reads the new file from the extract tree.
        """
        rel = rel.replace("\\", "/").lstrip("/")
        after_rel = after_rel.replace("\\", "/").lstrip("/")
        if "/" not in rel:
            raise ValueError(f"rel must include directory: {rel!r}")
        dir_name, file_name = rel.rsplit("/", 1)
        insert_at = None
        for i, e in enumerate(self.entries):
            if not e["isdir"] and e.get("rel") == after_rel:
                insert_at = i + 1
                break
        if insert_at is None:
            raise FileNotFoundError(after_rel)
        if any(not e["isdir"] and e.get("rel") == rel for e in self.entries):
            return  # already present
        self.entries.insert(
            insert_at,
            {
                "isdir": False,
                "name": file_name,
                "dir": dir_name,
                "rel": rel,
                "file": DarcFile(rel, 0, 0, 0),
            },
        )
        for e in self.entries:
            if not e["isdir"]:
                continue
            if e["file_len"] >= insert_at:
                e["file_len"] += 1
            if e["file_off"] >= insert_at:
                e["file_off"] += 1
        self.files = [e["file"] for e in self.entries if not e["isdir"]]
        for e in self.entries:
            if not e["isdir"]:
                e["file"].name = e["rel"]
        self._by_name = {f.name.lower(): f for f in self.files}
        self._by_base = {}
        for f in self.files:
            self._by_base.setdefault(Path(f.name).name.lower(), []).append(f)

    def save(self, path: Path) -> None:
        path.write_bytes(self.data)

    def rebuild_from_dir(
        self,
        src_dir: Path,
        out_path: Path,
        default_align: int = 0x20,
        type_align: dict[str, int] | None = None,
        align_mode: str = "relative",
        **_kwargs,
    ) -> None:
        """Rebuild archive from extracted directory; keep original dir table metadata.

        align_mode:
          relative — pad within the data blob (default)
          absolute — pad so file absolute offsets meet type_align (needed when
            inserting BCLIM into Title.arc so every .bclim stays 0x80-aligned)
        """
        type_align = type_align or {".bclim": 0x80, ".bcfnt": 0x80}
        endian = self.endian

        names: list[str] = []
        is_dirs: list[bool] = []
        dir_meta: list[tuple[int, int]] = []
        payloads: list[bytes | None] = []

        for ent in self.entries:
            names.append(ent["name"])
            is_dirs.append(ent["isdir"])
            if ent["isdir"]:
                dir_meta.append((ent["file_off"], ent["file_len"]))
                payloads.append(None)
            else:
                dir_meta.append((0, 0))
                path = src_dir / ent["rel"]
                if not path.is_file():
                    raise FileNotFoundError(f"missing {path}")
                payloads.append(path.read_bytes())

        name_table = bytearray()
        name_offsets: list[int] = []
        for name in names:
            name_offsets.append(len(name_table))
            name_table.extend(_write_utf16z(name, endian))

        count = len(names)
        table_offset = 0x1C
        table_size = count * 0xC + len(name_table)
        data_start = _align(table_offset + table_size, default_align)

        data_blob = bytearray()
        abs_offs: list[int] = []
        abs_lens: list[int] = []
        for name, is_dir, payload, meta in zip(names, is_dirs, payloads, dir_meta):
            if is_dir:
                abs_offs.append(meta[0])
                abs_lens.append(meta[1])
                continue
            assert payload is not None
            align = default_align
            lower = name.lower()
            for ext, al in type_align.items():
                if lower.endswith(ext):
                    align = al
                    break
            if align_mode == "absolute":
                cur_abs = data_start + len(data_blob)
                aligned_abs = _align(cur_abs, align)
                pad = aligned_abs - cur_abs
                if pad:
                    data_blob.extend(b"\x00" * pad)
            else:
                pos = _align(len(data_blob), align)
                if pos > len(data_blob):
                    data_blob.extend(b"\x00" * (pos - len(data_blob)))
            abs_offs.append(data_start + len(data_blob))
            abs_lens.append(len(payload))
            data_blob.extend(payload)

        out = bytearray()
        out.extend(b"darc")
        out.extend(b"\xff\xfe" if endian == "<" else b"\xfe\xff")
        out.extend(struct.pack(endian + "H", 0x1C))
        out.extend(
            struct.pack(
                endian + "IIIII",
                self.version,
                0,  # size filled later
                table_offset,
                table_size,
                data_start,
            )
        )
        if len(out) < table_offset:
            out.extend(b"\x00" * (table_offset - len(out)))

        for i, name_off in enumerate(name_offsets):
            raw_name = name_off & 0x00FFFFFF
            if is_dirs[i]:
                raw_name |= 0x01000000
            out.extend(struct.pack(endian + "III", raw_name, abs_offs[i], abs_lens[i]))
        out.extend(name_table)
        if len(out) < data_start:
            out.extend(b"\x00" * (data_start - len(out)))
        out.extend(data_blob)
        struct.pack_into(endian + "I", out, 0x0C, len(out))
        out_path.write_bytes(out)
