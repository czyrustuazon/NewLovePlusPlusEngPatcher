"""Line/branch coverage for softkey and related deploy_* modules.

CI has no vanilla img.bin. Packages are synthetic (tests/fake_img.py).
Zopfli exact-slot search is stubbed; local empty-block helpers run for real.
"""

from __future__ import annotations

import random
import shutil
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import fake_img as fi
from conftest import ROOT, TOOLS, load_module
from pack_images import PackError

confirm = load_module("deploy_confirm_btn_en", TOOLS / "deploy_confirm_btn_en.py")
quit_sk = load_module("deploy_softkey_quit_en", TOOLS / "deploy_softkey_quit_en.py")
back = load_module("deploy_softkey_back_next_en", TOOLS / "deploy_softkey_back_next_en.py")
defaults = load_module("deploy_softkey_defaults_en", TOOLS / "deploy_softkey_defaults_en.py")
password = load_module("deploy_optionpassword_en", TOOLS / "deploy_optionpassword_en.py")
display = load_module("deploy_display_settings_en", TOOLS / "deploy_display_settings_en.py")
sound = load_module("deploy_sound_settings_en", TOOLS / "deploy_sound_settings_en.py")
profile = load_module("deploy_profile_en", TOOLS / "deploy_profile_en.py")
datadelete = load_module("deploy_datadelete_en", TOOLS / "deploy_datadelete_en.py")
title = load_module("deploy_title_main_menu_en", TOOLS / "deploy_title_main_menu_en.py")
commu = load_module("deploy_commu_settings_header_en", TOOLS / "deploy_commu_settings_header_en.py")

from bclimutil import parse_bclim  # noqa: E402

MASTER = ROOT / "out" / "_cov_softkeys"
TITLE_MOD = "00040000000F4E00"


class LenZopfli:
    """Stand-in for zopfli.zlib: return a fixed-length buffer (no real zopfli)."""

    def __init__(self, length):
        self.length = length
        self.calls = 0

    def compress(self, data, *args, **kwargs):
        self.calls += 1
        n = self.length(self.calls, data) if callable(self.length) else self.length
        return b"z" * int(n)


def exact_zlib(data: bytes, exact_len: int) -> bytes | None:
    """SYNC_FLUSH body + empty stored blocks, same idea as the deploy helpers."""
    if exact_len < 16:
        return None
    adler = struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF)
    hdrs = (b"\x78\x9c", b"\x78\xda", b"\x78\x5e", b"\x78\x01")
    for level in range(10):
        co = zlib.compressobj(level, wbits=-15)
        body = co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH)
        for hdr in hdrs:
            remain = exact_len - len(hdr) - 4 - len(body)
            if remain < 5 or remain % 5:
                continue
            n_empty = remain // 5
            out = (
                hdr
                + body
                + b"\x00\x00\x00\xff\xff" * (n_empty - 1)
                + b"\x01\x00\x00\xff\xff"
                + adler
            )
            if len(out) != exact_len:
                continue
            dec = zlib.decompressobj()
            try:
                got = dec.decompress(out)
            except zlib.error:
                continue
            if got == data and not dec.unused_data and dec.eof:
                return out
    return None


def must_pair(data: bytes, exact_len: int, *args, **kwargs):
    slot = exact_zlib(data, exact_len)
    if slot is None:
        # A few salted pads, still zlib-speed — not a zopfli search.
        blob = bytearray(data)
        for i, b in enumerate(blob):
            if b == 0 and i % 17 == 0:
                blob[i] = 0x5A
                slot = exact_zlib(bytes(blob), exact_len)
                if slot is not None:
                    return bytes(blob), slot
                if i > 400:
                    break
        raise RuntimeError(f"exact zlib miss len={len(data)} slot={exact_len}")
    return data, slot


def write_png(path: Path, w: int, h: int, color=(30, 40, 50, 255)) -> Path:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if w > 2 and h > 2:
        ImageDraw.Draw(im).rectangle((1, 1, w - 2, h - 2), fill=color)
    im.putpixel((0, 0), (0, 0, 0, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def repo_png(name: str, w: int, h: int) -> Path:
    """Under the repo so Path.relative_to(ROOT) works. out/ is gitignored."""
    return write_png(MASTER / name, w, h)


def noise_bclim(w: int, h: int, fmt: int, seed: int) -> bytes:
    size = len(parse_bclim(fi.bclim(w, h, fmt))[0])
    return fi.bclim(w, h, fmt, pixels=random.Random(seed).randbytes(size))


def zero_bclim(w: int, h: int, fmt: int) -> bytes:
    return fi.bclim(w, h, fmt)


def bclyt(panes: list[str]) -> bytes:
    header_size = 0x14
    sections = []
    for name in panes:
        sec = bytearray(40)
        sec[0:4] = b"pan1"
        struct.pack_into("<I", sec, 4, len(sec))
        sec[8] = 1
        raw = name.encode("ascii")
        sec[12 : 12 + len(raw)] = raw
        sections.append(bytes(sec))
    body = b"".join(sections)
    total = header_size + len(body)
    head = bytearray(header_size)
    struct.pack_into(
        "<4sHHIII", head, 0, b"CLYT", 0xFEFF, header_size, 0, total, len(panes)
    )
    return bytes(head) + body


def pack_arc(arc_name: str, files: dict[str, bytes], *, compressed: bool = True) -> bytes:
    arc = fi.darc(files)
    return fi.package(
        [
            (arc_name, arc, b"ARC ", compressed),
            ("note.txt", b"note", b"TXT ", False),
        ]
    )


def write_img(path: Path, packages: dict[int, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fi.img(packages))
    return path


def instance_copy(root: Path, slot: str, data: bytes) -> Path:
    dest = root / slot / "user" / "load" / "mods" / TITLE_MOD / "romfs" / "img.bin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


_HOOKS = (
    "compress_exact_zopfli",
    "try_fast_exact_slot",
    "compress_exact_empty_blocks",
    "compress_exact_with_gap_tune",
    "shared_exact_zopfli",
    "splice_packages_into_img",
    "find_ui_png",
    "zopfli_zlib",
    "Package",
    "UI_FONT",
    "DarcArchive",
    "PLATE_MASTER",
    "interfile_zero_gaps",
)
_FROZEN: dict = {}
_PARSE_ENTRY: dict = {}


def _freeze(mod):
    _FROZEN[mod] = {name: getattr(mod, name) for name in _HOOKS if hasattr(mod, name)}
    _PARSE_ENTRY[mod] = mod.Package.parse_entry


for _mod in (
    confirm,
    quit_sk,
    back,
    defaults,
    password,
    display,
    sound,
    profile,
    datadelete,
    title,
    commu,
):
    _freeze(_mod)


def rewind(monkeypatch, mod):
    """Undo stubs from an earlier scenario in the same test."""
    saved = _FROZEN[mod]
    for name, value in saved.items():
        monkeypatch.setattr(mod, name, value)
    monkeypatch.setattr(saved["Package"], "parse_entry", _PARSE_ENTRY[mod])


def bind(monkeypatch, mod, tmp_path: Path, img: Path, vanilla: Path | None = None):
    rewind(monkeypatch, mod)
    inst = tmp_path / "azahar_instances"
    if inst.exists():
        shutil.rmtree(inst)
    paths = fi.use_paths(monkeypatch, tmp_path, mod)
    monkeypatch.setattr(mod, "MOD_IMG", img)
    if hasattr(mod, "VANILLA"):
        monkeypatch.setattr(mod, "VANILLA", img if vanilla is None else vanilla)
    if hasattr(mod, "ASSET"):
        asset = tmp_path / "asset_pngs"
        asset.mkdir(exist_ok=True)
        monkeypatch.setattr(mod, "ASSET", asset)
    if hasattr(mod, "PREV"):
        prev = tmp_path / "profile_previews"
        prev.mkdir(exist_ok=True)
        monkeypatch.setattr(mod, "PREV", prev)
    return paths


def stub_zopfli(monkeypatch, mod, length=8):
    if hasattr(mod, "zopfli_zlib"):
        monkeypatch.setattr(mod, "zopfli_zlib", LenZopfli(length))


def stub_pair(monkeypatch, mod, fn_name: str, impl=must_pair):
    if hasattr(mod, fn_name):
        monkeypatch.setattr(mod, fn_name, impl)


def install_bad_entry(monkeypatch, mod, mode: str):
    real = mod.Package.parse_entry

    def bad(buf):
        typ, dec, off, fl, is_cmp, slot_len, cmp_off = real(buf)
        if mode == "slot":
            return typ, dec, off, fl, 1, slot_len + 7, cmp_off
        if mode == "dec":
            return typ, dec + 7, off, fl, 1, slot_len, cmp_off
        return typ, dec, off, fl, 0, slot_len, cmp_off

    monkeypatch.setattr(mod.Package, "parse_entry", bad)


def pair_then(monkeypatch, mod, mode: str | None):
    def go(data, n, *args, **kwargs):
        tuned, slot = must_pair(data, n)
        if mode:
            install_bad_entry(monkeypatch, mod, mode)
        return tuned, slot

    return go


def bytes_then(monkeypatch, mod, mode: str | None):
    def go(data, n, *args, **kwargs):
        _tuned, slot = must_pair(data, n)
        if mode:
            install_bad_entry(monkeypatch, mod, mode)
        return slot

    return go


def wrap_second_pkg(monkeypatch, mod, mode: str):
    real = mod.Package

    class Wrapped(real):
        def parse(self, recursive=True):
            super().parse(recursive)
            if not Path(self.fw.filename).name.startswith("new_"):
                return
            for entry in self.entries:
                arc = isinstance(entry, mod.ARC)
                if mode == "arc" and arc:
                    entry.parsed = lambda: b"mismatch"
                    return
                if mode == "dmst" and not arc:
                    entry.parsed = lambda: b"mismatch"
                    return

    monkeypatch.setattr(mod, "Package", Wrapped)


def boom_splice(*_a, **_k):
    raise PackError("grew")


def softkey_files(fmt: int = 0xB, *, noise: bool = True) -> dict[str, bytes]:
    stems = [
        "Com_btn_k01_b",
        "Com_btn_k01_bON",
        "Com_btn_y01_b",
        "Com_btn_y01_bON",
        "Com_btn_m01_b",
        "Com_btn_m01_bON",
        "Com_btn_t01_b",
        "Com_btn_t01_bON",
        "Com_btn_sy01_a",
        "Com_btn_sy01_b",
    ]
    files = {}
    for i, stem in enumerate(stems):
        blob = noise_bclim(64, 32, fmt, 1000 + i) if noise else zero_bclim(64, 32, fmt)
        files[f"timg/{stem}.bclim"] = blob
    return files


def softkey_img(path: Path, fmt: int = 0xB, *, noise: bool = True, compressed: bool = True) -> Path:
    pkg = pack_arc("NCommonIcon.arc", softkey_files(fmt, noise=noise), compressed=compressed)
    return write_img(path, {confirm.PKG: pkg})


# ---------------------------------------------------------------------------
# Shared builder sanity
# ---------------------------------------------------------------------------


def test_exact_zlib_roundtrip():
    data = b"coverage-softkeys" * 12
    hit = None
    for n in range(40, len(data) + 80):
        hit = exact_zlib(data, n)
        if hit is not None:
            break
    assert hit is not None
    dec = zlib.decompressobj()
    assert dec.decompress(hit) == data
    assert dec.eof and not dec.unused_data


# ---------------------------------------------------------------------------
# Confirm OK @ 5238
# ---------------------------------------------------------------------------


def test_confirm_render_and_font():
    face = confirm.font(12)
    assert face.getbbox("OK")[2] > 0
    off = confirm.render_btn(64, 32, "OK", on=False, hard_text=True)
    on = confirm.render_btn(64, 32, "OK", on=True, hard_text=False, radius=10, border_w=2, max_size=18)
    assert off.size == on.size == (64, 32)
    with pytest.raises(RuntimeError, match="cannot fit"):
        confirm.render_btn(12, 12, "CONFIRM", on=False, max_size=14)


def test_confirm_main_renders_when_no_master(tmp_path, monkeypatch):
    img = softkey_img(tmp_path / "img.bin")
    before = img.read_bytes()
    bind(monkeypatch, confirm, tmp_path, img)
    stub_zopfli(monkeypatch, confirm, 8)
    stub_pair(monkeypatch, confirm, "compress_exact_zopfli")
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    assert confirm.main() == 0
    assert img.read_bytes() != before
    assert (confirm.OUT / "Com_btn_k01_b_en.png").is_file()
    assert (confirm.ASSET / "Com_btn_k01_b.png").is_file()
    assert (confirm.ASSET / "Com_btn_k01_bON.png").is_file()


def test_confirm_main_uses_master_png(tmp_path, monkeypatch):
    img = softkey_img(tmp_path / "img.bin")
    before = img.read_bytes()
    bind(monkeypatch, confirm, tmp_path, img)
    stub_zopfli(monkeypatch, confirm, 8)
    stub_pair(monkeypatch, confirm, "compress_exact_zopfli")
    png = repo_png("confirm_master.png", 16, 16)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: png)
    assert confirm.main() == 0
    assert img.read_bytes() != before
    assert not (confirm.ASSET / "Com_btn_k01_b.png").exists()


def test_confirm_vanilla_after_live_overshoot(tmp_path, monkeypatch):
    live = softkey_img(tmp_path / "live.bin")
    vanilla = softkey_img(tmp_path / "vanilla.bin")
    before = live.read_bytes()
    bind(monkeypatch, confirm, tmp_path, live, vanilla)
    # base + 5 live trials overshoot, then vanilla base + first trial fits.
    stub_zopfli(monkeypatch, confirm, lambda n, _d: 8 if n > 6 else 900_000)
    stub_pair(monkeypatch, confirm, "compress_exact_zopfli")
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    assert confirm.main() == 0
    assert live.read_bytes() != before


def test_confirm_gives_up_when_nothing_fits(tmp_path, monkeypatch):
    img = softkey_img(tmp_path / "img.bin")
    before = img.read_bytes()
    bind(monkeypatch, confirm, tmp_path, img)
    stub_zopfli(monkeypatch, confirm, 900_000)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    assert confirm.main() == 0
    assert img.read_bytes() == before


def test_confirm_gives_up_without_best_over(tmp_path, monkeypatch):
    img = softkey_img(tmp_path / "img.bin")
    bind(monkeypatch, confirm, tmp_path, img)
    stub_zopfli(monkeypatch, confirm, 8)

    def miss(*_a, **_k):
        raise RuntimeError("no-slot")

    stub_pair(monkeypatch, confirm, "compress_exact_zopfli", miss)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    assert confirm.main() == 0


def test_confirm_runtime_then_hit(tmp_path, monkeypatch):
    img = softkey_img(tmp_path / "img.bin")
    bind(monkeypatch, confirm, tmp_path, img)
    stub_zopfli(monkeypatch, confirm, 8)
    state = {"n": 0}

    def flaky(data, n, *a, **k):
        state["n"] += 1
        if state["n"] < 2:
            raise RuntimeError("miss")
        return must_pair(data, n)

    stub_pair(monkeypatch, confirm, "compress_exact_zopfli", flaky)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    assert confirm.main() == 0
    assert state["n"] >= 2


def test_confirm_errors(tmp_path, monkeypatch):
    missing = tmp_path / "nope.bin"
    bind(monkeypatch, confirm, tmp_path, missing)
    with pytest.raises(SystemExit, match="missing"):
        confirm.main()

    bad = softkey_img(tmp_path / "bad.bin", fmt=8)
    bind(monkeypatch, confirm, tmp_path, bad)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="fmt"):
        confirm.main()

    files = softkey_files()
    del files["timg/Com_btn_k01_bON.bclim"]
    img = write_img(tmp_path / "miss.bin", {confirm.PKG: pack_arc("NCommonIcon.arc", files)})
    bind(monkeypatch, confirm, tmp_path, img)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="missing timg/Com_btn_k01_bON"):
        confirm.main()


