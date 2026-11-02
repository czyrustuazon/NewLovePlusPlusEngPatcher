"""Coverage for the offline mini-game master cutters (tools/cut_minigame_*.py).

The cutters read vanilla l2mgtex textures from img.bin. Here the package
reader is a fake whose "raw" texture bytes are PIL images, and the fake
l2mgtex decodes / encodes them directly. The committed mockups are real.
Masters go to tmp_path, never to assets/.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

import l2mgtex as real_l2
from conftest import ROOT, TOOLS, load_module

FONT = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025" / "Geomanist-Regular.ttf"


def _cutter(name: str):
    return load_module(f"cut_minigame_{name}_en", TOOLS / f"cut_minigame_{name}_en.py")


def _decode(raw):
    return real_l2.decode(raw) if isinstance(raw, bytes) else raw.copy()


FAKE_L2 = SimpleNamespace(
    decode=_decode,
    encode_like=lambda _raw, im: np.array(im.convert("RGBA")).tobytes(),
    parse_header=real_l2.parse_header,
    HEADER_LEN=real_l2.HEADER_LEN,
)


class _Entry:
    def __init__(self, fn: str, raw, slot: int = 10**7) -> None:
        self.fn = fn
        self._raw = raw
        self.fw = SimpleNamespace(len=lambda: slot)

    def parsed(self):
        return self._raw


class _Res:
    def __init__(self, entries: list[_Entry]) -> None:
        self.entries = entries

    def parse(self, _deep) -> None:
        return None


def _install(monkeypatch, tmp_path: Path, mod, pkgs: dict[int, list[_Entry]]) -> Path:
    """Fake vanilla img.bin + l2mgtex; masters under tmp_path."""

    class _Img:
        def __init__(self, path: str) -> None:
            assert path.endswith("img.bin")
            self.entries = {k: _Res(v) for k, v in pkgs.items()}

        def parse(self, _deep) -> None:
            return None

    masters = tmp_path / "masters"
    masters.mkdir(exist_ok=True)
    monkeypatch.setattr(mod, "ImgBin", _Img)
    monkeypatch.setattr(mod, "require_vanilla_img", lambda: tmp_path / "img.bin")
    monkeypatch.setattr(mod, "l2mgtex", FAKE_L2)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "MASTERS", masters)
    return masters


def _rgba(w: int, h: int, color=(0, 0, 0, 0)) -> np.ndarray:
    a = np.zeros((h, w, 4), np.uint8)
    a[:] = color
    return a


def _im(a: np.ndarray) -> Image.Image:
    return Image.fromarray(a.astype(np.uint8), "RGBA")


# ---------------------------------------------------------------------------
# attention
# ---------------------------------------------------------------------------


def test_attention_main_writes_masters(monkeypatch, tmp_path, capsys):
    mod = _cutter("attention")
    rng = np.random.default_rng(1)
    tile = _rgba(64, 64, (0, 0, 0, 255))
    tile[..., :3] = rng.integers(0, 255, (64, 64, 3))
    s006 = _rgba(512, 32)
    s006[10:20, 480:500] = (20, 40, 200, 255)
    s007 = _rgba(256, 64)
    s007[10:20, 230:250] = (200, 40, 20, 255)
    comp = np.tile(tile, (2, 8, 1))[:104]
    comp[10:20, 480:500] = (20, 40, 200, 255)
    comp[30:40, 230:250] = (200, 40, 20, 255)
    end5 = _rgba(256, 32)
    end5[8:24, 100:150] = (0, 0, 0, 255)
    start = [
        _Entry("000.l2mgtex", _im(tile)),
        _Entry("006.l2mgtex", _im(s006)),
        _Entry("007.l2mgtex", _im(s007)),
        _Entry("008.l2mgtex", _im(comp)),
        _Entry("readme.bin", None),
    ]
    masters = _install(monkeypatch, tmp_path, mod, {95: start, 94: [_Entry("005.l2mgtex", _im(end5))]})

    assert mod.main() == 0
    names = sorted(p.name for p in masters.iterdir())
    assert names == [
        "AttentionEnd_005.png",
        "AttentionStart_005.png",
        "AttentionStart_006.png",
        "AttentionStart_007.png",
        "AttentionStart_008.png",
    ]
    assert Image.open(masters / "AttentionStart_008.png").size == (512, 104)
    assert "wrote" in capsys.readouterr().out


def test_attention_matte_min_h_drops_short_pieces():
    mod = _cutter("attention")
    src = np.full((60, 80, 3), mod.MOCKUP_BG, np.float32)
    src[5:50, 5:30] = (10, 10, 120)  # tall piece, kept
    src[40:55, 40:75] = (10, 10, 120)  # 15 rows, < min_h 20, dropped
    out = mod.matte(src, 0, 60, min_h=20)
    assert out.width < 40


# ---------------------------------------------------------------------------
# highscore
# ---------------------------------------------------------------------------


def _badge_tex(inner_w: int) -> np.ndarray:
    tex = _rgba(32, 32)
    x0 = 16 - inner_w // 2
    tex[2:30, x0 : x0 + inner_w] = (200, 60, 60, 255)
    tex[12:14, x0 : x0 + inner_w] = (255, 255, 255, 255)  # a white-only row
    return tex


def test_highscore_main(monkeypatch, tmp_path, capsys):
    mod = _cutter("highscore")
    monkeypatch.setattr(mod, "FONT", FONT)
    pkg = [
        _Entry("004.l2mgtex", _im(_rgba(256, 64)), 10**6),
        _Entry("000.l2mgtex", _im(_badge_tex(30)), 10**6),
        _Entry("001.l2mgtex", _im(_badge_tex(10)), 10**6),
        _Entry("other.bin", None),
    ]
    masters = _install(monkeypatch, tmp_path, mod, {mod.PKG: pkg})
    monkeypatch.setattr(mod, "pad_closed_zlib_stream", lambda stream, slot, expected: b"ok")
    assert mod.main() == 0
    assert {p.name for p in masters.iterdir()} == {
        "PuzzleResult_004.png",
        "PuzzleBadge_easy.png",
        "PuzzleBadge_hard.png",
    }
    assert "colours" in capsys.readouterr().out


def test_highscore_slot_failures(monkeypatch, tmp_path):
    mod = _cutter("highscore")
    monkeypatch.setattr(mod, "FONT", tmp_path / "missing.ttf")
    with pytest.raises(SystemExit, match="missing"):
        mod.main()

    monkeypatch.setattr(mod, "FONT", FONT)
    pkg = [
        _Entry("004.l2mgtex", _im(_rgba(256, 64)), 10**6),
        _Entry("000.l2mgtex", _im(_badge_tex(30)), 10**6),
    ]
    _install(monkeypatch, tmp_path, mod, {mod.PKG: pkg})
    monkeypatch.setattr(mod, "pad_closed_zlib_stream", lambda stream, slot, expected: None)
    with pytest.raises(SystemExit, match="cannot fill"):
        mod.main()

    with pytest.raises(SystemExit, match="does not fit"):
        mod.quantize_to_slot(_rgba(16, 16, (9, 9, 9, 255)), b"", 0)


def test_highscore_badge_stream_over_slot(monkeypatch, tmp_path):
    mod = _cutter("highscore")
    monkeypatch.setattr(mod, "FONT", FONT)
    pkg = [
        _Entry("004.l2mgtex", _im(_rgba(256, 64)), 10**6),
        _Entry("000.l2mgtex", _im(_badge_tex(30)), 1),
    ]
    _install(monkeypatch, tmp_path, mod, {mod.PKG: pkg})
    monkeypatch.setattr(mod, "pad_closed_zlib_stream", lambda stream, slot, expected: b"ok")
    with pytest.raises(SystemExit, match="cannot fill"):
        mod.main()


# ---------------------------------------------------------------------------
# result
# ---------------------------------------------------------------------------


def test_result_main(monkeypatch, tmp_path, capsys):
    mod = _cutter("result")
    pkg = [_Entry(f"{k}.l2mgtex", _im(_rgba(128, 64))) for k in ("043", "044", "125", "126")]
    pkg.append(_Entry("x.bin", None))
    masters = _install(monkeypatch, tmp_path, mod, {mod.PKG: pkg})
    assert mod.main() == 0
    assert len(list(masters.iterdir())) == 4
    assert "alpha levels" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="does not fit"):
        mod.fit(_rgba(8, 8, (1, 2, 3, 200)), b"", 0, None)


# ---------------------------------------------------------------------------
# select course / footer / prompt / names
# ---------------------------------------------------------------------------


def _plate() -> np.ndarray:
    tex = _rgba(256, 64)
    checker = np.array([(200, 200, 230), (180, 180, 210)] * 3, np.uint8)
    for x in range(4, 252):
        tex[2:62, x, :3] = checker[(x - 4) % 6]
        tex[2:62, x, 3] = 255
    tex[25:40, 60:200, :3] = (20, 20, 20)  # JP text
    return tex


def test_select_course_main(monkeypatch, tmp_path, capsys):
    mod = _cutter("select_course")
    pkg = [_Entry(f"{k}.l2mgtex", _im(_plate())) for k in ("070", "071")]
    pkg.append(_Entry("099.l2mgtex", None))
    masters = _install(monkeypatch, tmp_path, mod, {mod.PKG: pkg})
    assert mod.main() == 0
    assert {p.name for p in masters.iterdir()} == {"PuzzleSelect_070.png", "PuzzleSelect_071.png"}
    assert "wrote" in capsys.readouterr().out


def test_select_course_en_text_unscaled_and_border(monkeypatch):
    mod = _cutter("select_course")
    monkeypatch.setattr(mod, "TEXT_SCALE", 1.0)
    monkeypatch.setattr(mod, "PLACE", {"070": (1.0, 0.0, 0.0)})
    monkeypatch.setattr(mod, "EDGE_EXCLUDE", (1, 1))
    monkeypatch.setattr(mod, "TEXT_COLS", {"070": (0, 200)})
    mock = np.full((80, 200, 3), 250, np.float32)
    mock[10:70, 30:36] = 20  # tall thin bar: a plate border, dropped
    mock[30:50, 80:120] = 20  # a letter
    tex = _rgba(200, 80, (200, 200, 200, 255))
    rgb, a = mod.en_text(mock, tex, "070")
    assert a[40, 100] > 0.5
    assert a[40, 33] == 0


def test_select_footer_main(monkeypatch, tmp_path, capsys):
    mod = _cutter("select_footer")
    tex = _rgba(64, 32, (100, 200, 50, 255))
    pkg = [_Entry(f"{k}.l2mgtex", _im(tex)) for k in ("122", "123")] + [_Entry("001.l2mgtex", None)]
    masters = _install(monkeypatch, tmp_path, mod, {mod.PKG: pkg})
    assert mod.main() == 0
    assert len(list(masters.iterdir())) == 2
    assert "wrote" in capsys.readouterr().out


def test_select_prompt_main(monkeypatch, tmp_path, capsys):
    mod = _cutter("select_prompt")
    masters = _install(monkeypatch, tmp_path, mod, {
        mod.PKG: [_Entry("014.l2mgtex", None), _Entry("015.l2mgtex", _im(_rgba(256, 64)))],
    })
    monkeypatch.setattr(mod, "OUT_PNG", masters / "PuzzleSelect_015.png")
    assert mod.main() == 0
    assert (masters / "PuzzleSelect_015.png").is_file()
    assert "alpha levels" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="does not fit"):
        mod.fit_slot(_rgba(8, 8, (1, 1, 1, 255)), b"", 0)


def test_select_names_main(monkeypatch, tmp_path, capsys):
    mod = _cutter("select_names")
    monkeypatch.setattr(mod, "FONT", FONT)
    strip = _rgba(128, 32)
    strip[8:24, 30:90] = (255, 255, 255, 255)
    pkg = [_Entry(f"{n:03d}.l2mgtex", _im(strip)) for n in range(136, 161)]
    pkg.append(_Entry("readme.bin", None))
    masters = _install(monkeypatch, tmp_path, mod, {mod.PKG: pkg})
    assert mod.main() == 0
    assert len(list(masters.iterdir())) == 2 * len(mod.NAMES)
    assert "alpha levels" in capsys.readouterr().out


def test_select_names_failures(monkeypatch, tmp_path):
    mod = _cutter("select_names")
    monkeypatch.setattr(mod, "FONT", tmp_path / "missing.ttf")
    with pytest.raises(SystemExit, match="missing"):
        mod.main()
    monkeypatch.setattr(mod, "FONT", FONT)
    monkeypatch.setattr(mod, "MAX_W", 0)
    with pytest.raises(SystemExit, match="no font size"):
        mod._font_size()
    monkeypatch.setattr(mod, "l2mgtex", FAKE_L2)
    with pytest.raises(SystemExit, match="even with 2"):
        mod.fit_slot(_im(_rgba(8, 8, (1, 1, 1, 255))), b"", 0)


# ---------------------------------------------------------------------------
# instcard
# ---------------------------------------------------------------------------


def _card_texture() -> np.ndarray:
    rng = np.random.default_rng(7)
    tex = _rgba(512, 256, (0, 0, 0, 255))
    tex[..., :3] = rng.integers(60, 200, (256, 512, 3))
    return tex


def _small_mockup(tmp_path: Path, card: np.ndarray, name: str) -> Path:
    """Card pixels upscaled ~4.1×, with a dark 'EN' line drawn in."""
    im = _im(card).convert("RGB").resize((round(card.shape[1] / 0.243), round(card.shape[0] / 0.243)))
    a = np.array(im)
    a[20:40, 10:90] = (5, 5, 5)
    a[80:180, 30:50] = (250, 250, 250)  # tall block: not a text line
    path = tmp_path / name
    Image.fromarray(a).save(path)
    return path


def test_instcard_main_builds_all_sets(monkeypatch, tmp_path, capsys):
    mod = _cutter("instcard")
    tex = _card_texture()
    box = (0, 0, 40, 40)
    mock = _small_mockup(tmp_path, tex[0:40, 0:40], "m.png")
    van = {p: [_Entry("readme.bin", None), _Entry("000.l2mgtex", _im(tex), 99)] for p in (1, 2)}
    pieces = {k: _im(_rgba(64, 64, (250, 30, 30, 255))) for k in mod.CARD_LOGO}
    van[125] = [_Entry(f"{k}.l2mgtex", im) for k, im in pieces.items()] + [_Entry("999.l2mgtex", None)]
    masters = _install(monkeypatch, tmp_path, mod, van)
    for k in ("006", "007", "008", "011"):
        _im(_rgba(64, 64, (30, 30, 250, 255))).save(masters / f"PuzzleTitle_{k}.png")
    monkeypatch.setattr(mod, "SETS", {
        1: ("A.png", ((mock, box),), True, 16),
        2: ("B.png", ((mock, box, {"place": (0.243, 0.243, 0, 0), "regions": ((1, 1, 10, 10),)}),), False, 16),
    })
    monkeypatch.setattr(sys, "argv", ["cut"])
    assert mod.main() == 0
    assert (masters / "A.png").is_file() and (masters / "B.png").is_file()
    out = capsys.readouterr().out
    assert "registered mockup" in out and "EN px" in out

    monkeypatch.setattr(sys, "argv", ["cut", "2"])
    assert mod.main() == 0


# ---------------------------------------------------------------------------
# title
# ---------------------------------------------------------------------------


def _etc1_tile() -> bytes:
    body = bytes(64 * 64 // 2)
    return struct.pack("<4I", 64, 64, 12, len(body)) + bytes(real_l2.HEADER_LEN - 16) + body


def test_title_main(monkeypatch, tmp_path, capsys):
    mod = _cutter("title")
    piece = _rgba(64, 64)
    piece[8:56, 8:56] = (240, 120, 200, 255)
    pkg = [_Entry(f"{k}.l2mgtex", _im(piece)) for k in mod.PLACE]
    pkg += [_Entry("002.l2mgtex", _etc1_tile()), _Entry("notes.txt", None)]
    masters = _install(monkeypatch, tmp_path, mod, {mod.PKG: pkg})
    assert mod.main() == 0
    assert {p.name for p in masters.iterdir()} == {f"PuzzleTitle_{k}.png" for k in mod.EN_PIECES}
    assert "background tile phase" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="no palette"):
        mod.quantize_to_slot(_im(_rgba(8, 8, (1, 1, 1, 255))), b"", 0)
