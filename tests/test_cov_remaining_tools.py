"""Coverage for small tools and the last branches of near-complete modules.

No game dumps and no network. Output paths are tmp dirs or monkeypatched.
"""

from __future__ import annotations

import io
import json
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import ROOT, SRC, TOOLS, load_module

FONT = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025" / "Geomanist-Regular.ttf"


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _urlopen_cm(payload: bytes):
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return _Resp(payload)


# --- make_code_ips ---------------------------------------------------------


ips = load_module("make_code_ips", TOOLS / "make_code_ips.py")


def _run_ips(monkeypatch, van: bytes, new: bytes, dest: Path, capsys) -> str:
    van_path = dest.parent / "van.bin"
    new_path = dest.parent / "new.bin"
    van_path.write_bytes(van)
    new_path.write_bytes(new)
    monkeypatch.setattr(ips.sys, "argv", ["ips", str(van_path), str(new_path), str(dest)])
    ips.main()
    return capsys.readouterr().out


def test_ips_merges_nearby_diffs_and_roundtrips(tmp_path, monkeypatch, capsys):
    van = bytearray(40)
    new = bytearray(van)
    new[0] = 1
    new[3] = 2
    new[30] = 3
    out = _run_ips(monkeypatch, bytes(van), bytes(new), tmp_path / "c.ips", capsys)
    assert "records 2" in out and "roundtrip True" in out
    blob = (tmp_path / "c.ips").read_bytes()
    assert blob.startswith(b"PATCH") and blob.endswith(b"EOF")


def test_ips_identical_and_length_mismatch(tmp_path, monkeypatch, capsys):
    out = _run_ips(monkeypatch, b"same", b"same", tmp_path / "z.ips", capsys)
    assert "records 0" in out and "roundtrip True" in out
    with pytest.raises(AssertionError):
        _run_ips(monkeypatch, b"aa", b"bbb", tmp_path / "bad.ips", capsys)


def test_ips_splits_oversized_record_and_eof_offset(tmp_path, monkeypatch, capsys):
    van = bytes(70_000)
    new = bytes([9]) * 70_000
    out = _run_ips(monkeypatch, van, new, tmp_path / "big.ips", capsys)
    assert "records 1" in out and "roundtrip True" in out

    # A record that starts at 0x454F46 would spell EOF in the offset bytes.
    n = 0x454F46 + 2
    van_b = bytearray(n)
    new_b = bytearray(van_b)
    new_b[0x454F46] = 7
    out = _run_ips(monkeypatch, bytes(van_b), bytes(new_b), tmp_path / "eof.ips", capsys)
    assert "roundtrip True" in out


# --- script coverage report ------------------------------------------------


report = load_module("script_coverage_report", TOOLS / "script_coverage_report.py")


def test_script_coverage_report_missing_and_present(tmp_path, monkeypatch, capsys):
    dbin = tmp_path / "eng"
    (dbin / "script").mkdir(parents=True)
    (dbin / "script" / "t0001.dbin2").write_bytes(b"x")
    monkeypatch.setattr(report, "nlppatch_script_dir", lambda: None)
    assert report.main(["--dbin", str(dbin)]) == 1
    text = capsys.readouterr().out
    assert "Script coverage" in text and "Fetch NLPPPATCH" in text

    monkeypatch.setattr(report, "nlppatch_script_dir", lambda: tmp_path / "vendor")
    assert report.main(["--dbin", str(dbin)]) == 0
    assert "NLPPPATCH vendor" in capsys.readouterr().out


# --- community script deploy ----------------------------------------------


deploy_scripts = load_module(
    "deploy_nlppatch_scripts", SRC / "deploy_nlppatch_scripts.py"
)


def test_resolve_src_prefers_dir_then_legacy_then_errors(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.dbin2").write_bytes(b"a")
    assert deploy_scripts.resolve_src(src) == src

    empty = tmp_path / "empty"
    empty.mkdir()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "b.dbin2").write_bytes(b"b")
    monkeypatch.setattr(deploy_scripts, "LEGACY_SRC", legacy)
    assert deploy_scripts.resolve_src(empty) == legacy

    monkeypatch.setattr(deploy_scripts, "LEGACY_SRC", tmp_path / "missing")
    with pytest.raises(SystemExit, match="community scripts missing"):
        deploy_scripts.resolve_src(empty)


def test_deploy_filters_and_main_keeps_or_strips_tokens(tmp_path, monkeypatch, capsys):
    src = tmp_path / "scripts"
    src.mkdir()
    (src / "keep.dbin2").write_bytes(b"keep")
    (src / "drop.dbin2").write_bytes(b"drop")
    dest = tmp_path / "azahar"
    monkeypatch.setattr(deploy_scripts, "community_stems", lambda: {"keep"})
    assert deploy_scripts.deploy(src, dest) == 1
    assert (dest / "keep.dbin2").read_bytes() == b"keep"
    assert not (dest / "drop.dbin2").exists()

    monkeypatch.setattr(deploy_scripts, "community_stems", lambda: set())
    assert deploy_scripts.deploy(src, dest) == 2

    monkeypatch.setattr(deploy_scripts, "community_stems", lambda: {"nope"})
    with pytest.raises(SystemExit, match="no community"):
        deploy_scripts.deploy(src, dest)

    monkeypatch.setattr(deploy_scripts, "community_stems", lambda: {"keep"})
    monkeypatch.setattr(deploy_scripts, "patch_dbin2_tree", lambda *a, **k: (3, 4))
    assert deploy_scripts.main(
        ["--src", str(src), "--azahar", str(dest), "--strip-dialog-tokens"]
    ) == 0
    stripped = capsys.readouterr().out
    assert "strip: 3 files" in stripped

    assert deploy_scripts.main(["--src", str(src), "--azahar", str(dest)]) == 0
    assert "kept dialog tokens" in capsys.readouterr().out


