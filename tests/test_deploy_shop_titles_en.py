"""Shop title bars: raw ETC1A4 TEX streams in pkg 5789."""

from __future__ import annotations

import random
import struct
import zlib

import numpy as np
import pytest
from conftest import TOOLS, load_module
from PIL import Image

from bclimutil import decode_etc1a4_pixels

shop = load_module("deploy_shop_titles_en", TOOLS / "deploy_shop_titles_en.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")

TEX_LEN = 128 * 32
TITLES = [f"{n:02d}" for n in range(40)]
FLAT_COLOUR = bytes.fromhex("0000000026704850")


def _vanilla_tex(n: str) -> bytes:
    """Incompressible payload (a roomy slot); FLAT titles keep one colour block."""
    rng = random.Random(int(n))
    data = bytearray(rng.randbytes(TEX_LEN))
    if n in shop.FLAT:
        for i in range(0, TEX_LEN, 16):
            data[i + 8 : i + 16] = FLAT_COLOUR
    return bytes(data)


def _share(raw: bytes, leaders: dict[str, list[str]]) -> bytes:
    """Point every sharer's TEX entry at its leader's stream, as the game does."""
    import fake_img as fi

    out = bytearray(raw)
    for leader, sharers in leaders.items():
        lead = struct.unpack_from("<2I", out, fi.PKG_ENTRY * (2 * TITLES.index(leader) + 2) + 24)
        for n in sharers:
            struct.pack_into("<2I", out, fi.PKG_ENTRY * (2 * TITLES.index(n) + 2) + 24, *lead)
    return bytes(out)


def vanilla_pkg(*, rename: str = "", tex: dict[str, tuple] | None = None, shared=None) -> bytes:
    import fake_img as fi

    tex = tex or {}
    elements = []
    for n in TITLES:
        name = f"Shop_TitTxt{n}{'b' * (n == rename)}.texi"  # renamed, so entry positions hold
        elements.append((name, bytes(82), b"TEXI", False))
        elements.append((name, *tex.get(n, (_vanilla_tex(n), b"TEX ", True))))
    elements.append(("Shop_Bg.texi", b"\x05" * 64, b"TEX ", True))
    return _share(fi.package(elements), shop.SHARED if shared is None else shared)


def _write(tmp_path, raw: bytes):
    path = tmp_path / "5789.pkg"
    path.write_bytes(raw)
    return path


def _tex(raw: bytes, path, n: str) -> bytes:
    _dl, _c, cmp_len, cmp_off = shop.tex_entries(raw, path)[n]
    return zlib.decompress(raw[cmp_off : cmp_off + cmp_len])


def test_masters_exist_at_texture_size():
    for job in shop.JOBS:
        assert Image.open(shop.MASTERS / f"Shop_TitTxt{job}.png").size == shop.SIZE


def test_tex_entries_follow_shared_streams(tmp_path):
    raw = vanilla_pkg()
    entries = shop.tex_entries(raw, _write(tmp_path, raw))
    assert sorted(entries) == TITLES  # Shop_Bg and the TEXI rows are skipped
    assert entries["31"][3] == entries["30"][3]
    assert entries["32"][3] != entries["30"][3]


def test_patch_package_rewrites_each_job_in_its_slot(tmp_path):
    raw = vanilla_pkg()
    path = _write(tmp_path, raw)
    new = shop.patch_package(raw, path)
    assert len(new) == len(raw)
    assert new[: 0x20 * 82] == raw[: 0x20 * 82]  # header + entry table untouched
    new_path = tmp_path / "new.pkg"
    new_path.write_bytes(new)
    for n in TITLES:
        job = next((j for j, sharers in shop.SHARED.items() if n in sharers), n)
        got = _tex(new, new_path, n)
        if job not in shop.JOBS:
            assert got == _vanilla_tex(n)
            continue
        assert got != _vanilla_tex(n)
        px = np.array(decode_etc1a4_pixels(got, *shop.SIZE))
        want = np.array(Image.open(shop.MASTERS / f"Shop_TitTxt{job}.png").convert("RGBA"))
        assert np.abs(px[..., 3].astype(int) - want[..., 3]).max() <= 17
    flat = _tex(new, new_path, "29")
    assert {flat[i + 8 : i + 16] for i in range(0, TEX_LEN, 16)} == {FLAT_COLOUR}


