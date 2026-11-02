"""Line and branch coverage for chrome deploy scripts.

CI has no vanilla img.bin and no network. Packages come from tests/fake_img.py.
Zopfli / gap-tune searches are stubbed with a correctly sized zlib slot; the
patch and splice control flow still runs. Fonts are repo files only. Every
output path is under tmp_path.
"""

from __future__ import annotations

import random
import struct
import sys
import zlib
from pathlib import Path

import pytest
from PIL import Image

from conftest import ROOT, TOOLS, load_module

import fake_img as fi

GEOMANIST = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025" / "Geomanist-Regular.ttf"

# dsel before clock: clock binds set_pane_visible from this module object.
dsel = load_module("deploy_dsel_data_visible", TOOLS / "deploy_dsel_data_visible.py")
clock = load_module("deploy_clock_date_order_en", TOOLS / "deploy_clock_date_order_en.py")
header = load_module(
    "deploy_header_clock_ampm_en", TOOLS / "deploy_header_clock_ampm_en.py"
)
commu = load_module("deploy_commu_option_en", TOOLS / "deploy_commu_option_en.py")
camera = load_module("deploy_camera_filters_en", TOOLS / "deploy_camera_filters_en.py")
web_hub = load_module("deploy_web_hub_en", TOOLS / "deploy_web_hub_en.py")
card = load_module("deploy_card_name_labels_en", TOOLS / "deploy_card_name_labels_en.py")
weather = load_module("deploy_web_weather_en", TOOLS / "deploy_web_weather_en.py")
event = load_module("deploy_web_event_date_en", TOOLS / "deploy_web_event_date_en.py")
sms = load_module("deploy_sms_maildic_en", TOOLS / "deploy_sms_maildic_en.py")
myroom = load_module("deploy_myroom_main_en", TOOLS / "deploy_myroom_main_en.py")
cesa = load_module("deploy_cesa_en", TOOLS / "deploy_cesa_en.py")


def noise_bclim(w: int, h: int, fmt: int, seed: int = 1) -> bytes:
    from bclimutil import parse_bclim, rectangular_pot

    if fmt == 0xD:
        pot_w, pot_h = rectangular_pot(w, h)
        n = (pot_w * pot_h) // 2
        return fi.bclim(w, h, fmt, pixels=random.Random(seed).randbytes(n))
    blank = fi.bclim(w, h, fmt)
    n = len(parse_bclim(blank)[0])
    return fi.bclim(w, h, fmt, pixels=random.Random(seed).randbytes(n))


def noise_file(seed: int = 1, n: int = 4096) -> bytes:
    return random.Random(seed).randbytes(n)


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


def packed(files: dict[str, bytes], seed: int = 1) -> bytes:
    arc = fi.darc({**files, "zz_noise.bin": noise_file(seed)})
    return fi.package(
        [
            ("Data.arc", arc),
            ("meta.dmst", b"DMSTDATA!!", b"DMST", False),
        ]
    )


def write_img(path: Path, packages: dict[int, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fi.img(packages))


def retarget_sidecar(pkg: bytes) -> bytes:
    """Point the uncompressed sidecar at the ARC zlib slot."""
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


def bind(monkeypatch, tmp_path: Path, mod, img: Path, **extra):
    paths = fi.use_paths(
        monkeypatch,
        tmp_path,
        mod,
        MOD_IMG=img,
        VANILLA=img,
        _VANILLA=img,
        _FALLBACK_VANILLA=img,
        **extra,
    )
    if hasattr(mod, "compress_exact_zopfli"):
        monkeypatch.setattr(mod, "compress_exact_zopfli", lambda d, n: fast_exact(d, n))
    if hasattr(mod, "compress_to_exact_slot"):
        monkeypatch.setattr(mod, "compress_to_exact_slot", lambda d, n: fast_exact(d, n)[1])
    if hasattr(mod, "try_fast_exact_slot"):
        monkeypatch.setattr(mod, "try_fast_exact_slot", lambda d, n: fast_exact(d, n))
    if hasattr(mod, "FONT"):
        monkeypatch.setattr(mod, "FONT", GEOMANIST)
    return paths


def point_instances(monkeypatch, mod, img: Path, tmp_path: Path) -> Path:
    extra = tmp_path / f"inst_{mod.__name__}.bin"
    extra.write_bytes(img.read_bytes())
    missing = tmp_path / f"ghost_{mod.__name__}.bin"

    class _Root:
        def glob(self, _pattern):
            return [missing, img, extra]

        def is_dir(self):
            return True

    monkeypatch.setattr(mod, "AZAHAR_INSTANCES", _Root())
    monkeypatch.setattr(mod, "iter_deploy_targets", lambda primary: [primary.resolve()])
    monkeypatch.setattr(mod, "MOD_IMG", img)
    return extra


def arm_later_darc(monkeypatch):
    """After the slot is built, the next darc zlib.decompress grows by one byte."""
    armed = {"go": False}
    real = zlib.decompress

    def wrapped(data, *args, **kwargs):
        out = real(data, *args, **kwargs)
        if armed["go"] and isinstance(out, (bytes, bytearray)) and bytes(out)[:4] == b"darc":
            return bytes(out) + b"!"
        return out

    monkeypatch.setattr(zlib, "decompress", wrapped)
    return armed


def clyt(sections: list[bytes], header_size: int = 20) -> bytes:
    header = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, header_size, 0, 0, len(sections))
    if len(header) < header_size:
        header += b"\x00" * (header_size - len(header))
    blob = bytearray(header + b"".join(sections))
    struct.pack_into("<I", blob, 0x0C, len(blob))
    return bytes(blob)


def pane(tag: bytes, name: str, flag: int = 1, size: int = 0x50, **floats) -> bytes:
    sec = bytearray(size)
    sec[0:4] = tag
    struct.pack_into("<I", sec, 4, size)
    sec[8] = flag
    raw = name.encode("ascii")
    sec[12 : 12 + len(raw)] = raw
    for off, value in floats.items():
        struct.pack_into("<f", sec, int(off, 0), value)
    return bytes(sec)


def salty_pair() -> tuple[bytes, bytes]:
    from darcutil import DarcArchive

    clean = fi.darc({"a.bin": b"a" * 5, "b.bin": b"b" * 5}) + bytes(4)
    arc = bytearray(clean)
    a = DarcArchive(clean).find("a.bin")
    arc[a.offset + a.length] = 1
    arc[-1] = 2
    return clean, bytes(arc)


# ---------------------------------------------------------------------------
# Communication settings (pkg 4185)
# ---------------------------------------------------------------------------


def _pan1(name: str, y: float = 10.0) -> bytes:
    sec = bytearray(0x54)
    sec[0:4] = b"pan1"
    struct.pack_into("<I", sec, 4, len(sec))
    sec[8] = 1
    sec[0x0C : 0x0C + len(name)] = name.encode("ascii")
    struct.pack_into("<f", sec, 0x28, y)
    return bytes(sec)


def _commu_files() -> dict[str, bytes]:
    rows = {
        f"timg/{stem}.bclim": noise_bclim(128, 32, 8, seed=i + 3)
        for i, stem in enumerate(commu.ROW_TEXT)
    }
    # Smaller than the Zhoumaru help master so help_from_alpha resizes.
    rows["timg/Commu_Op_Text01.bclim"] = noise_bclim(128, 32, 5, seed=9)
    rows["blyt/Lyt_Commu_Option.bclyt"] = b"".join(
        _pan1(name) for name in ("Pos_Text02", *commu.HIDDEN_PANES)
    )
    return rows


def test_commu_render_and_pane_edges(tmp_path, monkeypatch):
    im = commu.render_row("StreetPass", 128, 32)
    assert im.size == (128, 32) and im.getchannel("A").getbbox()
    with pytest.raises(RuntimeError, match="cannot fit"):
        commu.render_row("Supercalifragilisticexpialidocious", 24, 16)
    with pytest.raises(RuntimeError, match="cannot fit"):
        commu.render_row("", 64, 32)

    import numpy as np

    def right_edge(cond):
        return (np.array([0]), np.array([cond.shape[1] - 1]))

    monkeypatch.setattr(commu.np, "where", right_edge)
    with pytest.raises(RuntimeError, match="cannot fit"):
        commu.render_row("A", 128, 32)

    same = tmp_path / "help.png"
    Image.new("RGBA", (32, 16), (1, 2, 3, 255)).save(same)
    exact = commu.help_from_alpha(same, 32, 16)
    assert exact.size == (32, 16)
    resized = commu.help_from_alpha(commu.HELP_PNG, 64, 16)
    assert resized.size == (64, 16)

    dup = _pan1("Pos_Text03") + _pan1("Pos_Text03")
    with pytest.raises(SystemExit, match="found 2"):
        commu._find_pane(dup, "Pos_Text03")


def test_commu_targets_and_main(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {commu.PKG: packed(_commu_files())})
    bind(monkeypatch, tmp_path, commu, img)
    extra = point_instances(monkeypatch, commu, img, tmp_path)
    assert extra.resolve() in commu._deploy_targets()
    before = img.read_bytes()
    assert commu.main() is None
    assert img.read_bytes() != before
    assert (commu.OUT / "Commu_Op_Text02.png").is_file()

    # Fast path misses; zopfli stub still returns an exact slot.
    write_img(img, {commu.PKG: packed(_commu_files(), seed=2)})
    bind(monkeypatch, tmp_path, commu, img)
    monkeypatch.setattr(commu, "try_fast_exact_slot", lambda d, n: None)
    assert commu.main() is None