# --- restore name-input baseline ------------------------------------------


restore_base = load_module(
    "restore_name_input_baseline", TOOLS / "restore_name_input_baseline.py"
)


def _point_restore(monkeypatch, tmp_path):
    code = tmp_path / "mods" / "exefs" / "code.bin"
    root = tmp_path / "mods"
    trb = tmp_path / "trb"
    monkeypatch.setattr(restore_base, "AZAHAR_MOD_CODE", code)
    monkeypatch.setattr(restore_base, "AZAHAR_MOD_ROOT", root)
    monkeypatch.setattr(restore_base, "AZAHAR_MOD_TRB_DIR", trb)
    return code, root, trb


def test_restore_code_from_backup_dry_and_real(tmp_path, monkeypatch, capsys):
    code, root, _trb = _point_restore(monkeypatch, tmp_path)
    bak = code.with_name("code.bin.bak_pre_name_input_en")
    bak.parent.mkdir(parents=True)
    bak.write_bytes(b"backup-code")
    restore_base.restore_code(dry_run=True)
    assert not code.exists()
    restore_base.restore_code(dry_run=False)
    assert code.read_bytes() == b"backup-code"
    assert (root / "code.bin").read_bytes() == b"backup-code"
    assert "code.bin <=" in capsys.readouterr().out


def test_restore_code_falls_back_to_vanilla(tmp_path, monkeypatch, capsys):
    code, _root, _trb = _point_restore(monkeypatch, tmp_path)
    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(b"vanilla-code")
    monkeypatch.setattr(restore_base, "require_vanilla_code", lambda: vanilla)
    restore_base.restore_code(dry_run=False)
    assert code.read_bytes() == b"vanilla-code"
    assert "using vanilla" in capsys.readouterr().out


def test_restore_trbs_and_main_flags(tmp_path, monkeypatch, capsys):
    _code, _root, trb = _point_restore(monkeypatch, tmp_path)
    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(b"v")
    monkeypatch.setattr(restore_base, "require_vanilla_code", lambda: vanilla)
    name = "textresource_jpn.trb"
    dest = trb / name
    bak = dest.with_suffix(dest.suffix + ".bak_pre_namekanji")
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"live")
    restore_base.restore_trbs(dry_run=False)
    assert "no backup" in capsys.readouterr().out

    bak.write_bytes(b"trb-bak")
    restore_base.restore_trbs(dry_run=True)
    assert dest.read_bytes() == b"live"
    restore_base.restore_trbs(dry_run=False)
    assert dest.read_bytes() == b"trb-bak"

    # Second TRB name with neither file: silent continue.
    assert restore_base.main(["--dry-run", "--code-only"]) == 0
    assert "Restored" not in capsys.readouterr().out
    assert restore_base.main([]) == 0
    assert "Restored" in capsys.readouterr().out


# --- nickname token verify / restore --------------------------------------


verify_names = load_module("verify_nickname_tokens", TOOLS / "verify_nickname_tokens.py")
restore_names = load_module("restore_nickname_tokens", TOOLS / "restore_nickname_tokens.py")


def _entry(dialogs: list[str]):
    return SimpleNamespace(sdl2=SimpleNamespace(dialogs=dialogs))


def test_verify_nickname_tokens_match_mismatch_and_dual(tmp_path, monkeypatch, capsys):
    def parse(data: bytes):
        text = data.decode()
        dialogs = [] if text == "-" else text.split("|")
        return None, None, [_entry(dialogs)]

    monkeypatch.setattr(verify_names, "parse_dbin2", parse)
    scripts = tmp_path / "scripts"
    dbin = tmp_path / "dbin"
    scripts.mkdir()
    dbin.mkdir()

    (scripts / "t_ok.xml").write_text("<Dialog>▲高嶺＊＊▲ hi</Dialog>", encoding="utf-8")
    (dbin / "t_ok.dbin2").write_bytes("▲高嶺＊＊▲ hi".encode())
    (scripts / "t_miss.xml").write_text("<Dialog>▲高嶺＊＊▲</Dialog>", encoding="utf-8")
    (scripts / "t_bad.xml").write_text("<Dialog>▲高嶺＊＊▲</Dialog>", encoding="utf-8")
    (dbin / "t_bad.dbin2").write_bytes(b"hello")
    (scripts / "t_dual.xml").write_text("<Dialog>▲高嶺＊＊▲</Dialog>", encoding="utf-8")
    (dbin / "t_dual.dbin2").write_bytes("▲高嶺＊＊▲ and Takane".encode())

    assert verify_names.main(["--scripts", str(scripts), "--dbin", str(dbin), "--glob", "t_*.xml"]) == 1
    out = capsys.readouterr().out
    assert "TOKEN MISMATCHES" in out
    assert "missing dbin2" in out
    assert "plain" in out

    only = tmp_path / "only"
    only_db = tmp_path / "only_db"
    only.mkdir()
    only_db.mkdir()
    (only / "t_ok.xml").write_text("<Dialog>▲高嶺＊＊▲</Dialog>", encoding="utf-8")
    (only_db / "t_ok.dbin2").write_bytes("▲高嶺＊＊▲".encode())
    assert verify_names.main(["--scripts", str(only), "--dbin", str(only_db)]) == 0
    assert "OK" in capsys.readouterr().out


