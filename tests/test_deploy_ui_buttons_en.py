"""EN UI button PNGs → BCLIMs inside img.bin packages (exact-zlib splice)."""

from __future__ import annotations

import random
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image

import fake_img as fi
from bclimutil import parse_bclim
from conftest import TOOLS, load_module
from darcutil import DarcArchive

ui = load_module("deploy_ui_buttons_en", TOOLS / "deploy_ui_buttons_en.py")
NOTE = b"untouched note"


def _arc(stems: list[str], real_size_dir: Path | None = None) -> bytes:
    """One BCLIM per stem. A small PNG keeps its own size (no resize).

    Noise pixels, so the zlib slot is as roomy as real artwork's. Big canvases
    are shrunk to 8x8: zopfli on 128KB of noise takes seconds.
    """
    rng = random.Random(len(stems))
    files = {}
    for stem in stems:
        w, h = 8, 8
        if real_size_dir is not None:
            size = Image.open(real_size_dir / f"{stem}.png").size
            if max(size) <= 64:
                w, h = size
        size = len(parse_bclim(fi.bclim(w, h))[0])
        files[f"timg/{stem}.bclim"] = fi.bclim(w, h, pixels=rng.randbytes(size))
    return fi.darc(files)


def _group_pkg(group: dict) -> bytes:
    elems = [("Other.arc", fi.darc({"timg/x.bclim": fi.bclim(8, 8)}))]
    for arc_name, d in zip(group["arcs"], group["asset_dirs"]):
        elems.append((arc_name, _arc(group["stems"], d)))
    elems.append(("note.txt", NOTE, b"TXT ", False))
    return fi.package(elems)


def _bclims(img: Path, pkg: int, arc_name: str, tmp: Path) -> dict[str, bytes]:
    arc = DarcArchive(fi.read_element(fi.read_package(img, pkg), arc_name, tmp))
    return {f.name: arc.extract_file(f) for f in arc.files}


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    fi.use_paths(monkeypatch, tmp_path, ui)
    img = tmp_path / "img.bin"
    img.write_bytes(fi.img({g["pkg"]: _group_pkg(g) for g in ui.GROUPS}))
    monkeypatch.setattr(ui, "MOD_IMG", img)
    monkeypatch.setattr(ui, "VANILLA", img)
    return img


def test_main_deploys_every_real_group(env, tmp_path: Path):
    before = {
        (g["pkg"], arc): _bclims(env, g["pkg"], arc, tmp_path) for g in ui.GROUPS for arc in (*g["arcs"], "Other.arc")
    }
    stale = ui.OUT / "_fit" / "stale.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    assert ui.main() == 0
    assert not stale.exists()
    for group in ui.GROUPS:
        for arc_name in group["arcs"]:
            got = _bclims(env, group["pkg"], arc_name, tmp_path)
            for stem in group["stems"]:
                name = f"timg/{stem}.bclim"
                assert got[name] != before[group["pkg"], arc_name][name], f"{group['pkg']} {arc_name} {stem}"
        assert fi.read_element(fi.read_package(env, group["pkg"]), "note.txt", tmp_path) == NOTE
        assert _bclims(env, group["pkg"], "Other.arc", tmp_path) == before[group["pkg"], "Other.arc"]


def test_main_needs_img(env, monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "MOD_IMG", tmp_path / "none.bin")
    with pytest.raises(SystemExit, match="missing deploy img"):
        ui.main()


def test_main_reports_splice_failure(env, monkeypatch):
    monkeypatch.setattr(ui, "GROUPS", [g for g in ui.GROUPS if g["pkg"] == 4149])

    def fail(*_a):
        raise ui.PackError("grew")

    monkeypatch.setattr(ui, "splice_packages_into_img", fail)
    with pytest.raises(SystemExit, match="splice failed: grew"):
        ui.main()


# --- single groups -------------------------------------------------------

def _png(folder: Path, stem: str, size=(8, 8)) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (255, 0, 0, 255)).save(folder / f"{stem}.png")


def _custom(tmp_path: Path, monkeypatch, *, arcs=("A.arc",), asset_dirs=None, from_live=False, pkg=7):
    asset_dirs = asset_dirs if asset_dirs is not None else (tmp_path / "assets" / "A",)
    group = {
        "pkg": pkg,
        "arcs": arcs,
        "asset_dirs": asset_dirs,
        "desktop": tmp_path / "desktop",
        "stems": ["S1"],
        "from_live": from_live,
    }
    img = tmp_path / "img.bin"
    pkg_dir = tmp_path / "pkgs"
    pkg_dir.mkdir()
    monkeypatch.setattr(ui, "MOD_IMG", img)
    monkeypatch.setattr(ui, "VANILLA", tmp_path / "no_vanilla.bin")
    return group, img, pkg_dir


