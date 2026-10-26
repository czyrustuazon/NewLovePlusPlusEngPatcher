"""Incremental scratch cleanup so Drop CIA does not hold GB-scale temps until the end."""

from __future__ import annotations

import sys
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


def test_wipe_directory_deletes_past_max_path(tmp_path: Path):
    """Citra sdmc backups exceed 260 characters and break a plain rmtree.

    Drop wipes out/, release/, and cache/ through the same helper.
    """
    if sys.platform != "win32":
        pytest.skip("MAX_PATH only applies on Windows")
    root = tmp_path / "repo"
    for name in ("out", "release", "cache"):
        folder = root / name
        # 32-hex id folders, same shape as a Citra Nintendo 3DS save tree.
        deep = folder / "extdata_backup" / ("pre_NR citra")
        deep = deep / "sdmc" / "Nintendo 3DS" / ("0" * 32) / ("0" * 32)
        deep = deep / "title" / "00040000" / "000f4e00" / "data" / "00000001"
        leaf = deep / "savedata10"
        cleanup.long_path(deep).mkdir(parents=True, exist_ok=True)
        cleanup.long_path(leaf).write_bytes(b"save")
        assert len(str(leaf)) > 260

        cleanup.wipe_directory(folder, root=root)

        assert folder.is_dir() and list(folder.iterdir()) == []
        assert not cleanup.long_path(leaf).exists()


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


