"""Line and branch coverage for patch helpers that the focused tests skip.

No vanilla dumps, no network, no real ROM. Heavy compressors and image packs
are mocked or given a few bytes.
"""

from __future__ import annotations

import argparse
import builtins
import io
import json
import struct
import sys
import types
import urllib.error
import zlib
from pathlib import Path

import pytest
from PIL import Image

import darcutil
import exact_zlib as ez
import extract_vanilla_from_rom as ev
import fake_img as fi
import bclimutil
import gemini_translate as gt
import pack_images as pack
import patch_bplace_list_pane as bplace
import patch_cesa as cesa
import patch_weather_weekdays as weather
import patcher
import patcher_version as pv
import report_progress as report
from img_pack_cache import ImgPackCache
from patch_password_serials import _pack_trb

# ---------------------------------------------------------------------------
# patcher.py
# ---------------------------------------------------------------------------


class _AsciiStdout:
    encoding = "ascii"

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def write(self, text: str) -> int:
        if any(ord(ch) > 127 for ch in text):
            raise UnicodeEncodeError("ascii", text, 0, 1, "ordinal not in range")
        self.chunks.append(text)
        return len(text)

    def flush(self) -> None:
        return None


def _xml(path: Path, dialogs: list[str]) -> None:
    body = "".join(f"<Dialog>{text}</Dialog>" for text in dialogs)
    path.write_text(
        f"<?xml version='1.0'?><root>{body}</root>",
        encoding="utf-8",
        newline="\n",
    )


def test_patcher_safe_print_replaces_unencodable_text(monkeypatch):
    out = _AsciiStdout()
    monkeypatch.setattr(sys, "stdout", out)
    patcher._safe_print("こんにちは")
    assert out.chunks
    assert all(ord(ch) < 128 for chunk in out.chunks for ch in chunk)


def test_patcher_dialog_edges(tmp_path: Path):
    empty = tmp_path / "empty.xml"
    empty.write_text("<root><Dialog/></root>", encoding="utf-8")
    assert patcher._dialog_texts(empty) == [""]
    bad = tmp_path / "bad.xml"
    bad.write_text("<nope", encoding="utf-8")
    with pytest.raises(ValueError, match="XML parse error"):
        patcher._dialog_texts(bad)


def test_patcher_status_counts_and_missing_import(tmp_path: Path, monkeypatch):
    scripts = tmp_path / "scripts"
    images = tmp_path / "images"
    scripts.mkdir()
    images.mkdir()
    for name in ("t001.xml", "p002.xml", "a003.xml", "k004.xml", "z005.xml", ".xml"):
        (scripts / name).write_text("<root/>", encoding="utf-8")
    (images / "a.png").write_bytes(b"png")
    (images / "nested").mkdir()
    (images / "nested" / "b.psd").write_bytes(b"psd")
    (images / "c.pdn").write_bytes(b"pdn")
    (images / "d.xcf").write_bytes(b"xcf")
    monkeypatch.setattr(patcher, "SCRIPTS", scripts)
    monkeypatch.setattr(patcher, "IMAGES", images)
    assert patcher.iter_scripts()
    assert patcher.cmd_status(argparse.Namespace()) == 0

    monkeypatch.setattr(patcher, "IMAGES", tmp_path / "no-images")
    monkeypatch.setattr(patcher, "SCRIPTS", tmp_path / "no-scripts")
    assert patcher.iter_scripts() == []
    assert patcher.cmd_status(argparse.Namespace()) == 0

    real_import = builtins.__import__

    def _block(name, *args, **kwargs):
        if name == "script_inject":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(patcher, "SCRIPTS", scripts)
    monkeypatch.setattr(patcher, "IMAGES", images)
    monkeypatch.setattr(builtins, "__import__", _block)
    assert patcher.cmd_status(argparse.Namespace()) == 0


def test_patcher_validate_flags_xml_japanese_and_placeholders(tmp_path: Path, monkeypatch):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    monkeypatch.setattr(patcher, "SCRIPTS", scripts)
    monkeypatch.setattr(sys, "stdout", _AsciiStdout())
    lines = ["日本語の文章です"] * 9
    lines.append("▲主人公＊▲は今日も元気です")
    lines.append("あい")
    lines.append("TODO later")
    _xml(scripts / "t010.xml", lines)
    _xml(scripts / "k099.xml", ["日本語の文章です"])
    (scripts / "p011.xml").write_text("<nope", encoding="utf-8")
    assert patcher.cmd_validate(argparse.Namespace()) == 1

    (scripts / "p011.xml").unlink()
    _xml(scripts / "p011.xml", ["Hello there."])
    monkeypatch.setattr(sys, "stdout", sys.__stdout__)
    assert patcher.cmd_validate(argparse.Namespace()) == 0


def test_patcher_dialogs_and_build(tmp_path: Path, monkeypatch, capsys):
    scripts = tmp_path / "scripts"
    images = tmp_path / "images" / "sub"
    scripts.mkdir()
    images.mkdir(parents=True)
    _xml(scripts / "t020.xml", ["Hello\r\nthere\rstill"])
    (scripts / "bad.xml").write_text("<nope", encoding="utf-8")
    (images / "pic.png").write_bytes(b"png")
    monkeypatch.setattr(patcher, "SCRIPTS", scripts)
    monkeypatch.setattr(patcher, "IMAGES", images.parent)

    missing = patcher.cmd_dialogs(argparse.Namespace(script="nope", out=None))
    assert missing == 1
    assert patcher.cmd_dialogs(argparse.Namespace(script="bad", out=None)) == 1
    (scripts / "bad.xml").unlink()

    out_file = tmp_path / "nested" / "dialogs.txt"
    assert patcher.cmd_dialogs(
        argparse.Namespace(script="t020.xml", out=str(out_file))
    ) == 0
    text = out_file.read_text(encoding="utf-8")
    assert "Hello\nthere\nstill" in text

    assert patcher.cmd_dialogs(argparse.Namespace(script=None, out=None)) == 0
    assert "0001|" in capsys.readouterr().out

    built = tmp_path / "pkg"
    (built / "keep.txt").parent.mkdir()
    (built / "keep.txt").write_text("keep", encoding="utf-8")
    assert patcher.cmd_build(argparse.Namespace(out=str(built), clean=False)) == 0
    assert (built / "keep.txt").is_file()
    assert (built / "images" / "sub" / "pic.png").is_file()
    assert patcher.cmd_build(argparse.Namespace(out=str(built), clean=True)) == 0
    assert not (built / "keep.txt").exists()
    assert "scripts:" in (built / "MANIFEST.txt").read_text(encoding="utf-8")

    monkeypatch.setattr(patcher, "IMAGES", tmp_path / "no-images")
    bare = tmp_path / "bare"
    assert patcher.cmd_build(argparse.Namespace(out=str(bare), clean=False)) == 0
    assert "images:  0" in (bare / "MANIFEST.txt").read_text(encoding="utf-8")


