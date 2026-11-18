"""PNG masters a deploy rebuilt away are re-applied on top of the bake."""

from __future__ import annotations

import pytest
from conftest import TOOLS, load_module
from PIL import Image

sv = load_module("deploy_pack_survivors_en", TOOLS / "deploy_pack_survivors_en.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")

PKG = 7
ARC = "Test.arc"
FOLDER = "Test.check"


def _bclim(seed: int) -> bytes:
    import fake_img as fi

    return fi.bclim(8, 8, 8, bytes((seed + i) % 251 for i in range(8 * 8 * 2)))


def _arc(**files: bytes) -> bytes:
    import fake_img as fi

    return fi.darc({f"timg/{n}.bclim": data for n, data in files.items()})


def _package(arc: bytes, extra=()) -> bytes:
    import fake_img as fi

    return fi.package([(ARC, arc), *extra])


def _master(tmp_path, name: str, colour=(10, 200, 30, 255)):
    root = tmp_path / "images" / FOLDER / "timg"
    root.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), colour).save(root / f"{name}.png")
    return root / f"{name}.png"


def _decoded(arc: bytes, name: str):
    from bclimutil import decode_bclim_to_image
    from darcutil import DarcArchive

    darc = DarcArchive(arc)
    return decode_bclim_to_image(darc.extract_file(darc.find(f"timg/{name}.bclim"))).convert("RGBA")


def test_inject_fills_only_textures_still_vanilla(tmp_path):
    van = _arc(A=_bclim(1), B=_bclim(2))
    cur = _arc(A=_bclim(1), B=_bclim(9))  # a deploy already replaced B
    masters = [_master(tmp_path, "A"), _master(tmp_path, "B")]
    new, applied = sv.inject(van, cur, masters, tmp_path / "w")
    assert applied == ["A"]
    assert _decoded(new, "A").getpixel((0, 0)) == (0, 187, 17, 255)  # RGBA4444 of the master
    assert _decoded(new, "B").tobytes() == _decoded(cur, "B").tobytes()
    with pytest.raises(SystemExit, match="no timg/C.bclim"):
        sv.inject(van, cur, [_master(tmp_path, "C")], tmp_path / "w")


def _env(tmp_path, monkeypatch, vanilla_pkgs, mod_pkgs, survivors):
    import fake_img as fi

    fi.use_paths(monkeypatch, tmp_path, sv)
    vanilla, mod = tmp_path / "vanilla.bin", tmp_path / "release" / "bake_img.bin"
    vanilla.write_bytes(fi.img(vanilla_pkgs, count=PKG + 2))
    mod.parent.mkdir(parents=True, exist_ok=True)
    mod.write_bytes(fi.img(mod_pkgs, count=PKG + 2))
    monkeypatch.setattr(sv, "MOD_IMG", mod)
    monkeypatch.setattr(sv, "_VANILLA", vanilla)
    monkeypatch.setattr(sv, "OUT", tmp_path / "out")
    monkeypatch.setattr(sv, "ASSETS", tmp_path / "images")
    monkeypatch.setattr(sv, "SURVIVORS", survivors)
    monkeypatch.setattr(sv, "resolve_folder", lambda f: (PKG, ARC) if f == FOLDER else None)
    return mod


def test_main_reapplies_masters_on_top_of_the_bake(tmp_path, monkeypatch, capsys):
    import fake_img as fi

    _master(tmp_path, "A")
    van = _package(_arc(A=_bclim(1), B=_bclim(2)))
    bake = _package(_arc(A=_bclim(1), B=_bclim(9)))  # B is a deploy's edit
    mod = _env(tmp_path, monkeypatch, {PKG: van}, {PKG: bake}, {FOLDER: ["A"]})
    assert sv.main() == 0
    arc = fi.read_element(fi.read_package(mod, PKG), ARC, tmp_path)
    assert _decoded(arc, "A").getpixel((0, 0)) == (0, 187, 17, 255)
    assert _decoded(arc, "B").tobytes() == _decoded(_arc(B=_bclim(9)), "B").tobytes()
    assert "OK pkg 7 Test.arc <- Test.check: A" in capsys.readouterr().out
    before = mod.read_bytes()
    assert sv.main() == 0  # A is no longer vanilla: nothing left to do
    assert mod.read_bytes() == before
    assert "nothing left vanilla" in capsys.readouterr().out


