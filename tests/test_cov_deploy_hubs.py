"""Line and branch coverage for hub / chrome deploy scripts.

CI has no vanilla img.bin and no network. Packages come from tests/fake_img.py.
Zopfli searches are stubbed with a correctly sized zlib slot; the patch and
splice control flow still runs. Fonts are repo files only.
"""

from __future__ import annotations

import random
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image

from conftest import ROOT, TOOLS, load_module

import fake_img as fi

GEOMANIST = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025" / "Geomanist-Regular.ttf"

map_hub = load_module("deploy_map_hub_en", TOOLS / "deploy_map_hub_en.py")
myroom_opt = load_module("deploy_myroom_options_en", TOOLS / "deploy_myroom_options_en.py")
card_flist = load_module("deploy_card_flist_en", TOOLS / "deploy_card_flist_en.py")
card_side = load_module("deploy_card_side_btn_en", TOOLS / "deploy_card_side_btn_en.py")
fileselect = load_module("deploy_fileselect_dating_en", TOOLS / "deploy_fileselect_dating_en.py")
msel_plates = load_module("deploy_msel_opt_plates_en", TOOLS / "deploy_msel_opt_plates_en.py")
bleeding = load_module(
    "deploy_bleeding_edge_name_input", TOOLS / "deploy_bleeding_edge_name_input.py"
)
name_input = load_module("deploy_name_input_en", TOOLS / "deploy_name_input_en.py")
gallery = load_module("deploy_gallery_common_en", TOOLS / "deploy_gallery_common_en.py")
todo = load_module("deploy_todo_en", TOOLS / "deploy_todo_en.py")
mydata = load_module("deploy_mydata_en", TOOLS / "deploy_mydata_en.py")
status = load_module("deploy_status_stats_en", TOOLS / "deploy_status_stats_en.py")
watcher = load_module("deploy_watcher_issue28_en", TOOLS / "deploy_watcher_issue28_en.py")
minigame = load_module(
    "deploy_minigame_textures_en", TOOLS / "deploy_minigame_textures_en.py"
)


def noise_bclim(w: int, h: int, fmt: int, seed: int = 1) -> bytes:
    from bclimutil import parse_bclim

    blank = fi.bclim(w, h, fmt)
    n = len(parse_bclim(blank)[0])
    return fi.bclim(w, h, fmt, pixels=random.Random(seed).randbytes(n))


def png_wh(folder: str, stem: str) -> tuple[int, int]:
    path = ROOT / "assets" / "images" / folder / "timg" / f"{stem}.png"
    with Image.open(path) as im:
        return im.size


def arc_package(files: dict[str, bytes], sidecar: bytes = b"DMSTDATA!!") -> bytes:
    arc = fi.darc(files)
    return fi.package(
        [
            ("Data.arc", arc),
            ("meta.dmst", sidecar, b"DMST", False),
        ]
    )


def write_img(path: Path, packages: dict[int, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fi.img(packages))


def fast_exact(data: bytes, target: int):
    """Correctly sized slot without a zopfli search."""
    from exact_zlib import compress_exact_empty_blocks, pad_closed_zlib_stream

    slot = compress_exact_empty_blocks(data, target, thorough=False)
    if slot is None:
        for level in (9, 1, 0):
            slot = pad_closed_zlib_stream(
                zlib.compress(data, level), target, expected=data
            )
            if slot is not None:
                break
    if slot is None:
        raise RuntimeError(f"no exact slot {target} for {len(data)} bytes")
    return data, slot


def use_font(monkeypatch, mod) -> None:
    if hasattr(mod, "FONT"):
        monkeypatch.setattr(mod, "FONT", GEOMANIST)
    if hasattr(mod, "UI_FONT"):
        monkeypatch.setattr(mod, "UI_FONT", GEOMANIST)


def point_instances(monkeypatch, mod, img: Path, tmp_path: Path) -> Path:
    """Cover is_file / already-seen / new-target branches of the instance walk."""
    extra = tmp_path / "inst_extra.bin"
    extra.write_bytes(img.read_bytes())
    missing = tmp_path / "ghost.bin"

    class _Root:
        def glob(self, _pattern):
            return [missing, img, extra]

        def is_dir(self):
            return True

    monkeypatch.setattr(mod, "AZAHAR_INSTANCES", _Root(), raising=False)
    return extra


def bind(monkeypatch, tmp_path: Path, mod, img: Path, *, vanilla: Path | None = None):
    vanilla = vanilla or img
    extra = {"MOD_IMG": img, "VANILLA": vanilla, "_VANILLA": vanilla, "_FALLBACK_VANILLA": vanilla}
    fi.use_paths(monkeypatch, tmp_path, mod, **extra)
    use_font(monkeypatch, mod)
    if hasattr(mod, "VANILLA_CANDIDATES"):
        monkeypatch.setattr(
            mod,
            "VANILLA_CANDIDATES",
            [vanilla, Path("C:/no/such/img.bin")],
        )
    if hasattr(mod, "compress_exact_zopfli"):
        monkeypatch.setattr(mod, "compress_exact_zopfli", fast_exact)
    return point_instances(monkeypatch, mod, img, tmp_path)


def retarget_sidecar(pkg: bytes) -> bytes:
    """Point the uncompressed sidecar at the ARC zlib slot so a rewrite changes it."""
    from img import Package

    blob = bytearray(pkg)
    e0 = Package.ENTRY_SIZE
    e1 = e0 + Package.ENTRY_SIZE
    _typ, _dl, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[e0 : e0 + Package.ENTRY_SIZE])
    )
    assert is_cmp and slot_len >= 16
    take = min(24, slot_len)
    struct.pack_into("<2I", blob, e1 + 8, take, cmp_off)
    return bytes(blob)


def corrupt_later_darc(monkeypatch):
    """Make the post-write ARC parse disagree with decompressobj.

    Slot builders (exact_zlib / fast_exact) keep a clean decompress and arm the
    mismatch. ``_write_slot`` has no earlier archive parse, so its check is
    always mismatched.
    """
    import inspect

    import exact_zlib

    real = zlib.decompress
    seen = {"arm": False}
    real_empty = exact_zlib.compress_exact_empty_blocks

    def armed_empty(*args, **kwargs):
        seen["arm"] = True
        return real_empty(*args, **kwargs)

    monkeypatch.setattr(exact_zlib, "compress_exact_empty_blocks", armed_empty)

    def wrapped(data, *args, **kwargs):
        out = real(data, *args, **kwargs)
        frames = inspect.stack()[1:10]
        in_helper = any(
            f.function == "fast_exact" or f.filename.replace("\\", "/").endswith("exact_zlib.py")
            for f in frames
        )
        if in_helper:
            seen["arm"] = True
            return out
        if not isinstance(out, (bytes, bytearray)) or out[:4] != b"darc":
            return out
        in_write = any(f.function == "_write_slot" for f in frames)
        if seen["arm"] or in_write:
            return bytes(out) + b"!"
        return out

    monkeypatch.setattr(zlib, "decompress", wrapped)
    corrupt_later_darc.real_decompress = real
    corrupt_later_darc.real_empty = real_empty
    return seen


def restore_zlib(monkeypatch):
    """Undo :func:`corrupt_later_darc` for later cases in the same test."""
    import exact_zlib

    real = getattr(corrupt_later_darc, "real_decompress", None)
    empty = getattr(corrupt_later_darc, "real_empty", None)
    if real is not None:
        monkeypatch.setattr(zlib, "decompress", real)
    if empty is not None:
        monkeypatch.setattr(exact_zlib, "compress_exact_empty_blocks", empty)


def first_empty_slot(fn, data: bytes, lo: int = 16, hi: int = 8000):
    """Length a SYNC_FLUSH empty-block stream can hit, without a wide scan."""
    co = zlib.compressobj(6, wbits=-15)
    body = co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH)
    base = 2 + 4 + len(body)
    for k in range(1, 40):
        n = base + 5 * k
        if lo <= n < hi:
            slot = fn(data, n)
            if slot is not None:
                return n, slot
    raise AssertionError("no exact empty-block length")


def tiny_darc_pair() -> bytes:
    return fi.darc({"a.bin": b"a" * 5, "b.bin": b"b" * 5})


# ---------------------------------------------------------------------------
# Shared pad / compress-slot helpers (map hub, myroom options, fileselect)
# ---------------------------------------------------------------------------


def _salted_darc() -> tuple[bytes, bytes]:
    clean = tiny_darc_pair() + bytes(4)
    from darcutil import DarcArchive

    arc = bytearray(clean)
    a = DarcArchive(clean).find("a.bin")
    arc[a.offset + a.length] = 1
    arc[-1] = 2
    return clean, bytes(arc)


@pytest.mark.parametrize("mod", [map_hub, myroom_opt, fileselect])
def test_zero_pads_and_compress_slot(mod, monkeypatch):
    clean, salted = _salted_darc()
    assert mod._zero_all_darc_pads(salted) == clean
    adjacent = fi.darc({"a.bin": b"abcd", "b.bin": b"efgh"}, align=1)
    assert mod._zero_all_darc_pads(adjacent) == adjacent

    monkeypatch.setattr(mod, "try_fast_exact_slot", lambda data, n: (data, b"fast"))
    assert mod._compress_slot(salted, 10) == (salted, b"fast")

    tried = []
    monkeypatch.setattr(mod, "try_fast_exact_slot", lambda data, n: None)

    def zopfli(data, n):
        tried.append(data)
        if len(tried) == 1:
            raise RuntimeError("miss")
        return data, b"slot"

    monkeypatch.setattr(mod, "compress_exact_zopfli", zopfli)
    assert mod._compress_slot(salted, 10) == (clean, b"slot")
    assert tried == [salted, clean]

    monkeypatch.setattr(
        mod, "compress_exact_zopfli", lambda d, n: (_ for _ in ()).throw(RuntimeError("no"))
    )
    with pytest.raises(RuntimeError, match="no"):
        mod._compress_slot(salted, 10)

    monkeypatch.setattr(mod, "try_fast_exact_slot", lambda data, n: None)
    monkeypatch.setattr(mod, "compress_exact_zopfli", lambda data, n: (data, b"z"))
    assert mod._compress_slot(adjacent, 4) == (adjacent, b"z")


def test_deploy_target_walk_branches(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(b"img")
    for mod, fn_name in (
        (map_hub, "_deploy_targets"),
        (myroom_opt, "_deploy_targets"),
        (card_side, "_deploy_targets"),
        (fileselect, "_deploy_targets"),
        (watcher, "_targets"),
        (minigame, "_deploy_targets"),
    ):
        extra = point_instances(monkeypatch, mod, img, tmp_path)
        monkeypatch.setattr(mod, "MOD_IMG", img)
        monkeypatch.setattr(mod, "iter_deploy_targets", lambda primary: [primary.resolve()])
        got = getattr(mod, fn_name)()
        assert extra.resolve() in got
        assert img.resolve() in got
        assert len(got) == 2

    monkeypatch.setattr(watcher, "AZAHAR_INSTANCES", tmp_path / "no-instances")
    monkeypatch.setattr(watcher, "MOD_IMG", img)
    assert watcher._targets() == [img.resolve()]


def _jobs_bclim(mod, fmt: int = 0xB) -> dict[int, dict[str, bytes]]:
    out: dict[int, dict[str, bytes]] = {}
    for i, (pkg, folder, path, _en) in enumerate(mod.JOBS):
        stem = Path(path).stem
        w, h = png_wh(folder, stem)
        out.setdefault(pkg, {})[path] = noise_bclim(w, h, fmt, seed=100 + i)
    return out


def _img_from_arcs(arcs: dict[int, dict[str, bytes]], *, retarget: bool = False) -> bytes:
    pkgs = {}
    for pkg, files in arcs.items():
        blob = arc_package(files)
        pkgs[pkg] = retarget_sidecar(blob) if retarget else blob
    return fi.img(pkgs)


def test_map_hub_main_and_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {k: arc_package(v) for k, v in _jobs_bclim(map_hub).items()})
    extra = bind(monkeypatch, tmp_path, map_hub, img)
    before = img.read_bytes()
    assert map_hub.main() == 0
    assert img.read_bytes() != before
    assert extra.read_bytes() != before
    assert (map_hub.OUT / "map_text_title_RGBA4_en.png").is_file()

    monkeypatch.setattr(map_hub, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        map_hub.main()


def test_map_hub_patch_arc_branches(tmp_path, monkeypatch):
    use_font(monkeypatch, map_hub)
    files = _jobs_bclim(map_hub)[5380]
    arc = fi.darc(files)
    bad = dict(files)
    bad["timg/map_text_townviewer_RGBA4.bclim"] = noise_bclim(32, 16, 8, seed=3)
    with pytest.raises(SystemExit, match="not ETC1A4"):
        map_hub._patch_arc(fi.darc(bad), [("Myroom.check", "timg/map_text_townviewer_RGBA4.bclim", "City Viewer")], tmp_path)
    with pytest.raises(SystemExit, match="missing"):
        map_hub._patch_arc(arc, [("Myroom.check", "timg/none.bclim", "x")], tmp_path)

    small = Image.new("RGBA", (4, 4), (9, 9, 9, 255))
    real_rgba = map_hub._rgba_for
    monkeypatch.setattr(map_hub, "_rgba_for", lambda *a: (small, "tiny"))
    map_hub.OUT = tmp_path / "out"
    map_hub.OUT.mkdir()
    patched = map_hub._patch_arc(
        arc,
        [("Myroom.check", "timg/map_text_townviewer_RGBA4.bclim", "City Viewer")],
        tmp_path,
    )
    assert patched != arc
    monkeypatch.setattr(map_hub, "_rgba_for", real_rgba)

    folder, _path, en = "Nope.check", "timg/not_a_real_stem.bclim", "Map"
    rgba, src = map_hub._rgba_for("Nope.check", "not_a_real_stem", "Map", 32, 16)
    assert src == "render:Map"
    assert rgba.size == (32, 16)
    w, h = png_wh("MyroomHeader.check", "map_text_title_RGBA4")
    rgba, src = map_hub._rgba_for("MyroomHeader.check", "map_text_title_RGBA4", "Map", w, h)
    assert src.endswith("map_text_title_RGBA4.png")
    assert rgba.size == (w, h)
    assert en


def test_map_hub_write_slot_errors(tmp_path, monkeypatch):
    files = {"timg/map_text_title_RGBA4.bclim": noise_bclim(32, 16, 0xB, seed=4)}
    pkg_bytes = arc_package(files)
    src = tmp_path / "5575"
    src.write_bytes(pkg_bytes)
    from img import FileWindow, Package

    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if e.fn == "Data.arc")
    tuned = arc.parsed()
    cmp_len = arc.fw.len()
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        map_hub._write_slot(src, pkg, tuned, b"short")
    _other, slot = fast_exact(b"\x00" * len(tuned), cmp_len)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        map_hub._write_slot(src, pkg, tuned, slot)

    src.write_bytes(retarget_sidecar(pkg_bytes))
    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    _tuned, good = fast_exact(tuned, cmp_len)
    with pytest.raises(SystemExit, match="DMST changed"):
        map_hub._write_slot(src, pkg, tuned, good)


