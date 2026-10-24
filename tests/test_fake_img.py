"""tests/fake_img.py builds containers the real parsers and ie/pe tools accept."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def _edited_package(tmp_path: Path) -> tuple[Path, Path, bytes]:
    """Sample img.bin unpacked with Foo.arc's A.bclim changed (same size)."""
    path = _sample(tmp_path)
    data = tmp_path / "img_data"
    pack_images.unpack_packages(path, data, {3})
    arc_path = pack_images.ensure_package_data(data, 3) / "Foo.arc"
    darc = DarcArchive.load(arc_path)
    entry = darc.find("A.bclim")
    new = bytes([0x11]) * 128 + darc.extract_file(entry)[128:]
    darc.replace_same_size(entry, new)
    darc.save(arc_path)
    return path, data, new


def _too_big(*_a, **_k):
    raise RuntimeError("zopfli 9 > slot 8")


def test_arc_over_its_slot_fails_a_direct_repack(tmp_path: Path, monkeypatch):
    _path, data, _new = _edited_package(tmp_path)
    monkeypatch.setattr(pack_images, "compress_to_exact_slot_cached", _too_big)
    with pytest.raises(pack_images.PackError, match="Foo.arc"):
        pack_images.repack_package_exact_slots(data, 3)


def test_pack_reports_an_arc_over_its_slot(tmp_path: Path, monkeypatch):
    # The pack used to keep the vanilla element and still report "[ok]";
    # Transfer.arc shipped Japanese. The report now names it for the bake check.
    _path, data, _new = _edited_package(tmp_path)
    monkeypatch.setattr(pack_images, "compress_to_exact_slot_cached", _too_big)
    skips: list[str] = []
    pack_images.repack_package_exact_slots(data, 3, slot_skips=skips)
    assert skips == ["Foo.arc"]
    line = "[slot-skip] package 0003 Foo.arc (left vanilla)"
    assert pack_images.SLOT_SKIP_RE.findall(line) == [("0003", "Foo.arc")]


def test_bake_fails_on_a_slot_skip_no_deploy_replaced(tmp_path: Path):
    from conftest import TOOLS, load_module

    rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")
    path, data, _new = _edited_package(tmp_path)
    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(path.read_bytes())
    report = "[ok] package 0003: 1 replaced\n[slot-skip] package 0003 Foo.arc (left vanilla)\n"

    # Nothing replaced Foo.arc: the bake would ship it Japanese.
    assert rebuild.unreplaced_slot_skips(report, vanilla, path) == ["package 0003 Foo.arc"]

    # A later deploy wrote its own Foo.arc (here: the real exact-slot repack).
    pack_images.repack_package_exact_slots(data, 3)
    pack_images.splice_packages_into_img(path, data, [3], path)
    assert rebuild.unreplaced_slot_skips(report, vanilla, path) == []
    assert rebuild.unreplaced_slot_skips("[ok] package 0003: 1 replaced", vanilla, path) == []


def test_splice_syncs_idx_dec_len_to_grown_pack(tmp_path: Path):
    # The game allocates a PAK from the img.bin idx dec_len. Title pkg 5261
    # grew its ARC and kept the vanilla idx size; the overflow smashed a
    # heap header (malloc abort at 0x10DE4C leaving Select Data).
    import struct

    path = _sample(tmp_path)
    idx_off = pack_images.IMG_IDX_TABLE_ADDR + 3 * pack_images.IMG_IDX_ENTRY_SIZE
    before = path.read_bytes()[idx_off : idx_off + pack_images.IMG_IDX_ENTRY_SIZE]
    pkg = bytearray(fi.read_package(path, 3))
    old = struct.unpack_from("<I", pkg, pack_images.PACK_HDR_DEC_LEN_OFF)[0]
    assert struct.unpack_from("<I", before, pack_images.IMG_IDX_DEC_LEN_OFF)[0] == old
    struct.pack_into("<I", pkg, pack_images.PACK_HDR_DEC_LEN_OFF, old + 0x80)
    data = tmp_path / "img_data"
    data.mkdir()
    (data / "new_0003").write_bytes(bytes(pkg))

    pack_images.splice_packages_into_img(path, data, [3], path)

    after = path.read_bytes()[idx_off : idx_off + pack_images.IMG_IDX_ENTRY_SIZE]
    assert struct.unpack_from("<I", after, pack_images.IMG_IDX_DEC_LEN_OFF)[0] == old + 0x80
    dl = pack_images.IMG_IDX_DEC_LEN_OFF
    assert after[:dl] + after[dl + 4 :] == before[:dl] + before[dl + 4 :]


