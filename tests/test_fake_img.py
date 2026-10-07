"""tests/fake_img.py builds containers the real parsers and ie/pe tools accept."""

from __future__ import annotations

from pathlib import Path

import fake_img as fi
import pack_images
from bclimutil import parse_bclim
from darcutil import DarcArchive


def _sample(tmp_path: Path) -> Path:
    arc = fi.darc({"timg/A.bclim": fi.bclim(8, 8), "blyt/A.bclyt": b"CLYT" + bytes(28)})
    pkg = fi.package([("Foo.arc", arc), ("note.txt", b"plain", b"TXT ", False)])
    path = tmp_path / "img.bin"
    path.write_bytes(fi.img({3: pkg}, raw={1: b"raw!"}))
    return path


def test_bclim_header_parses():
    pix, w, h, fmt, footer = parse_bclim(fi.bclim(16, 8, 3))
    assert (len(pix), w, h, fmt) == (16 * 8 * 2, 16, 8, 3)
    assert len(parse_bclim(fi.bclim(36, 36))[0]) == 64 * 64 * 2
    assert len(parse_bclim(fi.bclim(8, 8, 0xB))[0]) == 64
    assert footer.startswith(b"CLIM")


def test_darc_lists_files_in_subdirs():
    arc = DarcArchive(fi.darc({"timg/A.bclim": b"a" * 5, "timg/B.bclim": b"b", "top.bin": b"t"}))
    assert sorted(f.name for f in arc.files) == ["timg/A.bclim", "timg/B.bclim", "top.bin"]
    assert arc.extract_file(arc.find("A.bclim")) == b"a" * 5
    assert arc.extract_file(arc.find("top.bin")) == b"t"


def test_img_round_trips_through_parsers(tmp_path: Path):
    path = _sample(tmp_path)
    pkg = fi.read_package(path, 3)
    arc = DarcArchive(fi.read_element(pkg, "Foo.arc", tmp_path))
    assert arc.find("timg/A.bclim") is not None
    assert fi.read_element(pkg, "note.txt", tmp_path) == b"plain"


def test_ie_pe_unpack_repack_and_splice(tmp_path: Path):
    path = _sample(tmp_path)
    data = tmp_path / "img_data"
    pack_images.unpack_packages(path, data, {3})
    pkg_dir = pack_images.ensure_package_data(data, 3)
    arc_path = pkg_dir / "Foo.arc"
    darc = DarcArchive.load(arc_path)
    entry = darc.find("A.bclim")
    old = darc.extract_file(entry)
    new = bytes([0x11]) * 128 + old[128:]
    darc.replace_same_size(entry, new)
    darc.save(arc_path)

    pack_images.repack_package_exact_slots(data, 3)
    pack_images.splice_packages_into_img(path, data, [3], path)

    got = DarcArchive(fi.read_element(fi.read_package(path, 3), "Foo.arc", tmp_path))
    assert got.extract_file(got.find("A.bclim")) == new
