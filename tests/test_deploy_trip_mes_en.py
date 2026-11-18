"""Trip date-picker message box: raw ETC1A4 TEX in pkg 5792."""

from __future__ import annotations

import struct
import zlib
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import TOOLS, load_module
from PIL import Image

from bclimutil import decode_etc1a4_pixels

trip = load_module("deploy_trip_mes_en", TOOLS / "deploy_trip_mes_en.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")


def test_master_matches_vanilla_texture_size():
    assert Image.open(trip.MASTER).size == trip.SIZE == (256, 128)


def test_master_keeps_the_box_outside_the_text():
    """Only the box interior is redrawn; the transparent margin stays empty."""
    px = np.array(Image.open(trip.MASTER).convert("RGBA"))
    assert (px[:, 170:, 3] == 0).all()
    assert (px[124:, :, 3] == 0).all()
    assert (px[20:110, 20:150, 3] == 255).all()


def test_bake_runs_trip_before_cesa():
    scripts = rebuild.DEPLOY_SCRIPTS
    assert "deploy_trip_mes_en.py" in scripts
    assert scripts.index("deploy_trip_mes_en.py") < scripts.index("deploy_cesa_en.py")


TEX_LEN = 256 * 128
SLOT = 6000


def _pkg(elements: list[tuple[bytes, int, int, bytes]]) -> bytes:
    """Minimal PACK: header, one 0x20 entry per (typ, dec_len, is_cmp, stored bytes), data."""
    head = struct.pack("=6sH6I", b"PACK\n0", len(elements), 0, 0, 0, 0, 0, 0)
    table, body = b"", b""
    off = 0x20 * (len(elements) + 1)
    for typ, dec_len, is_cmp, stored in elements:
        table += struct.pack("=4s4x6I", typ, dec_len, 0, 0, is_cmp, len(stored), off + len(body))
        body += stored
    return head + table + body


def _vanilla_pkg(is_cmp: int = 1, dec_len: int = TEX_LEN) -> bytes:
    blank = bytes(TEX_LEN)  # fully transparent ETC1A4
    stored = trip.try_compress_to_slot(blank, SLOT) if is_cmp else blank
    return _pkg([(b"TEXI", 82, 0, bytes(82)), (b"TEX ", dec_len, is_cmp, stored)])


def _tex(pkg_raw: bytes) -> bytes:
    _off, ent = trip._tex_entry(pkg_raw)
    return zlib.decompress(pkg_raw[ent[6] : ent[6] + ent[5]])


def test_tex_entry_needs_exactly_one_tex():
    assert trip._tex_entry(_vanilla_pkg())[1][0] == b"TEX "
    with pytest.raises(SystemExit, match="found 0"):
        trip._tex_entry(_pkg([(b"TEXI", 1, 0, b"x")]))
    with pytest.raises(SystemExit, match="found 2"):
        trip._tex_entry(_pkg([(b"TEX ", 1, 0, b"x"), (b"TEX ", 1, 0, b"y")]))


def test_encode_master_rejects_wrong_size(tmp_path):
    small = tmp_path / "small.png"
    Image.new("RGBA", (64, 64)).save(small)
    with pytest.raises(SystemExit, match="expected"):
        trip.encode_master(bytes(TEX_LEN), small)


def test_patch_package_splices_master_into_same_slot():
    raw = _vanilla_pkg()
    new = trip.patch_package(raw)
    assert len(new) == len(raw)
    assert new[: 0x60] == raw[: 0x60]  # header + entry table untouched
    assert _tex(new) == trip.encode_master(bytes(TEX_LEN))


@pytest.mark.parametrize("kw", [{"is_cmp": 0}, {"dec_len": 1234}])
def test_patch_package_rejects_unexpected_tex(kw):
    with pytest.raises(SystemExit, match="unexpected TEX entry"):
        trip.patch_package(_vanilla_pkg(**kw))


def test_patch_package_rejects_master_that_does_not_fit(monkeypatch):
    raw = _vanilla_pkg()
    monkeypatch.setattr(trip, "try_compress_to_slot", lambda data, slot: None)
    with pytest.raises(SystemExit, match="does not fit"):
        trip.patch_package(raw)