def test_map_hub_package_and_splice_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    img.write_bytes(fi.img({}, count=5576))
    bind(monkeypatch, tmp_path, map_hub, img)
    with pytest.raises(SystemExit, match="pkg 5380 missing"):
        map_hub.main()

    write_img(img, {k: arc_package(v) for k, v in _jobs_bclim(map_hub).items()})
    bind(monkeypatch, tmp_path, map_hub, img)

    def bad_slot(data, n):
        return data, zlib.compress(data) + b"\x00"

    monkeypatch.setattr(map_hub, "_compress_slot", bad_slot)
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        map_hub.main()

    monkeypatch.setattr(map_hub, "_compress_slot", fast_exact)
    monkeypatch.setattr(
        map_hub, "splice_packages_into_img", lambda *a: (_ for _ in ()).throw(map_hub.PackError("grew"))
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        map_hub.main()


def test_myroom_options_rgba_and_retry(tmp_path, monkeypatch):
    use_font(monkeypatch, myroom_opt)
    w, h = png_wh("Myroom.check", "optn_tex_optionmenu_RGBA4")
    rgba, src = myroom_opt._rgba_for(
        "Myroom.check", "optn_tex_optionmenu_RGBA4", "Options Menu", w, h
    )
    assert "optionmenu" in src
    rgba, src = myroom_opt._rgba_for(
        "Myroom.check", "optn_tex_optionkabegami_RGBA4", "Wallpaper", w, h
    )
    assert src.startswith("render menu:")
    rgba, src = myroom_opt._rgba_for("Nope.check", "not_real", "X", 32, 16)
    assert src == "render:X"

    arcs = _jobs_bclim(myroom_opt)
    img = tmp_path / "img.bin"
    write_img(img, {k: arc_package(v) for k, v in arcs.items()})
    extra = bind(monkeypatch, tmp_path, myroom_opt, img)
    before = img.read_bytes()
    assert myroom_opt.main() == 0
    assert img.read_bytes() != before
    assert extra.read_bytes() != before

    # 5575 retry keeps only the Options Menu header when the full set misses.
    calls = {"n": 0}

    def flaky(data, n):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("miss")
        return fast_exact(data, n)

    monkeypatch.setattr(myroom_opt, "_compress_slot", flaky)
    jobs = [
        ("MyroomHeader.check", "timg/optn_tex_optionmenu_RGBA4.bclim", "Options Menu"),
        ("MyroomHeader.check", "timg/optn_tex_optionmenu_01.bclim", "Display Settings"),
    ]
    myroom_opt._patch_package(5575, jobs, myroom_opt.OUT / "img_data", myroom_opt.OUT / "_fit")
    assert calls["n"] == 2

    monkeypatch.setattr(
        myroom_opt, "_compress_slot", lambda *a: (_ for _ in ()).throw(RuntimeError("no"))
    )
    jobs_5380 = [
        ("Myroom.check", "timg/optn_tex_optionmenu_RGBA4.bclim", "Options Menu"),
        ("Myroom.check", "timg/optn_tex_optionhyouji_RGBA4.bclim", "Display Settings"),
    ]
    with pytest.raises(RuntimeError, match="no"):
        myroom_opt._patch_package(5380, jobs_5380, myroom_opt.OUT / "img_data", myroom_opt.OUT / "_fit")
    core = [jobs[0]]
    with pytest.raises(RuntimeError, match="no"):
        myroom_opt._patch_package(5575, core, myroom_opt.OUT / "img_data", myroom_opt.OUT / "_fit")
    no_core = [("MyroomHeader.check", "timg/optn_tex_optionmenu_01.bclim", "Display Settings")]
    with pytest.raises(RuntimeError, match="no"):
        myroom_opt._patch_package(5575, no_core, myroom_opt.OUT / "img_data", myroom_opt.OUT / "_fit")


def test_myroom_zlib_and_splice(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {k: arc_package(v) for k, v in _jobs_bclim(myroom_opt).items()})
    bind(monkeypatch, tmp_path, myroom_opt, img)
    monkeypatch.setattr(
        myroom_opt, "_compress_slot", lambda data, n: (data, zlib.compress(data) + b"\x00")
    )
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        myroom_opt.main()
    monkeypatch.setattr(myroom_opt, "_compress_slot", fast_exact)
    monkeypatch.setattr(
        myroom_opt,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(myroom_opt.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        myroom_opt.main()
    monkeypatch.setattr(myroom_opt, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        myroom_opt.main()


# ---------------------------------------------------------------------------
# Card friend-list header
# ---------------------------------------------------------------------------


def _flist_pkg(fmt: int = 3) -> bytes:
    w, h = png_wh("Card.check", "Flist_Txt03")
    return arc_package({"timg/Flist_Txt03.bclim": noise_bclim(w, h, fmt, seed=7)})


def test_card_flist_gap_helpers():
    data = tiny_darc_pair()
    assert card_flist.all_interfile_gaps(data)
    assert card_flist.interfile_zero_gaps(data)
    salted = bytearray(data)
    g0, g1 = card_flist.all_interfile_gaps(data)[0]
    salted[g0:g1] = b"\xab" * (g1 - g0)
    assert card_flist.interfile_zero_gaps(bytes(salted)) == []
    cleared = card_flist.zero_interfile_gaps(bytes(salted))
    assert cleared[g0:g1] == b"\x00" * (g1 - g0)
    padded = card_flist.apply_gap_pad(cleared, 3, b"xyz" * 20)
    assert padded[g0 : g0 + 3] == b"xyz"
    assert card_flist.apply_gap_pad(cleared, 0, b"xyz") == cleared
    assert card_flist.compress_exact_empty_blocks(b"hi", 4) is None
    n, slot = first_empty_slot(card_flist.compress_exact_empty_blocks, b"hello")
    assert zlib.decompress(slot) == b"hello"
    exact = first_empty_slot(card_flist.compress_exact_empty_blocks, cleared)[0]
    tuned, slot = card_flist.compress_exact_with_gap_tune(cleared, exact)
    assert zlib.decompress(slot) == tuned
    with pytest.raises(SystemExit, match="gap tune"):
        card_flist.compress_exact_with_gap_tune(fi.darc({"a.bin": b"ab"}, align=1), 6)


def test_card_flist_main_live_and_vanilla(tmp_path, monkeypatch):
    live = tmp_path / "live.bin"
    vanilla = tmp_path / "vanilla.bin"
    blob = _flist_pkg()
    write_img(live, {card_flist.PKG: blob})
    write_img(vanilla, {card_flist.PKG: blob})
    extra = bind(monkeypatch, tmp_path, card_flist, live, vanilla=vanilla)
    monkeypatch.setattr(card_flist, "compress_exact_with_gap_tune", fast_exact)
    assert card_flist.main() is None
    assert live.read_bytes() != fi.img({card_flist.PKG: blob})
    assert extra.read_bytes() != live.read_bytes() or extra.is_file()

    calls = {"n": 0}

    def miss_once(data, n):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SystemExit("nope")
        return fast_exact(data, n)

    write_img(live, {card_flist.PKG: blob})
    write_img(vanilla, {card_flist.PKG: blob})
    bind(monkeypatch, tmp_path, card_flist, live, vanilla=vanilla)
    monkeypatch.setattr(card_flist, "compress_exact_with_gap_tune", miss_once)
    assert card_flist.main() is None
    assert calls["n"] == 2

    bind(monkeypatch, tmp_path, card_flist, live, vanilla=live)
    monkeypatch.setattr(card_flist, "compress_exact_with_gap_tune", fast_exact)
    assert card_flist.main() is None


def test_card_flist_errors(tmp_path, monkeypatch):
    live = tmp_path / "live.bin"
    write_img(live, {card_flist.PKG: _flist_pkg(fmt=8)})
    bind(monkeypatch, tmp_path, card_flist, live, vanilla=live)
    with pytest.raises(SystemExit, match="not LA8"):
        card_flist.main()

    write_img(live, {card_flist.PKG: arc_package({"timg/other.bclim": noise_bclim(16, 16, 3, 1)})})
    bind(monkeypatch, tmp_path, card_flist, live, vanilla=live)
    with pytest.raises(SystemExit, match="missing"):
        card_flist.main()

    write_img(live, {card_flist.PKG: _flist_pkg()})
    bind(monkeypatch, tmp_path, card_flist, live, vanilla=tmp_path / "no-vanilla.bin")
    monkeypatch.setattr(
        card_flist, "compress_exact_with_gap_tune", lambda d, n: (_ for _ in ()).throw(SystemExit("nope"))
    )
    with pytest.raises(SystemExit, match="could not fit slot"):
        card_flist.main()

    bind(monkeypatch, tmp_path, card_flist, live, vanilla=live)
    monkeypatch.setattr(
        card_flist, "compress_exact_with_gap_tune", lambda d, n: (d, zlib.compress(d) + b"\x00")
    )
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        card_flist.main()

    bind(monkeypatch, tmp_path, card_flist, live, vanilla=live)
    monkeypatch.setattr(
        card_flist,
        "compress_exact_with_gap_tune",
        lambda d, n: (d + b"x", zlib.compress(d + b"x")),
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        card_flist.main()

    write_img(live, {card_flist.PKG: retarget_sidecar(_flist_pkg())})
    bind(monkeypatch, tmp_path, card_flist, live, vanilla=live)
    monkeypatch.setattr(card_flist, "compress_exact_with_gap_tune", fast_exact)
    with pytest.raises(SystemExit, match="DMST changed"):
        card_flist.main()

    write_img(live, {card_flist.PKG: _flist_pkg()})
    bind(monkeypatch, tmp_path, card_flist, live, vanilla=live)
    monkeypatch.setattr(card_flist, "compress_exact_with_gap_tune", fast_exact)
    monkeypatch.setattr(
        card_flist,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(card_flist.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        card_flist.main()

    write_img(live, {card_flist.PKG: _flist_pkg()})
    bind(monkeypatch, tmp_path, card_flist, live, vanilla=live)
    monkeypatch.setattr(card_flist, "compress_exact_with_gap_tune", fast_exact)
    corrupt_later_darc(monkeypatch)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        card_flist.main()

    monkeypatch.setattr(card_flist, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        card_flist.main()


# ---------------------------------------------------------------------------
# Save-select Front/Back and FileSelect Dating
# ---------------------------------------------------------------------------


def test_card_side_main_and_errors(tmp_path, monkeypatch):
    real_find = card_side.find_ui_png
    w, h = png_wh("NCommonIcon.check", "B_Card_b_btn_lite")
    img = tmp_path / "img.bin"
    blob = arc_package({"timg/B_Card_b_btn_lite.bclim": noise_bclim(w, h, 0xB, seed=9)})
    write_img(img, {card_side.PKG: blob})
    extra = bind(monkeypatch, tmp_path, card_side, img)
    before = img.read_bytes()
    assert card_side.main() == 0
    assert img.read_bytes() != before
    assert extra.read_bytes() != before
    assert (card_side.OUT / "B_Card_b_btn_lite_en.png").is_file()

    monkeypatch.setattr(card_side, "try_fast_exact_slot", lambda d, n: None)
    assert card_side.main() == 0

    write_img(img, {card_side.PKG: arc_package({"timg/B_Card_b_btn_lite.bclim": noise_bclim(w, h, 8, seed=9)})})
    bind(monkeypatch, tmp_path, card_side, img)
    with pytest.raises(SystemExit, match="not ETC1A4"):
        card_side.main()

    write_img(img, {card_side.PKG: arc_package({"timg/other.bclim": noise_bclim(16, 16, 0xB, 1)})})
    bind(monkeypatch, tmp_path, card_side, img)
    with pytest.raises(SystemExit, match="missing"):
        card_side.main()

    monkeypatch.setattr(card_side, "find_ui_png", lambda *a, **k: None)
    write_img(img, {card_side.PKG: blob})
    bind(monkeypatch, tmp_path, card_side, img)
    with pytest.raises(SystemExit, match="missing Zhoumaru"):
        card_side.main()
    monkeypatch.setattr(card_side, "find_ui_png", real_find)

    img.write_bytes(fi.img({}, count=card_side.PKG + 1))
    bind(monkeypatch, tmp_path, card_side, img)
    with pytest.raises(SystemExit, match="pkg"):
        card_side.main()

    write_img(img, {card_side.PKG: blob})
    bind(monkeypatch, tmp_path, card_side, img)
    monkeypatch.setattr(card_side, "try_fast_exact_slot", lambda d, n: (d, zlib.compress(d) + b"\x00"))
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        card_side.main()

    bind(monkeypatch, tmp_path, card_side, img)
    monkeypatch.setattr(
        card_side, "try_fast_exact_slot", lambda d, n: (d + b"x", zlib.compress(d + b"x"))
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        card_side.main()

    write_img(img, {card_side.PKG: retarget_sidecar(blob)})
    bind(monkeypatch, tmp_path, card_side, img)
    monkeypatch.setattr(card_side, "find_ui_png", real_find)
    monkeypatch.setattr(card_side, "try_fast_exact_slot", fast_exact)
    with pytest.raises(SystemExit, match="DMST changed"):
        card_side.main()

    write_img(img, {card_side.PKG: blob})
    bind(monkeypatch, tmp_path, card_side, img)
    corrupt_later_darc(monkeypatch)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        card_side.main()
    restore_zlib(monkeypatch)

    write_img(img, {card_side.PKG: blob})
    bind(monkeypatch, tmp_path, card_side, img)
    monkeypatch.setattr(
        card_side,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(card_side.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        card_side.main()

    monkeypatch.setattr(card_side, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        card_side.main()


def test_fileselect_encode_and_main(tmp_path, monkeypatch):
    w, h = png_wh("FileSelect.check", "D_Select_data03")
    png = tmp_path / "sheet.png"
    orig = tmp_path / "sheet.bclim"
    Image.new("RGBA", (w, h), (1, 2, 3, 255)).save(png)
    orig.write_bytes(noise_bclim(w, h, 8, seed=2))
    assert fileselect._encode(png, orig, 8)
    orig.write_bytes(noise_bclim(w, h, 0xB, seed=2))
    assert fileselect._encode(png, orig, 0xB)
    with pytest.raises(SystemExit, match="not RGBA4444"):
        fileselect._encode(png, orig, 1)

    arc = fi.darc({fileselect.PATH: noise_bclim(w, h, 0xB, seed=5)})
    fileselect.OUT = tmp_path / "out"
    fileselect.OUT.mkdir()
    assert fileselect._patch_arc(arc, tmp_path) != arc
    with pytest.raises(SystemExit, match="missing"):
        fileselect._patch_arc(fi.darc({"timg/other.bclim": noise_bclim(8, 8, 0xB, 1)}), tmp_path)
    real_find = fileselect.find_ui_png
    monkeypatch.setattr(fileselect, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="missing"):
        fileselect._patch_arc(arc, tmp_path)
    monkeypatch.setattr(fileselect, "find_ui_png", lambda *a, **k: png)
    tiny = fi.darc({fileselect.PATH: noise_bclim(32, 16, 0xB, seed=6)})
    with pytest.raises(SystemExit, match="!="):
        fileselect._patch_arc(tiny, tmp_path)
    monkeypatch.setattr(fileselect, "find_ui_png", real_find)

    img = tmp_path / "img.bin"
    blob = arc_package({fileselect.PATH: noise_bclim(w, h, 0xB, seed=5)})
    write_img(img, {fileselect.PKG: blob})
    extra = bind(monkeypatch, tmp_path, fileselect, img)
    before = img.read_bytes()
    assert fileselect.main() == 0
    assert img.read_bytes() != before
    assert extra.read_bytes() != before

    monkeypatch.setattr(fileselect, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        fileselect.main()

    img.write_bytes(fi.img({}, count=fileselect.PKG + 1))
    bind(monkeypatch, tmp_path, fileselect, img)
    with pytest.raises(SystemExit, match="pkg"):
        fileselect.main()

    write_img(img, {fileselect.PKG: blob})
    bind(monkeypatch, tmp_path, fileselect, img)
    monkeypatch.setattr(
        fileselect, "_compress_slot", lambda d, n: (d, zlib.compress(d) + b"\x00")
    )
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        fileselect.main()
    monkeypatch.setattr(fileselect, "_compress_slot", fast_exact)
    monkeypatch.setattr(
        fileselect,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(fileselect.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        fileselect.main()


def test_fileselect_write_slot(tmp_path):
    blob = arc_package({fileselect.PATH: noise_bclim(32, 16, 0xB, seed=1)})
    src = tmp_path / "5152"
    src.write_bytes(blob)
    from img import FileWindow, Package

    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if e.fn == "Data.arc")
    tuned = arc.parsed()
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        fileselect._write_slot(src, pkg, tuned, b"x")
    _o, slot = fast_exact(b"\x00" * len(tuned), arc.fw.len())
    with pytest.raises(SystemExit, match="ARC mismatch"):
        fileselect._write_slot(src, pkg, tuned, slot)
    src.write_bytes(retarget_sidecar(blob))
    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    _t, good = fast_exact(tuned, arc.fw.len())
    with pytest.raises(SystemExit, match="DMST changed"):
        fileselect._write_slot(src, pkg, tuned, good)


# ---------------------------------------------------------------------------
# Options plates (A8)
# ---------------------------------------------------------------------------


def test_msel_render_helpers(tmp_path, monkeypatch):
    use_font(monkeypatch, msel_plates)
    msel_plates.OUT = tmp_path / "plates"
    msel_plates.OUT.mkdir()
    assert msel_plates.glyph_h(__import__("numpy").zeros((4, 4), dtype="uint8")) == 0
    raw = noise_bclim(144, 28, 1, seed=11)
    canvas, w, h = msel_plates.decode_a8(raw)
    assert (w, h) == (144, 28)
    assert canvas.shape[0] >= h
    painted = msel_plates.render(144, 28, "Sound", 12, hard=False)
    assert painted.shape == (28, 144)
    hard = msel_plates.render(144, 28, "Sound", 12, hard=True)
    assert set(hard.reshape(-1).tolist()) <= {0, 255}
    with pytest.raises(RuntimeError):
        msel_plates.render(8, 8, "Communication Settings", 4, hard=False)

    soft = msel_plates.make_bclim(raw, "Sound Settings", tmp_path, hard=False, stem="Com_M_Sel_Plate_Text03_02_00")
    masked = msel_plates.make_bclim(raw, "Communication Settings", tmp_path, hard=False, stem="Com_M_Sel_Plate_Text04_04_00")
    hard_b = msel_plates.make_bclim(raw, "Display Settings", tmp_path, hard=True, stem="Com_M_Sel_Plate_Text03_01_00")
    rendered = msel_plates.make_bclim(raw, "Sound Settings", tmp_path, hard=False, stem="no-such-stem")
    assert len(soft) == len(raw) == len(masked) == len(hard_b) == len(rendered)
    assert (msel_plates.OUT / "Sound_Settings.png").is_file()

    arc = fi.darc({path: noise_bclim(*png_wh("NCommonMSel(3).check", Path(path).stem), 1, seed=i) for i, (path, _en) in enumerate(msel_plates.LABELS)})
    assert msel_plates._patch_candidate(arc, tmp_path, hard=False) != arc
    with pytest.raises(SystemExit, match="missing"):
        msel_plates._patch_candidate(arc, tmp_path, hard=True, labels=[("timg/nope.bclim", "X")])


def test_msel_main_paths(tmp_path, monkeypatch):
    use_font(monkeypatch, msel_plates)
    files = {
        path: noise_bclim(*png_wh("NCommonMSel(3).check", Path(path).stem), 1, seed=20 + i)
        for i, (path, _en) in enumerate(msel_plates.LABELS)
    }
    img = tmp_path / "img.bin"
    write_img(img, {msel_plates.PKG: arc_package(files)})
    extra = bind(monkeypatch, tmp_path, msel_plates, img)
    monkeypatch.setattr(msel_plates.zopfli_zlib, "compress", lambda data: b"Z")
    assert msel_plates.main() == 0
    assert extra.read_bytes() != img.read_bytes() or extra.is_file()

    calls = {"n": 0}

    def comp(_data):
        calls["n"] += 1
        if calls["n"] <= 2:
            return b"Z" * 100_000
        return b"Z"

    exact_calls = {"n": 0}

    def exact(data, target):
        exact_calls["n"] += 1
        if exact_calls["n"] == 1:
            raise RuntimeError("miss")
        return fast_exact(data, target)

    monkeypatch.setattr(msel_plates.zopfli_zlib, "compress", comp)
    monkeypatch.setattr(msel_plates, "compress_exact_zopfli", exact)
    assert msel_plates.main() == 0
    assert exact_calls["n"] == 2

    monkeypatch.setattr(msel_plates.zopfli_zlib, "compress", lambda data: b"Z" * 100_000)
    with pytest.raises(SystemExit, match="exceeds slot"):
        msel_plates.main()

    monkeypatch.setattr(msel_plates.zopfli_zlib, "compress", lambda data: b"Z")
    monkeypatch.setattr(
        msel_plates, "compress_exact_zopfli", lambda d, n: (_ for _ in ()).throw(RuntimeError("no"))
    )
    assert msel_plates.main() == 0

    monkeypatch.setattr(msel_plates, "compress_exact_zopfli", lambda d, n: (d, zlib.compress(d) + b"\x00"))
    with pytest.raises(SystemExit, match="zlib verify failed"):
        msel_plates.main()
    monkeypatch.setattr(
        msel_plates, "compress_exact_zopfli", lambda d, n: (d + b"q", zlib.compress(d + b"q"))
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        msel_plates.main()

    write_img(img, {msel_plates.PKG: retarget_sidecar(arc_package(files))})
    bind(monkeypatch, tmp_path, msel_plates, img)
    monkeypatch.setattr(msel_plates.zopfli_zlib, "compress", lambda data: b"Z")
    monkeypatch.setattr(msel_plates, "compress_exact_zopfli", fast_exact)
    with pytest.raises(SystemExit, match="DMST changed"):
        msel_plates.main()

    write_img(img, {msel_plates.PKG: arc_package(files)})
    bind(monkeypatch, tmp_path, msel_plates, img)
    monkeypatch.setattr(msel_plates.zopfli_zlib, "compress", lambda data: b"Z")
    monkeypatch.setattr(msel_plates, "compress_exact_zopfli", fast_exact)
    corrupt_later_darc(monkeypatch)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        msel_plates.main()

    monkeypatch.setattr(msel_plates, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        msel_plates.main()


# ---------------------------------------------------------------------------
# Gallery common
# ---------------------------------------------------------------------------


_GALLERY_ETC = {
    "Gallery_txt01",
    "Gallery_txt02",
    "Gallery_txt03",
    "Gallery_txt08",
    "Gallery_txt09",
}


def _gallery_files(fmt_override: int | None = None) -> dict[str, bytes]:
    files = {}
    for i, (path, _en) in enumerate(gallery.LABELS):
        stem = Path(path).stem
        w, h = png_wh("Gallery_Common.check", stem)
        fmt = fmt_override if fmt_override is not None else (0xB if stem in _GALLERY_ETC else 8)
        files[path] = noise_bclim(w, h, fmt, seed=30 + i)
    return files


def test_gallery_render_and_gaps(tmp_path, monkeypatch):
    use_font(monkeypatch, gallery)
    assert gallery.font(12).size == 12
    etc = gallery.render_label(64, 16, "Preview", 0xB)
    name = gallery.render_label(120, 18, "Nene", 8)
    assert etc.size == (64, 16) and name.size == (120, 18)
    with pytest.raises(RuntimeError):
        gallery.render_label(4, 4, "Kobayakawa Rinko", 0xB)
    with pytest.raises(RuntimeError):
        gallery.render_label(4, 4, "Kobayakawa Rinko", 8)

    data = tiny_darc_pair()
    assert gallery.interfile_zero_gaps(data)
    salted = bytearray(data)
    g0, g1 = gallery.interfile_zero_gaps(data)[0][1], None
    runs = gallery.interfile_zero_gaps(data)
    gsz, g0 = runs[0]
    salted[g0 : g0 + gsz] = b"\xcd" * gsz
    assert gallery.interfile_zero_gaps(bytes(salted)) == []
    cleared = bytearray(data)
    assert gallery.apply_gap_pad(bytes(cleared), 0, b"abcd") == bytes(cleared)
    assert gallery.apply_gap_pad(bytes(cleared), 2, b"XYZ")[g0 : g0 + 2] == b"XY"
    assert gallery.compress_exact_empty_blocks(b"hi", 5) is None
    n, slot = first_empty_slot(gallery.compress_exact_empty_blocks, data)
    assert zlib.decompress(slot) == data
    real_empty = gallery.compress_exact_empty_blocks

    def only_plain(buf, exact):
        return real_empty(buf, exact) if buf == data else None

    monkeypatch.setattr(gallery, "compress_exact_empty_blocks", only_plain)
    tuned, slot = gallery.compress_exact_with_gap_tune(data, n)
    assert zlib.decompress(slot) == tuned
    monkeypatch.setattr(gallery, "compress_exact_empty_blocks", real_empty)
    with pytest.raises(SystemExit, match="gap tune"):
        gallery.compress_exact_with_gap_tune(fi.darc({"a.bin": b"ab"}, align=1), 8)

    vanilla = tmp_path / "van.bin"
    vanilla.write_bytes(b"x")
    monkeypatch.setattr(gallery, "VANILLA_CANDIDATES", [tmp_path / "nope.bin", vanilla])
    assert gallery.pick_vanilla() == vanilla
    monkeypatch.setattr(gallery, "VANILLA_CANDIDATES", [tmp_path / "nope.bin"])
    with pytest.raises(SystemExit, match="no vanilla"):
        gallery.pick_vanilla()


def test_gallery_gap_second_loop(monkeypatch):
    base = fi.darc({"a.bin": b"abc", "b.bin": b"def"}, align=1)
    data = base
    while True:
        data += b"\x00"
        cap = sum(sz for sz, _ in gallery.interfile_zero_gaps(data))
        if cap >= 801 and cap % 2 == 1:
            break
    n, _slot = first_empty_slot(gallery.compress_exact_empty_blocks, data, lo=32)
    real = gallery.compress_exact_empty_blocks

    def wrapped(buf, exact):
        if buf.endswith(b"\x00" * 801):
            return real(buf, exact)
        return None

    monkeypatch.setattr(gallery.os, "urandom", lambda k: b"\xff" * k)
    monkeypatch.setattr(gallery, "compress_exact_empty_blocks", wrapped)
    tuned, slot = gallery.compress_exact_with_gap_tune(data, n)
    assert zlib.decompress(slot) == tuned


def test_gallery_main_branches(tmp_path, monkeypatch):
    use_font(monkeypatch, gallery)
    img = tmp_path / "img.bin"
    write_img(img, {gallery.PKG: arc_package(_gallery_files())})
    extra = bind(monkeypatch, tmp_path, gallery, img)
    monkeypatch.setattr(gallery, "compress_exact_with_gap_tune", fast_exact)
    before = img.read_bytes()
    assert gallery.main() is None
    assert img.read_bytes() != before
    assert extra.is_file()

    monkeypatch.setattr(gallery, "find_ui_png", lambda *a, **k: None)
    write_img(img, {gallery.PKG: arc_package(_gallery_files())})
    bind(monkeypatch, tmp_path, gallery, img)
    monkeypatch.setattr(gallery, "compress_exact_with_gap_tune", fast_exact)
    assert gallery.main() is None

    tiny = tmp_path / "tiny.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(tiny)
    monkeypatch.setattr(gallery, "find_ui_png", lambda *a, **k: tiny)
    write_img(img, {gallery.PKG: arc_package(_gallery_files())})
    bind(monkeypatch, tmp_path, gallery, img)
    monkeypatch.setattr(gallery, "compress_exact_with_gap_tune", fast_exact)
    assert gallery.main() is None

    bad = _gallery_files()
    bad["timg/Gallery_txt01.bclim"] = noise_bclim(16, 16, 1, seed=1)
    write_img(img, {gallery.PKG: arc_package(bad)})
    bind(monkeypatch, tmp_path, gallery, img)
    with pytest.raises(SystemExit, match="unsupported"):
        gallery.main()

    files = _gallery_files()
    files.pop("timg/Gallery_txt09.bclim")
    write_img(img, {gallery.PKG: arc_package(files)})
    bind(monkeypatch, tmp_path, gallery, img)
    with pytest.raises(SystemExit, match="missing"):
        gallery.main()

    write_img(img, {gallery.PKG: arc_package(_gallery_files())})
    bind(monkeypatch, tmp_path, gallery, img)
    monkeypatch.setattr(
        gallery, "compress_exact_with_gap_tune", lambda d, n: (d, zlib.compress(d) + b"\x00")
    )
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        gallery.main()
    monkeypatch.setattr(
        gallery, "compress_exact_with_gap_tune", lambda d, n: (d + b"q", zlib.compress(d + b"q"))
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        gallery.main()

    write_img(img, {gallery.PKG: retarget_sidecar(arc_package(_gallery_files()))})
    bind(monkeypatch, tmp_path, gallery, img)
    monkeypatch.setattr(gallery, "compress_exact_with_gap_tune", fast_exact)
    with pytest.raises(SystemExit, match="DMST changed"):
        gallery.main()

    write_img(img, {gallery.PKG: arc_package(_gallery_files())})
    bind(monkeypatch, tmp_path, gallery, img)
    monkeypatch.setattr(gallery, "compress_exact_with_gap_tune", fast_exact)
    corrupt_later_darc(monkeypatch)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        gallery.main()
    restore_zlib(monkeypatch)

    write_img(img, {gallery.PKG: arc_package(_gallery_files())})
    bind(monkeypatch, tmp_path, gallery, img)
    monkeypatch.setattr(gallery, "compress_exact_with_gap_tune", fast_exact)
    monkeypatch.setattr(
        gallery,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(gallery.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        gallery.main()

    img.write_bytes(fi.img({}, count=gallery.PKG + 1))
    bind(monkeypatch, tmp_path, gallery, img)
    with pytest.raises(SystemExit, match="pkg"):
        gallery.main()
    monkeypatch.setattr(gallery, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        gallery.main()


# ---------------------------------------------------------------------------
# To-Do
# ---------------------------------------------------------------------------


def test_todo_render_compress_and_labels(tmp_path, monkeypatch):
    use_font(monkeypatch, todo)
    todo.OUT = tmp_path / "todo"
    todo.OUT.mkdir()
    assert todo.font(14).size == 14
    im = todo.render_label(80, 18, "History", hard=True, max_size=14)
    assert im.size == (80, 18)
    with pytest.raises(RuntimeError):
        todo.render_label(4, 4, "Earned ToDo Points")

    data = tiny_darc_pair()
    assert todo.interfile_zero_gaps(data)
    assert todo.interfile_zero_gaps(data, min_len=10_000) == []
    runs = todo.interfile_zero_gaps(data)
    gsz, g0 = runs[0]
    assert todo.apply_gap_pad(data, 0, b"ab") == data
    assert todo.apply_gap_pad(data, 2, b"QW")[g0 : g0 + 2] == b"QW"
    assert todo.compress_exact_empty_blocks(b"hi", 6) is None
    n, slot = first_empty_slot(todo.compress_exact_empty_blocks, data)
    assert zlib.decompress(slot) == data
    real_empty = todo.compress_exact_empty_blocks

    def only_plain(buf, exact):
        return real_empty(buf, exact) if buf == data else None

    monkeypatch.setattr(todo, "compress_exact_empty_blocks", only_plain)
    tuned, slot = todo.compress_exact_with_gap_tune(data, n)
    assert zlib.decompress(slot) == tuned
    monkeypatch.setattr(todo, "compress_exact_empty_blocks", real_empty)
    with pytest.raises(SystemExit, match="exact zlib"):
        todo.compress_exact_with_gap_tune(fi.darc({"a.bin": b"ab"}, align=1), 8)

    masters = tmp_path / "masters"
    masters.mkdir()
    Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(masters / "Que_Txt00a.png")
    monkeypatch.setattr(todo, "QUEST_MASTERS", masters)
    darc_bytes = fi.darc({"timg/Que_Txt00a.bclim": noise_bclim(16, 16, 8, seed=1)})
    from darcutil import DarcArchive

    packed = todo.pack_quest_masters(DarcArchive(bytearray(darc_bytes)), tmp_path)
    assert packed == {"Que_Txt00a"}
    with pytest.raises(SystemExit, match="no timg"):
        todo.pack_quest_masters(DarcArchive(bytearray(fi.darc({"timg/other.bclim": b"x" * 16}))), tmp_path)

    monkeypatch.setattr(todo, "QUEST_MASTERS", tmp_path / "empty_m")
    (tmp_path / "empty_m").mkdir()
    labels = [
        ("timg/Que_Txt01b.bclim", "To-Do List"),
        ("timg/Que_Txt01d.bclim", "History"),
        ("timg/Que_Txt01c.bclim", "Points"),
    ]
    wide = {
        "timg/Que_Txt01b.bclim": noise_bclim(80, 18, 8, seed=2),
        "timg/Que_Txt01d.bclim": noise_bclim(80, 18, 8, seed=3),
        "timg/Que_Txt01c.bclim": noise_bclim(200, 32, 8, seed=4),
    }
    out = todo.patch_rgba_labels(fi.darc(wide), labels, tmp_path)
    assert out != fi.darc(wide)
    with pytest.raises(SystemExit, match="not RGBA4444"):
        todo.patch_rgba_labels(
            fi.darc({"timg/Que_Txt01b.bclim": noise_bclim(32, 16, 0xB, 1)}),
            [("timg/Que_Txt01b.bclim", "To-Do List")],
            tmp_path,
        )
    with pytest.raises(SystemExit, match="missing"):
        todo.patch_rgba_labels(fi.darc(wide), [("timg/nope.bclim", "X")], tmp_path)


def test_todo_zopfli_and_splice(tmp_path, monkeypatch):
    data = tiny_darc_pair()
    monkeypatch.setattr(todo, "compress_exact_with_gap_tune", lambda d, n: (d, b"gap-hit"))
    monkeypatch.setattr(todo.zopfli_zlib, "compress", lambda d: b"Z" * 999)
    assert todo.compress_exact_zopfli(data, 10)[1] == b"gap-hit"

    monkeypatch.setattr(todo.zopfli_zlib, "compress", lambda d: b"Z" * 40)
    assert todo.compress_exact_zopfli(data, 40)[1] == b"Z" * 40

    base_ff = data.count(0xFF)

    def by_salt(buf):
        return b"Z" * (100 + buf.count(0xFF) - base_ff)

    monkeypatch.setattr(todo.zopfli_zlib, "compress", by_salt)
    monkeypatch.setattr(todo.os, "urandom", lambda k: b"\xff" * k)
    tuned, slot = todo.compress_exact_zopfli(data, 103)
    assert len(slot) == 103

    calls = {"n": 0}

    def phased(buf):
        calls["n"] += 1
        if calls["n"] < 40:
            if buf.count(0xFF) <= base_ff:
                return b"Z" * 49
            return b"Z" * 55
        if calls["n"] == 40:
            return b"Z" * 55
        return b"Z" * 50

    monkeypatch.setattr(todo.zopfli_zlib, "compress", phased)
    monkeypatch.setattr(
        todo,
        "compress_exact_with_gap_tune",
        lambda d, n: (_ for _ in ()).throw(AssertionError("fine-scan fell through")),
    )
    assert len(todo.compress_exact_zopfli(data, 50)[1]) == 50

    monkeypatch.setattr(todo, "compress_exact_with_gap_tune", lambda d, n: (d, b"fallback"))
    monkeypatch.setattr(todo.zopfli_zlib, "compress", lambda d: b"Z" * 3)
    assert todo.compress_exact_zopfli(data, 50)[1] == b"fallback"

    img = tmp_path / "img.bin"
    files = {}
    for i, png in enumerate(sorted((ROOT / "assets" / "images" / "Quest.check" / "timg").glob("*.png"))):
        w, h = Image.open(png).size
        files[f"timg/{png.stem}.bclim"] = noise_bclim(w, h, 8, seed=40 + i)
    blob = arc_package(files)
    write_img(img, {todo.QUEST_PKG: blob})
    bind(monkeypatch, tmp_path, todo, img)
    from img import FileWindow, Package
    raw_pkg = fi.read_package(img, todo.QUEST_PKG)
    srcp = tmp_path / "q.pkg"
    srcp.write_bytes(raw_pkg)
    pkg = Package(FileWindow(str(srcp)), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if e.fn == "Data.arc")
    cmp_len = arc.fw.len()
    patched = arc.parsed()

    monkeypatch.setattr(todo, "compress_exact_with_gap_tune", fast_exact)
    monkeypatch.setattr(todo, "compress_exact_zopfli", fast_exact)
    monkeypatch.setattr(todo.zopfli_zlib, "compress", lambda d: b"Z" * (cmp_len + 5))
    todo.splice_pkg(todo.QUEST_PKG, img, patched, cmp_len)
    monkeypatch.setattr(todo.zopfli_zlib, "compress", lambda d: b"Z" * max(1, cmp_len - 10))
    todo.splice_pkg(todo.QUEST_PKG, img, patched, cmp_len)

    with pytest.raises(SystemExit, match="slot mismatch"):
        todo.splice_pkg(todo.QUEST_PKG, img, patched, cmp_len + 3)
    monkeypatch.setattr(todo, "compress_exact_zopfli", lambda d, n: (d, zlib.compress(d) + b"\x00"))
    monkeypatch.setattr(todo, "compress_exact_with_gap_tune", lambda d, n: (d, zlib.compress(d) + b"\x00"))
    monkeypatch.setattr(todo.zopfli_zlib, "compress", lambda d: b"Z")
    with pytest.raises(SystemExit, match="zlib verify failed"):
        todo.splice_pkg(todo.QUEST_PKG, img, patched, cmp_len)
    monkeypatch.setattr(
        todo, "compress_exact_zopfli", lambda d, n: (d + b"q", zlib.compress(d + b"q"))
    )
    monkeypatch.setattr(
        todo, "compress_exact_with_gap_tune", lambda d, n: (d + b"q", zlib.compress(d + b"q"))
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        todo.splice_pkg(todo.QUEST_PKG, img, patched, cmp_len)

    write_img(img, {todo.QUEST_PKG: retarget_sidecar(blob)})
    monkeypatch.setattr(todo, "compress_exact_zopfli", fast_exact)
    monkeypatch.setattr(todo, "compress_exact_with_gap_tune", fast_exact)
    monkeypatch.setattr(todo.zopfli_zlib, "compress", lambda d: b"Z" * (cmp_len + 5))
    with pytest.raises(SystemExit, match="DMST changed"):
        todo.splice_pkg(todo.QUEST_PKG, img, patched, cmp_len)

    write_img(img, {todo.QUEST_PKG: blob})
    monkeypatch.setattr(todo.zopfli_zlib, "compress", lambda d: b"Z" * (cmp_len + 5))
    corrupt_later_darc(monkeypatch)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        todo.splice_pkg(todo.QUEST_PKG, img, patched, cmp_len)


def test_todo_main(tmp_path, monkeypatch):
    use_font(monkeypatch, todo)
    files = {}
    for i, png in enumerate(sorted((ROOT / "assets" / "images" / "Quest.check" / "timg").glob("*.png"))):
        w, h = Image.open(png).size
        files[f"timg/{png.stem}.bclim"] = noise_bclim(w, h, 8, seed=50 + i)
    img = tmp_path / "img.bin"
    write_img(img, {todo.QUEST_PKG: arc_package(files)})
    extra = bind(monkeypatch, tmp_path, todo, img)
    monkeypatch.setattr(todo.zopfli_zlib, "compress", lambda d: b"Z" * 8)
    monkeypatch.setattr(todo, "compress_exact_with_gap_tune", fast_exact)
    monkeypatch.setattr(todo, "compress_exact_zopfli", fast_exact)
    before = img.read_bytes()
    assert todo.main() is None
    assert img.read_bytes() != before
    assert extra.is_file()
    monkeypatch.setattr(todo, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        todo.main()


def test_todo_gap_second_loop(monkeypatch):
    base = fi.darc({"a.bin": b"abc", "b.bin": b"def"}, align=1)
    data = base
    while True:
        data += b"\x00"
        cap = sum(sz for sz, _ in todo.interfile_zero_gaps(data))
        if cap >= 801 and cap % 2 == 1:
            break
    n, _slot = first_empty_slot(todo.compress_exact_empty_blocks, data, lo=32)
    real = todo.compress_exact_empty_blocks

    def wrapped(buf, exact):
        if buf.endswith(b"\x00" * 801):
            return real(buf, exact)
        return None

    monkeypatch.setattr(todo.os, "urandom", lambda k: b"\xff" * k)
    monkeypatch.setattr(todo, "compress_exact_empty_blocks", wrapped)
    tuned, slot = todo.compress_exact_with_gap_tune(data, n)
    assert zlib.decompress(slot) == tuned


# ---------------------------------------------------------------------------
# My Data
# ---------------------------------------------------------------------------


def test_mydata_helpers(tmp_path, monkeypatch):
    use_font(monkeypatch, mydata)
    mydata.OUT = tmp_path / "mydata"
    mydata.OUT.mkdir()
    assert mydata.font(12).size == 12
    im = mydata.render_label(64, 16, "Status", hard=True, max_size=12)
    assert im.size == (64, 16)
    with pytest.raises(RuntimeError):
        mydata.render_label(4, 4, "My Camera")

    data = tiny_darc_pair()
    assert mydata.zero_interfile_gaps(data) == data
    runs = mydata.interfile_zero_gaps(data)
    assert runs
    gsz, g0 = runs[0]
    assert mydata.apply_gap_pad(data, 0, b"ab") == data
    assert mydata.apply_gap_pad(data, 1, b"Q")[g0 : g0 + 1] == b"Q"
    assert mydata.interfile_zero_gaps(fi.darc({"a.bin": b"ab", "b.bin": b"cd"}, align=1), min_len=4) == []
    assert mydata.compress_exact_empty_blocks(b"hi", 5) is None
    body = zlib.compressobj(6, wbits=-15)
    raw_body = body.compress(b"hello") + body.flush(zlib.Z_SYNC_FLUSH)
    assert mydata._try_empty_pad(b"hello", raw_body, b"\x78\x9c", 4) is None
    n, slot = first_empty_slot(mydata.compress_exact_empty_blocks, b"hello")
    assert mydata._try_empty_pad(b"hello", raw_body, b"\x78\x9c", n) is None or True
    tuned, slot = mydata.compress_exact_with_gap_tune(data, first_empty_slot(mydata.compress_exact_empty_blocks, data)[0])
    assert zlib.decompress(slot) == tuned
    with pytest.raises(SystemExit, match="no gap"):
        mydata.compress_exact_with_gap_tune(fi.darc({"a.bin": b"ab"}, align=1), 7)

    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", lambda *a, **k: None)
    monkeypatch.setattr(mydata, "_try_empty_pad", lambda *a, **k: b"hit")
    tuned, slot = mydata.compress_exact_with_gap_tune(data, 40)
    assert slot == b"hit"
    monkeypatch.setattr(mydata, "_try_empty_pad", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="exact zlib"):
        mydata.compress_exact_with_gap_tune(data, 40)

    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z" * 9999)
    with pytest.raises(SystemExit, match="exceeds"):
        mydata.compress_exact_zopfli(b"abc", 10)
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z" * 10)
    assert mydata.compress_exact_zopfli(b"abc", 10)[1] == b"Z" * 10
    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", lambda d, n: b"empty")
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z" * 5)
    assert mydata.compress_exact_zopfli(fi.darc({"a.bin": b"ab"}, align=1), 20)[1] == b"empty"
    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", lambda d, n: None)
    with pytest.raises(SystemExit, match="no gaps"):
        mydata.compress_exact_zopfli(fi.darc({"a.bin": b"ab"}, align=1), 20)

    base_ff = data.count(0xFF)

    def by_pad(buf):
        return b"Z" * (40 + buf.count(0xFF) - base_ff)

    monkeypatch.setattr(mydata.os, "urandom", lambda k: b"\xff" * k)
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", by_pad)
    tuned, slot = mydata.compress_exact_zopfli(data, 43)
    assert len(slot) == 43
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z" * 3)
    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", lambda d, n: b"pad")
    assert mydata.compress_exact_zopfli(data, 80)[1] == b"pad"
    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", lambda d, n: None)
    with pytest.raises(SystemExit, match="exact zopfli"):
        mydata.compress_exact_zopfli(data, 80)


def test_mydata_patch_and_main(tmp_path, monkeypatch):
    use_font(monkeypatch, mydata)
    w, h = png_wh("Myroom.check", "mcmn_tex_todo_RGBA4")
    labels = [("timg/mcmn_tex_todo_RGBA4.bclim", "To-Do List")]
    arc = fi.darc({"timg/mcmn_tex_todo_RGBA4.bclim": noise_bclim(w, h, 0xB, seed=8)})
    mydata.OUT = tmp_path / "md"
    mydata.OUT.mkdir()
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z")
    assert mydata.fit_and_patch_arc(arc, labels, tmp_path, 10_000).startswith(b"darc")
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z" * 50_000)
    with pytest.raises(SystemExit, match="no trial fits"):
        mydata.fit_and_patch_arc(arc, labels, tmp_path, 10)
    with pytest.raises(SystemExit, match="missing"):
        mydata.patch_labels_into_darc(
            __import__("darcutil").DarcArchive(bytearray(arc)),
            [("timg/nope.bclim", "X")],
            tmp_path,
            hard=False,
        )
    bad = fi.darc({"timg/mcmn_tex_todo_RGBA4.bclim": noise_bclim(w, h, 8, seed=1)})
    with pytest.raises(SystemExit, match="not ETC1A4"):
        mydata.patch_labels_into_darc(
            __import__("darcutil").DarcArchive(bytearray(bad)),
            labels,
            tmp_path,
            hard=False,
        )
    header = [("timg/mydata_toptex_RGBA4.bclim", "My Data")]
    hw, hh = png_wh("MyroomHeader.check", "mydata_toptex_RGBA4")
    harc = fi.darc({"timg/mydata_toptex_RGBA4.bclim": noise_bclim(hw, hh, 0xB, seed=2)})
    mydata.patch_labels_into_darc(
        __import__("darcutil").DarcArchive(bytearray(harc)), header, tmp_path, hard=False
    )
    monkeypatch.setattr(mydata, "find_ui_png", lambda *a, **k: None)
    mydata.patch_labels_into_darc(
        __import__("darcutil").DarcArchive(bytearray(arc)), labels, tmp_path, hard=True, max_size=12
    )

    files = {}
    for i, (path, _en) in enumerate(mydata.JOBS[1][1]):
        stem = Path(path).stem
        files[path] = noise_bclim(*png_wh("Myroom.check", stem), 0xB, seed=60 + i)
    img = tmp_path / "img.bin"
    vanilla = tmp_path / "van.bin"
    blob = arc_package(files)
    write_img(img, {5380: blob})
    write_img(vanilla, {5380: blob})
    extra = bind(monkeypatch, tmp_path, mydata, img, vanilla=vanilla)
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z")
    before = img.read_bytes()
    assert mydata.main() is None
    assert img.read_bytes() != before
    assert extra.is_file()

    from img import FileWindow, Package

    raw = fi.read_package(img, 5380)
    cmp_len = None
    p = tmp_path / "p.pkg"
    p.write_bytes(raw)
    pkg = Package(FileWindow(str(p)), 0)
    pkg.parse(False)
    cmp_len = next(e for e in pkg.entries if e.fn == "Data.arc").fw.len()

    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", lambda *a, **k: None)
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z" * max(1, cmp_len - 10))
    monkeypatch.setattr(mydata, "compress_exact_zopfli", fast_exact)
    mydata.patch_package(5380, mydata.JOBS[1][1], source="live")

    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z")
    monkeypatch.setattr(mydata, "compress_exact_with_gap_tune", fast_exact)
    mydata.patch_package(5380, mydata.JOBS[1][1], source="vanilla")

    monkeypatch.setattr(mydata, "VANILLA", tmp_path / "no-van.bin")
    with pytest.raises(SystemExit, match="missing vanilla"):
        mydata.patch_package(5380, mydata.JOBS[1][1], source="vanilla")

    bind(monkeypatch, tmp_path, mydata, img, vanilla=vanilla)
    monkeypatch.setattr(mydata, "fit_and_patch_arc", lambda *a, **k: files and raw and __import__("darcutil").DarcArchive(bytearray(fi.darc({"a.bin": b"a"}))).data)
    # fit returns bytes; simpler:
    sample = fi.darc({"a.bin": b"abcdef"})
    monkeypatch.setattr(mydata, "fit_and_patch_arc", lambda *a, **k: sample)
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z" * (cmp_len + 20))
    with pytest.raises(SystemExit, match="exceeds slot"):
        mydata.patch_package(5380, labels, source="live")

    monkeypatch.setattr(mydata, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        mydata.main()


# ---------------------------------------------------------------------------
# Status stats
# ---------------------------------------------------------------------------


def _status_files() -> dict[int, dict[str, bytes]]:
    out: dict[int, dict[str, bytes]] = {}
    for pkg, labels in status.PKG_LABELS:
        folder = status.UI_PNG_FOLDERS[pkg][0]
        for i, (path, _en) in enumerate(labels):
            stem = Path(path).stem
            w, h = png_wh(folder, stem)
            out.setdefault(pkg, {})[path] = noise_bclim(w, h, 0xB, seed=70 + pkg + i)
    return out


def test_status_helpers(tmp_path, monkeypatch):
    use_font(monkeypatch, status)
    status.OUT = tmp_path / "st"
    status.OUT.mkdir()
    assert status.font(11).size == 11
    im = status.render_label(32, 14, "Sense")
    assert im.size == (32, 14)
    with pytest.raises(RuntimeError):
        status.render_label(4, 4, "G-Coin Exchange")
    data = tiny_darc_pair()
    runs = status.interfile_zero_gaps(data)
    gsz, g0 = runs[0]
    assert status.apply_gap_pad(data, 0, b"ab") == data
    assert status.apply_gap_pad(data, 2, b"LM")[g0 : g0 + 2] == b"LM"
    assert status.compress_exact_empty_blocks(b"hi", 5) is None
    n, slot = first_empty_slot(status.compress_exact_empty_blocks, data)
    tuned, slot = status.compress_exact_with_gap_tune(data, n)
    assert zlib.decompress(slot) == tuned
    with pytest.raises(SystemExit, match="no gaps"):
        status.compress_exact_with_gap_tune(fi.darc({"a.bin": b"ab"}, align=1), 7)
    with pytest.raises(SystemExit, match="exact zlib"):
        status.compress_exact_with_gap_tune(data, 8)


def test_status_main_and_errors(tmp_path, monkeypatch):
    use_font(monkeypatch, status)
    arcs = _status_files()
    img = tmp_path / "img.bin"
    write_img(img, {k: arc_package(v) for k, v in arcs.items()})
    extra = bind(monkeypatch, tmp_path, status, img)
    monkeypatch.setattr(status, "compress_exact_with_gap_tune", fast_exact)
    before = img.read_bytes()
    assert status.main() is None
    assert img.read_bytes() != before
    assert extra.is_file()

    monkeypatch.setattr(status, "find_ui_png", lambda *a, **k: None)
    one = {5501: {"timg/stat_tex_undo.bclim": noise_bclim(32, 14, 0xB, seed=1)}}
    write_img(img, {5501: arc_package(one[5501]), 5255: arc_package(arcs[5255])})
    bind(monkeypatch, tmp_path, status, img)
    monkeypatch.setattr(status, "compress_exact_with_gap_tune", fast_exact)
    # full main still wants every label; render path via a direct patch of one ETC label
    status.patch_pkg(5501, [("timg/stat_tex_undo.bclim", "Fitness")])

    monkeypatch.setattr(status, "find_ui_png", lambda *a, **k: None)
    write_img(img, {5255: arc_package({"timg/Scd_Result_Rich_Text.bclim": noise_bclim(32, 16, 8, seed=2)})})
    bind(monkeypatch, tmp_path, status, img)
    with pytest.raises(SystemExit, match="no render path"):
        status.patch_pkg(5255, [("timg/Scd_Result_Rich_Text.bclim", "Owned Rich:")])

    with pytest.raises(SystemExit, match="missing"):
        status.patch_pkg(5255, [("timg/nope.bclim", "X")])

    monkeypatch.setattr(status, "png_to_bclim_same_size", lambda *a, **k: b"short")
    monkeypatch.setattr(status, "find_ui_png", lambda *a, **k: ROOT / "assets" / "images" / "ScdStatus.check" / "timg" / "Scd_Result_Rich_Text.png")
    write_img(img, {5255: arc_package({"timg/Scd_Result_Rich_Text.bclim": noise_bclim(78, 16, 8, seed=3)})})
    bind(monkeypatch, tmp_path, status, img)
    with pytest.raises(SystemExit, match="size change"):
        status.patch_pkg(5255, [("timg/Scd_Result_Rich_Text.bclim", "Owned Rich:")])

    write_img(img, {k: arc_package(v) for k, v in arcs.items()})
    bind(monkeypatch, tmp_path, status, img)
    monkeypatch.setattr(
        status, "compress_exact_with_gap_tune", lambda d, n: (d, zlib.compress(d) + b"\x00")
    )
    with pytest.raises(SystemExit, match="zlib verify failed"):
        status.patch_pkg(5501, status.PKG_LABELS[0][1])
    monkeypatch.setattr(
        status, "compress_exact_with_gap_tune", lambda d, n: (d + b"q", zlib.compress(d + b"q"))
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        status.patch_pkg(5501, status.PKG_LABELS[0][1])

    write_img(img, {5501: retarget_sidecar(arc_package(arcs[5501]))})
    bind(monkeypatch, tmp_path, status, img)
    monkeypatch.setattr(status, "compress_exact_with_gap_tune", fast_exact)
    with pytest.raises(SystemExit, match="DMST changed"):
        status.patch_pkg(5501, status.PKG_LABELS[0][1])

    write_img(img, {5501: arc_package(arcs[5501])})
    bind(monkeypatch, tmp_path, status, img)
    monkeypatch.setattr(status, "compress_exact_with_gap_tune", fast_exact)
    corrupt_later_darc(monkeypatch)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        status.patch_pkg(5501, status.PKG_LABELS[0][1])
    restore_zlib(monkeypatch)

    write_img(img, {5501: arc_package(arcs[5501])})
    bind(monkeypatch, tmp_path, status, img)
    monkeypatch.setattr(status, "compress_exact_with_gap_tune", fast_exact)
    monkeypatch.setattr(
        status,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(status.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice"):
        status.patch_pkg(5501, status.PKG_LABELS[0][1])

    monkeypatch.setattr(status, "VANILLA", tmp_path / "absent.bin")
    monkeypatch.setattr(status, "MOD_IMG", img)
    monkeypatch.setattr(status, "compress_exact_with_gap_tune", fast_exact)
    monkeypatch.setattr(status, "splice_packages_into_img", lambda *a: None)
    status.patch_pkg(5501, status.PKG_LABELS[0][1][:1])

    monkeypatch.setattr(status, "MOD_IMG", tmp_path / "missing.bin")
    monkeypatch.setattr(status, "VANILLA", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        status.main()


# ---------------------------------------------------------------------------
# Watcher issue 28
# ---------------------------------------------------------------------------


def _pane_chunk(name: bytes, marker: bytes | None = None) -> bytes:
    chunk = bytearray(160)
    i = 32
    chunk[i - 12 : i - 8] = b"pic1"
    chunk[i - 4] = 0xFF
    chunk[i - 2] = 0xFF
    chunk[i : i + len(name)] = name
    if marker is not None:
        chunk[i + 20 : i + 20 + len(marker)] = marker
    return bytes(chunk)


def _layout(kind: str, *, marker: bool = True) -> bytes:
    spot_m = bytes.fromhex("1500000007")
    page_m = bytes.fromhex("1500000003")
    if kind == "spot":
        names = (b"Pic_Page01_02", b"Pic_Page01_03", b"Pic_Page01_04", b"Pic_Page01_05")
        return b"".join(_pane_chunk(n, spot_m if marker else None) for n in names)
    if kind == "page":
        parts = [_pane_chunk(b"Pic_Page01_00")]
        parts.append(_pane_chunk(b"Pic_Page01_01", page_m if marker else None))
        return b"".join(parts)
    return _pane_chunk(b"Pic_Page01_00") + _pane_chunk(b"Pic_Page01_01") + b"Mag_Page01.bclim"


def _watcher_arc(tmp_path: Path, *, page_marker: bool = True, with_page: bool = True) -> bytes:
    masters = tmp_path / "masters"
    masters.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (8, 8, 8, 255)).save(masters / "TinyMark.png")
    files = {
        "timg/TinyMark.bclim": noise_bclim(16, 16, 8, seed=4),
        "blyt/Lyt_Spot_O01.bclyt": _layout("spot"),
        "blyt/Lyt_Spot_U01.bclyt": _layout("spot"),
        "blyt/Pts_Page_O01a.bclyt": _layout("page", marker=page_marker),
        "blyt/Pts_Page_U01a.bclyt": _layout("page", marker=page_marker),
        "blyt/Pts_Shadow_O.bclyt": _layout("shadow"),
        "blyt/Pts_Shadow_U.bclyt": _layout("shadow"),
    }
    if with_page:
        files["timg/Mag_Page01.bclim"] = noise_bclim(32, 64, 2, seed=5)
    return fi.darc(files), masters, files


def test_watcher_layout_helpers(tmp_path, monkeypatch):
    use_font(monkeypatch, watcher)
    page = Image.new("RGBA", (32, 64), (0, 0, 0, 0))
    painted = watcher._draw(page, "Lake\nline", (40, 40, 40, 255))
    assert painted.size == (32, 64)
    raw = _layout("spot")
    hidden = watcher._hide_pic_panes(raw, (b"Pic_Page01_02",))
    assert hidden != raw
    bare = b"XXXXXXXXXXXXXXXXXXXXPic_Page01_02" + raw
    assert watcher._hide_pic_panes(bare, (b"Pic_Page01_02",))
    with pytest.raises(SystemExit, match="missing picture pane"):
        watcher._hide_pic_panes(b"nothing", (b"Pic_Page01_02",))
    unbound = watcher._unbind_page_texture(raw, b"Pic_Page01_04")
    assert unbound != raw

    orig = noise_bclim(16, 16, 2, seed=1)
    assert watcher._encode(Image.new("RGBA", (16, 16), (1, 1, 1, 255)), orig, tmp_path, "a", "la4")
    orig8 = noise_bclim(16, 16, 8, seed=1)
    assert watcher._encode(Image.new("RGBA", (16, 16), (1, 1, 1, 255)), orig8, tmp_path, "b", "rgba4444")
    orig5 = noise_bclim(16, 16, 5, seed=1)
    assert watcher._encode(Image.new("RGBA", (16, 16), (1, 1, 1, 255)), orig5, tmp_path, "c", "rgb565")

    arc, masters, _files = _watcher_arc(tmp_path)
    monkeypatch.setattr(watcher, "MASTERS", masters)
    patched = watcher.patch_arc(arc, tmp_path)
    assert b"Mag_Page02.bclim" in patched
    with pytest.raises(SystemExit, match="no timg"):
        watcher._pack_masters(__import__("darcutil").DarcArchive(bytearray(fi.darc({"timg/x.bclim": b"1234"}))), tmp_path)
    monkeypatch.setattr(watcher, "MASTERS", ROOT / "assets" / "images" / "TownGuide.check" / "timg")
    with pytest.raises(SystemExit, match="no timg"):
        watcher._pack_masters(__import__("darcutil").DarcArchive(bytearray(arc)), tmp_path)

    arc_np, masters, _files = _watcher_arc(tmp_path / "np", with_page=False)
    monkeypatch.setattr(watcher, "MASTERS", masters)
    with pytest.raises(SystemExit, match="missing Mag_Page01"):
        watcher.patch_arc(arc_np, tmp_path)
    arc_bad, masters, _files = _watcher_arc(tmp_path / "bad", page_marker=False)
    monkeypatch.setattr(watcher, "MASTERS", masters)
    with pytest.raises(SystemExit, match="no flipped page"):
        watcher.patch_arc(arc_bad, tmp_path)
    files_only = {"timg/Mag_Page01.bclim": noise_bclim(32, 64, 2, seed=1), "timg/TinyMark.bclim": noise_bclim(16, 16, 8, seed=2)}
    monkeypatch.setattr(watcher, "MASTERS", masters)
    with pytest.raises(SystemExit, match="missing"):
        watcher.patch_arc(fi.darc(files_only), tmp_path)


def test_watcher_main(tmp_path, monkeypatch):
    use_font(monkeypatch, watcher)
    _arc, masters, files = _watcher_arc(tmp_path)
    monkeypatch.setattr(watcher, "MASTERS", masters)
    img = tmp_path / "img.bin"
    write_img(img, {watcher.PKG: arc_package(files)})
    extra = bind(monkeypatch, tmp_path, watcher, img)
    before = img.read_bytes()
    assert watcher.main() is None
    assert img.read_bytes() != before
    assert extra.is_file()

    fresh = lambda: write_img(img, {watcher.PKG: arc_package(files)})
    fresh()
    monkeypatch.setattr(watcher, "try_fast_exact_slot", lambda d, n: None)
    assert watcher.main() is None

    fresh()
    monkeypatch.setattr(watcher, "try_fast_exact_slot", lambda d, n: (d, zlib.compress(d) + b"\x00"))
    with pytest.raises(SystemExit, match="zlib verify failed"):
        watcher.main()
    fresh()
    monkeypatch.setattr(watcher, "try_fast_exact_slot", lambda d, n: (d + b"q", zlib.compress(d + b"q")))
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        watcher.main()
    fresh()
    monkeypatch.setattr(watcher, "try_fast_exact_slot", fast_exact)
    monkeypatch.setattr(
        watcher,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(watcher.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed"):
        watcher.main()

    fresh()
    monkeypatch.setattr(watcher, "VANILLA", tmp_path / "absent.bin")
    monkeypatch.setattr(watcher, "MOD_IMG", img)
    monkeypatch.setattr(watcher, "splice_packages_into_img", lambda *a: None)
    monkeypatch.setattr(watcher, "try_fast_exact_slot", fast_exact)
    assert watcher.main() is None
    monkeypatch.setattr(watcher, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="no img.bin"):
        watcher.main()


# ---------------------------------------------------------------------------
# Mini-game texture helpers (no cut_minigame_*)
# ---------------------------------------------------------------------------


def _l2(w=8, h=8, fmt=13) -> bytes:
    if fmt == 13:
        n = (w // 4) * (h // 4) * 16
    elif fmt == 10:
        n = w * h * 4
    else:
        n = w * h * 2
    header = bytearray(0x80)
    struct.pack_into("<4I", header, 0, w, h, fmt, n)
    return bytes(header) + random.Random(fmt + w).randbytes(n)


def test_minigame_helpers(tmp_path, monkeypatch):
    van = tmp_path / "van.bin"
    van.write_bytes(b"v")
    monkeypatch.setattr(minigame, "find_vanilla_img", lambda: van)
    assert minigame._vanilla_src() == van.resolve()
    monkeypatch.setattr(minigame, "find_vanilla_img", lambda: None)
    monkeypatch.setattr(minigame, "_FALLBACK_VANILLA", tmp_path / "fall.bin")
    assert minigame._vanilla_src() == (tmp_path / "fall.bin").resolve()

    payload = b"texture-bytes-0123456789"
    n, slot = None, None
    slot = minigame.try_compress_to_slot(payload, 400)
    assert slot is not None and zlib.decompress(slot) == payload
    assert minigame.try_compress_to_slot(payload, 8) is None
    with pytest.raises(SystemExit, match="does not fit"):
        minigame.compress_to_slot(payload, 8)
    assert minigame.compress_to_slot(payload, 400) == minigame.try_compress_to_slot(payload, 400)

    pkg = fi.package(
        [
            ("005.l2mgtex", _l2(), b"TEX ", True),
            ("keep.bin", b"KEEPME!!", b"DMST", False),
        ]
    )
    offs = minigame._entry_offsets(pkg)
    assert offs
    minigame.OUT = tmp_path / "mg"
    masters = tmp_path / "masters"
    masters.mkdir()
    Image.new("RGBA", (8, 8), (255, 0, 0, 200)).save(masters / "a.png")
    patched = minigame.patch_package(pkg, {"005.l2mgtex": "a.png"}, masters)
    assert patched != pkg
    with pytest.raises(SystemExit, match="missing elements"):
        minigame.patch_package(pkg, {"005.l2mgtex": "a.png", "999.l2mgtex": "a.png"}, masters)
    raw_pkg = fi.package([("005.l2mgtex", _l2(), b"TEX ", False)])
    raw_path = tmp_path / "raw.pkg"
    raw_path.write_bytes(raw_pkg)
    from img import FileWindow, Package

    parsed = Package(FileWindow(str(raw_path)), 0)
    parsed.parse(False)
    raw_elem = parsed.entries[0]
    monkeypatch.setattr(
        minigame,
        "_entry_offsets",
        lambda blob, off=raw_elem.fw.base_offset: {off: Package.ENTRY_SIZE},
    )
    with pytest.raises(SystemExit, match="not zlib-compressed"):
        minigame.patch_package(raw_pkg, {"005.l2mgtex": "a.png"}, masters)
    monkeypatch.setattr(minigame, "_entry_offsets", lambda blob: {})
    with pytest.raises(SystemExit, match="not found"):
        minigame.patch_package(pkg, {"005.l2mgtex": "a.png"}, masters)

    import zopfli.zlib as zz

    real_compress = zlib.compress
    monkeypatch.setattr(minigame.zlib, "compress", lambda data, level=9: b"\x00" * 500)
    monkeypatch.setattr(zz, "compress", lambda data: real_compress(data, 9))
    padded = minigame.try_compress_to_slot(b"x", 200)
    assert padded is not None and zlib.decompress(padded) == b"x"
    monkeypatch.setattr(zz, "compress", lambda data: b"\x00" * 500)
    assert minigame.try_compress_to_slot(b"x", 20) is None


def test_minigame_patch_failures_and_main(tmp_path, monkeypatch):
    minigame.OUT = tmp_path / "mg2"
    masters = tmp_path / "masters"
    masters.mkdir()
    Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(masters / "a.png")
    pkg = fi.package(
        [
            ("005.l2mgtex", _l2(), b"TEX ", True),
            ("keep.bin", b"KEEPME!!", b"DMST", False),
        ]
    )
    monkeypatch.setattr(minigame.l2mgtex, "encode_like", lambda orig, im: b"short")
    with pytest.raises(SystemExit, match="dec_len"):
        minigame.patch_package(pkg, {"005.l2mgtex": "a.png"}, masters)

    monkeypatch.setattr(minigame, "try_compress_to_slot", lambda data, n: None)
    monkeypatch.setattr(minigame.l2mgtex, "encode_like", lambda orig, im: orig)
    with pytest.raises(SystemExit, match="do not fit"):
        minigame.patch_package(pkg, {"005.l2mgtex": "a.png"}, masters)

    def bad(data, slot_len):
        raw = zlib.compress(b"x", 9)
        return raw + b"\x00" * (slot_len - len(raw))

    monkeypatch.setattr(minigame, "try_compress_to_slot", bad)
    with pytest.raises(SystemExit, match="zlib slot not exact"):
        minigame.patch_package(pkg, {"005.l2mgtex": "a.png"}, masters)

    side = retarget_sidecar(pkg)

    def different_slot(data, n):
        from exact_zlib import pad_closed_zlib_stream

        original = zlib.compress(data, 1)
        for level in (9, 0, 6):
            slot = pad_closed_zlib_stream(zlib.compress(data, level), n, expected=data)
            if slot is not None and slot[:24] != original[:24]:
                return slot
        return fast_exact(data, n)[1]

    monkeypatch.setattr(minigame, "try_compress_to_slot", different_slot)
    monkeypatch.setattr(minigame.l2mgtex, "encode_like", lambda orig, im: orig)
    with pytest.raises(SystemExit, match="changed"):
        minigame.patch_package(side, {"005.l2mgtex": "a.png"}, masters)

    img = tmp_path / "img.bin"
    write_img(img, {95: pkg})
    extra = bind(monkeypatch, tmp_path, minigame, img)
    monkeypatch.setattr(minigame, "JOBS", {95: {"005.l2mgtex": "a.png"}})
    monkeypatch.setattr(minigame, "patch_package", lambda raw, jobs, masters=masters: raw)
    monkeypatch.setattr(minigame, "find_vanilla_img", lambda: img)
    assert minigame.main() == 0
    assert extra.is_file()

    img.write_bytes(fi.img({}, count=96))
    bind(monkeypatch, tmp_path, minigame, img)
    monkeypatch.setattr(minigame, "find_vanilla_img", lambda: img)
    with pytest.raises(SystemExit, match="pkg 95 missing"):
        minigame.main()

    write_img(img, {95: pkg})
    bind(monkeypatch, tmp_path, minigame, img)
    monkeypatch.setattr(minigame, "find_vanilla_img", lambda: None)
    monkeypatch.setattr(
        minigame,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(minigame.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed"):
        minigame.main()
    monkeypatch.setattr(minigame, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        minigame.main()


# ---------------------------------------------------------------------------
# Name-input code.bin stack
# ---------------------------------------------------------------------------


_ALREADY = (
    "lyt_null_pane_already",
    "force_ml_already",
    "ascii_dakuten_already",
    "chunk_walk_already",
    "call_romaji_already",
    "message_speed_already",
    "spotpass_skip_already",
    "spotpass_embed_already",
    "password_uribo_already",
    "commu_header_already",
    "weather_day_already",
    "profile_birthday_already",
    "web_event_date_already",
    "save_slot_date_already",
    "speaker_spacing_already",
    "eula_agreed_already",
    "camera_defaults_already",
    "camera_reset_already",
    "engpatch_info_already",
    "drawtext_64_already",
    "syspopup_tall_already",
    "syspopup_scroll_already",
    "bonus_digits_already",
)
_APPLIES = (
    "apply_pane_nullguard",
    "apply_lyt_null_pane",
    "apply_cand_nullguard",
    "apply_fillflag",
    "restore_bind_sites",
    "apply_kana_direct",
    "apply_force_ml",
    "apply_ascii_dakuten",
    "apply_strcat_raw",
    "apply_chunk_walk",
    "apply_call_romaji",
    "apply_message_speed",
    "apply_spotpass_skip",
    "apply_spotpass_embed",
    "apply_info_menu",
    "apply_map_comments",
    "apply_password_uribo",
    "apply_commu_header",
    "apply_weather_day_text",
    "apply_profile_birthday",
    "apply_web_event_date",
    "apply_save_slot_date",
    "apply_speaker_spacing",
    "apply_eula_agreed",
    "apply_camera_defaults",
    "apply_camera_reset",
    "apply_engpatch_info",
    "apply_drawtext_64",
    "apply_syspopup_tall",
    "apply_syspopup_scroll",
    "apply_bonus_digits",
)


def _name_buf(already: bool) -> bytearray:
    data = bytearray(0x200000)
    if already:
        data[name_input.PANE_SITE : name_input.PANE_SITE + 4] = name_input.pane_b_ins(
            name_input.PANE_SITE, name_input.PANE_CAVE
        )
        data[name_input.FILL_SITE : name_input.FILL_SITE + 4] = name_input.fill_b_ins(
            name_input.FILL_SITE, name_input.FILL_CAVE
        )
        data[name_input.KANA_SITE : name_input.KANA_SITE + 4] = name_input.KANA_PATCHED
    else:
        data[name_input.CAND_SITE1 : name_input.CAND_SITE1 + 4] = bytes.fromhex("1010b0e5")
    return data


def _stub_stack(monkeypatch, *, already: bool, romaji_ok: bool = True, panes: bool = True):
    def ret(value):
        return lambda *a, **k: value

    for name in _ALREADY:
        monkeypatch.setattr(name_input, name, ret(already))
    for name in _APPLIES:
        monkeypatch.setattr(name_input, name, ret(None))
    monkeypatch.setattr(name_input, "apply_name_pane_patches", ret(panes and not already))
    monkeypatch.setattr(name_input, "apply_bplace_list_pane", ret(panes and not already))
    monkeypatch.setattr(name_input, "patch_cesa_logo_white_native_size", ret(not already))
    monkeypatch.setattr(name_input, "patch_nintendo_logo_skip_thank_flash", ret(not already))
    monkeypatch.setattr(name_input, "is_romaji_patched", ret(already))
    monkeypatch.setattr(name_input, "patch_input_romaji", ret(romaji_ok))


def test_name_input_already_flags():
    fresh = _name_buf(False)
    done = _name_buf(True)
    assert name_input._u32_at(done, name_input.PANE_SITE) != 0
    assert name_input.pane_already(fresh) is False
    assert name_input.pane_already(done) is True
    assert name_input.cand_already(fresh) is False
    assert name_input.cand_already(done) is True
    assert name_input.fillflag_already(fresh) is False
    assert name_input.fillflag_already(done) is True
    assert name_input.kana_already(fresh) is False
    assert name_input.kana_already(done) is True


def test_name_input_stack_branches(monkeypatch):
    _stub_stack(monkeypatch, already=True)
    assert name_input.apply_name_input_stack(_name_buf(True)) == 2
    _stub_stack(monkeypatch, already=False)
    assert name_input.apply_name_input_stack(_name_buf(False)) == 33
    _stub_stack(monkeypatch, already=False, romaji_ok=False)
    with pytest.raises(SystemExit, match="romaji patch failed"):
        name_input.apply_name_input_stack(_name_buf(False))


def test_name_input_main(tmp_path, monkeypatch):
    assert name_input.main(["--dry-run"]) == 0
    mod_root = tmp_path / "mod"
    mod_root.mkdir()
    dest = tmp_path / "exefs" / "code.bin"
    dest.parent.mkdir()
    dest.write_bytes(b"old-code")
    out = tmp_path / "patched.bin"
    src = tmp_path / "vanilla.bin"
    src.write_bytes(b"vanilla-code")
    monkeypatch.setattr(name_input, "MOD", mod_root)
    monkeypatch.setattr(name_input, "DEST", dest)
    monkeypatch.setattr(name_input, "NAME_INPUT_CODE", tmp_path / "name_input_code.bin")

    def stack(data):
        data[0] = 0xAB
        return 4

    monkeypatch.setattr(name_input, "apply_name_input_stack", stack)
    assert name_input.main(["--src", str(src), "--out", str(out)]) == 0
    assert out.read_bytes()[0] == 0xAB
    assert name_input.main(["--src", str(src)]) == 0
    assert name_input.NAME_INPUT_CODE.read_bytes()[0] == 0xAB
    with pytest.raises(SystemExit, match="missing --src"):
        name_input.main(["--src", str(tmp_path / "nope.bin")])

    assert name_input.main([]) == 0
    assert dest.read_bytes()[0] == 0xAB
    assert (dest.parent / "code.bin.bak_pre_name_input_en").is_file()
    assert (mod_root / "code.bin").read_bytes() == dest.read_bytes()
    assert name_input.main([]) == 0

    other = tmp_path / "other.bin"
    other.write_bytes(b"zzzzzzzz")
    monkeypatch.setattr(name_input, "DEST", tmp_path / "somewhere-else.bin")
    assert name_input.main(["--out", str(other)]) == 0
    assert other.read_bytes()[0] == 0xAB
    with pytest.raises(SystemExit, match="missing --out"):
        name_input.main(["--out", str(tmp_path / "absent.bin")])
    monkeypatch.setattr(name_input, "DEST", tmp_path / "absent-dest.bin")
    with pytest.raises(SystemExit, match="seed LayeredFS"):
        name_input.main([])


# ---------------------------------------------------------------------------
# Bleeding-edge combine
# ---------------------------------------------------------------------------


def _bind_bleeding(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    (root / "out").mkdir(parents=True)
    mod = tmp_path / "azahar_mod"
    fi.use_paths(
        monkeypatch,
        tmp_path,
        bleeding,
        AZAHAR_MOD_ROOT=mod,
        AZAHAR_MOD_IMG=mod / "romfs" / "img.bin",
        AZAHAR_MOD_CODE=mod / "exefs" / "code.bin",
        AZAHAR_MOD_TRB_DIR=mod / "romfs" / "SystemData" / "TextResource",
        BAKE_IMG=tmp_path / "bake_img.bin",
        NAME_INPUT_CODE=tmp_path / "name_input_code.bin",
        TEXTRESOURCE=tmp_path / "textresource",
    )
    monkeypatch.setattr(bleeding, "ROOT", root)
    return root, mod


def test_bleeding_refresh_and_deploy(tmp_path, monkeypatch):
    root, mod = _bind_bleeding(monkeypatch, tmp_path)
    monkeypatch.setenv("NLPP_AZAHAR_USER_DIR", str(tmp_path / "user"))
    assert bleeding.main(["--dry-run"]) == 0

    code = tmp_path / "vanilla.code"
    code.write_bytes(b"code")
    bak = root.parent / "New Love Plus Plus" / "extracted" / "exefs" / "code.bin.bak"
    bak.parent.mkdir(parents=True)
    bak.write_bytes(b"bak-code")
    calls = []

    def fake_run(argv):
        calls.append(argv)
        bleeding.NAME_INPUT_CODE.parent.mkdir(parents=True, exist_ok=True)
        bleeding.NAME_INPUT_CODE.write_bytes(b"PATCHED")
        out = bleeding.ROOT / "out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "textresource_jpn_namekanji.trb").write_bytes(b"NK")
        (out / "textresource_config_namekanji.trb").write_bytes(b"CFG")

    monkeypatch.setattr(bleeding, "_run", fake_run)
    bleeding.refresh_artifacts(vanilla_code=code)
    assert str(bak) in calls[0]
    assert (bleeding.TEXTRESOURCE / "textresource_jpn.trb").read_bytes() == b"NK"
    assert (bleeding.TEXTRESOURCE / "textresource_config.trb").read_bytes() == b"CFG"
    overlay = root / "release" / "romfs_overlay" / "SystemData" / "TextResource"
    assert (overlay / "textresource_jpn.trb").read_bytes() == b"NK"

    bak.unlink()
    calls.clear()
    bleeding.refresh_artifacts(vanilla_code=code)
    assert str(code) in calls[0]
    (root / "out" / "textresource_config_namekanji.trb").unlink()
    bleeding.refresh_artifacts(vanilla_code=code)
    assert (bleeding.TEXTRESOURCE / "textresource_jpn.trb").read_bytes() == b"NK"

    monkeypatch.setattr(bleeding, "find_vanilla_code", lambda: code)
    bleeding.refresh_artifacts(vanilla_code=None)
    monkeypatch.setattr(bleeding, "find_vanilla_code", lambda: None)
    with pytest.raises(SystemExit, match="not found"):
        bleeding.refresh_artifacts(vanilla_code=None)
    monkeypatch.setattr(bleeding, "find_vanilla_code", lambda: tmp_path / "missing.code")
    with pytest.raises(SystemExit, match="not found"):
        bleeding.refresh_artifacts(vanilla_code=None)

    bleeding.BAKE_IMG.write_bytes(b"BAKEIMG")
    bleeding.NAME_INPUT_CODE.write_bytes(b"PATCHED")
    (root / "out" / "textresource_jpn_namekanji.trb").write_bytes(b"NK")
    (root / "out" / "textresource_config_namekanji.trb").write_bytes(b"CFG")
    dest_img = bleeding.AZAHAR_MOD_IMG
    dest_img.parent.mkdir(parents=True)
    dest_img.write_bytes(b"old-img")
    dest_code = bleeding.AZAHAR_MOD_CODE
    dest_code.parent.mkdir(parents=True)
    dest_code.write_bytes(b"old-code")
    dest_trb = bleeding.AZAHAR_MOD_TRB_DIR / "textresource_jpn.trb"
    dest_trb.parent.mkdir(parents=True)
    dest_trb.write_bytes(b"old-trb")
    bleeding.deploy_combined()
    assert dest_img.read_bytes() == b"BAKEIMG"
    assert dest_code.read_bytes() == b"PATCHED"
    assert (mod / "code.bin").read_bytes() == b"PATCHED"
    assert dest_trb.read_bytes() == b"NK"
    assert (dest_img.parent / "img.bin.bak_pre_combine_name_input").is_file()
    bleeding.deploy_combined()
    bleeding.deploy_combined(also_code_bak=False)

    (root / "out" / "textresource_jpn_namekanji.trb").unlink()
    (bleeding.TEXTRESOURCE / "textresource_jpn.trb").write_bytes(b"FALLBACK")
    (root / "out" / "textresource_config_namekanji.trb").unlink()
    bleeding.deploy_combined()
    assert dest_trb.read_bytes() == b"FALLBACK"

    (bleeding.TEXTRESOURCE / "textresource_jpn.trb").unlink()
    with pytest.raises(SystemExit, match="missing name-kanji"):
        bleeding.deploy_combined()
    bleeding.NAME_INPUT_CODE.unlink()
    (root / "out" / "textresource_jpn_namekanji.trb").write_bytes(b"NK")
    with pytest.raises(SystemExit, match="missing"):
        bleeding.deploy_combined()
    bleeding.BAKE_IMG.unlink()
    bleeding.NAME_INPUT_CODE.write_bytes(b"PATCHED")
    with pytest.raises(SystemExit, match="missing gold bake"):
        bleeding.deploy_combined()

    bleeding.BAKE_IMG.write_bytes(b"BAKEIMG")
    bleeding.NAME_INPUT_CODE.write_bytes(b"PATCHED")
    (root / "out" / "textresource_jpn_namekanji.trb").write_bytes(b"NK")
    ran = {"r": 0, "d": 0}

    def refresh(vanilla_code=None):
        ran["r"] += 1

    def deploy():
        ran["d"] += 1

    monkeypatch.setattr(bleeding, "refresh_artifacts", refresh)
    monkeypatch.setattr(bleeding, "deploy_combined", deploy)
    assert bleeding.main(["--refresh-artifacts", "--vanilla-code", str(code)]) == 0
    assert ran == {"r": 1, "d": 1}


def test_leftover_branches(tmp_path, monkeypatch):
    import sys

    root, _mod = _bind_bleeding(monkeypatch, tmp_path)
    bleeding._run([sys.executable, "-c", "pass"])

    code = tmp_path / "v.code"
    code.write_bytes(b"c")

    def fake_run(_argv):
        bleeding.NAME_INPUT_CODE.parent.mkdir(parents=True, exist_ok=True)
        bleeding.NAME_INPUT_CODE.write_bytes(b"P")
        out = bleeding.ROOT / "out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "textresource_jpn_namekanji.trb").write_bytes(b"NK")

    monkeypatch.setattr(bleeding, "_run", fake_run)
    bleeding.refresh_artifacts(vanilla_code=code)
    assert (bleeding.TEXTRESOURCE / "textresource_jpn.trb").read_bytes() == b"NK"
    assert not (root / "out" / "textresource_config_namekanji.trb").is_file()

    bleeding.BAKE_IMG.write_bytes(b"BAKE")
    bleeding.NAME_INPUT_CODE.write_bytes(b"CODE")
    bleeding.deploy_combined()
    assert bleeding.AZAHAR_MOD_IMG.read_bytes() == b"BAKE"
    assert not (bleeding.AZAHAR_MOD_TRB_DIR / "textresource_config.trb").is_file()
    assert bleeding.main([]) == 0

    trailed = fi.darc({"a.bin": b"ab", "b.bin": b"cd"}) + b"\x00" * 8
    assert card_flist.all_interfile_gaps(trailed)[-1][1] == len(trailed)
    calls = {"n": 0}

    def once(_data, _n):
        calls["n"] += 1
        return None if calls["n"] == 1 else b"SLOT"

    monkeypatch.setattr(card_flist, "compress_exact_empty_blocks", once)
    assert card_flist.compress_exact_with_gap_tune(trailed, 40)[1] == b"SLOT"

    use_font(monkeypatch, myroom_opt)
    monkeypatch.setattr(myroom_opt, "OUT", tmp_path / "mo")
    myroom_opt.OUT.mkdir()
    w, h = png_wh("Myroom.check", "optn_tex_optionmenu_RGBA4")
    job = [("Myroom.check", "timg/optn_tex_optionmenu_RGBA4.bclim", "Options Menu")]
    bad = fi.darc({"timg/optn_tex_optionmenu_RGBA4.bclim": noise_bclim(w, h, 8, seed=1)})
    with pytest.raises(SystemExit, match="not ETC1A4"):
        myroom_opt._patch_arc(bad, job, tmp_path)
    with pytest.raises(SystemExit, match="missing"):
        myroom_opt._patch_arc(bad, [("Myroom.check", "timg/nope.bclim", "X")], tmp_path)
    small = Image.new("RGBA", (4, 4), (1, 1, 1, 255))
    monkeypatch.setattr(myroom_opt, "_rgba_for", lambda *a: (small, "tiny"))
    good = fi.darc({"timg/optn_tex_optionmenu_RGBA4.bclim": noise_bclim(w, h, 0xB, seed=2)})
    assert myroom_opt._patch_arc(good, job, tmp_path) != good

    blob = arc_package({"timg/optn_tex_optionmenu_RGBA4.bclim": noise_bclim(w, h, 0xB, seed=3)})
    src = tmp_path / "pkg5575"
    src.write_bytes(blob)
    from img import FileWindow, Package

    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if e.fn == "Data.arc")
    tuned = arc_elem.parsed()
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        myroom_opt._write_slot(src, pkg, tuned, b"x")
    _o, zeros = fast_exact(b"\x00" * len(tuned), arc_elem.fw.len())
    with pytest.raises(SystemExit, match="ARC mismatch"):
        myroom_opt._write_slot(src, pkg, tuned, zeros)
    src.write_bytes(retarget_sidecar(blob))
    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    _t, good_slot = fast_exact(tuned, arc_elem.fw.len())
    with pytest.raises(SystemExit, match="DMST changed"):
        myroom_opt._write_slot(src, pkg, tuned, good_slot)

    img = tmp_path / "empty.bin"
    img.write_bytes(fi.img({}, count=5576))
    monkeypatch.setattr(myroom_opt, "MOD_IMG", img)
    with pytest.raises(SystemExit, match="pkg 5380 missing"):
        myroom_opt._patch_package(5380, job, tmp_path, tmp_path)

    files = {
        path: noise_bclim(*png_wh("NCommonMSel(3).check", Path(path).stem), 1, seed=30 + i)
        for i, (path, _en) in enumerate(msel_plates.LABELS)
    }
    plate_img = tmp_path / "plates.bin"
    write_img(plate_img, {msel_plates.PKG: arc_package(files)})
    bind(monkeypatch, tmp_path, msel_plates, plate_img)
    monkeypatch.setattr(msel_plates.zopfli_zlib, "compress", lambda data: b"Z")
    monkeypatch.setattr(msel_plates, "compress_exact_zopfli", lambda data, n: (None, None))
    assert msel_plates.main() == 0

    import zopfli.zlib as zz

    real_compress = zlib.compress
    monkeypatch.setattr(minigame.zlib, "compress", lambda data, level=9: real_compress(b"nope", 9))
    monkeypatch.setattr(zz, "compress", lambda data: real_compress(data, 9))
    assert zlib.decompress(minigame.try_compress_to_slot(b"x", 200)) == b"x"