def test_verify_nickname_truncates_long_mismatch_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        verify_names, "parse_dbin2", lambda data: (None, None, [_entry(["no"])])
    )
    scripts = tmp_path / "many"
    dbin = tmp_path / "many_db"
    scripts.mkdir()
    dbin.mkdir()
    for i in range(31):
        (scripts / f"t{i:02d}.xml").write_text("<Dialog>▲高嶺＊＊▲</Dialog>", encoding="utf-8")
        (dbin / f"t{i:02d}.dbin2").write_bytes(b"no")
    assert verify_names.main(["--scripts", str(scripts), "--dbin", str(dbin)]) == 1
    assert "+1 more" in capsys.readouterr().out


def test_restore_nickname_normalize_fetch_and_rewrite(tmp_path, monkeypatch):
    assert restore_names.normalize_hero_refs("  Hello   Takane ") == "Hello @HERO@"
    assert restore_names.extract_dialog_inners("<Dialog>A</Dialog><Dialog>B</Dialog>") == ["A", "B"]

    cache = tmp_path / "cache"
    cache.mkdir()
    hit = cache / "Done_t1.xml"
    hit.write_bytes(b"x" * 600)
    assert restore_names.fetch_makein("t1", cache) == hit

    def boom(url, timeout=30):
        raise OSError("offline")

    monkeypatch.setattr(restore_names.urllib.request, "urlopen", boom)
    assert restore_names.fetch_makein("t2", cache) is None

    monkeypatch.setattr(
        restore_names.urllib.request, "urlopen", lambda url, timeout=30: _urlopen_cm(b"y" * 20)
    )
    assert restore_names.fetch_makein("t3", cache) is None

    monkeypatch.setattr(
        restore_names.urllib.request, "urlopen", lambda url, timeout=30: _urlopen_cm(b"z" * 600)
    )
    got = restore_names.fetch_makein("t4", cache)
    assert got is not None and got.stat().st_size == 600


def test_restore_script_file_and_main(tmp_path, monkeypatch, capsys):
    eng = tmp_path / "t1.xml"
    mk = tmp_path / "Done_t1.xml"
    eng.write_text("<Dialog>Hello Takane</Dialog>", encoding="utf-8")
    mk.write_text("<Dialog>Hello ▲高嶺＊＊▲</Dialog>", encoding="utf-8")
    stats = restore_names.restore_script_file(eng, mk, dry_run=True)
    assert stats.restored == 1
    assert "Takane" in eng.read_text(encoding="utf-8")
    stats = restore_names.restore_script_file(eng, mk, dry_run=False)
    assert stats.restored == 1
    assert "▲高嶺＊＊▲" in eng.read_text(encoding="utf-8")

    same = restore_names.restore_script_file(eng, mk, dry_run=False)
    assert same.restored == 0

    other = tmp_path / "other.xml"
    other.write_text("<Dialog>Totally different</Dialog>", encoding="utf-8")
    mk.write_text("<Dialog>Hello ▲高嶺＊＊▲</Dialog>", encoding="utf-8")
    assert restore_names.restore_script_file(other, mk, dry_run=False).restored == 0

    short = tmp_path / "short.xml"
    short.write_text("<Dialog>A</Dialog><Dialog>B</Dialog>", encoding="utf-8")
    skipped = restore_names.restore_script_file(short, mk, dry_run=False)
    assert skipped.skipped_count_mismatch

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for i in range(13):
        (scripts / f"t{i:02d}.xml").write_text("<Dialog>x</Dialog>", encoding="utf-8")
    monkeypatch.setattr(restore_names, "fetch_makein", lambda stem, cache: None)
    assert restore_names.main(["--scripts", str(scripts), "--cache", str(tmp_path / "c"), "--dry-run"]) == 0
    assert "..." in capsys.readouterr().out

    (scripts / "t_fix.xml").write_text("<Dialog>Hello Takane</Dialog>", encoding="utf-8")
    ref = tmp_path / "ref.xml"
    ref.write_text("<Dialog>Hello ▲高嶺＊＊▲</Dialog>", encoding="utf-8")
    monkeypatch.setattr(restore_names, "fetch_makein", lambda stem, cache: ref if stem == "t_fix" else None)
    assert restore_names.main(["--scripts", str(scripts), "--cache", str(tmp_path / "c")]) == 0
    assert "updated" in capsys.readouterr().out
    assert "▲高嶺＊＊▲" in (scripts / "t_fix.xml").read_text(encoding="utf-8")


# --- camset alert renderer -------------------------------------------------


camset = load_module("render_camset_alert_en", TOOLS / "render_camset_alert_en.py")


def test_render_camset_alert_fits_and_overflows(monkeypatch):
    import shutil

    out_dir = ROOT / "out" / "_cov_camset"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "CamSet_Alert01.png"
    try:
        monkeypatch.setattr(camset, "FONT", FONT)
        monkeypatch.setattr(camset, "LINES", ("Hi", "Ok"))
        monkeypatch.setattr(camset, "OUT", dest)
        im = camset.render()
        assert im.size == (camset.W, camset.H)
        assert im.mode == "RGBA"
        assert any(px[3] > 0 for px in im.getdata())
        camset.main()
        assert dest.is_file()

        monkeypatch.setattr(camset, "W", 4)
        monkeypatch.setattr(camset, "LINES", ("MMMMMMMMMMMM", "MMMMMMMMMMMM"))
        with pytest.raises(SystemExit, match="overflows"):
            camset.main()
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


