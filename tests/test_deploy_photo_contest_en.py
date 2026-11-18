"""Photo Contest screens: raw RGBA4 / RGB8 TEX textures in pkgs 4090 / 4091."""

from __future__ import annotations

import random
import struct
import zlib
from types import SimpleNamespace

import pytest
from conftest import TOOLS, load_module
from PIL import Image

pc = load_module("deploy_photo_contest_en", TOOLS / "deploy_photo_contest_en.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")

W = H = 8


def texi(w: int = W, h: int = H, fmt: int = 11) -> bytes:
    meta = bytearray(82)
    struct.pack_into("<H", meta, 50, w)
    struct.pack_into("<H", meta, 54, h)
    meta[62] = fmt
    return bytes(meta)


def noise(n: int, seed: int) -> bytes:
    return random.Random(seed).randbytes(n)


def package(textures: list[tuple[str, bytes]], *, fmt: int = 11, extra=()) -> bytes:
    """Every TEXI, then every TEX (names repeat, as in the game), then ``extra``."""
    import fake_img as fi

    metas = [(f"{name}.texi", texi(fmt=fmt), b"TEXI", False) for name, _data in textures]
    texs = [(f"{name}.texi", data, b"TEX ", True) for name, data in textures]
    return fi.package([*metas, *texs, *extra])


def _write(tmp_path, raw: bytes, name: str = "pkg"):
    path = tmp_path / name
    path.write_bytes(raw)
    return path


def _masters(tmp_path, images: dict[str, Image.Image]):
    root = tmp_path / "masters"
    root.mkdir(exist_ok=True)
    for name, im in images.items():
        im.save(root / f"{name}.png")
    return root


def _noisy(seed: int) -> Image.Image:
    return Image.frombytes("RGB", (W, H), noise(W * H * 3, seed))


def _flat() -> Image.Image:
    return Image.new("RGB", (W, H), (200, 100, 50))


_TMP = {}


@pytest.fixture(autouse=True)
def _tmpdir(tmp_path):
    _TMP["dir"] = tmp_path


def _path_for(raw: bytes):
    path = _TMP["dir"] / f"p{zlib.crc32(raw):08x}"
    path.write_bytes(raw)
    return path


def _tex(raw: bytes, name: str) -> bytes:
    *_meta, cmp_len, cmp_off = pc.tex_slots(raw, _path_for(raw))[name]
    return zlib.decompress(raw[cmp_off : cmp_off + cmp_len])


def test_encode_rgba4_keeps_transparent_colour_and_matches_bclimutil_when_opaque():
    from bclimutil import encode_rgba4444_pixels

    opaque = Image.frombytes("RGBA", (W, H), bytes(range(256)))
    assert pc.encode_rgba4(opaque, W, H) == encode_rgba4444_pixels(opaque, W, H)
    clear = Image.new("RGBA", (W, H), (255, 0, 0, 0))
    assert pc.encode_rgba4(clear, W, H) == struct.pack("<H", 0xF000) * (W * H)


def test_tex_slots_reads_texi_meta_by_position(tmp_path):
    raw = package([("A", noise(W * H * 3, 1))], extra=[("orphan.texi", b"x", b"TEX ", True)])
    slots = pc.tex_slots(raw, _write(tmp_path, raw))
    assert list(slots) == ["A"]
    assert slots["A"][:5] == (W, H, 11, W * H * 3, 1)


def test_each_texture_goes_in_its_own_slot_when_all_fit(tmp_path, monkeypatch):
    monkeypatch.setitem(pc.JOBS, 1, ["A", "B"])
    raw = package([("A", noise(W * H * 3, 1)), ("B", noise(W * H * 3, 2))])
    masters = _masters(tmp_path, {"A": _flat(), "B": _noisy(3)})
    new = pc.patch_package(1, raw, _write(tmp_path, raw), masters)
    assert len(new) == len(raw)
    assert pc.tex_slots(new, _path_for(new)) == pc.tex_slots(raw, _path_for(raw))  # same slots
    assert _tex(new, "A") == pc.encode_rgb8_pixels(_flat(), W, H)
    assert _tex(new, "B") == pc.encode_rgb8_pixels(_noisy(3), W, H)