def test_flat_colour_needs_a_single_vanilla_colour():
    old = bytes(16) + bytes(8) + b"\x01" * 8
    with pytest.raises(SystemExit, match="2 colour blocks"):
        shop.flat_colour(bytes(32), old, "29")
    assert shop.flat_colour(b"\xff" * 32, bytes(8) + FLAT_COLOUR * 3, "29") == (b"\xff" * 8 + FLAT_COLOUR) * 2


def test_patch_package_errors(tmp_path, monkeypatch):
    def fails(raw, match, masters=shop.MASTERS):
        with pytest.raises(SystemExit, match=match):
            shop.patch_package(raw, _write(tmp_path, raw), masters)

    fails(vanilla_pkg(rename="17"), "Shop_TitTxt17 missing")
    fails(vanilla_pkg(shared={"00": shop.SHARED["00"][:-1], "30": shop.SHARED["30"]}), "Shop_TitTxt00: stream shared by")
    fails(vanilla_pkg(shared={"00": shop.SHARED["00"], "30": ["30", "31", "32"]}), "Shop_TitTxt30: stream shared by")
    fails(vanilla_pkg(tex={"04": (_vanilla_tex("04"), b"TEX ", False)}), "cmp=0")
    fails(vanilla_pkg(tex={"04": (bytes(100), b"TEX ", True)}), "dec_len=100")

    masters = tmp_path / "masters"
    masters.mkdir()
    for job in shop.JOBS:
        Image.new("RGBA", (64, 16) if job == "21" else shop.SIZE).save(masters / f"Shop_TitTxt{job}.png")
    fails(vanilla_pkg(), r"Shop_TitTxt21.png is \(64, 16\)", masters)

    monkeypatch.setattr(shop, "try_compress_to_slot", lambda data, n: None)
    fails(vanilla_pkg(), "Shop_TitTxt00.png does not fit")


def _env(tmp_path, monkeypatch, packages=None):
    import fake_img as fi

    fi.use_paths(monkeypatch, tmp_path, shop)
    tmp_path.mkdir(exist_ok=True)
    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(fi.img(packages if packages is not None else {shop.PKG: vanilla_pkg()}, count=shop.PKG + 2))
    mod = tmp_path / "release" / "bake_img.bin"
    mod.parent.mkdir(parents=True)
    mod.write_bytes(vanilla.read_bytes())
    monkeypatch.setattr(shop, "MOD_IMG", mod)
    monkeypatch.setattr(shop, "OUT", tmp_path / "out")
    monkeypatch.setattr(shop, "_vanilla_src", lambda: vanilla)
    monkeypatch.setattr(shop, "_deploy_targets", lambda: [mod])
    return vanilla, mod


def test_main_splices_the_package(tmp_path, monkeypatch):
    import fake_img as fi

    _vanilla, mod = _env(tmp_path, monkeypatch)
    assert shop.main() == 0
    got = fi.read_package(mod, shop.PKG)
    assert got == (tmp_path / "out" / "img_data" / f"new_{shop.PKG:04d}").read_bytes()
    assert got != vanilla_pkg()
    before = mod.read_bytes()
    assert shop.main() == 0  # starts from vanilla again, so re-runs are no-ops
    assert mod.read_bytes() == before


def test_main_errors(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)

    def fail(*_a):
        raise shop.PackError("grew")

    monkeypatch.setattr(shop, "splice_packages_into_img", fail)
    with pytest.raises(SystemExit, match="splice failed: grew"):
        shop.main()

    _env(tmp_path / "nopkg", monkeypatch, packages={shop.PKG + 1: vanilla_pkg()})
    with pytest.raises(SystemExit, match="pkg 5789 missing"):
        shop.main()

    monkeypatch.setattr(shop, "MOD_IMG", tmp_path / "none.bin")
    with pytest.raises(SystemExit, match="missing"):
        shop.main()


def test_bake_runs_shop_titles_before_cesa():
    scripts = rebuild.DEPLOY_SCRIPTS
    assert "deploy_shop_titles_en.py" in scripts
    assert scripts.index("deploy_shop_titles_en.py") < scripts.index("deploy_cesa_en.py")


@pytest.mark.local_data
def test_vanilla_package_takes_every_master(tmp_path):
    from img import Image as ImgBin

    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    img = ImgBin(str(vanilla))
    try:
        img.parse(False)
        raw = img.entries[shop.PKG].fw.read()
    finally:
        img.fh.close()
    new = shop.patch_package(raw, _write(tmp_path, raw))
    assert len(new) == len(raw)
    assert shop.tex_entries(new, _write(tmp_path, new)) == shop.tex_entries(raw, _write(tmp_path, raw))