# --- setup_tools -----------------------------------------------------------


setup = load_module("setup_tools", SRC / "setup_tools.py")


def _cia_tree(tmp_path, *, with_3ds: bool = True, with_romfs: bool = True) -> Path:
    cia = tmp_path / "cia"
    (cia / "3dstool").mkdir(parents=True)
    if with_3ds:
        (cia / "3dstool" / "3dstool.exe").write_bytes(b"3ds")
    (cia / "ctrtool.exe").write_bytes(b"ctr")
    (cia / "makerom.exe").write_bytes(b"mak")
    (cia / "seeddb.bin").write_bytes(b"seed")
    if with_romfs:
        (cia / "extract_romfs.py").write_bytes(b"# romfs\n")
    return cia


def test_setup_download_offline_and_online(tmp_path, monkeypatch):
    setup._OFFLINE = True
    with pytest.raises(SystemExit, match="offline"):
        setup.download("http://example/x", tmp_path / "x.bin")

    setup._OFFLINE = False
    monkeypatch.setattr(
        setup.urllib.request, "urlopen", lambda req, timeout=120: _urlopen_cm(b"payload")
    )
    dest = tmp_path / "sub" / "tool.bin"
    setup.download("http://example/tool", dest)
    assert dest.read_bytes() == b"payload"


def test_setup_extract_exe_picks_shallowest(tmp_path):
    blob = _zip({"deep/nested/ctrtool.exe": b"deep", "shallow/ctrtool.exe": b"shallow"})
    zpath = tmp_path / "tools.zip"
    zpath.write_bytes(blob)
    dest = tmp_path / "out" / "ctrtool.exe"
    setup._extract_exe_from_zip(zpath, "ctrtool.exe", dest)
    assert dest.read_bytes() == b"shallow"
    with pytest.raises(SystemExit, match="not found"):
        setup._extract_exe_from_zip(zpath, "missing.exe", tmp_path / "no.exe")


def test_setup_ensure_helpers(tmp_path, monkeypatch):
    cia = _cia_tree(tmp_path)
    monkeypatch.setattr(setup, "CIA_TOOLS", cia)
    setup._OFFLINE = False
    setup.ensure_3dstool()
    setup.ensure_project_ctr_bin("ctrtool.exe", "http://example/ctr")
    setup.ensure_seeddb()
    setup.ensure_extract_romfs()

    (cia / "3dstool" / "3dstool.exe").unlink()
    nested = _zip({"nested/3dstool.exe": b"nested-exe"})

    def fake_download(url, dest: Path):
        dest.write_bytes(nested)

    monkeypatch.setattr(setup, "download", fake_download)
    setup.ensure_3dstool()
    assert (cia / "3dstool" / "3dstool.exe").read_bytes() == b"nested-exe"

    (cia / "3dstool" / "3dstool.exe").unlink()
    monkeypatch.setattr(setup, "download", lambda url, dest: dest.write_bytes(_zip({"readme.txt": b"no"})))
    with pytest.raises(SystemExit, match="missing after extract"):
        setup.ensure_3dstool()

    (cia / "ctrtool.exe").unlink()
    monkeypatch.setattr(
        setup, "download", lambda url, dest: dest.write_bytes(_zip({"ctrtool.exe": b"fresh"}))
    )
    setup.ensure_project_ctr_bin("ctrtool.exe", "http://example/ctr")
    assert (cia / "ctrtool.exe").read_bytes() == b"fresh"

    (cia / "seeddb.bin").unlink()
    monkeypatch.setattr(setup, "download", lambda url, dest: dest.write_bytes(b"db"))
    setup.ensure_seeddb()
    assert (cia / "seeddb.bin").read_bytes() == b"db"

    (cia / "extract_romfs.py").unlink()
    src_romfs = tmp_path / "dump_extract.py"
    src_romfs.write_text("print(1)\n", encoding="utf-8")
    monkeypatch.setattr(setup, "EXTRACT_ROMFS_SRC", src_romfs)
    setup.ensure_extract_romfs()
    assert "print(1)" in (cia / "extract_romfs.py").read_text(encoding="utf-8")
    (cia / "extract_romfs.py").unlink()
    monkeypatch.setattr(setup, "EXTRACT_ROMFS_SRC", tmp_path / "nope.py")
    setup.ensure_extract_romfs()
    assert not (cia / "extract_romfs.py").exists()


def test_setup_python_deps_and_main(tmp_path, monkeypatch):
    real_import = __import__

    def missing_once(name, *args, **kwargs):
        if name == "yaml" and missing_once.left:
            missing_once.left -= 1
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    missing_once.left = 1
    monkeypatch.setattr("builtins.__import__", missing_once)

    class Ok:
        returncode = 0

    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: Ok())
    setup.ensure_python_deps()

    def always_missing(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", always_missing)

    class Bad:
        returncode = 1

    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: Bad())
    with pytest.raises(SystemExit, match="pip install failed"):
        setup.ensure_python_deps()

    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: Ok())
    with pytest.raises(SystemExit, match="still missing"):
        setup.ensure_python_deps()

    cia = _cia_tree(tmp_path)
    monkeypatch.setattr(setup, "CIA_TOOLS", cia)
    monkeypatch.setattr(setup, "ensure_python_deps", lambda: None)
    assert setup.main(["--offline"]) == 0
    monkeypatch.setenv("NLPP_OFFLINE", "yes")
    assert setup.main([]) == 0

    (cia / "3dstool" / "3dstool.exe").unlink()
    with pytest.raises(SystemExit, match="offline"):
        setup.main(["--offline"])