def test_group_is_relaid_when_one_texture_outgrows_its_slot(tmp_path, monkeypatch):
    monkeypatch.setitem(pc.JOBS, 1, ["A", "B"])
    # A had a big (noisy) slot, B a tiny (flat) one; the masters swap that round.
    raw = package([("A", noise(W * H * 3, 1)), ("B", bytes(W * H * 3))], extra=[("tail.bin", b"keep", b"BIN ", True)])
    masters = _masters(tmp_path, {"A": _flat(), "B": _noisy(3)})
    new = pc.patch_package(1, raw, _write(tmp_path, raw), masters)
    assert len(new) == len(raw)
    assert _tex(new, "A") == pc.encode_rgb8_pixels(_flat(), W, H)
    assert _tex(new, "B") == pc.encode_rgb8_pixels(_noisy(3), W, H)
    import fake_img as fi

    assert fi.read_element(new, "tail.bin", tmp_path) == b"keep"
    a, b = pc.tex_slots(new, _path_for(new))["A"], pc.tex_slots(new, _path_for(new))["B"]
    assert a[6] % 16 == 0 and b[6] % 16 == 0 and b[6] >= a[6] + a[5]


def test_relayout_falls_back_to_zopfli(tmp_path, monkeypatch):
    monkeypatch.setitem(pc.JOBS, 1, ["A", "B"])
    raw = package([("A", noise(W * H * 3, 1)), ("B", bytes(W * H * 3))])
    masters = _masters(tmp_path, {"A": _flat(), "B": _noisy(3)})
    fat = SimpleNamespace(compress=lambda data, level: zlib.compress(data, level) + bytes(4096), decompress=zlib.decompress)
    monkeypatch.setattr(pc, "zlib", fat)
    new = pc.patch_package(1, raw, _write(tmp_path, raw), masters)
    assert _tex(new, "B") == pc.encode_rgb8_pixels(_noisy(3), W, H)


def test_relayout_errors(tmp_path, monkeypatch):
    monkeypatch.setitem(pc.JOBS, 1, ["A", "B"])
    masters = _masters(tmp_path, {"A": _noisy(4), "B": _noisy(3)})
    # Both grow: the group does not fit either.
    raw = package([("A", bytes(W * H * 3)), ("B", bytes(W * H * 3))])
    with pytest.raises(SystemExit, match="do not fit their"):
        pc.patch_package(1, raw, _write(tmp_path, raw), masters)
    # Another element's data sits between the two streams.
    import fake_img as fi

    raw = fi.package([
        ("A.texi", texi(), b"TEXI", False), ("B.texi", texi(), b"TEXI", False),
        ("A.texi", bytes(W * H * 3), b"TEX ", True),
        ("C.bin", b"other", b"BIN ", True),
        ("B.texi", bytes(W * H * 3), b"TEX ", True),
    ])
    with pytest.raises(SystemExit, match="other data inside"):
        pc.patch_package(1, raw, _write(tmp_path, raw), masters)


def test_encode_jobs_errors(tmp_path, monkeypatch):
    monkeypatch.setitem(pc.JOBS, 1, ["A"])
    masters = _masters(tmp_path, {"A": _flat()})

    def fails(raw, match, m=masters):
        with pytest.raises(SystemExit, match=match):
            pc.patch_package(1, raw, _write(tmp_path, raw), m)

    fails(package([("Z", noise(W * H * 3, 1))]), "pkg 1: A missing")
    fails(package([("A", noise(W * H * 3, 1))], fmt=13), "unexpected TEX")
    fails(package([("A", noise(10, 1))]), "dec_len=10")
    import fake_img as fi

    raw = fi.package([("A.texi", texi(), b"TEXI", False), ("A.texi", noise(W * H * 3, 1), b"TEX ", False)])
    fails(raw, "cmp=0")
    raw = bytearray(package([("A", noise(W * H * 3, 1)), ("B", noise(W * H * 3, 2))]))
    # Entries: TEXI A, TEXI B, TEX A, TEX B (table rows 1-4). B's TEX points at A's stream.
    struct.pack_into("<2I", raw, 0x20 * 4 + 24, *struct.unpack_from("<2I", raw, 0x20 * 3 + 24))
    fails(bytes(raw), "shared with another texture")
    (tmp_path / "s").mkdir()
    small = _masters(tmp_path / "s", {"A": Image.new("RGB", (4, 4))})
    fails(package([("A", noise(W * H * 3, 1))]), r"A.png is \(4, 4\)", small)


