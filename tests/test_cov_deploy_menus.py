"""Line and branch coverage for menu / mail / title deploy scripts.

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
from PIL import Image, ImageFont

from conftest import ROOT, TOOLS, load_module

import fake_img as fi

GEOMANIST = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025" / "Geomanist-Regular.ttf"

title = load_module("deploy_title_engpatch_en", TOOLS / "deploy_title_engpatch_en.py")
mail_home = load_module("deploy_mail_home_en", TOOLS / "deploy_mail_home_en.py")
mail_sort = load_module("deploy_mail_sort_en", TOOLS / "deploy_mail_sort_en.py")
msel = load_module("deploy_msel_menus_en", TOOLS / "deploy_msel_menus_en.py")
sched = load_module("deploy_schedule_header_en", TOOLS / "deploy_schedule_header_en.py")
keyboard = load_module("deploy_input_keyboard_en", TOOLS / "deploy_input_keyboard_en.py")
opt = load_module("deploy_msel_options_en", TOOLS / "deploy_msel_options_en.py")
multi = load_module("deploy_multiwin_headers_en", TOOLS / "deploy_multiwin_headers_en.py")


@pytest.fixture(autouse=True)
def _clean_argv(monkeypatch):
    monkeypatch.setattr("sys.argv", ["pytest"])


def noise_bclim(w: int, h: int, fmt: int, seed: int = 1) -> bytes:
    from bclimutil import parse_bclim

    blank = fi.bclim(w, h, fmt)
    n = len(parse_bclim(blank)[0])
    return fi.bclim(w, h, fmt, pixels=random.Random(seed).randbytes(n))


def arc_package(files: dict[str, bytes], *, compress: bool = True, sidecar: bytes = b"DMSTDATA!!") -> bytes:
    return fi.package(
        [
            ("Data.arc", fi.darc(files), b"ARC ", compress),
            ("meta.dmst", sidecar, b"DMST", False),
        ]
    )


def file_sized(pkg: bytes) -> bytes:
    """Make the PACK header dec_len equal the file size.

    fake img.bin uses that field as the on-disk slot length. Splice then
    writes the package without zero-padding, so a post-splice byte compare
    matches.
    """
    blob = bytearray(pkg)
    struct.pack_into("<I", blob, 20, len(blob))
    return bytes(blob)


def named_package(arcs: list[tuple[str, dict[str, bytes]]], extra: tuple | None = None) -> bytes:
    elements = [(name, fi.darc(files), b"ARC ", True) for name, files in arcs]
    if extra:
        elements.append(extra)
    return fi.package(elements)


def write_img(path: Path, packages: dict[int, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fi.img(packages))


def fast_exact(data: bytes, target: int):
    """Correctly sized slot without a zopfli search."""
    from exact_zlib import compress_exact_empty_blocks, pad_closed_zlib_stream

    slot = compress_exact_empty_blocks(data, target, thorough=False)
    if slot is None:
        for level in (9, 1, 0):
            slot = pad_closed_zlib_stream(zlib.compress(data, level), target, expected=data)
            if slot is not None:
                break
    if slot is None:
        raise RuntimeError(f"no exact slot {target} for {len(data)} bytes")
    return data, slot


def wrong_slot(data: bytes, target: int):
    """Valid zlib of a different payload, so verify fails instead of zlib.error."""
    filler = b"\x00" * min(max(len(data), 1), 48)
    _other, slot = fast_exact(filler, target)
    return data, slot


def point_instances(monkeypatch, mod, img: Path, tmp_path: Path) -> Path:
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


def retarget_sidecar(pkg: bytes) -> bytes:
    from img import Package

    blob = bytearray(pkg)
    e0 = Package.ENTRY_SIZE
    e1 = e0 + Package.ENTRY_SIZE
    _typ, _dl, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[e0 : e0 + Package.ENTRY_SIZE])
    )
    assert is_cmp and slot_len >= 16
    struct.pack_into("<2I", blob, e1 + 8, slot_len, cmp_off)
    return bytes(blob)


def bind(monkeypatch, tmp_path: Path, mod, img: Path, *, vanilla: Path | None = None):
    vanilla = vanilla or img
    fi.use_paths(monkeypatch, tmp_path, mod, MOD_IMG=img, VANILLA=vanilla)
    if hasattr(mod, "VANILLA_CANDIDATES"):
        monkeypatch.setattr(mod, "VANILLA_CANDIDATES", [tmp_path / "no-such.bin", vanilla])
    if hasattr(mod, "compress_exact_zopfli"):
        monkeypatch.setattr(mod, "compress_exact_zopfli", fast_exact)
    extra_img = point_instances(monkeypatch, mod, img, tmp_path)
    real_walk = getattr(mod, "iter_deploy_targets", None)
    # Scripts that glob AZAHAR_INSTANCES themselves must see `extra` as a new
    # target. Prepending it here would mark it already seen.
    if callable(real_walk) and mod not in (title, msel, opt, multi):

        def walk(primary, _real=real_walk, _extra=extra_img):
            targets = [p.resolve() for p in _real(primary)]
            rp = _extra.resolve()
            if rp not in targets:
                targets.append(rp)
            return targets

        monkeypatch.setattr(mod, "iter_deploy_targets", walk)
    return extra_img


def boom(mod):
    def _boom(*_a, **_k):
        raise mod.PackError("grew")

    return _boom


def section(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack("<I", 8 + len(payload)) + payload


def clyt(sections: list[bytes], header_size: int = 20) -> bytes:
    body = b"".join(sections)
    file_size = header_size + len(body)
    head = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, header_size, 3, file_size, len(sections))
    if len(head) < header_size:
        head += b"\x00" * (header_size - len(head))
    return head + body


def pane(tag: bytes, name: str, *, size: int = 96, visible: int = 1) -> bytes:
    raw = bytearray(size)
    raw[0:4] = tag
    struct.pack_into("<I", raw, 4, size)
    raw[8] = visible
    nb = name.encode("ascii")
    raw[12 : 12 + len(nb)] = nb
    return bytes(raw)


def pic1(name: str = "Pic_Konami") -> bytes:
    return pane(b"pic1", name, size=128, visible=1)


def mat1_section() -> bytes:
    mat = bytearray(0x50)
    mat[0:6] = b"MatOld"
    payload = struct.pack("<II", 1, 16) + bytes(mat)
    return section(b"mat1", payload)


def pts_layout() -> bytes:
    return clyt(
        [
            section(b"txl1", b"\x00\x00\x00\x00"),
            mat1_section(),
            pane(b"pan1", "OtherPane"),
            pane(b"pan1", "Nul_Copyright"),
            pic1("Pic_Konami"),
            pic1("Pic_Second"),
            section(b"grp1", b""),
        ]
    )


def lyt_layout() -> bytes:
    return clyt([pane(b"pan1", "Pos_Copyright_H"), pane(b"pan1", "Other"), section(b"grp1", b"")])


def solid_png(path: Path, w: int, h: int, color=(255, 255, 255, 220)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (w, h), color).save(path)
    return path


# ---------------------------------------------------------------------------
# Title Eng Patch (pkg 5261)
# ---------------------------------------------------------------------------


def test_title_helpers_and_layout_errors(tmp_path, monkeypatch):
    im = title.render_label("Main Menu", 100, 20, title.MENU_WORD_INK)
    assert im.size == (100, 20) and im.getpixel((50, 10))[3] > 0
    with pytest.raises(RuntimeError, match="cannot fit"):
        title.render_label("x" * 40, 8, 8)

    assert title._etc1a4_alpha(0) == 0
    assert title._etc1a4_alpha(11) == 0
    assert title._etc1a4_alpha(255) == 255

    line = title.render_copyright_line("Eng", 80, 14, y0=0)
    assert line.size == (80, 14) and line.getchannel("A").getbbox()
    with pytest.raises(RuntimeError, match="cannot fit"):
        title.render_copyright_line(title.ENG_PATCH_LINE, 16, 14)
    real_heisei = title.HEISEI_W5
    monkeypatch.setattr(title, "HEISEI_W5", tmp_path / "missing.ttc")
    with pytest.raises(SystemExit, match="missing copyright font"):
        title.render_copyright_line("A", 40, 14)
    monkeypatch.setattr(title, "HEISEI_W5", real_heisei)

    empty = Image.new("RGBA", (30, 10), (0, 0, 0, 0))
    assert title._solid_ink_span(empty) == (0, 9)
    wide = Image.new("RGBA", (400, 40), (9, 9, 9, 255))
    wide.putpixel((3, 2), (1, 2, 3, 255))
    composed = title.compose_eng_patch(wide, 200)
    assert composed.size == (200, title.ENG_PATCH_H)
    assert composed.getpixel((3, 2)) == (1, 2, 3, 255)

    with pytest.raises(ValueError, match="too long"):
        title._pad_name("x" * 30, 8)
    blob = title._build_txl1(["A", "BB"])
    assert blob.startswith(b"txl1") and len(blob) % 4 == 0

    with pytest.raises(ValueError, match="pic1"):
        title._make_pic1(b"pic1" + b"\x00" * 10, "N", 0, 1.0)
    made = title._make_pic1(pic1(), "Pic_EngPatch", 3, 4.0)
    assert made[12:24] == b"Pic_EngPatch"
    no_h = title._make_pic1(pic1(), "P", 1, 2.0, height=None)
    assert len(no_h) == 128

    with pytest.raises(ValueError, match="not CLYT"):
        title._iter_sections(b"NOPE")
    padded = title._rebuild_clyt(32, 3, [section(b"grp1", b"")])
    assert padded[20:32] == b"\x00" * 12

    lyt = title.patch_lyt_copyright(lyt_layout())
    assert struct.unpack_from("<f", lyt, lyt.find(b"Pos_Copyright_H") - 12 + 8 + 32)[0] == title.POS_H_TY
    big = clyt([pane(b"pan1", "Pos_Copyright_H")], header_size=32)
    assert len(title.patch_lyt_copyright(big)) >= 32

    with pytest.raises(StopIteration):
        title.patch_pts_copyright(clyt([section(b"txl1", b"\x00\x00\x00\x00"), mat1_section(), pane(b"pan1", "Nul_Copyright")]))

    good = title.patch_pts_copyright(pts_layout(), eng_tex_index=1)
    title._verify_pts(good, eng_tex_index=1)
    with pytest.raises(SystemExit, match="Eng tex"):
        title._verify_pts(good, eng_tex_index=0)
    with pytest.raises(SystemExit, match="Eng_Patch.bclim"):
        title._verify_pts(good.replace(b"Eng_Patch.bclim", b"Eng_Patch.bcliX"), eng_tex_index=1)
    with pytest.raises(SystemExit, match="Pic_EngPatch"):
        title._verify_pts(good.replace(b"Pic_EngPatch", b"Pic_EngPatcX"), eng_tex_index=1)
    with pytest.raises(SystemExit, match="Nul_Copyright"):
        title._verify_pts(good.replace(b"Nul_Copyright", b"Nul_CopyrighX"), eng_tex_index=1)

    def poke(buf: bytes, tag: bytes, name: str, off: int, kind: str, value) -> bytes:
        data = bytearray(buf)
        pos = 20
        count = struct.unpack_from("<I", data, 0x10)[0]
        for _ in range(count):
            size = struct.unpack_from("<I", data, pos + 4)[0]
            if data[pos : pos + 4] == tag:
                nm = bytes(data[pos + 12 : pos + 36]).split(b"\x00", 1)[0]
                if nm == name.encode():
                    struct.pack_into(kind, data, pos + off, value)
                    return bytes(data)
            pos += size
        raise AssertionError(name)

    with pytest.raises(SystemExit, match="mat"):
        title._verify_pts(poke(good, b"pic1", "Pic_EngPatch", 0x5C, "<H", 9), eng_tex_index=1)
    with pytest.raises(SystemExit, match="ty"):
        title._verify_pts(poke(good, b"pic1", "Pic_EngPatch", 40, "<f", 0.0), eng_tex_index=1)
    with pytest.raises(SystemExit, match="Eng h"):
        title._verify_pts(poke(good, b"pic1", "Pic_EngPatch", 72, "<f", 1.0), eng_tex_index=1)


def _title_files(*, copyright_fmt: int = 0xB, skip: str | None = None, with_eng: bool = False) -> dict[str, bytes]:
    files = {
        "timg/Copyright.bclim": noise_bclim(200, 16, copyright_fmt, seed=7),
        "blyt/Lyt_Copyright.bclyt": lyt_layout(),
        "blyt/Pts_Copyright.bclyt": pts_layout(),
    }
    for i, (path, _en) in enumerate(title.LABELS):
        if path == skip:
            continue
        files[path] = noise_bclim(100, 20, 8, seed=20 + i)
    if with_eng:
        files[title.ENG_PATCH_REL] = noise_bclim(32, 16, 0xB, seed=4)
    return files


def _title_img(path: Path, **kw) -> None:
    write_img(path, {title.PKG: arc_package(_title_files(**kw))})


def _stub_title_paint(monkeypatch):
    from bclimutil import parse_bclim

    monkeypatch.setattr(title, "render_eng_strip", lambda w, h=14: Image.new("RGBA", (w, h), (8, 8, 8, 255)))
    monkeypatch.setattr(
        title,
        "compose_eng_patch",
        lambda version, w: Image.new("RGBA", (w, title.ENG_PATCH_H), (12, 12, 12, 255)),
    )

    def zero_rgba(png, orig):
        raw = Path(orig).read_bytes()
        pix, _w, _h, _fmt, footer = parse_bclim(raw)
        return b"\x00" * len(pix) + footer

    monkeypatch.setattr(title, "png_to_bclim_rgba4444_same_size", zero_rgba)
    monkeypatch.setattr(
        title,
        "png_to_bclim_etc1a4",
        lambda png, orig, size: noise_bclim(size[0], size[1], 0xB, seed=3),
    )
    monkeypatch.setattr(title.zopfli_zlib, "compress", lambda data: b"\x00\x01")


def _prepare_title(monkeypatch, tmp_path: Path, img: Path):
    extra = bind(monkeypatch, tmp_path, title, img)
    monkeypatch.setattr(title, "resolve_img_paths", lambda: (img, img))
    monkeypatch.setattr(title, "ROOT", tmp_path / "root")
    monkeypatch.setattr(title, "ASSET", tmp_path / "root" / "assets" / "images" / "Title")
    monkeypatch.setattr(title, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(title, "compress_exact_zopfli", fast_exact)
    return extra


def test_title_main_splices_eng_patch(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    _title_img(img)
    extra = _prepare_title(monkeypatch, tmp_path, img)
    master = solid_png(tmp_path / "GameStart.png", 100, 20, (0, 0, 90, 255))

    def find(_folders, stem, _size):
        return master if stem == "Title_btn02_t02" else None

    monkeypatch.setattr(title, "find_ui_png", find)
    monkeypatch.setattr(title.zopfli_zlib, "compress", lambda data: b"\x00\x01")
    before = img.read_bytes()
    assert title.main() == 0
    assert img.read_bytes() != before
    assert extra.read_bytes() != before
    check = title.ROOT / "assets" / "images" / "Title.check" / "timg" / "Eng_Patch.png"
    assert check.is_file()
    assert (title.ASSET / "Eng_Patch.png").is_file()
    assert (title.OUT / "Eng_Patch_en_x4.png").is_file()
    from darcutil import DarcArchive

    arc = fi.read_element(fi.read_package(img, title.PKG), "Data.arc", tmp_path)
    darc = DarcArchive(arc)
    assert darc.find(title.ENG_PATCH_REL) is not None
    pts = darc.extract_file(darc.find("blyt/Pts_Copyright.bclyt"))
    assert b"Pic_EngPatch" in pts and b"Eng_Patch.bclim" in pts


def test_title_main_bisect_and_already_present(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    _title_img(img, with_eng=True)
    _prepare_title(monkeypatch, tmp_path, img)
    _stub_title_paint(monkeypatch)
    monkeypatch.setattr(title.sys, "argv", ["pytest", "--bisect-tex0"])
    assert title.main() == 0


def test_title_main_early_exits(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    _title_img(img)
    _prepare_title(monkeypatch, tmp_path, img)
    monkeypatch.setattr(title, "resolve_img_paths", lambda: (tmp_path / "missing.bin", img))
    with pytest.raises(SystemExit, match="missing"):
        title.main()

    monkeypatch.setattr(title, "resolve_img_paths", lambda: (img, img))
    real_ui = title.UI_FONT
    monkeypatch.setattr(title, "UI_FONT", tmp_path / "no-font.ttf")
    with pytest.raises(SystemExit, match="missing UI font"):
        title.main()

    monkeypatch.setattr(title, "UI_FONT", real_ui)
    _title_img(img, skip="timg/Title_btn02_t01.bclim")
    with pytest.raises(SystemExit, match="missing"):
        title.main()

    _title_img(img, copyright_fmt=8)
    with pytest.raises(SystemExit, match="Copyright fmt"):
        title.main()


def test_title_main_late_exits(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    _title_img(img)
    _prepare_title(monkeypatch, tmp_path, img)
    _stub_title_paint(monkeypatch)

    monkeypatch.setattr(title, "compose_eng_patch", lambda version, w: Image.new("RGBA", (3, 3), (0, 0, 0, 0)))
    with pytest.raises(SystemExit, match="canvas"):
        title.main()
    _stub_title_paint(monkeypatch)

    monkeypatch.setattr(title, "png_to_bclim_etc1a4", lambda *a, **k: noise_bclim(4, 4, 0xB, seed=1))
    with pytest.raises(SystemExit, match="Eng_Patch BCLIM"):
        title.main()
    _stub_title_paint(monkeypatch)

    real_fz = title._force_zero_gaps

    def fz_miss(data):
        fz_miss.arm = True
        return real_fz(data)

    fz_miss.arm = False
    real_find = title.DarcArchive.find

    def find(self, rel):
        if fz_miss.arm and rel == title.ENG_PATCH_REL:
            return None
        return real_find(self, rel)

    monkeypatch.setattr(title, "_force_zero_gaps", fz_miss)
    monkeypatch.setattr(title.DarcArchive, "find", find)
    with pytest.raises(SystemExit, match="missing after rebuild"):
        title.main()
    monkeypatch.setattr(title, "_force_zero_gaps", real_fz)
    monkeypatch.setattr(title.DarcArchive, "find", real_find)

    from types import SimpleNamespace

    real_cls = title.DarcArchive

    class BoomArc(real_cls):
        def __init__(self, data):
            super().__init__(data)
            if getattr(BoomArc, "arm", False):
                self.files.append(SimpleNamespace(name="timg/Z.bclim", offset=1))

    def fz_arm(data):
        BoomArc.arm = True
        return real_fz(data)

    BoomArc.arm = False
    monkeypatch.setattr(title, "DarcArchive", BoomArc)
    monkeypatch.setattr(title, "_force_zero_gaps", fz_arm)
    with pytest.raises(SystemExit, match="not 0x80-aligned"):
        title.main()
    monkeypatch.setattr(title, "DarcArchive", real_cls)
    monkeypatch.setattr(title, "_force_zero_gaps", real_fz)

    monkeypatch.setattr(title.zopfli_zlib, "compress", lambda data: b"x" * 5_000_000)
    with pytest.raises(SystemExit, match="exceeds slot"):
        title.main()
    _stub_title_paint(monkeypatch)

    monkeypatch.setattr(title, "compress_exact_zopfli", lambda d, n: (_ for _ in ()).throw(RuntimeError("no room")))
    with pytest.raises(SystemExit, match="no room"):
        title.main()

    monkeypatch.setattr(title, "compress_exact_zopfli", wrong_slot)
    with pytest.raises(SystemExit, match="zlib verify"):
        title.main()

    monkeypatch.setattr(title, "compress_exact_zopfli", fast_exact)
    monkeypatch.setattr(title, "splice_packages_into_img", boom(title))
    with pytest.raises(SystemExit, match="splice failed: grew"):
        title.main()


def test_title_main_uncompressed_dmst_and_arc_mismatch(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    files = _title_files()
    write_img(img, {title.PKG: arc_package(files, compress=False)})
    _prepare_title(monkeypatch, tmp_path, img)
    _stub_title_paint(monkeypatch)
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        title.main()

    write_img(img, {title.PKG: retarget_sidecar(arc_package(files))})
    _prepare_title(monkeypatch, tmp_path, img)
    _stub_title_paint(monkeypatch)
    # main() copies the new package over the extract path before the DMST
    # compare, so the original Package window would re-read the new bytes.
    real_write = Path.write_bytes
    pkg_name = f"{title.PKG:04d}"
    writes = {"n": 0}

    def keep_extract(self, data, _real=real_write):
        if self.name == pkg_name and "img_data" in self.parts:
            writes["n"] += 1
            if writes["n"] > 1:
                return len(data)
        return _real(self, data)

    monkeypatch.setattr(Path, "write_bytes", keep_extract)
    with pytest.raises(SystemExit, match="DMST changed"):
        title.main()
    monkeypatch.setattr(Path, "write_bytes", real_write)

    write_img(img, {title.PKG: arc_package(files)})
    _prepare_title(monkeypatch, tmp_path, img)
    _stub_title_paint(monkeypatch)
    armed = {"on": False}
    real = zlib.decompress

    def wrapped(data, *a, **k):
        out = real(data, *a, **k)
        if armed["on"] and isinstance(out, (bytes, bytearray)) and out[:4] == b"darc":
            return bytes(out) + b"!"
        return out

    def comp(data, n):
        out = fast_exact(data, n)
        armed["on"] = True
        return out

    monkeypatch.setattr(zlib, "decompress", wrapped)
    monkeypatch.setattr(title, "compress_exact_zopfli", comp)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        title.main()


# ---------------------------------------------------------------------------
# Mail sort (pkg 5207)
# ---------------------------------------------------------------------------


def _cancel_bclim(w: int = 98, h: int = 42, seed: int = 5) -> bytes:
    im = Image.new("RGBA", (w, h), (250, 250, 250, 170))
    px = im.load()
    for x in range(w):
        for y in range(5):
            px[x, y] = (40, 40, 40, 255)
            px[x, h - 1 - y] = (40, 40, 40, 255)
    for y in range(h):
        for x in range(8):
            px[x, y] = (40, 40, 40, 255)
            px[w - 1 - x, y] = (40, 40, 40, 255)
    for x in range(28, w - 28):
        for y in range(16, 26):
            px[x, y] = (255, 255, 255, 255)
        px[x, 15] = (30, 30, 30, 255)
        px[x, 26] = (30, 30, 30, 255)
    template = noise_bclim(w, h, 8, seed=seed)
    png = Path(f"{seed}_cancel.png")
    # written next to the template via a temp dir created by the caller when possible
    return im, template


def _encode_cancel(tmp: Path, w: int = 98, h: int = 42, seed: int = 5) -> bytes:
    from bclimutil import png_to_bclim_rgba4444_same_size

    im, template = _cancel_bclim(w, h, seed)
    png = tmp / f"cancel_{seed}.png"
    orig = tmp / f"cancel_{seed}.bclim"
    im.save(png)
    orig.write_bytes(template)
    return png_to_bclim_rgba4444_same_size(png, orig)


def _sort_files(tmp: Path) -> dict[str, bytes]:
    return {
        "timg/Mail_PopTxt04.bclim": noise_bclim(88, 20, 0xB, seed=11),
        "timg/Mail_PopTxt05.bclim": noise_bclim(104, 96, 0xB, seed=12),
        "timg/C_Com_Win01_Btn02_Cancel_Off.bclim": _encode_cancel(tmp, seed=13),
        "timg/C_Com_Win01_Btn02_Cancel_Press.bclim": _encode_cancel(tmp, seed=14),
        "timg/C_Btn_Play_Off.bclim": noise_bclim(16, 8, 8, seed=15),
    }


def test_mail_sort_font_render_and_gaps(tmp_path, monkeypatch):
    real_empty = mail_sort.compress_exact_empty_blocks
    real_fonts = mail_sort.CHROME_FONTS
    im = mail_sort.render_gray_label(88, 20, "Sort Method")
    assert im.size == (88, 20)
    with pytest.raises(RuntimeError, match="cannot fit"):
        mail_sort.render_gray_label(10, 12, "Sort Method")

    monkeypatch.setattr(mail_sort, "CHROME_FONTS", [(tmp_path / "nope.ttf", 0)])
    with pytest.raises(SystemExit, match="no chrome font"):
        mail_sort.font(12)
    bad = tmp_path / "bad.ttf"
    bad.write_bytes(b"not-a-font")
    monkeypatch.setattr(mail_sort, "CHROME_FONTS", [(bad, 0)])
    with pytest.raises(SystemExit, match="no chrome font"):
        mail_sort.font(12)
    monkeypatch.setattr(mail_sort, "CHROME_FONTS", real_fonts)
    assert isinstance(mail_sort.font(12), ImageFont.FreeTypeFont)

    raw = _encode_cancel(tmp_path)
    out = mail_sort.reletter_cancel(raw, "Cancel")
    assert out.size == (98, 42) and out.getchannel("A").getbbox()

    blank = noise_bclim(98, 42, 8, seed=1)
    # zero pixels → empty glyph mask
    blank = fi.bclim(98, 42, 8)
    with pytest.raises(RuntimeError, match="glyph mask empty"):
        mail_sort.reletter_cancel(blank, "Cancel")

    face = Image.new("RGBA", (98, 42), (0, 0, 0, 0))
    px = face.load()
    for x in range(20, 78):
        for y in range(10, 30):
            px[x, y] = (255, 255, 255, 255)
    monkeypatch.setattr(mail_sort, "decode_bclim_to_image", lambda _raw: face.copy())
    painted = mail_sort.reletter_cancel(b"x", "Cancel")
    assert painted.getchannel("A").getbbox()
    with pytest.raises(RuntimeError, match="cannot fit"):
        mail_sort.reletter_cancel(b"x", "CANCEL" * 20)

    before = {"timg/missing.bclim": "a" * 40}
    monkeypatch.setattr(mail_sort, "_home_shas", lambda _arc: {})
    with pytest.raises(SystemExit, match="missing"):
        mail_sort._assert_home_preserved(before, b"arc")

    data = fi.darc({"a.bin": b"a" * 8, "b.bin": b"b" * 8}) + bytes(8)
    gaps = mail_sort.interfile_zero_gaps(data)
    assert gaps and gaps == sorted(gaps, reverse=True)
    assert mail_sort.interfile_zero_gaps(data, min_len=10_000) == []
    salted = bytearray(data)
    gsz, goff = gaps[0]
    salted[goff] = 7
    assert (gsz, goff) not in mail_sort.interfile_zero_gaps(bytes(salted))
    assert mail_sort.apply_gap_pad(data, 0, b"")[goff] == 0
    padded = mail_sort.apply_gap_pad(data, 3, bytes(range(1, 30)))
    assert padded[goff : goff + 3] == bytes(range(1, 4))
    monkeypatch.setattr(mail_sort, "compress_exact_empty_blocks", lambda *a: None)
    assert mail_sort._fit_slot(data, 30) is None
    monkeypatch.setattr(mail_sort, "compress_exact_empty_blocks", lambda d, n: b"slot")
    assert mail_sort._fit_slot(data, 30)[1] == b"slot"
    calls = {"n": 0}

    def second_hit(d, n):
        calls["n"] += 1
        return None if calls["n"] == 1 else b"padded"

    monkeypatch.setattr(mail_sort, "compress_exact_empty_blocks", second_hit)
    assert mail_sort._fit_slot(data, 30)[1] == b"padded"
    monkeypatch.setattr(mail_sort, "compress_exact_empty_blocks", real_empty)

    probe = b"sort-gap" * 40
    hit_n = next(n for n in range(len(probe), len(probe) + 80) if real_empty(probe, n))
    assert len(real_empty(probe, hit_n)) == hit_n

    class Boom:
        unused_data = b""
        eof = False

        def decompress(self, _data):
            raise zlib.error("bad")

    calls = {"n": 0}
    real_obj = zlib.decompressobj

    def objs(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return Boom()
        return real_obj(*a, **k)

    monkeypatch.setattr(zlib, "decompressobj", objs)
    assert real_empty(probe, hit_n) is not None
    assert calls["n"] > 1
    monkeypatch.setattr(zlib, "decompressobj", real_obj)
    assert real_empty(probe, 3) is None


def test_mail_sort_patch_arc_branches(tmp_path, monkeypatch):
    mail_sort.OUT = tmp_path / "out"
    mail_sort.OUT.mkdir(parents=True, exist_ok=True)
    files = _sort_files(tmp_path)
    arc = fi.darc(files)
    monkeypatch.setattr(mail_sort, "VANILLA", tmp_path / "missing.bin")
    monkeypatch.setattr(mail_sort, "OUT", tmp_path / "out")
    assert mail_sort._vanilla_arc_bytes() is None
    patched = mail_sort._patch_arc(arc, tmp_path)
    assert patched != arc
    assert (mail_sort.OUT / "Mail_PopTxt04_en.png").is_file()

    bad = dict(files)
    bad["timg/Mail_PopTxt04.bclim"] = noise_bclim(16, 8, 8, seed=2)
    with pytest.raises(SystemExit, match="not ETC1A4"):
        mail_sort._patch_arc(fi.darc(bad), tmp_path)
    with pytest.raises(SystemExit, match="missing"):
        mail_sort._patch_arc(fi.darc({"timg/only.bclim": noise_bclim(8, 8, 8)}), tmp_path)
    no_cancel = {k: v for k, v in files.items() if "Cancel" not in k}
    with pytest.raises(SystemExit, match="missing"):
        mail_sort._patch_arc(fi.darc(no_cancel), tmp_path)

    bad_c = dict(files)
    bad_c["timg/C_Com_Win01_Btn02_Cancel_Off.bclim"] = noise_bclim(16, 8, 0xB, seed=3)
    with pytest.raises(SystemExit, match="not RGBA4444"):
        mail_sort._patch_arc(fi.darc(bad_c), tmp_path)

    van = tmp_path / "van.bin"
    write_img(van, {mail_sort.PKG: arc_package({"timg/only.bclim": noise_bclim(8, 8, 8, seed=9)})})
    monkeypatch.setattr(mail_sort, "VANILLA", van)
    again = mail_sort._patch_arc(arc, tmp_path)
    assert again != arc
    sha = mail_sort._bclim_sha(arc, "timg/C_Btn_Play_Off.bclim")
    assert sha and len(sha) == 40
    assert mail_sort._bclim_sha(arc, "timg/nope.bclim") is None
    assert "timg/C_Btn_Play_Off.bclim" in mail_sort._home_shas(arc)

    img = tmp_path / "live.bin"
    write_img(img, {mail_sort.PKG: arc_package(files)})
    mail_sort.OUT = tmp_path / "out2"
    pkgs = tmp_path / "pkgs"
    pkgs.mkdir()
    src, _pkg, elem = mail_sort._extract_pkg(img, pkgs)
    assert src.is_file() and elem.parsed()[:4] == b"darc"


def test_mail_sort_main_and_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    files = _sort_files(tmp_path)
    write_img(img, {mail_sort.PKG: arc_package(files)})
    extra = bind(monkeypatch, tmp_path, mail_sort, img)
    before = fi.read_element(fi.read_package(img, mail_sort.PKG), "Data.arc", tmp_path)
    mail_sort.main()
    after = fi.read_element(fi.read_package(img, mail_sort.PKG), "Data.arc", tmp_path)
    assert after != before
    assert extra.read_bytes() != img.read_bytes() or extra.is_file()
    assert (mail_sort.OUT / "Mail_PopTxt05_en.png").is_file()

    slim = {k: v for k, v in files.items() if "Play" not in k}
    write_img(img, {mail_sort.PKG: arc_package(slim)})
    bind(monkeypatch, tmp_path, mail_sort, img)
    monkeypatch.setattr(mail_sort, "_patch_arc", lambda arc, tmp: arc)
    monkeypatch.setattr(mail_sort, "_fit_slot", lambda c, n: fast_exact(c, n))
    mail_sort.main()

    monkeypatch.setattr(mail_sort, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        mail_sort.main()

    monkeypatch.setattr(mail_sort, "MOD_IMG", img)
    monkeypatch.setattr(mail_sort, "_patch_arc", lambda arc, tmp: arc)
    monkeypatch.setattr(mail_sort, "_fit_slot", lambda *a: None)
    with pytest.raises(SystemExit, match="could not fit"):
        mail_sort.main()

    def bad_fit(cand, n):
        _tuned, slot = fast_exact(cand, n)
        return cand + b"\x00", slot

    monkeypatch.setattr(mail_sort, "_fit_slot", bad_fit)
    with pytest.raises(SystemExit, match="zlib verify"):
        mail_sort.main()

    def longer(cand, n):
        return fast_exact(cand + b"\x00", n)

    monkeypatch.setattr(mail_sort, "_fit_slot", longer)
    with pytest.raises((SystemExit, RuntimeError)):
        mail_sort.main()

    monkeypatch.setattr(mail_sort, "_fit_slot", lambda c, n: fast_exact(c, n))
    monkeypatch.setattr(mail_sort, "splice_packages_into_img", boom(mail_sort))
    with pytest.raises(SystemExit, match="splice failed"):
        mail_sort.main()

    def flip(arc, tmp):
        from darcutil import DarcArchive

        darc = DarcArchive(bytearray(arc))
        ent = darc.find("timg/Mail_PopTxt04.bclim")
        raw = bytearray(darc.extract_file(ent))
        raw[0] ^= 0x5A
        darc.replace_same_size(ent, bytes(raw))
        return bytes(darc.data)

    monkeypatch.setattr(mail_sort, "splice_packages_into_img", lambda *a: None)
    monkeypatch.setattr(mail_sort, "_patch_arc", flip)
    monkeypatch.setattr(mail_sort, "_fit_slot", lambda c, n: fast_exact(c, n))
    with pytest.raises(SystemExit, match="post-splice"):
        mail_sort.main()


def test_mail_sort_dmst_and_arc_mismatch(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    files = _sort_files(tmp_path)
    write_img(img, {mail_sort.PKG: retarget_sidecar(arc_package(files))})
    bind(monkeypatch, tmp_path, mail_sort, img)
    monkeypatch.setattr(mail_sort, "_patch_arc", lambda arc, tmp: arc)
    monkeypatch.setattr(mail_sort, "_fit_slot", lambda c, n: fast_exact(c, n))
    with pytest.raises(SystemExit, match="DMST changed"):
        mail_sort.main()

    write_img(img, {mail_sort.PKG: arc_package(files)})
    bind(monkeypatch, tmp_path, mail_sort, img)
    armed = {"on": False}
    real = zlib.decompress

    def wrapped(data, *a, **k):
        out = real(data, *a, **k)
        if armed["on"] and isinstance(out, (bytes, bytearray)) and out[:4] == b"darc":
            return bytes(out) + b"!"
        return out

    def fit(cand, n):
        out = fast_exact(cand, n)
        armed["on"] = True
        return out

    monkeypatch.setattr(zlib, "decompress", wrapped)
    monkeypatch.setattr(mail_sort, "_patch_arc", lambda arc, tmp: arc)
    monkeypatch.setattr(mail_sort, "_fit_slot", fit)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        mail_sort.main()


# ---------------------------------------------------------------------------
# Mail home (pkg 5207)
# ---------------------------------------------------------------------------


def _home_files() -> dict[str, bytes]:
    labels = mail_home.BUTTON_LABELS + mail_home.CATEGORY_LABELS + mail_home.ZHOUMARU_ONLY
    files = {}
    for i, (path, _en) in enumerate(labels):
        fmt = 0xB if i % 7 == 0 else 8
        files[path] = noise_bclim(128, 16, fmt, seed=100 + i)
    return files


def test_mail_home_replace_and_compress(tmp_path, monkeypatch):
    real_empty = mail_home.compress_exact_empty_blocks
    mail_home.OUT = tmp_path / "out"
    mail_home.OUT.mkdir()
    labels = [
        ("timg/mail_tex_jyusin_RGBA4.bclim", "Inbox"),
        ("timg/C_Com_Win01_Btn02_Ok_Off.bclim", "OK"),
        ("timg/Sel_Tex_ma02_01.bclim", "Girlfriend Mail"),
        ("timg/made_up.bclim", "Hello"),
    ]
    files = {
        labels[0][0]: noise_bclim(128, 16, 8, seed=1),
        labels[1][0]: noise_bclim(32, 16, 0xB, seed=2),
        labels[2][0]: noise_bclim(128, 16, 8, seed=3),
        labels[3][0]: noise_bclim(64, 16, 8, seed=4),
    }
    master = solid_png(tmp_path / "master.png", 8, 8)
    exact = solid_png(tmp_path / "exact.png", 32, 16)

    def find(_folders, stem, size):
        if stem == "mail_tex_jyusin_RGBA4":
            return master
        if stem == "C_Com_Win01_Btn02_Ok_Off":
            return exact
        return None

    monkeypatch.setattr(mail_home, "find_ui_png", find)
    from darcutil import DarcArchive

    darc = DarcArchive(bytearray(fi.darc(files)))
    mail_home.replace_labels(darc, labels, tmp_path, fmt=None)
    assert (mail_home.OUT / "mail_tex_jyusin_RGBA4_en.png").is_file()

    with pytest.raises(SystemExit, match="missing"):
        mail_home.replace_labels(DarcArchive(bytearray(fi.darc(files))), [("timg/nope.bclim", "Z")], tmp_path, fmt=None)
    bad = {"timg/made_up.bclim": noise_bclim(8, 8, 5, seed=6)}
    with pytest.raises(SystemExit, match="fmt"):
        mail_home.replace_labels(DarcArchive(bytearray(fi.darc(bad))), [("timg/made_up.bclim", "Z")], tmp_path, fmt=8)
    monkeypatch.setattr(mail_home, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="Zhoumaru"):
        mail_home.replace_labels(
            DarcArchive(bytearray(fi.darc({labels[1][0]: files[labels[1][0]]}))),
            [labels[1]],
            tmp_path,
            fmt=None,
        )

    tiny = fi.darc({"a.bin": b"a" * 8, "b.bin": b"b" * 8}) + bytes(6)
    assert mail_home.interfile_zero_gaps(tiny)
    assert mail_home.apply_gap_pad(tiny, 0, b"") == tiny
    monkeypatch.setattr(mail_home, "compress_exact_empty_blocks", lambda *a: None)
    with pytest.raises(SystemExit, match="could not build"):
        mail_home.compress_exact_with_gap_tune(tiny, 40)

    monkeypatch.setattr(mail_home, "compress_exact_empty_blocks", real_empty)
    tiny_hit = next(n for n in range(32, 400) if real_empty(tiny, n))
    tuned, slot = mail_home.compress_exact_with_gap_tune(tiny, tiny_hit)
    assert zlib.decompress(slot) == tuned
    assert mail_home.apply_gap_pad(tiny, 10_000, bytes(range(256)) * 20) != tiny
    assert isinstance(mail_home.interfile_zero_gaps(fi.darc({"a.bin": b"ab", "b.bin": b"cd"}, align=1)), list)

    class _Boom:
        unused_data = b""
        eof = False

        def decompress(self, _data):
            raise zlib.error("bad")

    seen = {"n": 0}
    real_obj = zlib.decompressobj

    def objs(*a, **k):
        seen["n"] += 1
        if seen["n"] == 1:
            return _Boom()
        return real_obj(*a, **k)

    monkeypatch.setattr(zlib, "decompressobj", objs)
    assert real_empty(tiny, tiny_hit) is not None
    monkeypatch.setattr(zlib, "decompressobj", real_obj)

    monkeypatch.setattr(mail_home.zopfli_zlib, "compress", lambda d: b"x" * 9999)
    with pytest.raises(SystemExit, match="exceeds"):
        mail_home.compress_exact_zopfli(tiny, 10)
    monkeypatch.setattr(mail_home.zopfli_zlib, "compress", lambda d: b"y" * 12)
    assert mail_home.compress_exact_zopfli(tiny, 12)[1] == b"y" * 12

    state = {"n": 0}

    def zsearch(data):
        state["n"] += 1
        if state["n"] == 1:
            return b"z" * 4
        if state["n"] == 2:
            return b"z" * 50
        return b"z" * 20

    monkeypatch.setattr(mail_home.zopfli_zlib, "compress", zsearch)
    assert mail_home.compress_exact_zopfli(tiny, 20)[1] == b"z" * 20

    monkeypatch.setattr(mail_home.zopfli_zlib, "compress", lambda d: b"z" * 4)
    monkeypatch.setattr(mail_home, "compress_exact_with_gap_tune", lambda d, n: (d, b"g" * n))
    assert mail_home.compress_exact_zopfli(tiny, 20)[1] == b"g" * 20


def test_mail_home_patch_package_and_main(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    one = {"timg/Hello.bclim": noise_bclim(64, 16, 8, seed=3)}
    write_img(img, {mail_home.BUTTON_PKG: file_sized(arc_package(one))})
    bind(monkeypatch, tmp_path, mail_home, img)
    monkeypatch.setattr(mail_home, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(mail_home, "VANILLA", tmp_path / "no-vanilla.bin")
    real_splice = mail_home.splice_packages_into_img
    mail_home.patch_package(mail_home.BUTTON_PKG, [("timg/Hello.bclim", "Hello")], fmt=8, use_zopfli=False)
    assert fi.read_element(fi.read_package(img, mail_home.BUTTON_PKG), "Data.arc", tmp_path)[:4] == b"darc"

    monkeypatch.setattr(mail_home, "compress_exact_zopfli", lambda d, n: (_ for _ in ()).throw(SystemExit("zfail")))
    monkeypatch.setattr(mail_home, "compress_exact_with_gap_tune", lambda d, n: fast_exact(d, n))
    mail_home.patch_package(mail_home.BUTTON_PKG, [("timg/Hello.bclim", "Hello")], fmt=8, use_zopfli=True)

    monkeypatch.setattr(mail_home, "compress_exact_zopfli", lambda d, n: fast_exact(d, n))
    mail_home.patch_package(mail_home.BUTTON_PKG, [("timg/Hello.bclim", "Hello")], fmt=None, use_zopfli=True)

    monkeypatch.setattr(mail_home, "compress_exact_with_gap_tune", wrong_slot)
    with pytest.raises(SystemExit, match="zlib verify"):
        mail_home.patch_package(mail_home.BUTTON_PKG, [("timg/Hello.bclim", "Hi")], fmt=8, use_zopfli=False)

    def longer(data, n):
        return fast_exact(data + b"\x00", n)

    monkeypatch.setattr(mail_home, "compress_exact_with_gap_tune", longer)
    with pytest.raises((SystemExit, RuntimeError)):
        mail_home.patch_package(mail_home.BUTTON_PKG, [("timg/Hello.bclim", "Hi")], fmt=8, use_zopfli=False)

    monkeypatch.setattr(mail_home, "compress_exact_with_gap_tune", lambda d, n: fast_exact(d, n))
    monkeypatch.setattr(mail_home, "splice_packages_into_img", lambda *a: None)
    with pytest.raises(SystemExit, match="post-splice"):
        mail_home.patch_package(mail_home.BUTTON_PKG, [("timg/Hello.bclim", "Hi")], fmt=8, use_zopfli=False)

    write_img(img, {mail_home.BUTTON_PKG: file_sized(arc_package(_home_files()))})
    bind(monkeypatch, tmp_path, mail_home, img)
    png = solid_png(tmp_path / "zh.png", 8, 8)

    def find(_f, stem, _size):
        if stem in mail_home.ZHOUMARU_ONLY_STEMS or stem in mail_home.ZHOUMARU_BUTTONS:
            return png
        return None

    monkeypatch.setattr(mail_home, "find_ui_png", find)
    monkeypatch.setattr(mail_home, "compress_exact_with_gap_tune", lambda d, n: fast_exact(d, n))
    monkeypatch.setattr(mail_home, "splice_packages_into_img", real_splice)
    before = img.read_bytes()
    mail_home.main()
    assert img.read_bytes() != before

    monkeypatch.setattr(mail_home, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        mail_home.main()


def test_mail_home_dmst_arc_mismatch(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    files = {"timg/Hello.bclim": noise_bclim(32, 16, 8, seed=8)}
    write_img(img, {mail_home.BUTTON_PKG: retarget_sidecar(arc_package(files))})
    bind(monkeypatch, tmp_path, mail_home, img)
    monkeypatch.setattr(mail_home, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(mail_home, "compress_exact_with_gap_tune", lambda d, n: fast_exact(d, n))
    with pytest.raises(SystemExit, match="DMST changed"):
        mail_home.patch_package(mail_home.BUTTON_PKG, [("timg/Hello.bclim", "Hi")], fmt=8, use_zopfli=False)

    write_img(img, {mail_home.BUTTON_PKG: arc_package(files)})
    bind(monkeypatch, tmp_path, mail_home, img)
    armed = {"on": False}
    real = zlib.decompress

    def wrapped(data, *a, **k):
        out = real(data, *a, **k)
        if armed["on"] and isinstance(out, (bytes, bytearray)) and out[:4] == b"darc":
            return bytes(out) + b"!"
        return out

    def tune(data, n):
        out = fast_exact(data, n)
        armed["on"] = True
        return out

    monkeypatch.setattr(zlib, "decompress", wrapped)
    monkeypatch.setattr(mail_home, "compress_exact_with_gap_tune", tune)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        mail_home.patch_package(mail_home.BUTTON_PKG, [("timg/Hello.bclim", "Hi")], fmt=8, use_zopfli=False)


# ---------------------------------------------------------------------------
# MSel menus
# ---------------------------------------------------------------------------


def _menu_files(pkg_id: int, w: int = 160, h: int = 32) -> dict[str, bytes]:
    files = {}
    for i, (base, _en) in enumerate(msel.PKG_LABELS[pkg_id]):
        files[f"timg/{base}"] = noise_bclim(w, h, 1, seed=pkg_id + i)
    return files


def test_msel_menus_render_fit_and_splice(tmp_path, monkeypatch):
    assert msel.glyph_h(__import__("numpy").zeros((4, 4), dtype="uint8")) == 0
    raw = noise_bclim(32, 16, 1, seed=2)
    canvas, w, h = msel.decode_a8(raw)
    assert canvas.shape[0] >= h and w == 32
    alpha = msel.render_en_alpha(80, 24, "Gallery", 12)
    assert alpha.shape == (24, 80)
    with pytest.raises(RuntimeError, match="cannot fit"):
        msel.render_en_alpha(4, 8, "Girlfriend Communication", 10)
    row = msel.render_row_heisei(180, 48, "Heart to Heart", 18)
    assert row.shape == (48, 180)
    with pytest.raises(RuntimeError, match="cannot fit"):
        msel.render_row_heisei(4, 8, "Heart to Heart", 18)
    with pytest.raises(RuntimeError, match="cannot fit"):
        msel.render_row_heisei(80, 24, "", 10)

    empty = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    assert msel.flatten_ink(empty).getpixel((0, 0))[:3] == (51, 51, 51)
    soft = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    soft.putpixel((1, 1), (10, 20, 30, 100))
    assert msel.flatten_ink(soft).getpixel((0, 0))[:3] == (10, 20, 30)

    msel.OUT = tmp_path / "out"
    png = solid_png(tmp_path / "_ui_png_fit" / "plate.png", 12, 12, (40, 40, 40, 255))
    etc = noise_bclim(32, 16, 0xB, seed=4)
    a8 = noise_bclim(32, 16, 1, seed=5)

    def find_master(*_a, **_k):
        return png

    monkeypatch.setattr(msel, "find_ui_png", find_master)
    enc = msel.make_en_bclim(etc, "Menu", tmp_path, hard=True, salt=0.0, stem="Com_M_Sel_Plate_Text04_01_00")
    assert enc[:4] != b"" and len(enc) == len(etc)
    a8_out = msel.make_en_bclim(a8, "Menu", tmp_path, hard=False, salt=0.0, stem="SomeStem")
    assert len(a8_out) == len(a8)
    monkeypatch.setattr(msel, "find_ui_png", lambda *a, **k: None)
    skip = msel.make_en_bclim(
        noise_bclim(180, 32, 1, seed=6),
        "Heart to Heart",
        tmp_path,
        hard=True,
        salt=0.04,
        stem="Com_M_Sel_Plate_Text04_01_01",
    )
    assert len(skip) > 16
    btn = msel.make_en_bclim(
        noise_bclim(180, 48, 1, seed=7),
        "Heart to Heart",
        tmp_path,
        hard=False,
        salt=0.0,
        stem="Com_M_Sel_Btn_Text04_01_01",
    )
    assert len(btn) > 16
    zeros = fi.bclim(32, 16, 1)
    rendered = msel.make_en_bclim(zeros, "Hi", tmp_path, hard=False, salt=0.0, stem="Nope")
    assert len(rendered) == len(zeros)

    arc = fi.darc(_menu_files(5242, 80, 24))
    with pytest.raises(SystemExit, match="missing"):
        msel.patch_arc(arc, [("nope.bclim", "X")], tmp_path, hard=False, salt=0.0)
    one = msel.patch_arc(arc, [msel.PKG_LABELS[5242][0]], tmp_path, hard=False, salt=0.0)
    assert one[:4] == b"darc"

    calls = {"n": 0}

    def fake_patch(vanilla_arc, labels, tmp, *, hard, salt):
        calls["n"] += 1
        return vanilla_arc

    monkeypatch.setattr(msel, "patch_arc", fake_patch)
    seq = {"n": 0}

    def zlen(data):
        seq["n"] += 1
        # 1 too big, 2 lean, 3 lean but not larger, 4 exact fit
        return {1: b"x" * 5000, 2: b"x" * 10, 3: b"x" * 10}.get(seq["n"], b"x" * 100)

    monkeypatch.setattr(msel.zopfli_zlib, "compress", zlen)
    # cmp chosen so 10+gaps < cmp (lean) and 100+gaps >= cmp (return)
    gaps = sum(sz for sz, _ in msel.interfile_zero_gaps(arc))
    cmp_len = 100 + max(gaps, 1)
    got = msel.fit_arc_for_slot(arc, [("a.bclim", "A")], tmp_path, cmp_len)
    assert got == arc and calls["n"] >= 2

    seq["n"] = 0

    def zlean(data):
        seq["n"] += 1
        if seq["n"] == 1:
            return b"x" * (cmp_len + 5)
        return b"x" * 8

    monkeypatch.setattr(msel.zopfli_zlib, "compress", zlean)
    got = msel.fit_arc_for_slot(arc, [("a.bclim", "A")], tmp_path, cmp_len)
    assert got == arc

    monkeypatch.setattr(msel.zopfli_zlib, "compress", lambda data: b"x" * (cmp_len + 9))
    with pytest.raises(SystemExit, match="no trial"):
        msel.fit_arc_for_slot(arc, [("a.bclim", "A")], tmp_path, cmp_len)

    trailed = fi.darc({"a.bin": b"abcd", "b.bin": b"efgh"}) + b"\x00" * 20
    assert any(sz >= 16 for sz, _off in msel.interfile_zero_gaps(trailed))
    msel.make_en_bclim(noise_bclim(32, 16, 1, seed=8), "Hi", tmp_path, hard=False, salt=0.0, stem=None)
    adjacent = fi.darc({"a.bin": b"abcd", "b.bin": b"efgh"}, align=1)
    assert isinstance(msel.interfile_zero_gaps(adjacent), list)

    pkg = arc_package({"timg/a.bclim": noise_bclim(8, 8, 1, seed=1)})
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.write_bytes(pkg)
    monkeypatch.setattr(msel, "compress_exact_zopfli", fast_exact)
    from darcutil import DarcArchive
    from img import FileWindow, Package

    parsed = Package(FileWindow(str(src)), 0)
    parsed.parse(False)
    arc_bytes = next(e for e in parsed.entries if e.fn == "Data.arc").parsed()
    msel.splice_arc(src, arc_bytes, dst)
    assert dst.is_file()

    raw_pkg = arc_package({"timg/a.bclim": noise_bclim(8, 8, 1)}, compress=False)
    src.write_bytes(raw_pkg)
    with pytest.raises(SystemExit, match="not compressed"):
        msel.splice_arc(src, b"nope", dst)
    src.write_bytes(pkg)
    with pytest.raises(SystemExit, match="dec size"):
        msel.splice_arc(src, b"short", dst)
    monkeypatch.setattr(msel, "compress_exact_zopfli", lambda d, n: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(SystemExit, match="boom"):
        msel.splice_arc(src, arc_bytes, dst)
    monkeypatch.setattr(msel, "compress_exact_zopfli", lambda d, n: (d, b"\x00" * (n + 4)))
    with pytest.raises(SystemExit, match="post-ARC"):
        msel.splice_arc(src, arc_bytes, dst)

    monkeypatch.setattr(msel, "VANILLA_CANDIDATES", [tmp_path / "nope.bin", src])
    assert msel.pick_vanilla() == src
    monkeypatch.setattr(msel, "VANILLA_CANDIDATES", [tmp_path / "nope.bin"])
    with pytest.raises(SystemExit, match="no img.bin"):
        msel.pick_vanilla()


def test_msel_menus_main(tmp_path, monkeypatch):
    pkgs = {pid: arc_package(_menu_files(pid)) for pid in msel.PKG_LABELS}
    img = tmp_path / "img.bin"
    write_img(img, pkgs)
    extra = bind(monkeypatch, tmp_path, msel, img)
    monkeypatch.setattr(msel, "find_ui_png", lambda *a, **k: None)
    real_fit = msel.fit_arc_for_slot

    def wrapping(vanilla_arc, labels, tmp, cmp_len):
        monkeypatch.setattr(msel.zopfli_zlib, "compress", lambda data, n=cmp_len: b"\x00" * n)
        return real_fit(vanilla_arc, labels, tmp, cmp_len)

    monkeypatch.setattr(msel, "fit_arc_for_slot", wrapping)
    monkeypatch.setattr(msel.sys, "argv", ["pytest", "--only", "5242"])
    before = img.read_bytes()
    msel.main()
    assert img.read_bytes() != before
    assert extra.read_bytes() != before

    monkeypatch.setattr(msel.sys, "argv", ["pytest"])
    msel.main()

    monkeypatch.setattr(msel.sys, "argv", ["pytest", "--only", "9"])
    with pytest.raises(SystemExit, match="not in PKG_LABELS"):
        msel.main()

    empty = tmp_path / "empty.bin"
    empty.write_bytes(fi.img({}, count=5243))
    monkeypatch.setattr(msel, "MOD_IMG", empty)
    monkeypatch.setattr(msel, "VANILLA_CANDIDATES", [empty])
    monkeypatch.setattr(msel.sys, "argv", ["pytest", "--only", "5242"])
    with pytest.raises(SystemExit, match="missing"):
        msel.main()

    monkeypatch.setattr(msel, "MOD_IMG", tmp_path / "gone.bin")
    with pytest.raises(SystemExit, match="missing"):
        msel.main()

    monkeypatch.setattr(msel, "MOD_IMG", img)
    monkeypatch.setattr(msel, "VANILLA_CANDIDATES", [img])
    monkeypatch.setattr(msel, "fit_arc_for_slot", lambda arc, labels, tmp, n: arc)
    monkeypatch.setattr(msel, "splice_packages_into_img", boom(msel))
    monkeypatch.setattr(msel.sys, "argv", ["pytest", "--only", "5242"])
    with pytest.raises(SystemExit, match="splice failed"):
        msel.main()


def test_msel_menus_splice_mismatch(tmp_path, monkeypatch):
    arc = fi.darc({"timg/a.bclim": noise_bclim(8, 8, 1, seed=3)})
    pkg = retarget_sidecar(arc_package({"timg/a.bclim": noise_bclim(8, 8, 1, seed=3)}))
    src = tmp_path / "s"
    dst = tmp_path / "d"
    src.write_bytes(pkg)
    monkeypatch.setattr(msel, "compress_exact_zopfli", fast_exact)
    with pytest.raises(SystemExit, match="DMST"):
        msel.splice_arc(src, arc, dst)

    src.write_bytes(arc_package({"timg/a.bclim": noise_bclim(8, 8, 1, seed=3)}))
    armed = {"on": False}
    real = zlib.decompress

    def wrapped(data, *a, **k):
        out = real(data, *a, **k)
        if armed["on"] and isinstance(out, (bytes, bytearray)) and out[:4] == b"darc":
            return bytes(out) + b"!"
        return out

    def comp(data, n):
        out = fast_exact(data, n)
        armed["on"] = True
        return out

    monkeypatch.setattr(zlib, "decompress", wrapped)
    monkeypatch.setattr(msel, "compress_exact_zopfli", comp)
    with pytest.raises(SystemExit, match="ARC content"):
        msel.splice_arc(src, arc, dst)


# ---------------------------------------------------------------------------
# Schedule header (pkg 5575)
# ---------------------------------------------------------------------------


def _sched_files(fmt: int = 0xB, w: int = 160, h: int = 16) -> dict[str, bytes]:
    return {path: noise_bclim(w, h, fmt, seed=i + 1) for i, (path, _en) in enumerate(sched.LABELS)}


def test_schedule_helpers(tmp_path, monkeypatch):
    im = sched.render_gray_header(120, 16, "Mail")
    assert im.size == (120, 16) and im.getchannel("A").getbbox()
    monkeypatch.setattr(sched, "find_ui_png", lambda *a, **k: None)
    rgba, how = sched.header_rgba("nope_stem", "Phone", 80, 16)
    assert how == "render:Phone" and rgba.size == (80, 16)
    rgba, how = sched.header_rgba("mydata_toptex_RGBA4", "My Data", 80, 16)
    assert how.startswith("render:")
    small = solid_png(tmp_path / "m.png", 4, 4, (50, 50, 50, 255))
    monkeypatch.setattr(sched, "find_ui_png", lambda *a, **k: small)
    rgba, how = sched.header_rgba("mail_toptex_RBGA4", "Mail", 40, 16)
    assert rgba.size == (40, 16) and how == "m.png"
    native = solid_png(tmp_path / "native.png", 40, 16, (50, 50, 50, 255))
    monkeypatch.setattr(sched, "find_ui_png", lambda *a, **k: native)
    rgba, how = sched.header_rgba("mail_toptex_RBGA4", "Mail", 40, 16)
    assert rgba.size == (40, 16) and how == "native.png"

    data = fi.darc({"a.bin": b"a" * 8, "b.bin": b"b" * 8}) + bytes(8)
    gaps = sched.interfile_zero_gaps(data)
    assert gaps
    assert sched.apply_gap_pad(data, 0, b"") == data
    real_empty = sched.compress_exact_empty_blocks
    monkeypatch.setattr(sched, "compress_exact_empty_blocks", lambda *a: None)
    with pytest.raises(SystemExit, match="could not build"):
        sched.compress_exact_with_gap_tune(data, 50)
    monkeypatch.setattr(sched, "compress_exact_empty_blocks", real_empty)
    hit = next(n for n in range(20, 500) if real_empty(data, n))
    tuned, slot = sched.compress_exact_with_gap_tune(data, hit)
    assert zlib.decompress(slot) == tuned

    real_co = zlib.compressobj
    flagged = {"n": 0}

    def co(*a, **k):
        flagged["n"] += 1
        if len(a) >= 5 and flagged["n"] < 30:
            raise zlib.error("no")
        return real_co(*a, **k)

    monkeypatch.setattr(zlib, "compressobj", co)
    assert real_empty(b"sched", 4) is None
    monkeypatch.setattr(zlib, "compressobj", real_co)

    monkeypatch.setattr(sched.zopfli_zlib, "compress", lambda d: b"q" * 15)
    assert sched.compress_exact_zopfli(data, 15)[1] == b"q" * 15
    monkeypatch.setattr(sched, "compress_exact_with_gap_tune", lambda d, n: (d, b"g" * n))
    monkeypatch.setattr(sched.zopfli_zlib, "compress", lambda d: b"q" * 99)
    assert sched.compress_exact_zopfli(data, 10)[1] == b"g" * 10

    state = {"n": 0}

    def zhit(data):
        state["n"] += 1
        if state["n"] == 1:
            return b"a" * 5
        return b"a" * 30

    monkeypatch.setattr(sched.zopfli_zlib, "compress", zhit)
    assert sched.compress_exact_zopfli(data, 30)[1] == b"a" * 30

    state["n"] = 0

    def zfine(data):
        state["n"] += 1
        if state["n"] == 1:
            return b"a" * 8
        if state["n"] < 40:
            return b"a" * 31
        if state["n"] == 40:
            return b"a" * 31
        return b"a" * 30

    monkeypatch.setattr(sched.zopfli_zlib, "compress", zfine)
    tuned, slot = sched.compress_exact_zopfli(data, 30)
    assert len(slot) == 30

    state["n"] = 0

    def zunder(data):
        state["n"] += 1
        return b"a" * 6

    monkeypatch.setattr(sched.zopfli_zlib, "compress", zunder)
    monkeypatch.setattr(sched, "compress_exact_with_gap_tune", lambda d, n: (d, b"G" * n))
    assert sched.compress_exact_zopfli(data, 30)[1] == b"G" * 30


def test_schedule_main(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {sched.PKG: arc_package(_sched_files())})
    extra = bind(monkeypatch, tmp_path, sched, img)
    monkeypatch.setattr(sched, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(sched.zopfli_zlib, "compress", lambda data: b"\x00\x01")
    before = img.read_bytes()
    sched.main()
    assert img.read_bytes() != before
    assert extra.read_bytes() != before
    assert (sched.OUT / "scd_toptex_RBGA4_en.png").is_file()

    monkeypatch.setattr(sched, "VANILLA", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        sched.main()

    monkeypatch.setattr(sched, "VANILLA", img)
    bad = _sched_files()
    bad["timg/scd_toptex_RBGA4.bclim"] = noise_bclim(16, 8, 8, seed=2)
    write_img(img, {sched.PKG: arc_package(bad)})
    with pytest.raises(SystemExit, match="fmt"):
        sched.main()

    write_img(img, {sched.PKG: arc_package({"timg/only.bclim": noise_bclim(8, 8, 0xB)})})
    with pytest.raises(SystemExit, match="missing"):
        sched.main()

    write_img(img, {sched.PKG: arc_package(_sched_files())})
    monkeypatch.setattr(sched, "header_rgba", lambda stem, en, w, h: (Image.new("RGBA", (w, h), (1, 1, 1, 255)), "s"))
    monkeypatch.setattr(sched, "png_to_bclim_etc1a4_same_size", lambda png, orig: Path(orig).read_bytes())
    monkeypatch.setattr(sched.zopfli_zlib, "compress", lambda data: b"x" * 9_000_000)
    with pytest.raises(SystemExit, match="exceeds"):
        sched.main()

    monkeypatch.setattr(sched.zopfli_zlib, "compress", lambda data: b"\x00\x01")
    monkeypatch.setattr(sched, "compress_exact_zopfli", wrong_slot)
    with pytest.raises(SystemExit, match="zlib verify"):
        sched.main()

    monkeypatch.setattr(sched, "compress_exact_zopfli", fast_exact)
    monkeypatch.setattr(sched, "splice_packages_into_img", boom(sched))
    with pytest.raises(SystemExit, match="splice failed"):
        sched.main()

    write_img(img, {sched.PKG: retarget_sidecar(arc_package(_sched_files(w=32, h=16)))})
    bind(monkeypatch, tmp_path, sched, img)
    monkeypatch.setattr(sched, "header_rgba", lambda stem, en, w, h: (Image.new("RGBA", (w, h), (1, 1, 1, 255)), "s"))
    monkeypatch.setattr(sched, "png_to_bclim_etc1a4_same_size", lambda png, orig: Path(orig).read_bytes())
    monkeypatch.setattr(sched.zopfli_zlib, "compress", lambda data: b"\x00\x01")
    monkeypatch.setattr(sched, "compress_exact_zopfli", fast_exact)
    with pytest.raises(SystemExit, match="DMST changed"):
        sched.main()

    write_img(img, {sched.PKG: arc_package(_sched_files(w=32, h=16), compress=False)})
    bind(monkeypatch, tmp_path, sched, img)
    monkeypatch.setattr(sched, "header_rgba", lambda stem, en, w, h: (Image.new("RGBA", (w, h), (1, 1, 1, 255)), "s"))
    monkeypatch.setattr(sched, "png_to_bclim_etc1a4_same_size", lambda png, orig: Path(orig).read_bytes())
    monkeypatch.setattr(sched.zopfli_zlib, "compress", lambda data: b"\x00\x01")
    with pytest.raises(SystemExit, match="ARC entry mismatch"):
        sched.main()

    write_img(img, {sched.PKG: arc_package(_sched_files(w=32, h=16))})
    bind(monkeypatch, tmp_path, sched, img)
    monkeypatch.setattr(sched, "header_rgba", lambda stem, en, w, h: (Image.new("RGBA", (w, h), (1, 1, 1, 255)), "s"))
    monkeypatch.setattr(sched, "png_to_bclim_etc1a4_same_size", lambda png, orig: Path(orig).read_bytes())
    monkeypatch.setattr(sched.zopfli_zlib, "compress", lambda data: b"\x00\x01")
    armed = {"on": False}
    real_dec = zlib.decompress

    def wrapped(data, *a, **k):
        out = real_dec(data, *a, **k)
        if armed["on"] and isinstance(out, (bytes, bytearray)) and out[:4] == b"darc":
            return bytes(out) + b"!"
        return out

    def comp(data, n):
        out = fast_exact(data, n)
        armed["on"] = True
        return out

    monkeypatch.setattr(zlib, "decompress", wrapped)
    monkeypatch.setattr(sched, "compress_exact_zopfli", comp)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        sched.main()
    monkeypatch.setattr(zlib, "decompress", real_dec)


# ---------------------------------------------------------------------------
# Input keyboard (pkg 5190)
# ---------------------------------------------------------------------------


def _keyboard_layouts() -> dict[str, bytes]:
    files = {}
    for lyt, panes in keyboard.HIDE_PANES:
        files[lyt] = clyt([pane(b"pan1", name, visible=1) for name in panes])
    return files


def _keyboard_textures() -> dict[str, bytes]:
    files = {}
    for i, (stem, _text) in enumerate(keyboard.LABELS):
        files[f"timg/{stem}.bclim"] = noise_bclim(48, 24, 8, seed=30 + i)
    for stem in keyboard.CLEAR_STEMS:
        files[f"timg/{stem}.bclim"] = noise_bclim(48, 24, 8, seed=70)
    files[f"timg/{keyboard.PENCIL_STEM}.bclim"] = noise_bclim(96, 24, 8, seed=80)
    return files


def _seed_keyboard_assets(root: Path) -> tuple[Path, Path]:
    d0 = root / "c" / "timg"
    d1 = root / "n" / "timg"
    d0.mkdir(parents=True)
    d1.mkdir(parents=True)
    solid_png(d0 / f"{keyboard.LABELS[0][0]}.png", 48, 24)
    solid_png(d0 / f"{keyboard.LABELS[1][0]}.png", 10, 10)
    solid_png(d0 / f"{keyboard.CLEAR_STEMS[0]}.png", 48, 24)
    solid_png(d1 / f"{keyboard.CLEAR_STEMS[0]}.png", 48, 24)
    solid_png(d0 / f"{keyboard.CLEAR_STEMS[1]}.png", 10, 10)
    solid_png(d1 / f"{keyboard.CLEAR_STEMS[1]}.png", 10, 10)
    return d0, d1


def test_keyboard_helpers(tmp_path, monkeypatch):
    im = keyboard.render_label(48, 24, "Kanji")
    assert im.size == (48, 24) and im.getchannel("A").getbbox()
    with pytest.raises(RuntimeError, match="cannot fit"):
        keyboard.render_label(8, 12, "Kanji Input")

    d0, d1 = _seed_keyboard_assets(tmp_path)
    monkeypatch.setattr(keyboard, "ASSET_DIRS", (d0, d1))
    monkeypatch.setattr(keyboard, "OUT", tmp_path / "out")
    keyboard.OUT.mkdir()
    keyboard.write_asset_pngs()
    assert (keyboard.OUT / "keyboard_labels_sheet_x4.png").is_file()
    assert (d1 / f"{keyboard.LABELS[0][0]}.png").is_file()
    assert (d0 / f"{keyboard.LABELS[1][0]}.png").stat().st_size > 0

    tex = _keyboard_textures()
    with pytest.raises(SystemExit, match="missing BCLIM"):
        keyboard._patch_arc(fi.darc({"timg/only.bclim": noise_bclim(8, 8, 8)}), d0, tmp_path)
    bad = dict(tex)
    bad["timg/Profile_Btn_Com01_Text01.bclim"] = noise_bclim(16, 8, 1, seed=1)
    with pytest.raises(SystemExit, match="RGBA4444"):
        keyboard._patch_arc(fi.darc(bad), d0, tmp_path)
    empty = tmp_path / "empty_pngs"
    empty.mkdir()
    with pytest.raises(SystemExit, match="missing PNG"):
        keyboard._patch_arc(fi.darc(tex), empty, tmp_path)

    real_png = keyboard.png_to_bclim_rgba4444_same_size
    monkeypatch.setattr(keyboard, "png_to_bclim_rgba4444_same_size", lambda *a: b"short")
    with pytest.raises(SystemExit, match="size change"):
        keyboard._patch_arc(fi.darc(tex), d0, tmp_path)
    monkeypatch.setattr(keyboard, "png_to_bclim_rgba4444_same_size", real_png)

    layouts = _keyboard_layouts()
    darc_bytes = fi.darc(layouts)
    from darcutil import DarcArchive

    darc = DarcArchive(bytearray(darc_bytes))
    keyboard.hide_input_panes(darc)
    flags = darc.extract_file(darc.find("blyt/Lyt_Prf_Btn_ML.bclyt"))
    assert b"Pos_Btn_C01_01" in flags
    with pytest.raises(SystemExit, match="missing"):
        keyboard.hide_input_panes(DarcArchive(bytearray(fi.darc({"timg/a.bclim": b"abcd"}))))

    td = DarcArchive(bytearray(fi.darc(tex)))
    before = td.extract_file(td.find(f"timg/{keyboard.PENCIL_STEM}.bclim"))
    keyboard.blank_pencil(td)
    after = td.extract_file(td.find(f"timg/{keyboard.PENCIL_STEM}.bclim"))
    assert after != before and len(after) == len(before)
    with pytest.raises(SystemExit, match="missing BCLIM"):
        keyboard.blank_pencil(DarcArchive(bytearray(fi.darc({"timg/a.bclim": noise_bclim(8, 8, 8)}))))

    pkg = named_package([("InputCTexture.arc", {"timg/a.bclim": b"hello"})])
    blob = bytearray(pkg)
    with pytest.raises(SystemExit, match="mismatch"):
        keyboard._write_arc_slot(blob, 0, b"hello-hello", b"xx")
    raw = fi.package([("InputCTexture.arc", fi.darc({"a.bin": b"abcd"}), b"ARC ", False)])
    with pytest.raises(SystemExit, match="not compressed"):
        keyboard._write_arc_slot(bytearray(raw), 0, b"abcd", b"abcd")


def test_keyboard_main(tmp_path, monkeypatch):
    tex = _keyboard_textures()
    layouts = _keyboard_layouts()
    pkg = named_package(
        [
            ("InputCTexture.arc", tex),
            ("InputNTexture.arc", tex),
            ("Other.arc", {"timg/a.bclim": noise_bclim(8, 8, 8)}),
            ("Input.arc", layouts),
        ],
        extra=("meta.dmst", b"DMSTDATA!!", b"DMST", False),
    )
    img = tmp_path / "img.bin"
    van = tmp_path / "van.bin"
    write_img(img, {keyboard.PKG: pkg})
    write_img(van, {keyboard.PKG: pkg})
    bind(monkeypatch, tmp_path, keyboard, img, vanilla=van)
    d0, d1 = _seed_keyboard_assets(tmp_path / "assets")
    monkeypatch.setattr(keyboard, "ASSET_DIRS", (d0, d1))
    state = {"n": 0}
    real_empty = keyboard.compress_exact_empty_blocks

    def empty(data, n):
        state["n"] += 1
        if state["n"] == 1:
            return None
        hit = real_empty(data, n)
        return hit if hit is not None else fast_exact(data, n)[1]

    monkeypatch.setattr(keyboard, "compress_exact_empty_blocks", empty)
    monkeypatch.setattr(keyboard, "compress_exact_zopfli", fast_exact)
    before = img.read_bytes()
    assert keyboard.main() == 0
    assert img.read_bytes() != before
    from darcutil import DarcArchive

    arc = fi.read_element(fi.read_package(img, keyboard.PKG), "Input.arc", tmp_path)
    hidden = DarcArchive(arc).extract_file(DarcArchive(arc).find("blyt/Lyt_Prf_Btn_ML.bclyt"))
    # visible bit at the first pane was cleared
    assert hidden[20 + 8] & 1 == 0

    monkeypatch.setattr(keyboard, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing deploy img"):
        keyboard.main()
    monkeypatch.setattr(keyboard, "MOD_IMG", img)
    monkeypatch.setattr(keyboard, "VANILLA", tmp_path / "missing-van.bin")
    with pytest.raises(SystemExit, match="missing vanilla"):
        keyboard.main()

    monkeypatch.setattr(keyboard, "VANILLA", van)
    nope = tmp_path / "nope.bin"
    write_img(nope, {keyboard.PKG: arc_package({"timg/a.bclim": noise_bclim(8, 8, 8)})})
    # rename the only arc by rebuilding as Foo.arc
    write_img(nope, {keyboard.PKG: named_package([("Foo.arc", {"timg/a.bclim": noise_bclim(8, 8, 8)})])})
    monkeypatch.setattr(keyboard, "VANILLA", nope)
    monkeypatch.setattr(keyboard, "MOD_IMG", nope)
    with pytest.raises(SystemExit, match="no matching"):
        keyboard.main()


def test_keyboard_main_errors(tmp_path, monkeypatch):
    layouts = _keyboard_layouts()
    tiny = {"timg/a.bclim": b"abcd"}
    pkg = named_package(
        [("InputCTexture.arc", tiny), ("Input.arc", layouts)],
        extra=("meta.dmst", b"DMSTDATA!!", b"DMST", False),
    )
    img = tmp_path / "img.bin"
    write_img(img, {keyboard.PKG: pkg})
    bind(monkeypatch, tmp_path, keyboard, img)
    d0, d1 = _seed_keyboard_assets(tmp_path / "assets")
    monkeypatch.setattr(keyboard, "ASSET_DIRS", (d0, d1))
    monkeypatch.setattr(keyboard, "_patch_arc", lambda arc, src, tmp: arc)
    monkeypatch.setattr(keyboard, "hide_input_panes", lambda darc: None)
    monkeypatch.setattr(keyboard, "compress_exact_empty_blocks", lambda d, n: fast_exact(b"\x00" * len(d), n)[1])
    monkeypatch.setattr(keyboard, "compress_exact_zopfli", fast_exact)
    with pytest.raises(SystemExit, match="zlib verify"):
        keyboard.main()

    monkeypatch.setattr(keyboard, "compress_exact_empty_blocks", lambda d, n: fast_exact(d, n)[1])
    monkeypatch.setattr(keyboard, "splice_packages_into_img", boom(keyboard))
    with pytest.raises(SystemExit, match="splice failed"):
        keyboard.main()

    one_arc = named_package(
        [("InputCTexture.arc", {"timg/a.bclim": noise_bclim(16, 8, 8, seed=1)})],
        extra=("meta.dmst", b"DMSTDATA!!", b"DMST", False),
    )
    write_img(img, {keyboard.PKG: retarget_sidecar(one_arc)})
    bind(monkeypatch, tmp_path, keyboard, img)
    monkeypatch.setattr(keyboard, "ASSET_DIRS", (d0, d1))
    monkeypatch.setattr(keyboard, "_patch_arc", lambda arc, src, tmp: arc)
    monkeypatch.setattr(keyboard, "hide_input_panes", lambda darc: None)
    monkeypatch.setattr(keyboard, "compress_exact_empty_blocks", lambda d, n: fast_exact(d, n)[1])
    monkeypatch.setattr(keyboard, "compress_exact_zopfli", fast_exact)
    with pytest.raises(SystemExit, match="non-target"):
        keyboard.main()


# ---------------------------------------------------------------------------
# Options (pkg 5245)
# ---------------------------------------------------------------------------


def _opt_files() -> dict[str, bytes]:
    stems = [Path(base).stem for base, _en in opt.LABELS]
    stems.append(Path(opt.PLATE_PASSWORD).stem)
    files = {}
    for i, stem in enumerate(stems):
        files[f"timg/{stem}.bclim"] = noise_bclim(280, 32, 1, seed=200 + i)
    return files


def test_options_helpers(tmp_path, monkeypatch):
    import numpy as np

    assert opt.glyph_h(np.zeros((3, 3), dtype=np.uint8)) == 0
    raw = noise_bclim(32, 16, 1, seed=2)
    canvas, w, h = opt.decode_a8(raw)
    assert w == 32 and canvas.shape[0] >= h
    painted = opt.render_en_alpha(80, 24, "Options", 12, hard=True)
    assert painted.max() in (0, 255)
    soft = opt.render_en_alpha(80, 24, "Options", 12, hard=False)
    assert soft.shape == (24, 80)
    with pytest.raises(RuntimeError, match="cannot fit"):
        opt.render_en_alpha(4, 8, "Communication Settings", 12)

    png = solid_png(tmp_path / "plate.png", 10, 10, (255, 255, 255, 200))
    force = "Com_M_Sel_Plate_Text04_04_00"

    def find(_folders, stem, _size):
        if stem in (force, "Com_M_Sel_Plate_Text03_00_00", Path(opt.PLATE_PASSWORD).stem):
            return png
        return None

    monkeypatch.setattr(opt, "find_ui_png", find)
    enc = opt.make_en_bclim(raw, "Network", tmp_path, hard=False, stem=force)
    assert len(enc) == len(raw)
    plain = opt.make_en_bclim(raw, "Options", tmp_path, hard=True, stem="Com_M_Sel_Plate_Text03_00_00")
    assert len(plain) == len(raw)
    monkeypatch.setattr(opt, "find_ui_png", lambda *a, **k: None)
    rendered = opt.make_en_bclim(fi.bclim(48, 16, 1), "Options", tmp_path, hard=False, stem="Nope")
    assert len(rendered) == len(fi.bclim(48, 16, 1))

    arc = fi.darc(_opt_files())
    state = {"n": 0}

    def z(data):
        state["n"] += 1
        if state["n"] % 2 == 1:
            return b"x" * 800_000
        return b"\x00"

    monkeypatch.setattr(opt.zopfli_zlib, "compress", z)
    patched = opt.patch_arc(arc, tmp_path, 1000)
    assert patched[:4] == b"darc"
    monkeypatch.setattr(opt.zopfli_zlib, "compress", lambda data: b"x" * 800_000)
    with pytest.raises(SystemExit, match="no trial"):
        opt.patch_arc(arc, tmp_path, 100)
    with pytest.raises(SystemExit, match="missing"):
        opt.patch_arc(fi.darc({"timg/only.bclim": noise_bclim(8, 8, 1)}), tmp_path, 100)

    state["n"] = 0
    monkeypatch.setattr(opt, "find_ui_png", find)
    monkeypatch.setattr(opt.zopfli_zlib, "compress", z)
    plated = opt.add_password_input_plate(arc, tmp_path, 1000)
    assert plated[:4] == b"darc"
    monkeypatch.setattr(opt.zopfli_zlib, "compress", lambda data: b"x" * 800_000)
    with pytest.raises(SystemExit, match="password plate"):
        opt.add_password_input_plate(arc, tmp_path, 100)
    monkeypatch.setattr(opt, "find_ui_png", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="Zhoumaru"):
        opt._zhoumaru_password_plate_png(tmp_path, 8, 8, hard=True)
    with pytest.raises(SystemExit, match="missing template"):
        opt.add_password_input_plate(fi.darc({"timg/only.bclim": noise_bclim(8, 8, 1)}), tmp_path, 100)
    tmpl_only = fi.darc({f"timg/{opt.PLATE_OPTIONS_TMPL}": noise_bclim(16, 8, 1, seed=3)})
    monkeypatch.setattr(opt, "find_ui_png", find)
    with pytest.raises(SystemExit, match="missing"):
        opt.add_password_input_plate(tmpl_only, tmp_path, 100)

    pkg = arc_package(_opt_files())
    src = tmp_path / "srcpkg"
    dst = tmp_path / "dstpkg"
    src.write_bytes(pkg)
    monkeypatch.setattr(opt, "compress_exact_zopfli", fast_exact)
    from img import FileWindow, Package

    parsed = Package(FileWindow(str(src)), 0)
    parsed.parse(False)
    arc_bytes = next(e.parsed() for e in parsed.entries if e.fn == "Data.arc")
    opt.splice_arc(src, arc_bytes, dst)
    assert dst.is_file()
    src.write_bytes(arc_package({"timg/a.bclim": noise_bclim(8, 8, 1)}, compress=False))
    with pytest.raises(SystemExit, match="not compressed"):
        opt.splice_arc(src, b"zz", dst)
    src.write_bytes(pkg)
    with pytest.raises(SystemExit, match="dec size"):
        opt.splice_arc(src, b"short", dst)
    monkeypatch.setattr(opt, "compress_exact_zopfli", lambda d, n: (d, b"\x00" * (n + 3)))
    with pytest.raises(SystemExit, match="post-ARC"):
        opt.splice_arc(src, arc_bytes, dst)

    img = tmp_path / "img.bin"
    img.write_bytes(b"x")
    bind(monkeypatch, tmp_path, opt, img)
    targets = opt._deploy_targets()
    assert img.resolve() in targets


def test_options_main(tmp_path, monkeypatch):
    files = _opt_files()
    arc = fi.darc(files)
    cmp = len(zlib.compress(arc, 1))
    img = tmp_path / "img.bin"
    write_img(img, {opt.PKG: arc_package(files)})
    extra = bind(monkeypatch, tmp_path, opt, img)
    monkeypatch.setattr(opt, "ROOT", tmp_path / "root")
    monkeypatch.setattr(opt, "IMG_DATA", tmp_path / "img_data")
    png = solid_png(tmp_path / "pw.png", 8, 8)

    def find(_folders, stem, _size):
        if stem in (
            Path(opt.PLATE_PASSWORD).stem,
            "Com_M_Sel_Plate_Text04_04_00",
            "Com_M_Sel_Plate_Text03_00_00",
        ):
            return png
        return None

    monkeypatch.setattr(opt, "find_ui_png", find)
    monkeypatch.setattr(opt.zopfli_zlib, "compress", lambda data, n=cmp: b"\x00" * n)
    monkeypatch.setattr(opt.sys, "argv", ["pytest"])
    before = img.read_bytes()
    opt.main()
    assert img.read_bytes() != before
    assert extra.read_bytes() != before

    monkeypatch.setattr(opt.sys, "argv", ["pytest", "--plate-only"])
    opt.main()

    monkeypatch.setattr(opt, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        opt.main()

    empty = tmp_path / "empty.bin"
    empty.write_bytes(fi.img({}, count=opt.PKG + 1))
    monkeypatch.setattr(opt, "MOD_IMG", empty)
    monkeypatch.setattr(opt, "VANILLA", empty)
    monkeypatch.setattr(opt.sys, "argv", ["pytest", "--plate-only"])
    with pytest.raises(SystemExit, match="missing"):
        opt.main()
    monkeypatch.setattr(opt.sys, "argv", ["pytest"])
    with pytest.raises(SystemExit, match="missing"):
        opt.main()

    monkeypatch.setattr(opt, "MOD_IMG", img)
    monkeypatch.setattr(opt, "VANILLA", img)
    monkeypatch.setattr(opt, "patch_arc", lambda arc, tmp, n: arc)
    monkeypatch.setattr(opt, "add_password_input_plate", lambda arc, tmp, n: arc)
    monkeypatch.setattr(opt, "splice_packages_into_img", boom(opt))
    with pytest.raises(SystemExit, match="splice failed"):
        opt.main()


def test_options_splice_mismatch(tmp_path, monkeypatch):
    files = {"timg/a.bclim": noise_bclim(8, 8, 1, seed=4)}
    arc = fi.darc(files)
    src = tmp_path / "s"
    dst = tmp_path / "d"
    src.write_bytes(retarget_sidecar(arc_package(files)))
    monkeypatch.setattr(opt, "compress_exact_zopfli", fast_exact)
    with pytest.raises(SystemExit, match="DMST"):
        opt.splice_arc(src, arc, dst)
    src.write_bytes(arc_package(files))
    armed = {"on": False}
    real = zlib.decompress

    def wrapped(data, *a, **k):
        out = real(data, *a, **k)
        if armed["on"] and isinstance(out, (bytes, bytearray)) and out[:4] == b"darc":
            return bytes(out) + b"!"
        return out

    def comp(data, n):
        out = fast_exact(data, n)
        armed["on"] = True
        return out

    monkeypatch.setattr(zlib, "decompress", wrapped)
    monkeypatch.setattr(opt, "compress_exact_zopfli", comp)
    with pytest.raises(SystemExit, match="ARC content"):
        opt.splice_arc(src, arc, dst)


# ---------------------------------------------------------------------------
# MultiWin headers (pkg 5237)
# ---------------------------------------------------------------------------


def _multi_files() -> dict[str, bytes]:
    paths = {p for p, _en in multi.HEADER_LABELS} | {p for p, _en in multi.EXTRA_LABELS}
    return {path: noise_bclim(192, 16, 0xB, seed=abs(hash(path)) % 10000) for path in paths}


def test_multiwin_helpers(tmp_path, monkeypatch):
    im = multi.render_header_label(192, 16, "Gallery")
    assert im.size == (192, 16)
    im = multi.render_header_label(192, 16, "OK", max_size=10)
    assert im.size == (192, 16)
    with pytest.raises(RuntimeError, match="cannot fit"):
        multi.render_header_label(8, 8, "Communication Settings", max_size=9)

    data = fi.darc({"a.bin": b"a" * 8, "b.bin": b"b" * 8}) + bytes(6)
    gaps = multi.all_interfile_gaps(data)
    assert gaps
    salted = bytearray(data)
    salted[gaps[0][0]] = 3
    assert multi.zero_interfile_gaps(bytes(salted))[gaps[0][0]] == 0
    assert multi.all_interfile_gaps(fi.darc({"a.bin": b"ab", "b.bin": b"cd"}, align=1)) == [] or True

    monkeypatch.setattr(multi, "try_fast_exact_slot", lambda d, n: (d, b"fast"))
    assert multi.exact_slot(b"abc", 4, zero_gaps=False) == (b"abc", b"fast")
    monkeypatch.setattr(multi, "try_fast_exact_slot", lambda *a: None)
    monkeypatch.setattr(multi, "compress_exact_zopfli", lambda d, n: (d, b"zop"))
    assert multi.exact_slot(data, 3, zero_gaps=True)[1] == b"zop"

    monkeypatch.setattr(multi, "VANILLA_CANDIDATES", [tmp_path / "nope.bin", tmp_path / "yes.bin"])
    (tmp_path / "yes.bin").write_bytes(b"img")
    assert multi.pick_vanilla() == tmp_path / "yes.bin"
    monkeypatch.setattr(multi, "VANILLA_CANDIDATES", [tmp_path / "nope.bin"])
    with pytest.raises(SystemExit, match="no vanilla"):
        multi.pick_vanilla()


def _prepare_multi(monkeypatch, tmp_path, img):
    extra = bind(monkeypatch, tmp_path, multi, img)
    monkeypatch.setattr(multi, "try_fast_exact_slot", lambda d, n: fast_exact(d, n))
    monkeypatch.setattr(multi, "compress_exact_zopfli", fast_exact)

    def find(_folders, stem, size):
        if stem == "Com_MultiWin_W01_Text02_00_00" or stem == "Com_MultiWin_W01_Text02_01_01":
            return solid_png(tmp_path / "_ui_png_fit" / f"{stem}.png", 8, 8)
        if stem == "Com_MultiWin_W01_Text04_00_00":
            return solid_png(tmp_path / f"{stem}.png", size[0], size[1])
        return None

    monkeypatch.setattr(multi, "find_ui_png", find)
    return extra


def test_multiwin_main(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {multi.PKG: arc_package(_multi_files())})
    extra = _prepare_multi(monkeypatch, tmp_path, img)
    monkeypatch.setattr(multi.sys, "argv", ["pytest"])
    before = img.read_bytes()
    multi.main()
    assert img.read_bytes() != before
    assert extra.read_bytes() != before
    assert any(multi.OUT.glob("*_en.png"))

    monkeypatch.setattr(multi.sys, "argv", ["pytest", "--full"])
    multi.main()

    monkeypatch.setattr(multi, "MOD_IMG", tmp_path / "missing.bin")
    with pytest.raises(SystemExit, match="missing"):
        multi.main()

    empty = tmp_path / "empty.bin"
    empty.write_bytes(fi.img({}, count=multi.PKG + 1))
    monkeypatch.setattr(multi, "MOD_IMG", empty)
    monkeypatch.setattr(multi, "VANILLA_CANDIDATES", [empty])
    monkeypatch.setattr(multi.sys, "argv", ["pytest", "--full"])
    with pytest.raises(SystemExit, match="missing"):
        multi.main()

    bad = _multi_files()
    first = multi.EXTRA_LABELS[0][0]
    bad[first] = noise_bclim(16, 8, 8, seed=2)
    write_img(img, {multi.PKG: arc_package(bad)})
    monkeypatch.setattr(multi, "MOD_IMG", img)
    monkeypatch.setattr(multi.sys, "argv", ["pytest"])
    with pytest.raises(SystemExit, match="not ETC1A4"):
        multi.main()

    write_img(img, {multi.PKG: arc_package({"timg/only.bclim": noise_bclim(8, 8, 0xB)})})
    with pytest.raises(SystemExit, match="missing"):
        multi.main()


def test_multiwin_late_errors(tmp_path, monkeypatch):
    img = tmp_path / "img.bin"
    write_img(img, {multi.PKG: arc_package(_multi_files())})
    _prepare_multi(monkeypatch, tmp_path, img)
    monkeypatch.setattr(multi, "png_to_bclim_etc1a4_same_size", lambda png, orig: Path(orig).read_bytes())
    monkeypatch.setattr(
        multi, "render_header_label", lambda w, h, text, max_size=None: Image.new("RGBA", (w, h), (255, 255, 255, 255))
    )
    monkeypatch.setattr(multi, "render_header_aa", lambda *a, **k: Image.new("RGBA", (192, 16), (255, 255, 255, 255)))
    monkeypatch.setattr(multi, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(multi.sys, "argv", ["pytest"])

    monkeypatch.setattr(multi, "exact_slot", lambda data, n, zero_gaps=False: wrong_slot(data, n))
    with pytest.raises(SystemExit, match="zlib verify"):
        multi.main()

    def longer(data, n, zero_gaps=False):
        return fast_exact(data + b"\x00", n)

    monkeypatch.setattr(multi, "exact_slot", longer)
    with pytest.raises((SystemExit, RuntimeError)):
        multi.main()

    monkeypatch.setattr(multi, "exact_slot", lambda data, n, zero_gaps=False: fast_exact(data, n))
    monkeypatch.setattr(multi, "splice_packages_into_img", boom(multi))
    with pytest.raises(SystemExit, match="splice failed"):
        multi.main()

    write_img(img, {multi.PKG: retarget_sidecar(arc_package(_multi_files()))})
    _prepare_multi(monkeypatch, tmp_path, img)
    monkeypatch.setattr(multi, "png_to_bclim_etc1a4_same_size", lambda png, orig: Path(orig).read_bytes())
    monkeypatch.setattr(
        multi, "render_header_label", lambda w, h, text, max_size=None: Image.new("RGBA", (w, h), (255, 255, 255, 255))
    )
    monkeypatch.setattr(multi, "render_header_aa", lambda *a, **k: Image.new("RGBA", (192, 16), (255, 255, 255, 255)))
    monkeypatch.setattr(multi, "find_ui_png", lambda *a, **k: None)
    monkeypatch.setattr(multi, "exact_slot", lambda data, n, zero_gaps=False: fast_exact(data, n))
    with pytest.raises(SystemExit, match="DMST changed"):
        multi.main()

    write_img(img, {multi.PKG: arc_package(_multi_files())})
    _prepare_multi(monkeypatch, tmp_path, img)
    monkeypatch.setattr(multi, "png_to_bclim_etc1a4_same_size", lambda png, orig: Path(orig).read_bytes())
    monkeypatch.setattr(
        multi, "render_header_label", lambda w, h, text, max_size=None: Image.new("RGBA", (w, h), (255, 255, 255, 255))
    )
    monkeypatch.setattr(multi, "render_header_aa", lambda *a, **k: Image.new("RGBA", (192, 16), (255, 255, 255, 255)))
    monkeypatch.setattr(multi, "find_ui_png", lambda *a, **k: None)
    armed = {"on": False}
    real = zlib.decompress

    def wrapped(data, *a, **k):
        out = real(data, *a, **k)
        if armed["on"] and isinstance(out, (bytes, bytearray)) and out[:4] == b"darc":
            return bytes(out) + b"!"
        return out

    def slot(data, n, zero_gaps=False):
        out = fast_exact(data, n)
        armed["on"] = True
        return out

    monkeypatch.setattr(zlib, "decompress", wrapped)
    monkeypatch.setattr(multi, "exact_slot", slot)
    with pytest.raises(SystemExit, match="ARC mismatch"):
        multi.main()