# --- integrate + fetch NLPPPATCH ------------------------------------------


integrate = load_module(
    "integrate_nlppatch_into_rebuild", TOOLS / "integrate_nlppatch_into_rebuild.py"
)
fetch_nlp = load_module("fetch_nlppatch_release", TOOLS / "fetch_nlppatch_release.py")


def _community_src(path: Path) -> None:
    path.mkdir(parents=True)
    for i in range(96):
        (path / f"a{i:03d}.dbin2").write_bytes(b"a")
    (path / "k001.dbin2").write_bytes(b"k")
    (path / "t001.dbin2").write_bytes(b"t")
    (path / "p001.dbin2").write_bytes(b"p")
    (path / "z001.dbin2").write_bytes(b"z")


def test_integrate_dry_run_errors_and_write(tmp_path, monkeypatch, capsys):
    import script_inject as si

    saved = si._community_stems
    scratch = ROOT / "out" / "_cov_integrate_test"
    try:
        assert integrate.main(["--src", str(tmp_path / "nope"), "--dst", str(tmp_path / "d")]) == 1
        small = tmp_path / "small"
        small.mkdir()
        (small / "a.dbin2").write_bytes(b"a")
        assert integrate.main(["--src", str(small), "--dst", str(tmp_path / "d")]) == 1

        src = tmp_path / "community"
        _community_src(src)
        dst = tmp_path / "rebuild" / "script"
        dst.mkdir(parents=True)
        (dst / "t001.dbin2").write_bytes(b"keep-t")
        (dst / "p001.dbin2").write_bytes(b"keep-p")
        (dst / "a999.dbin2").write_bytes(b"mt")
        (dst / "k888.dbin2").write_bytes(b"mt")
        nlp = tmp_path / "rebuild" / "NLP_01"
        nlp.mkdir()
        (nlp / "a001.dbin2").write_bytes(b"mt")
        assert integrate.main(["--src", str(src), "--dst", str(dst), "--dry-run"]) == 0
        assert (dst / "a999.dbin2").is_file()
        assert "dry-run" in capsys.readouterr().out

        scratch.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(integrate, "MANIFEST", scratch / "stems.json")
        monkeypatch.setattr(integrate, "README", scratch / "README.md")
        monkeypatch.setattr(si, "coverage_summary", lambda *a, **k: {"english_pct": 28})
        monkeypatch.setattr(si, "nlppatch_script_dir", lambda: tmp_path / "vendor")
        assert integrate.main(["--src", str(src), "--dst", str(dst)]) == 0
        assert not (dst / "a999.dbin2").exists()
        assert not (nlp / "a001.dbin2").exists()
        assert (dst / "t001.dbin2").read_bytes() == b"keep-t"
        assert (dst / "a000.dbin2").read_bytes() == b"a"
        manifest = json.loads((scratch / "stems.json").read_text(encoding="utf-8"))
        assert "z001" in manifest["by_prefix"]["other"]
        assert "t001" in manifest["nlppatch_overlap_skipped_t_p"]
        assert "vendor/NLPPATCH still present" in capsys.readouterr().out

        monkeypatch.setattr(si, "nlppatch_script_dir", lambda: None)
        assert integrate.main(["--src", str(src), "--dst", str(dst)]) == 0
        assert "still present" not in capsys.readouterr().out
    finally:
        si._community_stems = saved
        if hasattr(si, "_nlppatch_stems"):
            del si._nlppatch_stems
        import shutil

        shutil.rmtree(scratch, ignore_errors=True)