def test_commu_main_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {commu.PKG: packed(_commu_files())})
    bind(monkeypatch, tmp_path, commu, img)

    monkeypatch.setattr(commu, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        commu.main()

    bind(monkeypatch, tmp_path, commu, img)
    spot = commu.SPOTPASS_PNG
    monkeypatch.setattr(commu, "SPOTPASS_PNG", tmp_path / "no-spot.png")
    with pytest.raises(SystemExit, match="Zhoumaru"):
        commu.main()
    monkeypatch.setattr(commu, "SPOTPASS_PNG", spot)

    bare = tmp_path / "bare.bin"
    bare.write_bytes(fi.img({}, count=commu.PKG + 1))
    bind(monkeypatch, tmp_path, commu, bare)
    with pytest.raises(SystemExit, match="pkg"):
        commu.main()

    write_img(img, {commu.PKG: packed(_commu_files())})
    bind(monkeypatch, tmp_path, commu, img)
    real_find = commu.DarcArchive.find
    seen: set[str] = set()

    def miss_second(self, rel):
        hit = real_find(self, rel)
        if rel.endswith("Commu_Op_Text04.bclim"):
            if rel in seen:
                return None
            seen.add(rel)
        return hit

    monkeypatch.setattr(commu.DarcArchive, "find", miss_second)
    with pytest.raises(SystemExit, match="missing timg/Commu_Op_Text04"):
        commu.main()
    monkeypatch.setattr(commu.DarcArchive, "find", real_find)

    files = _commu_files()
    del files["blyt/Lyt_Commu_Option.bclyt"]
    write_img(img, {commu.PKG: packed(files)})
    bind(monkeypatch, tmp_path, commu, img)
    with pytest.raises(SystemExit, match="Lyt_Commu_Option"):
        commu.main()

    write_img(img, {commu.PKG: packed(_commu_files())})
    bind(monkeypatch, tmp_path, commu, img)
    real_row = commu.render_row
    monkeypatch.setattr(commu, "render_row", lambda *a: Image.new("RGBA", (4, 4)))
    with pytest.raises(SystemExit, match="!="):
        commu.main()
    monkeypatch.setattr(commu, "render_row", real_row)

    write_img(img, {commu.PKG: packed(_commu_files())})
    bind(monkeypatch, tmp_path, commu, img)
    real_replace = commu.DarcArchive.replace_same_size

    def grow(self, entry, new):
        real_replace(self, entry, new)
        if not getattr(self, "_grew", False):
            self._grew = True
            self.data += b"\x00"

    monkeypatch.setattr(commu.DarcArchive, "replace_same_size", grow)
    with pytest.raises(SystemExit, match="ARC length changed"):
        commu.main()
    monkeypatch.setattr(commu.DarcArchive, "replace_same_size", real_replace)

    write_img(img, {commu.PKG: packed(_commu_files())})
    bind(monkeypatch, tmp_path, commu, img)
    monkeypatch.setattr(
        commu, "try_fast_exact_slot", lambda d, n: (d, zlib.compress(d) + b"\x00")
    )
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        commu.main()

    write_img(img, {commu.PKG: packed(_commu_files())})
    bind(monkeypatch, tmp_path, commu, img)
    monkeypatch.setattr(
        commu,
        "try_fast_exact_slot",
        lambda d, n: (d + b"!", zlib.compress(d + b"!")),
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        commu.main()

    write_img(img, {commu.PKG: packed(_commu_files())})
    bind(monkeypatch, tmp_path, commu, img)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        tuned, slot = fast_exact(d, n)
        armed["go"] = True
        return tuned, slot

    monkeypatch.setattr(commu, "try_fast_exact_slot", arming)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        commu.main()
    armed["go"] = False

    write_img(img, {commu.PKG: retarget_sidecar(packed(_commu_files()))})
    bind(monkeypatch, tmp_path, commu, img)
    with pytest.raises(SystemExit, match="DMST changed"):
        commu.main()

    write_img(img, {commu.PKG: packed(_commu_files())})
    bind(monkeypatch, tmp_path, commu, img)
    monkeypatch.setattr(
        commu,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(commu.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        commu.main()


# ---------------------------------------------------------------------------
# In-room WEB hub (pkg 5380)
# ---------------------------------------------------------------------------


def _web_hub_files() -> dict[str, bytes]:
    files = {}
    for i, (_folder, path, _en) in enumerate(web_hub.JOBS):
        stem = Path(path).stem
        png = ROOT / "assets" / "images" / "Myroom.check" / "timg" / f"{stem}.png"
        with Image.open(png) as im:
            w, h = im.size
        files[path] = noise_bclim(w, h, 0xB, seed=20 + i)
    return files


def test_web_hub_compress_and_rgba(tmp_path, monkeypatch):
    clean, salted = salty_pair()
    assert web_hub._zero_all_darc_pads(salted) == clean
    adjacent = fi.darc({"a.bin": b"abcd", "b.bin": b"efgh"}, align=1)
    assert web_hub._zero_all_darc_pads(adjacent) == adjacent

    monkeypatch.setattr(web_hub, "try_fast_exact_slot", lambda d, n: (d, b"fast"))
    assert web_hub._compress_slot(salted, 4) == (salted, b"fast")

    monkeypatch.setattr(web_hub, "try_fast_exact_slot", lambda d, n: None)
    monkeypatch.setattr(web_hub, "compress_exact_zopfli", lambda d, n: (d, b"z"))
    assert web_hub._compress_slot(salted, 4)[1] == b"z"

    calls = {"n": 0}

    def zfail(d, n):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("miss")
        return d, b"z2"

    monkeypatch.setattr(web_hub, "compress_exact_zopfli", zfail)
    assert web_hub._compress_slot(salted, 4)[1] == b"z2"
    assert calls["n"] == 2

    monkeypatch.setattr(
        web_hub, "compress_exact_zopfli", lambda d, n: (_ for _ in ()).throw(RuntimeError("no"))
    )
    with pytest.raises(RuntimeError, match="no"):
        web_hub._compress_slot(salted, 4)

    monkeypatch.setattr(web_hub, "compress_exact_zopfli", lambda d, n: (d, b"one"))
    assert web_hub._compress_slot(adjacent, 3) == (adjacent, b"one")

    rgba, src = web_hub._rgba_for("Nope.check", "not_a_real_stem", "Net", 32, 16)
    assert src == "render:Net" and rgba.size == (32, 16)
    rgba, src = web_hub._rgba_for("Myroom.check", "web_tex_net_RGBA4", "TOWANO.NET", 152, 16)
    assert src.endswith("web_tex_net_RGBA4.png") and rgba.size == (152, 16)

    small = Image.new("RGBA", (4, 4), (9, 9, 9, 255))
    monkeypatch.setattr(web_hub, "_rgba_for", lambda *a: (small, "tiny"))
    monkeypatch.setattr(web_hub, "OUT", tmp_path / "out")
    web_hub.OUT.mkdir()
    arc = fi.darc(_web_hub_files())
    patched = web_hub._patch_arc(arc, tmp_path)
    assert patched != arc
    with pytest.raises(SystemExit, match="missing"):
        web_hub._patch_arc(fi.darc({"timg/a.bclim": noise_bclim(16, 16, 0xB)}), tmp_path)


def test_web_hub_patch_arc_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(web_hub, "OUT", tmp_path / "out")
    web_hub.OUT.mkdir()
    bad = dict(_web_hub_files())
    bad["timg/web_tex_net_RGBA4.bclim"] = noise_bclim(16, 16, 8, seed=4)
    with pytest.raises(SystemExit, match="not ETC1A4"):
        web_hub._patch_arc(fi.darc(bad), tmp_path)


def test_web_hub_main_and_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {web_hub.PKG: packed(_web_hub_files())})
    bind(monkeypatch, tmp_path, web_hub, img)
    extra = point_instances(monkeypatch, web_hub, img, tmp_path)
    assert extra.resolve() in web_hub._deploy_targets()
    before = img.read_bytes()
    assert web_hub.main() == 0
    assert img.read_bytes() != before
    assert (web_hub.OUT / "web_tex_net_RGBA4_en.png").is_file()

    monkeypatch.setattr(web_hub, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        web_hub.main()

    bare = tmp_path / "bare.bin"
    bare.write_bytes(fi.img({}, count=web_hub.PKG + 1))
    bind(monkeypatch, tmp_path, web_hub, bare)
    with pytest.raises(SystemExit, match="pkg"):
        web_hub.main()

    write_img(img, {web_hub.PKG: packed({"timg/other.bclim": noise_bclim(16, 16, 0xB)})})
    bind(monkeypatch, tmp_path, web_hub, img)
    with pytest.raises(SystemExit, match="missing"):
        web_hub.main()

    write_img(img, {web_hub.PKG: packed(_web_hub_files())})
    bind(monkeypatch, tmp_path, web_hub, img)
    real_slot = web_hub._compress_slot
    monkeypatch.setattr(
        web_hub, "_compress_slot", lambda d, n: (d, zlib.compress(d) + b"\x00")
    )
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        web_hub.main()

    bind(monkeypatch, tmp_path, web_hub, img)
    monkeypatch.setattr(
        web_hub, "_compress_slot", lambda d, n: (d + b"!", zlib.compress(d + b"!"))
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        web_hub.main()

    bind(monkeypatch, tmp_path, web_hub, img)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        tuned, slot = fast_exact(d, n)
        armed["go"] = True
        return tuned, slot

    monkeypatch.setattr(web_hub, "_compress_slot", arming)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        web_hub.main()
    armed["go"] = False
    monkeypatch.setattr(web_hub, "_compress_slot", real_slot)

    write_img(img, {web_hub.PKG: retarget_sidecar(packed(_web_hub_files()))})
    bind(monkeypatch, tmp_path, web_hub, img)
    with pytest.raises(SystemExit, match="DMST changed"):
        web_hub.main()

    write_img(img, {web_hub.PKG: packed(_web_hub_files())})
    bind(monkeypatch, tmp_path, web_hub, img)
    monkeypatch.setattr(
        web_hub,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(web_hub.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        web_hub.main()


# ---------------------------------------------------------------------------
# Select Data sheet visibility
# ---------------------------------------------------------------------------


def _dsel_layout(show_flag: int, *names: str) -> bytes:
    sections = [pane(b"pan1", name, show_flag) for name in names]
    sections.append(pane(b"pic1", "Pic_Other", 1))
    sections.append(pane(b"grp1", "G", 1, size=32))
    return clyt(sections)


def _dsel_pkgs() -> dict[int, bytes]:
    lyt = _dsel_layout(1, "Vis_Dsel_Data")
    pts = _dsel_layout(0, "Pic_Dsel_data")
    folder = _dsel_layout(0, "Vis_folder_txt", "Vis_folder_tx_00")
    return {
        5152: packed({"blyt/Lyt_Dsel_data.bclyt": lyt, "blyt/Pts_Dsel_Data.bclyt": pts}, seed=3),
        5208: packed({"blyt/Lyt_C_Com_folder.bclyt": folder}, seed=4),
    }


def test_dsel_pane_edges_and_main(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="bad layout"):
        dsel.set_pane_visible(b"XXXX" + bytes(24), (), ())
    bad_len = bytearray(clyt([pane(b"pan1", "A", 1)]))
    struct.pack_into("<I", bad_len, 0x0C, 1)
    with pytest.raises(RuntimeError, match="bad layout"):
        dsel.set_pane_visible(bytes(bad_len), (), ())
    with pytest.raises(RuntimeError, match="both shown and hidden"):
        dsel.set_pane_visible(clyt([pane(b"pan1", "A", 1)]), ("A",), ("A",))
    with pytest.raises(RuntimeError, match="missing panes"):
        dsel.set_pane_visible(clyt([pane(b"pan1", "A", 1)]), ("Gone",), ())

    shown = dsel.set_pane_visible(_dsel_layout(0, "Pic_Dsel_data"), ("Pic_Dsel_data",), ())
    assert shown[20 + 8] & 1 == 1
    hidden = dsel.set_pane_visible(_dsel_layout(1, "Vis_Dsel_Data"), (), ("Vis_Dsel_Data",))
    assert hidden[20 + 8] & 1 == 0

    img = tmp_path / "img.bin"
    write_img(img, _dsel_pkgs())
    bind(monkeypatch, tmp_path, dsel, img)
    extra = point_instances(monkeypatch, dsel, img, tmp_path)
    assert extra.resolve() in dsel._deploy_targets()
    assert dsel.main() == 0
    assert img.read_bytes() != fi.img(_dsel_pkgs())

    monkeypatch.setattr(dsel, "try_fast_exact_slot", lambda d, n: None)
    write_img(img, _dsel_pkgs())
    bind(monkeypatch, tmp_path, dsel, img)
    monkeypatch.setattr(dsel, "try_fast_exact_slot", lambda d, n: None)
    assert dsel.main() == 0

    # A non-ARC entry before the archive makes the slot scan skip once.
    arc = fi.darc(
        {
            "blyt/Lyt_Dsel_data.bclyt": _dsel_layout(1, "Vis_Dsel_Data"),
            "blyt/Pts_Dsel_Data.bclyt": _dsel_layout(0, "Pic_Dsel_data"),
            "zz_noise.bin": noise_file(7),
        }
    )
    write_img(
        img,
        {
            5152: fi.package(
                [
                    ("note.bin", b"DMSTDATA!!", b"DMST", False),
                    ("Data.arc", arc, b"ARC ", True),
                ]
            ),
            5208: _dsel_pkgs()[5208],
        },
    )
    bind(monkeypatch, tmp_path, dsel, img)
    assert dsel.main() == 0


def test_dsel_main_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, _dsel_pkgs())
    bind(monkeypatch, tmp_path, dsel, img)
    monkeypatch.setattr(dsel, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        dsel.main()

    bare = tmp_path / "bare.bin"
    bare.write_bytes(fi.img({}, count=5209))
    bind(monkeypatch, tmp_path, dsel, bare)
    with pytest.raises(SystemExit, match="pkg 5152 missing"):
        dsel.main()

    pkgs = _dsel_pkgs()
    pkgs[5152] = packed({"blyt/Other.bclyt": clyt([pane(b"pan1", "A", 1)])})
    write_img(img, pkgs)
    bind(monkeypatch, tmp_path, dsel, img)
    with pytest.raises(SystemExit, match="missing blyt/Lyt_Dsel_data"):
        dsel.main()

    write_img(img, _dsel_pkgs())
    bind(monkeypatch, tmp_path, dsel, img)
    monkeypatch.setattr(
        dsel, "try_fast_exact_slot", lambda d, n: (d, zlib.compress(d) + b"\x00")
    )
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        dsel.main()

    bind(monkeypatch, tmp_path, dsel, img)
    monkeypatch.setattr(
        dsel, "try_fast_exact_slot", lambda d, n: (d + b"!", zlib.compress(d + b"!"))
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        dsel.main()

    real_unpack = struct.unpack_from

    def no_arc(fmt, buffer, offset=0):
        if fmt == "=6sH":
            return (b"PACK\n0", 0)
        return real_unpack(fmt, buffer, offset)

    bind(monkeypatch, tmp_path, dsel, img)
    monkeypatch.setattr(struct, "unpack_from", no_arc)
    with pytest.raises(SystemExit, match="ARC entry missing"):
        dsel.main()
    monkeypatch.setattr(struct, "unpack_from", real_unpack)

    write_img(img, _dsel_pkgs())
    bind(monkeypatch, tmp_path, dsel, img)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        tuned, slot = fast_exact(d, n)
        armed["go"] = True
        return tuned, slot

    monkeypatch.setattr(dsel, "try_fast_exact_slot", arming)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        dsel.main()
    armed["go"] = False

    pkgs = {k: retarget_sidecar(v) for k, v in _dsel_pkgs().items()}
    write_img(img, pkgs)
    bind(monkeypatch, tmp_path, dsel, img)
    with pytest.raises(SystemExit, match="other entry changed"):
        dsel.main()

    write_img(img, _dsel_pkgs())
    bind(monkeypatch, tmp_path, dsel, img)
    monkeypatch.setattr(
        dsel,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(dsel.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        dsel.main()


# ---------------------------------------------------------------------------
# Card name tabs
# ---------------------------------------------------------------------------


def _card_layout() -> bytes:
    sections = [pane(b"pan1", name, 0) for name in sorted(card.SHOW_PANES)]
    sections.append(pane(b"pan1", "SkipMe", 0))
    sections.append(pane(b"grp1", "G", 0, size=32))
    return clyt(sections)


def _card_files() -> dict[str, bytes]:
    return {
        "timg/B_Card04_txt01.bclim": noise_bclim(128, 28, 8, seed=11),
        # Basename only: find("timg/...") still resolves a unique stem.
        "B_Card04_txt06.bclim": noise_bclim(128, 28, 8, seed=12),
        "blyt/Lyt_B_Card04_btn.bclyt": _card_layout(),
    }


def test_card_label_edges_and_main(tmp_path, monkeypatch):
    im = card.render_tab_label(128, 28, "Name")
    assert im.size == (128, 28) and im.getchannel("A").getbbox()
    blank = card.render_tab_label(128, 28, " ")
    assert blank.size == (128, 28) and blank.getchannel("A").getbbox() is None
    with pytest.raises(RuntimeError, match="cannot fit"):
        card.render_tab_label(16, 8, "Girlfriend's Name")
    with pytest.raises(RuntimeError, match="bad card field"):
        card.show_field_row(b"XXXX" + bytes(32))
    bad_len = bytearray(clyt([pane(b"pan1", "Vis_White_Base", 1)]))
    struct.pack_into("<I", bad_len, 0x0C, 3)
    with pytest.raises(RuntimeError, match="bad card field"):
        card.show_field_row(bytes(bad_len))

    img = tmp_path / "img.bin"
    write_img(img, {card.PKG: packed(_card_files())})
    bind(monkeypatch, tmp_path, card, img)
    extra = point_instances(monkeypatch, card, img, tmp_path)
    assert extra.resolve() in card._deploy_targets()
    assert card.main() == 0
    assert (card.OUT / "B_Card04_txt01_en.png").is_file()

    write_img(img, {card.PKG: packed(_card_files())})
    bind(monkeypatch, tmp_path, card, img)
    monkeypatch.setattr(card, "try_fast_exact_slot", lambda d, n: None)
    assert card.main() == 0


def test_card_main_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {card.PKG: packed(_card_files())})
    bind(monkeypatch, tmp_path, card, img)
    monkeypatch.setattr(card, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        card.main()

    bare = tmp_path / "bare.bin"
    bare.write_bytes(fi.img({}, count=card.PKG + 1))
    bind(monkeypatch, tmp_path, card, bare)
    with pytest.raises(SystemExit, match="pkg"):
        card.main()

    files = _card_files()
    del files["timg/B_Card04_txt01.bclim"]
    write_img(img, {card.PKG: packed(files)})
    bind(monkeypatch, tmp_path, card, img)
    with pytest.raises(SystemExit, match="missing"):
        card.main()

    files = _card_files()
    files["timg/B_Card04_txt01.bclim"] = noise_bclim(128, 28, 5, seed=2)
    write_img(img, {card.PKG: packed(files)})
    bind(monkeypatch, tmp_path, card, img)
    with pytest.raises(SystemExit, match="not RGBA4444"):
        card.main()

    files = _card_files()
    del files["blyt/Lyt_B_Card04_btn.bclyt"]
    write_img(img, {card.PKG: packed(files)})
    bind(monkeypatch, tmp_path, card, img)
    with pytest.raises(SystemExit, match="Lyt_B_Card04_btn"):
        card.main()

    write_img(img, {card.PKG: packed(_card_files())})
    bind(monkeypatch, tmp_path, card, img)
    monkeypatch.setattr(
        card, "try_fast_exact_slot", lambda d, n: (d, zlib.compress(d) + b"\x00")
    )
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        card.main()

    bind(monkeypatch, tmp_path, card, img)
    monkeypatch.setattr(
        card, "try_fast_exact_slot", lambda d, n: (d + b"!", zlib.compress(d + b"!"))
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        card.main()

    bind(monkeypatch, tmp_path, card, img)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        tuned, slot = fast_exact(d, n)
        armed["go"] = True
        return tuned, slot

    monkeypatch.setattr(card, "try_fast_exact_slot", arming)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        card.main()
    armed["go"] = False

    write_img(img, {card.PKG: retarget_sidecar(packed(_card_files()))})
    bind(monkeypatch, tmp_path, card, img)
    with pytest.raises(SystemExit, match="DMST changed"):
        card.main()

    write_img(img, {card.PKG: packed(_card_files())})
    bind(monkeypatch, tmp_path, card, img)
    monkeypatch.setattr(
        card,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(card.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        card.main()


# ---------------------------------------------------------------------------
# Clock date order + header AM/PM (shared layout movers)
# ---------------------------------------------------------------------------


def _clock_pane(tag: bytes, name: str, x: float) -> bytes:
    return pane(tag, name, 1, size=0x4C, **{"0x24": x})


def _txl(names: list[str]) -> bytes:
    strings = b""
    offs = []
    base = 4 * len(names)
    for n in names:
        offs.append(base + len(strings))
        strings += n.encode("ascii") + b"\x00"
    body = struct.pack("<I", len(names)) + struct.pack(f"<{len(names)}I", *offs) + strings
    body += b"\x00" * (-len(body) % 4)
    return b"txl1" + struct.pack("<I", 8 + len(body)) + body


def _mat(name: str, tex_idx: int, maps: int = 1) -> bytes:
    mat = bytearray(0x38)
    mat[0 : len(name)] = name.encode("ascii")
    struct.pack_into("<I", mat, 0x30, maps)
    struct.pack_into("<H", mat, 0x34, tex_idx)
    head = 12 + 4
    return b"mat1" + struct.pack("<III", 8 + 4 + 4 + len(mat), 1, head) + bytes(mat)


def _vanilla_anchor() -> bytes:
    return clyt([_clock_pane(b"pan1", n, v) for n, (v, _t) in clock.ANCHOR_X.items()])


def _vanilla_win() -> bytes:
    panes = [
        _clock_pane(b"wnd1" if n.startswith("window") else b"pic1", n, v)
        for n, (v, _t) in clock.WIN_X.items()
    ]
    panes.append(_clock_pane(b"pic1", "Pic_Opt_Win_tex4", 48.0))
    txl = _txl(
        [
            "Opt_Time_tex1.bclim",
            "Opt_Time_tex2.bclim",
            "Opt_Time_Week01.bclim",
            "Opt_Time_Week07.bclim",
        ]
    )
    return clyt([txl, _mat("Pic_Opt_Win_tex3", 2), *panes])


def _clock_files() -> dict[str, bytes]:
    return {
        clock.SLASH_BCLIM: noise_bclim(16, 16, 0xD, seed=15),
        clock.ANCHOR_LYT: _vanilla_anchor(),
        clock.WIN_LYT: _vanilla_win(),
    }


def _header_layout() -> bytes:
    return clyt(
        [pane(b"pan1", n, 1, size=0x4C, **{"0x28": v}) for n, (v, _t) in header.ANCHOR_Y.items()]
    )


def _stage_root(monkeypatch, mod, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "ROOT", root)


def test_clock_rebind_edges_and_main(tmp_path, monkeypatch):
    txl = _txl(["a.bclim", "b.bclim", "c.bclim"])
    no_map = bytearray(_mat("M", 0, maps=0))
    with pytest.raises(ValueError, match="has no texMap"):
        clock.rebind_textures(clyt([txl, bytes(no_map)]), {"M": ("a.bclim", "b.bclim")})
    with pytest.raises(ValueError, match="uses c.bclim"):
        clock.rebind_textures(clyt([txl, _mat("M", 2)]), {"M": ("a.bclim", "b.bclim")})
    with pytest.raises(ValueError, match="missing materials"):
        clock.rebind_textures(clyt([txl, _mat("Other", 0)]), {"M": ("a.bclim", "b.bclim")})
    # Already rebound: cur == new, changed stays 0. A non-pane tag is skipped.
    once, n = clock.rebind_textures(clyt([txl, _mat("M", 0), b"grp1" + struct.pack("<I", 8)]), {"M": ("a.bclim", "b.bclim")})
    assert n == 1
    again, n2 = clock.rebind_textures(once, {"M": ("a.bclim", "b.bclim")})
    assert n2 == 0 and again == once
    with pytest.raises(ValueError, match="bad CLYT"):
        list(clock._sections(b"FLYT" + bytes(16)))
    with pytest.raises(ValueError, match="missing panes"):
        clock.move_panes(clyt([pane(b"pan1", "Other", 1, size=0x4C)]), {"Gone": (0.0, 1.0)})
    moved, n = clock.move_panes(_vanilla_anchor(), clock.ANCHOR_X)
    assert n == len(clock.ANCHOR_X)
    same, n0 = clock.move_panes(moved, clock.ANCHOR_X)
    assert n0 == 0 and same == moved
    with pytest.raises(ValueError, match="expected vanilla"):
        clock.move_panes(
            clyt([_clock_pane(b"pan1", n, 999.0) for n in clock.ANCHOR_X]),
            clock.ANCHOR_X,
        )

    img = tmp_path / "img.bin"
    write_img(img, {clock.PKG: packed(_clock_files())})
    _stage_root(monkeypatch, clock, tmp_path)
    bind(monkeypatch, tmp_path, clock, img)
    assert clock.main() is None
    assert (clock.ROOT / clock.PNG_REL).is_file()
    # Second pass is a no-op on anchors that already sit at the US x.
    assert clock.main() is None


def test_clock_main_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {clock.PKG: packed(_clock_files())})
    _stage_root(monkeypatch, clock, tmp_path)
    bind(monkeypatch, tmp_path, clock, img)
    monkeypatch.setattr(clock, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        clock.main()

    bare = tmp_path / "bare.bin"
    bare.write_bytes(fi.img({}, count=clock.PKG + 1))
    _stage_root(monkeypatch, clock, tmp_path)
    bind(monkeypatch, tmp_path, clock, bare)
    with pytest.raises(SystemExit, match="pkg"):
        clock.main()

    files = _clock_files()
    del files[clock.SLASH_BCLIM]
    write_img(img, {clock.PKG: packed(files)})
    _stage_root(monkeypatch, clock, tmp_path)
    bind(monkeypatch, tmp_path, clock, img)
    with pytest.raises(SystemExit, match="Opt_Time_tex2"):
        clock.main()

    files = _clock_files()
    del files[clock.WIN_LYT]
    write_img(img, {clock.PKG: packed(files)})
    _stage_root(monkeypatch, clock, tmp_path)
    bind(monkeypatch, tmp_path, clock, img)
    with pytest.raises(SystemExit, match="Pts_Opt_Time_Win"):
        clock.main()

    write_img(img, {clock.PKG: packed(_clock_files())})
    _stage_root(monkeypatch, clock, tmp_path)
    bind(monkeypatch, tmp_path, clock, img)
    monkeypatch.setattr(clock, "compress_to_exact_slot", lambda d, n: zlib.compress(d) + b"\x00")
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        clock.main()

    bind(monkeypatch, tmp_path, clock, img)
    monkeypatch.setattr(clock, "compress_to_exact_slot", lambda d, n: zlib.compress(d))
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        clock.main()

    bind(monkeypatch, tmp_path, clock, img)

    def changed(d, n):
        alt = bytearray(d)
        at = alt.find(b"CLYT")
        alt[at + 24] ^= 0x5A
        return zlib.compress(bytes(alt))

    monkeypatch.setattr(clock, "compress_to_exact_slot", changed)
    with pytest.raises(SystemExit, match="exact zlib changed"):
        clock.main()

    bind(monkeypatch, tmp_path, clock, img)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        _tuned, slot = fast_exact(d, n)
        armed["go"] = True
        return slot

    monkeypatch.setattr(clock, "compress_to_exact_slot", arming)
    with pytest.raises(SystemExit, match="ARC round-trip mismatch"):
        clock.main()
    armed["go"] = False

    write_img(img, {clock.PKG: retarget_sidecar(packed(_clock_files()))})
    _stage_root(monkeypatch, clock, tmp_path)
    bind(monkeypatch, tmp_path, clock, img)
    with pytest.raises(SystemExit, match="other entry changed"):
        clock.main()

    # ARC type bytes wiped after the in-memory parse: the slot scan finds nothing.
    from img import Package

    write_img(img, {clock.PKG: packed(_clock_files())})
    _stage_root(monkeypatch, clock, tmp_path)
    bind(monkeypatch, tmp_path, clock, img)
    pkg_dir = clock.ROOT / "out" / "clock_date_order_en" / "img_data"
    pkg, arc = clock._load_pkg(img, pkg_dir)
    blob = bytearray((pkg_dir / f"{clock.PKG:04d}").read_bytes())
    blob[Package.ENTRY_SIZE : Package.ENTRY_SIZE + 4] = b"XXX "
    (pkg_dir / f"{clock.PKG:04d}").write_bytes(blob)
    with pytest.raises(SystemExit, match="ARC entry missing"):
        clock._write_arc_slot(pkg_dir, pkg, b"\x00" * 8, arc.parsed())

    write_img(img, {clock.PKG: packed(_clock_files())})
    _stage_root(monkeypatch, clock, tmp_path)
    bind(monkeypatch, tmp_path, clock, img)
    monkeypatch.setattr(
        clock,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(clock.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        clock.main()


def test_header_clock_main_and_errors(tmp_path, monkeypatch):
    raw = _header_layout()
    patched, n = header.patch_layout(raw)
    assert n == len(header.ANCHOR_Y)
    assert header.patch_layout(patched) == (patched, 0)
    with pytest.raises(ValueError, match="expected vanilla"):
        header.patch_layout(
            clyt([pane(b"pan1", name, 1, size=0x4C, **{"0x28": 999.0}) for name in header.ANCHOR_Y])
        )

    img = tmp_path / "img.bin"
    write_img(img, {header.PKG: packed({header.LAYOUT: raw})})
    _stage_root(monkeypatch, header, tmp_path)
    bind(monkeypatch, tmp_path, header, img)
    assert header.main() is None
    assert header.main() is None

    monkeypatch.setattr(header, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        header.main()

    bare = tmp_path / "bare.bin"
    bare.write_bytes(fi.img({}, count=header.PKG + 1))
    _stage_root(monkeypatch, header, tmp_path)
    bind(monkeypatch, tmp_path, header, bare)
    with pytest.raises(SystemExit, match="pkg"):
        header.main()

    write_img(img, {header.PKG: packed({"blyt/other.bclyt": raw})})
    _stage_root(monkeypatch, header, tmp_path)
    bind(monkeypatch, tmp_path, header, img)
    with pytest.raises(SystemExit, match="manl_lyt_left_0"):
        header.main()

    write_img(img, {header.PKG: packed({header.LAYOUT: raw})})
    _stage_root(monkeypatch, header, tmp_path)
    bind(monkeypatch, tmp_path, header, img)
    monkeypatch.setattr(header, "compress_to_exact_slot", lambda d, n: zlib.compress(d) + b"\x00")
    with pytest.raises(SystemExit, match="exact zlib verify failed"):
        header.main()

    bind(monkeypatch, tmp_path, header, img)
    monkeypatch.setattr(header, "compress_to_exact_slot", lambda d, n: zlib.compress(d))
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        header.main()

    bind(monkeypatch, tmp_path, header, img)

    def changed(d, n):
        alt = bytearray(d)
        at = alt.find(b"CLYT")
        alt[at + 24] ^= 0x5A
        return zlib.compress(bytes(alt))

    monkeypatch.setattr(header, "compress_to_exact_slot", changed)
    with pytest.raises(SystemExit, match="exact zlib changed"):
        header.main()

    bind(monkeypatch, tmp_path, header, img)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        _tuned, slot = fast_exact(d, n)
        armed["go"] = True
        return slot

    monkeypatch.setattr(header, "compress_to_exact_slot", arming)
    with pytest.raises(SystemExit, match="ARC round-trip mismatch"):
        header.main()
    armed["go"] = False

    from img import Package

    write_img(img, {header.PKG: packed({header.LAYOUT: raw})})
    _stage_root(monkeypatch, header, tmp_path)
    bind(monkeypatch, tmp_path, header, img)
    pkg_dir = header.ROOT / "out" / "header_clock_ampm_en" / "img_data"
    pkg, _arc = header._load_pkg(img, pkg_dir)
    blob = bytearray((pkg_dir / f"{header.PKG:04d}").read_bytes())
    blob[Package.ENTRY_SIZE : Package.ENTRY_SIZE + 4] = b"XXX "
    (pkg_dir / f"{header.PKG:04d}").write_bytes(blob)
    with pytest.raises(SystemExit, match="ARC entry missing"):
        header._write_arc_slot(pkg_dir, pkg, b"short", b"dec")

    write_img(img, {header.PKG: retarget_sidecar(packed({header.LAYOUT: raw}))})
    _stage_root(monkeypatch, header, tmp_path)
    bind(monkeypatch, tmp_path, header, img)
    with pytest.raises(SystemExit, match="other entry changed"):
        header.main()

    write_img(img, {header.PKG: packed({header.LAYOUT: raw})})
    _stage_root(monkeypatch, header, tmp_path)
    bind(monkeypatch, tmp_path, header, img)
    monkeypatch.setattr(
        header,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(header.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        header.main()


# ---------------------------------------------------------------------------
# Web weather + event-card date
# ---------------------------------------------------------------------------


def _day_section(name: str, width: float, ty: float = -36.0) -> bytes:
    return pane(b"pic1", name, 1, size=80, **{"40": ty, "68": width, "72": 14.0})


def _weather_layout(width: float = 14.0) -> bytes:
    days = [_day_section(f"Txt_Day_{i:02d}", width) for i in range(7)]
    days.append(pane(b"pic1", "Txt_Other", 1, size=80, **{"68": 14.0}))
    days.append(pane(b"grp1", "G", 1, size=32))
    return clyt(days)


def _date_section(x: float, width: float) -> bytes:
    return pane(b"pic1", "Pic_Txt_Date", 1, size=80, **{"36": x, "68": width})


def _date_layout(x: float, width: float) -> bytes:
    return clyt([_date_section(x, width), pane(b"grp1", "G", 1, size=32)])


def _paint_panel(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (248, 184), (240, 200, 180, 255)).save(path)


def test_weather_layout_edges_and_main(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="not CLYT"):
        weather.patch_weather_layout(b"NOPE" + bytes(24))
    wide, n = weather.patch_weather_layout(clyt([_day_section("Txt_Day_00", 24.0)]))
    assert n == 1
    assert struct.unpack_from("<f", wide, 20 + 68)[0] == weather.DAY_W
    padded = clyt([_day_section("Txt_Day_00", weather.DAY_W)], header_size=24)
    again, n0 = weather.patch_weather_layout(padded)
    assert n0 == 0 and len(again) == len(padded)
    extra = _weather_layout() + b"TRAILING!!"
    with pytest.raises(ValueError, match="layout grew"):
        weather.patch_weather_layout(extra)

    monkeypatch.setattr(weather, "HEISEI_W7", tmp_path / "no-w7.ttc")
    monkeypatch.setattr(weather, "TITLE", "W" * 40)
    src = tmp_path / "panel.png"
    _paint_panel(src)
    with pytest.raises(RuntimeError, match="px"):
        weather.paint_weekly_title(src)
    monkeypatch.setattr(weather, "TITLE", "Weekly")
    painted = weather.paint_weekly_title(src)
    assert painted.size == (248, 184)

    root = tmp_path / "root"
    _paint_panel(root / weather.PNG_REL)
    monkeypatch.setattr(weather, "ROOT", root)
    img = tmp_path / "img.bin"
    files = {
        weather.PANEL_BCLIM: noise_bclim(32, 32, 8, seed=21),
        weather.LAYOUTS[0]: _weather_layout(),
        weather.LAYOUTS[1]: _weather_layout(),
    }
    write_img(img, {weather.PKG: packed(files)})
    bind(monkeypatch, tmp_path, weather, img)
    monkeypatch.setattr(weather, "VANILLA", tmp_path / "no-vanilla.bin")
    assert weather.main() is None
    # Day panes are already DAY_W; the second pass takes the n == 0 branch.
    assert weather.main() is None


def test_weather_main_errors(tmp_path, monkeypatch):
    root = tmp_path / "root"
    monkeypatch.setattr(weather, "ROOT", root)
    monkeypatch.setattr(weather, "MOD_IMG", tmp_path / "no-mod.bin")
    monkeypatch.setattr(weather, "VANILLA", tmp_path / "no-van.bin")
    with pytest.raises(SystemExit, match="no-mod.bin"):
        weather.main()

    img = tmp_path / "img.bin"
    img.write_bytes(b"not-an-img")
    monkeypatch.setattr(weather, "MOD_IMG", img)
    monkeypatch.setattr(weather, "VANILLA", img)
    with pytest.raises(SystemExit, match="Web_Pnl_Wea"):
        weather.main()

    _paint_panel(root / weather.PNG_REL)
    files = {
        weather.PANEL_BCLIM: noise_bclim(32, 32, 8, seed=22),
        weather.LAYOUTS[0]: _weather_layout(),
        weather.LAYOUTS[1]: clyt([_day_section("Txt_Day_00", 14.0)]),
    }
    write_img(img, {weather.PKG: packed(files)})
    bind(monkeypatch, tmp_path, weather, img)
    with pytest.raises(SystemExit, match="day panes"):
        weather.main()

    files[weather.LAYOUTS[1]] = _weather_layout()
    del files[weather.PANEL_BCLIM]
    write_img(img, {weather.PKG: packed(files)})
    bind(monkeypatch, tmp_path, weather, img)
    with pytest.raises(SystemExit, match="Web_Pnl_Wea.bclim"):
        weather.main()

    files = {
        weather.PANEL_BCLIM: noise_bclim(32, 32, 8, seed=23),
        weather.LAYOUTS[0]: _weather_layout(),
    }
    write_img(img, {weather.PKG: packed(files)})
    bind(monkeypatch, tmp_path, weather, img)
    with pytest.raises(SystemExit, match="Lyt_Weather"):
        weather.main()

    files[weather.LAYOUTS[1]] = _weather_layout()
    write_img(img, {weather.PKG: packed(files)})
    bind(monkeypatch, tmp_path, weather, img)
    monkeypatch.setattr(weather, "compress_to_exact_slot", lambda d, n: zlib.compress(d) + b"\x00")
    with pytest.raises(SystemExit, match="zlib verify failed"):
        weather.main()

    bind(monkeypatch, tmp_path, weather, img)
    monkeypatch.setattr(weather, "compress_to_exact_slot", lambda d, n: zlib.compress(d))
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        weather.main()

    bind(monkeypatch, tmp_path, weather, img)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        _tuned, slot = fast_exact(d, n)
        armed["go"] = True
        return slot

    monkeypatch.setattr(weather, "compress_to_exact_slot", arming)
    with pytest.raises(SystemExit, match="ARC round-trip mismatch"):
        weather.main()
    armed["go"] = False

    write_img(img, {weather.PKG: retarget_sidecar(packed(files))})
    bind(monkeypatch, tmp_path, weather, img)
    with pytest.raises(SystemExit, match="DMST changed"):
        weather.main()

    from img import Package

    write_img(img, {weather.PKG: packed(files)})
    bind(monkeypatch, tmp_path, weather, img)
    _raw, pkg, arc = weather._load_pkg(img, weather.ROOT / "out" / "web_weather_en" / "img_data")
    pkg_dir = weather.ROOT / "out" / "web_weather_en" / "img_data"
    blob = bytearray((pkg_dir / f"{weather.PKG:04d}").read_bytes())
    off = Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[off : off + Package.ENTRY_SIZE])
    )
    assert is_cmp
    slot = fast_exact(arc.parsed(), slot_len)[1]
    bad = bytearray(arc.parsed())
    bad[0] ^= 1
    with pytest.raises(SystemExit, match="ARC round-trip mismatch"):
        weather._write_arc_slot(pkg_dir, pkg, slot, bytes(bad))
    assert dec_len and cmp_off

    write_img(img, {weather.PKG: packed(files)})
    bind(monkeypatch, tmp_path, weather, img)
    monkeypatch.setattr(
        weather,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(weather.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        weather.main()


def test_event_date_edges_and_main(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="not CLYT"):
        event.patch_date_layout(b"NOPE" + bytes(24))
    with pytest.raises(ValueError, match="expected vanilla"):
        event.patch_date_layout(_date_layout(1.0, 10.0))
    with pytest.raises(ValueError, match="no Pic_Txt_Date"):
        event.patch_date_layout(clyt([pane(b"pic1", "Other", 1, size=80)]))
    padded = clyt([_date_section(event.VANILLA_X, event.VANILLA_W)], header_size=24)
    same, changed = event.patch_date_layout(padded)
    assert changed is False and len(same) == len(padded)
    grown = _date_layout(event.WIDE_X, event.WIDE_W) + b"EXTRA!!!"
    with pytest.raises(ValueError, match="layout grew"):
        event.patch_date_layout(grown)
    label = event.paint_date_label()
    assert label.size == (event.TEX_W, event.TEX_H)

    root = tmp_path / "root"
    monkeypatch.setattr(event, "ROOT", root)
    img = tmp_path / "img.bin"
    files = {
        event.DATE_BCLIM: noise_bclim(event.TEX_W, event.TEX_H, 8, seed=30),
        event.LAYOUTS[0]: _date_layout(event.WIDE_X, event.WIDE_W),
        event.LAYOUTS[1]: _date_layout(event.VANILLA_X, event.VANILLA_W),
    }
    write_img(img, {event.PKG: packed(files)})
    bind(monkeypatch, tmp_path, event, img)
    assert event.main() is None
    assert (root / event.PNG_REL).is_file()
    assert event.main() is None


def test_event_date_errors(tmp_path, monkeypatch):
    root = tmp_path / "root"
    monkeypatch.setattr(event, "ROOT", root)
    monkeypatch.setattr(event, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        event.main()

    img = tmp_path / "img.bin"
    files = {
        event.DATE_BCLIM: noise_bclim(64, 16, 8, seed=31),
        event.LAYOUTS[0]: _date_layout(event.VANILLA_X, event.VANILLA_W),
        event.LAYOUTS[1]: _date_layout(event.WIDE_X, event.WIDE_W),
    }
    write_img(img, {event.PKG: packed({event.LAYOUTS[0]: files[event.LAYOUTS[0]]})})
    bind(monkeypatch, tmp_path, event, img)
    with pytest.raises(SystemExit, match="Web_Txt_Date"):
        event.main()

    write_img(img, {event.PKG: packed({event.DATE_BCLIM: files[event.DATE_BCLIM]})})
    bind(monkeypatch, tmp_path, event, img)
    with pytest.raises(SystemExit, match="Lyt_Spot"):
        event.main()

    write_img(img, {event.PKG: packed(files)})
    bind(monkeypatch, tmp_path, event, img)
    monkeypatch.setattr(event, "compress_to_exact_slot", lambda d, n: zlib.compress(d) + b"\x00")
    with pytest.raises(SystemExit, match="zlib verify failed"):
        event.main()

    bind(monkeypatch, tmp_path, event, img)
    monkeypatch.setattr(event, "compress_to_exact_slot", lambda d, n: zlib.compress(d))
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        event.main()

    bind(monkeypatch, tmp_path, event, img)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        _tuned, slot = fast_exact(d, n)
        armed["go"] = True
        return slot

    monkeypatch.setattr(event, "compress_to_exact_slot", arming)
    with pytest.raises(SystemExit, match="ARC round-trip mismatch"):
        event.main()
    armed["go"] = False

    write_img(img, {event.PKG: retarget_sidecar(packed(files))})
    bind(monkeypatch, tmp_path, event, img)
    with pytest.raises(SystemExit, match="DMST changed"):
        event.main()

    from img import Package

    write_img(img, {event.PKG: packed(files)})
    bind(monkeypatch, tmp_path, event, img)
    pkg_dir = event.ROOT / "out" / "web_event_date_en" / "img_data"
    pkg, arc = event._load_pkg(img, pkg_dir)
    blob = bytearray((pkg_dir / f"{event.PKG:04d}").read_bytes())
    blob[Package.ENTRY_SIZE : Package.ENTRY_SIZE + 4] = b"XXX "
    (pkg_dir / f"{event.PKG:04d}").write_bytes(blob)
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        event._write_arc_slot(pkg_dir, pkg, b"short", arc.parsed())

    write_img(img, {event.PKG: packed(files)})
    bind(monkeypatch, tmp_path, event, img)
    monkeypatch.setattr(
        event,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(event.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        event.main()


# ---------------------------------------------------------------------------
# Camera filters
# ---------------------------------------------------------------------------


def _cam_pngs(folder: Path) -> None:
    (folder / "timg").mkdir(parents=True)
    Image.new("RGBA", (16, 16), (20, 30, 40, 255)).save(folder / "timg" / "Btn.png")
    Image.new("RGBA", (8, 8), (1, 1, 1, 255)).save(folder / "timg" / "Skip.png")
    Image.new("RGBA", (16, 16), (255, 0, 0, 200)).save(folder / "timg" / "Flat.png")
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(folder / "timg" / "Orphan.png")


def _cam_darc(seed: int) -> bytes:
    return fi.darc(
        {
            "timg/Btn.bclim": noise_bclim(16, 16, 0xB, seed=seed),
            "timg/Skip.bclim": noise_bclim(16, 16, 0xB, seed=seed + 50),
            "timg/Flat.bclim": noise_bclim(16, 16, 8, seed=seed + 80),
            "zz_noise.bin": noise_file(seed),
        }
    )


def _cam_pkgs() -> dict[int, bytes]:
    from image_map import IMAGE_MAP

    pkgs: dict[int, list] = {}
    seed = 40
    for _key, (pkg_id, arc_name) in IMAGE_MAP.items():
        if pkg_id not in camera.PKGS:
            continue
        pkgs.setdefault(pkg_id, []).append((arc_name, _cam_darc(seed), b"ARC ", True))
        seed += 1
    # Sidecar is the second entry so retarget_sidecar aliases the first ARC slot.
    pkgs[5322].insert(1, ("note.bin", b"DMSTDATA!!", b"DMST", False))
    pkgs[5322].append(("loose.arc", _cam_darc(90), b"ARC ", False))
    pkgs[5322].append(("Other.arc", _cam_darc(91), b"ARC ", True))
    return {pkg_id: fi.package(entries) for pkg_id, entries in pkgs.items()}


def _cam_chosen(folder: Path) -> dict[str, Path]:
    from image_map import IMAGE_MAP

    return {key: folder for key, (pkg_id, _arc) in IMAGE_MAP.items() if pkg_id in camera.PKGS}


def test_camera_block_edges(tmp_path, monkeypatch):
    from bclimutil import encode_etc1a4_pixels

    plate = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    raw = fi.bclim(16, 16, 0xB, pixels=encode_etc1a4_pixels(plate, 16, 16))
    assert camera.encode_text_blocks(raw, plate, plate, 24) == raw
    low = plate.copy()
    low.putpixel((1, 1), (10, 10, 10, 8))
    van = camera.decode(raw)
    out = camera.encode_text_blocks(raw, low, van, 0, a_levels=4)
    assert len(out) == len(raw)

    opaque = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    opaque.putpixel((2, 2), (255, 255, 255, 255))
    opaque.putpixel((3, 2), (0, 0, 0, 0))
    mixed = camera.encode_text_blocks(raw, opaque, van, 0)
    assert len(mixed) == len(raw)
    real_parse = camera.parse_bclim

    def shifted(data):
        pix, w, h, fmt, ft = real_parse(data)
        return bytes([pix[0] ^ 1]) + pix[1:], w, h, fmt, ft

    monkeypatch.setattr(camera, "parse_bclim", shifted)
    with pytest.raises(ValueError, match="offset 0"):
        camera.encode_text_blocks(raw, opaque, van, 0)
    monkeypatch.setattr(camera, "parse_bclim", real_parse)

    with pytest.raises(ValueError, match="not ETC1A4"):
        camera.encode_text_blocks(noise_bclim(16, 16, 8), opaque, van, 24)
    padded = fi.bclim(8, 8, 0xB, pixels=random.Random(3).randbytes(16 * 16))
    with pytest.raises(ValueError, match="padded"):
        camera.encode_text_blocks(padded, opaque.resize((8, 8)), van.resize((8, 8)), 24)

    la8 = camera.decode(noise_bclim(16, 16, 3, seed=6))
    assert la8.size == (16, 16)
    with pytest.raises(SystemExit, match="cannot decode"):
        camera.decode(noise_bclim(16, 16, 0xD, seed=7))

    masters = tmp_path / "masters"
    _cam_pngs(masters)
    arc = _cam_darc(100)
    patched, n = camera.patch_arc(arc, masters, (24, 16, 256), tmp_path)
    assert n >= 1 and patched
    blocks, n2 = camera.patch_arc_blocks(arc, masters, 24, 8, tmp_path)
    assert n2 >= 1 and blocks


def test_camera_main_and_build(tmp_path, monkeypatch):
    masters = tmp_path / "masters"
    _cam_pngs(masters)
    img = tmp_path / "img.bin"
    write_img(img, _cam_pkgs())
    bind(monkeypatch, tmp_path, camera, img)
    monkeypatch.setattr(camera, "prefer_asset_folders", lambda _root: _cam_chosen(masters))
    assert camera.main() is None

    calls = {"n": 0}

    def flaky(data, n):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("miss")
        return fast_exact(data, n)[1]

    monkeypatch.setattr(camera, "compress_to_exact_slot", flaky)
    assert camera.build_pkg(5326, _cam_chosen(masters), camera.OUT / "img_data", tmp_path) is True
    assert calls["n"] >= 2

    monkeypatch.setattr(
        camera, "compress_to_exact_slot", lambda d, n: (_ for _ in ()).throw(RuntimeError("no"))
    )
    assert camera.build_pkg(5326, _cam_chosen(masters), camera.OUT / "img_data", tmp_path) is False

    monkeypatch.setattr(camera, "compress_to_exact_slot", lambda d, n: zlib.compress(b"no"))
    with pytest.raises(SystemExit, match="ARC length changed"):
        camera.build_pkg(5326, _cam_chosen(masters), camera.OUT / "img_data", tmp_path)

    retargeted = tmp_path / "retarget.bin"
    pkgs = _cam_pkgs()
    pkgs[5322] = retarget_sidecar(pkgs[5322])
    write_img(retargeted, pkgs)
    bind(monkeypatch, tmp_path, camera, retargeted)
    monkeypatch.setattr(camera, "prefer_asset_folders", lambda _root: _cam_chosen(masters))
    monkeypatch.setattr(camera, "VANILLA", retargeted)
    with pytest.raises(SystemExit, match="non-ARC entry changed"):
        camera.build_pkg(5322, _cam_chosen(masters), camera.OUT / "img_data", tmp_path)

    monkeypatch.setattr(camera, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        camera.main()

    write_img(img, _cam_pkgs())
    bind(monkeypatch, tmp_path, camera, img)
    monkeypatch.setattr(camera, "prefer_asset_folders", lambda _root: _cam_chosen(masters))
    monkeypatch.setattr(
        camera, "compress_to_exact_slot", lambda d, n: (_ for _ in ()).throw(RuntimeError("no"))
    )
    assert camera.main() is None

    monkeypatch.setattr(camera, "compress_to_exact_slot", lambda d, n: fast_exact(d, n)[1])
    monkeypatch.setattr(
        camera,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(camera.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        camera.main()


# ---------------------------------------------------------------------------
# SMS maildic
# ---------------------------------------------------------------------------


def _sms_xml(path: Path, rows: list[tuple[str, str]]) -> None:
    import xml.etree.ElementTree as ET

    root = ET.Element("Dictionary")
    for hex_id, text in rows:
        entry = ET.SubElement(root, "Entry")
        jt = ET.SubElement(entry, "JapaneseText", {"hex": hex_id})
        jt.text = text
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8")


def _sms_mdc() -> bytes:
    from mdcutil import MdcEntry, pack_mdc, pad_to_size

    packed_mdc = pack_mdc([MdcEntry(0x11, 0, "hi"), MdcEntry(0x22, 0, "yo")])
    return pad_to_size(packed_mdc, 256)


def _sms_pkg(blob: bytes | None = None) -> bytes:
    data = blob if blob is not None else _sms_mdc()
    return fi.package(
        [
            ("maildic_m.mdc", data, b"MDC ", False),
            ("maildic_n.mdc", data, b"MDC ", False),
            ("maildic_r.mdc", data, b"MDC ", False),
            ("worddic_m.mdc", b"word" + b"\xff" * 60, b"MDC ", False),
        ]
    )


def _sms_rows() -> list[tuple[str, str]]:
    return [("11", "Hello"), ("22", "There")]


def test_sms_resolve_and_main(tmp_path, monkeypatch):
    monkeypatch.setattr(sms, "CONTRIB_SMS_DIR", tmp_path / "empty-contrib")
    en = tmp_path / "en"
    for stem in sms.STEMS:
        _sms_xml(en / f"{stem}.en.xml", _sms_rows())
    assert sms.resolve_sms_xml("maildic_m", en) == en / "maildic_m.en.xml"
    contrib = tmp_path / "contrib"
    _sms_xml(contrib / "maildic_m.en.xml", _sms_rows())
    monkeypatch.setattr(sms, "CONTRIB_SMS_DIR", contrib)
    assert sms.resolve_sms_xml("maildic_m", en) == contrib / "maildic_m.en.xml"
    monkeypatch.setattr(sms, "CONTRIB_SMS_DIR", tmp_path / "none")
    with pytest.raises(SystemExit, match="missing"):
        sms.resolve_sms_xml("maildic_m", tmp_path / "no-en")

    img = tmp_path / "img.bin"
    write_img(img, {sms.PKG: _sms_pkg()})
    monkeypatch.setattr(sms, "OUT", tmp_path / "out")
    monkeypatch.setattr(sms, "find_vanilla_img", lambda: None)
    monkeypatch.setattr(sys, "argv", ["sms", "--img", str(img), "--en-dir", str(en), "--dry-run"])
    sms.main()
    assert (sms.OUT / "maildic_m.mdc").is_file()
    assert img.read_bytes() == fi.img({sms.PKG: _sms_pkg()})

    monkeypatch.setenv("NLPP_NO_IMG_BACKUP", "0")
    monkeypatch.setattr(sms, "find_vanilla_img", lambda: None)
    monkeypatch.setattr(
        sys, "argv", ["sms", "--img", str(img), "--en-dir", str(en)]
    )
    sms.main()
    assert (img.parent / sms.BAK_NAME).is_file()
    sms.main()  # backup already exists

    extra = tmp_path / "extra.bin"
    extra.write_bytes(img.read_bytes())
    monkeypatch.setattr(sms, "iter_deploy_targets", lambda primary: [primary, primary, extra])
    monkeypatch.setattr(
        sys, "argv", ["sms", "--img", str(img), "--en-dir", str(en), "--all-targets", "--no-backup"]
    )
    sms.main()
    assert extra.read_bytes() != img.read_bytes() or extra.is_file()

    monkeypatch.setattr(sms, "resolve_img_paths", lambda: (img, img))
    monkeypatch.setattr(sys, "argv", ["sms", "--en-dir", str(en), "--dry-run", "--no-backup"])
    sms.main()


def test_sms_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(sms, "CONTRIB_SMS_DIR", tmp_path / "no-contrib")
    monkeypatch.setattr(sms, "find_vanilla_img", lambda: None)
    monkeypatch.setattr(sms, "OUT", tmp_path / "out")
    en = tmp_path / "en"
    for stem in sms.STEMS:
        _sms_xml(en / f"{stem}.en.xml", _sms_rows())

    monkeypatch.setattr(sys, "argv", ["sms", "--img", str(tmp_path / "missing.bin"), "--en-dir", str(en)])
    with pytest.raises(SystemExit, match="not found"):
        sms.main()

    bare = tmp_path / "bare.bin"
    bare.write_bytes(fi.img({}, count=sms.PKG + 1))
    monkeypatch.setattr(sys, "argv", ["sms", "--img", str(bare), "--en-dir", str(en), "--dry-run"])
    with pytest.raises(SystemExit, match="package 92 missing"):
        sms.main()

    img = tmp_path / "img.bin"
    write_img(img, {sms.PKG: _sms_pkg()})
    vanilla = tmp_path / "vanilla.bin"
    write_img(vanilla, {sms.PKG: _sms_pkg(_sms_mdc() + b"\xff" * 40)})
    monkeypatch.setattr(sms, "find_vanilla_img", lambda: vanilla)
    monkeypatch.setattr(sys, "argv", ["sms", "--img", str(img), "--en-dir", str(en), "--no-backup"])
    with pytest.raises(SystemExit, match="offset/size mismatch"):
        sms.main()

    _im, pak = sms.load_pkg92(img)
    with pytest.raises(SystemExit, match="len"):
        sms.splice_inplace(img, {"maildic_m.mdc": b"short"}, pak)

    monkeypatch.setattr(sms, "find_vanilla_img", lambda: img)
    monkeypatch.setenv("NLPP_NO_IMG_BACKUP", "0")
    paths = fi.use_paths(monkeypatch, tmp_path, sms)
    bake = paths["BAKE_IMG"]
    bake.parent.mkdir(parents=True, exist_ok=True)
    bake.write_bytes(img.read_bytes())
    monkeypatch.setattr(sys, "argv", ["sms", "--img", str(bake), "--en-dir", str(en)])
    sms.main()


# ---------------------------------------------------------------------------
# Myroom main labels
# ---------------------------------------------------------------------------


def _myroom_files(modoru: tuple[int, int] = (64, 16), fmt: int = 0xB) -> dict[str, bytes]:
    files = {}
    for i, (path, _en) in enumerate(myroom.LABELS):
        w, h = modoru if path.endswith("common_modoru_RGBA4.bclim") else (64, 16)
        files[path] = noise_bclim(w, h, fmt, seed=60 + i)
    return files


def test_myroom_gap_and_empty_block_edges(monkeypatch):
    tight = fi.darc({"a.bin": b"abcd", "b.bin": b"efgh"}, align=1)
    assert myroom.interfile_zero_gaps(tight) == []
    short = fi.darc({"a.bin": b"abcd", "b.bin": b"efgh"}) + b"\x00\x00"
    assert all(sz >= 4 for sz, _off in myroom.interfile_zero_gaps(short))
    gappy = fi.darc({"a.bin": b"abcd", "b.bin": b"efgh"}, align=0x80)
    assert myroom.interfile_zero_gaps(gappy)
    assert myroom.apply_gap_pad(gappy, 0, b"\xff" * 16) == gappy
    assert myroom.apply_gap_pad(tight, 4, b"\xff" * 8) == tight
    real_pack = struct.pack

    def fat_adler(fmt, *args, **kwargs):
        out = real_pack(fmt, *args, **kwargs)
        return out + b"\x00" if fmt == ">I" else out

    monkeypatch.setattr(struct, "pack", fat_adler)
    assert myroom.compress_exact_empty_blocks(b"abc", 80) is None
    monkeypatch.setattr(struct, "pack", real_pack)

    class Boom:
        def decompress(self, _data):
            raise zlib.error("bad")

        unused_data = b""
        eof = True

    monkeypatch.setattr(zlib, "decompressobj", lambda *a, **k: Boom())
    assert myroom.compress_exact_empty_blocks(b"abc", 80) is None

    class Mismatch:
        def decompress(self, _data):
            return b"nope"

        unused_data = b""
        eof = True

    monkeypatch.setattr(zlib, "decompressobj", lambda *a, **k: Mismatch())
    assert myroom.compress_exact_empty_blocks(b"abc", 80) is None

    class Unused:
        def decompress(self, _data):
            return b"abc"

        unused_data = b"x"
        eof = True

    monkeypatch.setattr(zlib, "decompressobj", lambda *a, **k: Unused())
    assert myroom.compress_exact_empty_blocks(b"abc", 80) is None

    class NoEof:
        def decompress(self, _data):
            return b"abc"

        unused_data = b""
        eof = False

    monkeypatch.setattr(zlib, "decompressobj", lambda *a, **k: NoEof())
    assert myroom.compress_exact_empty_blocks(b"abc", 80) is None


def test_myroom_main_and_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {myroom.PKG: packed(_myroom_files())})
    bind(monkeypatch, tmp_path, myroom, img)
    monkeypatch.setattr(myroom, "MODORU_PNG", tmp_path / "no-modoru.png")
    monkeypatch.setattr(myroom, "compress_exact_with_gap_tune", lambda d, n: fast_exact(d, n))
    assert myroom.main() is None
    assert (myroom.OUT / "main_tex_love_RGBA4_en.png").is_file()

    # Master already matches the BCLIM, so the resize branch is skipped.
    write_img(img, {myroom.PKG: packed(_myroom_files((80, 30)))})
    bind(monkeypatch, tmp_path, myroom, img)
    monkeypatch.setattr(
        myroom,
        "MODORU_PNG",
        ROOT / "assets" / "images" / "Myroom.check" / "timg" / "common_modoru_RGBA4.png",
    )
    monkeypatch.setattr(myroom, "compress_exact_with_gap_tune", lambda d, n: fast_exact(d, n))
    assert myroom.main() is None

    # Empty-block miss falls through to the gap-tune stub. Modoru master resizes.
    write_img(img, {myroom.PKG: packed(_myroom_files((40, 16)))})
    bind(monkeypatch, tmp_path, myroom, img)
    monkeypatch.setattr(
        myroom,
        "MODORU_PNG",
        ROOT / "assets" / "images" / "Myroom.check" / "timg" / "common_modoru_RGBA4.png",
    )
    monkeypatch.setattr(myroom, "compress_exact_empty_blocks", lambda d, n: None)
    monkeypatch.setattr(myroom, "compress_exact_with_gap_tune", lambda d, n: fast_exact(d, n))
    assert myroom.main() is None

    monkeypatch.setattr(myroom, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        myroom.main()

    files = _myroom_files()
    del files["timg/main_tex_yotei_RGBA4_NEW.bclim"]
    write_img(img, {myroom.PKG: packed(files)})
    bind(monkeypatch, tmp_path, myroom, img)
    monkeypatch.setattr(myroom, "MODORU_PNG", tmp_path / "no-modoru.png")
    with pytest.raises(SystemExit, match="missing"):
        myroom.main()

    files = _myroom_files(fmt=8)
    write_img(img, {myroom.PKG: packed(files)})
    bind(monkeypatch, tmp_path, myroom, img)
    monkeypatch.setattr(myroom, "MODORU_PNG", tmp_path / "no-modoru.png")
    with pytest.raises(SystemExit, match="not ETC1A4"):
        myroom.main()

    write_img(img, {myroom.PKG: packed(_myroom_files())})
    bind(monkeypatch, tmp_path, myroom, img)
    monkeypatch.setattr(myroom, "MODORU_PNG", tmp_path / "no-modoru.png")
    monkeypatch.setattr(myroom, "compress_exact_empty_blocks", lambda d, n: zlib.compress(d) + b"\x00")
    monkeypatch.setattr(
        myroom, "compress_exact_with_gap_tune", lambda d, n: (d, zlib.compress(d) + b"\x00")
    )
    with pytest.raises(SystemExit, match="zlib verify failed"):
        myroom.main()

    bind(monkeypatch, tmp_path, myroom, img)
    monkeypatch.setattr(myroom, "compress_exact_empty_blocks", lambda d, n: None)
    monkeypatch.setattr(
        myroom, "compress_exact_with_gap_tune", lambda d, n: (d + b"!", zlib.compress(d + b"!"))
    )
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        myroom.main()

    bind(monkeypatch, tmp_path, myroom, img)
    armed = arm_later_darc(monkeypatch)

    def arming(d, n):
        tuned, slot = fast_exact(d, n)
        armed["go"] = True
        return tuned, slot

    monkeypatch.setattr(myroom, "compress_exact_empty_blocks", lambda d, n: None)
    monkeypatch.setattr(myroom, "compress_exact_with_gap_tune", arming)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        myroom.main()
    armed["go"] = False

    write_img(img, {myroom.PKG: retarget_sidecar(packed(_myroom_files()))})
    bind(monkeypatch, tmp_path, myroom, img)
    monkeypatch.setattr(myroom, "MODORU_PNG", tmp_path / "no-modoru.png")
    monkeypatch.setattr(myroom, "compress_exact_with_gap_tune", lambda d, n: fast_exact(d, n))
    with pytest.raises(SystemExit, match="DMST changed"):
        myroom.main()

    write_img(img, {myroom.PKG: packed(_myroom_files())})
    bind(monkeypatch, tmp_path, myroom, img)
    monkeypatch.setattr(myroom, "MODORU_PNG", tmp_path / "no-modoru.png")
    monkeypatch.setattr(myroom, "compress_exact_with_gap_tune", lambda d, n: fast_exact(d, n))
    monkeypatch.setattr(
        myroom,
        "splice_packages_into_img",
        lambda *a: (_ for _ in ()).throw(myroom.PackError("grew")),
    )
    with pytest.raises(SystemExit, match="splice failed: grew"):
        myroom.main()


# ---------------------------------------------------------------------------
# CESA boot warning
# ---------------------------------------------------------------------------


def test_cesa_refresh_and_fallback(tmp_path, monkeypatch):
    png = tmp_path / "cesa.png"
    comp = tmp_path / "white.png"
    monkeypatch.setattr(cesa, "CESA_PNG", png)
    monkeypatch.setattr(cesa, "COMPANION_PNG", comp)
    monkeypatch.setattr(cesa, "render_cesa_en", lambda: Image.new("RGB", (8, 8), (9, 0, 0)))
    monkeypatch.setattr(cesa, "render_cesa_companion_en", lambda: Image.new("RGB", (8, 8), (0, 9, 0)))
    cesa._refresh_pngs()
    assert png.is_file() and comp.is_file()

    monkeypatch.setattr(cesa, "render_cesa_en", lambda: (_ for _ in ()).throw(RuntimeError("font")))
    cesa._refresh_pngs()

    monkeypatch.setattr(cesa, "CESA_PNG", tmp_path / "gone-cesa.png")
    monkeypatch.setattr(cesa, "COMPANION_PNG", tmp_path / "gone-white.png")
    monkeypatch.setattr(cesa, "render_cesa_en", lambda: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        cesa._refresh_pngs()
    monkeypatch.setattr(cesa, "render_cesa_en", lambda: (_ for _ in ()).throw(SystemExit("stop")))
    with pytest.raises(SystemExit, match="stop"):
        cesa._refresh_pngs()

    dest = tmp_path / "live.bin"
    dest.write_bytes(b"live")
    fb = tmp_path / "fallback.bin"
    fb.write_bytes(b"fb")
    monkeypatch.setattr(cesa, "find_vanilla_img", lambda: dest)
    monkeypatch.setattr(cesa, "_FALLBACK_VANILLA", fb)
    assert cesa._vanilla_pkg90_src(dest) == fb.resolve()
    monkeypatch.setattr(cesa, "find_vanilla_img", lambda: None)
    assert cesa._vanilla_pkg90_src(dest) == fb.resolve()


def test_cesa_main(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {90: packed({"note.txt": b"cesa"})})
    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(img.read_bytes())
    png = tmp_path / "cesa.png"
    comp = tmp_path / "white.png"
    Image.new("RGB", (4, 4), (1, 0, 0)).save(png)
    Image.new("RGB", (4, 4), (1, 1, 1)).save(comp)
    bind(monkeypatch, tmp_path, cesa, img)
    monkeypatch.setattr(cesa, "CESA_PNG", png)
    monkeypatch.setattr(cesa, "COMPANION_PNG", comp)
    monkeypatch.setattr(cesa, "find_vanilla_img", lambda: None)
    monkeypatch.setattr(cesa, "_FALLBACK_VANILLA", vanilla)
    seen = {}

    def refresh():
        return None

    def patch(dest, cesa_png, companion_png, dst, work=None, vanilla_img=None):
        seen["dest"] = dest
        seen["vanilla"] = vanilla_img
        assert cesa_png.is_file() and companion_png.is_file()
        assert work is not None
        work.mkdir(parents=True, exist_ok=True)
        return dest

    monkeypatch.setattr(cesa, "_refresh_pngs", refresh)
    monkeypatch.setattr(cesa, "patch_img_bin_with_companion", patch)
    assert cesa.main() == 0
    assert seen["vanilla"] == vanilla.resolve()

    monkeypatch.setattr(cesa, "find_vanilla_img", lambda: vanilla)
    assert cesa.main() == 0
    assert seen["vanilla"] == vanilla.resolve()

    monkeypatch.setattr(cesa, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        cesa.main()

    bind(monkeypatch, tmp_path, cesa, img)
    monkeypatch.setattr(cesa, "CESA_PNG", tmp_path / "no-cesa.png")
    monkeypatch.setattr(cesa, "COMPANION_PNG", tmp_path / "no-white.png")
    monkeypatch.setattr(cesa, "_refresh_pngs", lambda: None)
    assert cesa.main() == 0