def test_cleanup_out_dir_prints_no_summary_line(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.setattr(patch_cia, "ROOT", tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    cia = out / "NewLovePlusPlus-EN.cia"
    cia.write_bytes(b"cia")
    (out / "scratch").mkdir()
    patch_cia.cleanup_out_dir(out_cia=cia)
    captured = capsys.readouterr().out
    assert "out/ kept" not in captured
    assert "already clean" not in captured
    assert cia.is_file()
    assert not (out / "scratch").exists()


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


def test_is_reparse_dir_plain_dir_symlink_and_junction_error(tmp_path: Path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert cleanup.is_reparse_dir(plain) is False
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "link")
    assert cleanup.is_reparse_dir(tmp_path / "link") is True

    def broken(self):
        raise OSError("no junction info")

    monkeypatch.setattr(Path, "is_junction", broken, raising=False)
    assert cleanup.is_reparse_dir(plain) is False


def _fake_reparse(monkeypatch, *names: str) -> None:
    """Treat dirs with these names as junctions; unlink on them fails like a real dir."""
    monkeypatch.setattr(cleanup, "is_reparse_dir", lambda p: p.name in names)


def test_wipe_directory_handles_junction_file_and_nested_romfs(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "repo"
    missing = root / "fresh"
    cleanup.wipe_directory(missing, root=root)
    assert missing.is_dir() and "created empty" in capsys.readouterr().out

    _fake_reparse(monkeypatch, "junction", "romfs")
    junction = root / "junction"
    junction.mkdir()
    cleanup.wipe_directory(junction, root=root)  # unlink fails on a dir -> rmdir
    assert junction.is_dir() and list(junction.iterdir()) == []

    as_file = root / "as_file"
    as_file.write_bytes(b"x")
    cleanup.wipe_directory(as_file, root=root)
    assert as_file.is_dir()

    inst = root / "inst"
    (inst / "romfs").mkdir(parents=True)
    (inst / "save.bin").write_bytes(b"s")
    cleanup.wipe_directory(inst, root=root)
    assert inst.is_dir() and list(inst.iterdir()) == []


def test_wipe_directory_reports_delete_failures(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    target = root / "out"
    target.mkdir(parents=True)

    def denied(_p):
        raise OSError("denied")

    monkeypatch.setattr(cleanup, "rmtree", denied)
    with pytest.raises(SystemExit, match="out/: denied"):
        cleanup.wipe_directory(target, root=root)
    monkeypatch.setattr(cleanup, "rmtree", lambda _p: None)
    with pytest.raises(SystemExit, match="still exists"):
        cleanup.wipe_directory(target, root=root)

    monkeypatch.setattr(cleanup, "rmtree", cleanup.shutil.rmtree)
    monkeypatch.setattr(Path, "iterdir", lambda self: iter([self / "ghost"]))
    with pytest.raises(SystemExit, match="not empty: ghost"):
        cleanup.wipe_directory(target, root=root)


def test_park_outside_copies_a_directory(tmp_path: Path):
    parent = tmp_path / "cache"
    src = parent / "romfs_dump"
    src.mkdir(parents=True)
    (src / "a.bin").write_bytes(b"a")
    parked = cleanup.park_outside(src, parent)
    assert (parked / "a.bin").read_bytes() == b"a"
    cleanup.shutil.rmtree(parked.parent)


def test_wipe_cia_build_dirs_parks_rom_and_wipes_all(tmp_path: Path, monkeypatch):
    import nlpp_paths

    root = tmp_path / "repo"
    dirs = {name: root / name.lower() for name in ("CACHE", "OUT", "RELEASE")}
    for name, d in dirs.items():
        (d / "junk").mkdir(parents=True)
        monkeypatch.setattr(nlpp_paths, name, d)
    monkeypatch.setattr(nlpp_paths, "ROOT", root)
    rom = dirs["RELEASE"] / "game.3ds"
    rom.write_bytes(b"rom")

    parked = cleanup.wipe_cia_build_dirs(rom)
    assert parked is not None and parked.read_bytes() == b"rom"
    for d in dirs.values():
        assert d.is_dir() and list(d.iterdir()) == []
    assert cleanup.wipe_cia_build_dirs(tmp_path / "gone.3ds") is None
    cleanup.shutil.rmtree(parked.parent)


def test_remove_scratch_edge_cases(tmp_path: Path, monkeypatch, capsys):
    cleanup.remove_scratch(None)

    def stat_fails(self):
        raise OSError("stat")

    with monkeypatch.context() as m:
        m.setattr(Path, "exists", stat_fails)
        cleanup.remove_scratch(tmp_path / "x")

    _fake_reparse(monkeypatch, "junction", "romfs")
    junction = tmp_path / "junction"
    junction.mkdir()
    cleanup.remove_scratch(junction, label="jn")  # unlink fails on a dir -> rmdir
    assert not junction.exists()

    work = tmp_path / "work"
    (work / "romfs" / "keep").mkdir(parents=True)  # non-empty: rmdir fails too, ignored
    cleanup.remove_scratch(work)
    assert "removing" in capsys.readouterr().out

    with monkeypatch.context() as m:
        m.setattr(Path, "is_file", lambda self: False)
        m.setattr(Path, "is_dir", lambda self: False)
        f = tmp_path / "odd"
        f.write_bytes(b"o")
        cleanup.remove_scratch(f)  # neither file nor dir: left alone
    assert f.exists()

    def boom(_p):
        raise OSError("busy")

    monkeypatch.setattr(cleanup, "is_reparse_dir", boom)
    cleanup.remove_scratch(f, label="odd")
    assert "warning: odd: busy" in capsys.readouterr().out


def test_long_path_windows_forms(monkeypatch):
    """Pure string rewrite, so it runs on Linux CI too with sys.platform faked."""
    monkeypatch.setattr(cleanup.sys, "platform", "win32")
    resolved = {
        r"C:\out": r"C:\repo\out",
        "rel": r"\\?\C:\already",
        "share": r"\\server\share\out",
    }

    def fake_resolve(self):
        if str(self) == "gone":
            raise OSError("offline")
        return Path(resolved[str(self)])

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    assert str(cleanup.long_path(Path(r"\\?\C:\x"))) == r"\\?\C:\x"
    assert str(cleanup.long_path(Path(r"C:\out"))) == r"\\?\C:\repo\out"
    assert str(cleanup.long_path(Path("rel"))) == r"\\?\C:\already"
    assert str(cleanup.long_path(Path("share"))) == r"\\?\UNC\server\share\out"
    assert str(cleanup.long_path(Path("gone"))) == r"\\?\gone"


def test_is_reparse_dir_without_is_junction(tmp_path: Path, monkeypatch):
    """Py3.10/3.11 path: Windows asks GetFileAttributesW; elsewhere it is False."""
    monkeypatch.setattr(Path, "is_junction", None, raising=False)
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(cleanup.sys, "platform", "linux")
    assert cleanup.is_reparse_dir(plain) is False
    monkeypatch.setattr(cleanup.sys, "platform", "win32")
    # Real kernel32 call on Windows; no ctypes.windll on Linux -> False.
    assert cleanup.is_reparse_dir(plain) is False


def test_wipe_cia_build_dirs_keeps_rom_outside_the_wiped_trees(tmp_path: Path, monkeypatch):
    import nlpp_paths

    root = tmp_path / "repo"
    for name in ("CACHE", "OUT", "RELEASE"):
        monkeypatch.setattr(nlpp_paths, name, root / name.lower())
    monkeypatch.setattr(nlpp_paths, "ROOT", root)
    rom = tmp_path / "desktop.3ds"
    rom.write_bytes(b"rom")
    assert cleanup.wipe_cia_build_dirs(rom) is None
    assert rom.read_bytes() == b"rom"