def test_fetch_nlppatch_zip_api_and_fallback(tmp_path, monkeypatch, capsys):
    out_dir = tmp_path / "scripts"
    monkeypatch.setattr(fetch_nlp, "SCRIPT_OUT", out_dir)
    blob = _zip(
        {
            "NLPPATCH/romfs/script/bin/script/a001.dbin2": b"db",
            "NLPPPATCH/readme.txt": b"no",
            "other/a002.dbin2": b"skip",
        }
    )
    zpath = tmp_path / "pack.zip"
    zpath.write_bytes(blob)
    assert fetch_nlp.extract_scripts(zpath) == 1
    assert (out_dir / "a001.dbin2").read_bytes() == b"db"

    with pytest.raises(SystemExit, match="zip not found"):
        fetch_nlp.main(["--zip", str(tmp_path / "missing.zip")])

    assert fetch_nlp.main(["--zip", str(zpath)]) == 0
    captured = capsys.readouterr()
    assert "extracted 1" in captured.out
    assert "expected ~168" in captured.err

    keep = tmp_path / "kept.zip"
    keep.write_bytes(blob)
    assert fetch_nlp.main(["--keep-zip", str(keep)]) == 0

    calls = {"n": 0}

    def urlopen(req, timeout=60):
        calls["n"] += 1
        url = req.full_url if hasattr(req, "full_url") else req
        if "api.github.com/repos/LovePlusProject/NLPPPATCH" in str(url):
            if calls["n"] == 1:
                body = json.dumps(
                    {"assets": [{"name": "NLPPPATCH.zip", "browser_download_url": "http://example/z"}]}
                ).encode()
                return _urlopen_cm(body)
            raise OSError("api down")
        if str(url).endswith("/z") or "NLPPATCH" in str(url):
            raise OSError("zip down")
        raise OSError(str(url))

    monkeypatch.setattr(fetch_nlp.urllib.request, "urlopen", urlopen)
    assert fetch_nlp._api_asset_url() == "http://example/z"
    assert fetch_nlp._api_asset_url() is None

    def fail_all(req, timeout=60):
        raise OSError("nope")

    monkeypatch.setattr(fetch_nlp.urllib.request, "urlopen", fail_all)
    with pytest.raises(SystemExit, match="could not download"):
        fetch_nlp.download_zip(tmp_path / "dl.zip")

    items = [
        {"name": f"a{i:03d}.dbin2", "download_url": f"http://example/{i}.dbin2"}
        for i in range(25)
    ]
    items.append({"name": "note.txt"})
    items.append({"name": "bare.dbin2"})

    def ctr_open(req, timeout=60):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "api.github.com" in str(url):
            return _urlopen_cm(json.dumps(items).encode())
        return _urlopen_cm(b"script-bytes")

    monkeypatch.setattr(fetch_nlp.urllib.request, "urlopen", ctr_open)
    assert fetch_nlp.fetch_from_nlppctr() == 26
    assert (out_dir / "bare.dbin2").read_bytes() == b"script-bytes"
    assert "25 scripts" in capsys.readouterr().out

    fresh = tmp_path / "fresh.zip"
    monkeypatch.setattr(fetch_nlp, "download_zip", lambda dest: dest.write_bytes(blob))
    monkeypatch.setattr(fetch_nlp, "fetch_from_nlppctr", lambda: (_ for _ in ()).throw(AssertionError("no")))
    assert fetch_nlp.main(["--keep-zip", str(fresh)]) == 0


def test_fetch_falls_back_to_nlppctr_when_zip_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fetch_nlp, "SCRIPT_OUT", tmp_path / "out")

    def boom(dest):
        raise SystemExit("no zip")

    monkeypatch.setattr(fetch_nlp, "download_zip", boom)
    monkeypatch.setattr(fetch_nlp, "fetch_from_nlppctr", lambda: 120)
    assert fetch_nlp.main(["--keep-zip", str(tmp_path / "absent.zip")]) == 0
    captured = capsys.readouterr()
    assert "falling back" in captured.out
    assert "extracted 120" in captured.out


# --- SMS maildic restore ---------------------------------------------------


restore_sms = load_module("restore_sms_maildic_jpn", TOOLS / "restore_sms_maildic_jpn.py")


def _sms_img(path: Path, payload: bytes) -> None:
    import fake_img as fi

    elements = [(f"{stem}.mdc", payload, b"TXT ", False) for stem in restore_sms.STEMS]
    path.write_bytes(fi.img({restore_sms.PKG: fi.package(elements)}))


def test_restore_sms_maildic(tmp_path, monkeypatch, capsys):
    import fake_img as fi

    vanilla = tmp_path / "vanilla.img.bin"
    target = tmp_path / "live.img.bin"
    _sms_img(vanilla, b"JP!!")
    _sms_img(target, b"EN!!")
    assert restore_sms.restore_maildic(vanilla, target) == 3
    assert b"JP!!" in target.read_bytes()

    def run_main(argv: list[str]) -> int:
        monkeypatch.setattr(restore_sms.sys, "argv", ["restore_sms_maildic_jpn.py", *argv])
        return restore_sms.main()

    monkeypatch.setattr(restore_sms, "find_vanilla_img", lambda: None)
    with pytest.raises(SystemExit, match="vanilla img.bin not found"):
        run_main([])

    monkeypatch.setattr(restore_sms, "find_vanilla_img", lambda: vanilla)
    with pytest.raises(SystemExit, match="target img.bin not found"):
        run_main(["--img", str(tmp_path / "nope.img.bin")])

    assert run_main(["--vanilla", str(vanilla), "--img", str(target), "--no-backup"]) == 0
    assert "done." in capsys.readouterr().out

    _sms_img(target, b"EN!!")
    other = tmp_path / "release" / "bake_img.bin"
    other.parent.mkdir()
    _sms_img(other, b"EN!!")
    monkeypatch.setattr(restore_sms, "iter_deploy_targets", lambda primary: [primary, other])
    assert run_main(["--vanilla", str(vanilla), "--img", str(target), "--all-targets"]) == 0
    assert (target.parent / restore_sms.BAK_NAME).is_file()
    assert b"JP!!" in other.read_bytes()

    broken = tmp_path / "short.img.bin"
    _sms_img(broken, b"XXXX")
    # Vanilla payload longer than the target slot.
    fat = tmp_path / "fat.img.bin"
    elements = [(f"{stem}.mdc", b"TOO-LONG!!", b"TXT ", False) for stem in restore_sms.STEMS]
    fat.write_bytes(fi.img({restore_sms.PKG: fi.package(elements)}))
    with pytest.raises(SystemExit, match=">"):
        restore_sms.restore_maildic(fat, broken)

    missing_stem = tmp_path / "nostem.img.bin"
    missing_stem.write_bytes(fi.img({restore_sms.PKG: fi.package([("other.mdc", b"xx", b"TXT ", False)])}))
    with pytest.raises(SystemExit, match="missing"):
        restore_sms.restore_maildic(missing_stem, target)


# --- near-complete modules: last branches ---------------------------------