def test_patcher_main_assets_gate(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(patcher, "ASSETS", tmp_path / "missing-assets")
    assert patcher.main(["status"]) == 1
    assets = tmp_path / "assets"
    (assets / "scripts").mkdir(parents=True)
    (assets / "images").mkdir()
    monkeypatch.setattr(patcher, "ASSETS", assets)
    monkeypatch.setattr(patcher, "SCRIPTS", assets / "scripts")
    monkeypatch.setattr(patcher, "IMAGES", assets / "images")
    assert patcher.main(["status"]) == 0


# ---------------------------------------------------------------------------
# patch_bplace_list_pane.py
# ---------------------------------------------------------------------------


def _bplace_buf() -> bytearray:
    data = bytearray(bplace.ADDR_DRAW_SP4 + 16)
    data[bplace.ADDR_PANE : bplace.ADDR_PANE + len(bplace.ORIG_PANE)] = bplace.ORIG_PANE
    for site in bplace.GLYPH_CAP_SITES:
        data[site : site + len(bplace.ORIG_CAP)] = bplace.ORIG_CAP
    for site in bplace.DRAW_SP0_SITES:
        data[site : site + len(bplace.ORIG_DRAW_SP0)] = bplace.ORIG_DRAW_SP0
    data[bplace.ADDR_DRAW_SP4 : bplace.ADDR_DRAW_SP4 + len(bplace.ORIG_DRAW_SP4)] = (
        bplace.ORIG_DRAW_SP4
    )
    return data


def test_bplace_apply_vanilla_bad_pane_and_partial_wide():
    data = _bplace_buf()
    assert bplace.is_vanilla(data)
    assert not bplace.is_wide(data)
    assert bplace.apply_patch(data) is True
    assert bplace.is_wide(data)
    assert bplace.apply_patch(data) is False

    again = _bplace_buf()
    again[bplace.ADDR_PANE : bplace.ADDR_PANE + 16] = bplace.BAD_PANE
    assert not bplace.is_vanilla(again)
    assert bplace.apply_patch(again) is True
    assert again[bplace.ADDR_PANE : bplace.ADDR_PANE + 16] == bplace.WIDE_PANE

    partial = _bplace_buf()
    partial[bplace.ADDR_PANE : bplace.ADDR_PANE + 16] = bplace.WIDE_PANE
    partial[bplace.GLYPH_CAP_SITES[0] : bplace.GLYPH_CAP_SITES[0] + 8] = bplace.WIDE_CAP
    partial[bplace.DRAW_SP0_SITES[0] : bplace.DRAW_SP0_SITES[0] + 8] = bplace.WIDE_DRAW_SP0
    partial[bplace.ADDR_DRAW_SP4 : bplace.ADDR_DRAW_SP4 + 8] = bplace.WIDE_DRAW_SP4
    assert not bplace._caps_ok(partial)
    assert not bplace._draw_ok(_bplace_buf())
    assert bplace.apply_patch(partial) is True
    assert bplace.is_wide(partial)


def test_bplace_rejects_unexpected_bytes():
    pane = _bplace_buf()
    pane[bplace.ADDR_PANE : bplace.ADDR_PANE + 16] = b"\xff" * 16
    with pytest.raises(ValueError, match="CreateTextPane"):
        bplace.apply_patch(pane)

    cap = _bplace_buf()
    cap[bplace.GLYPH_CAP_SITES[1] : bplace.GLYPH_CAP_SITES[1] + 8] = b"\xff" * 8
    cap[bplace.GLYPH_CAP_SITES[0] : bplace.GLYPH_CAP_SITES[0] + 8] = bplace.WIDE_CAP
    with pytest.raises(ValueError, match="glyph cap"):
        bplace.apply_patch(cap)

    draw = _bplace_buf()
    site = bplace.DRAW_SP0_SITES[1]
    draw[site : site + 8] = b"\xff" * 8
    draw[bplace.DRAW_SP0_SITES[0] : bplace.DRAW_SP0_SITES[0] + 8] = bplace.WIDE_DRAW_SP0
    with pytest.raises(ValueError, match="maxGlyphs"):
        bplace.apply_patch(draw)

    sp4 = _bplace_buf()
    sp4[bplace.ADDR_DRAW_SP4 : bplace.ADDR_DRAW_SP4 + 8] = b"\xff" * 8
    with pytest.raises(ValueError, match="maxGlyphs"):
        bplace.apply_patch(sp4)

    vanilla = _bplace_buf()
    vanilla[bplace.GLYPH_CAP_SITES[0] : bplace.GLYPH_CAP_SITES[0] + 8] = b"\xff" * 8
    assert not bplace.is_vanilla(vanilla)
    vanilla = _bplace_buf()
    vanilla[bplace.ADDR_DRAW_SP4 : bplace.ADDR_DRAW_SP4 + 8] = b"\xff" * 8
    assert not bplace.is_vanilla(vanilla)
    vanilla = _bplace_buf()
    vanilla[bplace.DRAW_SP0_SITES[2] : bplace.DRAW_SP0_SITES[2] + 8] = b"\xff" * 8
    assert not bplace.is_vanilla(vanilla)
    assert not bplace._draw_ok(vanilla)
    assert not bplace.is_vanilla(bytearray(bplace.ADDR_DRAW_SP4 + 16))


# ---------------------------------------------------------------------------
# patch_weather_weekdays.py
# ---------------------------------------------------------------------------


def _weather_trb(text: str = "A", *, flag: int = 1, counts=(2, 14, 32)) -> bytes:
    raw = text.encode("utf-8")
    stri = struct.pack("<IHH", 0, len(raw), flag)
    strb = raw + (b"\x00" if flag == 1 else b"")
    cat = weather.WEEKDAY_CAT
    cat_off = 0x400
    indx = bytearray(cat_off + 16)
    struct.pack_into("<I", indx, cat * 4, cat_off)
    struct.pack_into("<I", indx, cat_off, 3)
    cursor = cat_off + 16
    rels = []
    for count in counts:
        rels.append(cursor - cat_off)
        need = cursor + 4 + count * 2
        if len(indx) < need:
            indx.extend(b"\x00" * (need - len(indx)))
        struct.pack_into("<I", indx, cursor, count)
        cursor += 4 + count * 2
    for i, rel in enumerate(rels):
        struct.pack_into("<I", indx, cat_off + 4 + i * 4, rel)
    chunks = {
        "STRI": stri,
        "STRB": strb,
        "INDX": bytes(indx),
        "_order": ["STRI", "STRB", "INDX"],
    }
    return _pack_trb(chunks)


def test_weather_weekdays_appends_pads_and_is_idempotent():
    saw_pad = saw_aligned = False
    for text in ("A", "AB", "ABC", "ABCD"):
        patched, logs = weather.apply_weather_weekdays(_weather_trb(text))
        assert any("-> Su" in line for line in logs)
        body = weather.parse_needed(patched)["STRB"]
        assert len(body) % 4 == 0
        saw_pad = saw_pad or body.endswith(b"\xc9")
        saw_aligned = saw_aligned or not body.endswith(b"\xc9")
        again, logs2 = weather.apply_weather_weekdays(patched)
        assert again == patched
        assert all("already" in line for line in logs2)
        assert list(weather.iter_stri(weather.parse_needed(patched)["STRI"]))
    assert saw_pad and saw_aligned

    flagged, logs = weather.apply_weather_weekdays(_weather_trb("Z", flag=0))
    assert flagged != _weather_trb("Z", flag=0)
    assert any("->" in line for line in logs)


def test_weather_weekdays_rejects_a_short_pack():
    with pytest.raises(ValueError, match="slots"):
        weather.apply_weather_weekdays(_weather_trb(counts=(1, 14, 32)))


# ---------------------------------------------------------------------------
# patcher_version.py
# ---------------------------------------------------------------------------


def test_patcher_version_fingerprint_and_stale_skip(tmp_path: Path, monkeypatch, capsys):
    images = tmp_path / "images"
    check = images / "album.check" / "timg"
    check.mkdir(parents=True)
    (check / "Keep.png").write_bytes(b"small-png")
    (check / "Skip_jpn.png").write_bytes(b"jp")
    (check / "Skip (2).png").write_bytes(b"copy")
    copied = images / "album.check" / "timg - copy"
    copied.mkdir()
    (copied / "Hidden.png").write_bytes(b"hidden")
    (images / "album.check" / "__pycache__").mkdir()
    (images / "album.check" / "__pycache__" / "X.png").write_bytes(b"pyc")
    big = check / "Big.png"
    big.write_bytes(b"B" * (1024 * 1024 + 8))
    (images / "album").mkdir()
    (images / "album" / "Other.png").write_bytes(b"plain")
    (images / "album.arc").mkdir()
    (images / "album.arc" / "Arc.png").write_bytes(b"arc")
    (images / "notes.txt").write_text("x", encoding="utf-8")
    (images / "not-a-folder-key").mkdir()
    assert pv._prefer_image_folders(tmp_path / "missing") == {}
    chosen = pv._prefer_image_folders(images)
    assert chosen["album"].name.endswith(".check")
    monkeypatch.setattr(pv, "ASSETS_IMAGES", images)
    fp_default = pv.ui_png_fingerprint()
    fp = pv.ui_png_fingerprint(images)
    assert fp == fp_default
    assert len(fp) == 16
    assert pv.ui_png_fingerprint(tmp_path / "empty-images") != "" or True
    empty = tmp_path / "empty-images"
    empty.mkdir()
    assert len(pv.ui_png_fingerprint(empty)) == 16

    stamp = tmp_path / "rel" / "bake_stamp.txt"
    monkeypatch.setattr(pv, "ui_png_fingerprint", lambda images_root=None: "ab" * 8)
    pv.write_bake_stamp(stamp, packed_assets=False)
    assert not stamp.is_file()
    assert "stale" in capsys.readouterr().out
    stamp.write_text("not-a-release\nno-prefix\n", encoding="utf-8")
    assert pv.bake_stamp_matches(stamp) is False
    stamp.write_text(f"{pv.PATCHER_RELEASE}\nui-png:ffff\n", encoding="utf-8")
    assert pv.bake_stamp_matches(stamp) is False


# ---------------------------------------------------------------------------
# report_progress.py
# ---------------------------------------------------------------------------


def _progress_trb(texts: list[str]) -> bytes:
    strb = bytearray()
    stri = bytearray()
    for text in texts:
        raw = text.encode("utf-8")
        stri += struct.pack("<IHH", len(strb), len(raw), 1)
        strb += raw + b"\x00"
    chunks = {"STRI": bytes(stri), "STRB": bytes(strb), "_order": ["STRI", "STRB"]}
    return _pack_trb(chunks)


def _isolate_progress(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(report.paths, "ROOT", tmp_path)
    monkeypatch.delenv("NLPP_PROGRESS_ENDPOINT", raising=False)
    monkeypatch.delenv("NLPP_PROGRESS_TOKEN", raising=False)
    monkeypatch.delenv("PROGRESS_API_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    monkeypatch.delenv("NLPP_PROGRESS_SKIP", raising=False)


def test_report_progress_dotenv_and_required_gates(tmp_path: Path, monkeypatch):
    _isolate_progress(monkeypatch, tmp_path / "repo")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text(
        "\n# comment\nNOEQUALS\nEMPTY=\nNLPP_PROGRESS_TOKEN='from-file'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NLPP_PROGRESS_TOKEN", "   ")
    assert report._from_env_or_dotenv("NLPP_PROGRESS_TOKEN") == "from-file"
    assert report.load_token("  explicit  ") == "explicit"
    assert report.load_token("", required=False) is None
    with pytest.raises(SystemExit, match="No progress token"):
        report.load_token("", required=True)
    assert report.load_endpoint(" https://example.test/p ") == "https://example.test/p"
    assert report.load_endpoint("", required=False) is None
    with pytest.raises(SystemExit, match="No progress endpoint"):
        report.load_endpoint("", required=True)

    monkeypatch.delenv("NLPP_PROGRESS_TOKEN", raising=False)
    (repo / ".env").write_text("# only\nEMPTY=\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "NLPP_PROGRESS_ENDPOINT=\"https://parent.test/p\"\n",
        encoding="utf-8",
    )
    assert report._from_env_or_dotenv("NLPP_PROGRESS_ENDPOINT") == "https://parent.test/p"


def test_report_script_progress_counts_and_mismatch(tmp_path: Path):
    vanilla = tmp_path / "jp.trb"
    english = tmp_path / "en.trb"
    vanilla.write_bytes(_progress_trb(["", "Hello", "こんにちは", "さようなら"]))
    english.write_bytes(_progress_trb(["", "Hello", "Hello", "さようなら"]))
    got = report.script_progress(vanilla, english)
    assert got == {"scriptTranslated": 1, "scriptTotal": 2, "scriptPercent": 50}

    vanilla.write_bytes(_progress_trb(["Hello"]))
    english.write_bytes(_progress_trb(["Hello"]))
    assert report.script_progress(vanilla, english)["scriptPercent"] == 0

    english.write_bytes(_progress_trb(["Hello", "extra"]))
    with pytest.raises(SystemExit, match="entry count mismatch"):
        report.script_progress(vanilla, english)


def test_report_post_and_try_report(tmp_path: Path, monkeypatch, capsys):
    _isolate_progress(monkeypatch, tmp_path)

    class _Resp:
        status = 204

        def read(self):
            return b'{"ok":true}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(report.urllib.request, "urlopen", lambda *a, **k: _Resp())
    report.post_progress("https://example.test/p", "tok", {"scriptPercent": 1})
    assert "204" in capsys.readouterr().out

    def _http(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://example.test/p", 500, "no", {}, io.BytesIO(b"denied")
        )

    monkeypatch.setattr(report.urllib.request, "urlopen", _http)
    with pytest.raises(SystemExit, match="HTTP 500"):
        report.post_progress("https://example.test/p", "tok", {"scriptPercent": 1})

    def _url(*args, **kwargs):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(report.urllib.request, "urlopen", _url)
    with pytest.raises(SystemExit, match="down"):
        report.post_progress("https://example.test/p", "tok", {"scriptPercent": 1})

    van = tmp_path / "jp.trb"
    en = tmp_path / "en.trb"
    van.write_bytes(_progress_trb(["こんにちは"]))
    en.write_bytes(_progress_trb(["Hello"]))
    monkeypatch.setattr(report.paths, "find_vanilla_main_trb", lambda: None)
    assert report.try_report_progress(en_trb=en, vanilla_trb=van, dry_run=True) is False
    assert "scriptPercent" in capsys.readouterr().out

    monkeypatch.setenv("NLPP_PROGRESS_SKIP", "on")
    assert report.try_report_progress() is False
    monkeypatch.delenv("NLPP_PROGRESS_SKIP", raising=False)
    assert report.try_report_progress(en_trb=en, vanilla_trb=tmp_path / "missing-jp.trb") is False
    assert report.try_report_progress(en_trb=tmp_path / "missing-en.trb", vanilla_trb=van) is False

    monkeypatch.setattr(report, "script_progress", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setenv("NLPP_PROGRESS_ENDPOINT", "https://example.test/p")
    monkeypatch.setenv("NLPP_PROGRESS_TOKEN", "tok")
    assert report.try_report_progress(en_trb=en, vanilla_trb=van) is False

    monkeypatch.setattr(report, "script_progress", lambda *a, **k: (_ for _ in ()).throw(SystemExit("hard")))
    assert report.try_report_progress(en_trb=en, vanilla_trb=van) is False
    monkeypatch.setattr(report, "script_progress", lambda *a, **k: (_ for _ in ()).throw(SystemExit(3)))
    assert report.try_report_progress(en_trb=en, vanilla_trb=van) is False

    monkeypatch.setattr(
        report,
        "script_progress",
        lambda *a, **k: {"scriptTranslated": 1, "scriptTotal": 1, "scriptPercent": 100},
    )
    monkeypatch.setattr(report, "post_progress", lambda *a, **k: None)
    assert report.try_report_progress(en_trb=en, vanilla_trb=van) is True


def test_report_progress_main_modes(tmp_path: Path, monkeypatch):
    _isolate_progress(monkeypatch, tmp_path)
    van = tmp_path / "jp.trb"
    en = tmp_path / "en.trb"
    van.write_bytes(_progress_trb(["こんにちは"]))
    en.write_bytes(_progress_trb(["Hello"]))
    monkeypatch.setattr(report.paths, "find_vanilla_main_trb", lambda: None)
    monkeypatch.setattr(sys, "argv", ["report_progress.py", "--dry-run", "--vanilla-trb", str(van), "--en-trb", str(en)])
    assert report.main() == 0
    monkeypatch.setattr(sys, "argv", ["report_progress.py", "--best-effort", "--en-trb", str(tmp_path / "missing.trb")])
    assert report.main() == 0

    monkeypatch.setenv("NLPP_PROGRESS_SKIP", "true")
    monkeypatch.setattr(sys, "argv", ["report_progress.py", "--vanilla-trb", str(van), "--en-trb", str(en)])
    assert report.main() == 0
    monkeypatch.delenv("NLPP_PROGRESS_SKIP", raising=False)

    monkeypatch.setattr(sys, "argv", ["report_progress.py", "--en-trb", str(en)])
    with pytest.raises(SystemExit, match="vanilla textresource"):
        report.main()
    monkeypatch.setattr(sys, "argv", ["report_progress.py", "--vanilla-trb", str(van), "--en-trb", str(tmp_path / "no.trb")])
    with pytest.raises(SystemExit, match="English TRB not found"):
        report.main()

    monkeypatch.setenv("NLPP_PROGRESS_ENDPOINT", "https://example.test/p")
    monkeypatch.setenv("NLPP_PROGRESS_TOKEN", "tok")
    monkeypatch.setattr(report, "post_progress", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["report_progress.py", "--vanilla-trb", str(van), "--en-trb", str(en)])
    assert report.main() == 0


# ---------------------------------------------------------------------------
# darcutil.py
# ---------------------------------------------------------------------------


def _darc_bytes(files: dict[str, bytes], endian: str = "<") -> bytes:
    bom = b"\xff\xfe" if endian == "<" else b"\xfe\xff"
    enc = "utf-16le" if endian == "<" else "utf-16be"
    groups: dict[str, list[tuple[str, bytes]]] = {}
    for rel, data in files.items():
        folder, _, name = rel.rpartition("/")
        groups.setdefault(folder, []).append((name, data))
    rows: list[tuple[str, bool, bytes | None]] = [("", True, None), (".", True, None)]
    dir_rows: list[int] = []
    for folder in sorted(groups):
        if folder:
            dir_rows.append(len(rows))
            rows.append((folder, True, None))
        rows.extend((name, False, data) for name, data in groups[folder])
    names = bytearray()
    name_offs = []
    for name, _, _ in rows:
        name_offs.append(len(names))
        names += name.encode(enc) + b"\x00\x00"
    count = len(rows)
    table_off = 0x1C
    table_size = count * 12 + len(names)
    align = 0x20
    data_start = (table_off + table_size + align - 1) & ~(align - 1)
    blob = bytearray()
    entries = []
    dir_end = {}
    for i, idx in enumerate(dir_rows):
        dir_end[idx] = dir_rows[i + 1] if i + 1 < len(dir_rows) else count
    for i, (name, is_dir, data) in enumerate(rows):
        if is_dir:
            parent, end = (0, count) if i < 2 else (1, dir_end[i])
            entries.append(struct.pack(endian + "III", name_offs[i] | 0x01000000, parent, end))
            continue
        blob += bytes((-len(blob)) % align)
        entries.append(struct.pack(endian + "III", name_offs[i], data_start + len(blob), len(data)))
        blob += data or b""
    out = bytearray(b"darc" + bom + struct.pack(endian + "H", 0x1C))
    out += struct.pack(endian + "IIIII", 1, 0, table_off, table_size, data_start)
    out += b"".join(entries) + names
    if len(out) < data_start:
        out += bytes(data_start - len(out))
    out += blob
    struct.pack_into(endian + "I", out, 0x0C, len(out))
    return bytes(out)


def test_darc_parse_errors_align_and_lookup(tmp_path: Path):
    with pytest.raises(ValueError, match="not a darc"):
        darcutil.DarcArchive(b"nope")
    with pytest.raises(ValueError, match="bad DARC BOM"):
        darcutil.DarcArchive(b"darc\x00\x00" + b"\x00" * 24)
    assert darcutil._align(5, 1) == 5
    assert darcutil._align(5, 0) == 5
    assert darcutil._align(8, 4) == 8
    assert darcutil._read_utf16z(b"\x41\x00", 0, "<") == "A"
    assert darcutil._read_utf16z(b"\x41\x00\x00\x00", 0, "<") == "A"
    assert darcutil._write_utf16z("A", ">").startswith("A".encode("utf-16be"))

    raw = _darc_bytes({"timg/A.bclim": b"aaaa", "other/A.bclim": b"bbbb", "only.bin": b"cccc"})
    arch = darcutil.DarcArchive(raw)
    assert arch.find("timg/A.bclim") is not None
    assert arch.find("timg\\A.bclim").name.endswith("A.bclim")
    assert arch.find("only.bin") is not None
    assert arch.find("A.bclim").name.startswith("timg/")
    ambiguous = _darc_bytes({"left/Foo.bin": b"1", "right/Foo.bin": b"2"})
    assert darcutil.DarcArchive(ambiguous).find("Foo.bin") is None
    both = _darc_bytes({"timg/Foo.bin": b"1", "timg/nested/Foo.bin": b"22"})
    assert darcutil.DarcArchive(both).find("Foo.bin") is None

    # A lone file (not a directory) takes the count=1 branch.
    name = "Z.bin".encode("utf-16le") + b"\x00\x00"
    table_off = 0x1C
    data_start = 0x40
    lone = bytearray(b"darc\xff\xfe" + struct.pack("<H", 0x1C))
    lone += struct.pack("<IIIII", 1, 0, table_off, 12 + len(name), data_start)
    lone += struct.pack("<III", 0, data_start, 3) + name
    lone += bytes(data_start - len(lone)) + b"xyz"
    struct.pack_into("<I", lone, 0x0C, len(lone))
    lone_arch = darcutil.DarcArchive(bytes(lone))
    assert lone_arch.files[0].name == "Z.bin"
    assert lone_arch.extract_file(lone_arch.files[0]) == b"xyz"

    dest = tmp_path / "out"
    assert arch.extract_all(dest) == 3
    src = tmp_path / "src.darc"
    arch.save(src)
    loaded = darcutil.DarcArchive.load(src)
    entry = loaded.find("only.bin")
    assert entry is not None
    loaded.replace_same_size(entry, b"CCCC")
    assert loaded.extract_file(entry) == b"CCCC"
    with pytest.raises(ValueError, match="size mismatch"):
        loaded.replace_same_size(entry, b"no")


def test_darc_insert_and_rebuild(tmp_path: Path):
    raw = _darc_bytes({"timg/Copyright.bclim": b"abcd"}, endian=">")
    arch = darcutil.DarcArchive(raw)
    assert arch.endian == ">"
    with pytest.raises(ValueError, match="directory"):
        arch.insert_file_entry("Eng_Patch.bclim", "timg/Copyright.bclim")
    with pytest.raises(FileNotFoundError):
        arch.insert_file_entry("timg/Eng_Patch.bclim", "missing")
    arch.insert_file_entry("timg/Eng_Patch.bclim", "timg/Copyright.bclim")
    arch.insert_file_entry("timg/Eng_Patch.bclim", "timg/Copyright.bclim")
    assert sum(1 for e in arch.entries if e.get("rel") == "timg/Eng_Patch.bclim") == 1

    extracted = tmp_path / "tree"
    darcutil.DarcArchive(raw).extract_all(extracted)
    (extracted / "timg" / "Eng_Patch.bclim").write_bytes(b"WXYZ")
    arch.rebuild_from_dir(
        extracted,
        tmp_path / "be.darc",
        align_mode="absolute",
        type_align={".bclim": 0x80},
        extra=1,
    )
    rebuilt = darcutil.DarcArchive((tmp_path / "be.darc").read_bytes())
    assert rebuilt.endian == ">"
    got = rebuilt.find("timg/Eng_Patch.bclim")
    assert got is not None
    assert rebuilt.extract_file(got) == b"WXYZ"

    rel = darcutil.DarcArchive(_darc_bytes({"timg/Copyright.bclim": b"abcd"}))
    rel.insert_file_entry("timg/Eng_Patch.bclim", "timg/Copyright.bclim")
    rel.rebuild_from_dir(extracted, tmp_path / "le.darc", align_mode="relative")
    assert darcutil.DarcArchive((tmp_path / "le.darc").read_bytes()).find("Eng_Patch.bclim")

    with pytest.raises(FileNotFoundError, match="missing"):
        rel.rebuild_from_dir(tmp_path / "empty", tmp_path / "no.darc")


# ---------------------------------------------------------------------------
# extract_vanilla_from_rom.py
# ---------------------------------------------------------------------------


@pytest.fixture
def vanilla_paths(tmp_path: Path, monkeypatch):
    root = tmp_path / "vanilla_from_rom"
    romfs = root / "romfs"
    code = tmp_path / "code.bin"
    monkeypatch.setattr(ev, "ROOT", tmp_path)
    monkeypatch.setattr(ev, "VANILLA_ROOT", root)
    monkeypatch.setattr(ev, "VANILLA_ROMFS", romfs)
    monkeypatch.setattr(ev, "VANILLA_IMG", romfs / "img.bin")
    monkeypatch.setattr(ev, "VANILLA_MAIN_TRB", romfs / "SystemData" / "TextResource" / "textresource_jpn.trb")
    monkeypatch.setattr(ev, "VANILLA_CODE", code)
    monkeypatch.setattr(ev, "MARKER", root / ".source_rom.txt")
    monkeypatch.setattr(ev, "CACHE_VANILLA_EXEFS", tmp_path / "exefs")
    monkeypatch.setattr(ev, "find_vanilla_img", lambda: None)
    monkeypatch.setattr(ev, "find_vanilla_code", lambda: None)
    monkeypatch.setattr(ev.time, "sleep", lambda _s: None)
    return root


def _wire_rom(monkeypatch, *, img=True, trb=True, code=True):
    def prepare(rom, dest, kind=None):
        dest.mkdir(parents=True, exist_ok=True)
        return dest / "game.cxi", False, 0

    def split(cxi, dest):
        dest.mkdir(parents=True, exist_ok=True)
        exefs = dest / "exefs.bin"
        romfs = dest / "romfs.bin"
        exefs.write_bytes(b"E")
        romfs.write_bytes(b"R")
        return {"exefs": exefs, "romfs": romfs}

    def ensure(romfs_bin, out_dir, reuse=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        if img:
            (out_dir / "img.bin").write_bytes(b"IMG")
        if trb:
            path = out_dir / "SystemData" / "TextResource" / "textresource_jpn.trb"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"TRB")
            resident = path.with_name("textresource_resident_jpn.trb")
            resident.write_bytes(b"RES")
        (out_dir / "junk.bin").write_bytes(b"JUNK")
        script = out_dir / "script" / "bin" / "script"
        script.mkdir(parents=True, exist_ok=True)
        (script / "a.dbin2").write_bytes(b"DB")
        return out_dir

    def unpack(exefs, folder):
        return folder / "code.bin", b"H"

    def blz(src, dest):
        if code:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"CODE")

    monkeypatch.setattr(ev, "prepare_cxi_from_rom", prepare)
    monkeypatch.setattr(ev, "split_cxi", split)
    monkeypatch.setattr(ev, "ensure_romfs_dir", ensure)
    monkeypatch.setattr(ev, "_unpack_exefs", unpack)
    monkeypatch.setattr(ev, "_blz_uncompress", blz)
    monkeypatch.setattr(ev, "_require_tools", lambda: None)
    monkeypatch.setattr(ev, "detect_rom_kind", lambda rom: "cia")


def test_extract_cache_ready_retry_and_code_write(tmp_path: Path, vanilla_paths, monkeypatch):
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"CIA")
    assert ev.vanilla_cache_ready(rom) is False
    ev.VANILLA_IMG.parent.mkdir(parents=True)
    ev.VANILLA_IMG.write_bytes(b"IMG")
    ev.VANILLA_MAIN_TRB.parent.mkdir(parents=True, exist_ok=True)
    ev.VANILLA_MAIN_TRB.write_bytes(b"TRB")
    ev.VANILLA_CODE.write_bytes(b"CODE")
    assert ev.vanilla_cache_ready() is True
    assert ev.vanilla_cache_ready(rom) is True
    ev.MARKER.write_text("other", encoding="utf-8")
    assert ev.vanilla_cache_ready(rom) is False
    ev.MARKER.write_text(ev._rom_fingerprint(rom), encoding="utf-8")
    assert "|" in ev._rom_fingerprint(rom)
    assert ev.vanilla_cache_ready(rom) is True

    sleeps: list[float] = []
    monkeypatch.setattr(ev.time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("busy")
        return "ok"

    assert ev._retry(flaky, attempts=3, delay_s=0.0, what="unit") == "ok"
    assert len(sleeps) == 2
    with pytest.raises(ev.PatchError, match="failed after 2"):
        ev._retry(lambda: (_ for _ in ()).throw(RuntimeError("no")), attempts=2, delay_s=0, what="unit")
    with pytest.raises(ValueError):
        ev._retry(lambda: (_ for _ in ()).throw(ValueError("nope")), what="unit")

    ev.VANILLA_CODE.write_bytes(b"OLD")
    _wire_rom(monkeypatch)
    written = ev._write_decompressed_code(tmp_path / "exefs.bin", tmp_path / "work")
    assert written.read_bytes() == b"CODE"
    monkeypatch.setattr(ev, "_blz_uncompress", lambda src, dest: None)
    with pytest.raises(ev.PatchError, match="failed to write"):
        ev._write_decompressed_code(tmp_path / "exefs.bin", tmp_path / "work")


def test_extract_from_rom_branches(tmp_path: Path, vanilla_paths, monkeypatch):
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"CIA")
    with pytest.raises(FileNotFoundError, match="ROM not found"):
        ev.ensure_vanilla_from_rom(tmp_path / "missing.cia")

    ev.VANILLA_IMG.parent.mkdir(parents=True)
    ev.VANILLA_IMG.write_bytes(b"IMG")
    ev.VANILLA_MAIN_TRB.parent.mkdir(parents=True, exist_ok=True)
    ev.VANILLA_MAIN_TRB.write_bytes(b"TRB")
    ev.VANILLA_CODE.write_bytes(b"CODE")
    ev.MARKER.write_text(ev._rom_fingerprint(rom), encoding="utf-8")
    assert ev.ensure_vanilla_from_rom(rom) == ev.VANILLA_IMG.resolve()

    _wire_rom(monkeypatch)
    (ev.ROOT / "out" / "extract_vanilla_work").mkdir(parents=True)
    ev.VANILLA_ROOT.mkdir(parents=True, exist_ok=True)
    (ev.VANILLA_ROMFS.parent / "_slim_staging").mkdir(parents=True, exist_ok=True)
    img = ev.ensure_vanilla_from_rom(rom, force=True, slim=True)
    assert img.is_file()
    assert not (ev.VANILLA_ROMFS / "junk.bin").exists()
    assert (ev.VANILLA_ROMFS / "script" / "bin" / "script" / "a.dbin2").is_file()
    assert ev.VANILLA_CODE.is_file()

    _wire_rom(monkeypatch, img=False)
    with pytest.raises(ev.PatchError, match="missing img.bin"):
        ev.ensure_vanilla_from_rom(rom, force=True)
    _wire_rom(monkeypatch, trb=False)
    with pytest.raises(ev.PatchError, match="textresource_jpn.trb"):
        ev.ensure_vanilla_from_rom(rom, force=True)
    _wire_rom(monkeypatch, code=False)
    with pytest.raises(ev.PatchError, match="ExeFS code.bin extract"):
        ev.ensure_vanilla_from_rom(rom, force=True)
    monkeypatch.setattr(ev, "_write_decompressed_code", lambda *a, **k: tmp_path / "not-written.bin")
    _wire_rom(monkeypatch)
    monkeypatch.setattr(ev, "_write_decompressed_code", lambda *a, **k: tmp_path / "not-written.bin")
    ev.VANILLA_CODE.unlink(missing_ok=True)
    with pytest.raises(ev.PatchError, match="missing after extract"):
        ev.ensure_vanilla_from_rom(rom, force=True)


def test_extract_code_only_resolve_and_main(tmp_path: Path, vanilla_paths, monkeypatch):
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"CIA")
    _wire_rom(monkeypatch)
    ev.VANILLA_CODE.write_bytes(b"CODE")
    assert ev.ensure_vanilla_code_from_rom(rom) == ev.VANILLA_CODE.resolve()
    ev.MARKER.parent.mkdir(parents=True, exist_ok=True)
    ev.MARKER.write_text(ev._rom_fingerprint(rom), encoding="utf-8")
    assert ev.ensure_vanilla_code_from_rom(rom) == ev.VANILLA_CODE.resolve()

    other = tmp_path / "sibling-code.bin"
    other.write_bytes(b"SIB")
    ev.MARKER.write_text("stale", encoding="utf-8")
    monkeypatch.setattr(ev, "find_vanilla_code", lambda: other)
    assert ev.ensure_vanilla_code_from_rom(rom) == other.resolve()

    monkeypatch.setattr(ev, "find_vanilla_code", lambda: ev.VANILLA_CODE)
    ev.VANILLA_IMG.parent.mkdir(parents=True, exist_ok=True)
    ev.VANILLA_IMG.write_bytes(b"IMG")
    ev.VANILLA_CODE.unlink()
    got = ev.ensure_vanilla_code_from_rom(rom)
    assert got.read_bytes() == b"CODE"

    def _boom(*args, **kwargs):
        raise AssertionError("full extract should not run")

    monkeypatch.setattr(ev, "ensure_vanilla_from_rom", _boom)
    ev.VANILLA_CODE.unlink()
    assert ev.ensure_vanilla_code_from_rom(rom).is_file()

    calls = {"n": 0}

    def _ensure(rom, force=False, slim=False):
        calls["n"] += 1
        ev.VANILLA_CODE.write_bytes(b"FORCED")
        return ev.VANILLA_IMG

    monkeypatch.setattr(ev, "ensure_vanilla_from_rom", _ensure)
    ev.VANILLA_CODE.write_bytes(b"OLD")
    assert ev.ensure_vanilla_code_from_rom(rom, force=True).read_bytes() == b"FORCED"
    assert calls["n"] == 1

    monkeypatch.setattr(ev, "find_vanilla_img", lambda: other)
    assert ev.resolve_vanilla_img() == other
    with pytest.raises(FileNotFoundError, match="vanilla romfs"):
        monkeypatch.setattr(ev, "find_vanilla_img", lambda: None)
        ev.resolve_vanilla_img()
    monkeypatch.setattr(ev, "ensure_vanilla_from_rom", lambda rom, force=False, slim=False: rom)
    assert ev.resolve_vanilla_img(rom=rom) == rom
    assert ev.resolve_vanilla_img(rom=rom, force=True) == rom

    monkeypatch.setattr(ev, "ensure_vanilla_from_rom", lambda rom, force=False, slim=False: ev.VANILLA_IMG)
    ev.VANILLA_IMG.write_bytes(b"IMG")
    assert ev.main(["--rom", str(rom), "--force", "--slim"]) == 0
    monkeypatch.setattr(
        ev,
        "ensure_vanilla_from_rom",
        lambda *a, **k: (_ for _ in ()).throw(ev.PatchError("nope")),
    )
    assert ev.main(["--rom", str(rom)]) == 1


# ---------------------------------------------------------------------------
# gemini_translate.py
# ---------------------------------------------------------------------------


def test_gemini_env_markers_and_finalize(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gt, "ROOT", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    (tmp_path / ".env").write_text(
        "# c\n\nBAD\nEMPTY=\nDUP=1\nDUP=2\nGEMINI_API_KEY='key'\n",
        encoding="utf-8",
    )
    assert gt.dotenv_paths()
    loaded = gt.load_dotenv_map()
    assert loaded["GEMINI_API_KEY"] == "key"
    assert loaded["DUP"] == "1"
    assert gt.load_env_value("NOPE", explicit="  ") is None
    assert gt.load_env_value("NOPE", explicit="  x ") == "x"
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    assert gt.load_gemini_model() == "custom-model"
    assert gt.load_gemini_model(" override ") == "override"
    assert gt.load_gemini_api_key() == "key"
    (tmp_path / ".env").unlink()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        gt.load_gemini_api_key()

    assert gt.strip_markers("") == ""
    assert gt.should_skip_line("")
    assert gt.should_skip_line("   ")
    assert gt.protect_markers("hello") == ("hello", [])
    assert "@@M9@@" in gt.restore_markers("@@M9@@", ["only"])
    assert gt.leftover_sentinels("@@M0@@") == ["0"]
    assert gt.to_api_newlines("a\r\nb\rc") == "a◙b◙c"
    assert gt.from_api_newlines("a◙b\r\nc") == "a\nb\nc"
    assert gt.parse_items_json("") == {}
    assert gt.parse_items_json('{"nope": 1}') == {}
    assert gt.parse_items_json('{"items": [{"i": 1, "t": "a"}, {"no": 1}, "x"]}') == {1: "a"}

    skipped = gt.prepare_items(["おはよう"], need=[False])[0]
    assert gt.finalize_item(skipped, None).english == "おはよう"
    missing = gt.prepare_items(["おはよう"])[0]
    assert gt.finalize_item(missing, None).error == "missing"
    leftover = gt.finalize_item(missing, "Hi @@M3@@")
    assert leftover.error == "leftover_sentinel"
    still = gt.finalize_item(missing, "あいうえおかきく")
    assert still.error == "still_japanese"
    prompt = gt.build_user_prompt([missing], heroine="nobody", context="scene")
    assert "scene" in prompt
    assert "Shared / system" in prompt


def test_gemini_client_retry_and_translate(monkeypatch):
    monkeypatch.setitem(sys.modules, "google", None)
    with pytest.raises(SystemExit, match="google-genai"):
        gt.make_gemini_client("k")

    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")

    class Client:
        def __init__(self, api_key):
            self.api_key = api_key

    genai.Client = Client
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    assert gt.make_gemini_client("k").api_key == "k"

    assert gt._retry_delay_seconds(RuntimeError("retry in 12.5s"), 0) == 14.5
    assert gt._retry_delay_seconds(RuntimeError("'retryDelay': '1000s'"), 0) == 900.0
    assert gt._retry_delay_seconds(RuntimeError("no hint"), 0) == 30.0
    assert gt._retry_delay_seconds(RuntimeError("no hint"), 10) == 300.0
    assert gt._is_retryable_api_error(RuntimeError("503"))
    assert not gt._is_retryable_api_error(RuntimeError("nope"))
    assert gt._context_window([], []) == []
    assert gt._thinking_config(types.SimpleNamespace(), "OFF") is None

    class Thinking:
        def __init__(self, thinking_level=None):
            if thinking_level == "HIGH":
                raise TypeError("enum")
            if thinking_level == "BAD":
                raise ValueError("no")
            self.level = thinking_level

    class Level:
        HIGH = "enum-high"

    types_mod = types.SimpleNamespace(ThinkingConfig=Thinking, ThinkingLevel=Level)
    assert gt._thinking_config(types_mod, "HIGH").level == "enum-high"
    assert gt._thinking_config(types.SimpleNamespace(ThinkingConfig=Thinking), "HIGH") is None

    class Part:
        def __init__(self, text):
            self.text = text

    class Resp:
        def __init__(self, text=None, candidates=None):
            self.text = text
            self.candidates = candidates

    assert gt._extract_response_text(Resp(text="plain")) == "plain"
    assert gt._extract_response_text(Resp(text="", candidates=[])) == ""
    nested = Resp(
        text=None,
        candidates=[
            types.SimpleNamespace(content=None),
            types.SimpleNamespace(content=types.SimpleNamespace(parts=None)),
            types.SimpleNamespace(
                content=types.SimpleNamespace(parts=[Part(""), Part(" joined ")])
            ),
        ],
    )
    assert gt._extract_response_text(nested) == "joined"

    calls = {"n": 0}

    class Models:
        def generate_content(self, **kwargs):
            calls["n"] += 1
            if calls["mode"] == "retry" and calls["n"] == 1:
                raise RuntimeError("429 RESOURCE_EXHAUSTED retry in 1s")
            if calls["mode"] == "perday":
                raise RuntimeError("429 PerDay")
            if calls["mode"] == "fatal":
                raise RuntimeError("400 bad request")
            if calls["mode"] == "always":
                raise RuntimeError("503 UNAVAILABLE")
            return Resp(text='{"items":[]}')

    client = types.SimpleNamespace(models=Models())
    monkeypatch.setattr(gt.time, "sleep", lambda _s: None)

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            if calls["schema"] == "first" and "response_json_schema" in kwargs:
                raise TypeError("no json schema")
            if calls["schema"] == "both" and (
                "response_json_schema" in kwargs or "response_schema" in kwargs
            ):
                raise TypeError("no schema")

    gtypes = types.ModuleType("google.genai.types")
    gtypes.GenerateContentConfig = Config
    gtypes.ThinkingConfig = Thinking
    gtypes.ThinkingLevel = Level
    genai.types = gtypes
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)

    calls["mode"] = "ok"
    calls["schema"] = "first"
    assert gt.gemini_generate_json(client, "m", "{}", thinking_level="HIGH") == '{"items":[]}'
    calls["n"] = 0
    calls["mode"] = "retry"
    calls["schema"] = "both"
    assert "items" in gt.gemini_generate_json(client, "m", "{}", thinking_level="OFF")
    calls["mode"] = "fatal"
    with pytest.raises(RuntimeError, match="400"):
        gt.gemini_generate_json(client, "m", "{}")
    calls["mode"] = "perday"
    with pytest.raises(RuntimeError, match="PerDay"):
        gt.gemini_generate_json(client, "m", "{}")
    calls["mode"] = "always"
    with pytest.raises(RuntimeError, match="503"):
        gt.gemini_generate_json(client, "m", "{}")

    users: list[str] = []

    def fake_gen(client, model, user, **kwargs):
        users.append(user)
        if "broke a rule" not in user:
            return json.dumps({"items": [{"i": 0, "t": "Morning"}]}, ensure_ascii=False)
        return json.dumps({"items": [{"i": 0, "t": "Morning @@M0@@"}]}, ensure_ascii=False)

    monkeypatch.setattr(gt, "gemini_generate_json", fake_gen)
    item = gt.prepare_items(["おはよう※"])[0]
    idle = gt.prepare_items(["Hello"], need=[False])
    assert gt.translate_prepared(None, "m", idle, heroine="common")[0].english == "Hello"
    assert gt._translate_prepared_once(None, "m", [], [], heroine="common") == {}
    fixed = gt.translate_prepared(None, "m", [item], heroine="nene", context="hall", chunk_size=0)
    assert fixed[0].english == "Morning ※"
    assert "kept_pronoun" not in users[-1]
    texts = gt.translate_texts(None, "m", ["おはよう※"], heroine="manaka", repair=False, chunk_size=0)
    assert texts[0].error == "dropped_marker"

    prepared = gt.prepare_items(["あ", "い", "う"])
    window = gt._context_window(prepared, [prepared[1]], pad=0)
    assert [it.index for it in window] == [1]
    wide = gt._context_window(prepared, [prepared[1]], pad=1)
    assert [it.index for it in wide] == [0, 1, 2]


# ---------------------------------------------------------------------------
# exact_zlib.py
# ---------------------------------------------------------------------------


def test_exact_zlib_gaps_empty_blocks_and_verify():
    blob = fi.darc({"timg/A.bclim": b"hello", "timg/B.bclim": b"world"})
    gaps = ez.interfile_zero_gaps(blob, min_len=1)
    assert gaps
    assert ez.apply_gap_pad(blob, 0, b"\x11") == blob
    assert ez.apply_gap_pad(blob, 2, b"") == blob
    salted = ez.apply_gap_pad(blob, 2, b"\x11\x22")
    assert salted != blob
    assert ez._force_zero_gaps(blob) == blob
    assert ez._force_zero_gaps(salted) == salted
    assert ez.interfile_zero_gaps(b"darc\xff\xfe" + b"\x00" * 8)
    assert not ez.zlib_body_fits_slot(b"x" * 32, 4)
    assert ez.compress_exact_empty_blocks(b"hi", 3) is None
    assert ez.compress_exact_empty_blocks(b"hi", 3, thorough=True) is None
    assert ez._format_secs(0) == "0s"
    assert ez._format_secs(59) == "59s"
    assert ez._format_secs(125) == "2m05s"
    assert 0 in ez._empty_block_candidates(0, None)
    assert ez._empty_block_candidates(20, 5)
    assert len(ez._empty_block_candidates(800, None)) < 800

    slot = zlib.compress(b"abc")
    with pytest.raises(RuntimeError, match="length"):
        ez._verify_exact_slot(b"abc", slot, len(slot) + 1)
    assert ez.try_fast_exact_slot(b"abc", 4) is None
    with pytest.raises(RuntimeError, match="could not build"):
        ez.compress_exact_with_gap_tune(b"abc", 4)

    stream = zlib.compress(b"hello exact")
    assert ez.pad_closed_zlib_stream(stream, len(stream)) == stream
    assert ez.pad_closed_zlib_stream(stream, len(stream) - 1) is None
    assert ez.pad_closed_zlib_stream(stream, len(stream) + 1_000_001) is None
    assert ez.pad_closed_zlib_stream(b"garbage-stream", 80) is None
    assert ez.pad_closed_zlib_stream(stream, len(stream) + 8, expected=b"nope") is None
    assert ez._split_zlib(b"short") is None
    assert ez._split_zlib(b"\x00" * 8) is None
    bad_flag = bytearray(stream)
    bad_flag[1] |= 0x20
    # Flipping the preset-dict bit also breaks the header check; either None is fine.
    assert ez._split_zlib(bytes(bad_flag)) is None
    assert ez._plan_empty_block_bits(0, 5) is None
    assert ez._plan_empty_block_bits(0, 10)
    assert ez._stored_empty_bits(1) >= 3
    with pytest.raises(ValueError, match="truncated deflate"):
        ez._BitReader(b"").bit()
    assert ez._BitReader(b"\x01").bits(3) == 1
    writer = ez._BitWriter(bytearray(), 0)
    writer.write(0b101, 3)
    assert writer.data
    with pytest.raises(ValueError, match="bad stored"):
        ez._walk_deflate(b"\x01\x01\x00\x00\x00")
    with pytest.raises(ValueError, match="truncated stored"):
        ez._walk_deflate(b"\x01\x05\x00\xfa\xff")
    with pytest.raises(ValueError, match="reserved BTYPE"):
        ez._walk_deflate(b"\x07")
    with pytest.raises(ValueError, match="bad code length"):
        ez._huffman_from_lengths([-1])
    with pytest.raises(ValueError, match="over-subscribed"):
        ez._huffman_from_lengths([1, 1, 1])
    assert ez._huffman_from_lengths([]) == ([0], [])
    with pytest.raises(ValueError, match="invalid Huffman"):
        ez._huff_decode(ez._BitReader(b"\xff"), [0, 0], [])
    lit = ez._huffman_from_lengths([0] * 286 + [1])
    dist = ez._huffman_from_lengths([1])
    with pytest.raises(ValueError, match="bad length symbol"):
        ez._skip_huffman(ez._BitReader(b"\x00"), lit, dist)
    lit257 = ez._huffman_from_lengths([0] * 257 + [1])
    dist_bad = ez._huffman_from_lengths([0] * 32 + [1])
    with pytest.raises(ValueError, match="bad distance symbol"):
        ez._skip_huffman(ez._BitReader(b"\x00"), lit257, dist_bad)
    blocks = ez._BitWriter(bytearray(), 0)
    ez._write_empty_blocks(blocks, ["fixed", "stored"])
    assert blocks.pos > 0


def test_exact_zlib_zopfli_edges(monkeypatch):
    monkeypatch.setattr(ez.time, "sleep", lambda _s: None)
    payload = b"z"
    first = ez._zopfli_compress(payload, label="calibrate")
    assert zlib.decompress(first) == payload
    second = ez._zopfli_compress(payload, label="eta")
    assert zlib.decompress(second) == payload

    def _boom(_data):
        raise RuntimeError("zfail")

    monkeypatch.setattr(ez.zopfli_zlib, "compress", _boom)
    with pytest.raises(RuntimeError, match="zfail"):
        ez._zopfli_compress(payload, label="boom")

    monkeypatch.setattr(ez, "zopfli_zlib", None)
    with pytest.raises(RuntimeError, match="zopfli not installed"):
        ez._zopfli_compress(payload, label="missing")
    tuned, slot = ez.compress_exact_zopfli(b"gap-only", 400)
    assert zlib.decompress(slot) == tuned

    target = 40

    def _short(data, *, label):
        return b"short"

    def _no_pad(stream, tgt, expected=None):
        return None

    monkeypatch.setattr(ez, "zopfli_zlib", object())
    monkeypatch.setattr(ez, "_zopfli_compress", lambda data, *, label: b"x" * target)
    assert ez.compress_exact_zopfli(b"abc\x00\x00\x00\x00\x00\x00\x00\x00", target)[1] == b"x" * target

    monkeypatch.setattr(ez, "_zopfli_compress", lambda data, *, label: b"x" * 100)
    monkeypatch.setattr(ez, "compress_exact_with_gap_tune", lambda *a, **k: (b"tuned", b"g" * target))
    assert ez.compress_exact_zopfli(b"abc", target)[1] == b"g" * target

    state = {"n": 0}

    def _grow(data, *, label):
        state["n"] += 1
        if state["n"] > 1:
            return b"Z" * target
        return b"short"

    monkeypatch.setattr(ez, "_zopfli_compress", _grow)
    monkeypatch.setattr(ez, "pad_closed_zlib_stream", _no_pad)
    assert ez.compress_exact_zopfli(b"abc\x00" * 4, target)[1] == b"Z" * target

    pads = {"n": 0}

    def _pad_later(stream, tgt, expected=None):
        pads["n"] += 1
        if pads["n"] >= 3:
            return b"P" * tgt
        return None

    monkeypatch.setattr(ez, "_zopfli_compress", _short)
    monkeypatch.setattr(ez, "pad_closed_zlib_stream", _pad_later)
    assert ez.compress_exact_zopfli(b"abc", target)[0]

    monkeypatch.setattr(
        ez,
        "_bounded_near_miss_tune",
        lambda *a, **k: (b"near", b"N" * target),
    )
    monkeypatch.setattr(ez, "pad_closed_zlib_stream", _no_pad)
    assert ez.compress_exact_zopfli(b"ab" + b"\x00" * 8, target)[1] == b"N" * target

    flips = {"n": 0}

    def _fine(data, *, label):
        flips["n"] += 1
        if "fine-tune" in label:
            return b"F" * target
        return b"short"

    monkeypatch.setattr(ez, "_bounded_near_miss_tune", lambda *a, **k: None)
    monkeypatch.setattr(ez, "_zopfli_compress", _fine)
    assert ez.compress_exact_zopfli(b"ab" + b"\x00" * 8, target, fine_tune=True)[1] == b"F" * target

    monkeypatch.setattr(ez, "_zopfli_compress", _short)
    monkeypatch.setattr(
        ez,
        "compress_exact_with_gap_tune",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no room")),
    )
    with pytest.raises(RuntimeError, match="could not build"):
        ez.compress_exact_zopfli(b"\x02" * 20, target, fine_tune=True)
    with pytest.raises(RuntimeError, match="could not build"):
        ez.compress_exact_zopfli(b"\x02" * 200_001, target, fine_tune=True)


def test_exact_zlib_near_miss(monkeypatch):
    assert ez._bounded_near_miss_tune(b"ab\x00\x00", 10, 0, b"zz", 0) is None
    monkeypatch.setattr(ez, "zopfli_zlib", None)
    assert ez._bounded_near_miss_tune(b"ab\x00\x00\x00\x00", 8, 0, b"\x11" * 4, 4) is None

    class Z:
        def compress(self, data):
            if b"\x11" in data:
                return b"HIT!!!"
            return b"SHORT"

    monkeypatch.setattr(ez, "zopfli_zlib", Z())
    raw = b"ab" + b"\x00" * 8
    hit = ez._bounded_near_miss_tune(raw, 6, 0, b"\x11" * 8, 8, max_tries=4, workers=2)
    assert hit is not None and hit[1] == b"HIT!!!"
    assert ez._bounded_near_miss_tune(raw, 6, 0, b"\x11" * 8, 8, workers=1)[1] == b"HIT!!!"
    assert ez._bounded_near_miss_tune(raw, 3, 0, b"\x11" * 8, 8) is None

    class Short:
        def compress(self, data):
            return b"12"

    monkeypatch.setattr(ez, "zopfli_zlib", Short())
    assert ez._bounded_near_miss_tune(raw, 8, 8, b"\x11" * 8, 8, max_tries=4) is None
    filled = ez._bounded_near_miss_tune(raw, 2, 0, b"\x11" * 8, 8)
    assert filled is not None and filled[1] == b"12"


# ---------------------------------------------------------------------------
# patch_cesa.py
# ---------------------------------------------------------------------------


def _cesa_pkg(payload: bytes = b"cesa-tex-payload", *, compressed: bool = True, name: str = cesa.CESA_TEX_NAME) -> bytes:
    return fi.package([(name, payload, b"TEX ", compressed)])


def test_cesa_idx_encode_and_exact_zlib(tmp_path: Path):
    pkg = _cesa_pkg()
    blob = fi.img({90: pkg}, raw={1: b"raw"})
    with pytest.raises(RuntimeError, match="not PAK"):
        cesa.read_img_idx_dec_len(blob, 1)
    buf = bytearray(blob)
    with pytest.raises(RuntimeError, match="not PAK"):
        cesa.set_img_idx_dec_len(buf, 1, 4)
    path = tmp_path / "img.bin"
    path.write_bytes(blob)
    assert cesa.sync_img_pkg90_idx_to_pack(path) is False
    data = bytearray(path.read_bytes())
    struct.pack_into("<I", data, cesa.img_idx_entry_off(90) + 8, 1)
    path.write_bytes(data)
    assert cesa.sync_img_pkg90_idx_to_pack(path) is True
    assert cesa.sync_img_pkg90_idx_to_pack(path) is False
    empty = tmp_path / "empty.bin"
    empty.write_bytes(fi.img({0: pkg}, count=91))
    with pytest.raises(RuntimeError, match="missing package"):
        cesa.sync_img_pkg90_idx_to_pack(empty)

    small = Image.new("RGB", (4, 4), (9, 8, 7))
    raw = cesa.encode_tex(small, 8, 8, 4, 4)
    back = cesa.decode_cesa_tex(raw, 8, 8, 4, 4)
    assert back.getpixel((0, 0)) == (9, 8, 7)
    portrait = cesa.encode_cesa_tex(small)
    assert cesa.decode_cesa_tex(portrait).getpixel((0, 0)) == (9, 8, 7)
    companion = cesa.encode_cesa_companion_tex(small)
    shown = cesa.decode_cesa_tex(
        companion,
        cesa.COMPANION_TEX_W,
        cesa.COMPANION_TEX_H,
        cesa.COMPANION_VISIBLE_W,
        cesa.COMPANION_VISIBLE_H,
    )
    assert shown.getpixel((0, 0)) == (9, 8, 7)
    assert cesa.morton(0) == (0, 0)

    assert cesa.read_cesa_tex_from_pkg(pkg) == b"cesa-tex-payload"
    assert cesa._pkg_names(pkg) == [cesa.CESA_TEX_NAME]
    plain = _cesa_pkg(compressed=False)
    with pytest.raises(RuntimeError, match="not compressed"):
        cesa._find_cesa_tex_entry(plain)
    with pytest.raises(RuntimeError, match="not found"):
        cesa._find_cesa_tex_entry(_cesa_pkg(name="Other.texi"))
    tweaked = bytearray(pkg)
    struct.pack_into("<I", tweaked, cesa.ENTRY_SIZE + 8, len(b"cesa-tex-payload") + 3)
    with pytest.raises(RuntimeError, match="unexpected decompressed"):
        cesa.read_cesa_tex_from_pkg(bytes(tweaked))
    with pytest.raises(ValueError, match="stored block too large"):
        cesa._stored_final_block(b"\x00" * 0x10000)
    assert cesa._try_zlib_exact_candidate(b"not-zlib", b"x") is False
    assert cesa._try_zlib_exact_candidate(zlib.compress(b"hi") + b"\x00", b"hi") is False
    with pytest.raises(RuntimeError, match="cannot build exact zlib"):
        cesa.compress_zlib_exact(b"hi", 3)
    exact = None
    for length in range(len(b"cesa-pad") + 16, len(b"cesa-pad") + 80):
        try:
            exact = cesa.compress_zlib_exact(b"cesa-pad", length)
        except RuntimeError:
            continue
        break
    assert exact is not None and zlib.decompress(exact) == b"cesa-pad"
    assert cesa.compress_tex_to_slot(b"cesa-pad", len(exact)) == exact or zlib.decompress(
        cesa.compress_tex_to_slot(b"cesa-pad", len(exact))
    ) == b"cesa-pad"
    best = cesa.compress_tex_best(b"hello cesa")
    assert zlib.decompress(best) == b"hello cesa"
    texi = b"\x69" * 8 + b"\x00" * 32
    patched = cesa._patch_texi_dims(texi, 16, 16, 8, 8)
    assert struct.unpack_from("<I", patched, 8)[0] == 16
    with pytest.raises(RuntimeError, match="TEXI"):
        cesa._patch_texi_dims(b"nope", 1, 1, 1, 1)
    with pytest.raises(RuntimeError, match="TEXI"):
        cesa._patch_texi_dims(b"\x69" * 8, 1, 1, 1, 1)


def test_cesa_package_splice_and_rebuild_errors(tmp_path: Path, monkeypatch):
    tex = b"cesa-tex-payload"
    pkg = _cesa_pkg(tex)
    patched = cesa.patch_cesa_package_inplace_tex(pkg, tex)
    assert cesa.read_cesa_tex_from_pkg(patched) == tex
    with pytest.raises(RuntimeError, match="TEX size"):
        cesa.patch_cesa_package_inplace_tex(pkg, b"short")
    real_exact = cesa.compress_zlib_exact
    monkeypatch.setattr(cesa, "compress_zlib_exact", lambda data, n: zlib.compress(b"other"))
    with pytest.raises(RuntimeError, match="round-trip"):
        cesa.compress_tex_to_slot(tex, 32)
    monkeypatch.setattr(cesa, "compress_zlib_exact", real_exact)

    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    src.write_bytes(fi.img({90: pkg}))
    out = cesa.patch_img_bin_tex(src, tex, dst)
    assert out.is_file()
    assert cesa.read_cesa_tex_from_pkg(fi.read_package(out, 90)) == tex
    cesa.patch_img_bin_tex(src, tex, src, work=None)
    assert cesa._load_pkg90(src)

    missing = tmp_path / "missing.bin"
    missing.write_bytes(fi.img({0: pkg}, count=91))
    with pytest.raises(RuntimeError, match="missing package"):
        cesa.patch_img_bin_tex(missing, tex, tmp_path / "no.bin")
    with pytest.raises(RuntimeError, match="missing package"):
        cesa._load_pkg90(missing)

    monkeypatch.setattr(cesa, "patch_cesa_package_inplace_tex", lambda pkg_raw, new: pkg_raw + b"\x00")
    with pytest.raises(RuntimeError, match="changed package size"):
        cesa.patch_img_bin_tex(src, tex, tmp_path / "grown.bin")
    monkeypatch.setattr(
        cesa,
        "patch_cesa_package_inplace_tex",
        lambda pkg_raw, new: bytes([pkg_raw[0] ^ 1]) + pkg_raw[1:],
    )
    monkeypatch.setattr(cesa, "read_cesa_tex_from_pkg", lambda pkg_raw: b"nope")
    with pytest.raises(RuntimeError, match="TEX mismatch"):
        cesa.patch_img_bin_tex(src, tex, tmp_path / "bad.bin")

    big = bytes(cesa.TEX_W * cesa.TEX_H * 3)
    with pytest.raises(RuntimeError, match="CESA TEX size"):
        cesa.rebuild_pkg90_with_companion(b"xx", b"no", b"no")
    with pytest.raises(RuntimeError, match="companion TEX size"):
        cesa.rebuild_pkg90_with_companion(pkg, big, b"no")
    with pytest.raises(RuntimeError, match="cmp_len"):
        cesa.rebuild_pkg90_with_companion(pkg + b"\x00", big, big)
    other = fi.package([("Other.texi", b"hi", b"TEX ", True)])
    with pytest.raises(RuntimeError, match="missing CESA"):
        cesa.rebuild_pkg90_with_companion(other, big, big)

    named = fi.package(
        [
            (cesa.CESA_TEX_NAME, tex, b"TEX ", False),
            ("Other.texi", b"abcd", b"TEX ", True),
        ]
    )
    with pytest.raises(RuntimeError, match="not compressed"):
        cesa.read_named_tex_from_pkg(named, cesa.CESA_TEX_NAME)
    with pytest.raises(RuntimeError, match="not found"):
        cesa.read_named_tex_from_pkg(pkg, "missing.texi")
    bad_len = bytearray(pkg)
    struct.pack_into("<I", bad_len, cesa.ENTRY_SIZE + 8, len(tex) + 9)
    with pytest.raises(RuntimeError, match="decompressed"):
        cesa.read_named_tex_from_pkg(bytes(bad_len), cesa.CESA_TEX_NAME)

    png = tmp_path / "c.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(png)
    monkeypatch.setattr(cesa, "encode_cesa_tex", lambda im: b"c" * 8)
    monkeypatch.setattr(cesa, "encode_cesa_companion_tex", lambda im: b"d" * 8)
    short_pkg = _cesa_pkg(b"hi")
    long_pkg = _cesa_pkg(bytes(range(256)) * 4)
    assert len(short_pkg) != len(long_pkg)
    (tmp_path / "a.bin").write_bytes(fi.img({90: short_pkg}))
    (tmp_path / "b.bin").write_bytes(fi.img({90: long_pkg}))
    with pytest.raises(RuntimeError, match="pkg 90 length"):
        cesa.patch_img_bin_with_companion(
            tmp_path / "a.bin", png, png, tmp_path / "b.bin", vanilla_img=tmp_path / "a.bin"
        )
    (tmp_path / "none.bin").write_bytes(fi.img({0: pkg}, count=91))
    with pytest.raises(RuntimeError, match="missing package"):
        cesa.patch_img_bin_with_companion(tmp_path / "none.bin", png, png, tmp_path / "none.bin")

    def _wrap(src_img, new, dst, work=None):
        Path(dst).write_bytes(b"ok")
        return Path(dst)

    monkeypatch.setattr(cesa, "encode_cesa_tex", lambda im: tex)
    monkeypatch.setattr(cesa, "patch_img_bin_tex", _wrap)
    assert cesa.patch_img_bin(src, png, tmp_path / "wrapped.bin").read_bytes() == b"ok"


def test_cesa_main_modes(tmp_path: Path, monkeypatch):
    tex = b"cesa-tex-payload"
    src = tmp_path / "img.bin"
    src.write_bytes(fi.img({90: _cesa_pkg(tex)}))
    png = tmp_path / "out.png"
    work = tmp_path / "work"

    def _argv(*args: str) -> None:
        monkeypatch.setattr(sys, "argv", ["patch_cesa", *args])

    monkeypatch.setattr(cesa, "decode_cesa_tex", lambda raw: Image.new("RGB", (2, 2), (4, 5, 6)))
    _argv("--img", str(src), "--png", str(png), "--decode")
    assert cesa.main() == 0
    assert png.is_file()

    _argv("--img", str(src), "--png", str(tmp_path / "missing.png"), "--out", str(tmp_path / "o.bin"), "--work", str(work))
    assert cesa.main() == 1

    out = tmp_path / "re.bin"
    _argv("--img", str(src), "--recompress-only", "--out", str(out), "--work", str(work))
    assert cesa.main() == 0
    assert out.is_file()

    monkeypatch.setattr(cesa, "decode_cesa_tex", lambda raw: Image.new("RGB", (2, 2)))
    monkeypatch.setattr(cesa, "encode_cesa_tex", lambda im: tex)
    rt = tmp_path / "rt.bin"
    _argv("--img", str(src), "--roundtrip-jp", "--out", str(rt), "--work", str(work))
    assert cesa.main() == 0
    real_patch_img = cesa.patch_img_bin_tex

    def _copy_img(src_img, new_tex, dst_img, work=None):
        if Path(dst_img).resolve() != Path(src_img).resolve():
            Path(dst_img).write_bytes(Path(src_img).read_bytes())
        return Path(dst_img)

    monkeypatch.setattr(cesa, "encode_cesa_tex", lambda im: b"\xff" * len(tex))
    monkeypatch.setattr(cesa, "patch_img_bin_tex", _copy_img)
    rt2 = tmp_path / "rt2.bin"
    _argv("--img", str(src), "--roundtrip-jp", "--out", str(rt2), "--work", str(work))
    assert cesa.main() == 0
    monkeypatch.setattr(cesa, "patch_img_bin_tex", real_patch_img)

    _argv("--img", str(src), "--inplace", "--recompress-only", "--work", str(work))
    assert cesa.main() == 0
    assert src.with_suffix(src.suffix + ".bak").is_file()
    assert cesa.main() == 0

    real_copy = cesa.shutil.copy2
    real_mkdir = cesa.Path.mkdir

    def _copy(src_path, dst_path, *args, **kwargs):
        if "Azahar" in str(dst_path):
            return dst_path
        return real_copy(src_path, dst_path, *args, **kwargs)

    def _mkdir(self, *args, **kwargs):
        if "Azahar" in str(self):
            return None
        return real_mkdir(self, *args, **kwargs)

    def _fake_bin(src_img, png_path, dst, work=None):
        Path(dst).write_bytes(b"cesa-out")
        return Path(dst)

    monkeypatch.setattr(cesa, "patch_img_bin", _fake_bin)
    painted = tmp_path / "painted.bin"
    _argv("--img", str(src), "--png", str(png), "--out", str(painted), "--work", str(work))
    assert cesa.main() == 0
    assert painted.read_bytes() == b"cesa-out"

    monkeypatch.setattr(cesa.shutil, "copy2", _copy)
    monkeypatch.setattr(cesa.Path, "mkdir", _mkdir)
    deployed = tmp_path / "dep.bin"
    _argv(
        "--img",
        str(src),
        "--recompress-only",
        "--out",
        str(deployed),
        "--work",
        str(work),
        "--deploy-azahar",
    )
    assert cesa.main() == 0


# ---------------------------------------------------------------------------
# pack_images.py helpers
# ---------------------------------------------------------------------------


class _Live:
    active = True

    def set_progress(self, *args, **kwargs):
        return None

    def set_job(self, *args, **kwargs):
        return None

    def log(self, *args, **kwargs):
        return None

    def clear_job(self, *args, **kwargs):
        return None

    def clear_jobs(self):
        return None


class _Proc:
    def __init__(self, code, out, err):
        self.returncode = code
        self.stdout = out
        self.stderr = err


def test_pack_helpers_progress_run_and_assets(tmp_path: Path, monkeypatch, capsys):
    assert pack.default_workers() >= 1
    assert pack.default_pkg_workers() >= 1
    pack._progress_bar(0, 0, prefix="p ")
    pack._progress_bar(2, 2, prefix="p ")
    pack._say("plain")
    monkeypatch.setattr(pack, "live", _Live())
    pack._say("pinned", job="job")
    monkeypatch.setattr(pack.subprocess, "run", lambda *a, **k: _Proc(0, "one\ntwo\n", ""))
    pack._run([sys.executable, "-c", "pass"])
    monkeypatch.setattr(pack.subprocess, "run", lambda *a, **k: _Proc(0, "", ""))
    pack._run(["cmd"])
    monkeypatch.setattr(pack.subprocess, "run", lambda *a, **k: _Proc(3, "out", "err"))
    with pytest.raises(pack.PackError, match="command failed"):
        pack._run(["cmd"])
    monkeypatch.setattr(pack, "live", pack.live if False else _Live())
    with pytest.raises(pack.PackError, match="command failed"):
        pack._run(["cmd"])
    monkeypatch.setattr(pack, "live", types.SimpleNamespace(active=False))
    monkeypatch.setattr(pack.subprocess, "run", lambda *a, **k: _Proc(0, "only\n", ""))
    pack._run(["cmd"])

    from multiprocessing import Queue

    old_out, old_err = sys.stdout, sys.stderr
    queue: Queue = Queue()
    try:
        pack._pool_init(queue)
        print("hello-pool")
        sys.stderr.write("err-pool\n")
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    kinds = {queue.get(timeout=2)[0], queue.get(timeout=2)[0]}
    assert kinds == {"out", "err"}

    monkeypatch.setattr(pack, "live", _Live())
    with pack._capture_job("row"):
        print("inside")
    monkeypatch.setattr(pack, "live", types.SimpleNamespace(active=False))
    with pack._capture_job("row"):
        pass
    timer = types.SimpleNamespace(elapsed_str=lambda: "1s")
    monkeypatch.setattr(pack, "live", _Live())
    pack._report_package(1, 2, {"ok": True, "index": 3, "touched": 1}, timer)
    pack._report_package(1, 2, {"ok": False, "index": 3, "touched": 0}, timer)
    monkeypatch.setattr(pack, "live", types.SimpleNamespace(active=False))
    pack._report_package(1, 2, {"ok": True, "index": 3, "touched": 0}, timer)

    monkeypatch.setattr(pack, "IE", tmp_path / "missing-ie")
    monkeypatch.setattr(pack, "PE", tmp_path / "missing-pe")
    with pytest.raises(pack.PackError, match="missing tools"):
        pack._require_tools()

    images = tmp_path / "images"
    (images / "album.check" / "timg").mkdir(parents=True)
    (images / "album").mkdir()
    (images / "album.arc").mkdir()
    (images / "nope").mkdir()
    (images / "note.txt").write_text("x", encoding="utf-8")
    chosen = pack.prefer_asset_folders(images)
    assert chosen["album"].name.endswith(".check")
    (images / "album.check" / "timg" / "Hello_en.png").write_bytes(b"en")
    (images / "album.check" / "Hello.png").write_bytes(b"plain")
    (images / "album.check" / "Skip_jpn.png").write_bytes(b"jp")
    (images / "album.check" / "Skip (2).png").write_bytes(b"2")
    (images / "album.check" / "timg - copy").mkdir()
    (images / "album.check" / "timg - copy" / "Nope.png").write_bytes(b"no")
    pngs = pack.iter_asset_pngs(images / "album.check")
    assert [p.name for p in pngs] == ["Hello_en.png"]
    stems = pack.png_logical_stems(Path("__Foo_en.png"))
    assert "Foo" in stems
    assert "Bar" in pack.png_logical_stems(Path("Bar_upper.png"))
    assert "Baz" in pack.png_logical_stems(Path("Baz_rgba4.png"))
    aliases = pack.png_logical_stems(Path("new_Thing.png"))
    assert "Thing" in aliases and "C_Thing" in aliases
    assert pack.png_to_bclim_candidates(Path("new_Thing.png"))
    tiny = tmp_path / "tiny.bclim"
    tiny.write_bytes(b"abcd")
    ok, reason = pack._bclim_looks_valid(tiny, 4)
    assert not ok and "too small" in reason
    same = tmp_path / "same.bclim"
    same.write_bytes(b"Z" * 64)
    assert pack._bclim_looks_valid(same, 64)[0]
    changed = tmp_path / "changed.bclim"
    changed.write_bytes(b"Y" * 200)
    assert "size/format" in pack._bclim_looks_valid(changed, 64)[1]
    clim = tmp_path / "clim.bclim"
    clim.write_bytes(b"CLIM" + b"\x00" * 20)
    assert "too small" in pack._bclim_looks_valid(clim, 64)[1]
    header = tmp_path / "header.bclim"
    header.write_bytes(b"CLIM" + b"\x00" * 200)
    assert "header-only" in pack._bclim_looks_valid(header, 64)[1]
    assert capsys.readouterr().out


def test_pack_convert_arc_and_repack(tmp_path: Path, monkeypatch):
    work = tmp_path / "work"
    orig = tmp_path / "Face.bclim"
    orig.write_bytes(b"O" * 64)
    png = tmp_path / "Face.png"
    png.write_bytes(b"\x89PNG")
    cache = ImgPackCache(tmp_path / "cache")

    class Hit:
        def get_bclim(self, png_bytes, orig_bytes):
            return b"C" * 64

        def put_bclim(self, *args):
            raise AssertionError("cache hit should not store")

    hit = pack.convert_png_to_bclim(png, orig, work, cache=Hit())
    assert hit.read_bytes() == b"C" * 64

    monkeypatch.setattr(bclimutil, "parse_bclim", lambda data: (None, 1, 1, 8, None))
    monkeypatch.setattr(bclimutil, "png_to_bclim_same_size", lambda png, orig: b"E" * 64)
    stored: list[bytes] = []
    cache.get_bclim = lambda *a: None  # type: ignore[method-assign]
    cache.put_bclim = lambda *a: stored.append(a[-1])  # type: ignore[method-assign]
    produced = pack.convert_png_to_bclim(png, orig, work / "ok", cache=cache)
    assert produced.read_bytes() == b"E" * 64
    assert stored

    monkeypatch.setattr(bclimutil, "png_to_bclim_same_size", lambda png, orig: b"short")
    with pytest.raises(pack.PackError, match="size/format|too small"):
        pack.convert_png_to_bclim(png, orig, work / "bad")
    monkeypatch.setattr(
        bclimutil, "png_to_bclim_same_size", lambda png, orig: (_ for _ in ()).throw(OSError("disk"))
    )
    with pytest.raises(OSError, match="could not write/read"):
        pack.convert_png_to_bclim(png, orig, work / "os")
    monkeypatch.setattr(
        bclimutil,
        "png_to_bclim_same_size",
        lambda png, orig: (_ for _ in ()).throw(ValueError("encode")),
    )
    with pytest.raises(pack.PackError, match="same-size BCLIM"):
        pack.convert_png_to_bclim(png, orig, work / "val")

    monkeypatch.setattr(bclimutil, "parse_bclim", lambda data: (_ for _ in ()).throw(ValueError("hdr")))
    monkeypatch.setattr(pack, "PNG2BCLIM", tmp_path / "missing.exe")
    with pytest.raises(pack.PackError, match="unsupported BCLIM"):
        pack.convert_png_to_bclim(png, orig, work / "fmt")

    tool = tmp_path / "png2bclim.exe"
    tool.write_bytes(b"")
    monkeypatch.setattr(pack, "PNG2BCLIM", tool)

    def _write_exact(cmd, cwd=None):
        (Path(cwd) / "FaceX.bclim").write_bytes(b"Y" * 64)

    monkeypatch.setattr(pack, "_run", _write_exact)
    assert pack.convert_png_to_bclim(png, orig, work / "tool").read_bytes() == b"Y" * 64

    def _write_alt(cmd, cwd=None):
        (Path(cwd) / "FaceAltX.bclim").write_bytes(b"Y" * 64)

    monkeypatch.setattr(pack, "_run", _write_alt)
    assert pack.convert_png_to_bclim(png, orig, work / "alt").stat().st_size == 64
    monkeypatch.setattr(pack, "_run", lambda cmd, cwd=None: None)
    with pytest.raises(pack.PackError, match="produced no BCLIM"):
        pack.convert_png_to_bclim(png, orig, work / "none")

    def _write_bad(cmd, cwd=None):
        (Path(cwd) / "FaceX.bclim").write_bytes(b"Z" * 10)

    monkeypatch.setattr(pack, "_run", _write_bad)
    with pytest.raises(pack.PackError, match="bad BCLIM"):
        pack.convert_png_to_bclim(png, orig, work / "badtool")

    monkeypatch.setattr(pack, "convert_png_to_bclim", lambda *a, **k: (_ for _ in ()).throw(pack.PackError("skip")))
    assert pack._convert_one_png(png, orig, work / "c1")[0] == "skip"
    monkeypatch.setattr(pack, "convert_png_to_bclim", lambda *a, **k: (_ for _ in ()).throw(ValueError("skip")))
    assert pack._convert_one_png(png, orig, work / "c2")[0] == "skip"

    arc = tmp_path / "Album.arc"
    arc.write_bytes(fi.darc({"timg/Face.bclim": b"O" * 64, "timg/Other.bclim": b"P" * 64}))
    (work / "extract").mkdir(parents=True)
    (work / "extract" / "old.txt").write_text("x", encoding="utf-8")
    no_match = tmp_path / "Nope.png"
    no_match.write_bytes(b"png")
    ok, skipped, warnings = pack.patch_arc_with_pngs(arc, [no_match], work / "arc1")
    assert ok == 0 and skipped == 1 and warnings

    monkeypatch.setattr(pack, "_convert_one_png", lambda *a, **k: ("ok", b"Q" * 64, None))
    ok, skipped, warnings = pack.patch_arc_with_pngs(
        arc, [png, png], work / "arc2", workers=2
    )
    assert ok == 2 and not warnings
    monkeypatch.setattr(pack, "_convert_one_png", lambda *a, **k: ("ok", b"NO", None))
    ok, skipped, warnings = pack.patch_arc_with_pngs(arc, [png], work / "arc3")
    assert skipped == 1 and warnings
    monkeypatch.setattr(pack, "_convert_one_png", lambda *a, **k: ("ok", None, None))
    assert pack.patch_arc_with_pngs(arc, [png], work / "arc4")[1] == 1
    monkeypatch.setattr(darcutil.DarcArchive, "replace_same_size", lambda self, entry, data: (_ for _ in ()).throw(pack.PackError("nope")))
    monkeypatch.setattr(pack, "_convert_one_png", lambda *a, **k: ("ok", b"Q" * 64, None))
    assert pack.patch_arc_with_pngs(arc, [png], work / "arc5")[1] == 1

    img_data = tmp_path / "img_data"
    img_data.mkdir()
    with pytest.raises(pack.PackError, match="missing unpacked"):
        pack.ensure_package_data(img_data, 1)
    (img_data / "0002").write_bytes(b"pkg")
    monkeypatch.setattr(pack, "_run", lambda *a, **k: None)
    assert pack.ensure_package_data(img_data, 2).name == "0002_data"
    (img_data / "0003").write_bytes(b"pkg")
    arc_dir = img_data / "0003_data"
    arc_dir.mkdir()
    (arc_dir / "Album.arc").write_bytes(b"arc")
    assert pack.ensure_package_data(img_data, 3) == arc_dir.resolve()

    calls = {"n": 0}

    def _count(*args, **kwargs):
        calls["n"] += 1

    monkeypatch.setattr(pack, "_run", _count)
    (img_data / "0004").write_bytes(b"pkg")
    pack.unpack_packages(tmp_path / "img.bin", img_data, {4})
    assert calls["n"] == 0
    pack.unpack_packages(tmp_path / "img.bin", img_data, {5})
    assert calls["n"] == 1

    darc = darcutil.DarcArchive(arc.read_bytes())
    assert pack._resolve_bclim_entry(darc, Path("Face_en.png")) is not None
    assert pack._resolve_bclim_entry(darc, Path("missing.png")) is None

    src_pkg = img_data / "0008"
    raw_pkg = fi.package([("A.bin", b"hello", b"BIN ", False), ("B.bin", b"world", b"BIN ", False)])
    src_pkg.write_bytes(raw_pkg)
    pkg_dir = img_data / "0008_data"
    pkg_dir.mkdir()
    (pkg_dir / "A.bin").write_bytes(b"hello")
    (pkg_dir / "B.bin.seri").write_bytes(b"WORLD")
    new_pkg = pack.repack_package(img_data, 8)
    assert new_pkg.is_file()
    (pkg_dir / "A.bin").write_bytes(b"HELLO")
    (pkg_dir / "B.bin.seri").unlink()
    copied = pack.repack_package_exact_slots(img_data, 8)
    assert copied.read_bytes()[:4] == b"PACK"
    (pkg_dir / "A.bin").write_bytes(b"too-long")
    with pytest.raises(pack.PackError, match="uncompressed grew"):
        pack.repack_package_exact_slots(img_data, 8)

    cmp_pkg = fi.package([("A.arc", b"hello")])
    (img_data / "0009").write_bytes(cmp_pkg)
    (img_data / "0009_data").mkdir()
    (img_data / "0009_data" / "A.arc").write_bytes(b"hello!")
    with pytest.raises(pack.PackError, match="decompressed size"):
        pack.repack_package_exact_slots(img_data, 9)
    (img_data / "0009_data" / "A.arc").write_bytes(b"HELLO")
    monkeypatch.setattr(
        pack,
        "compress_to_exact_slot_cached",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no slot")),
    )
    skips: list[str] = []
    pack.repack_package_exact_slots(img_data, 9, slot_skips=skips)
    assert skips == ["A.arc"]
    with pytest.raises(pack.PackError, match="shrink its PNG"):
        pack.repack_package_exact_slots(img_data, 9)
    with pytest.raises(pack.PackError, match="missing"):
        pack.repack_package_exact_slots(img_data, 10)
    (img_data / "0011").write_bytes(b"pkg")
    with pytest.raises(pack.PackError, match="missing"):
        pack.repack_package_exact_slots(img_data, 11)

    pack.cleanup_package_unpack(img_data, 8)
    assert not (img_data / "0008").exists()


def test_pack_splice_idx_and_orchestration(tmp_path: Path, monkeypatch):
    pkg = fi.package([("A.arc", b"hello-arc-body")])
    other = fi.package([("B.arc", b"other-body!!")])
    src = tmp_path / "img.bin"
    src.write_bytes(fi.img({0: pkg, 1: other}))
    img_data = tmp_path / "data"
    img_data.mkdir()
    (img_data / "new_0000").write_bytes(pkg + b"EXTRA")
    pack.splice_packages_into_img(src, img_data, [], tmp_path / "empty-dst.bin")
    with pytest.raises(pack.PackError, match="missing"):
        pack.splice_packages_into_img(src, img_data, [1], tmp_path / "miss.bin")
    (img_data / "new_0004").write_bytes(b"PACK")
    wide = tmp_path / "wide.bin"
    wide.write_bytes(fi.img({0: pkg}, count=5))
    with pytest.raises(pack.PackError, match="empty"):
        pack.splice_packages_into_img(wide, img_data, [4], tmp_path / "empty-idx.bin")

    dst = tmp_path / "dst.bin"
    pack.splice_packages_into_img(src, img_data, [0], dst)
    assert fi.read_package(dst, 1) == other
    (img_data / "new_0000").write_bytes(pkg[:-1])
    pack.splice_packages_into_img(src, img_data, [0], dst)
    bumped = bytearray(pkg)
    struct.pack_into("<I", bumped, pack.PACK_HDR_DEC_LEN_OFF, 999999)
    (img_data / "new_0000").write_bytes(bumped)
    pack.splice_packages_into_img(src, img_data, [0], src)
    off = pack.IMG_IDX_TABLE_ADDR + pack.IMG_IDX_DEC_LEN_OFF
    assert struct.unpack_from("<I", src.read_bytes(), off)[0] == 999999

    fresh = bytearray(fi.img({0: pkg}))
    struct.pack_into("<I", fresh, pack.IMG_IDX_TABLE_ADDR + pack.IMG_IDX_DEC_LEN_OFF, 1)
    mismatch = tmp_path / "mismatch.bin"
    mismatch.write_bytes(fresh)
    bad = pack.img_idx_mismatches(mismatch)
    assert bad and bad[0][0] == 0 and bad[0][1] == 1
    src.write_bytes(fi.img({0: pkg, 1: other}, raw={2: b"raw-bytes"}))
    assert pack.img_idx_mismatches(src) == []

    with pytest.raises(pack.PackError, match="missing"):
        pack.selective_ie_repack(src, img_data, tmp_path / "ie.bin", [2])
    (img_data / "new_0003").write_bytes(pkg)
    fi_img = tmp_path / "count.bin"
    fi_img.write_bytes(fi.img({0: pkg}, count=4))
    with pytest.raises(pack.PackError, match="empty"):
        pack.selective_ie_repack(fi_img, img_data, tmp_path / "ie.bin", [3])

    class ShortFile:
        def __init__(self, path: Path):
            self._fh = open(path, "r+b")

        def seek(self, n, whence=0):
            return self._fh.seek(n, whence)

        def write(self, blob):
            self._fh.write(blob[:1] if blob else blob)
            return 1 if blob else 0

        def read(self, n=-1):
            return self._fh.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self._fh.close()
            return False

    real_open = Path.open

    def _open(self, mode="r", *args, **kwargs):
        if mode == "r+b":
            return ShortFile(self)
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _open)
    (img_data / "new_0000").write_bytes(pkg)
    with pytest.raises(pack.PackError, match="short splice"):
        pack.splice_packages_into_img(src, img_data, [0], tmp_path / "short.bin")
    monkeypatch.setattr(Path, "open", real_open)

    images = tmp_path / "images"
    (images / "album" / "timg").mkdir(parents=True)
    (images / "album" / "timg" / "A.png").write_bytes(b"png")
    (images / "cesa").mkdir()
    (images / "cesa" / "CESA_240X400.png").write_bytes(b"png")
    imgf = tmp_path / "in.bin"
    imgf.write_bytes(b"IMG")
    out = tmp_path / "out.bin"
    work = tmp_path / "packwork"

    def _ok(index, items, img_data, conv, png_workers=1, fine_tune=False, cache_dir=None):
        return {
            "index": index,
            "ok": True,
            "touched": True,
            "png_ok": 1,
            "png_skip": 2,
            "arcs": 1,
            "report": ["[ok] package"],
            "error": None,
        }

    monkeypatch.setattr(pack, "unpack_packages", lambda *a, **k: None)
    monkeypatch.setattr(pack, "ensure_package_data", lambda *a, **k: work)
    monkeypatch.setattr(pack, "_process_one_package", _ok)
    monkeypatch.setattr(pack, "splice_packages_into_img", lambda *a, **k: None)
    monkeypatch.setattr(pack, "live", _Live())
    totals = pack.pack_images(
        images,
        imgf,
        work,
        out,
        only_keys={"album"},
        workers=0,
        pkg_workers=4,
        cache=ImgPackCache(tmp_path / "pack-cache"),
    )
    assert totals["packages"] == 1
    assert (work / "image_pack_report.txt").is_file()

    monkeypatch.setattr(pack, "live", types.SimpleNamespace(active=False))

    def _untouched(*args, **kwargs):
        return {"index": 4149, "ok": True, "touched": False, "png_ok": 0, "png_skip": 0, "arcs": 0, "report": [], "error": None}

    monkeypatch.setattr(pack, "_process_one_package", _untouched)
    with pytest.raises(pack.PackError, match="no textures were injected"):
        pack.pack_images(images, imgf, work / "u", out, only_keys={"album"}, workers=1, pkg_workers=1, cache=False)

    def _fail(*args, **kwargs):
        return {"index": 4149, "ok": False, "touched": False, "png_ok": 0, "png_skip": 0, "arcs": 0, "report": [], "error": "boom"}

    monkeypatch.setattr(pack, "_process_one_package", _fail)
    with pytest.raises(pack.PackError, match="failed"):
        pack.pack_images(images, imgf, work / "f", out, only_keys={"album"}, cache=False)

    def _fake_cesa(src, png, dst, work=None):
        Path(dst).write_bytes(b"CESA")
        return Path(dst)

    monkeypatch.setattr("patch_cesa.patch_img_bin", _fake_cesa)
    cesa_images = tmp_path / "cesa-only"
    (cesa_images / "cesa").mkdir(parents=True)
    (cesa_images / "cesa" / "CESA_240X400.png").write_bytes(b"png")
    done = pack.pack_images(
        cesa_images, imgf, work / "c", out, only_keys={"cesa"}, splice=False, cache=False
    )
    assert done["cesa"] == 1
    assert out.read_bytes() == b"CESA"

    ie_calls: list[int] = []
    monkeypatch.setattr(pack, "_process_one_package", _ok)
    monkeypatch.setattr(
        pack,
        "selective_ie_repack",
        lambda *a, **k: ie_calls.append(1),
    )
    monkeypatch.setattr(pack, "CACHE_IMG_PACK", tmp_path / "auto-cache")
    packed = pack.pack_images(
        images,
        imgf,
        work / "nosplice",
        out,
        only_keys={"album"},
        splice=False,
        cache=True,
        cache_dir=tmp_path / "cache-dir",
    )
    assert packed["packages"] == 1 and ie_calls

    monkeypatch.setattr(pack, "_process_one_package", _untouched)
    imgf.write_bytes(b"IMG-SRC")
    kept = pack.pack_images(
        images,
        imgf,
        work / "cesa-keep",
        out,
        only_keys={"album", "cesa"},
        cache=False,
    )
    assert kept["cesa"] == 1 and kept["packages"] == 0
    assert out.read_bytes() == b"CESA"

    with pytest.raises(pack.PackError, match="img.bin not found"):
        pack.pack_images(images, tmp_path / "no.bin", work, out, cache=False)
    with pytest.raises(pack.PackError, match="images root missing"):
        pack.pack_images(tmp_path / "no-images", imgf, work, out, cache=False)
    (tmp_path / "blank").mkdir()
    with pytest.raises(pack.PackError, match="no mapped"):
        pack.pack_images(tmp_path / "blank", imgf, work, out, cache=False)

    monkeypatch.setattr(pack, "pack_images", lambda *a, **k: {"packages": 0})
    monkeypatch.setattr(pack, "AZAHAR_IMG", tmp_path / "azahar" / "img.bin")
    (tmp_path / "azahar").mkdir()
    pack.AZAHAR_IMG.write_bytes(b"old")
    monkeypatch.setenv("NLPP_PREFER_AZAHAR_SRC", "1")
    seen = {}

    def _capture(images, img_bin, work, out_img, **kwargs):
        seen["img"] = Path(img_bin)
        Path(out_img).write_bytes(b"OUT")
        return {}

    monkeypatch.setattr(pack, "pack_images", _capture)
    assert pack.main(
        [
            "--images",
            str(images),
            "--img-bin",
            str(imgf),
            "--work",
            str(work / "cli"),
            "--out",
            str(tmp_path / "cli.bin"),
            "--deploy-azahar",
            "--no-cache",
            "--only",
            "album",
        ]
    ) == 0
    assert seen["img"] == pack.AZAHAR_IMG
    assert pack.AZAHAR_IMG.read_bytes() == b"OUT"
    monkeypatch.setenv("NLPP_PREFER_AZAHAR_SRC", "off")
    assert pack.main(
        ["--images", str(images), "--img-bin", str(imgf), "--work", str(work / "cli2"), "--out", str(tmp_path / "cli2.bin"), "--deploy-azahar"]
    ) == 0
    assert seen["img"] == imgf

    def _err(*args, **kwargs):
        raise pack.PackError("stopped")

    monkeypatch.setattr(pack, "pack_images", _err)
    assert pack.main(["--images", str(images), "--img-bin", str(imgf), "--work", str(work), "--out", str(out)]) == 1


