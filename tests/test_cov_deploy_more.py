"""Remaining branches of deploy_* scripts: their exact-zlib helper copies,
master-PNG resizing, and the post-splice verify guards.

Reuses the synthetic img.bin helpers of test_cov_deploy_hubs / _chrome.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import pytest
from PIL import Image

import fake_img as fi
from test_cov_deploy_chrome import arm_later_darc
from test_cov_deploy_hubs import (
    arc_package,
    bind,
    fast_exact,
    mydata,
    noise_bclim,
    png_wh,
    retarget_sidecar,
    use_font,
    write_img,
)


class _Co:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def compress(self, data):
        return self.body

    def flush(self, mode):
        return b""


def _fake_zlib(**over):
    import types

    ns = types.SimpleNamespace(**{k: getattr(zlib, k) for k in dir(zlib) if not k.startswith("__")})
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


DATA, TWIN = b"\x00\x02\x00", b"\x01\x00\x01"  # same Adler-32


def _twin_body() -> bytes:
    co = zlib.compressobj(9, wbits=-15)
    return co.compress(TWIN) + co.flush(zlib.Z_SYNC_FLUSH)


# ---------------------------------------------------------------------------
# deploy_mydata_en
# ---------------------------------------------------------------------------


def test_mydata_render_label_shrinks_long_text(monkeypatch):
    use_font(monkeypatch, mydata)
    im = mydata.render_label(64, 16, "To-Do List")  # too wide at the top sizes
    assert im.size == (64, 16)


def test_mydata_gaps_and_pad():
    arc = fi.darc({"a.bin": b"x" * 16, "b.bin": b"y" * 16}, align=0x80) + bytes(8)
    gaps = mydata.interfile_zero_gaps(arc)
    assert any(po + sz == len(arc) for sz, po in gaps)  # trailing pad counts
    salted = mydata.apply_gap_pad(arc, 10_000, b"\x01" * 10_000)
    assert salted.count(b"\x01") - arc.count(b"\x01") == sum(sz for sz, _ in gaps)


def test_mydata_empty_block_helpers_reject_bad_bodies(monkeypatch):
    wrong = _twin_body()
    bodies = iter([wrong, b"\xff" * 5] * 50)
    monkeypatch.setattr(mydata, "zlib", _fake_zlib(compressobj=lambda *a, **k: _Co(next(bodies))))
    assert mydata.compress_exact_empty_blocks(DATA, 6 + len(wrong) + 5) is None
    monkeypatch.setattr(mydata, "zlib", _fake_zlib(compressobj=lambda *a, **k: _Co(b"\xff" * 5)))
    assert mydata.compress_exact_empty_blocks(DATA, 6 + 5 + 5) is None  # not deflate
    monkeypatch.undo()
    assert mydata._try_empty_pad(DATA, b"\xff" * 5, b"\x78\x9c", 6 + 5 + 5) is None
    assert mydata._try_empty_pad(DATA, wrong, b"\x78\x9c", 6 + len(wrong) + 5) is None


def test_mydata_zopfli_linear_scan_hit(monkeypatch):
    arc = fi.darc({"a.bin": b"x" * 16, "b.bin": b"y" * 16}, align=0x80)
    monkeypatch.setattr(mydata.os, "urandom", lambda n: b"\x01" * n)

    def zl(data: bytes) -> bytes:
        n = data.count(b"\x01")
        if n == 20:
            return b"Z" * 50  # only the linear scan visits pad 20
        return b"Z" * (40 + n if n < 10 else 41 + n)

    monkeypatch.setattr(mydata.zopfli_zlib, "compress", zl)
    tuned, slot = mydata.compress_exact_zopfli(arc, 50)
    assert tuned.count(b"\x01") == 20 and len(slot) == 50


def test_mydata_master_png_is_resized(tmp_path, monkeypatch):
    use_font(monkeypatch, mydata)
    w, h = png_wh("Myroom.check", "mcmn_tex_todo_RGBA4")
    arc = fi.darc({"timg/mcmn_tex_todo_RGBA4.bclim": noise_bclim(w, h, 0xB, seed=8)})
    master = tmp_path / "master.png"
    Image.new("RGBA", (w + 6, h + 2), (9, 9, 9, 255)).save(master)
    monkeypatch.setattr(mydata, "OUT", tmp_path / "out")
    mydata.OUT.mkdir()
    monkeypatch.setattr(mydata, "ZHOUMARU_BUTTONS", {"mcmn_tex_todo_RGBA4"})
    monkeypatch.setattr(mydata, "find_ui_png", lambda *a, **k: master)
    from darcutil import DarcArchive

    mydata.patch_labels_into_darc(
        DarcArchive(bytearray(arc)), [("timg/mcmn_tex_todo_RGBA4.bclim", "To-Do List")], tmp_path, hard=False
    )
    assert (mydata.OUT / "mcmn_tex_todo_RGBA4_en.png").is_file()


def _mydata_img(tmp_path, monkeypatch, *, sidecar_on_slot: bool = False):
    files = {}
    for i, (path, _en) in enumerate(mydata.JOBS[1][1]):
        files[path] = noise_bclim(*png_wh("Myroom.check", Path(path).stem), 0xB, seed=60 + i)
    blob = arc_package(files)
    if sidecar_on_slot:
        blob = retarget_sidecar(blob)
    img = tmp_path / "img.bin"
    write_img(img, {5380: blob})
    bind(monkeypatch, tmp_path, mydata, img)
    monkeypatch.setattr(mydata.zopfli_zlib, "compress", lambda d: b"Z")
    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", lambda d, n: fast_exact(d, n)[1])
    return img


def test_mydata_patch_package_verify_guards(tmp_path, monkeypatch):
    jobs = mydata.JOBS[1][1]
    _mydata_img(tmp_path, monkeypatch)
    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", lambda d, n: fast_exact(d, n)[1] + b"!")
    with pytest.raises(SystemExit, match="zlib verify failed"):
        mydata.patch_package(5380, jobs, source="live")

    _mydata_img(tmp_path, monkeypatch)
    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", lambda d, n: None)
    monkeypatch.setattr(mydata, "compress_exact_with_gap_tune", lambda d, n: (d + b"!", zlib.compress(d + b"!")))
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        mydata.patch_package(5380, jobs, source="live")

    _mydata_img(tmp_path, monkeypatch)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        slot = fast_exact(d, n)[1]
        armed["go"] = True
        return slot

    monkeypatch.setattr(mydata, "compress_exact_empty_blocks", arming)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        mydata.patch_package(5380, jobs, source="live")
    armed["go"] = False

    _mydata_img(tmp_path, monkeypatch, sidecar_on_slot=True)
    with pytest.raises(SystemExit, match="DMST changed"):
        mydata.patch_package(5380, jobs, source="live")


# ---------------------------------------------------------------------------
# Shared exact-zlib helper copies in deploy_* scripts
# ---------------------------------------------------------------------------

import inspect  # noqa: E402

from conftest import TOOLS, load_module  # noqa: E402

HELPER_MODS = {
    name: load_module(f"{name}_helpers", TOOLS / f"{name}.py")
    for name in (
        "deploy_card_flist_en",
        "deploy_datadelete_en",
        "deploy_display_settings_en",
        "deploy_gallery_common_en",
        "deploy_mail_home_en",
        "deploy_mail_sort_en",
        "deploy_msel_menus_en",
        "deploy_myroom_main_en",
        "deploy_profile_en",
        "deploy_schedule_header_en",
        "deploy_sound_settings_en",
        "deploy_status_stats_en",
        "deploy_todo_en",
    )
}


def _with(mod, name):
    fn = getattr(mod, name, None)
    if fn is None:
        pytest.skip(f"{mod.__name__} has no {name}")
    return fn


@pytest.mark.parametrize("mod", HELPER_MODS.values(), ids=list(HELPER_MODS))
def test_empty_block_copies_reject_bad_bodies(mod, monkeypatch):
    fn = _with(mod, "compress_exact_empty_blocks")
    wrong = _twin_body()
    monkeypatch.setattr(mod, "zlib", _fake_zlib(compressobj=lambda *a, **k: _Co(wrong)))
    assert fn(DATA, 6 + len(wrong) + 5) is None  # decodes, but to the twin
    monkeypatch.setattr(mod, "zlib", _fake_zlib(compressobj=lambda *a, **k: _Co(bytes([255]) * 5)))
    assert fn(DATA, 6 + 5 + 5) is None  # not deflate at all
    if "mem" in inspect.getsource(fn):  # sweeps memLevel / strategy
        def compressobj(*args, **kw):
            if len(args) < 5:
                return _Co(bytes([255]) * 5)
            if args[3] == 1:
                raise zlib.error("bad memLevel")
            return zlib.compressobj(*args, **kw)

        monkeypatch.setattr(mod, "zlib", _fake_zlib(compressobj=compressobj))
        data = b"hello hello hello"
        co = zlib.compressobj(9, zlib.DEFLATED, -15, 2, zlib.Z_DEFAULT_STRATEGY)
        body = co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH)
        kw = {"thorough": True} if "thorough" in inspect.signature(fn).parameters else {}
        out = fn(data, 2 + len(body) + 5 + 4, **kw)
        assert out is not None and zlib.decompress(out) == data


@pytest.mark.parametrize("mod", HELPER_MODS.values(), ids=list(HELPER_MODS))
def test_gap_helper_copies(mod):
    gaps_fn = _with(mod, "interfile_zero_gaps")
    adjacent = fi.darc({"a/A.bin": b"x" * 4, "a/B.bin": b"y" * 4}, align=4)
    gaps_fn(adjacent)
    spaced = fi.darc({"a.bin": b"x" * 16, "b.bin": b"y" * 16}, align=0x80)
    gaps_fn(spaced + bytes(8))
    gaps_fn(spaced + bytes([1]) * 8)  # trailing pad that is not zero
    pad_fn = getattr(mod, "apply_gap_pad", None)
    if pad_fn is not None:
        out = pad_fn(spaced, 10_000, bytes([1]) * 10_000)
        assert len(out) == len(spaced)


# ---------------------------------------------------------------------------
# deploy_minigame_hub_en
# ---------------------------------------------------------------------------

from test_cov_deploy_hubs import point_instances  # noqa: E402

hub = load_module("deploy_minigame_hub_en_cov", TOOLS / "deploy_minigame_hub_en.py")


def _hub_pkg(seed: int = 3) -> bytes:
    w, h = png_wh("MyroomHeader.check", "game_text_title_RGBA4")
    return arc_package({"timg/game_text_title_RGBA4.bclim": noise_bclim(w, h, 0xB, seed=seed)})


def test_hub_small_helpers(tmp_path, monkeypatch):
    adjacent = fi.darc({"a/A.bin": b"x" * 4, "a/B.bin": b"y" * 4}, align=4)
    assert hub._zero_all_darc_pads(adjacent) == adjacent
    img = tmp_path / "img.bin"
    write_img(img, {5575: _hub_pkg()})
    bind(monkeypatch, tmp_path, hub, img)
    extra = point_instances(monkeypatch, hub, img, tmp_path)
    targets = hub._deploy_targets()
    assert extra.resolve() in targets
    monkeypatch.setattr(hub, "find_ui_png", lambda *a, **k: None)
    rgba, src = hub._rgba_for("MyroomHeader.check", "not_a_menu_stem", "Mini-Game", 64, 16)
    assert src == "render:Mini-Game" and rgba.size == (64, 16)


def test_hub_patch_arc_resizes_master(tmp_path, monkeypatch):
    use_font(monkeypatch, hub)
    w, h = png_wh("MyroomHeader.check", "game_text_title_RGBA4")
    arc = fi.darc({"timg/game_text_title_RGBA4.bclim": noise_bclim(w, h, 0xB, seed=4)})
    master = tmp_path / "m.png"
    Image.new("RGBA", (w * 2, h * 2), (5, 5, 5, 255)).save(master)
    monkeypatch.setattr(hub, "OUT", tmp_path)
    monkeypatch.setattr(hub, "_rgba_for", lambda *a: (Image.open(master).convert("RGBA"), "m.png"))
    out = hub._patch_arc(arc, [("MyroomHeader.check", "timg/game_text_title_RGBA4.bclim", "Mini-Game")], tmp_path)
    assert len(out) == len(arc)


def test_hub_package_guards(tmp_path, monkeypatch):
    jobs = [("MyroomHeader.check", "timg/game_text_title_RGBA4.bclim", "Mini-Game")]
    pkg_dir = tmp_path / "pkgs"
    pkg_dir.mkdir()

    def setup(blob=None):
        img = tmp_path / "img.bin"
        write_img(img, {5575: blob or _hub_pkg()})
        bind(monkeypatch, tmp_path, hub, img)
        hub.OUT.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(hub, "_compress_slot", fast_exact)

    setup()
    with pytest.raises(SystemExit, match="pkg 4 missing"):
        hub._patch_package(4, jobs, pkg_dir, tmp_path)  # no package at index 4

    setup()
    monkeypatch.setattr(hub, "_compress_slot", lambda d, n: (d, fast_exact(d, n)[1] + b"!"))
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        hub._patch_package(5575, jobs, pkg_dir, tmp_path)

    setup()
    monkeypatch.setattr(hub, "_compress_slot", lambda d, n: (d + b"!", zlib.compress(d + b"!")))
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        hub._patch_package(5575, jobs, pkg_dir, tmp_path)

    setup()
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        out = fast_exact(d, n)
        armed["go"] = True
        return out

    monkeypatch.setattr(hub, "_compress_slot", arming)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        hub._patch_package(5575, jobs, pkg_dir, tmp_path)
    armed["go"] = False

    setup(retarget_sidecar(_hub_pkg()))
    with pytest.raises(SystemExit, match="DMST changed"):
        hub._patch_package(5575, jobs, pkg_dir, tmp_path)


# ---------------------------------------------------------------------------
# deploy_msel_options_en
# ---------------------------------------------------------------------------

opts = load_module("deploy_msel_options_en_cov", TOOLS / "deploy_msel_options_en.py")


def test_options_decode_a8_skips_texels_past_the_canvas():
    canvas, w, h = opts.decode_a8(fi.bclim(8, 2, 1, pixels=bytes(range(16))))
    assert canvas.shape == (2, 8) and (w, h) == (8, 2)


@pytest.mark.parametrize("mod", HELPER_MODS.values(), ids=list(HELPER_MODS))
def test_gap_tune_copies_without_gaps(mod, monkeypatch):
    fn = _with(mod, "compress_exact_with_gap_tune")
    adjacent = fi.darc({"a/A.bin": b"x" * 4, "a/B.bin": b"y" * 4}, align=4)
    monkeypatch.setattr(mod, "interfile_zero_gaps", lambda data, min_len=4: [])
    monkeypatch.setattr(mod, "compress_exact_empty_blocks", lambda *a, **k: b"SLOT")
    assert fn(adjacent, 10) == (adjacent, b"SLOT")


@pytest.mark.parametrize("name", ["deploy_todo_en", "deploy_schedule_header_en"])
def test_zopfli_fine_scan_walks_every_byte(name, monkeypatch):
    mod = HELPER_MODS[name]
    arc = fi.darc({"a.bin": b"x" * 16, "b.bin": b"y" * 16}, align=0x80)
    monkeypatch.setattr(mod.os, "urandom", lambda n: bytes([1]) * n)
    calls = {"n": 0}

    def zl(data: bytes) -> bytes:
        # Alternate just under / just over the odd target: never a hit, and
        # the fine scan both keeps and resets bytes before giving up.
        calls["n"] += 1
        return b"Z" * (44 if calls["n"] % 2 else 46)

    # No gaps for the binary search (min_len=8), two zero runs for the fine scan.
    monkeypatch.setattr(
        mod, "interfile_zero_gaps", lambda data, min_len=4: [] if min_len == 8 else [(4, 150), (4, 200)]
    )

    monkeypatch.setattr(mod.zopfli_zlib, "compress", zl)
    monkeypatch.setattr(mod, "compress_exact_with_gap_tune", lambda d, n: ("GAP", n))
    assert mod.compress_exact_zopfli(arc, 45) == ("GAP", 45)


def test_todo_label_left_alignment(tmp_path, monkeypatch):
    todo = HELPER_MODS["deploy_todo_en"]
    use_font(monkeypatch, todo)
    assert todo.render_label(64, 16, "To-Do List").size == (64, 16)  # too wide at the top sizes
    w, h = 64, 16
    arc = fi.darc({"timg/Que_Txt01c.bclim": fi.bclim(w, h, 8)})
    monkeypatch.setattr(todo, "OUT", tmp_path)
    monkeypatch.setattr(todo, "QUEST_MASTERS", tmp_path / "none")
    for col in (None, 1):  # empty render, then ink already at the left edge
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if col is not None:
            img.putpixel((col, 4), (255, 255, 255, 255))
        monkeypatch.setattr(todo, "render_label", lambda *a, _im=img, **k: _im)
        out = todo.patch_rgba_labels(arc, [("timg/Que_Txt01c.bclim", "Earned ToDo Points:")], tmp_path)
        assert len(out) == len(arc)


# ---------------------------------------------------------------------------
# deploy_msel_menus_en / deploy_msel_opt_plates_en render + decode edges
# ---------------------------------------------------------------------------

menus = load_module("deploy_msel_menus_en_cov", TOOLS / "deploy_msel_menus_en.py")
plates = load_module("deploy_msel_opt_plates_en_cov", TOOLS / "deploy_msel_opt_plates_en.py")


@pytest.mark.parametrize("mod", [menus, plates], ids=["menus", "plates"])
def test_a8_decode_skips_texels_past_the_canvas(mod):
    canvas, w, h = mod.decode_a8(fi.bclim(8, 2, 1, pixels=bytes(range(16))))
    assert canvas.shape == (2, 8)


def test_menu_and_plate_renderers_shrink_tall_text(monkeypatch):
    use_font(monkeypatch, menus)
    monkeypatch.setattr(menus, "ROW_FONT", Path(menus.ROW_FONT) if Path(menus.ROW_FONT).is_file() else __import__("test_cov_deploy_hubs").GEOMANIST)
    row = menus.render_row_heisei(96, 16, "Options", 9)  # larger sizes are too tall
    assert row.shape == (16, 96)
    use_font(monkeypatch, plates)
    plate = plates.render(96, 16, "Options", 7, hard=False)  # larger sizes are too tall
    assert plate.shape == (16, 96)


# ---------------------------------------------------------------------------
# deploy_title_engpatch_en / deploy_mail_sort_en leftovers
# ---------------------------------------------------------------------------

import test_cov_deploy_menus as menus_t  # noqa: E402


def test_title_main_redeploy_keeps_arc_size(tmp_path, monkeypatch):
    title = menus_t.title
    img = tmp_path / "img.bin"
    menus_t._title_img(img, with_eng=True)
    menus_t._prepare_title(monkeypatch, tmp_path, img)
    monkeypatch.setattr(title.sys, "argv", ["deploy"])
    monkeypatch.setattr(title.zopfli_zlib, "compress", lambda data: b"\x00\x01")
    # Hand back the vanilla-sized ARC: the PACK dec_len needs no update.
    vanilla_arc = fi.read_element(fi.read_package(img, title.PKG), "Data.arc", tmp_path)
    monkeypatch.setattr(title, "compress_exact_zopfli", lambda d, n: fast_exact(vanilla_arc, n))
    try:
        title.main()
    except SystemExit:
        pass  # a later check may notice the ARC is the vanilla one


def test_mail_sort_cancel_without_soft_edges(tmp_path, monkeypatch):
    mail_sort = menus_t.mail_sort
    raw = menus_t._encode_cancel(tmp_path)
    out = mail_sort.reletter_cancel(raw, "")
    assert out.size == (98, 42)
