"""Coverage for patch_cesa: exact-zlib fallbacks, the pkg 90 companion rebuild,
and the img.bin splices, on a small synthetic pkg 90.

TEX dimensions are shrunk (16×16 CESA, 16×32 companion) so zlib/zopfli run on
a few hundred bytes instead of 393 KB per texture.
"""

from __future__ import annotations

import mmap as real_mmap
import random
import shutil
import struct
import sys
import types
import zlib
from pathlib import Path

import pytest
from PIL import Image

import fake_img as fi
import patch_cesa as cesa

STUB = bytes(cesa.STUB_TEX_DEC_LEN)
CESA_LEN = 16 * 16 * 3
COMP_LEN = 16 * 32 * 3


def _texi() -> bytes:
    return b"T" * 10 + b"\x69" * 8 + bytes(32) + b"Z" * 32


def _noise(n: int, seed: int = 1) -> bytes:
    return random.Random(seed).randbytes(n)


def _pkg90(*, companion: bytes = STUB, konami: bytes = b"k" * 900, cesa_tex: bytes = bytes(CESA_LEN),
           stubs: bool = True) -> bytes:
    el = [
        (cesa.CESA_COMPANION_TEX_NAME, _texi(), b"TEXI", False),
        (cesa.BOTTOM_THANK_TEX_NAME, _texi(), b"TEXI", False),
        (cesa.PROD_LANDSCAPE_STUB_TEX_NAME, _texi(), b"TEXI", False),
        (cesa.CESA_TEX_NAME, cesa_tex, b"TEX ", True),
        (cesa.CESA_COMPANION_TEX_NAME, companion, b"TEX ", True),
        ("KONAMI_CI_240X400.texi", konami, b"TEX ", True),
        ("ProductionLogo_240X320.texi", _noise(600, 2), b"TEX ", True),
        ("Other.arc", b"zz" * 40, b"ARC ", True),
    ]
    if stubs:
        el += [
            (cesa.BOTTOM_THANK_TEX_NAME, STUB, b"TEX ", True),
            (cesa.CESA_ALT_ORIENT_TEX_NAME, STUB, b"TEX ", True),
            (cesa.PROD_LANDSCAPE_STUB_TEX_NAME, STUB, b"TEX ", True),
        ]
    pkg = bytearray(fi.package(el))
    # Point the last stub at the first stub's payload, like the game's shared stub.
    if stubs:
        first = cesa.ENTRY_SIZE * (1 + 8)
        last = cesa.ENTRY_SIZE * (1 + 10)
        pkg[last + 24 : last + 32] = pkg[first + 24 : first + 32]  # cmp_len, cmp_off
    return bytes(pkg)


def _dec_len(pkg: bytes) -> int:
    return struct.unpack_from("<I", pkg, 20)[0]


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(cesa, "TEX_W", 16)
    monkeypatch.setattr(cesa, "TEX_H", 16)
    monkeypatch.setattr(cesa, "COMPANION_TEX_W", 16)
    monkeypatch.setattr(cesa, "COMPANION_TEX_H", 32)


def test_ensure_nlpp_path_inserts_tools(monkeypatch):
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(cesa.NLPP_TOOLS)])
    cesa._ensure_nlpp_path()
    assert sys.path[0] == str(cesa.NLPP_TOOLS)