def test_patch_package_rejects_inexact_slot(monkeypatch):
    raw = _vanilla_pkg()
    cmp_len, cmp_off = trip._tex_entry(raw)[1][5:7]
    wrong = raw[cmp_off : cmp_off + cmp_len]  # the vanilla stream: decodes, but not to the master
    monkeypatch.setattr(trip, "try_compress_to_slot", lambda data, slot: wrong)
    with pytest.raises(SystemExit, match="not exact"):
        trip.patch_package(raw)


def _stub_main(monkeypatch, tmp_path, entry, splice):
    pkg_raw = _vanilla_pkg()
    src = tmp_path / "vanilla.bin"
    src.write_bytes(b"\0" * 16 + pkg_raw)
    mod = tmp_path / "mod_img.bin"
    mod.write_bytes(b"")
    fake_img = SimpleNamespace(parse=lambda _full: None, entries={trip.PKG: entry(len(pkg_raw))})
    monkeypatch.setattr(trip, "MOD_IMG", mod)
    monkeypatch.setattr(trip, "OUT", tmp_path / "out")
    monkeypatch.setattr(trip, "maybe_backup_img", lambda img, tag: tmp_path / "bak")
    monkeypatch.setattr(trip, "_vanilla_src", lambda: src)
    monkeypatch.setattr(trip, "ImgBin", lambda path: fake_img)
    monkeypatch.setattr(trip, "_deploy_targets", lambda: [mod])
    monkeypatch.setattr(trip, "splice_packages_into_img", splice)


def _entry(n: int):
    return SimpleNamespace(fw=SimpleNamespace(base_offset=16, len=lambda: n))


def test_main_splices_package_into_each_target(monkeypatch, tmp_path):
    calls = []
    _stub_main(monkeypatch, tmp_path, _entry, lambda *a: calls.append(a))
    assert trip.main() == 0
    pkg_dir = tmp_path / "out" / "img_data"
    assert calls == [(tmp_path / "mod_img.bin", pkg_dir, [trip.PKG], tmp_path / "mod_img.bin")]
    assert _tex((pkg_dir / f"new_{trip.PKG:04d}").read_bytes()) == trip.encode_master(bytes(TEX_LEN))


def test_main_reports_splice_failure(monkeypatch, tmp_path):
    def splice(*_a):
        raise trip.PackError("boom")

    _stub_main(monkeypatch, tmp_path, _entry, splice)
    with pytest.raises(SystemExit, match="splice failed: boom"):
        trip.main()


def test_main_needs_the_package(monkeypatch, tmp_path):
    _stub_main(monkeypatch, tmp_path, lambda n: None, lambda *a: None)
    with pytest.raises(SystemExit, match="5792 missing"):
        trip.main()


def test_main_needs_the_mod_img(monkeypatch, tmp_path):
    monkeypatch.setattr(trip, "MOD_IMG", tmp_path / "absent.bin")
    with pytest.raises(SystemExit, match="missing"):
        trip.main()


@pytest.mark.local_data
def test_vanilla_package_takes_master_at_same_size():
    from img import Image as ImgBin

    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    raw = vanilla.read_bytes()
    img = ImgBin(str(vanilla))
    img.parse(False)
    res = img.entries[trip.PKG]
    pkg_raw = raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
    new = trip.patch_package(pkg_raw)
    assert len(new) == len(pkg_raw)
    off, ent = trip._tex_entry(new)
    assert trip._tex_entry(pkg_raw) == (off, ent)
    cmp_len, cmp_off = ent[5], ent[6]
    assert new[:cmp_off] == pkg_raw[:cmp_off]
    assert new[cmp_off + cmp_len :] == pkg_raw[cmp_off + cmp_len :]
    got = np.array(decode_etc1a4_pixels(zlib.decompress(new[cmp_off : cmp_off + cmp_len]), 256, 128))
    want = np.array(Image.open(trip.MASTER).convert("RGBA"))
    assert np.abs(got[..., 3].astype(int) - want[..., 3]).max() <= 17