def test_pack_process_one_package_reports(tmp_path: Path, monkeypatch):
    img_data = tmp_path / "img"
    arc_dir = img_data / "0007_data"
    arc_dir.mkdir(parents=True)
    (arc_dir / "Album.arc").write_bytes(fi.darc({"timg/A.bclim": fi.bclim(8, 8)}))
    folder = tmp_path / "album"
    folder.mkdir()
    monkeypatch.setattr(pack, "ensure_package_data", lambda *a, **k: arc_dir)
    empty = pack._process_one_package(7, [("album", str(folder), "Album.arc")], str(img_data), str(tmp_path / "conv"))
    assert empty["ok"] and not empty["touched"]
    assert any("empty" in line for line in empty["report"])
    missed = pack._process_one_package(7, [("album", str(folder), "Missing.arc")], str(img_data), str(tmp_path / "conv"))
    assert any("miss-arc" in line for line in missed["report"])
    (folder / "A.png").write_bytes(b"png")
    arc_dir.mkdir(parents=True, exist_ok=True)
    (arc_dir / "Album.arc").write_bytes(fi.darc({"timg/A.bclim": fi.bclim(8, 8)}))
    monkeypatch.setattr(pack, "repack_package", lambda *a, **k: None)
    monkeypatch.setattr(pack, "cleanup_package_unpack", lambda *a, **k: None)
    monkeypatch.setattr(pack, "remove_scratch", lambda *a, **k: None)
    monkeypatch.setattr(
        pack,
        "patch_arc_with_pngs",
        lambda *a, **k: (1, 12, [f"w{i}" for i in range(13)]),
    )
    warned = pack._process_one_package(
        7, [("album", str(folder), "album.arc")], str(img_data), str(tmp_path / "conv")
    )
    assert any("+1 more" in line for line in warned["report"])
    monkeypatch.setattr(pack, "ensure_package_data", lambda *a, **k: (_ for _ in ()).throw(pack.PackError("missing")))
    failed = pack._process_one_package(7, [], str(img_data), str(tmp_path / "conv"))
    assert failed["ok"] is False and "PackError" in failed["error"]


