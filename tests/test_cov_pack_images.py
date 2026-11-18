"""Coverage for pack_images: the package ProcessPool path, png2bclim fallback,
exact-slot repack guards, and selective ie repack, on tiny synthetic data.

The pool is replaced by an in-process executor, so its status queue, drain
thread and result loop run under coverage on every OS.
"""

from __future__ import annotations

import sys
import time
import types
from concurrent.futures import Future
from pathlib import Path

import pytest

import fake_img as fi
import pack_images as pack
from image_map import IMAGE_MAP


class _Live:
    active = True

    def __init__(self) -> None:
        self.jobs: list[tuple] = []
        self.logs: list[str] = []

    def set_progress(self, *a, **k):
        return None

    def set_job(self, key, line):
        self.jobs.append((key, line))

    def log(self, line):
        self.logs.append(line)

    def clear_job(self, *a, **k):
        return None

    def clear_jobs(self):
        return None


def _two_folders(root: Path) -> list[str]:
    """Image folders that map to two different packages."""
    seen: dict[int, str] = {}
    for key, (index, _arc) in sorted(IMAGE_MAP.items()):
        if index not in seen:
            seen[index] = key
        if len(seen) == 2:
            break
    for key in seen.values():
        (root / key).mkdir(parents=True)
        (root / key / "A.png").write_bytes(b"png")
    return list(seen.values())


def test_run_failure_without_live(monkeypatch):
    monkeypatch.setattr(pack, "live", types.SimpleNamespace(active=False))
    monkeypatch.setattr(
        pack.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=3, stdout="", stderr="bad")
    )
    with pytest.raises(pack.PackError, match="command failed \\(3\\)"):
        pack._run(["tool", "arg"])


def test_iter_asset_pngs_keeps_best_rank(tmp_path):
    folder = tmp_path / "f"
    (folder / "timg").mkdir(parents=True)
    for rel in ("A_en.png", "A.png", "timg/A.png", "timg/A_en.png"):
        (folder / rel).write_bytes(b"png")
    picked = pack.iter_asset_pngs(folder)
    assert len(picked) == 1 and picked[0].stem == "A_en"


def test_bclim_valid_same_size():
    assert pack._bclim_looks_valid(Path(__file__), Path(__file__).stat().st_size) == (True, "")


def test_convert_png_via_png2bclim_and_cache(tmp_path, monkeypatch):
    work = tmp_path / "work"
    (work / "stale_dir").mkdir(parents=True)
    (work / "stale.bin").write_bytes(b"old")
    orig = tmp_path / "Odd.bclim"
    orig.write_bytes(fi.bclim(8, 8, 7, pixels=bytes(160)))
    png = tmp_path / "Odd.png"
    png.write_bytes(b"png")
    tool = tmp_path / "png2bclim.exe"
    tool.write_bytes(b"")
    monkeypatch.setattr(pack, "PNG2BCLIM", tool)

    def fake_run(cmd, cwd=None):
        (Path(cwd) / "OddX.bclim").write_bytes(orig.read_bytes())

    monkeypatch.setattr(pack, "_run", fake_run)
    cache = pack.ImgPackCache(tmp_path / "cache")
    out = pack.convert_png_to_bclim(png, orig, work, cache=cache)
    assert out.read_bytes() == orig.read_bytes()
    assert not (work / "stale.bin").exists() and (work / "stale_dir").is_dir()
    assert cache.get_bclim(b"png", orig.read_bytes()) == orig.read_bytes()


def test_patch_arc_clears_old_extract(tmp_path, monkeypatch):
    arc = tmp_path / "Album.arc"
    arc.write_bytes(fi.darc({"timg/A.bclim": fi.bclim(8, 8)}))
    work = tmp_path / "work"
    (work / "extract" / "old").mkdir(parents=True)
    ok, skipped, warnings = pack.patch_arc_with_pngs(arc, [], work)
    assert (ok, skipped) == (0, 0)
    assert not (work / "extract" / "old").exists()


def _without(monkeypatch, path) -> None:
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(path)])


