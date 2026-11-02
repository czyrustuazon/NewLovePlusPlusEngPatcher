"""Coverage for small offline tools: their main() on synthetic img.bin / files.

No game dumps, no network. Paths are monkeypatched to tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import fake_img as fi
from conftest import TOOLS, load_module

# ---------------------------------------------------------------------------
# render_card_seal_labels_en
# ---------------------------------------------------------------------------

seal = load_module("render_card_seal_labels_en", TOOLS / "render_card_seal_labels_en.py")


def _seal_img(tmp_path: Path, members: dict[int, dict[str, bytes]]) -> Path:
    pkgs = {pkg: fi.package([(f"ExCardCommonT{pkg - 4315:03d}.arc", fi.darc(files))]) for pkg, files in members.items()}
    path = tmp_path / "img.bin"
    path.write_bytes(fi.img(pkgs))
    return path


def test_seal_labels_main_writes_every_sticker(tmp_path, monkeypatch, capsys):
    members = {
        pkg: {f"timg/{name}.bclim": fi.bclim(160, 64, 8)} for pkg, name, *_ in seal.LABELS
    }
    monkeypatch.setattr(seal, "VANILLA_IMG", _seal_img(tmp_path, members))
    monkeypatch.setattr(seal, "OUT_ROOT", tmp_path / "assets")
    monkeypatch.setattr(seal, "ROOT", tmp_path)
    assert seal.main() == 0
    pngs = sorted(p.name for p in (tmp_path / "assets").rglob("*.png"))
    assert pngs == [f"{name}_en.png" for _pkg, name, *_ in seal.LABELS]
    assert capsys.readouterr().out.count("OK Seal_T") == len(seal.LABELS)


def test_seal_load_vanilla_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(seal, "VANILLA_IMG", _seal_img(tmp_path, {4315: {"timg/Other.bclim": fi.bclim(8, 8, 8)}}))
    with pytest.raises(SystemExit, match="missing timg/Seal_T000.bclim"):
        seal.load_vanilla(4315, "Seal_T000")
    monkeypatch.setattr(seal, "VANILLA_IMG", _seal_img(tmp_path, {4315: {"timg/Seal_T000.bclim": fi.bclim(8, 8, 8)}}))
    with pytest.raises(SystemExit, match="cannot decode Seal_T000"):
        seal.load_vanilla(4315, "Seal_T000")


# ---------------------------------------------------------------------------
# mdcutil
# ---------------------------------------------------------------------------

mdc = load_module("mdcutil", TOOLS / "mdcutil.py")


def _rec(key: int, text: bytes, *, strlen: int | None = None) -> bytes:
    body = text + b"\x00"
    n = len(body) if strlen is None else strlen
    return key.to_bytes(8, "big") + bytes(8) + bytes([n]) + body


def test_mdc_parse_errors():
    with pytest.raises(ValueError, match="too small"):
        mdc.parse_mdc(b"\x01")
    with pytest.raises(ValueError, match="truncated MDC header"):
        mdc.parse_mdc(b"\x01\x00" + bytes(5))
    with pytest.raises(ValueError, match="truncated MDC text"):
        mdc.parse_mdc(b"\x01\x00" + _rec(1, b"hi", strlen=40))
    no_nul = b"\x01\x00" + (1).to_bytes(8, "big") + bytes(8) + b"\x02" + b"hi"
    with pytest.raises(ValueError, match="missing NUL"):
        mdc.parse_mdc(no_nul)


def test_mdc_pack_and_pad():
    with pytest.raises(ValueError, match="too long"):
        mdc.pack_mdc([mdc.MdcEntry(1, 0, "x" * 300)])
    with pytest.raises(ValueError, match="grew past slot"):
        mdc.pad_to_size(b"abc", 2)
    assert mdc.pad_to_size(b"abc", 3) == b"abc"
    with pytest.raises(ValueError, match="pad must be 1 byte"):
        mdc.pad_to_size(b"abc", 5, pad=b"xy")
    with pytest.raises(ValueError, match="text count"):
        mdc.apply_texts([mdc.MdcEntry(1, 0, "a")], [])


def _dict_xml(tmp_path: Path, body: str, root: str = "Dictionary") -> Path:
    path = tmp_path / "d.xml"
    path.write_text(f"<{root}>{body}</{root}>", encoding="utf-8")
    return path


def test_mdc_dictionary_xml_errors(tmp_path):
    base = [mdc.MdcEntry(0x10, 0, "a")]
    with pytest.raises(ValueError, match="expected <Dictionary>"):
        mdc.texts_from_dictionary_xml(_dict_xml(tmp_path, "", root="Other"))
    with pytest.raises(ValueError, match="Entry 0 missing JapaneseText"):
        mdc.texts_from_dictionary_xml(_dict_xml(tmp_path, "<Entry/>"), base)
    with pytest.raises(ValueError, match="no usable hex key"):
        mdc.texts_from_dictionary_xml(_dict_xml(tmp_path, "<Entry><JapaneseText>x</JapaneseText></Entry>"), base)
    with pytest.raises(ValueError, match="odd Entry count"):
        mdc.texts_from_dictionary_xml(_dict_xml(tmp_path, "<Entry/>"))
    with pytest.raises(ValueError, match="Entry 1 missing JapaneseText"):
        mdc.texts_from_dictionary_xml(_dict_xml(tmp_path, "<Entry/><Entry/>"))


# ---------------------------------------------------------------------------
# export_workbench_gemini
# ---------------------------------------------------------------------------

wb = load_module("export_workbench_gemini", TOOLS / "export_workbench_gemini.py")


def test_workbench_sms_map_skips_bad_entries(tmp_path):
    path = tmp_path / "m.xml"
    path.write_text(
        "<Dictionary><Entry/><Entry><JapaneseText>no key</JapaneseText></Entry>"
        "<Entry><JapaneseText hex='AB'>ok</JapaneseText></Entry></Dictionary>",
        encoding="utf-8",
    )
    assert wb.sms_map(path) == {"ab": "ok"}


def test_workbench_embed_errors():
    with pytest.raises(SystemExit, match="missing embedded JSON"):
        wb._embed("<html></html>", "x")
    with pytest.raises(SystemExit, match="unclosed script"):
        wb._embed('<script id="x">{}', "x")


def test_workbench_attach_edges(tmp_path):
    xml = tmp_path / "xml"
    xml.mkdir()
    (xml / "a001.xml").write_text("<D><Dialog>one</Dialog></D>", encoding="utf-8")
    data = {
        "stats": [],  # not a dict: left alone
        "items": [
            {"kind": "trb"},
            {"kind": "script", "stem": "a001", "baseline_dialogs": ["x", "y"], "gemini_dialogs": ["old"]},
        ],
    }
    assert wb.attach_scripts(data, xml) == {"scripts": 0, "scripts_skipped": 1}
    assert "gemini_dialogs" not in data["items"][1]
    sms = {"stats": [], "items": [{"kind": "sms", "heroine": "nene", "key": "0x1", "gemini": "old"}]}
    assert wb.attach_sms(sms, tmp_path / "nosms") == {"sms": 0}
    assert "gemini" not in sms["items"][0]


def test_workbench_read_build_and_main(tmp_path, capsys):
    bench = tmp_path / "bench"
    kit = bench / "kit"
    kit.mkdir(parents=True)
    assert wb.read_build(bench) == 0
    (bench / "version.json").write_text("{nope", encoding="utf-8")
    assert wb.read_build(bench) == 0
    (bench / "version.json").write_text('{"build": "x"}', encoding="utf-8")
    assert wb.read_build(bench) == 0
    (bench / "version.json").write_text('{"build": 4}', encoding="utf-8")
    (kit / "NLPP_Translate.html").write_text(
        '<meta charset="utf-8" />\n<meta name="nlpp-workbench-build" content="4" />\n'
        '<script type="application/json" id="embedded-workkit">{"items":[]}</script>',
        encoding="utf-8",
    )
    (kit / "NLPP_Translate_Strings.html").write_text(
        '<meta charset="utf-8" />\n<script type="application/json" id="embedded-strings">{"items":[]}</script>',
        encoding="utf-8",
    )
    assert wb.main(["--workbench", str(bench), "--gemini-root", str(tmp_path / "gem")]) == 0
    assert "build=5" in capsys.readouterr().out
    assert 'content="5"' in (kit / "NLPP_Translate.html").read_text(encoding="utf-8")
    assert 'content="5"' in (kit / "NLPP_Translate_Strings.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# fetch_release_bake
# ---------------------------------------------------------------------------

import io  # noqa: E402
import json  # noqa: E402
import types  # noqa: E402
import urllib.error  # noqa: E402
import zipfile  # noqa: E402

frb = load_module("fetch_release_bake", TOOLS / "fetch_release_bake.py")


def test_github_reachable(monkeypatch):
    import socket

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: _Conn())
    assert frb.github_reachable() is True

    def refuse(addr, timeout):
        raise OSError("down")

    monkeypatch.setattr(socket, "create_connection", refuse)
    assert frb.github_reachable() is False


def test_urlopen_headers(monkeypatch):
    seen = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen.append(dict(req.header_items()))
        return _Resp(b"ok")

    monkeypatch.setattr(frb.urllib.request, "urlopen", fake_urlopen)
    assert frb._urlopen("https://api.github.com/x", "tok") == b"ok"
    assert frb._urlopen("https://github.com/x", "tok") == b"ok"
    assert frb._urlopen("https://example.test/x", None) == b"ok"
    assert "Accept" in seen[0] and "Accept" not in seen[1] and "Authorization" not in seen[2]


def _release(urls: dict[str, str], *, message: str | None = None):
    def fake(url, _token):
        if "releases" in url:
            meta = {"assets": [{"name": k, "browser_download_url": v} for k, v in urls.items()]}
            if message:
                meta = {"message": message}
            return json.dumps(meta).encode()
        if url.endswith(".zip"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("SystemData/x.trb", b"trb")  # no romfs_overlay/ prefix
            return buf.getvalue()
        return b"BAKE"

    return fake


GOLD = {"bake_img.bin": "https://e.test/bake_img.bin", "romfs_overlay.zip": "https://e.test/o.zip"}


def test_try_fetch_gold_dry_run_latest_and_flat_overlay(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(frb, "github_reachable", lambda: True)
    monkeypatch.setattr(frb, "_urlopen", _release(GOLD))
    ok, msg = frb.try_fetch_gold(repo="o/r", tag="latest", token=None, out_dir=tmp_path, dry_run=True)
    assert ok and msg == "dry-run OK"
    # A stale overlay and extract dir are replaced; a flat zip still lands in romfs_overlay/.
    (tmp_path / "romfs_overlay").mkdir()
    (tmp_path / "_overlay_extract").mkdir()
    ok, msg = frb.try_fetch_gold(repo="o/r", tag="gold", token=None, out_dir=tmp_path, force=True)
    assert ok and (tmp_path / "romfs_overlay" / "SystemData" / "x.trb").is_file()


@pytest.mark.parametrize("exc, want", [
    (urllib.error.HTTPError("u", 500, "boom", {}, None), "GitHub HTTP 500"),
    (urllib.error.URLError("dns"), "network error: dns"),
    (OSError("disk"), "disk"),
])
def test_try_fetch_gold_errors(tmp_path, monkeypatch, exc, want):
    monkeypatch.setattr(frb, "github_reachable", lambda: True)

    def boom(url, token):
        raise exc

    monkeypatch.setattr(frb, "_urlopen", boom)
    ok, msg = frb.try_fetch_gold(repo="o/r", tag="gold", token=None, out_dir=tmp_path, force=True)
    assert not ok and want in msg


def test_try_fetch_gold_release_message(tmp_path, monkeypatch):
    monkeypatch.setattr(frb, "github_reachable", lambda: True)
    monkeypatch.setattr(frb, "_urlopen", _release(GOLD, message="Not Found"))
    ok, msg = frb.try_fetch_gold(repo="o/r", tag="gold", token=None, out_dir=tmp_path, force=True)
    assert not ok and msg == "Not Found"


# ---------------------------------------------------------------------------
# restore_azahar_extdata
# ---------------------------------------------------------------------------

from test_restore_azahar_extdata import ID0, _fake_azahar  # noqa: E402
from test_restore_azahar_extdata import mod as rex  # noqa: E402


class _Text:
    """Path stand-in whose resolve() is a fixed string (Windows spellings on any OS)."""

    def __init__(self, text: str) -> None:
        self.text = text

    def resolve(self):
        return self

    def __str__(self) -> str:
        return self.text


def test_long_path_spellings(monkeypatch):
    monkeypatch.setattr(rex.sys, "platform", "linux")
    plain = Path("x")
    assert rex.long_path(plain) is plain
    monkeypatch.setattr(rex.sys, "platform", "win32")
    bs = chr(92)  # backslash
    prefixed = bs * 2 + "?" + bs + "C:" + bs + "a"  # \\?\C:\a
    assert str(rex.long_path(_Text(prefixed))) == str(Path(prefixed))
    unc = bs * 2 + "server" + bs + "share"  # \\server\share
    assert "UNC" in str(rex.long_path(_Text(unc)))
    assert str(rex.long_path(_Text("C:" + bs + "a"))).endswith("C:" + bs + "a")


def test_discover_edges(tmp_path, monkeypatch):
    assert rex.discover_sd_title_saves(tmp_path / "none") == []
    user = _fake_azahar(tmp_path)
    nand_ext = user / "nand" / "data" / ID0 / "extdata" / "00000000"
    (nand_ext / "00000f4e").mkdir(parents=True)
    (nand_ext / "0000abcd").mkdir()
    # A save path that is a file, not a folder, is skipped.
    other = user / "sdmc" / "Nintendo 3DS" / ID0 / ("c" * 32) / rex.SD_SAVE_REL
    other.parent.mkdir(parents=True)
    other.write_bytes(b"x")
    trees = rex.discover_nlpp_trees(user)
    assert any("nand" in str(t) and t.name == "00000f4e" for t in trees)

    # Duplicates and unresolvable paths are dropped.
    dup = trees[0]
    monkeypatch.setattr(rex, "discover_sd_title_saves", lambda u: [dup, dup])
    assert rex.discover_nlpp_trees(user).count(dup) == 1
    real_resolve = Path.resolve

    def resolve(self, *a, **k):
        if self.name == "00000321":
            raise OSError("gone")
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(Path, "resolve", resolve)
    assert not any(t.name == "00000321" for t in rex.discover_nlpp_trees(user))


def test_backup_restore_cli_edges(tmp_path, capsys):
    user = _fake_azahar(tmp_path)
    root = tmp_path / "snaps"
    assert rex.latest_backup(root) is None
    assert rex.main(["list", "--user-dir", str(user), "--backup-root", str(root)]) == 0
    assert "No snapshots" in capsys.readouterr().out
    assert rex.main(["backup", "--user-dir", str(user), "--backup-root", str(root), "--stamp", "s1"]) == 0
    with pytest.raises(SystemExit, match="already exists"):
        rex.main(["backup", "--user-dir", str(user), "--backup-root", str(root), "--stamp", "s1"])
    assert rex.main(["list", "--user-dir", str(user), "--backup-root", str(root)]) == 0
    assert "Latest snapshot" in capsys.readouterr().out

    # Back up again over an existing tree in the destination.
    trees = rex.discover_nlpp_trees(user)
    rex.backup_trees(user, root / "s1", trees=trees)

    empty = tmp_path / "empty_user"
    empty.mkdir()
    rex.cmd_list(empty, root)
    assert "No NLPP extra data" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="No snapshot under"):
        rex.cmd_restore(user, tmp_path / "nosnaps", None)
    with pytest.raises(SystemExit, match="backup not found"):
        rex.cmd_restore(user, root, tmp_path / "missing")
    bad = tmp_path / "bad"
    bad.mkdir()
    assert rex.main(["restore", "--user-dir", str(user), "--backup-root", str(root), "--from", str(bad)]) == 1
    assert "missing manifest.json" in capsys.readouterr().err
    gone = root / "s1"
    first = json.loads((gone / rex.MANIFEST_NAME).read_text(encoding="utf-8"))["files"][0]["rel"]
    (gone / first).unlink()
    with pytest.raises(FileNotFoundError, match="backup file missing"):
        rex.restore_trees(gone, user)


# ---------------------------------------------------------------------------
# import_azahar_save
# ---------------------------------------------------------------------------

from test_import_azahar_save import ID0 as SAVE_ID0  # noqa: E402
from test_import_azahar_save import ID1 as SAVE_ID1  # noqa: E402
from test_import_azahar_save import _pack as _save_pack  # noqa: E402
from test_import_azahar_save import _user as _save_user  # noqa: E402
from test_import_azahar_save import mod as ias  # noqa: E402


def test_save_slot_lookup(tmp_path):
    direct = tmp_path / "direct"
    direct.mkdir()
    (direct / "savedata0").write_bytes(b"x")
    assert ias.find_save_slot(direct) == direct
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="no savedata0"):
        ias.find_save_slot(empty)
    many = tmp_path / "many"
    for d in ("a/x", "b/y"):
        (many / d).mkdir(parents=True)
        (many / d / "savedata0").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="multiple savedata0"):
        ias.find_save_slot(many)
    with pytest.raises(FileNotFoundError, match="no savedata"):
        ias.iter_savedata_files(empty)
    assert ias.load_pack_manifest(empty) == {"id": "empty"}


def test_list_packs_and_cli(tmp_path, capsys):
    saves = tmp_path / "saves"
    assert ias.list_packs(saves) == []
    assert ias.main(["--list", "--saves-root", str(saves)]) == 0
    assert "No save packs" in capsys.readouterr().out
    _save_pack(saves)
    (saves / "notes.txt").write_text("x", encoding="utf-8")
    (saves / "broken").mkdir()
    assert [p.name for p in ias.list_packs(saves)] == ["nene"]

    with pytest.raises(SystemExit, match="zip not found"):
        ias.main(["--zip", str(tmp_path / "none.zip"), "--saves-root", str(saves)])
    with pytest.raises(SystemExit, match="unknown save pack 'zz'. Known: nene"):
        ias.main(["--pack", "zz", "--saves-root", str(saves)])
    (saves / "broken" / "00000001").mkdir()
    (saves / "broken" / "00000001" / "savedata0").mkdir()  # a folder, not a file
    assert ias.main(["--pack", "broken", "--saves-root", str(saves), "--user-dir", str(tmp_path / "u")]) == 1
    assert "error:" in capsys.readouterr().err


def test_nintendo_ids_and_backup_stamps(tmp_path, monkeypatch):
    user = tmp_path / "u"
    other = user / "sdmc" / "Nintendo 3DS" / SAVE_ID0 / SAVE_ID1
    other.mkdir(parents=True)  # no title folder: still used
    assert ias.nintendo_3ds_ids(user) == (SAVE_ID0, SAVE_ID1)
    bare = tmp_path / "bare"
    (bare / "sdmc" / "Nintendo 3DS").mkdir(parents=True)
    assert ias.nintendo_3ds_ids(bare) == (ias.AZAHAR_DEFAULT_ID, ias.AZAHAR_DEFAULT_ID)
    assert list(ias.iter_or_empty(tmp_path / "nothing")) == []
    assert ias.backup_existing_title_save(bare, "p", tmp_path / "bk") is None

    user = _save_user(tmp_path)
    data = ias.sd_title_data_dir(user, SAVE_ID0, SAVE_ID1)
    (data / "00000001").mkdir(parents=True)
    (data / "00000001" / "savedata0").write_bytes(b"old")

    class _FixedNow:
        @staticmethod
        def now():
            import datetime as dt

            return dt.datetime(2026, 1, 2, 3, 4, 5, 6)

    monkeypatch.setattr(ias, "datetime", _FixedNow)
    first = ias.backup_existing_title_save(user, "p", tmp_path / "bk")
    second = ias.backup_existing_title_save(user, "p", tmp_path / "bk")
    assert first != second and second.name.endswith("_1")


# ---------------------------------------------------------------------------
# render_cesa_en
# ---------------------------------------------------------------------------

import sys  # noqa: E402

rcesa = load_module("render_cesa_en", TOOLS / "render_cesa_en.py")


def test_render_cesa_guards(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        rcesa._font(tmp_path / "none.ttc", 10)
    with monkeypatch.context() as m:
        m.setattr(rcesa, "H", 50)
        with pytest.raises(RuntimeError, match="CESA layout overflow"):
            rcesa.render_cesa_en()
    with monkeypatch.context() as m:
        m.setattr(rcesa, "COMPANION_MAX_TEXT_W", 1)
        with pytest.raises(RuntimeError, match="companion title does not fit"):
            rcesa.render_cesa_companion_en()
    with monkeypatch.context() as m:
        m.setattr(rcesa, "_runs_width", lambda font, line: 10**9)
        with pytest.raises(RuntimeError, match="companion body does not fit"):
            rcesa.render_cesa_companion_en()
    with monkeypatch.context() as m:
        m.setattr(rcesa, "COMPANION_CH", 100 * rcesa.SCALE)
        with pytest.raises(RuntimeError, match="companion layout overflow"):
            rcesa.render_cesa_companion_en()


def test_render_cesa_main(tmp_path, monkeypatch, capsys):
    out, comp = tmp_path / "p" / "a.png", tmp_path / "p" / "b.png"
    monkeypatch.setattr(sys, "argv", ["render", "--out", str(out), "--companion-out", str(comp)])
    assert rcesa.main() == 0
    assert out.is_file() and comp.is_file()
    monkeypatch.setattr(rcesa, "ASSET", tmp_path / "a" / "CESA.png")
    monkeypatch.setattr(rcesa, "COMPANION_ASSET", tmp_path / "a" / "logo_white.png")
    monkeypatch.setattr(sys, "argv", ["render", "--write-asset"])
    assert rcesa.main() == 0
    assert (tmp_path / "a" / "CESA.png").is_file()
    assert "companion" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# restore_sms_maildic_jpn / fetch_nlppatch_release
# ---------------------------------------------------------------------------

rsms = load_module("restore_sms_maildic_jpn", TOOLS / "restore_sms_maildic_jpn.py")
fnlp = load_module("fetch_nlppatch_release", TOOLS / "fetch_nlppatch_release.py")


def _mdc_img(path: Path, names: list[str], pkg: int = 92) -> Path:
    path.write_bytes(fi.img({pkg: fi.package([(n, b"m" * 32, b"ARC ", False) for n in names])}, count=100))
    return path


def test_restore_maildic_errors_and_default_target(tmp_path, monkeypatch, capsys):
    van = _mdc_img(tmp_path / "van.bin", [f"{s}.mdc" for s in rsms.STEMS])
    with pytest.raises(SystemExit, match="package 92 missing"):
        rsms.load_pkg92(_mdc_img(tmp_path / "other.bin", ["x"], pkg=5))
    partial = _mdc_img(tmp_path / "t.bin", ["maildic_m.mdc"])
    with pytest.raises(SystemExit, match="maildic_n.mdc missing in target"):
        rsms.restore_maildic(van, partial)

    target = _mdc_img(tmp_path / "target.bin", [f"{s}.mdc" for s in rsms.STEMS])
    monkeypatch.setattr(rsms, "resolve_img_paths", lambda: (target, None))
    monkeypatch.setattr(sys, "argv", ["restore", "--vanilla", str(van), "--no-backup"])
    rsms.main()
    assert "maildic_r.mdc" in capsys.readouterr().out


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_nlppatch_api_and_download(tmp_path, monkeypatch, capsys):
    payloads = iter([
        json.dumps({"assets": [{"name": "other.txt"}, {"name": "NLPPPATCH.zip", "browser_download_url": "https://dl/x.zip"}]}).encode(),
    ])
    monkeypatch.setattr(fnlp.urllib.request, "urlopen", lambda req, timeout: _Resp(next(payloads)))
    assert fnlp._api_asset_url() == "https://dl/x.zip"

    nothing = iter([json.dumps({"assets": [{"name": "readme.md"}]}).encode()] * 2)
    monkeypatch.setattr(fnlp.urllib.request, "urlopen", lambda req, timeout: _Resp(next(nothing)))
    assert fnlp._api_asset_url() is None

    monkeypatch.setattr(fnlp, "_api_asset_url", lambda: "https://dl/x.zip")
    seen = []
    monkeypatch.setattr(fnlp.urllib.request, "urlopen", lambda url, timeout: seen.append(url) or _Resp(b"ZIP"))
    dest = tmp_path / "p.zip"
    fnlp.download_zip(dest)
    assert dest.read_bytes() == b"ZIP" and seen == ["https://dl/x.zip"]
