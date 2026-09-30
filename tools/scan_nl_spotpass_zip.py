#!/usr/bin/env python3
"""Scan the split NEW Love Plus SpotPass zip for Towano Watcher files.

Internet Archive published task ``NiAJFnn4fyAAiggq`` as raw pieces
``NiAJFnn4fyAAiggq.zip.000``, ``.001``, … of about 200 GB each. They are
one stored zip, not separate archives. ``.000`` has one extra leading byte
that is not part of the zip.

This reads the central directory (a few GB at the end) and then the small
``filelist.txt`` catalogs. It does not extract the boss payloads.

A filelist line is ``name<tabs>size<tab>unix_time``. The same ``info.dat``
copied once per country/language is one magazine file, not one issue per
copy. Weekly issues that were replaced on the CDN are absent here; only
names still in the filelist survived.

Usage (folder that contains the parts):

    python tools/scan_nl_spotpass_zip.py D:\\path\\to\\parts

Pull the stored bytes for one catalog name (still ciphertext):

    python tools/scan_nl_spotpass_zip.py D:\\path\\to\\parts --extract info.dat.boss --out out/nl_spotpass_hits
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SIG_EOCD = b"PK\x05\x06"
SIG_EOCD64 = b"PK\x06\x06"
SIG_LOC64 = b"PK\x06\x07"
SIG_CD = b"PK\x01\x02"
SIG_LOCAL = b"PK\x03\x04"
ZIP64_EXTRA = 0x0001

# Names that are the magazine / index, not a one-off city-voice upload.
INTERESTING = re.compile(
    r"(?i)(info\.dat|filelist|tasksheet|watch|towano|magazine|news|\.xml$)"
)


@dataclass
class Entry:
    name: str
    method: int
    crc: int
    comp_size: int
    uncomp_size: int
    local_offset: int


@dataclass
class TaskReport:
    filelists: list[Entry] = field(default_factory=list)
    boss_count: int = 0
    boss_bytes: int = 0
    # basename -> {crc: size}
    payloads: dict[str, dict[int, int]] = field(default_factory=lambda: defaultdict(dict))
    payload_overflow: int = 0


class SplitReader:
    """Logical file over ``.zip.NNN`` parts. ``skip_first`` drops the IA byte."""

    def __init__(self, parts: list[Path], skip_first: int) -> None:
        if not parts:
            raise SystemExit("no zip parts")
        self.parts = parts
        self._sizes = [p.stat().st_size for p in parts]
        self._spans: list[tuple[int, int, int]] = []
        logical = 0
        for i, size in enumerate(self._sizes):
            skip = skip_first if i == 0 else 0
            if skip > size:
                raise SystemExit(f"skip {skip} is past the end of {parts[0].name}")
            length = size - skip
            self._spans.append((logical, length, skip))
            logical += length
        self.size = logical

    def read(self, offset: int, n: int) -> bytes:
        if offset < 0 or n < 0 or offset + n > self.size:
            raise ValueError(f"read {offset}+{n} outside logical size {self.size}")
        out = bytearray()
        remaining = n
        pos = offset
        for start, length, skip in self._spans:
            end = start + length
            if pos >= end:
                continue
            if pos < start:
                break
            take = min(remaining, end - pos)
            part_i = next(i for i, span in enumerate(self._spans) if span == (start, length, skip))
            file_off = skip + (pos - start)
            with self.parts[part_i].open("rb") as fh:
                fh.seek(file_off)
                chunk = fh.read(take)
            if len(chunk) != take:
                raise ValueError(f"short read in {self.parts[part_i].name}")
            out += chunk
            remaining -= take
            pos += take
            if remaining == 0:
                return bytes(out)
        raise ValueError(f"could not map offset {offset}")


def discover_parts(path: Path) -> tuple[list[Path], int | None]:
    """Return part paths in order. ``None`` skip means auto-detect the IA byte."""
    if path.is_dir():
        parts = sorted(path.glob("*.zip.[0-9][0-9][0-9]"))
        if not parts:
            parts = sorted(p for p in path.iterdir() if re.search(r"\.zip\.\d+$", p.name, re.I))
        if not parts:
            zips = sorted(path.glob("*.zip"))
            if len(zips) == 1:
                return zips, 0
        if not parts:
            raise SystemExit(f"no .zip.NNN parts in {path}")
        _require_contiguous(parts)
        return parts, None
    if re.search(r"\.zip\.\d+$", path.name, re.I):
        prefix = path.name.rsplit(".", 1)[0]
        folder = path.parent
        parts = sorted(
            p for p in folder.iterdir() if p.name.startswith(prefix + ".") and re.search(r"\.zip\.\d+$", p.name, re.I)
        )
        _require_contiguous(parts)
        return parts, None
    if path.is_file() and path.suffix.lower() == ".zip":
        return [path], 0
    raise SystemExit(f"not a zip or a .zip.NNN part: {path}")


def _require_contiguous(parts: list[Path]) -> None:
    numbers = [int(p.name.rsplit(".", 1)[-1]) for p in parts]
    expected = list(range(len(numbers)))
    if numbers != expected:
        missing = sorted(set(expected) - set(numbers))
        raise SystemExit(f"zip parts are not contiguous; missing {missing[:12]}")


def detect_skip(first: Path) -> int:
    with first.open("rb") as fh:
        head = fh.read(5)
    if head.startswith(SIG_LOCAL):
        return 0
    if len(head) >= 5 and head[1:5] == SIG_LOCAL:
        return 1
    return 0


def _find_eocd(tail: bytes, file_size: int) -> tuple[int, int, int, int]:
    """Return (eocd_offset, cd_offset, cd_size, entry_count) from the last bytes."""
    search_from = max(0, len(tail) - (22 + 65535))
    rel = tail.rfind(SIG_EOCD, search_from)
    if rel < 0:
        raise SystemExit("end-of-central-directory signature not found in the last part")
    eocd = tail[rel:]
    if len(eocd) < 22:
        raise SystemExit("truncated end-of-central-directory")
    comment_len = struct.unpack_from("<H", eocd, 20)[0]
    if 22 + comment_len != len(eocd):
        # A false PK\x05\x06 inside the comment. Walk back.
        cursor = rel
        while True:
            cursor = tail.rfind(SIG_EOCD, search_from, cursor)
            if cursor < 0:
                raise SystemExit("no end-of-central-directory record matches the file tail")
            eocd = tail[cursor:]
            if len(eocd) < 22:
                continue
            comment_len = struct.unpack_from("<H", eocd, 20)[0]
            if 22 + comment_len == len(eocd):
                rel = cursor
                break
    disk_entries, total_entries, cd_size, cd_offset = struct.unpack_from("<HHII", eocd, 8)
    tail_base = file_size - len(tail)
    eocd_off = tail_base + rel
    if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF or total_entries == 0xFFFF:
        loc_rel = rel - 20
        if loc_rel < 0 or tail[loc_rel : loc_rel + 4] != SIG_LOC64:
            raise SystemExit("zip64 central directory, but the locator is missing")
        eocd64_off = struct.unpack_from("<Q", tail, loc_rel + 8)[0]
        return eocd_off, eocd64_off, -1, -1
    return eocd_off, cd_offset, cd_size, total_entries or disk_entries


def locate_central_directory(reader: SplitReader) -> tuple[int, int, int]:
    tail_n = min(reader.size, 22 + 65535 + 20)
    tail = reader.read(reader.size - tail_n, tail_n)
    _eocd_off, cd_or_eocd64, cd_size, count = _find_eocd(tail, reader.size)
    if cd_size >= 0:
        return cd_or_eocd64, cd_size, count
    eocd64 = reader.read(cd_or_eocd64, 56)
    if eocd64[:4] != SIG_EOCD64:
        raise SystemExit(f"zip64 EOCD missing at {cd_or_eocd64:#x}")
    count = struct.unpack_from("<Q", eocd64, 32)[0]
    cd_size = struct.unpack_from("<Q", eocd64, 40)[0]
    cd_offset = struct.unpack_from("<Q", eocd64, 48)[0]
    return cd_offset, cd_size, count


def _zip64_extra(extra: bytes, need_size: bool, need_offset: bool) -> tuple[int | None, int | None, int | None]:
    uncomp = comp = offset = None
    i = 0
    while i + 4 <= len(extra):
        kind, size = struct.unpack_from("<HH", extra, i)
        i += 4
        blob = extra[i : i + size]
        i += size
        if kind != ZIP64_EXTRA:
            continue
        pos = 0
        if need_size:
            uncomp, comp = struct.unpack_from("<QQ", blob, pos)
            pos += 16
        if need_offset and pos + 8 <= len(blob):
            offset = struct.unpack_from("<Q", blob, pos)[0]
        break
    return uncomp, comp, offset


def iter_central_directory(reader: SplitReader, offset: int, size: int, count: int):
    data = reader.read(offset, size)
    pos = 0
    seen = 0
    while pos + 46 <= len(data) and (count == 0 or seen < count):
        if data[pos : pos + 4] != SIG_CD:
            raise SystemExit(f"central-directory entry {seen} is not PK\\x01\\x02 at +{pos}")
        method = struct.unpack_from("<H", data, pos + 10)[0]
        crc, comp_size, uncomp_size = struct.unpack_from("<III", data, pos + 16)
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", data, pos + 28)
        local_offset = struct.unpack_from("<I", data, pos + 42)[0]
        name_b = data[pos + 46 : pos + 46 + name_len]
        extra = data[pos + 46 + name_len : pos + 46 + name_len + extra_len]
        need_size = comp_size == 0xFFFFFFFF or uncomp_size == 0xFFFFFFFF
        need_off = local_offset == 0xFFFFFFFF
        if need_size or need_off:
            z_uncomp, z_comp, z_off = _zip64_extra(extra, need_size, need_off)
            if need_size:
                if z_comp is None or z_uncomp is None:
                    raise SystemExit(f"zip64 sizes missing for {name_b!r}")
                comp_size, uncomp_size = z_comp, z_uncomp
            if need_off:
                if z_off is None:
                    raise SystemExit(f"zip64 offset missing for {name_b!r}")
                local_offset = z_off
        name = name_b.decode("utf-8", "replace")
        yield Entry(name, method, crc, comp_size, uncomp_size, local_offset)
        pos += 46 + name_len + extra_len + comment_len
        seen += 1
        if seen % 500_000 == 0:
            print(f"  … {seen} central-directory entries", flush=True)


def task_of(name: str) -> str:
    parts = name.split("/")
    if len(parts) >= 3:
        return parts[2]
    return "(root)"


def prefer_filelist(entries: list[Entry]) -> Entry:
    for entry in entries:
        if entry.name.startswith("JP/ja/"):
            return entry
    return entries[0]


def read_stored(reader: SplitReader, entry: Entry) -> bytes:
    if entry.method not in (0, zipfile.ZIP_STORED):
        raise SystemExit(f"{entry.name} is compressed (method {entry.method}); this archive is documented as stored")
    local = reader.read(entry.local_offset, 30)
    if local[:4] != SIG_LOCAL:
        raise SystemExit(f"local header missing for {entry.name} at {entry.local_offset:#x}")
    name_len, extra_len = struct.unpack_from("<HH", local, 26)
    start = entry.local_offset + 30 + name_len + extra_len
    return reader.read(start, entry.comp_size)


def parse_filelist(blob: bytes) -> list[tuple[str, int, int]]:
    """Return (filename, size, unix_time) from a 3DS NPFL filelist."""
    text = blob.decode("utf-8", "replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    rows: list[tuple[str, int, int]] = []
    for line in lines[2:]:
        parts = line.split("\t")
        name = parts[0].strip()
        if not name:
            continue
        nums = [p for p in parts[1:] if p.strip().lstrip("-").isdigit()]
        size = int(nums[-2]) if len(nums) >= 2 else (int(nums[0]) if nums else -1)
        when = int(nums[-1]) if len(nums) >= 2 else -1
        if len(nums) == 1:
            size, when = int(nums[0]), -1
        rows.append((name, size, when))
    return rows


def scan(reader: SplitReader, track_limit: int) -> dict[str, TaskReport]:
    cd_off, cd_size, count = locate_central_directory(reader)
    print(
        f"central directory at {cd_off:#x}, {cd_size} bytes, {count} entries",
        flush=True,
    )
    tasks: dict[str, TaskReport] = defaultdict(TaskReport)
    total = 0
    for entry in iter_central_directory(reader, cd_off, cd_size, count):
        total += 1
        base = entry.name.rsplit("/", 1)[-1]
        task = task_of(entry.name)
        report = tasks[task]
        if base == "filelist.txt":
            report.filelists.append(entry)
            continue
        if not base.endswith(".boss"):
            continue
        report.boss_count += 1
        report.boss_bytes += entry.uncomp_size
        stem = base[: -len(".boss")]
        bucket = report.payloads
        if stem in bucket or len(bucket) < track_limit:
            bucket[stem][entry.crc] = entry.uncomp_size
        else:
            report.payload_overflow += 1
    print(f"read {total} entries across {len(tasks)} task folders", flush=True)
    return tasks


def print_report(reader: SplitReader, tasks: dict[str, TaskReport], show_all: bool) -> None:
    for task in sorted(tasks):
        report = tasks[task]
        print(f"\n== {task} ==")
        print(f"boss files: {report.boss_count}  ({report.boss_bytes} bytes)")
        if report.payload_overflow:
            print(
                f"basename table overflowed by {report.payload_overflow} files; "
                "those are extra unique city-voice names, not a second copy of a tracked file"
            )
        repeated = []
        singles = 0
        for stem, crcs in sorted(report.payloads.items()):
            if len(crcs) > 1 or INTERESTING.search(stem) or show_all:
                sizes = sorted(set(crcs.values()))
                repeated.append((stem, len(crcs), sizes))
            else:
                singles += 1
        if singles:
            print(f"unique boss names with one CRC (city-voice shaped): {singles}")
        if repeated:
            print("payloads with more than one CRC, or a magazine-like name:")
            for stem, ncrc, sizes in repeated:
                print(f"  {stem}.boss  distinct_crc={ncrc}  sizes={sizes}")
        if not report.filelists:
            print("no filelist.txt")
            continue
        chosen = prefer_filelist(report.filelists)
        print(f"filelists: {len(report.filelists)}  reading {chosen.name}")
        rows = parse_filelist(read_stored(reader, chosen))
        print(f"catalog lines: {len(rows)}")
        interesting = [row for row in rows if INTERESTING.search(row[0])]
        if interesting:
            print("magazine-like catalog names:")
            for name, size, when in interesting:
                print(f"  {name}  size={size}  time={when}")
        shown = 0
        for name, size, when in rows:
            if not show_all and (INTERESTING.search(name) or size > 65536):
                continue
            print(f"  {name}  size={size}  time={when}")
            shown += 1
            if not show_all and shown >= 200:
                print("  … stopped after 200 other small catalog lines (pass --show-all to print the rest)")
                break


def extract_named(reader: SplitReader, cd_off: int, cd_size: int, count: int, needle: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[int, Path] = {}
    hits = 0
    for entry in iter_central_directory(reader, cd_off, cd_size, count):
        base = entry.name.rsplit("/", 1)[-1]
        if base != needle and not entry.name.endswith("/" + needle):
            continue
        hits += 1
        if entry.crc in saved:
            continue
        blob = read_stored(reader, entry)
        dest = out_dir / f"{needle}.{entry.crc:08x}"
        dest.write_bytes(blob)
        saved[entry.crc] = dest
        print(f"wrote {dest}  ({len(blob)} bytes) from {entry.name}")
    if hits == 0:
        raise SystemExit(f"no central-directory entry named {needle}")
    print(f"{hits} copies, {len(saved)} distinct CRC")


_BULK_NUM = re.compile(r"^(.*?)(\d+)$")
_DESC = b"PK\x07\x08"
_DESC_LEN = 24


def _payload_length(fh, first: bytes, logical_pos: int, logical_end: int) -> tuple[int, bytes | None] | None:
    """Return payload length and leave the handle after its descriptor.

    The second item is the payload bytes for a non-boss file that fit in the
    first read window (filelist.txt). Boss payloads are not copied.
    """
    if first.startswith(b"boss") and len(first) >= 12:
        payload = struct.unpack_from(">I", first, 8)[0]
        if payload < 12 or logical_pos + payload + _DESC_LEN > logical_end:
            return None
        fh.seek(payload - len(first), 1)
        desc = fh.read(_DESC_LEN)
        if desc[:4] != _DESC:
            return None
        return payload, None
    window = bytearray(first)
    base = 0
    while logical_pos + base < logical_end:
        found = window.find(_DESC)
        while found >= 0:
            if found + _DESC_LEN > len(window):
                break
            comp, uncomp = struct.unpack_from("<QQ", window, found + 8)
            absolute = base + found
            nxt = found + _DESC_LEN
            if comp == uncomp == absolute and (
                nxt + 4 > len(window) or window[nxt : nxt + 4] == SIG_LOCAL
            ):
                consumed = base + len(window)
                fh.seek((absolute + _DESC_LEN) - consumed, 1)
                body = bytes(window[:absolute]) if base == 0 else None
                return absolute, body
            found = window.find(_DESC, found + 1)
        if len(window) > _DESC_LEN:
            drop = len(window) - (_DESC_LEN - 1)
            del window[:drop]
            base += drop
        chunk = fh.read(1024 * 1024)
        if not chunk:
            return None
        window += chunk
    return None


def walk_local_part(path: Path, skip: int, report_path: Path) -> None:
    """Walk stored local headers in one split piece.

    Part .000 does not contain the central directory. A ``boss`` payload's
    big-endian size at offset 8 is the file length. Other entries (filelist.txt)
    end at a 24-byte Zip64 data descriptor.
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)
    size = path.stat().st_size
    logical_end = size - skip
    task_counts: dict[str, int] = defaultdict(int)
    prefix_counts: dict[str, int] = defaultdict(int)
    interesting: list[str] = []
    files = 0
    payload_bytes = 0
    with path.open("rb") as fh, report_path.open("w", encoding="utf-8") as out:
        fh.seek(skip)
        pos = 0
        while pos + 30 <= logical_end:
            hdr = fh.read(30)
            if len(hdr) < 30:
                break
            if hdr[:4] != SIG_LOCAL:
                out.write(f"STOPPED not a local header at logical {pos:#x}\n")
                print(f"STOPPED not a local header at logical {pos:#x}", flush=True)
                break
            name_len, extra_len = struct.unpack_from("<HH", hdr, 26)
            name = fh.read(name_len).decode("utf-8", "replace")
            fh.read(extra_len)
            pos += 30 + name_len + extra_len
            head = fh.read(12)
            if len(head) < 12:
                out.write(f"STOPPED truncated payload {name}\n")
                break
            bounded = _payload_length(fh, head, pos, logical_end)
            if bounded is None:
                payload = None
            else:
                payload, body = bounded
            if payload is None:
                out.write(f"STOPPED could not bound {name} at {pos:#x}\n")
                print(f"STOPPED could not bound {name} at logical {pos:#x}", flush=True)
                break
            files += 1
            payload_bytes += payload
            pos += payload + _DESC_LEN
            base = name.rsplit("/", 1)[-1]
            stem = base[: -len(".boss")] if base.endswith(".boss") else base
            task_counts[task_of(name)] += 1
            match = _BULK_NUM.match(stem)
            prefix = match.group(1) if match else stem
            prefix_counts[prefix] += 1
            if body and base in ("filelist.txt", "tasksheet.xml"):
                rows = parse_filelist(body) if base == "filelist.txt" else []
                kept = [row for row in rows if INTERESTING.search(row[0]) or _BULK_NUM.match(row[0]) is None]
                out.write(f"CATALOG {name} lines={len(rows)} kept={len(kept)}\n")
                for row_name, row_size, row_time in kept[:100]:
                    out.write(f"  {row_name}\tsize={row_size}\ttime={row_time}\n")
                print(f"catalog {name} lines={len(rows)} kept={len(kept)}", flush=True)
            if INTERESTING.search(name) or match is None:
                line = f"{name}\tsize={payload}"
                interesting.append(line)
                out.write(line + "\n")
            if files % 20000 == 0:
                gib = payload_bytes / (1024 ** 3)
                out.flush()
                print(f"  … {files} files, {gib:.1f} GiB, last {name}", flush=True)
        out.write(
            f"\nfiles={files} payload_bytes={payload_bytes} logical_end={logical_end}\n"
        )
        out.write("tasks:\n")
        for task, count in sorted(task_counts.items(), key=lambda kv: -kv[1]):
            out.write(f"  {task}\t{count}\n")
        out.write("name prefixes:\n")
        for prefix, count in sorted(prefix_counts.items(), key=lambda kv: -kv[1]):
            out.write(f"  {prefix}\t{count}\n")
        out.write(f"interesting_or_unnamed={len(interesting)}\n")
    print(f"walked {files} files, {payload_bytes} payload bytes", flush=True)
    print(f"report {report_path}", flush=True)
    print("tasks:", flush=True)
    for task, count in sorted(task_counts.items(), key=lambda kv: -kv[1])[:30]:
        print(f"  {task}  {count}", flush=True)
    print("name prefixes:", flush=True)
    for prefix, count in sorted(prefix_counts.items(), key=lambda kv: -kv[1])[:40]:
        print(f"  {prefix}  {count}", flush=True)
    if interesting:
        print(f"magazine-like or non-numbered names: {len(interesting)}", flush=True)
        for line in interesting[:80]:
            print(f"  {line}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path, help="folder of .zip.NNN parts, one part, or a single .zip")
    parser.add_argument(
        "--skip-first",
        type=int,
        default=None,
        help="bytes to drop from the first part (default: 1 when .000 is PK shifted by one byte)",
    )
    parser.add_argument("--show-all", action="store_true", help="print every filelist line and every boss basename")
    parser.add_argument(
        "--track-limit",
        type=int,
        default=500_000,
        help="max distinct boss basenames kept per task (default 500000)",
    )
    parser.add_argument("--extract", metavar="NAME", help="copy stored bytes of this basename, one file per CRC")
    parser.add_argument("--out", type=Path, default=Path("out/nl_spotpass_hits"))
    parser.add_argument(
        "--walk-local",
        action="store_true",
        help="walk one split part by boss sizes (use when the central directory is in a later part)",
    )
    args = parser.parse_args()

    if args.walk_local:
        skip = args.skip_first if args.skip_first is not None else detect_skip(args.path)
        print(f"walking {args.path.name}, skip {skip} byte(s)", flush=True)
        walk_local_part(args.path, skip, args.out / f"{args.path.name}.txt")
        return

    parts, hinted = discover_parts(args.path)
    skip = args.skip_first
    if skip is None:
        skip = hinted if hinted is not None else detect_skip(parts[0])
    print(f"{len(parts)} part(s), skip {skip} byte(s) on {parts[0].name}", flush=True)
    reader = SplitReader(parts, skip)
    print(f"logical zip size {reader.size}", flush=True)
    if args.extract:
        cd_off, cd_size, count = locate_central_directory(reader)
        extract_named(reader, cd_off, cd_size, count, args.extract, args.out)
        return
    print_report(reader, scan(reader, args.track_limit), args.show_all)


if __name__ == "__main__":
    main()