def test_tool_paths_are_added_on_demand(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(fi.img({0: fi.package([("A.arc", b"x")])}))
    _without(monkeypatch, pack.NLPP_TOOLS)
    assert pack.img_idx_mismatches(img) == []
    for call in (
        lambda: pack.repack_package_exact_slots(tmp_path, 5),
        lambda: pack.splice_packages_into_img(img, tmp_path, [5], tmp_path / "o.bin"),
        lambda: pack.selective_ie_repack(img, tmp_path, tmp_path / "o.bin", [5]),
    ):
        _without(monkeypatch, pack.NLPP_TOOLS)
        with pytest.raises(pack.PackError, match="missing"):
            call()
        assert str(pack.NLPP_TOOLS) in sys.path

    src_dir = str(Path(pack.__file__).resolve().parent)
    _without(monkeypatch, src_dir)
    res = pack._process_one_package(1, [], str(tmp_path / "nodata"), str(tmp_path / "conv"))
    assert src_dir in sys.path and res["ok"] is False


def _exact_slot_setup(tmp_path: Path, payload: bytes, new: bytes) -> Path:
    img_data = tmp_path / "data"
    (img_data / "0009_data").mkdir(parents=True)
    (img_data / "0009").write_bytes(fi.package([("A.arc", payload)]))
    (img_data / "0009_data" / "A.arc").write_bytes(new)
    return img_data


def test_exact_slots_skip_none_entries_and_catch_drift(tmp_path, monkeypatch):
    img_data = _exact_slot_setup(tmp_path, b"a" * 64, b"b" * 64)
    import img as nlpp_img

    real_parse = nlpp_img.Package.parse

    def parse_with_hole(self, deep):
        real_parse(self, deep)
        self.entries.insert(0, None)

    monkeypatch.setattr(nlpp_img.Package, "parse", parse_with_hole)
    monkeypatch.setattr(pack, "compress_to_exact_slot_cached", lambda data, n, **k: b"z" * (n + 1))
    with pytest.raises(pack.PackError, match="size drift"):
        pack.repack_package_exact_slots(img_data, 9)


def test_selective_ie_repack_success_and_short_output(tmp_path, monkeypatch, capsys):
    a = fi.package([("A.arc", b"alpha" * 20)])
    b = fi.package([("B.arc", b"beta" * 20)])
    src = tmp_path / "img.bin"
    src.write_bytes(fi.img({0: a, 1: b}))
    img_data = tmp_path / "data"
    img_data.mkdir()
    new_a = fi.package([("A.arc", b"ALPHA" * 20)])
    (img_data / "new_0000").write_bytes(new_a)
    dst = tmp_path / "out.bin"
    pack.selective_ie_repack(src, img_data, dst, [0])
    pack.selective_ie_repack(src, img_data, dst, [0])  # replaces the old output
    assert fi.read_package(dst, 0) == new_a
    assert fi.read_package(dst, 1) == b
    assert "selective repack" in capsys.readouterr().out

    import img as nlpp_img

    monkeypatch.setattr(nlpp_img.Image, "write", lambda self, fh: fh.write(b"tiny"))
    with pytest.raises(pack.PackError, match="selective ie repack failed"):
        pack.selective_ie_repack(src, img_data, dst, [0])


def test_process_one_package_case_insensitive_arc_and_few_warnings(tmp_path, monkeypatch):
    arc_dir = tmp_path / "img" / "0007_data"
    arc_dir.mkdir(parents=True)
    (arc_dir / "Album.arc").write_bytes(b"arc")
    folder = tmp_path / "album"
    folder.mkdir()
    (folder / "A.png").write_bytes(b"png")
    monkeypatch.setattr(pack, "ensure_package_data", lambda *a, **k: arc_dir)
    monkeypatch.setattr(pack, "patch_arc_with_pngs", lambda *a, **k: (1, 0, ["one warning"]))
    monkeypatch.setattr(pack, "repack_package_exact_slots", lambda *a, **k: arc_dir / "new")
    monkeypatch.setattr(pack, "cleanup_package_unpack", lambda *a, **k: None)
    monkeypatch.setattr(pack, "remove_scratch", lambda *a, **k: None)
    # A case-sensitive file system misses ALBUM.ARC; force that on Windows too.
    real_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda self: False if self.name == "ALBUM.ARC" else real_is_file(self))
    items = [("album", str(folder), "ALBUM.ARC"), ("album2", str(folder), "ALBUM.ARC")]
    res = pack._process_one_package(7, items, str(tmp_path / "img"), str(tmp_path / "conv"))
    assert res["ok"] and res["arcs"] == 2
    assert res["report"].count("[warn] album: one warning") == 1


class _InlinePool:
    """ProcessPoolExecutor stand-in: runs each job when submitted."""

    def __init__(self, max_workers, initializer=None, initargs=()):
        self.max_workers = max_workers
        self.streams = None
        if initializer is not None:
            # A worker process's stdout/stderr: swap them in only per job.
            saved = sys.stdout, sys.stderr
            initializer(*initargs)
            self.streams = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = saved

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args):
        fut: Future = Future()
        saved = sys.stdout, sys.stderr
        if self.streams:
            sys.stdout, sys.stderr = self.streams
        try:
            fut.set_result(fn(*args))
        finally:
            sys.stdout, sys.stderr = saved
        return fut


