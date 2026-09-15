"""Incremental scratch cleanup so Drop CIA does not hold GB-scale temps until the end."""

from __future__ import annotations

from pathlib import Path

from conftest import SRC, TOOLS, load_module

cleanup = load_module("scratch_cleanup", SRC / "scratch_cleanup.py")
pack_images = load_module("pack_images", SRC / "pack_images.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")
patch_cia = load_module("patch_cia", SRC / "patch_cia.py")


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
    assert "vanilla bake bak" in text


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


def test_rebuild_cleanup_scratch_skips_when_keep_work(monkeypatch):
    called = {"n": 0}

    def fake_cleanup(**_kw):
        called["n"] += 1

    monkeypatch.setattr(rebuild, "cleanup_out_dir", fake_cleanup)
    rebuild.cleanup_rebuild_scratch(keep_work=True)
    assert called["n"] == 0
    rebuild.cleanup_rebuild_scratch(keep_work=False)
    assert called["n"] == 1
