"""Incremental scratch cleanup so Drop CIA does not hold GB-scale temps until the end."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import SRC, TOOLS, load_module

cleanup = load_module("scratch_cleanup", SRC / "scratch_cleanup.py")
pack_images = load_module("pack_images", SRC / "pack_images.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")
patch_cia = load_module("patch_cia", SRC / "patch_cia.py")


def test_wipe_directory_recreates_empty(tmp_path: Path):
    root = tmp_path / "repo"
    out = root / "out"
    nested = out / "nested_scratch" / "a"
    nested.mkdir(parents=True)
    (nested / "save.bin").write_bytes(b"save")
    (out / "NewLovePlusPlus-EN.cia").write_bytes(b"cia")
    release = root / "release"
    release.mkdir()
    (release / "bake_img.bin").write_bytes(b"bake")
    (release / "romfs_overlay" / "SystemData").mkdir(parents=True)

    cleanup.wipe_directory(out, root=root)
    cleanup.wipe_directory(release, root=root)

    assert out.is_dir() and list(out.iterdir()) == []
    assert release.is_dir() and list(release.iterdir()) == []
    assert not (nested / "save.bin").exists()
    assert not (release / "bake_img.bin").exists()


def test_park_outside_copies_file_under_parent(tmp_path: Path):
    parent = tmp_path / "cache"
    src = parent / "rom_source" / "game.3ds"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"rom")
    outside = tmp_path / "desktop" / "game.3ds"
    outside.parent.mkdir()
    outside.write_bytes(b"desk")

    parked = cleanup.park_outside(src, parent)
    assert parked != src.resolve()
    assert parked.is_file()
    assert parked.read_bytes() == b"rom"
    assert cleanup.park_outside(outside, parent) == outside.resolve()


def test_wipe_cia_build_dirs_includes_cache():
    text = (SRC / "scratch_cleanup.py").read_text(encoding="utf-8")
    body = text.split("def wipe_cia_build_dirs", 1)[1].split("def remove_scratch", 1)[0]
    assert "CACHE" in body
    assert "OUT, RELEASE, CACHE" in body


def test_wipe_directory_refuses_repo_root(tmp_path: Path):
    with pytest.raises(SystemExit, match="refusing"):
        cleanup.wipe_directory(tmp_path, root=tmp_path)


def test_remove_scratch_deletes_file_and_dir(tmp_path: Path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"x" * 10)
    d = tmp_path / "tree"
    d.mkdir()
    (d / "nested.bin").write_bytes(b"y")
    cleanup.remove_scratch(f)
    cleanup.remove_scratch(d)
    assert not f.exists()
    assert not d.exists()
    cleanup.remove_scratch(tmp_path / "missing")  # no-op


def test_path_is_under(tmp_path: Path):
    work = tmp_path / "cia_work"
    work.mkdir()
    inner = work / "contents" / "content.0000.cxi"
    inner.parent.mkdir()
    inner.write_bytes(b"cxi")
    outside = tmp_path / "extracted" / "content.0000.cxi"
    outside.parent.mkdir()
    outside.write_bytes(b"cxi")
    assert cleanup.path_is_under(inner, work)
    assert cleanup.path_is_under(work, work)
    assert not cleanup.path_is_under(outside, work)


def test_cleanup_package_unpack_keeps_new_blob(tmp_path: Path):
    img_data = tmp_path / "img_data"
    img_data.mkdir()
    (img_data / "0090").write_bytes(b"orig")
    data = img_data / "0090_data"
    data.mkdir()
    (data / "CESA.texi").write_bytes(b"tex")
    (img_data / "new_0090").write_bytes(b"patched")
    pack_images.cleanup_package_unpack(img_data, 90)
    assert not (img_data / "0090").exists()
    assert not data.exists()
    assert (img_data / "new_0090").read_bytes() == b"patched"


def test_cleanup_out_dir_quiet_skips_already_clean_line(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.setattr(patch_cia, "ROOT", tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    cia = out / "NewLovePlusPlus-EN.cia"
    cia.write_bytes(b"cia")
    patch_cia.cleanup_out_dir(out_cia=cia, quiet=True)
    captured = capsys.readouterr().out
    assert "already clean" not in captured


def test_rebuild_cleans_scratch_by_default():
    text = (TOOLS / "rebuild_bake_img.py").read_text(encoding="utf-8")
    assert "cleanup_rebuild_scratch" in text
    assert "duplicate cache/new_img.bin" in text
    assert "rebuild_bake_img_work" in text
    assert "--keep-work" in text
    assert "cleanup_bake_img_baks" in text
    assert "NLPP_NO_IMG_BACKUP" in text
    assert "seed_vanilla_bak" not in text


def test_extract_deletes_work_dir():
    text = (SRC / "extract_vanilla_from_rom.py").read_text(encoding="utf-8")
    assert 'label="extract_vanilla_work"' in text
    assert 'label="extract_vanilla_code_work"' in text


def test_patch_cia_drops_intermediates_during_rebuild():
    text = (SRC / "patch_cia.py").read_text(encoding="utf-8")
    assert "extracted CXI" in text
    assert "split romfs.bin" in text
    assert "injected RomFS tree" in text
    assert "romfs_patched.bin" in text
    assert "patched.cxi" in text


def test_pack_images_cleans_per_package():
    text = (SRC / "pack_images.py").read_text(encoding="utf-8")
    assert "cleanup_package_unpack" in text
    assert "One package at a time" in text
    assert 'label="pack img_data"' in text
    assert "elapsed={timer.elapsed_str()}" in text
    assert 'f"elapsed:          {timer.elapsed_str()}"' in text


def test_splice_packages_patches_slot_in_place(tmp_path: Path, monkeypatch):
    import sys
    import types

    img_bin = tmp_path / "img.bin"
    original = bytearray(b"\x11" * 64)
    img_bin.write_bytes(original)
    img_data = tmp_path / "img_data"
    img_data.mkdir()
    (img_data / "new_0007").write_bytes(b"MAIL")

    class FW:
        base_offset = 16

        def len(self) -> int:
            return 8

    class Entry:
        fw = FW()

    class FakeImage:
        def __init__(self, _path: str):
            self.entries = [None] * 8
            self.entries[7] = Entry()

        def parse(self, _full: bool) -> None:
            return None

    fake = types.ModuleType("img")
    fake.Image = FakeImage
    monkeypatch.setitem(sys.modules, "img", fake)

    pack_images.splice_packages_into_img(img_bin, img_data, [7], img_bin)
    data = img_bin.read_bytes()
    assert len(data) == 64
    assert data[16:24] == b"MAIL\x00\x00\x00\x00"
    assert data[:16] == b"\x11" * 16
    assert data[24:] == b"\x11" * 40

    (img_data / "new_0007").write_bytes(b"TOO-LONG!!")
    pack_images.splice_packages_into_img(img_bin, img_data, [7], img_bin)
    assert img_bin.read_bytes() == data


def test_rebuild_cleanup_scratch_skips_when_keep_work(monkeypatch):
    called = {"n": 0}

    def fake_cleanup(**_kw):
        called["n"] += 1

    monkeypatch.setattr(rebuild, "cleanup_out_dir", fake_cleanup)
    rebuild.cleanup_rebuild_scratch(keep_work=True)
    assert called["n"] == 0
    rebuild.cleanup_rebuild_scratch(keep_work=False)
    assert called["n"] == 1