def test_ensure_staged_copies_desktop_pngs(tmp_path: Path, monkeypatch):
    group, *_ = _custom(tmp_path, monkeypatch)
    with pytest.raises(SystemExit, match="missing PNGs for pkg 7"):
        ui._ensure_staged(group)
    _png(group["desktop"], "S1")
    assert ui._ensure_staged(group) == group["asset_dirs"][0]
    assert (group["asset_dirs"][0] / "S1.png").is_file()


def test_png_for_missing(tmp_path: Path):
    with pytest.raises(SystemExit, match="missing PNG"):
        ui._png_for("Nope", tmp_path)


def test_patch_arc_finds_top_level_and_rejects_missing(tmp_path: Path):
    _png(tmp_path / "src", "S1")
    arc = fi.darc({"S1.bclim": fi.bclim(8, 8)})
    out = ui._patch_arc(arc, ["S1"], tmp_path / "src", tmp_path)
    assert out != arc and len(out) == len(arc)
    with pytest.raises(SystemExit, match="missing BCLIM timg/S2.bclim"):
        ui._patch_arc(arc, ["S2"], tmp_path / "src", tmp_path)


def test_patch_arc_rejects_size_change(tmp_path: Path, monkeypatch):
    _png(tmp_path / "src", "S1")
    monkeypatch.setattr(ui, "png_to_bclim_same_size", lambda png, orig: b"short")
    with pytest.raises(SystemExit, match="size change S1"):
        ui._patch_arc(fi.darc({"timg/S1.bclim": fi.bclim(8, 8)}), ["S1"], tmp_path / "src", tmp_path)


def test_write_arc_slot_checks(tmp_path: Path):
    blob = bytearray(fi.package([("A.arc", b"x" * 64), ("t.txt", b"plain", b"TXT ", False)]))
    _t, dec_len, _o, _f, _c, slot_len, _off = struct.unpack_from("<4s4x6I", blob, 0x20)
    with pytest.raises(SystemExit, match="entry 1 not compressed"):
        ui._write_arc_slot(blob, 1, b"plain", b"")
    with pytest.raises(SystemExit, match="entry 0 mismatch"):
        ui._write_arc_slot(blob, 0, b"x" * dec_len, b"\0" * (slot_len + 1))


def test_deploy_group_falls_back_to_mod_img_and_shared_dir(tmp_path: Path, monkeypatch):
    # Two arcs, one asset dir: lengths differ, so the shared staged dir is used.
    shared = tmp_path / "assets" / "shared"
    group, img, pkg_dir = _custom(tmp_path, monkeypatch, arcs=("A.arc", "B.arc"), asset_dirs=(shared,))
    _png(shared, "S1")
    img.write_bytes(fi.img({7: fi.package([("A.arc", _arc(["S1"])), ("B.arc", _arc(["S1"]))])}))
    new = ui._deploy_group(group, pkg_dir, tmp_path)
    assert new == pkg_dir / "new_0007"


def test_deploy_group_skips_missing_per_arc_dir(tmp_path: Path, monkeypatch):
    # Same count of arcs and dirs, but the matching dir is absent: use the staged dir.
    a, b = tmp_path / "assets" / "A", tmp_path / "assets" / "B"
    group, img, pkg_dir = _custom(tmp_path, monkeypatch, arcs=("A.arc", "B.arc"), asset_dirs=(a, b), from_live=True)
    _png(a, "S1")
    img.write_bytes(fi.img({7: fi.package([("B.arc", _arc(["S1"]))])}))
    assert ui._deploy_group(group, pkg_dir, tmp_path).is_file()


def test_deploy_group_errors(tmp_path: Path, monkeypatch):
    group, img, pkg_dir = _custom(tmp_path, monkeypatch)
    _png(group["asset_dirs"][0], "S1")

    img.write_bytes(fi.img({7: fi.package([("Z.arc", _arc(["S1"]))])}))
    with pytest.raises(SystemExit, match="no matching ARCs in pkg 7"):
        ui._deploy_group(group, pkg_dir, tmp_path)

    img.write_bytes(fi.img({7: fi.package([("A.arc", _arc(["S1"])), ("t.txt", NOTE, b"TXT ", False)])}))
    monkeypatch.setattr(ui, "compress_exact_zopfli", lambda data, n: (data, zlib.compress(b"other")))
    with pytest.raises(SystemExit, match="zlib verify failed for A.arc"):
        ui._deploy_group(group, pkg_dir, tmp_path)
    monkeypatch.undo()
    fi.use_paths(monkeypatch, tmp_path, ui)
    monkeypatch.setattr(ui, "MOD_IMG", img)
    monkeypatch.setattr(ui, "VANILLA", tmp_path / "no_vanilla.bin")

    real_write = ui._write_arc_slot

    def clobber_note(blob, i, tuned, slot):
        real_write(blob, i, tuned, slot)
        blob[blob.index(NOTE)] ^= 0xFF

    monkeypatch.setattr(ui, "_write_arc_slot", clobber_note)
    with pytest.raises(SystemExit, match="non-target changed: t.txt"):
        ui._deploy_group(group, pkg_dir, tmp_path)