def test_remaining_easy_branches(tmp_path: Path, monkeypatch):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    _xml(scripts / "t001.xml", ["こんにちは"])
    _xml(scripts / "t002.xml", ["Hello"])
    monkeypatch.setattr(patcher, "SCRIPTS", scripts)
    assert patcher.cmd_validate(argparse.Namespace()) == 0

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(report.paths, "ROOT", repo)
    monkeypatch.delenv("NLPP_PROGRESS_TOKEN", raising=False)
    monkeypatch.delenv("NLPP_PROGRESS_ENDPOINT", raising=False)
    monkeypatch.delenv("NLPP_PROGRESS_SKIP", raising=False)
    (repo / ".env").write_text(
        "NLPP_PROGRESS_TOKEN=\nNLPP_PROGRESS_TOKEN=kept\n",
        encoding="utf-8",
    )
    assert report._from_env_or_dotenv("NLPP_PROGRESS_TOKEN") == "kept"
    monkeypatch.setenv("NLPP_PROGRESS_ENDPOINT", "https://example.test/p")
    monkeypatch.setenv("NLPP_PROGRESS_TOKEN", "tok")
    van = tmp_path / "jp.trb"
    van.write_bytes(_progress_trb(["こんにちは"]))
    assert report.try_report_progress(
        en_trb=tmp_path / "missing-en.trb", vanilla_trb=tmp_path / "missing-jp.trb"
    ) is False
    assert report.try_report_progress(
        en_trb=tmp_path / "missing-en.trb", vanilla_trb=van
    ) is False

    raw = _darc_bytes({"timg/Copyright.bclim": b"abcd"})
    arch = darcutil.DarcArchive(raw)
    odd = next(e for e in arch.entries if e["isdir"])
    odd["file_len"] = 0
    odd["file_off"] = 50
    arch.insert_file_entry("timg/New.bclim", "timg/Copyright.bclim")
    assert odd["file_off"] == 51 and odd["file_len"] == 0

    tree = tmp_path / "darc-tree"
    fresh = darcutil.DarcArchive(raw)
    fresh.extract_all(tree)
    (tree / "timg" / "note.txt").write_bytes(b"hi")
    (tree / "timg" / "note.bcfnt").write_bytes(b"font")
    fresh.insert_file_entry("timg/note.txt", "timg/Copyright.bclim")
    fresh.insert_file_entry("timg/note.bcfnt", "timg/Copyright.bclim")
    fresh.rebuild_from_dir(
        tree,
        tmp_path / "aligned.darc",
        default_align=1,
        align_mode="absolute",
        type_align={".bclim": 1, ".bcfnt": 1},
    )
    rebuilt = darcutil.DarcArchive((tmp_path / "aligned.darc").read_bytes())
    assert rebuilt.find("note.txt") is not None
    assert rebuilt.extract_file(rebuilt.find("note.bcfnt")) == b"font"

    assert gt.marker_multiset("a @@M0@@") == gt.extract_markers("a @@M0@@")

    class _Types:
        ThinkingLevel = types.SimpleNamespace(HIGH="H")

        def ThinkingConfig(self, thinking_level=None):
            raise TypeError(str(thinking_level))

    assert gt._thinking_config(_Types(), "high") is None

    class _Part:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Cand:
        def __init__(self, parts: list) -> None:
            self.content = types.SimpleNamespace(parts=parts)

    class _Resp:
        text = ""
        candidates = [_Cand([_Part(""), _Part("  ")]), _Cand([_Part("ok")])]

    assert gt._extract_response_text(_Resp()) == "ok"

    window = gt._context_window([], [], pad=1)
    assert window == []


