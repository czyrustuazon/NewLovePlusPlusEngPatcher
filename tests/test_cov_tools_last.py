"""Last branches of nearly-covered tools and gemini_translate."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from PIL import Image

import gemini_translate as gt
from conftest import TOOLS, load_module

fit = load_module("fit_ui_masters_last", TOOLS / "fit_ui_masters.py")
restore_names = load_module("restore_nickname_tokens_last", TOOLS / "restore_nickname_tokens.py")
integrate = load_module("integrate_nlppatch_into_rebuild_last", TOOLS / "integrate_nlppatch_into_rebuild.py")
nl = load_module("import_nlppctr_textures_last", TOOLS / "import_nlppctr_textures.py")


def test_fit_contain_clamps_to_a_zero_box():
    with pytest.raises(ValueError):
        fit.fit_contain(Image.new("RGBA", (10, 10)), 0, 0)  # 1x1 minimum clamped to 0x0


def test_gemini_last_attempt_succeeds(monkeypatch):
    calls = {"n": 0}

    class Models:
        def generate_content(self, **kwargs):
            calls["n"] += 1
            if calls["n"] <= 7:
                raise RuntimeError("503 UNAVAILABLE")
            return types.SimpleNamespace(text='{"items":[]}')

    # CI has no google-genai; stub the config types the call builds.
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    gtypes = types.ModuleType("google.genai.types")
    gtypes.GenerateContentConfig = dict
    gtypes.ThinkingConfig = dict
    google.genai = genai
    genai.types = gtypes
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    monkeypatch.setattr(gt.time, "sleep", lambda _s: None)
    out = gt.gemini_generate_json(types.SimpleNamespace(models=Models()), "m", "{}")
    assert out == '{"items":[]}' and calls["n"] == 8


def test_restore_nickname_main_counts(tmp_path, monkeypatch, capsys):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "t001.xml").write_text("<Dialog>Hi</Dialog>", encoding="utf-8")
    mk = tmp_path / "Done_t001.xml"
    mk.write_text("<Dialog>Hi</Dialog>", encoding="utf-8")  # nothing to restore
    monkeypatch.setattr(restore_names, "fetch_makein", lambda stem, cache: mk)
    assert restore_names.main(["--scripts", str(scripts), "--cache", str(tmp_path)]) == 0
    assert "skipped" not in capsys.readouterr().out
    (scripts / "t002.xml").write_text("<Dialog>x</Dialog>", encoding="utf-8")
    monkeypatch.setattr(restore_names, "fetch_makein", lambda stem, cache: None if stem == "t002" else mk)
    assert restore_names.main(["--scripts", str(scripts), "--cache", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "skipped 1 scripts" in out and "..." not in out


def test_integrate_dry_run_without_destination(tmp_path):
    from test_cov_remaining_tools import _community_src

    src = tmp_path / "community"
    _community_src(src)
    assert integrate.main(["--src", str(src), "--dst", str(tmp_path / "no-dst"), "--dry-run"]) == 0


def test_nlppctr_index_skips_unknown_ui_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(nl, "UI_PACKAGE_KEYS", ("no-such-folder",))
    assert nl.index_bclims_from_img(tmp_path / "img.bin", tmp_path / "work") == {}


# ---------------------------------------------------------------------------
# scan_nl_spotpass_zip
# ---------------------------------------------------------------------------

import struct  # noqa: E402

from test_cov_cia_rebuild import _reader, _stored_zip  # noqa: E402
from test_cov_cia_rebuild import scan as snz  # noqa: E402


def test_split_reader_end_of_data(tmp_path):
    zpath = tmp_path / "z.zip"
    _stored_zip(zpath, {"a.txt": b"abc"})
    reader = _reader(zpath)
    with pytest.raises(ValueError, match="could not map"):
        reader.read(reader.size, 0)


def test_find_eocd_walks_past_two_fake_records():
    fake = snz.SIG_EOCD + bytes(18)  # claims no comment; not at the tail
    comment = b"xx" + fake + b"yy" + fake + b"zz"
    real = snz.SIG_EOCD + struct.pack("<HHHHIIH", 0, 0, 0, 0, 0, 0, len(comment)) + comment
    tail = b"\x00" * 10 + real
    eocd_off, cd_off, cd_size, count = snz._find_eocd(tail, len(tail))
    assert eocd_off == 10


def test_central_directory_zip64_sizes_only_and_progress(monkeypatch, capsys):
    name = b"big.boss"
    extra = struct.pack("<HHQQ", 1, 16, 7, 7)
    entry = (
        snz.SIG_CD
        + bytes(6)
        + struct.pack("<H", 0)
        + bytes(4)
        + struct.pack("<III", 0, 0xFFFFFFFF, 0xFFFFFFFF)
        + struct.pack("<HHH", len(name), len(extra), 0)
        + bytes(8)
        + struct.pack("<I", 5)
        + name
        + extra
    )
    reader = types.SimpleNamespace(read=lambda off, n: entry[off : off + n], size=len(entry))
    monkeypatch.setattr(snz, "CD_PROGRESS_EVERY", 1)
    got = list(snz.iter_central_directory(reader, 0, len(entry), 1))
    assert got[0].comp_size == 7 and got[0].local_offset == 5
    assert "central-directory entries" in capsys.readouterr().out


def test_report_without_magazine_names_and_walk_progress(tmp_path, monkeypatch, capsys):
    catalog = b"hash\r\n        1\r\naabbccddeeff0011\t\t\t\t\t80\t1400000000\r\n"
    zpath = tmp_path / "plain.zip"
    _stored_zip(zpath, {"JP/ja/PTASK/filelist.txt": catalog, "JP/ja/PTASK/voice.boss": b"v"})
    reader = _reader(zpath)
    snz.print_report(reader, snz.scan(reader, 10), False)
    assert "magazine-like catalog names" not in capsys.readouterr().out

    from test_cov_cia_rebuild import _boss, _local

    monkeypatch.setattr(snz, "LOCAL_PROGRESS_EVERY", 1)
    walk = tmp_path / "walk.bin"
    walk.write_bytes(_local("JP/ja/TASK/a.boss", _boss()) + _local("JP/ja/TASK/b.boss", _boss()))
    snz.walk_local_part(walk, 0, tmp_path / "rep.txt")
    assert "GiB, last" in capsys.readouterr().out


def test_walk_stops_on_a_short_header(tmp_path):
    import io

    class _Shrunk:
        """A part that reports 100 bytes but only 10 come back."""

        def stat(self):
            return types.SimpleNamespace(st_size=100)

        def open(self, mode):
            return io.BytesIO(snz.SIG_LOCAL + bytes(6))

    snz.walk_local_part(_Shrunk(), 0, tmp_path / "short.txt")
    assert (tmp_path / "short.txt").is_file()


# ---------------------------------------------------------------------------
# translate_heroines_gemini
# ---------------------------------------------------------------------------

from test_cov_cia_rebuild import _bind_th, _dlg, _sms_xml, _th_args  # noqa: E402
from test_cov_cia_rebuild import th  # noqa: E402

JP = "こんにちは"


def _th_setup(monkeypatch, tmp_path):
    root = _bind_th(monkeypatch, tmp_path)
    vanilla = tmp_path / "vanilla"
    vanilla.mkdir()
    (vanilla / "a001.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg([JP, "まだ", "Hello"])))
    (vanilla / "a002.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg([JP])))
    return root, vanilla


def _results(texts, english):
    return [th.TranslateResult(i, t, e, error="" if e else "bad") for i, (t, e) in enumerate(zip(texts, english))]


def test_th_overlay_and_translate_one(monkeypatch, tmp_path):
    root, vanilla = _th_setup(monkeypatch, tmp_path)
    th.REBUILD_SCRIPT.mkdir(parents=True)
    (th.REBUILD_SCRIPT / "a001.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg(["Hi"])))  # shorter overlay
    assert th.overlay_path("a001").suffix == ".dbin2"
    seen = {}

    def prepared(client, model, items, **k):
        seen["items"] = items
        return [th.TranslateResult(it.index, it.source, "EN") for it in items]

    monkeypatch.setattr(th, "translate_prepared", prepared)
    args = _th_args(["run", "--out", str(tmp_path / "o")])
    pending = [th.Job("x", "nene", "script", "a001", 0, 1, "まだ", "まだ")]
    # JP already mapped, one pending, one beyond the overlay's dialogs.
    stem, results, errors = th.translate_one_script(None, "m", "a001", pending, vanilla, {JP: "Hello!"}, args)
    assert stem == "a001" and errors == []
    # Overlay with fewer entries than vanilla; then an overlay that does not parse.
    (th.REBUILD_SCRIPT / "a001.dbin2").write_bytes(th.build_dbin2(1, 0, []))
    th.translate_one_script(None, "m", "a001", pending, vanilla, {}, args)
    (th.REBUILD_SCRIPT / "a001.dbin2").write_bytes(b"broken")
    th.translate_one_script(None, "m", "a001", pending, vanilla, {}, args)
    (th.REBUILD_SCRIPT / "a001.dbin2").unlink()
    th.translate_one_script(None, "m", "a001", pending, vanilla, {}, args)

    # apply: unparsable overlay, an English line that keeps Japanese, a failure.
    (th.REBUILD_SCRIPT / "a001.dbin2").write_bytes(b"broken")
    mapping = {}
    w, f = th.apply_script_results(
        "a001", _results([JP, "まだ", "Hello"], ["Hi まだ", None, "Hey"]), vanilla, tmp_path / "xml", mapping
    )
    assert f == 1 and JP not in mapping


def test_th_cmd_run_limit_sms_and_write_xml(monkeypatch, tmp_path, capsys):
    root, vanilla = _th_setup(monkeypatch, tmp_path)
    _sms_xml(th.SMS_PACK / "maildic_n.xml", [("1", "まだ")])
    _sms_xml(th.SMS_PACK / "maildic_m.xml", [("2", "まだまだ")])
    monkeypatch.setattr(th, "load_gemini_api_key", lambda key=None: "k")
    monkeypatch.setattr(th, "make_gemini_client", lambda key: None)
    monkeypatch.setattr(
        th, "translate_one_script", lambda client, model, stem, jobs, *a: (stem, [th.TranslateResult(0, JP, "Hi")], [])
    )
    monkeypatch.setattr(th, "apply_script_results", lambda *a: (1, 0))
    monkeypatch.setattr(th, "translate_sms_unique", lambda client, model, group, mapping, args: (len(group), 0))
    monkeypatch.setattr(th, "write_sms_xml", lambda heroines, mapping, out: None)
    out = tmp_path / "run"
    (out / "xml").mkdir(parents=True)
    (out / "xml" / "a009.xml").write_text("<x/>", encoding="utf-8")
    argv = ["run", "--vanilla-script", str(vanilla), "--heroine", "nene", "--source", "all",
            "--out", str(out), "--workers", "1", "--limit", "1", "--write-xml"]
    assert th.cmd_run(_th_args(argv)) == 0
    assert (th.ASSETS_SCRIPTS / "a009.xml").is_file()
    text = capsys.readouterr().out
    assert "[limit] keeping" in text and "[sms]" in text

    # SMS only: no script stems at all.
    assert th.cmd_run(_th_args(["run", "--heroine", "nene", "--source", "sms", "--out", str(tmp_path / "sms")])) == 0