def test_run_log_append_and_oserror(tmp_path, capsys):
    import run_log

    assert run_log.default_log_path().name == "log.txt"
    path = tmp_path / "log.txt"
    path.write_text("no-nl", encoding="utf-8")
    assert run_log.write_log("more", dest=path, append=True) == path
    assert path.read_text(encoding="utf-8").startswith("no-nl\n")
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    assert run_log.write_log("z", dest=blocker / "child.txt") is None
    assert "could not write" in capsys.readouterr().out


def test_overall_bad_env_empty_finish_and_bound(monkeypatch, capsys):
    import overall_progress

    monkeypatch.setenv("NLPP_OVERALL_LO", "nope")
    assert overall_progress._env_float("NLPP_OVERALL_LO", 4.0) == 4.0
    overall_progress.OverallBar([]).finish()
    monkeypatch.delenv("NLPP_OVERALL_LO", raising=False)
    monkeypatch.delenv("NLPP_OVERALL_HI", raising=False)
    overall_progress.OverallBar([("pack", 1)]).finish()
    assert "done" in capsys.readouterr().out
    with overall_progress.overall_scope([("pack", 1)]):
        overall_progress.finish_bound()
    assert overall_progress._bound is None


def test_scratch_reparse_and_non_windows_long_path(tmp_path, monkeypatch):
    import ctypes

    import scratch_cleanup

    class Boom:
        def is_symlink(self):
            return False

        def is_junction(self):
            raise OSError("junction")

    assert scratch_cleanup.is_reparse_dir(Boom()) is False

    class Windll:
        @property
        def kernel32(self):
            raise RuntimeError("no kernel")

    monkeypatch.setattr(ctypes, "windll", Windll(), raising=False)
    monkeypatch.setattr(scratch_cleanup.sys, "platform", "win32")
    folder = tmp_path / "dir"
    folder.mkdir()
    assert scratch_cleanup.is_reparse_dir(folder) is False

    monkeypatch.setattr(scratch_cleanup.sys, "platform", "linux")
    assert scratch_cleanup.long_path(folder) == folder


def test_run_timer_heartbeat_and_context(monkeypatch, capsys):
    import run_timer

    monkeypatch.setenv("NLPP_PLAIN_LOG", "1")
    timer = run_timer.RunTimer("hb", heartbeat_s=0.02)
    time.sleep(0.12)
    timer.start_heartbeat()
    timer.finish("hb done")
    assert "still running" in capsys.readouterr().out

    class Live:
        def __init__(self):
            self.owner = None
            self.logs: list[str] = []

        def try_acquire(self, who):
            self.owner = who
            return True

        def log(self, line):
            self.logs.append(line)

        def refresh(self, force=False):
            return None

        def release(self, who):
            self.owner = None

    live = Live()
    monkeypatch.setattr(run_timer, "live", live)
    timer = run_timer.RunTimer("live", heartbeat_s=0.02)
    timer.mark("stage")
    assert live.logs and "stage" in live.logs[-1]
    live.owner = object()
    time.sleep(0.08)
    timer.finish("live done")

    with run_timer.RunTimer("ok", heartbeat_s=None) as entered:
        assert entered.label == "ok"
    assert "OK" in capsys.readouterr().out

    with pytest.raises(RuntimeError):
        with run_timer.RunTimer("bad", heartbeat_s=None):
            raise RuntimeError("boom")
    assert "failed" in capsys.readouterr().out

    with pytest.raises(KeyboardInterrupt):
        with run_timer.RunTimer("key", heartbeat_s=None):
            raise KeyboardInterrupt
    assert "aborted" in capsys.readouterr().out
    assert threading.active_count() >= 1


def test_l2mgtex_rejects_bad_headers_and_formats():
    import numpy as np
    from PIL import Image

    import l2mgtex

    with pytest.raises(ValueError, match="too short"):
        l2mgtex.parse_header(b"\x00" * 8)
    bad = bytearray(l2mgtex.HEADER_LEN + 4)
    bad[0:16] = np.array([8, 8, 99, 8], "<u4").tobytes()
    with pytest.raises(ValueError, match="length"):
        l2mgtex.parse_header(bytes(bad))
    header = bytearray(l2mgtex.HEADER_LEN)
    header[0:16] = np.array([8, 8, 99, 4], "<u4").tobytes()
    blob = bytes(header) + b"\x00" * 4
    with pytest.raises(ValueError, match="not supported"):
        l2mgtex.decode(blob)
    im = Image.new("RGBA", (8, 8))
    with pytest.raises(ValueError, match="not supported"):
        l2mgtex.encode_like(blob, im)
    with pytest.raises(ValueError, match="image"):
        etc = bytearray(l2mgtex.HEADER_LEN)
        etc[0:16] = np.array([8, 8, l2mgtex.FMT_ETC1A4, 8 * 8], "<u4").tobytes()
        l2mgtex.encode_like(bytes(etc) + bytes(64), Image.new("RGBA", (4, 4)))

    monkey = pytest.MonkeyPatch()
    monkey.setattr(l2mgtex, "encode_etc1a4_pixels", lambda *a, **k: b"xx")
    try:
        with pytest.raises(ValueError, match="encoded"):
            l2mgtex.encode_like(bytes(etc) + bytes(64), Image.new("RGBA", (8, 8)))
    finally:
        monkey.undo()