def test_img_idx_mismatches_flags_stale_pak_size(tmp_path: Path):
    import struct

    path = _sample(tmp_path)
    assert pack_images.img_idx_mismatches(path) == []
    raw = bytearray(path.read_bytes())
    off = (
        pack_images.IMG_IDX_TABLE_ADDR
        + 3 * pack_images.IMG_IDX_ENTRY_SIZE
        + pack_images.IMG_IDX_DEC_LEN_OFF
    )
    (good,) = struct.unpack_from("<I", raw, off)
    struct.pack_into("<I", raw, off, good - 0x10)
    path.write_bytes(bytes(raw))
    assert pack_images.img_idx_mismatches(path) == [(3, good - 0x10, good)]


def _two_pkg_img(tmp_path: Path) -> tuple[Path, bytes, bytes]:
    """Bak with pkgs 3 and 5; returns (path, pkg3_bytes, pkg5_bytes)."""
    pkg3 = fi.package([("Foo.arc", fi.darc({"timg/A.bclim": fi.bclim(8, 8)}))])
    pkg5 = fi.package([("Bar.arc", fi.darc({"timg/B.bclim": fi.bclim(8, 8)}))])
    path = tmp_path / "bak_img.bin"
    path.write_bytes(fi.img({3: pkg3, 5: pkg5}))
    return path, pkg3, pkg5


def test_splice_from_bak_over_live_wipes_other_packages(tmp_path: Path):
    """Hard ban: splice_packages_into_img(bak, …, live) copies bak over live first."""
    bak, pkg3, pkg5_vanilla = _two_pkg_img(tmp_path)
    live = tmp_path / "live_img.bin"
    live.write_bytes(bak.read_bytes())

    # Live pkg 5 holds EN bytes that bak does not.
    en5 = fi.package(
        [("Bar.arc", fi.darc({"timg/B.bclim": fi.bclim(8, 8, pixels=b"\xee" * 128)}))]
    )
    data = tmp_path / "img_data"
    data.mkdir()
    (data / "new_0005").write_bytes(en5)
    pack_images.splice_packages_into_img(live, data, [5], live)
    assert fi.read_package(live, 5) == en5
    assert fi.read_package(live, 3) == pkg3

    # Splice only pkg 3 from bak into live — copies entire bak first.
    (data / "new_0003").write_bytes(pkg3)
    pack_images.splice_packages_into_img(bak, data, [3], live)
    assert fi.read_package(live, 3) == pkg3
    assert fi.read_package(live, 5) == pkg5_vanilla  # EN wiped


def test_same_path_splice_preserves_other_packages(tmp_path: Path):
    bak, pkg3, _pkg5 = _two_pkg_img(tmp_path)
    live = tmp_path / "live_img.bin"
    live.write_bytes(bak.read_bytes())

    en5 = fi.package(
        [("Bar.arc", fi.darc({"timg/B.bclim": fi.bclim(8, 8, pixels=b"\xee" * 128)}))]
    )
    data = tmp_path / "img_data"
    data.mkdir()
    (data / "new_0005").write_bytes(en5)
    pack_images.splice_packages_into_img(live, data, [5], live)

    (data / "new_0003").write_bytes(pkg3)
    pack_images.splice_packages_into_img(live, data, [3], live)
    assert fi.read_package(live, 5) == en5
    assert fi.read_package(live, 3) == pkg3


def test_encode_os_error_fails_instead_of_skipping(tmp_path: Path, monkeypatch):
    # A work dir past Windows MAX_PATH lost the written BCLIM; the master was
    # reported as one [warn] skip and shipped Japanese.
    import bclimutil
    from PIL import Image

    orig = tmp_path / "A.bclim"
    orig.write_bytes(fi.bclim(8, 8))
    png = tmp_path / "A.png"
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(png)

    def lost(*_a, **_k):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(bclimutil, "png_to_bclim_same_size", lost)
    with pytest.raises(OSError, match="shorter --work path"):
        pack_images._convert_one_png(png, orig, tmp_path / "w")

    def bad(*_a, **_k):
        raise ValueError("size mismatch")

    monkeypatch.setattr(bclimutil, "png_to_bclim_same_size", bad)
    status, _data, warn = pack_images._convert_one_png(png, orig, tmp_path / "w")
    assert status == "skip" and "size mismatch" in warn