def test_confirm_verify_splice_and_entry(tmp_path, monkeypatch):
    img = softkey_img(tmp_path / "img.bin")
    bind(monkeypatch, confirm, tmp_path, img)
    stub_zopfli(monkeypatch, confirm, 8)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    stub_pair(monkeypatch, confirm, "compress_exact_zopfli", lambda d, n, *a, **k: (d, zlib.compress(b"nope")))
    with pytest.raises(SystemExit, match="verify failed"):
        confirm.main()

    img2 = softkey_img(tmp_path / "img2.bin")
    bind(monkeypatch, confirm, tmp_path, img2)
    stub_zopfli(monkeypatch, confirm, 8)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    stub_pair(monkeypatch, confirm, "compress_exact_zopfli")
    monkeypatch.setattr(confirm, "splice_packages_into_img", boom_splice)
    with pytest.raises(SystemExit, match="splice failed: grew"):
        confirm.main()

    for mode in ("slot", "dec"):
        img_m = softkey_img(tmp_path / f"img_{mode}.bin")
        bind(monkeypatch, confirm, tmp_path, img_m)
        stub_zopfli(monkeypatch, confirm, 8)
        monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
        stub_pair(monkeypatch, confirm, "compress_exact_zopfli", pair_then(monkeypatch, confirm, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            confirm.main()

    raw = softkey_img(tmp_path / "unc.bin", noise=False, compressed=False)
    bind(monkeypatch, confirm, tmp_path, raw)
    stub_zopfli(monkeypatch, confirm, 8)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    stub_pair(monkeypatch, confirm, "compress_exact_zopfli")
    with pytest.raises(SystemExit, match="entry mismatch"):
        confirm.main()

    img3 = softkey_img(tmp_path / "img3.bin")
    bind(monkeypatch, confirm, tmp_path, img3)
    stub_zopfli(monkeypatch, confirm, 8)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    stub_pair(monkeypatch, confirm, "compress_exact_zopfli")
    wrap_second_pkg(monkeypatch, confirm, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        confirm.main()

    img4 = softkey_img(tmp_path / "img4.bin")
    bind(monkeypatch, confirm, tmp_path, img4)
    stub_zopfli(monkeypatch, confirm, 8)
    monkeypatch.setattr(confirm, "find_ui_png", lambda *a, **k: None)
    stub_pair(monkeypatch, confirm, "compress_exact_zopfli")
    wrap_second_pkg(monkeypatch, confirm, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        confirm.main()


# ---------------------------------------------------------------------------
# Quit
# ---------------------------------------------------------------------------


def test_quit_render_and_load_rgba(tmp_path, monkeypatch):
    assert quit_sk.font(11).getbbox("Quit")[2] > 0
    assert quit_sk.render_btn(64, 32, "Quit", on=True, hard_text=True).size == (64, 32)
    with pytest.raises(RuntimeError, match="cannot fit"):
        quit_sk.render_btn(10, 10, "QuitQuit", on=False)
    black = Image.new("RGBA", (4, 4), (0, 0, 0, 255))
    black.putpixel((1, 1), (200, 200, 200, 255))
    punched = quit_sk._punch_black(black)
    assert punched.getpixel((0, 0))[3] == 0
    assert punched.getpixel((1, 1))[3] == 255

    png = write_png(tmp_path / "q.png", 8, 8)
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: png)
    mastered = quit_sk.load_rgba("timg/Com_btn_y01_bON.bclim", "Quit", 64, 32, style=None)
    assert mastered.getpixel((0, 0))[3] == 0
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
    rendered = quit_sk.load_rgba("timg/Com_btn_y01_b.bclim", "Quit", 64, 32, style=None)
    assert rendered.size == (64, 32)
    styled = quit_sk.load_rgba(
        "timg/Com_btn_y01_bON.bclim", "Quit", 64, 32, style=quit_sk.STYLES[-1]
    )
    assert styled.size == (64, 32)


def test_quit_fit_slot_branches(monkeypatch):
    payload = b"quit-slot" * 30
    # Find a length the fast stub can hit, then exercise each branch.
    target = next(n for n in range(len(payload), len(payload) + 80) if exact_zlib(payload, n))
    monkeypatch.setattr(quit_sk, "zopfli_zlib", LenZopfli(4))
    monkeypatch.setattr(quit_sk, "try_fast_exact_slot", lambda d, n: must_pair(d, n))
    assert quit_sk._fit_slot(payload, target)[1] and len(quit_sk._fit_slot(payload, target)[1]) == target

    monkeypatch.setattr(quit_sk, "try_fast_exact_slot", lambda *_a, **_k: None)
    monkeypatch.setattr(quit_sk, "zopfli_zlib", LenZopfli(10**6))
    assert quit_sk._fit_slot(payload, target) is None

    monkeypatch.setattr(quit_sk, "zopfli_zlib", LenZopfli(4))
    monkeypatch.setattr(quit_sk, "compress_exact_zopfli", lambda d, n: must_pair(d, n))
    tuned, slot = quit_sk._fit_slot(payload, target)
    assert zlib.decompress(slot) == tuned

    def miss(*_a, **_k):
        raise RuntimeError("miss")

    monkeypatch.setattr(quit_sk, "compress_exact_zopfli", miss)
    assert quit_sk._fit_slot(payload, target) is None


def test_quit_main_live_and_vanilla(tmp_path, monkeypatch):
    img = softkey_img(tmp_path / "img.bin")
    before = img.read_bytes()
    bind(monkeypatch, quit_sk, tmp_path, img)
    stub_zopfli(monkeypatch, quit_sk, 8)
    stub_pair(monkeypatch, quit_sk, "try_fast_exact_slot")
    png = repo_png("quit_master.png", 12, 12)
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: png)
    assert quit_sk.main() == 0
    assert img.read_bytes() != before
    assert (quit_sk.OUT / "Com_btn_y01_b_en.png").is_file()

    live = softkey_img(tmp_path / "live.bin")
    vanilla = softkey_img(tmp_path / "van.bin")
    before_v = live.read_bytes()
    bind(monkeypatch, quit_sk, tmp_path, live, vanilla)
    # 6 live trials (None + 5 styles) overshoot; vanilla's first trial fits.
    stub_zopfli(monkeypatch, quit_sk, lambda n, _d: 8 if n > 6 else 900_000)
    stub_pair(monkeypatch, quit_sk, "try_fast_exact_slot", lambda *_a, **_k: None)
    stub_pair(monkeypatch, quit_sk, "compress_exact_zopfli")
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: png)
    assert quit_sk.main() == 0
    assert live.read_bytes() != before_v


def test_quit_errors(tmp_path, monkeypatch):
    bind(monkeypatch, quit_sk, tmp_path, tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        quit_sk.main()

    bad = softkey_img(tmp_path / "bad.bin", fmt=8)
    bind(monkeypatch, quit_sk, tmp_path, bad)
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="fmt"):
        quit_sk.main()

    files = softkey_files()
    del files["timg/Com_btn_y01_b.bclim"]
    img = write_img(tmp_path / "miss.bin", {quit_sk.PKG: pack_arc("NCommonIcon.arc", files)})
    bind(monkeypatch, quit_sk, tmp_path, img)
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="missing timg/Com_btn_y01_b"):
        quit_sk.main()

    img = softkey_img(tmp_path / "nofit.bin")
    bind(monkeypatch, quit_sk, tmp_path, img)
    stub_zopfli(monkeypatch, quit_sk, 900_000)
    stub_pair(monkeypatch, quit_sk, "try_fast_exact_slot", lambda *_a, **_k: None)
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="could not fit"):
        quit_sk.main()

    img = softkey_img(tmp_path / "verify.bin")
    bind(monkeypatch, quit_sk, tmp_path, img)
    stub_zopfli(monkeypatch, quit_sk, 8)
    stub_pair(monkeypatch, quit_sk, "try_fast_exact_slot", lambda d, n, *a, **k: (d, zlib.compress(b"no")))
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="verify failed"):
        quit_sk.main()

    img = softkey_img(tmp_path / "splice.bin")
    bind(monkeypatch, quit_sk, tmp_path, img)
    stub_zopfli(monkeypatch, quit_sk, 8)
    stub_pair(monkeypatch, quit_sk, "try_fast_exact_slot")
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(quit_sk, "splice_packages_into_img", boom_splice)
    with pytest.raises(SystemExit, match="splice failed"):
        quit_sk.main()

    for mode in ("slot", "dec"):
        img = softkey_img(tmp_path / f"ent_{mode}.bin")
        bind(monkeypatch, quit_sk, tmp_path, img)
        stub_zopfli(monkeypatch, quit_sk, 8)
        monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
        stub_pair(monkeypatch, quit_sk, "try_fast_exact_slot", pair_then(monkeypatch, quit_sk, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            quit_sk.main()

    img = softkey_img(tmp_path / "arc.bin")
    bind(monkeypatch, quit_sk, tmp_path, img)
    stub_zopfli(monkeypatch, quit_sk, 8)
    stub_pair(monkeypatch, quit_sk, "try_fast_exact_slot")
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
    wrap_second_pkg(monkeypatch, quit_sk, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        quit_sk.main()

    img = softkey_img(tmp_path / "dmst.bin")
    bind(monkeypatch, quit_sk, tmp_path, img)
    stub_zopfli(monkeypatch, quit_sk, 8)
    stub_pair(monkeypatch, quit_sk, "try_fast_exact_slot")
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
    wrap_second_pkg(monkeypatch, quit_sk, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        quit_sk.main()

    raw = softkey_img(tmp_path / "unc.bin", noise=False, compressed=False)
    bind(monkeypatch, quit_sk, tmp_path, raw)
    stub_zopfli(monkeypatch, quit_sk, 8)
    stub_pair(monkeypatch, quit_sk, "try_fast_exact_slot")
    monkeypatch.setattr(quit_sk, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="entry mismatch"):
        quit_sk.main()


def test_quit_replace_missing(tmp_path, monkeypatch):
    bind(monkeypatch, quit_sk, tmp_path, tmp_path / "unused.bin")
    darc_bytes = fi.darc({"timg/other.bclim": zero_bclim(64, 32, 0xB)})
    from darcutil import DarcArchive

    with pytest.raises(SystemExit, match="missing timg/nope.bclim"):
        quit_sk._replace(DarcArchive(darc_bytes), tmp_path, "timg/nope.bclim", "Quit", style=None)


# ---------------------------------------------------------------------------
# Back / Next
# ---------------------------------------------------------------------------


def test_back_render_and_masters(tmp_path, monkeypatch):
    assert back.font(12).getbbox("Back")[2] > 0
    assert back.render_btn(64, 32, "Next", on=True, hard_text=False).size == (64, 32)
    with pytest.raises(RuntimeError, match="cannot fit"):
        back.render_btn(8, 8, "Next", on=False)
    bind(monkeypatch, back, tmp_path, tmp_path / "unused.bin")
    write_png(back.ASSET / "Com_btn_m01_b.png", 64, 32)
    matched = back.load_or_render("timg/Com_btn_m01_b.bclim", "Back", 64, 32, back.STYLES[0])
    assert matched.getpixel((0, 0))[3] == 0
    write_png(back.ASSET / "Com_btn_m01_bON.png", 8, 8)
    fallback = back.load_or_render("timg/Com_btn_m01_bON.bclim", "Back", 64, 32, back.STYLES[-1])
    assert fallback.size == (64, 32)
    missing = back.load_or_render("timg/Com_btn_t01_b.bclim", "Next", 64, 32, back.STYLES[0])
    assert missing.size == (64, 32)


def test_back_main_live_and_vanilla(tmp_path, monkeypatch):
    img = softkey_img(tmp_path / "img.bin")
    before = img.read_bytes()
    bind(monkeypatch, back, tmp_path, img)
    stub_zopfli(monkeypatch, back, 8)
    stub_pair(monkeypatch, back, "compress_exact_zopfli")
    assert back.main() == 0
    assert img.read_bytes() != before
    assert (back.OUT / "Com_btn_m01_b_en.png").is_file()

    live = softkey_img(tmp_path / "live.bin")
    vanilla = softkey_img(tmp_path / "van.bin")
    before_v = live.read_bytes()
    bind(monkeypatch, back, tmp_path, live, vanilla)
    # No separate base compress: 5 live styles overshoot, vanilla's first fits
    # and also repaints Confirm.
    stub_zopfli(monkeypatch, back, lambda n, _d: 8 if n > 5 else 900_000)
    stub_pair(monkeypatch, back, "compress_exact_zopfli")
    assert back.main() == 0
    assert live.read_bytes() != before_v


def test_back_errors(tmp_path, monkeypatch):
    bind(monkeypatch, back, tmp_path, tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        back.main()

    bad = softkey_img(tmp_path / "bad.bin", fmt=8)
    bind(monkeypatch, back, tmp_path, bad)
    with pytest.raises(SystemExit, match="fmt"):
        back.main()

    files = softkey_files()
    del files["timg/Com_btn_t01_bON.bclim"]
    img = write_img(tmp_path / "miss.bin", {back.PKG: pack_arc("NCommonIcon.arc", files)})
    bind(monkeypatch, back, tmp_path, img)
    with pytest.raises(SystemExit, match="missing timg/Com_btn_t01_bON"):
        back.main()

    img = softkey_img(tmp_path / "nofit.bin")
    bind(monkeypatch, back, tmp_path, img)
    stub_zopfli(monkeypatch, back, 900_000)
    with pytest.raises(SystemExit, match="could not fit"):
        back.main()

    img = softkey_img(tmp_path / "misszip.bin")
    bind(monkeypatch, back, tmp_path, img)
    stub_zopfli(monkeypatch, back, 8)

    def miss(*_a, **_k):
        raise RuntimeError("miss")

    stub_pair(monkeypatch, back, "compress_exact_zopfli", miss)
    with pytest.raises(SystemExit, match="could not fit"):
        back.main()

    img = softkey_img(tmp_path / "verify.bin")
    bind(monkeypatch, back, tmp_path, img)
    stub_zopfli(monkeypatch, back, 8)
    stub_pair(monkeypatch, back, "compress_exact_zopfli", lambda d, n, *a, **k: (d, zlib.compress(b"no")))
    with pytest.raises(SystemExit, match="verify failed"):
        back.main()

    img = softkey_img(tmp_path / "splice.bin")
    bind(monkeypatch, back, tmp_path, img)
    stub_zopfli(monkeypatch, back, 8)
    stub_pair(monkeypatch, back, "compress_exact_zopfli")
    monkeypatch.setattr(back, "splice_packages_into_img", boom_splice)
    with pytest.raises(SystemExit, match="splice failed"):
        back.main()

    for mode in ("slot", "dec"):
        img = softkey_img(tmp_path / f"ent_{mode}.bin")
        bind(monkeypatch, back, tmp_path, img)
        stub_zopfli(monkeypatch, back, 8)
        stub_pair(monkeypatch, back, "compress_exact_zopfli", pair_then(monkeypatch, back, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            back.main()

    raw = softkey_img(tmp_path / "unc.bin", noise=False, compressed=False)
    bind(monkeypatch, back, tmp_path, raw)
    stub_zopfli(monkeypatch, back, 8)
    stub_pair(monkeypatch, back, "compress_exact_zopfli")
    with pytest.raises(SystemExit, match="entry mismatch"):
        back.main()

    img = softkey_img(tmp_path / "arc.bin")
    bind(monkeypatch, back, tmp_path, img)
    stub_zopfli(monkeypatch, back, 8)
    stub_pair(monkeypatch, back, "compress_exact_zopfli")
    wrap_second_pkg(monkeypatch, back, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        back.main()

    img = softkey_img(tmp_path / "dmst.bin")
    bind(monkeypatch, back, tmp_path, img)
    stub_zopfli(monkeypatch, back, 8)
    stub_pair(monkeypatch, back, "compress_exact_zopfli")
    wrap_second_pkg(monkeypatch, back, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        back.main()


# ---------------------------------------------------------------------------
# Restore Default
# ---------------------------------------------------------------------------


def test_defaults_punch_and_targets(tmp_path, monkeypatch):
    im = Image.new("RGBA", (3, 2), (1, 1, 1, 255))
    im.putpixel((2, 1), (255, 255, 255, 255))
    assert defaults._punch_black(im).getpixel((0, 0))[3] == 0
    assert defaults._punch_black(im).getpixel((2, 1))[:3] == (255, 255, 255)

    img = softkey_img(tmp_path / "img.bin")
    paths = bind(monkeypatch, defaults, tmp_path, img)
    inst = instance_copy(paths["AZAHAR_INSTANCES"], "b", img.read_bytes())
    # Primary is not under the instance root, so the glob adds inst.
    found = defaults._deploy_targets()
    assert img.resolve() in found
    assert inst.resolve() in found

    # Same file is already the primary: the glob must not add it twice.
    dup = instance_copy(paths["AZAHAR_INSTANCES"], "a", img.read_bytes())
    monkeypatch.setattr(defaults, "MOD_IMG", dup)
    again = defaults._deploy_targets()
    assert again.count(dup.resolve()) == 1
    assert inst.resolve() in again


def test_defaults_main_fast_and_zopfli(tmp_path, monkeypatch):
    img = softkey_img(tmp_path / "img.bin")
    before = img.read_bytes()
    paths = bind(monkeypatch, defaults, tmp_path, img)
    inst = instance_copy(paths["AZAHAR_INSTANCES"], "b", before)
    png = repo_png("sy01.png", 20, 16)
    monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: png)
    stub_pair(monkeypatch, defaults, "try_fast_exact_slot")
    assert defaults.main() == 0
    assert img.read_bytes() != before
    assert inst.read_bytes() != before
    assert (defaults.OUT / "Com_btn_sy01_b_en.png").is_file()

    img2 = softkey_img(tmp_path / "img2.bin")
    before2 = img2.read_bytes()
    bind(monkeypatch, defaults, tmp_path, img2)
    monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: png)
    stub_pair(monkeypatch, defaults, "try_fast_exact_slot", lambda *_a, **_k: None)
    stub_pair(monkeypatch, defaults, "compress_exact_zopfli")
    assert defaults.main() == 0
    assert img2.read_bytes() != before2


def test_defaults_errors(tmp_path, monkeypatch):
    bind(monkeypatch, defaults, tmp_path, tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        defaults.main()

    empty = write_img(tmp_path / "empty.bin", {0: pack_arc("X.arc", {"a.bin": b"a"})})
    # Index table includes 5238 as None.
    empty.write_bytes(fi.img({0: pack_arc("X.arc", {"a.bin": b"aa"})}, count=defaults.PKG + 1))
    bind(monkeypatch, defaults, tmp_path, empty)
    with pytest.raises(SystemExit, match="missing"):
        defaults.main()

    bad = softkey_img(tmp_path / "bad.bin", fmt=8)
    bind(monkeypatch, defaults, tmp_path, bad)
    monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: repo_png("sy_bad.png", 8, 8))
    with pytest.raises(SystemExit, match="not ETC1A4"):
        defaults.main()

    files = softkey_files()
    del files["timg/Com_btn_sy01_a.bclim"]
    img = write_img(tmp_path / "miss.bin", {defaults.PKG: pack_arc("NCommonIcon.arc", files)})
    bind(monkeypatch, defaults, tmp_path, img)
    with pytest.raises(SystemExit, match="missing timg/Com_btn_sy01_a"):
        defaults.main()

    img = softkey_img(tmp_path / "nomaster.bin")
    bind(monkeypatch, defaults, tmp_path, img)
    monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="missing Zhoumaru"):
        defaults.main()

    img = softkey_img(tmp_path / "verify.bin")
    bind(monkeypatch, defaults, tmp_path, img)
    monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: repo_png("sy_v.png", 8, 8))
    stub_pair(monkeypatch, defaults, "try_fast_exact_slot", lambda d, n, *a, **k: (d, zlib.compress(b"no")))
    with pytest.raises(SystemExit, match="verify failed"):
        defaults.main()

    img = softkey_img(tmp_path / "splice.bin")
    bind(monkeypatch, defaults, tmp_path, img)
    monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: repo_png("sy_s.png", 8, 8))
    stub_pair(monkeypatch, defaults, "try_fast_exact_slot")
    monkeypatch.setattr(defaults, "splice_packages_into_img", boom_splice)
    with pytest.raises(SystemExit, match="splice failed"):
        defaults.main()

    for mode in ("slot", "dec"):
        img = softkey_img(tmp_path / f"ent_{mode}.bin")
        bind(monkeypatch, defaults, tmp_path, img)
        monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: repo_png(f"sy_{mode}.png", 8, 8))
        stub_pair(monkeypatch, defaults, "try_fast_exact_slot", pair_then(monkeypatch, defaults, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            defaults.main()

    raw = softkey_img(tmp_path / "unc.bin", noise=False, compressed=False)
    bind(monkeypatch, defaults, tmp_path, raw)
    monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: repo_png("sy_u.png", 8, 8))
    stub_pair(monkeypatch, defaults, "try_fast_exact_slot")
    with pytest.raises(SystemExit, match="entry mismatch"):
        defaults.main()

    img = softkey_img(tmp_path / "arc.bin")
    bind(monkeypatch, defaults, tmp_path, img)
    monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: repo_png("sy_a.png", 8, 8))
    stub_pair(monkeypatch, defaults, "try_fast_exact_slot")
    wrap_second_pkg(monkeypatch, defaults, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        defaults.main()

    img = softkey_img(tmp_path / "dmst.bin")
    bind(monkeypatch, defaults, tmp_path, img)
    monkeypatch.setattr(defaults, "find_ui_png", lambda *a, **k: repo_png("sy_d.png", 8, 8))
    stub_pair(monkeypatch, defaults, "try_fast_exact_slot")
    wrap_second_pkg(monkeypatch, defaults, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        defaults.main()


# ---------------------------------------------------------------------------
# Password window
# ---------------------------------------------------------------------------


def _pass_img(path: Path, fmt: int = 0xB, *, noise: bool = True, compressed: bool = True) -> Path:
    blob = noise_bclim(96, 32, fmt, 7) if noise else zero_bclim(96, 32, fmt)
    files = {"timg/Pass_Win01.bclim": blob, "timg/other.bclim": b"\x00" * 16}
    # other.bclim is not a real bclim; only Pass_Win01 is parsed. Keep a second
    # real file so DARC has a gap.
    files["timg/other.bclim"] = zero_bclim(16, 16, fmt)
    pkg = pack_arc("OptionPassword.arc", files, compressed=compressed)
    return write_img(path, {password.PKG: pkg})


def test_password_main_and_vanilla_flip(tmp_path, monkeypatch):
    img = _pass_img(tmp_path / "img.bin")
    before = img.read_bytes()
    bind(monkeypatch, password, tmp_path, img)
    png = repo_png("pass.png", 24, 16)
    monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: png)
    stub_pair(monkeypatch, password, "try_fast_exact_slot")
    assert password.main() == 0
    assert img.read_bytes() != before
    assert (password.OUT / "Pass_Win01_en.png").is_file()

    # try_fast misses → zopfli stub.
    img2 = _pass_img(tmp_path / "img2.bin")
    bind(monkeypatch, password, tmp_path, img2)
    monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: png)
    stub_pair(monkeypatch, password, "try_fast_exact_slot", lambda *_a, **_k: None)
    stub_pair(monkeypatch, password, "compress_exact_zopfli")
    assert password.main() == 0

    class Flip:
        def __init__(self, real: Path):
            self._real = real
            self.n = 0

        def is_file(self):
            self.n += 1
            return self.n == 1

        def __str__(self):
            return str(self._real)

    bind(monkeypatch, password, tmp_path, img)
    monkeypatch.setattr(password, "VANILLA", Flip(img))
    with pytest.raises(SystemExit, match="missing vanilla"):
        password.main()


def test_password_errors(tmp_path, monkeypatch):
    bind(monkeypatch, password, tmp_path, tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        password.main()

    # VANILLA missing selects MOD, which is also missing.
    bind(monkeypatch, password, tmp_path, tmp_path / "no-mod.bin", tmp_path / "no-van.bin")
    with pytest.raises(SystemExit, match="missing"):
        password.main()

    bad = _pass_img(tmp_path / "bad.bin", fmt=8)
    bind(monkeypatch, password, tmp_path, bad)
    monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: repo_png("pass_bad.png", 8, 8))
    with pytest.raises(SystemExit, match="expected ETC1A4"):
        password.main()

    files = {"timg/nope.bclim": zero_bclim(16, 16, 0xB)}
    img = write_img(tmp_path / "miss.bin", {password.PKG: pack_arc("OptionPassword.arc", files)})
    bind(monkeypatch, password, tmp_path, img)
    with pytest.raises(SystemExit, match="missing timg/Pass_Win01"):
        password.main()

    img = _pass_img(tmp_path / "nomaster.bin")
    bind(monkeypatch, password, tmp_path, img)
    monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="missing Zhoumaru"):
        password.main()

    img = _pass_img(tmp_path / "verify.bin")
    bind(monkeypatch, password, tmp_path, img)
    monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: repo_png("pass_v.png", 8, 8))
    stub_pair(monkeypatch, password, "try_fast_exact_slot", lambda d, n, *a, **k: (d, zlib.compress(b"no")))
    with pytest.raises(SystemExit, match="verify failed"):
        password.main()

    img = _pass_img(tmp_path / "splice.bin")
    bind(monkeypatch, password, tmp_path, img)
    monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: repo_png("pass_s.png", 8, 8))
    stub_pair(monkeypatch, password, "try_fast_exact_slot")
    monkeypatch.setattr(password, "splice_packages_into_img", boom_splice)
    with pytest.raises(SystemExit, match="splice failed"):
        password.main()

    for mode in ("slot", "dec"):
        img = _pass_img(tmp_path / f"ent_{mode}.bin")
        bind(monkeypatch, password, tmp_path, img)
        monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: repo_png(f"pass_{mode}.png", 8, 8))
        stub_pair(monkeypatch, password, "try_fast_exact_slot", pair_then(monkeypatch, password, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            password.main()

    raw = _pass_img(tmp_path / "unc.bin", noise=False, compressed=False)
    bind(monkeypatch, password, tmp_path, raw)
    monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: repo_png("pass_u.png", 8, 8))
    stub_pair(monkeypatch, password, "try_fast_exact_slot")
    with pytest.raises(SystemExit, match="entry mismatch"):
        password.main()

    img = _pass_img(tmp_path / "arc.bin")
    bind(monkeypatch, password, tmp_path, img)
    monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: repo_png("pass_a.png", 8, 8))
    stub_pair(monkeypatch, password, "try_fast_exact_slot")
    wrap_second_pkg(monkeypatch, password, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        password.main()

    img = _pass_img(tmp_path / "dmst.bin")
    bind(monkeypatch, password, tmp_path, img)
    monkeypatch.setattr(password, "find_ui_png", lambda *a, **k: repo_png("pass_d.png", 8, 8))
    stub_pair(monkeypatch, password, "try_fast_exact_slot")
    wrap_second_pkg(monkeypatch, password, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        password.main()


# ---------------------------------------------------------------------------
# Display + Sound settings (RGBA4444, local empty-block zlib)
# ---------------------------------------------------------------------------


def _option_files(labels, fmt: int = 8, *, noise: bool = True) -> dict[str, bytes]:
    files = {}
    for i, (path, _en, _kind) in enumerate(labels):
        blob = noise_bclim(160, 32, fmt, 3000 + i) if noise else zero_bclim(160, 32, fmt)
        files[path] = blob
    return files


def _option_img(path: Path, mod, fmt: int = 8, *, noise: bool = True, compressed: bool = True) -> Path:
    pkg = pack_arc("Option.arc", _option_files(mod.LABELS, fmt, noise=noise), compressed=compressed)
    return write_img(path, {mod.PKG: pkg})


def test_display_render_and_empty_blocks():
    assert display.font(10).getbbox("SE")[2] > 0
    label = display.render_label(120, 24, "Help Display")
    button = display.render_button(96, 24, "Once")
    assert label.size == (120, 24)
    assert button.size == (96, 24)
    with pytest.raises(RuntimeError, match="cannot fit label"):
        display.render_label(4, 4, "Help Display")
    with pytest.raises(RuntimeError, match="cannot fit button"):
        display.render_button(4, 8, "Every Time")

    data = b"display-empty" * 40
    hit_at = None
    for n in range(30, len(data) + 100):
        slot = display.compress_exact_empty_blocks(data, n)
        if slot is not None:
            hit_at = n
            dec = zlib.decompressobj()
            assert dec.decompress(slot) == data and dec.eof and not dec.unused_data
            break
    assert hit_at is not None
    assert display.compress_exact_empty_blocks(data, 4) is None

    # remain % 5 != 0 for at least one header, and the thorough sweep still runs.
    co = zlib.compressobj(6, wbits=-15)
    body = co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH)
    display.compress_exact_empty_blocks(data, len(body) + 6 + 6)


def test_display_empty_blocks_thorough_and_zlib_error(monkeypatch):
    data = b"thorough" * 25
    real = zlib.compressobj
    state = {"n": 0}

    def wrapped(*a, **k):
        state["n"] += 1
        if state["n"] <= 10:
            class Bad:
                def compress(self, _d):
                    return b"\x00" * 8000

                def flush(self, _mode=None):
                    return b""

            return Bad()
        return real(*a, **k)

    monkeypatch.setattr(display.zlib, "compressobj", wrapped)
    target = next(n for n in range(len(data), len(data) + 120) if exact_zlib(data, n))
    slot = display.compress_exact_empty_blocks(data, target)
    assert slot is not None and len(slot) == target

    class Boom:
        def decompress(self, _data):
            raise zlib.error("boom")

        unused_data = b""
        eof = False

    monkeypatch.setattr(display.zlib, "decompressobj", lambda: Boom())
    assert display.compress_exact_empty_blocks(b"abc" * 10, 80) is None


def test_display_main(tmp_path, monkeypatch):
    img = _option_img(tmp_path / "img.bin", display)
    before = img.read_bytes()
    bind(monkeypatch, display, tmp_path, img)
    stub_zopfli(monkeypatch, display, 8)
    help_png = write_png(tmp_path / "help.png", 16, 16)

    def find(_folders, stem, _size=None):
        if stem == "Opt_TxtItem_Help":
            return help_png
        return None

    monkeypatch.setattr(display, "find_ui_png", find)
    assert display.main() is None
    assert img.read_bytes() != before
    assert (display.OUT / "Opt_TxtItem_Message_en.png").is_file()
    assert (display.OUT / "Opt_HelpBtn_A_A_en.png").is_file()


def test_display_errors(tmp_path, monkeypatch):
    bind(monkeypatch, display, tmp_path, tmp_path / "mod.bin", tmp_path / "no-van.bin")
    with pytest.raises(SystemExit, match="missing"):
        display.main()

    bad = _option_img(tmp_path / "bad.bin", display, fmt=1)
    bind(monkeypatch, display, tmp_path, bad)
    monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="expected RGBA4444"):
        display.main()

    files = _option_files(display.LABELS)
    del files["timg/Opt_TxtItem_Help.bclim"]
    img = write_img(tmp_path / "miss.bin", {display.PKG: pack_arc("Option.arc", files)})
    bind(monkeypatch, display, tmp_path, img)
    monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(AttributeError):
        display.main()

    img = _option_img(tmp_path / "over.bin", display)
    bind(monkeypatch, display, tmp_path, img)
    stub_zopfli(monkeypatch, display, 9_000_000)
    monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="exceeds slot"):
        display.main()

    img = _option_img(tmp_path / "none.bin", display)
    bind(monkeypatch, display, tmp_path, img)
    stub_zopfli(monkeypatch, display, 8)
    monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(display, "compress_exact_empty_blocks", lambda *_a, **_k: None)
    with pytest.raises(SystemExit, match="exact zlib failed"):
        display.main()

    img = _option_img(tmp_path / "verify.bin", display)
    bind(monkeypatch, display, tmp_path, img)
    stub_zopfli(monkeypatch, display, 8)
    monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(display, "compress_exact_empty_blocks", lambda *_a, **_k: zlib.compress(b"no"))
    with pytest.raises(SystemExit, match="verify failed"):
        display.main()

    img = _option_img(tmp_path / "splice.bin", display)
    bind(monkeypatch, display, tmp_path, img)
    stub_zopfli(monkeypatch, display, 8)
    monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(display, "compress_exact_empty_blocks", bytes_then(monkeypatch, display, None))
    monkeypatch.setattr(display, "splice_packages_into_img", boom_splice)
    with pytest.raises(PackError, match="grew"):
        display.main()

    for mode in ("slot", "dec"):
        img = _option_img(tmp_path / f"ent_{mode}.bin", display)
        bind(monkeypatch, display, tmp_path, img)
        stub_zopfli(monkeypatch, display, 8)
        monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
        monkeypatch.setattr(display, "compress_exact_empty_blocks", bytes_then(monkeypatch, display, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            display.main()

    raw = _option_img(tmp_path / "unc.bin", display, noise=False, compressed=False)
    bind(monkeypatch, display, tmp_path, raw)
    stub_zopfli(monkeypatch, display, 8)
    monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="entry mismatch"):
        display.main()

    img = _option_img(tmp_path / "arc.bin", display)
    bind(monkeypatch, display, tmp_path, img)
    stub_zopfli(monkeypatch, display, 8)
    monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(display, "compress_exact_empty_blocks", bytes_then(monkeypatch, display, None))
    wrap_second_pkg(monkeypatch, display, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        display.main()

    img = _option_img(tmp_path / "dmst.bin", display)
    bind(monkeypatch, display, tmp_path, img)
    stub_zopfli(monkeypatch, display, 8)
    monkeypatch.setattr(display, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(display, "compress_exact_empty_blocks", bytes_then(monkeypatch, display, None))
    wrap_second_pkg(monkeypatch, display, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        display.main()


def test_sound_render_and_empty_blocks(monkeypatch):
    assert sound.font(10).getbbox("SE")[2] > 0
    assert sound.render_label(100, 20, "Voice").size == (100, 20)
    assert sound.render_button(80, 22, "SE").size == (80, 22)
    with pytest.raises(RuntimeError, match="cannot fit label"):
        sound.render_label(2, 2, "Mic Sensitivity")
    with pytest.raises(RuntimeError, match="cannot fit button"):
        sound.render_button(6, 8, "Mic")
    data = b"sound-empty" * 20
    assert any(sound.compress_exact_empty_blocks(data, n) for n in range(30, len(data) + 80))
    assert sound.compress_exact_empty_blocks(data, 3) is None

    real = zlib.compressobj
    state = {"n": 0}

    def wrapped(*a, **k):
        state["n"] += 1
        if state["n"] <= 10:
            class Bad:
                def compress(self, _d):
                    return b"\x00" * 4000

                def flush(self, _mode=None):
                    return b""

            return Bad()
        return real(*a, **k)

    monkeypatch.setattr(sound.zlib, "compressobj", wrapped)
    target = next(n for n in range(len(data), len(data) + 100) if exact_zlib(data, n))
    assert sound.compress_exact_empty_blocks(data, target) is not None

    class Boom:
        def decompress(self, _data):
            raise zlib.error("boom")

        unused_data = b""
        eof = False

    monkeypatch.setattr(sound.zlib, "decompressobj", lambda: Boom())
    assert sound.compress_exact_empty_blocks(b"zz" * 8, 60) is None


def test_sound_main_and_errors(tmp_path, monkeypatch):
    img = _option_img(tmp_path / "img.bin", sound)
    before = img.read_bytes()
    bind(monkeypatch, sound, tmp_path, img)
    stub_zopfli(monkeypatch, sound, 8)
    assert sound.main() is None
    assert img.read_bytes() != before
    assert (sound.OUT / "Opt_txtItem_MIC_en.png").is_file()

    # Vanilla path is the only source; a distinct vanilla file still deploys onto MOD.
    live = _option_img(tmp_path / "live.bin", sound)
    vanilla = _option_img(tmp_path / "van.bin", sound)
    before_l = live.read_bytes()
    bind(monkeypatch, sound, tmp_path, live, vanilla)
    stub_zopfli(monkeypatch, sound, 8)
    assert sound.main() is None
    assert live.read_bytes() != before_l

    bind(monkeypatch, sound, tmp_path, tmp_path / "mod.bin", tmp_path / "missing-van.bin")
    with pytest.raises(SystemExit, match="missing"):
        sound.main()

    bad = _option_img(tmp_path / "bad.bin", sound, fmt=1)
    bind(monkeypatch, sound, tmp_path, bad)
    with pytest.raises(SystemExit, match="fmt"):
        sound.main()

    img = _option_img(tmp_path / "over.bin", sound)
    bind(monkeypatch, sound, tmp_path, img)
    stub_zopfli(monkeypatch, sound, 9_000_000)
    with pytest.raises(SystemExit, match="exceeds slot"):
        sound.main()

    img = _option_img(tmp_path / "none.bin", sound)
    bind(monkeypatch, sound, tmp_path, img)
    stub_zopfli(monkeypatch, sound, 8)
    monkeypatch.setattr(sound, "compress_exact_empty_blocks", lambda *_a, **_k: None)
    with pytest.raises(SystemExit, match="exact zlib failed"):
        sound.main()

    img = _option_img(tmp_path / "verify.bin", sound)
    bind(monkeypatch, sound, tmp_path, img)
    stub_zopfli(monkeypatch, sound, 8)
    monkeypatch.setattr(sound, "compress_exact_empty_blocks", lambda *_a, **_k: zlib.compress(b"no"))
    with pytest.raises(SystemExit, match="verify failed"):
        sound.main()

    img = _option_img(tmp_path / "splice.bin", sound)
    bind(monkeypatch, sound, tmp_path, img)
    stub_zopfli(monkeypatch, sound, 8)
    monkeypatch.setattr(sound, "splice_packages_into_img", boom_splice)
    with pytest.raises(PackError, match="grew"):
        sound.main()

    for mode in ("slot", "dec"):
        img = _option_img(tmp_path / f"ent_{mode}.bin", sound)
        bind(monkeypatch, sound, tmp_path, img)
        stub_zopfli(monkeypatch, sound, 8)
        monkeypatch.setattr(sound, "compress_exact_empty_blocks", bytes_then(monkeypatch, sound, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            sound.main()

    raw = _option_img(tmp_path / "unc.bin", sound, noise=False, compressed=False)
    bind(monkeypatch, sound, tmp_path, raw)
    stub_zopfli(monkeypatch, sound, 8)
    with pytest.raises(SystemExit, match="entry mismatch"):
        sound.main()

    img = _option_img(tmp_path / "arc.bin", sound)
    bind(monkeypatch, sound, tmp_path, img)
    stub_zopfli(monkeypatch, sound, 8)
    wrap_second_pkg(monkeypatch, sound, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        sound.main()

    img = _option_img(tmp_path / "dmst.bin", sound)
    bind(monkeypatch, sound, tmp_path, img)
    stub_zopfli(monkeypatch, sound, 8)
    wrap_second_pkg(monkeypatch, sound, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        sound.main()

    files = _option_files(sound.LABELS)
    del files["timg/Opt_txtItem_SE.bclim"]
    img = write_img(tmp_path / "miss.bin", {sound.PKG: pack_arc("Option.arc", files)})
    bind(monkeypatch, sound, tmp_path, img)
    with pytest.raises(AttributeError):
        sound.main()


# ---------------------------------------------------------------------------
# Data delete
# ---------------------------------------------------------------------------


def _dd_files(fmt_button=3, fmt_sheet=8, fmt_header=0xB) -> tuple[dict, dict]:
    buttons = {
        "timg/DD_Data_Txt_Big01.bclim": noise_bclim(96, 32, fmt_button, 11),
        "timg/DD_Data_Txt_Big02.bclim": noise_bclim(96, 32, fmt_button, 12),
    }
    for i, stem in enumerate(datadelete.SHEET_STEMS):
        buttons[f"timg/{stem}.bclim"] = noise_bclim(128, 64, fmt_sheet, 20 + i)
    header = {
        "timg/Com_MultiWin_W01_Text05_01_00.bclim": noise_bclim(192, 16, fmt_header, 30),
    }
    return buttons, header


def _dd_img(path: Path, *, compressed: bool = True, **fmts) -> Path:
    buttons, header = _dd_files(**fmts)
    return write_img(
        path,
        {
            datadelete.PKG_BUTTONS: pack_arc("DataDelete.arc", buttons, compressed=compressed),
            datadelete.PKG_HEADER: pack_arc("MultiWin.arc", header, compressed=compressed),
        },
    )


def test_datadelete_gap_helpers(monkeypatch):
    assert datadelete.font(12).getbbox("A")[2] > 0
    assert datadelete.render_header_label(192, 16, "Delete Save Data").size == (192, 16)
    with pytest.raises(RuntimeError, match="cannot fit header"):
        datadelete.render_header_label(8, 4, "Delete Save Data Delete Save Data")

    data = fi.darc({"a.bin": b"a" * 8, "b.bin": b"b" * 8, "c.bin": b"c" * 8})
    runs = datadelete.interfile_zero_gaps(data)
    assert runs and runs == sorted(runs, reverse=True)
    assert datadelete.apply_gap_pad(data, 0, b"\xff" * 8) == data
    padded = datadelete.apply_gap_pad(data, runs[0][0], b"\x5a" * 500)
    assert padded != data
    raw = bytearray(data)
    _sz, off = runs[-1]
    raw[off] = 1
    assert all(o != off for _s, o in datadelete.interfile_zero_gaps(bytes(raw)))

    blob = b"dd-gap" * 40
    assert any(datadelete.compress_exact_empty_blocks(blob, n) for n in range(20, len(blob) + 60))
    assert datadelete.compress_exact_empty_blocks(blob, 4) is None

    class Boom:
        def decompress(self, _d):
            raise zlib.error("boom")

        unused_data = b""
        eof = False

    monkeypatch.setattr(datadelete.zlib, "decompressobj", lambda: Boom())
    assert datadelete.compress_exact_empty_blocks(blob, 80) is None


def test_datadelete_gap_tune_branches(monkeypatch):
    data = fi.darc({"a.bin": b"alpha" * 4, "b.bin": b"beta" * 4})
    real_blocks = datadelete.compress_exact_empty_blocks
    target = next(n for n in range(len(data), len(data) + 150) if real_blocks(data, n))
    tuned, slot = datadelete.compress_exact_with_gap_tune(data, target)
    assert len(slot) == target
    assert zlib.decompress(slot) == tuned

    cap = sum(sz for sz, _ in datadelete.interfile_zero_gaps(data))
    step = max(1, cap // 400) if cap else 1
    n_first = len(range(cap, -1, -step))
    state = {"n": 0}

    def flaky(payload, n):
        state["n"] += 1
        if state["n"] <= n_first:
            return None
        return real_blocks(payload, n)

    monkeypatch.setattr(datadelete, "compress_exact_empty_blocks", flaky)
    tuned, slot = datadelete.compress_exact_with_gap_tune(data, target)
    assert state["n"] > n_first
    assert zlib.decompress(slot) == tuned

    monkeypatch.setattr(datadelete, "compress_exact_empty_blocks", lambda *_a, **_k: None)
    with pytest.raises(SystemExit, match="could not build exact zlib"):
        datadelete.compress_exact_with_gap_tune(data, target)


def test_datadelete_main(tmp_path, monkeypatch):
    img = _dd_img(tmp_path / "img.bin")
    before = img.read_bytes()
    bind(monkeypatch, datadelete, tmp_path, img, tmp_path / "no-vanilla.bin")
    png = repo_png("dd.png", 16, 16)

    def find(_folders, stem, _size=None):
        return png

    monkeypatch.setattr(datadelete, "find_ui_png", find)
    # Gap tune on these small arcs is real; stub only if a call would scan forever.
    assert datadelete.main() is None
    assert img.read_bytes() != before
    assert (datadelete.OUT / "DD_data02_en.png").is_file()
    assert (datadelete.OUT / "Com_MultiWin_W01_Text05_01_00_en.png").is_file()


def test_datadelete_errors(tmp_path, monkeypatch):
    bind(monkeypatch, datadelete, tmp_path, tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        datadelete.main()

    empty = tmp_path / "empty.bin"
    empty.write_bytes(
        fi.img({0: pack_arc("X.arc", {"a.bin": b"a"})}, count=datadelete.PKG_HEADER + 1)
    )
    bind(monkeypatch, datadelete, tmp_path, empty)
    png = repo_png("dd_e.png", 8, 8)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
    with pytest.raises(SystemExit, match="pkg"):
        datadelete.main()

    buttons, header = _dd_files(fmt_button=8)
    img = write_img(
        tmp_path / "badbtn.bin",
        {
            datadelete.PKG_BUTTONS: pack_arc("DataDelete.arc", buttons),
            datadelete.PKG_HEADER: pack_arc("MultiWin.arc", header),
        },
    )
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
    with pytest.raises(SystemExit, match="not LA8"):
        datadelete.main()

    buttons, header = _dd_files(fmt_sheet=1)
    img = write_img(
        tmp_path / "badsheet.bin",
        {
            datadelete.PKG_BUTTONS: pack_arc("DataDelete.arc", buttons),
            datadelete.PKG_HEADER: pack_arc("MultiWin.arc", header),
        },
    )
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
    with pytest.raises(SystemExit, match="not RGBA4444"):
        datadelete.main()

    buttons, header = _dd_files(fmt_header=8)
    img = write_img(
        tmp_path / "badhdr.bin",
        {
            datadelete.PKG_BUTTONS: pack_arc("DataDelete.arc", buttons),
            datadelete.PKG_HEADER: pack_arc("MultiWin.arc", header),
        },
    )
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
    with pytest.raises(SystemExit, match="not ETC1A4"):
        datadelete.main()

    buttons, _header = _dd_files()
    del buttons["timg/DD_Data_Txt_Big02.bclim"]
    img = write_img(
        tmp_path / "missbtn.bin",
        {datadelete.PKG_BUTTONS: pack_arc("DataDelete.arc", buttons)},
    )
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
    with pytest.raises(SystemExit, match="missing timg/DD_Data_Txt_Big02"):
        datadelete.main()

    img = _dd_img(tmp_path / "nomaster.bin")
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="missing Zhoumaru"):
        datadelete.main()

    img = _dd_img(tmp_path / "splice.bin")
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
    monkeypatch.setattr(datadelete, "compress_exact_with_gap_tune", must_pair)
    monkeypatch.setattr(datadelete, "splice_packages_into_img", boom_splice)
    with pytest.raises(SystemExit, match="splice failed"):
        datadelete.main()

    img = _dd_img(tmp_path / "verify.bin")
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)

    def bad_pair(data, n, *a, **k):
        return data, zlib.compress(b"no")

    monkeypatch.setattr(datadelete, "compress_exact_with_gap_tune", bad_pair)
    with pytest.raises(SystemExit, match="verify failed"):
        datadelete.main()


def test_datadelete_entry_and_pkg_mismatch(tmp_path, monkeypatch):
    png = repo_png("dd_m.png", 8, 8)

    def prep(name, mode):
        img = _dd_img(tmp_path / name)
        bind(monkeypatch, datadelete, tmp_path, img)
        monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
        monkeypatch.setattr(datadelete, "compress_exact_with_gap_tune", pair_then(monkeypatch, datadelete, mode))
        return img

    for mode in ("slot", "dec"):
        prep(f"{mode}.bin", mode)
        with pytest.raises(SystemExit, match="entry mismatch"):
            datadelete.main()

    img = _dd_img(tmp_path / "arc.bin")
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
    monkeypatch.setattr(datadelete, "compress_exact_with_gap_tune", must_pair)
    wrap_second_pkg(monkeypatch, datadelete, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        datadelete.main()

    img = _dd_img(tmp_path / "dmst.bin")
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
    monkeypatch.setattr(datadelete, "compress_exact_with_gap_tune", must_pair)
    wrap_second_pkg(monkeypatch, datadelete, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        datadelete.main()

    # Header label missing, buttons already valid — second patch_pkg raises.
    buttons, _header = _dd_files()
    img = write_img(
        tmp_path / "misshdr.bin",
        {
            datadelete.PKG_BUTTONS: pack_arc("DataDelete.arc", buttons),
            datadelete.PKG_HEADER: pack_arc("MultiWin.arc", {"timg/other.bclim": zero_bclim(16, 16, 0xB)}),
        },
    )
    bind(monkeypatch, datadelete, tmp_path, img)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *a, **k: png)
    monkeypatch.setattr(datadelete, "compress_exact_with_gap_tune", must_pair)
    with pytest.raises(SystemExit, match="missing timg/Com_MultiWin"):
        datadelete.main()


# ---------------------------------------------------------------------------
# Title main menu
# ---------------------------------------------------------------------------


def _title_files(fmt: int = 8) -> dict[str, bytes]:
    return {
        path: noise_bclim(128, 32, fmt, 4000 + i)
        for i, (path, _en) in enumerate(title.LABELS)
    }


def _title_img(path: Path, fmt: int = 8, *, compressed: bool = True) -> Path:
    return write_img(path, {title.PKG: pack_arc("Title.arc", _title_files(fmt), compressed=compressed)})


def test_title_render_and_main(tmp_path, monkeypatch):
    assert title.render_label("Options").size == (100, 20)
    with pytest.raises(RuntimeError, match="cannot fit"):
        title.render_label("Data Management Communication", w=8, h=8)

    img = _title_img(tmp_path / "img.bin")
    before = img.read_bytes()
    bind(monkeypatch, title, tmp_path, img, tmp_path / "no-vanilla.bin")
    stub_zopfli(monkeypatch, title, 8)
    stub_pair(monkeypatch, title, "compress_exact_zopfli")
    assert title.main() == 0
    assert img.read_bytes() != before
    assert (title.OUT / "Title_btn02_t02_en.png").is_file()
    assert (title.ASSET / "Title_btn02_t06.png").is_file()

    # Vanilla file present: the other side of the source pick.
    live = _title_img(tmp_path / "live.bin")
    vanilla = _title_img(tmp_path / "van.bin")
    before_l = live.read_bytes()
    bind(monkeypatch, title, tmp_path, live, vanilla)
    stub_zopfli(monkeypatch, title, 8)
    stub_pair(monkeypatch, title, "compress_exact_zopfli")
    assert title.main() == 0
    assert live.read_bytes() != before_l


def test_title_errors(tmp_path, monkeypatch):
    bind(monkeypatch, title, tmp_path, tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        title.main()

    img = _title_img(tmp_path / "img.bin")
    bind(monkeypatch, title, tmp_path, img)
    monkeypatch.setattr(title, "UI_FONT", tmp_path / "no-font.ttf")
    with pytest.raises(SystemExit, match="missing UI font"):
        title.main()

    files = _title_files()
    del files["timg/Title_btn02_t01.bclim"]
    img = write_img(tmp_path / "miss.bin", {title.PKG: pack_arc("Title.arc", files)})
    bind(monkeypatch, title, tmp_path, img)
    with pytest.raises(SystemExit, match="missing timg/Title_btn02_t01"):
        title.main()

    img = _title_img(tmp_path / "bad.bin", fmt=1)
    bind(monkeypatch, title, tmp_path, img)
    with pytest.raises(ValueError, match="RGBA4444"):
        title.main()

    img = _title_img(tmp_path / "over.bin")
    bind(monkeypatch, title, tmp_path, img)
    stub_zopfli(monkeypatch, title, 9_000_000)
    with pytest.raises(SystemExit, match="exceeds slot"):
        title.main()

    img = _title_img(tmp_path / "boom.bin")
    bind(monkeypatch, title, tmp_path, img)
    stub_zopfli(monkeypatch, title, 8)

    def boom(*_a, **_k):
        raise RuntimeError("zopfli-miss")

    stub_pair(monkeypatch, title, "compress_exact_zopfli", boom)
    with pytest.raises(SystemExit, match="zopfli-miss"):
        title.main()

    img = _title_img(tmp_path / "verify.bin")
    bind(monkeypatch, title, tmp_path, img)
    stub_zopfli(monkeypatch, title, 8)
    stub_pair(monkeypatch, title, "compress_exact_zopfli", lambda d, n, *a, **k: (d, zlib.compress(b"no")))
    with pytest.raises(SystemExit, match="verify failed"):
        title.main()

    img = _title_img(tmp_path / "splice.bin")
    bind(monkeypatch, title, tmp_path, img)
    stub_zopfli(monkeypatch, title, 8)
    stub_pair(monkeypatch, title, "compress_exact_zopfli")
    monkeypatch.setattr(title, "splice_packages_into_img", boom_splice)
    with pytest.raises(SystemExit, match="splice failed"):
        title.main()

    for mode in ("slot", "dec"):
        img = _title_img(tmp_path / f"ent_{mode}.bin")
        bind(monkeypatch, title, tmp_path, img)
        stub_zopfli(monkeypatch, title, 8)
        stub_pair(monkeypatch, title, "compress_exact_zopfli", pair_then(monkeypatch, title, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            title.main()

    files = {path: zero_bclim(128, 32, 8) for path, _en in title.LABELS}
    raw = write_img(
        tmp_path / "unc.bin",
        {title.PKG: pack_arc("Title.arc", files, compressed=False)},
    )
    bind(monkeypatch, title, tmp_path, raw)
    stub_zopfli(monkeypatch, title, 8)
    stub_pair(monkeypatch, title, "compress_exact_zopfli")
    with pytest.raises(SystemExit, match="entry mismatch"):
        title.main()

    img = _title_img(tmp_path / "arc.bin")
    bind(monkeypatch, title, tmp_path, img)
    stub_zopfli(monkeypatch, title, 8)
    stub_pair(monkeypatch, title, "compress_exact_zopfli")
    wrap_second_pkg(monkeypatch, title, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        title.main()

    img = _title_img(tmp_path / "dmst.bin")
    bind(monkeypatch, title, tmp_path, img)
    stub_zopfli(monkeypatch, title, 8)
    stub_pair(monkeypatch, title, "compress_exact_zopfli")
    wrap_second_pkg(monkeypatch, title, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        title.main()


# ---------------------------------------------------------------------------
# Communication settings header
# ---------------------------------------------------------------------------


def _commu_files(fmt: int = 0xB) -> dict[str, bytes]:
    return {
        "timg/Com_M_Sel_Plate_Text04_04_00.bclim": noise_bclim(144, 28, fmt, 51),
        "timg/Com_M_Sel_Btn_Text04_04_00.bclim": noise_bclim(246, 48, fmt, 52),
    }


def _commu_img(path: Path, fmt: int = 0xB, *, compressed: bool = True) -> Path:
    return write_img(path, {commu.PKG: pack_arc("NCommonMSel.arc", _commu_files(fmt), compressed=compressed)})


def test_commu_render_edges(tmp_path, monkeypatch):
    plate = commu.render_gallery_plate(160, 32, 14)
    assert plate.size == (160, 32)
    tight = commu.render_gallery_plate(48, 12, 14)
    assert tight.size == (48, 12)
    blank = write_png(tmp_path / "blank.png", 32, 16, color=(0, 0, 0, 0))
    # write_png paints an opaque pixel; force a fully empty master.
    Image.new("RGBA", (32, 16), (0, 0, 0, 0)).save(blank)
    monkeypatch.setattr(commu, "PLATE_MASTER", blank)
    with pytest.raises(RuntimeError, match="empty plate"):
        commu.render_gallery_plate(64, 28, 14)

    label = commu.render_label(
        "OK", 120, 36, 16, commu.ROW_FONT, 0, (255, 255, 255)
    )
    assert label.size == (120, 36)
    with pytest.raises(RuntimeError, match="cannot fit"):
        commu.render_label("Communication Settings " * 4, 24, 16, 10, commu.ROW_FONT, 0, (1, 1, 1))
    # Spaces often have no coverage above the glyph threshold.
    try:
        spaced = commu.render_label(" ", 40, 24, 12, commu.ROW_FONT, 0, (255, 255, 255))
        assert spaced.size == (40, 24)
    except RuntimeError as exc:
        assert "cannot fit" in str(exc)


def test_commu_main(tmp_path, monkeypatch):
    img = _commu_img(tmp_path / "img.bin")
    before = img.read_bytes()
    paths = bind(monkeypatch, commu, tmp_path, img)
    inst = instance_copy(paths["AZAHAR_INSTANCES"], "b", before)
    stub_pair(monkeypatch, commu, "try_fast_exact_slot")
    assert commu.main() is None
    assert img.read_bytes() != before
    assert inst.read_bytes() != before
    assert (commu.OUT / "Com_M_Sel_Plate_Text04_04_00.png").is_file()

    img2 = _commu_img(tmp_path / "img2.bin")
    bind(monkeypatch, commu, tmp_path, img2)
    stub_pair(monkeypatch, commu, "try_fast_exact_slot", lambda *_a, **_k: None)
    stub_pair(monkeypatch, commu, "compress_exact_zopfli")
    assert commu.main() is None


def test_commu_errors(tmp_path, monkeypatch):
    paths = bind(monkeypatch, commu, tmp_path, tmp_path / "missing.bin")
    with pytest.raises(FileNotFoundError):
        commu.main()

    empty = tmp_path / "empty.bin"
    empty.write_bytes(fi.img({0: pack_arc("X.arc", {"a.bin": b"a"})}, count=commu.PKG + 1))
    bind(monkeypatch, commu, tmp_path, empty)
    with pytest.raises(SystemExit, match="missing"):
        commu.main()

    bad = _commu_img(tmp_path / "bad.bin", fmt=8)
    bind(monkeypatch, commu, tmp_path, bad)
    with pytest.raises(SystemExit, match="expected ETC1A4"):
        commu.main()

    files = _commu_files()
    del files["timg/Com_M_Sel_Btn_Text04_04_00.bclim"]
    img = write_img(tmp_path / "miss.bin", {commu.PKG: pack_arc("NCommonMSel.arc", files)})
    bind(monkeypatch, commu, tmp_path, img)
    with pytest.raises(SystemExit, match="missing timg/Com_M_Sel_Btn"):
        commu.main()

    img = _commu_img(tmp_path / "grown.bin")
    bind(monkeypatch, commu, tmp_path, img)
    real = commu.DarcArchive

    class Grow(real):
        def replace_same_size(self, entry, new):
            super().replace_same_size(entry, new)
            if not getattr(self, "_grew", False):
                self.data.extend(b"\x00")
                self._grew = True

    monkeypatch.setattr(commu, "DarcArchive", Grow)
    with pytest.raises(SystemExit, match="ARC length changed"):
        commu.main()

    img = _commu_img(tmp_path / "len.bin")
    paths = bind(monkeypatch, commu, tmp_path, img)
    stub_pair(monkeypatch, commu, "try_fast_exact_slot")
    short = instance_copy(
        paths["AZAHAR_INSTANCES"],
        "c",
        fi.img({0: pack_arc("X.arc", {"a.bin": b"a"})}, count=commu.PKG + 1),
    )
    with pytest.raises(SystemExit, match="length"):
        commu.main()
    assert short.is_file()

    img = _commu_img(tmp_path / "verify.bin")
    bind(monkeypatch, commu, tmp_path, img)
    stub_pair(monkeypatch, commu, "try_fast_exact_slot", lambda d, n, *a, **k: (d, zlib.compress(b"no")))
    with pytest.raises(SystemExit, match="verify failed"):
        commu.main()

    img = _commu_img(tmp_path / "splice.bin")
    bind(monkeypatch, commu, tmp_path, img)
    stub_pair(monkeypatch, commu, "try_fast_exact_slot")
    monkeypatch.setattr(commu, "splice_packages_into_img", boom_splice)
    with pytest.raises(SystemExit, match="splice failed"):
        commu.main()

    for mode in ("slot", "dec"):
        img = _commu_img(tmp_path / f"ent_{mode}.bin")
        bind(monkeypatch, commu, tmp_path, img)
        stub_pair(monkeypatch, commu, "try_fast_exact_slot", pair_then(monkeypatch, commu, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            commu.main()

    files = {k: zero_bclim(64, 32, 0xB) for k in _commu_files()}
    # Logical sizes must stay valid for the renderers, so keep real sizes.
    files = {
        "timg/Com_M_Sel_Plate_Text04_04_00.bclim": zero_bclim(144, 28, 0xB),
        "timg/Com_M_Sel_Btn_Text04_04_00.bclim": zero_bclim(246, 48, 0xB),
    }
    raw = write_img(tmp_path / "unc.bin", {commu.PKG: pack_arc("NCommonMSel.arc", files, compressed=False)})
    bind(monkeypatch, commu, tmp_path, raw)
    stub_pair(monkeypatch, commu, "try_fast_exact_slot")
    with pytest.raises(SystemExit, match="entry mismatch"):
        commu.main()

    img = _commu_img(tmp_path / "arc.bin")
    bind(monkeypatch, commu, tmp_path, img)
    stub_pair(monkeypatch, commu, "try_fast_exact_slot")
    wrap_second_pkg(monkeypatch, commu, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        commu.main()

    img = _commu_img(tmp_path / "dmst.bin")
    bind(monkeypatch, commu, tmp_path, img)
    stub_pair(monkeypatch, commu, "try_fast_exact_slot")
    wrap_second_pkg(monkeypatch, commu, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        commu.main()


# ---------------------------------------------------------------------------
# Profile header + atlas
# ---------------------------------------------------------------------------


def _profile_header_files(fmt: int = 1) -> dict[str, bytes]:
    return {
        "timg/Com_M_Sel_Plate_Text01_00_00.bclim": noise_bclim(144, 32, fmt, 70),
    }


def _profile_atlas_files() -> dict[str, bytes]:
    files = {
        "timg/Profile_Info_Profile_t.bclim": noise_bclim(256, 192, 3, 81),
        "timg/Profile_Info_Call01_t.bclim": noise_bclim(256, 160, 3, 82),
        "timg/Profile_Info_Call02_t.bclim": noise_bclim(256, 104, 3, 83),
        "timg/Profile_Info_Check03.bclim": noise_bclim(240, 168, 3, 84),
        "timg/Profile_Info_Check02.bclim": noise_bclim(76, 24, 8, 85),
        "timg/Profile_Btn_Change_Obj.bclim": noise_bclim(96, 32, 8, 86),
        "blyt/Lyt_Prf_Btn_ML.bclyt": bclyt(
            ["Pos_Btn_C01_01", "Pos_Btn_C01_02", "Pos_Btn_C01_03", "Pos_Btn_C01_04"]
        ),
        "blyt/Lyt_Prf_Btn_Change.bclyt": bclyt(["Pos_Btn_Change"]),
    }
    for i, stem in enumerate(profile.REGION_BUTTONS):
        files[f"timg/{stem}.bclim"] = noise_bclim(32, 24, 8, 90 + i)
    return files


def _profile_img(path: Path) -> Path:
    return write_img(
        path,
        {
            profile.PKG_HEADER: pack_arc("MSel.arc", _profile_header_files()),
            profile.PKG_ATLAS: pack_arc("Profile.arc", _profile_atlas_files()),
        },
    )


def _small_profile_pkg(path: Path, pkg_id: int) -> Path:
    files = {"timg/only.bclim": zero_bclim(16, 16, 1), "timg/two.bclim": zero_bclim(16, 16, 1)}
    return write_img(path, {pkg_id: pack_arc("Small.arc", files)})


def test_profile_header_trials(tmp_path, monkeypatch):
    for name in ("fit", "over", "miss"):
        (tmp_path / name).mkdir()
    raw = _profile_header_files()["timg/Com_M_Sel_Plate_Text01_00_00.bclim"]
    bind(monkeypatch, profile, tmp_path, tmp_path / "unused.bin")
    profile.OUT.mkdir(parents=True, exist_ok=True)
    arc = fi.darc({"timg/Com_M_Sel_Plate_Text01_00_00.bclim": raw})
    monkeypatch.setattr(profile, "zopfli_zlib", LenZopfli(lambda n, _d: 10 if n == 4 else 99_999))
    patched = profile.patch_header_arc(arc, tmp_path / "fit", slot_len=50)
    assert patched.startswith(b"darc")
    assert (profile.OUT / "Profile_a8.png").is_file()

    monkeypatch.setattr(profile, "zopfli_zlib", LenZopfli(99_999))
    with pytest.raises(SystemExit, match="exceeds slot"):
        profile.patch_header_arc(arc, tmp_path / "over", slot_len=20)

    bare = fi.darc({"timg/other.bclim": raw})
    monkeypatch.setattr(profile, "zopfli_zlib", LenZopfli(10))
    with pytest.raises(SystemExit, match="missing"):
        profile.patch_header_arc(bare, tmp_path / "miss", slot_len=50)


def test_profile_rgb_and_labels(tmp_path, monkeypatch):
    for name in ("call", "c3", "c3b", "c2", "c2b", "c2c", "atlas", "atlas2", "atlas3"):
        (tmp_path / name).mkdir()
    bind(monkeypatch, profile, tmp_path, tmp_path / "unused.bin")
    profile.OUT.mkdir(parents=True, exist_ok=True)
    rgb = noise_bclim(64, 40, 3, 3)
    decoded, w, h = profile.decode_rgb565(rgb)
    assert (w, h) == (64, 40) and decoded.size == (64, 40)

    wide = fi.bclim(240, 104, 3, pixels=random.Random(4).randbytes(256 * 128 * 2))
    im, w, h = profile.decode_rgb565(wide)
    assert (w, h) == (240, 104) and im.size == (240, 104)

    square = fi.bclim(200, 180, 3, pixels=random.Random(5).randbytes(256 * 256 * 2))
    im, w, h = profile.decode_rgb565(square)
    assert (w, h) == (200, 180) and im.size == (200, 180)

    other = noise_bclim(48, 24, 8, 6)
    with pytest.raises(SystemExit, match="expected RGB565"):
        profile.decode_rgb565(other)

    soft = profile.render_hard_label(40, 16, "Hi")
    assert soft.size == (40, 16)
    # Empty text still returns a plate (peak stays 0).
    blank = profile.render_hard_label(24, 12, "")
    assert blank.size == (24, 12)
    with pytest.raises(RuntimeError, match="cannot fit"):
        profile.render_hard_label(4, 4, "Last Name Hometown", prefer_size=15)

    call = noise_bclim(256, 160, 3, 9)
    out = profile.make_call_en(call, profile.CALL01_LABELS, tmp_path / "call", "Profile_Info_Call01_t")
    assert len(out) == len(call)

    check = noise_bclim(240, 168, 3, 10)
    made = profile.make_check03_en(check, tmp_path / "c3")
    assert len(made) == len(check)
    with pytest.raises(SystemExit, match="Check03 size"):
        profile.make_check03_en(noise_bclim(32, 32, 3, 11), tmp_path / "c3b")

    chip = noise_bclim(76, 24, 8, 12)
    made = profile.make_check02_en(chip, tmp_path / "c2")
    assert len(made) == len(chip)
    with pytest.raises(SystemExit, match="Check02"):
        profile.make_check02_en(noise_bclim(32, 32, 8, 13), tmp_path / "c2b")
    with pytest.raises(SystemExit, match="Check02"):
        profile.make_check02_en(fi.bclim(76, 24, 4, pixels=b"\x00" * 64), tmp_path / "c2c")

    atlas = noise_bclim(256, 192, 3, 14)
    made = profile.make_atlas_en(atlas, tmp_path / "atlas")
    assert len(made) == len(atlas)
    preview = write_png(profile.PREV / "Profile_Info_Profile_t.png", 32, 32)
    assert preview.is_file()
    made2 = profile.make_atlas_en(atlas, tmp_path / "atlas2")
    assert len(made2) == len(atlas)
    with pytest.raises(SystemExit, match="not RGB565"):
        profile.make_atlas_en(noise_bclim(32, 32, 8, 15), tmp_path / "atlas3")


def test_profile_regions_and_gap(tmp_path, monkeypatch):
    for name in ("reg", "reg2", "reg3", "reg4"):
        (tmp_path / name).mkdir()
    bind(monkeypatch, profile, tmp_path, tmp_path / "unused.bin")
    profile.OUT.mkdir(parents=True, exist_ok=True)
    small = repo_png("region_small.png", 4, 4)
    big = repo_png("region_big.png", 80, 40)
    native = profile.fit_region_png(small, (32, 24), tmp_path / "native.png")
    assert native == small
    fitted = profile.fit_region_png(big, (32, 24), tmp_path / "fitted.png")
    assert fitted == tmp_path / "fitted.png" and fitted.is_file()

    from darcutil import DarcArchive

    files = {f"timg/{stem}.bclim": noise_bclim(32, 24, 8, i) for i, stem in enumerate(profile.REGION_BUTTONS)}
    monkeypatch.setattr(profile, "find_ui_png", lambda *_a, **_k: small)
    profile.patch_region_buttons(DarcArchive(fi.darc(files)), tmp_path / "reg")
    monkeypatch.setattr(profile, "find_ui_png", lambda *_a, **_k: None)
    with pytest.raises(SystemExit, match="missing Zhoumaru"):
        profile.patch_region_buttons(DarcArchive(fi.darc(files)), tmp_path / "reg2")

    bad = dict(files)
    stem0 = profile.REGION_BUTTONS[0]
    bad[f"timg/{stem0}.bclim"] = noise_bclim(32, 24, 1, 3)
    monkeypatch.setattr(profile, "find_ui_png", lambda *_a, **_k: small)
    with pytest.raises(SystemExit, match="not RGBA4444"):
        profile.patch_region_buttons(DarcArchive(fi.darc(bad)), tmp_path / "reg3")

    missing = dict(files)
    del missing[f"timg/{stem0}.bclim"]
    with pytest.raises(SystemExit, match="missing"):
        profile.patch_region_buttons(DarcArchive(fi.darc(missing)), tmp_path / "reg4")

    data = fi.darc({"a.bin": b"a" * 8, "b.bin": b"b" * 8})
    runs = profile.interfile_zero_gaps(data)
    assert runs
    assert profile.apply_gap_pad(data, 0, b"\xff" * 4) == data
    assert profile.apply_gap_pad(data, runs[0][0], b"\x11" * 80) != data
    assert profile.interfile_zero_gaps(data, min_len=10**6) == []
    blob = b"prof-gap" * 30
    assert any(profile.compress_exact_empty_blocks(blob, n) for n in range(20, len(blob) + 70))
    assert profile.compress_exact_empty_blocks(blob, 3) is None


def test_profile_zopfli_helper(monkeypatch):
    data = fi.darc({"a.bin": b"profile" * 3, "b.bin": b"atlas" * 3})
    monkeypatch.setattr(profile, "zopfli_zlib", LenZopfli(80))
    with pytest.raises(SystemExit, match="exceeds slot"):
        profile.compress_exact_zopfli(data, 10)

    monkeypatch.setattr(profile, "zopfli_zlib", LenZopfli(20))
    tuned, slot = profile.compress_exact_zopfli(data, 20)
    assert tuned == data and len(slot) == 20

    state = {"phase": "base"}

    def search_eq(payload):
        if state["phase"] == "base":
            state["phase"] = "search"
            return b"a" * 8
        return b"q" * 30

    monkeypatch.setattr(profile, "zopfli_zlib", type("Z", (), {"compress": staticmethod(search_eq)}))
    tuned, slot = profile.compress_exact_zopfli(data, 30)
    assert len(slot) == 30 and len(tuned) == len(data)

    monkeypatch.setattr(profile, "interfile_zero_gaps", lambda *_a, **_k: [])
    monkeypatch.setattr(profile, "zopfli_zlib", LenZopfli(8))
    target = next(
        n
        for n in range(len(data), len(data) + 120)
        if profile.compress_exact_empty_blocks(data, n)
    )
    tuned, slot = profile.compress_exact_zopfli(data, target)
    assert zlib.decompress(slot) == tuned


def test_profile_zopfli_scan_and_give_up(monkeypatch, tmp_path):
    data = fi.darc({"a.bin": b"aa" * 8, "b.bin": b"bb" * 8})
    calls = {"n": 0}

    def always_over(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return b"a" * 10
        return b"b" * 100

    monkeypatch.setattr(profile, "zopfli_zlib", type("Z", (), {"compress": staticmethod(always_over)}))
    with pytest.raises(SystemExit, match="cannot reach slot"):
        profile.compress_exact_zopfli(data, 40)

    # Search stays short, fine scan emits a real exact stream, else gap-tune.
    cap = sum(sz for sz, _ in profile.interfile_zero_gaps(data, min_len=8))
    search_n = 0
    lo, hi = 0, cap
    while lo <= hi:
        mid = (lo + hi) // 2
        search_n += 1
        lo = mid + 1
    calls["n"] = 0
    target = next(n for n in range(len(data) + 30, len(data) + 160) if exact_zlib(data, n))

    def scan(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return b"a" * 8
        if calls["n"] <= 1 + search_n:
            return b"s" * 12
        slot = exact_zlib(payload, target)
        return slot if slot is not None else b"s" * 12

    monkeypatch.setattr(profile, "zopfli_zlib", type("Z", (), {"compress": staticmethod(scan)}))
    tuned, slot = profile.compress_exact_zopfli(data, target)
    assert len(slot) == target
    assert zlib.decompress(slot) == tuned


def test_profile_package_paths(tmp_path, monkeypatch):
    img = _small_profile_pkg(tmp_path / "img.bin", profile.PKG_HEADER)
    before = img.read_bytes()
    bind(monkeypatch, profile, tmp_path, img)
    stub_pair(monkeypatch, profile, "try_fast_exact_slot")
    profile.patch_package(profile.PKG_HEADER, lambda arc, tmp, slot_len=0: arc, use_zopfli=True)
    assert img.read_bytes() != before

    img2 = _small_profile_pkg(tmp_path / "img2.bin", profile.PKG_HEADER)
    before2 = img2.read_bytes()
    bind(monkeypatch, profile, tmp_path, img2)
    stub_pair(monkeypatch, profile, "try_fast_exact_slot", lambda *_a, **_k: None)
    stub_pair(monkeypatch, profile, "shared_exact_zopfli")
    profile.patch_package(profile.PKG_HEADER, lambda arc, tmp, slot_len=0: arc, use_zopfli=True)
    assert img2.read_bytes() != before2
    assert (profile.OUT / "img_data" / f"new_{profile.PKG_HEADER:04d}").is_file()

    img3 = _small_profile_pkg(tmp_path / "img3.bin", profile.PKG_ATLAS)
    before3 = img3.read_bytes()
    bind(monkeypatch, profile, tmp_path, img3)
    stub_pair(monkeypatch, profile, "compress_exact_with_gap_tune")
    profile.patch_package(profile.PKG_ATLAS, lambda arc, tmp, slot_len=0: arc, use_zopfli=False)
    assert img3.read_bytes() != before3

    img4 = _small_profile_pkg(tmp_path / "img4.bin", profile.PKG_HEADER)
    bind(monkeypatch, profile, tmp_path, img4)
    stub_pair(monkeypatch, profile, "try_fast_exact_slot", lambda d, n, *a, **k: (d, zlib.compress(b"no")))
    with pytest.raises(SystemExit, match="verify failed"):
        profile.patch_package(profile.PKG_HEADER, lambda arc, tmp, slot_len=0: arc, use_zopfli=True)

    for mode in ("slot", "dec"):
        img_m = _small_profile_pkg(tmp_path / f"p_{mode}.bin", profile.PKG_HEADER)
        bind(monkeypatch, profile, tmp_path, img_m)
        stub_pair(monkeypatch, profile, "try_fast_exact_slot", pair_then(monkeypatch, profile, mode))
        with pytest.raises(SystemExit, match="entry mismatch"):
            profile.patch_package(profile.PKG_HEADER, lambda arc, tmp, slot_len=0: arc, use_zopfli=True)

    img5 = _small_profile_pkg(tmp_path / "img5.bin", profile.PKG_HEADER)
    bind(monkeypatch, profile, tmp_path, img5)
    stub_pair(monkeypatch, profile, "try_fast_exact_slot")
    monkeypatch.setattr(profile, "splice_packages_into_img", boom_splice)
    with pytest.raises(SystemExit, match="splice"):
        profile.patch_package(profile.PKG_HEADER, lambda arc, tmp, slot_len=0: arc, use_zopfli=True)

    img6 = _small_profile_pkg(tmp_path / "img6.bin", profile.PKG_HEADER)
    bind(monkeypatch, profile, tmp_path, img6)
    stub_pair(monkeypatch, profile, "try_fast_exact_slot")
    wrap_second_pkg(monkeypatch, profile, "arc")
    with pytest.raises(SystemExit, match="ARC mismatch"):
        profile.patch_package(profile.PKG_HEADER, lambda arc, tmp, slot_len=0: arc, use_zopfli=True)

    img7 = _small_profile_pkg(tmp_path / "img7.bin", profile.PKG_HEADER)
    bind(monkeypatch, profile, tmp_path, img7)
    stub_pair(monkeypatch, profile, "try_fast_exact_slot")
    wrap_second_pkg(monkeypatch, profile, "dmst")
    with pytest.raises(SystemExit, match="DMST changed"):
        profile.patch_package(profile.PKG_HEADER, lambda arc, tmp, slot_len=0: arc, use_zopfli=True)


def test_profile_main_and_missing_chain(tmp_path, monkeypatch):
    img = _profile_img(tmp_path / "img.bin")
    before = img.read_bytes()
    paths = bind(monkeypatch, profile, tmp_path, img)
    inst = instance_copy(paths["AZAHAR_INSTANCES"], "b", before)
    stub_zopfli(monkeypatch, profile, 8)
    stub_pair(monkeypatch, profile, "try_fast_exact_slot")
    stub_pair(monkeypatch, profile, "shared_exact_zopfli")
    stub_pair(monkeypatch, profile, "compress_exact_with_gap_tune")
    small = repo_png("prof_small.png", 4, 4)
    big = repo_png("prof_big.png", 90, 50)

    def find(_folders, stem, _size=None):
        if stem.endswith("01"):
            return small
        return big

    monkeypatch.setattr(profile, "find_ui_png", find)
    assert profile.main() is None
    assert img.read_bytes() != before
    assert inst.read_bytes() != before

    bind(monkeypatch, profile, tmp_path, tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        profile.main()

    def boom_at(fragment: str):
        files = _profile_atlas_files()
        # Drop the first file whose name contains fragment, keeping earlier ones.
        for key in list(files):
            if fragment in key:
                del files[key]
                break
        arc = fi.darc(files)
        with pytest.raises(SystemExit, match="missing"):
            profile.patch_atlas_arc(arc, tmp_path / "chain", slot_len=0)

    bind(monkeypatch, profile, tmp_path, tmp_path / "unused.bin")
    monkeypatch.setattr(profile, "find_ui_png", lambda *_a, **_k: small)
    monkeypatch.setattr(profile, "make_atlas_en", lambda raw, tmp: raw)
    monkeypatch.setattr(profile, "make_call_en", lambda raw, labels, tmp, stem: raw)
    monkeypatch.setattr(profile, "make_check03_en", lambda raw, tmp: raw)
    monkeypatch.setattr(profile, "make_check02_en", lambda raw, tmp: raw)
    boom_at("Profile_Info_Profile_t")
    boom_at("Call01")
    boom_at("Call02")
    boom_at("Check03")
    boom_at("Check02")
    boom_at("Profile_Btn_Com02_Text01")


def test_profile_gap_tune_second_pass(monkeypatch):
    data = fi.darc({"a.bin": b"p" * 12, "b.bin": b"q" * 12})
    real = profile.compress_exact_empty_blocks
    target = next(n for n in range(len(data), len(data) + 140) if real(data, n))
    cap = sum(sz for sz, _ in profile.interfile_zero_gaps(data))
    step = max(1, cap // 400) if cap else 1
    n_first = len(range(cap, -1, -step))
    state = {"n": 0}

    def flaky(payload, n):
        state["n"] += 1
        if state["n"] <= n_first:
            return None
        return real(payload, n)

    monkeypatch.setattr(profile, "compress_exact_empty_blocks", flaky)
    tuned, slot = profile.compress_exact_with_gap_tune(data, target)
    assert state["n"] > n_first
    assert zlib.decompress(slot) == tuned

    monkeypatch.setattr(profile, "compress_exact_empty_blocks", lambda *_a, **_k: None)
    with pytest.raises(SystemExit, match="could not build exact zlib"):
        profile.compress_exact_with_gap_tune(data, target)


def test_leftover_branches(tmp_path, monkeypatch):
    """Branches the happy-path sizes and the first zlib attempt never touch."""
    with pytest.raises(RuntimeError, match="cannot fit label"):
        display.render_label(3, 16, "Help Display")
    with pytest.raises(RuntimeError, match="cannot fit button"):
        display.render_button(4, 20, "Every Time")
    with pytest.raises(RuntimeError, match="cannot fit label"):
        sound.render_label(3, 16, "Mic Sensitivity")
    with pytest.raises(RuntimeError, match="cannot fit button"):
        sound.render_button(4, 20, "Voice")
    with pytest.raises(RuntimeError, match="cannot fit header"):
        datadelete.render_header_label(4, 16, "Delete Save Data")

    tight = fi.darc({"a.bin": b"aa", "b.bin": b"bb"}, align=1)
    assert datadelete.interfile_zero_gaps(tight) == []
    assert profile.interfile_zero_gaps(tight) == []
    assert profile.apply_gap_pad(tight, 4, b"\xff" * 8) == tight
    trailed = tight + b"\x00" * 16
    assert datadelete.interfile_zero_gaps(trailed)
    assert profile.interfile_zero_gaps(trailed)
    wide = fi.darc({"a.bin": b"a" * 8, "b.bin": b"b" * 8, "c.bin": b"c" * 8})
    pruns = profile.interfile_zero_gaps(wide)
    assert profile.apply_gap_pad(wide, 0, b"\xff" * 8) == wide
    assert profile.apply_gap_pad(wide, pruns[0][0] + 1, b"\x11" * 400) != wide

    raw_a8 = fi.bclim(12, 8, 1, pixels=bytes(12 * 8))
    canvas, w, h = profile.decode_a8(raw_a8)
    assert (w, h) == (12, 8) and canvas.shape == (8, 12)
    raw_rgb = fi.bclim(12, 8, 3, pixels=bytes(12 * 8 * 2))
    rgb, w, h = profile.decode_rgb565(raw_rgb)
    assert (w, h) == (12, 8) and rgb.size == (12, 8)

    data = b"branch" * 30
    target = next(n for n in range(len(data), len(data) + 100) if exact_zlib(data, n))
    real_co = zlib.compressobj
    real_dec = zlib.decompressobj
    state = {"n": 0}

    def wrapped(*_a, **_k):
        state["n"] += 1
        if state["n"] <= 10:
            class Bad:
                def compress(self, _d):
                    return b"\x00" * 20000

                def flush(self, _mode=None):
                    return b""

            return Bad()
        if state["n"] <= 13:
            raise zlib.error("strategy")
        return real_co(*_a, **_k)

    monkeypatch.setattr(zlib, "compressobj", wrapped)
    assert display.compress_exact_empty_blocks(data, target) is not None
    state["n"] = 0
    assert sound.compress_exact_empty_blocks(data, target) is not None
    monkeypatch.setattr(zlib, "compressobj", real_co)

    class Boom:
        def decompress(self, _data):
            raise zlib.error("boom")

        unused_data = b""
        eof = True

    class Dirty:
        def decompress(self, _data):
            return b""

        unused_data = b"x"
        eof = False

    for dec in (Boom, Dirty):
        monkeypatch.setattr(zlib, "decompressobj", lambda dec=dec: dec())
        for mod in (display, sound, datadelete, profile):
            assert mod.compress_exact_empty_blocks(data, target) is None
    monkeypatch.setattr(zlib, "decompressobj", real_dec)

    arc = fi.darc({"a.bin": b"aa" * 8, "b.bin": b"bb" * 8})
    ztarget = next(n for n in range(len(arc) + 20, len(arc) + 140) if exact_zlib(arc, n))
    monkeypatch.setattr(profile, "zopfli_zlib", LenZopfli(8))
    tuned, slot = profile.compress_exact_zopfli(arc, ztarget)
    assert zlib.decompress(slot) == tuned

    cap = sum(sz for sz, _ in profile.interfile_zero_gaps(arc, min_len=8))
    search_n = 0
    lo, hi = 0, cap
    while lo <= hi:
        mid = (lo + hi) // 2
        search_n += 1
        lo = mid + 1
    calls = {"n": 0}
    decoy = next(
        (
            exact_zlib(payload, ztarget)
            for payload in (b"decoy-bytes", b"other-payload!!")
            if exact_zlib(payload, ztarget)
        ),
        None,
    )
    used = {"decoy": False}

    def scan(payload):
        calls["n"] += 1
        if calls["n"] <= 1 + search_n:
            return b"s" * 12
        if decoy is not None and not used["decoy"]:
            used["decoy"] = True
            return decoy
        found = exact_zlib(payload, ztarget)
        return found if found is not None else b"s" * 12

    monkeypatch.setattr(profile, "zopfli_zlib", type("Z", (), {"compress": staticmethod(scan)}))
    tuned, slot = profile.compress_exact_zopfli(arc, ztarget)
    assert len(slot) == ztarget and zlib.decompress(slot) == tuned

    img = _commu_img(tmp_path / "dup.bin")
    paths = bind(monkeypatch, commu, tmp_path, img)
    inst = instance_copy(paths["AZAHAR_INSTANCES"], "d", img.read_bytes())
    monkeypatch.setattr(commu, "MOD_IMG", inst)
    seen = commu._deploy_targets()
    assert seen.count(inst.resolve()) == 1

    pimg = tmp_path / "pimg.bin"
    pimg.write_bytes(b"not-an-img")
    paths = bind(monkeypatch, profile, tmp_path, pimg)
    pinst = instance_copy(paths["AZAHAR_INSTANCES"], "e", b"not-an-img")
    monkeypatch.setattr(profile, "MOD_IMG", pinst)
    assert profile._iter_splice_imgs().count(pinst.resolve()) == 1

    buttons, header = _dd_files()
    del buttons["timg/DD_data02.bclim"]
    missing_sheet = write_img(
        tmp_path / "missheet.bin",
        {
            datadelete.PKG_BUTTONS: pack_arc("DataDelete.arc", buttons),
            datadelete.PKG_HEADER: pack_arc("MultiWin.arc", header),
        },
    )
    bind(monkeypatch, datadelete, tmp_path, missing_sheet)
    png = repo_png("dd_sheet.png", 8, 8)
    monkeypatch.setattr(datadelete, "find_ui_png", lambda *_a, **_k: png)
    with pytest.raises(SystemExit, match="missing timg/DD_data02"):
        datadelete.main()

    img = _dd_img(tmp_path / "nosheet.bin")
    bind(monkeypatch, datadelete, tmp_path, img)

    def sheets_only(_folders, stem, _size=None):
        if stem.startswith("DD_data"):
            return None
        return png

    monkeypatch.setattr(datadelete, "find_ui_png", sheets_only)
    with pytest.raises(SystemExit, match="DD_data02"):
        datadelete.main()