def test_main_errors(tmp_path, monkeypatch):
    _master(tmp_path, "A")
    van = _package(_arc(A=_bclim(1)))
    _env(tmp_path, monkeypatch, {PKG: van}, {PKG: van}, {FOLDER: ["A"]})

    def boom(*_a):
        raise sv.PackError("grew")

    monkeypatch.setattr(sv, "splice_packages_into_img", boom)
    with pytest.raises(SystemExit, match="splice failed: grew"):
        sv.main()

    def no_fit(data, n):
        raise RuntimeError("too big")

    monkeypatch.setattr(sv, "compress_to_exact_slot", no_fit)
    with pytest.raises(SystemExit, match=r"1 master\(s\) do not fit"):
        sv.main()
    monkeypatch.setattr(sv, "compress_to_exact_slot", lambda data, n: __import__("zlib").compress(b"x"))
    with pytest.raises(SystemExit, match="wrong length"):
        sv.main()

    monkeypatch.setattr(sv, "_VANILLA", sv.MOD_IMG.parent / "none.bin")
    with pytest.raises(SystemExit, match="missing vanilla"):
        sv.main()
    monkeypatch.setattr(sv, "MOD_IMG", sv.MOD_IMG.parent / "none.bin")
    with pytest.raises(SystemExit, match="missing"):
        sv.main()


def test_package_and_arc_must_exist(tmp_path, monkeypatch):
    import fake_img as fi

    _master(tmp_path, "A")
    van = _package(_arc(A=_bclim(1)))
    _env(tmp_path, monkeypatch, {PKG: van}, {PKG + 1: van}, {FOLDER: ["A"]})
    with pytest.raises(SystemExit, match="pkg 7 missing in"):
        sv.main()
    other = fi.package([("Other.arc", _arc(A=_bclim(1)))])
    _env(tmp_path, monkeypatch, {PKG: other}, {PKG: other}, {FOLDER: ["A"]})
    with pytest.raises(SystemExit, match="no Test.arc"):
        sv.main()


def test_plan_checks_folders_and_masters(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "ASSETS", tmp_path / "images")
    monkeypatch.setattr(sv, "resolve_folder", lambda f: (PKG, ARC) if f == FOLDER else None)
    _master(tmp_path, "A")
    assert sv.plan({FOLDER: ["A"]}) == {PKG: [(FOLDER, ARC, [tmp_path / "images" / FOLDER / "timg" / "A.png"])]}
    with pytest.raises(SystemExit, match=r"missing masters \['Z.png'\]"):
        sv.plan({FOLDER: ["A", "Z"]})
    with pytest.raises(SystemExit, match="not in image_map"):
        sv.plan({"Nope.check": ["A"]})


def test_shipped_survivor_list_resolves():
    """Every listed master exists and maps to a package (no game data needed)."""
    plan = sv.plan()
    assert {pkg for pkg in plan} == {5153, 5207, 5237, 5252}
    assert sum(len(m) for jobs in plan.values() for *_x, m in jobs) == 43


def test_bake_runs_survivors_after_ui_deploys_before_cesa():
    scripts = rebuild.DEPLOY_SCRIPTS
    i = scripts.index("deploy_pack_survivors_en.py")
    assert scripts[-1] == "deploy_cesa_en.py" and i == len(scripts) - 2
    for name in ("deploy_gallery_common_en.py", "deploy_profile_en.py", "deploy_multiwin_headers_en.py"):
        assert scripts.index(name) < i