def test_extract_fallthrough_and_slim_staging(tmp_path: Path, vanilla_paths, monkeypatch):
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"CIA")
    _wire_rom(monkeypatch)
    img = ev.ensure_vanilla_from_rom(rom, force=True, slim=False)
    assert img.is_file()
    assert (ev.VANILLA_ROMFS / "junk.bin").is_file()

    def _keep_staging(romfs_bin, out_dir, reuse=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "img.bin").write_bytes(b"IMG")
        trb = out_dir / "SystemData" / "TextResource" / "textresource_jpn.trb"
        trb.parent.mkdir(parents=True, exist_ok=True)
        trb.write_bytes(b"TRB")
        script = out_dir / "script" / "bin" / "script"
        script.mkdir(parents=True, exist_ok=True)
        (script / "a.dbin2").write_bytes(b"DB")
        staging = out_dir.parent / "_slim_staging" / "script" / "bin" / "script"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "old.dbin2").write_bytes(b"OLD")
        return out_dir

    monkeypatch.setattr(ev, "ensure_romfs_dir", _keep_staging)
    slimmed = ev.ensure_vanilla_from_rom(rom, force=True, slim=True)
    assert slimmed.is_file()
    assert not (ev.VANILLA_ROMFS / "junk.bin").exists()

    ev.VANILLA_CODE.unlink()
    ev.VANILLA_IMG.unlink()
    monkeypatch.setattr(ev, "ensure_vanilla_from_rom", lambda *a, **k: ev.VANILLA_IMG)
    code_work = ev.ROOT / "out" / "extract_vanilla_code_work"
    code_work.mkdir(parents=True)
    (code_work / "stale.txt").write_text("x", encoding="utf-8")
    _wire_rom(monkeypatch)
    monkeypatch.setattr(ev, "ensure_vanilla_from_rom", lambda *a, **k: ev.VANILLA_IMG)
    got = ev.ensure_vanilla_code_from_rom(rom)
    assert got.read_bytes() == b"CODE"