def test_pack_images_process_pool(tmp_path, monkeypatch):
    images = tmp_path / "images"
    keys = _two_folders(images)
    imgf = tmp_path / "in.bin"
    imgf.write_bytes(b"IMG")
    live = _Live()
    # _pool_init swaps sys.stdout/stderr for status streams; put them back after.
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(pack, "live", live)
    monkeypatch.setattr(pack, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(pack, "unpack_packages", lambda *a, **k: None)
    monkeypatch.setattr(pack, "ensure_package_data", lambda *a, **k: tmp_path)
    monkeypatch.setattr(pack, "splice_packages_into_img", lambda *a, **k: None)
    monkeypatch.setattr(pack, "remove_scratch", lambda *a, **k: None)

    def worker(index, items, img_data, conv, png_workers, fine_tune, cache_dir):
        print(f"working {index}")
        sys.stderr.write("warn line\n")
        sys.stderr.flush()
        q = pack_queue[0]
        q.put("not a tuple")
        time.sleep(0.4)  # let the drain thread time out once
        return {"index": index, "ok": True, "touched": True, "png_ok": 1, "png_skip": 0,
                "arcs": 1, "report": [], "error": None}

    pack_queue: list = []
    real_init = pack._pool_init

    def init(q):
        pack_queue.append(q)
        real_init(q)

    monkeypatch.setattr(pack, "_pool_init", init)
    monkeypatch.setattr(pack, "_process_one_package", worker)
    totals = pack.pack_images(images, imgf, tmp_path / "work", tmp_path / "out.bin",
                              only_keys=set(keys), workers=2, pkg_workers=2, cache=False)
    assert totals["packages"] == 2
    assert any("working" in line for _k, line in live.jobs)
    assert any("warn line" in line for line in live.logs)


def test_pack_images_process_pool_without_live(tmp_path, monkeypatch):
    images = tmp_path / "images"
    keys = _two_folders(images)
    imgf = tmp_path / "in.bin"
    imgf.write_bytes(b"IMG")
    monkeypatch.setattr(pack, "live", types.SimpleNamespace(active=False))
    monkeypatch.setattr(pack, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(pack, "unpack_packages", lambda *a, **k: None)
    monkeypatch.setattr(pack, "ensure_package_data", lambda *a, **k: tmp_path)
    monkeypatch.setattr(pack, "splice_packages_into_img", lambda *a, **k: None)
    monkeypatch.setattr(pack, "remove_scratch", lambda *a, **k: None)
    monkeypatch.setattr(
        pack,
        "_process_one_package",
        lambda index, *a: {"index": index, "ok": True, "touched": True, "png_ok": 1,
                           "png_skip": 0, "arcs": 1, "report": [], "error": None},
    )
    totals = pack.pack_images(images, imgf, tmp_path / "work", tmp_path / "out.bin",
                              only_keys=set(keys), workers=2, pkg_workers=2, cache=False)
    assert totals["packages"] == 2


def test_main_without_deploy(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(pack, "pack_images", lambda *a, **k: seen.setdefault("called", True))
    assert pack.main(["--images", str(tmp_path), "--img-bin", str(tmp_path / "i.bin"),
                      "--work", str(tmp_path / "w"), "--out", str(tmp_path / "o.bin")]) == 0
    assert seen["called"]


def test_convert_same_size_without_cache(tmp_path):
    from PIL import Image

    orig = tmp_path / "A.bclim"
    orig.write_bytes(fi.bclim(8, 8, 8))
    png = tmp_path / "A.png"
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(png)
    out = pack.convert_png_to_bclim(png, orig, tmp_path / "w")
    assert len(out.read_bytes()) == len(orig.read_bytes())


def test_splice_non_pack_blob(tmp_path):
    pkg = fi.package([("A.arc", b"hello-arc-body")])
    src = tmp_path / "img.bin"
    src.write_bytes(fi.img({0: pkg}))
    img_data = tmp_path / "data"
    img_data.mkdir()
    (img_data / "new_0000").write_bytes(b"RAW!" + bytes(12))
    dst = tmp_path / "dst.bin"
    pack.splice_packages_into_img(src, img_data, [0], dst)
    assert dst.read_bytes() != src.read_bytes()
