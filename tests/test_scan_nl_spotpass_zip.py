"""Split-zip central-directory scan for the NEW Love Plus SpotPass archive."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from conftest import TOOLS, load_module

scan_mod = load_module("scan_nl_spotpass_zip", TOOLS / "scan_nl_spotpass_zip.py")
SplitReader = scan_mod.SplitReader
detect_skip = scan_mod.detect_skip
discover_parts = scan_mod.discover_parts
parse_filelist = scan_mod.parse_filelist
scan = scan_mod.scan


FILELIST = (
    b"275ace998ac0269716e34c654be6c9f03b4bdba0\r\n"
    b"        84\r\n"
    b"info.dat\t\t\t\t\t2324\t1393894774\r\n"
    b"aabbccddeeff0011\t\t\t\t\t80000\t1400000000\r\n"
)


def _build_split(tmp: Path) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("JP/ja/PTASK01/filelist.txt", FILELIST)
        zf.writestr("JP/ja/PTASK01/info.dat.boss", b"boss-magazine")
        zf.writestr("US/en/PTASK01/info.dat.boss", b"boss-magazine")
        zf.writestr("JP/ja/PTASK01/aabbccddeeff0011.boss", b"city-voice-blob")
    raw = buf.getvalue()
    folder = tmp / "parts"
    folder.mkdir()
    # One junk byte on .000, then 40-byte slices, matching the Archive.org split.
    raw = b"\x00" + raw
    for i in range(0, len(raw), 40):
        (folder / f"NiAJFnn4fyAAiggq.zip.{i // 40:03d}").write_bytes(raw[i : i + 40])
    return folder


def test_parse_filelist_tabs():
    rows = parse_filelist(FILELIST)
    assert rows == [
        ("info.dat", 2324, 1393894774),
        ("aabbccddeeff0011", 80000, 1400000000),
    ]


def test_split_scan_finds_magazine_not_each_region_copy(tmp_path: Path):
    folder = _build_split(tmp_path)
    parts, hinted = discover_parts(folder)
    assert hinted is None
    assert detect_skip(parts[0]) == 1
    reader = SplitReader(parts, 1)
    tasks = scan(reader, track_limit=100)
    task = tasks["PTASK01"]
    assert task.boss_count == 3
    assert set(task.payloads["info.dat"]) == {zipfile.crc32(b"boss-magazine") & 0xFFFFFFFF}
    assert len(task.payloads["info.dat"]) == 1
    assert "aabbccddeeff0011" in task.payloads
    chosen = task.filelists[0]
    assert chosen.name == "JP/ja/PTASK01/filelist.txt"