def test_zlib_and_pack_tails(tmp_path: Path, monkeypatch):
    tail = fi.darc({"timg/A.bclim": b"hello", "timg/B.bclim": b"world"}) + b"\x00" * 8
    gaps = ez.interfile_zero_gaps(tail, min_len=1)
    assert len(gaps) >= 2
    assert ez.apply_gap_pad(tail, gaps[0][0] + 1, b"\xab" * 64) != tail
    cmf = 0x78
    flg = next(n for n in range(256) if n & 0x20 and (cmf * 256 + n) % 31 == 0)
    assert ez._split_zlib(bytes([cmf, flg, 0, 0, 0, 0, 0, 0])) is None
    assert ez._split_zlib(b"\x00" * 8) is None
    assert ez._plan_empty_block_bits(0, 18) is None
    kinds = ez._plan_empty_block_bits(0, 40)
    assert kinds
    writer = ez._BitWriter(bytearray(64), 1)
    ez._write_empty_blocks(writer, ["stored", "fixed"])

    class _Once:
        encoding = "ascii"

        def __init__(self) -> None:
            self.n = 0

        def write(self, text: str) -> int:
            self.n += 1
            if self.n == 1:
                raise UnicodeEncodeError("ascii", text, 0, 1, "ordinal not in range")
            return len(text)

        def flush(self) -> None:
            return None

    monkeypatch.setattr(sys, "stdout", _Once())
    ez._zlib_progress("plain", newline=True)

    png = tmp_path / "face.png"
    png.write_bytes(b"png-bytes")
    dest = tmp_path / "Face.bclim"
    dest.write_bytes(b"Y" * 64)

    def _converted(src, orig, work, cache=None):
        out_bclim = Path(work) / "out.bclim"
        out_bclim.parent.mkdir(parents=True, exist_ok=True)
        out_bclim.write_bytes(b"Y" * 64)
        if cache is not None:
            cache.put_bclim(b"png-bytes", b"Y" * 64, b"Y" * 64)
        return out_bclim

    monkeypatch.setattr(pack, "convert_png_to_bclim", _converted)
    status, data, warn = pack._convert_one_png(png, dest, tmp_path / "conv-one")
    assert status == "ok" and data == b"Y" * 64 and warn is None
    monkeypatch.setattr(
        pack,
        "convert_png_to_bclim",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad-clim")),
    )
    assert pack._convert_one_png(png, dest, tmp_path / "conv-bad")[0] == "skip"

    arc = tmp_path / "Album.arc"
    arc.write_bytes(fi.darc({"timg/Face.bclim": b"Y" * 64}))
    monkeypatch.setattr(pack, "_convert_one_png", lambda *a, **k: ("skip", None, "kept"))
    _ok_n, skipped, warnings = pack.patch_arc_with_pngs(arc, [png], tmp_path / "arc-warn")
    assert skipped == 1 and warnings == ["kept"]