def test_compress_zlib_exact_fallbacks(monkeypatch):
    data = b"x"
    real_try = cesa._try_zlib_exact_candidate
    # A zlib.compress candidate of the right length that fails the round-trip
    # check falls through to the stored-block builder.
    exact = len(zlib.compress(data, 0))
    calls = []

    def picky(out, d):
        calls.append(out)
        return len(calls) > 1 and real_try(out, d)

    monkeypatch.setattr(cesa, "_try_zlib_exact_candidate", picky)
    with pytest.raises(RuntimeError, match="cannot build"):
        cesa.compress_zlib_exact(data, exact)
    monkeypatch.setattr(cesa, "_try_zlib_exact_candidate", real_try)

    # Payload too long for one stored block: empty sync markers instead.
    co = zlib.compressobj(6, wbits=-15)
    body = co.compress(data) + co.flush(zlib.Z_SYNC_FLUSH)
    length = len(body) + 6 + 0x10009
    out = cesa.compress_zlib_exact(data, length)
    assert len(out) == length and zlib.decompress(out) == data

    # Real zopfli body is a final block: its sync-marker candidate fails, and
    # the loop moves on to the zlib bodies.
    import zopfli.zlib as zz

    zbody = zz.compress(data)[2:-4]
    try:
        cesa.compress_zlib_exact(data, len(zbody) + 6 + 10)
    except RuntimeError:
        pass

    # zopfli returning nothing usable, or failing, is skipped.
    fake = types.ModuleType("zopfli.zlib")
    monkeypatch.setitem(sys.modules, "zopfli.zlib", fake)
    monkeypatch.setitem(sys.modules, "zopfli", types.SimpleNamespace(zlib=fake))
    # remain 10: the stored-payload try adds 5 bytes of output, then two empty
    # sync markers fit exactly.
    sync_len = len(body) + 6 + 10
    fake.compress = lambda d: b"\x78"
    out = cesa.compress_zlib_exact(data, sync_len)
    assert len(out) == sync_len and zlib.decompress(out) == data

    def boom(d):
        raise RuntimeError("no zopfli")

    fake.compress = boom
    assert zlib.decompress(cesa.compress_zlib_exact(data, sync_len)) == data
    assert zlib.decompress(cesa.compress_tex_best(b"abc" * 9)) == b"abc" * 9
    monkeypatch.setattr(cesa, "_try_zlib_exact_candidate", lambda out, d: False)
    with pytest.raises(RuntimeError, match="round-trip"):
        cesa.compress_tex_best(b"abc")