def test_smdh_error_branches(tmp_path, monkeypatch):
    import smdh_meta

    assert smdh_meta.utf16_field("ab", 3) == b"\x00\x00\x00"
    monkeypatch.setattr(smdh_meta, "TITLE_SLOT", 1)
    with pytest.raises(ValueError, match="title slot"):
        smdh_meta.title_slot()
    with pytest.raises(ValueError, match="too small"):
        smdh_meta.patch_smdh(b"SMDH")
    with pytest.raises(ValueError, match="not SMDH"):
        smdh_meta.patch_smdh(b"XXXX" + bytes(smdh_meta.SMDH_SIZE))
    empty = tmp_path / "exefs"
    empty.mkdir()
    (empty / "icon_extra.bin").write_bytes(b"SMDH" + bytes(8))
    assert smdh_meta.find_exefs_icon(empty).name == "icon_extra.bin"
    (empty / "icon_extra.bin").unlink()
    with pytest.raises(FileNotFoundError):
        smdh_meta.find_exefs_icon(empty)
    with pytest.raises(ValueError, match="not an NCCH"):
        smdh_meta.read_ncch_product_code(b"nope")
    with pytest.raises(ValueError, match="unknown CIA region"):
        smdh_meta.resolve_region("mars")


def test_profile_birthday_window_length_guard(monkeypatch):
    import patch_profile_birthday as bday

    monkeypatch.setattr(bday, "SITE", bday.SITE + 4)
    with pytest.raises(ValueError, match="window"):
        bday.build_window()


def test_camera_defaults_error_branches(monkeypatch):
    import patch_camera_restore_default as cam

    real_len = cam.CAMERA_DEFAULTS_CAVE_LEN
    monkeypatch.setattr(cam, "CAMERA_DEFAULTS_CAVE_LEN", 1)
    with pytest.raises(ValueError, match="cave"):
        cam.build_cave()
    monkeypatch.setattr(cam, "CAMERA_DEFAULTS_CAVE_LEN", real_len)

    data = bytearray(cam.ADDR_CAMERA_DEFAULTS_CAVE + cam.CAMERA_DEFAULTS_CAVE_LEN)
    for site, _ in cam.SITES:
        data[site : site + 4] = cam.bl(site, cam.ADDR_SET_SOFTKEY)
    data[cam.ADDR_CAMERA_DEFAULTS_CAVE] = 1
    with pytest.raises(ValueError, match="not empty"):
        cam.apply_patch(data)

    fresh = bytearray(cam.ADDR_CAMERA_DEFAULTS_CAVE + cam.CAMERA_DEFAULTS_CAVE_LEN)
    with pytest.raises(ValueError, match="unexpected insn"):
        cam.apply_patch(fresh)

    ok = bytearray(cam.ADDR_CAMERA_DEFAULTS_CAVE + cam.CAMERA_DEFAULTS_CAVE_LEN)
    for site, _ in cam.SITES:
        ok[site : site + 4] = cam.bl(site, cam.ADDR_SET_SOFTKEY)
    assert cam.apply_patch(ok) is True
    ok[cam.ADDR_CAMERA_DEFAULTS_CAVE] ^= 0xFF
    with pytest.raises(ValueError, match="cave bytes differ"):
        cam.apply_patch(ok)


def test_commu_header_error_branches(monkeypatch):
    import patch_commu_settings_header as commu

    real_len = commu.COMMU_HEADER_CAVE_LEN
    monkeypatch.setattr(commu, "COMMU_HEADER_CAVE_LEN", 1)
    with pytest.raises(ValueError, match="header cave"):
        commu.build_cave()
    monkeypatch.setattr(commu, "COMMU_HEADER_CAVE_LEN", real_len)

    size = commu.ADDR_COMMU_HEADER_CAVE + 64
    bad = bytearray(size)
    with pytest.raises(ValueError, match="unexpected insn"):
        commu.apply_patch(bad)

    occupied = bytearray(size)
    occupied[commu.SITE : commu.SITE + 4] = commu.VANILLA_SITE
    occupied[commu.ADDR_COMMU_HEADER_CAVE] = 1
    with pytest.raises(ValueError, match="not empty"):
        commu.apply_patch(occupied)

    ok = bytearray(size)
    ok[commu.SITE : commu.SITE + 4] = commu.VANILLA_SITE
    assert commu.apply_patch(ok) is True
    ok[commu.ADDR_COMMU_HEADER_CAVE] ^= 0xFF
    with pytest.raises(ValueError, match="cave bytes differ"):
        commu.apply_patch(ok)


def test_verify_name_input_main(tmp_path, monkeypatch, capsys):
    import hashlib

    verify_mod = load_module("verify_name_input_code_main", TOOLS / "verify_name_input_code.py")
    snap = tmp_path / "snap.json"
    code = tmp_path / "code.bin"
    vanilla = tmp_path / "vanilla.bin"
    code.write_bytes(b"patched")
    vanilla.write_bytes(b"vanilla")
    snap.write_text(
        json.dumps(
            {
                "vanilla_sha256": hashlib.sha256(b"vanilla").hexdigest(),
                "final_sha256": hashlib.sha256(b"patched").hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(verify_mod.verify, "__defaults__", (snap,))
    monkeypatch.delenv("NLPP_VANILLA_CODE", raising=False)
    assert verify_mod.main(["--code", str(code)]) == 0
    assert "matches" in capsys.readouterr().out
    monkeypatch.setenv("NLPP_VANILLA_CODE", str(vanilla))
    assert verify_mod.main(["--code", str(code)]) == 0
    assert verify_mod.main(["--code", str(tmp_path / "missing.bin"), "--vanilla", str(vanilla)]) == 1
    assert "verify" in capsys.readouterr().err