def _env(tmp_path, monkeypatch, packages):
    import fake_img as fi

    tmp_path.mkdir(parents=True, exist_ok=True)
    fi.use_paths(monkeypatch, tmp_path, pc)
    monkeypatch.setattr(pc, "JOBS", {7: ["A"]})
    monkeypatch.setattr(pc, "MASTERS", _masters(tmp_path, {"A": _noisy(9)}))
    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(fi.img(packages, count=9))
    mod = tmp_path / "release" / "bake_img.bin"
    mod.parent.mkdir(parents=True, exist_ok=True)
    mod.write_bytes(vanilla.read_bytes())
    monkeypatch.setattr(pc, "MOD_IMG", mod)
    monkeypatch.setattr(pc, "OUT", tmp_path / "out")
    monkeypatch.setattr(pc, "_vanilla_src", lambda: vanilla)
    monkeypatch.setattr(pc, "_deploy_targets", lambda: [mod])
    return mod


def test_main_splices_the_packages(tmp_path, monkeypatch):
    import fake_img as fi

    mod = _env(tmp_path, monkeypatch, {7: package([("A", noise(W * H * 3, 1))])})
    assert pc.main() == 0
    got = fi.read_package(mod, 7)
    assert _tex(got, "A") == pc.encode_rgb8_pixels(_noisy(9), W, H)
    before = mod.read_bytes()
    assert pc.main() == 0  # starts from vanilla again
    assert mod.read_bytes() == before


def test_main_errors(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, {7: package([("A", noise(W * H * 3, 1))])})

    def boom(*_a):
        raise pc.PackError("grew")

    monkeypatch.setattr(pc, "splice_packages_into_img", boom)
    with pytest.raises(SystemExit, match="splice failed: grew"):
        pc.main()
    _env(tmp_path / "x", monkeypatch, {8: package([("A", noise(W * H * 3, 1))])})
    with pytest.raises(SystemExit, match="pkg 7 missing"):
        pc.main()
    monkeypatch.setattr(pc, "MOD_IMG", tmp_path / "none.bin")
    with pytest.raises(SystemExit, match="missing"):
        pc.main()


def test_masters_match_the_shipped_jobs():
    sizes = {4090: (128, 32), 4091: (256, 256)}
    for pkg, names in pc.JOBS.items():
        for name in names:
            assert Image.open(pc.MASTERS / f"{name}.png").size == sizes[pkg], name


def test_bake_runs_photo_contest_before_cesa():
    scripts = rebuild.DEPLOY_SCRIPTS
    assert "deploy_photo_contest_en.py" in scripts
    assert scripts.index("deploy_photo_contest_en.py") < scripts.index("deploy_cesa_en.py")


@pytest.mark.local_data
def test_vanilla_packages_take_every_master(tmp_path):
    from img import Image as ImgBin

    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    img = ImgBin(str(vanilla))
    try:
        img.parse(False)
        raws = {pkg: img.entries[pkg].fw.read() for pkg in pc.JOBS}
    finally:
        img.fh.close()
    for pkg, raw in raws.items():
        path = _write(tmp_path, raw, f"v{pkg}")
        new = pc.patch_package(pkg, raw, path)
        assert len(new) == len(raw)
        data = pc.encode_jobs(pkg, pc.tex_slots(raw, path), pc.MASTERS)
        for name, payload in data.items():
            assert _tex(new, name) == payload