def test_rebuild_pkg90_with_companion(small, monkeypatch, capsys):
    pkg = _pkg90()
    monkeypatch.setattr(cesa, "VANILLA_PKG90_DEC_LEN", _dec_len(pkg))
    cesa_tex, comp_tex = b"\x01\x02\x03" * (CESA_LEN // 3), bytes(COMP_LEN)
    out = cesa.rebuild_pkg90_with_companion(pkg, cesa_tex, comp_tex)
    assert len(out) == len(pkg)
    assert _dec_len(out) == _dec_len(pkg) + COMP_LEN
    assert cesa.read_named_tex_from_pkg(out, cesa.CESA_TEX_NAME) == cesa_tex
    assert cesa.read_named_tex_from_pkg(out, cesa.CESA_COMPANION_TEX_NAME) == comp_tex
    assert "pkg90 TEX zlib" in capsys.readouterr().out

    # Already-grown companion keeps its dec_off and the header dec_len.
    grown = _pkg90(companion=bytes(COMP_LEN))
    again = cesa.rebuild_pkg90_with_companion(grown, cesa_tex, comp_tex)
    assert _dec_len(again) == _dec_len(grown)


def test_rebuild_pkg90_errors(small, monkeypatch):
    pkg = _pkg90()
    ok_c, ok_comp = bytes(CESA_LEN), bytes(COMP_LEN)
    with pytest.raises(RuntimeError, match="CESA TEX size"):
        cesa.rebuild_pkg90_with_companion(pkg, b"x", ok_comp)
    with pytest.raises(RuntimeError, match="companion TEX size"):
        cesa.rebuild_pkg90_with_companion(pkg, ok_c, b"x")
    with pytest.raises(RuntimeError, match="cmp_len"):
        cesa.rebuild_pkg90_with_companion(pkg + b"\0", ok_c, ok_comp)
    no_cesa = fi.package([("KONAMI_CI_240X400.texi", b"k" * 10, b"TEX ", True)])
    with pytest.raises(RuntimeError, match="missing CESA TEX"):
        cesa.rebuild_pkg90_with_companion(no_cesa, ok_c, ok_comp)
    with pytest.raises(RuntimeError, match="overflow"):
        cesa.rebuild_pkg90_with_companion(pkg, _noise(CESA_LEN, 9), _noise(COMP_LEN, 8))
    # dec_len is not vanilla but logo_white is still a stub.
    with pytest.raises(RuntimeError, match="already grown"):
        cesa.rebuild_pkg90_with_companion(pkg, ok_c, ok_comp)
    # The smallest TEX payload is not a 16×16 stub: stubs come out wrong-sized.
    tiny = _pkg90(konami=b"")
    monkeypatch.setattr(cesa, "VANILLA_PKG90_DEC_LEN", _dec_len(tiny))
    with pytest.raises(RuntimeError, match="must stay a 16"):
        cesa.rebuild_pkg90_with_companion(tiny, ok_c, ok_comp)


def test_read_named_tex_errors():
    plain = fi.package([("A.texi", b"abc", b"TEX ", False)])
    with pytest.raises(RuntimeError, match="not compressed"):
        cesa.read_named_tex_from_pkg(plain, "A.texi")
    with pytest.raises(RuntimeError, match="not found"):
        cesa.read_named_tex_from_pkg(plain, "B.texi")
    pkg = bytearray(fi.package([("A.texi", b"abc", b"TEX ", True)]))
    struct.pack_into("<I", pkg, cesa.ENTRY_SIZE + 8, 5)
    with pytest.raises(RuntimeError, match="decompressed 3 != 5"):
        cesa.read_named_tex_from_pkg(bytes(pkg), "A.texi")


# ---------------------------------------------------------------------------
# patch_img_bin_tex
# ---------------------------------------------------------------------------


def _img(tmp_path: Path, name: str, packages: dict[int, bytes], count: int = 100) -> Path:
    path = tmp_path / name
    path.write_bytes(fi.img(packages, count=count))
    return path


# Level-1 zlib is 23 bytes: an exact-length stream of 300 zeros fits that slot.
VANILLA_TEX = bytes(range(10)) + bytes(290)


def _truncated(tmp_path: Path, pkg: bytes) -> Path:
    """img.bin cut off inside pkg 90, so the package read comes back short."""
    path = _img(tmp_path, "short.bin", {90: pkg})
    data = path.read_bytes()
    path.write_bytes(data[: data.rindex(pkg[:64]) + 64])
    return path


def test_patch_img_bin_tex(tmp_path, monkeypatch):
    pkg = fi.package([(cesa.CESA_TEX_NAME, VANILLA_TEX, b"TEX ", True)])
    src = _img(tmp_path, "src.bin", {5: fi.package([("a", b"a" * 50)]), 90: pkg})
    tex = bytes(300)
    dst = cesa.patch_img_bin_tex(src, tex, tmp_path / "out" / "dst.bin")
    assert cesa.read_cesa_tex_from_pkg(fi.read_package(dst, 90)) == tex
    assert (tmp_path / "out" / "cesa_img_work" / "0090_patched.bin").is_file()

    # Same TEX again (an in-place re-run) is fine.
    same = cesa.patch_img_bin_tex(src, VANILLA_TEX, tmp_path / "same.bin", work=tmp_path / "w")
    assert fi.read_package(same, 90) == pkg
    missing = _img(tmp_path, "missing.bin", {5: pkg})
    with pytest.raises(RuntimeError, match="missing package 90"):
        cesa.patch_img_bin_tex(missing, tex, tmp_path / "x.bin", work=tmp_path / "w")
    with pytest.raises(RuntimeError, match="read length mismatch"):
        cesa.patch_img_bin_tex(_truncated(tmp_path, pkg), tex, tmp_path / "x.bin", work=tmp_path / "w")

    # A copy whose other package differs is caught by the verify pass.
    other = _img(tmp_path, "other.bin", {5: fi.package([("a", b"b" * 50)]), 90: pkg})
    monkeypatch.setattr(cesa, "shutil", types.SimpleNamespace(copy2=lambda a, b: shutil.copy2(other, b)))
    with pytest.raises(RuntimeError, match="unexpected diff at package 5"):
        cesa.patch_img_bin_tex(src, tex, tmp_path / "y.bin", work=tmp_path / "w")


def test_patch_img_bin_tex_verify_mismatch(tmp_path, monkeypatch):
    pkg = fi.package([(cesa.CESA_TEX_NAME, VANILLA_TEX, b"TEX ", True)])
    src = _img(tmp_path, "src.bin", {90: pkg})
    monkeypatch.setattr(cesa, "read_cesa_tex_from_pkg", lambda raw: b"other")
    with pytest.raises(RuntimeError, match="TEX mismatch after splice"):
        cesa.patch_img_bin_tex(src, bytes(300), tmp_path / "d.bin", work=tmp_path / "w")


def test_patch_img_bin_tex_rejects_resize(tmp_path, monkeypatch):
    pkg = fi.package([(cesa.CESA_TEX_NAME, VANILLA_TEX, b"TEX ", True)])
    src = _img(tmp_path, "src.bin", {90: pkg})
    monkeypatch.setattr(cesa, "patch_cesa_package_inplace_tex", lambda raw, tex: raw + b"\0")
    with pytest.raises(RuntimeError, match="changed package size"):
        cesa.patch_img_bin_tex(src, bytes(300), tmp_path / "d.bin", work=tmp_path / "w")


# ---------------------------------------------------------------------------
# patch_img_bin_with_companion
# ---------------------------------------------------------------------------


@pytest.fixture
def companion_img(small, monkeypatch, tmp_path):
    pkg = _pkg90()
    monkeypatch.setattr(cesa, "VANILLA_PKG90_DEC_LEN", _dec_len(pkg))
    monkeypatch.setattr(cesa, "encode_cesa_tex", lambda im: bytes(CESA_LEN))
    monkeypatch.setattr(cesa, "encode_cesa_companion_tex", lambda im: b"\x07" * COMP_LEN)
    png = tmp_path / "x.png"
    Image.new("RGB", (4, 4)).save(png)
    src = _img(tmp_path, "src.bin", {5: fi.package([("a", b"a" * 50)]), 90: pkg})
    return src, png


def test_patch_img_bin_with_companion(companion_img, tmp_path, capsys):
    src, png = companion_img
    dst = tmp_path / "out" / "dst.bin"
    dst.parent.mkdir()
    shutil.copy2(src, dst)
    assert cesa.patch_img_bin_with_companion(src, png, png, dst) == dst.resolve()
    assert "img idx pkg90 dec_len" in capsys.readouterr().out
    assert (tmp_path / "out" / "cesa_img_work" / "0090.bin").is_file()
    # Re-run from vanilla: idx already matches, nothing to report.
    cesa.patch_img_bin_with_companion(dst, png, png, dst, work=tmp_path / "w", vanilla_img=src)
    assert "img idx" not in capsys.readouterr().out


def test_patch_img_bin_with_companion_errors(companion_img, tmp_path, monkeypatch):
    src, png = companion_img
    work = tmp_path / "w"

    def dst() -> Path:
        d = tmp_path / "d.bin"
        shutil.copy2(src, d)
        return d

    missing = _img(tmp_path, "missing.bin", {5: fi.package([("a", b"a")])})
    with pytest.raises(RuntimeError, match="missing package 90"):
        cesa.patch_img_bin_with_companion(missing, png, png, dst(), work=work)

    with pytest.raises(RuntimeError, match="read length mismatch"):
        cesa.patch_img_bin_with_companion(_truncated(tmp_path, _pkg90()), png, png, dst(), work=work)

    other = _img(tmp_path, "other.bin", {90: fi.package([("a", b"a" * 9)])})
    with pytest.raises(RuntimeError, match="!= dest slot"):
        cesa.patch_img_bin_with_companion(src, png, png, dst(), work=work, vanilla_img=other)

    with monkeypatch.context() as m:
        m.setattr(cesa, "rebuild_pkg90_with_companion", lambda raw, a, b: raw + b"\0")
        with pytest.raises(RuntimeError, match="rebuild changed package size"):
            cesa.patch_img_bin_with_companion(src, png, png, dst(), work=work)

    with monkeypatch.context() as m:
        m.setattr(cesa, "read_img_idx_dec_len", lambda mm, i: -1)
        with pytest.raises(RuntimeError, match="did not stick"):
            cesa.patch_img_bin_with_companion(src, png, png, dst(), work=work)

    class _StaleRead(real_mmap.mmap):
        """mmap whose read-only view still shows zeros where pkg 90 went."""

        def __new__(cls, *args, **kwargs):
            obj = super().__new__(cls, *args, **kwargs)
            obj.ro = kwargs.get("access") == real_mmap.ACCESS_READ
            return obj

        def __getitem__(self, key):
            got = super().__getitem__(key)
            return bytes(len(got)) if self.ro and isinstance(key, slice) and len(got) > 64 else got

    with monkeypatch.context() as m:
        m.setattr(cesa, "mmap", types.SimpleNamespace(mmap=_StaleRead, ACCESS_READ=real_mmap.ACCESS_READ))
        with pytest.raises(RuntimeError, match="splice did not stick"):
            cesa.patch_img_bin_with_companion(src, png, png, dst(), work=work)

    real_read = cesa.read_named_tex_from_pkg
    for name, msg in ((cesa.CESA_TEX_NAME, "patched CESA TEX"), (cesa.CESA_COMPANION_TEX_NAME, "companion TEX")):
        with monkeypatch.context() as m:
            m.setattr(cesa, "read_named_tex_from_pkg",
                      lambda raw, n, bad=name: b"?" if n == bad else real_read(raw, n))
            with pytest.raises(RuntimeError, match=msg):
                cesa.patch_img_bin_with_companion(src, png, png, dst(), work=work)
