"""Offline coverage for tools that do not need a game dump or the network.

Every output path is pointed at tmp_path. urllib.request.urlopen is blocked
unless a test installs its own stub. The mcp package is stubbed before
ab_mcp_server is imported.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import fake_img as fi
from conftest import TOOLS, load_module
from patch_names import DbinEntry, SDL2Data, build_dbin2

# --- mcp stub must exist before ab_mcp_server imports it -----------------

_MCP_NAMES = ("mcp", "mcp.server", "mcp.server.fastmcp")
_SAVED_MCP = {name: sys.modules.get(name) for name in _MCP_NAMES}


class _FastMCP:
    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: dict[str, object] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco

    def run(self) -> str:
        return "ran"


_fastmcp_mod = types.ModuleType("mcp.server.fastmcp")
_fastmcp_mod.FastMCP = _FastMCP
sys.modules["mcp"] = types.ModuleType("mcp")
sys.modules["mcp.server"] = types.ModuleType("mcp.server")
sys.modules["mcp.server.fastmcp"] = _fastmcp_mod

spot = load_module("cov_spotpass", TOOLS / "build_spotpass_inject.py")
audit = load_module("cov_audit_manaka", TOOLS / "audit_manaka_vs_makein.py")
fit = load_module("cov_fit_ui", TOOLS / "fit_ui_masters.py")
sms = load_module("cov_translate_sms", TOOLS / "translate_sms_en.py")
rn = load_module("cov_restore_nlpp", TOOLS / "restore_nlppatch_nickname_tokens.py")
epm = load_module("cov_export_metrics", TOOLS / "export_progress_metrics.py")
ub = load_module("cov_import_ui_buttons", TOOLS / "import_ui_buttons_bundle.py")
nl = load_module("cov_import_nlppctr", TOOLS / "import_nlppctr_textures.py")
br = load_module("cov_build_call_romaji", TOOLS / "build_call_romaji_match.py")
ab = load_module("cov_ab_mcp", TOOLS / "ab_mcp_server.py")

for _name, _prev in _SAVED_MCP.items():
    if _prev is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _prev


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError(f"network blocked: {args!r} {kwargs!r}")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", boom)


def _png(path: Path, w: int, h: int, color=(255, 0, 0, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (w, h), color).save(path)


def _png_bytes(w: int = 4, h: int = 4, color=(10, 20, 30, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


class _Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return self.data
        return self.data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


# ---------------------------------------------------------------------------
# build_spotpass_inject
# ---------------------------------------------------------------------------

_PID = 0x00040000000F4E00


def _boss_blob(info: bytes, *, unk: int = 7, datatype: int = 3, nsid: int = 1, ver: int = 9, prefix: bytes = b"xx") -> bytes:
    hdr = struct.pack(">QIIIII", _PID, unk, datatype, len(info), nsid, ver)
    return prefix + hdr + b"ZZ"


def _write_spot_sources(directory: Path, info: bytes = b"PAYLOAD-INFO", **kwargs) -> bytes:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "info.dat").write_bytes(info)
    (directory / "info.dat.boss.decrypted").write_bytes(_boss_blob(info, **kwargs))
    return info


def _bind_spot(monkeypatch, tmp_path: Path, info: bytes = b"PAYLOAD-INFO", **kwargs):
    src = tmp_path / "spotpass"
    out = tmp_path / "out"
    boss = tmp_path / "azahar" / "boss"
    _write_spot_sources(src, info, **kwargs)
    monkeypatch.setattr(spot, "SPOTPASS_DIR", src)
    monkeypatch.setattr(spot, "OUT_ROOT", out)
    monkeypatch.setattr(spot, "AZAHAR_BOSS", boss)
    return src, out, boss


def test_spot_header_and_blob_layouts(tmp_path, monkeypatch):
    info = b"INFO-BYTES"
    _bind_spot(monkeypatch, tmp_path, info, unk=4, datatype=8, ver=2)
    loaded_info, decrypted = spot._load_sources()
    meta = spot.parse_payload_header(decrypted, loaded_info)
    assert meta["program_id"] == _PID
    assert meta["unk"] == 4 and meta["datatype"] == 8
    assert meta["payload_size"] == len(info) and meta["ns_data_id"] == 1
    assert meta["version"] == 2 and meta["offset"] == 2

    hdr = spot.build_boss_header(meta, len(info), download_date=0x1_0000_0005)
    assert len(hdr) == spot.BOSS_HEADER_LEN and hdr[0] == 0x18
    assert struct.unpack_from(">I", hdr, 0x10)[0] == 5
    assert struct.unpack_from(">Q", hdr, 0x18)[0] == _PID
    assert struct.unpack_from(">I", hdr, 0x28)[0] == len(info)

    plain = spot.build_blob(meta, info, pad_hle=False)
    padded = spot.build_blob(meta, info, pad_hle=True)
    assert plain == hdr[:0] or plain[spot.BOSS_HEADER_LEN :] == info
    assert len(plain) == spot.BOSS_HEADER_LEN + len(info)
    assert len(padded) == spot.BOSS_HEADER_LEN + spot.HLE_PAD_SIZE
    assert padded.endswith(b"\x00")

    with pytest.raises(ValueError, match="program ID not found"):
        spot.parse_payload_header(b"no-pid-here", info)
    bad = _boss_blob(info, nsid=2)
    with pytest.raises(ValueError, match="unexpected header"):
        spot.parse_payload_header(bad, info)
    short = _boss_blob(info)
    with pytest.raises(ValueError, match="unexpected header"):
        spot.parse_payload_header(short, info + b"EXTRA")


def test_spot_missing_sources(tmp_path, monkeypatch):
    src = tmp_path / "empty"
    src.mkdir()
    monkeypatch.setattr(spot, "SPOTPASS_DIR", src)
    with pytest.raises(FileNotFoundError, match="info.dat"):
        spot._load_sources()
    (src / "info.dat").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="info.dat.boss.decrypted"):
        spot._load_sources()


def test_spot_write_tree_and_install_azahar(tmp_path, monkeypatch):
    _src, _out, boss = _bind_spot(monkeypatch, tmp_path)
    blob = b"BLOB"
    dest = spot.write_tree(tmp_path / "tree", blob, include_readme=True)
    assert dest.read_bytes() == blob
    assert (tmp_path / "tree" / "info.dat").read_bytes() == blob
    assert "SpotPass" in (tmp_path / "tree" / "README.txt").read_text(encoding="utf-8")
    bare = spot.write_tree(tmp_path / "bare", blob, include_readme=False)
    assert bare.read_bytes() == blob
    assert not (tmp_path / "bare" / "README.txt").exists()

    boss.parent.mkdir(parents=True, exist_ok=True)
    (boss.parent / "metadata").write_bytes(b"keep")
    first = spot.install_azahar(blob)
    assert first.read_bytes() == blob
    assert (boss.parent / "metadata").read_bytes() == b"keep"
    assert (boss.parent / "user").is_dir()
    (boss.parent / "metadata").unlink()
    second = spot.install_azahar(blob + b"2")
    assert second.read_bytes() == blob + b"2"
    assert (boss.parent / "metadata").read_bytes() == b"\x00" * 0x20


def test_spot_build_inject_modes(tmp_path, monkeypatch, capsys):
    info = b"PAY"
    _src, out, boss = _bind_spot(monkeypatch, tmp_path, info)
    with pytest.raises(ValueError, match="unknown SpotPass mode"):
        spot.build_inject("nope")

    flat = spot.build_inject("real3ds", quiet=True)
    assert capsys.readouterr().out == ""
    assert flat == out / "spotpass_real3ds" / "info.dat"
    assert flat.stat().st_size == spot.BOSS_HEADER_LEN + len(info)
    assert (flat.parent / "README.txt").is_file()
    assert not (boss / "info.dat").exists()

    az = spot.build_inject("azahar", out_dir=tmp_path / "az-out")
    err = capsys.readouterr().out
    assert "padded for stock Azahar" in err
    assert az.stat().st_size == spot.BOSS_HEADER_LEN + spot.HLE_PAD_SIZE
    assert (boss / "info.dat").is_file()
    assert not (tmp_path / "az-out" / "README.txt").exists()

    quiet_az = spot.build_inject("azahar", out_dir=tmp_path / "quiet-az", quiet=True)
    assert quiet_az.is_file() and capsys.readouterr().out == ""

    exact = spot.build_inject(
        "azahar_exact", out_dir=tmp_path / "exact", install_azahar_sdmc=False, quiet=False
    )
    text = capsys.readouterr().out
    assert "mode=azahar_exact" in text
    assert "Azahar SDMC" not in text
    assert exact.stat().st_size == spot.BOSS_HEADER_LEN + len(info)

    forced = spot.build_inject("real3ds", out_dir=tmp_path / "force", install_azahar_sdmc=True)
    assert "FBI" in capsys.readouterr().out
    assert (tmp_path / "force" / "00000321" / "boss" / "info.dat").is_file()
    assert forced.name == "info.dat"


def test_spot_main_cli(tmp_path, monkeypatch, capsys):
    _bind_spot(monkeypatch, tmp_path, b"Z")
    out = tmp_path / "cli"
    assert spot.main(["--real3ds", "--out", str(out), "--no-install-azahar"]) == 0
    assert (out / "README.txt").is_file()
    assert spot.main(["--azahar", "--out", str(tmp_path / "cli-az"), "--install-azahar"]) == 0
    assert "padded" in capsys.readouterr().out
    assert spot.main(["--azahar-exact", "--out", str(tmp_path / "cli-ex")]) == 0

    monkeypatch.setattr(spot, "SPOTPASS_DIR", tmp_path / "missing-src")
    assert spot.main(["--out", str(tmp_path / "bad")]) == 1
    assert "error:" in capsys.readouterr().err

    src = tmp_path / "badhdr"
    _write_spot_sources(src, b"Z", nsid=9)
    monkeypatch.setattr(spot, "SPOTPASS_DIR", src)
    assert spot.main(["--out", str(tmp_path / "bad2")]) == 1
    assert "unexpected header" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# audit_manaka_vs_makein
# ---------------------------------------------------------------------------


def _dialog_xml(parts: list[str]) -> str:
    body = "".join(f"<Dialog>{part}</Dialog>" for part in parts)
    return f"<root><!-- {'x' * 80} -->{body}</root>"


def _allow_urlopen(monkeypatch, handler):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", handler)


def test_audit_fetch_normalize_and_classify(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    calls: list[str] = []

    def urlopen(req, timeout=30):
        url = getattr(req, "full_url", str(req))
        calls.append(url)
        if url.endswith("/tiny.xml"):
            return _Body(b"<root/>")
        if url.endswith("/stale.xml"):
            return _Body(_dialog_xml(["downloaded"]).encode())
        raise OSError("offline")

    _allow_urlopen(monkeypatch, urlopen)

    hit = cache / "Done_cached.xml"
    hit.write_bytes(b"y" * 51)
    assert audit.fetch_makein_any("cached", cache) == hit
    assert calls == []

    stale = cache / "Done_stale.xml"
    stale.write_bytes(b"y" * 50)
    got = audit.fetch_makein_any("stale", cache)
    assert got is not None and got.stat().st_size > 50
    assert any(url.endswith("/stale.xml") for url in calls)

    assert audit.fetch_makein_any("tiny", cache) is None
    assert (cache / "Done_tiny.xml").stat().st_size <= 50
    assert audit.fetch_makein_any("boom", cache) is None

    assert audit.normalize_compare("  ▲高嶺＊＊▲   hi ") == audit.normalize_compare("Takane hi")
    assert "HERO" in audit.normalize_compare("Takane")

    eng = tmp_path / "scripts" / "tExact.xml"
    eng.parent.mkdir()
    eng.write_text(_dialog_xml(["Hello", "Takane hi"]), encoding="utf-8")
    (cache / "Done_tExact.xml").write_text(_dialog_xml(["Hello", "▲高嶺＊＊▲ hi"]), encoding="utf-8")
    row = audit.classify_file(eng, cache)
    assert row["status"] == "token_only"
    assert row["exact"] == 1 and row["token_only"] == 1
    assert row["eng"].endswith("tExact.xml")
    assert row["makein"].endswith("Done_tExact.xml")

    many = tmp_path / "scripts" / "tMany.xml"
    many.write_text(_dialog_xml([f"Takane {i}" for i in range(9)]), encoding="utf-8")
    (cache / "Done_tMany.xml").write_text(
        _dialog_xml([f"▲高嶺＊＊▲ {i}" for i in range(9)]), encoding="utf-8"
    )
    capped = audit.classify_file(many, cache)
    assert capped["token_only"] == 9 and len(capped["diffs"]) == 8

    both = tmp_path / "scripts" / "tBoth.xml"
    both.write_text(_dialog_xml(["Takane", "nope"]), encoding="utf-8")
    (cache / "Done_tBoth.xml").write_text(_dialog_xml(["▲高嶺＊＊▲", "other"]), encoding="utf-8")
    mixed = audit.classify_file(both, cache)
    assert mixed["status"] == "content_diff"
    assert {d["kind"] for d in mixed["diffs"]} == {"token_only", "content_diff"}

    flood = tmp_path / "scripts" / "tFlood.xml"
    flood.write_text(_dialog_xml([f"left {i}" for i in range(13)]), encoding="utf-8")
    (cache / "Done_tFlood.xml").write_text(_dialog_xml([f"right {i}" for i in range(13)]), encoding="utf-8")
    flooded = audit.classify_file(flood, cache)
    assert flooded["content_diff"] == 13 and len(flooded["diffs"]) == 12

    mismatch = tmp_path / "scripts" / "tCount.xml"
    mismatch.write_text(_dialog_xml(["only"]), encoding="utf-8")
    (cache / "Done_tCount.xml").write_text(_dialog_xml(["a", "b"]), encoding="utf-8")
    counted = audit.classify_file(mismatch, cache)
    assert counted["status"] == "count_mismatch" and counted["diffs"][0]["eng_n"] == 1

    stub_eng = tmp_path / "scripts" / "tStub.xml"
    stub_eng.write_text(_dialog_xml([]), encoding="utf-8")
    (cache / "Done_tStub.xml").write_text(_dialog_xml([]), encoding="utf-8")
    stub = audit.classify_file(stub_eng, cache)
    assert stub["status"] == "exact" and stub["empty_stub"] is True

    same = tmp_path / "scripts" / "tSame.xml"
    same.write_text(_dialog_xml(["Hello"]), encoding="utf-8")
    (cache / "Done_tSame.xml").write_text(_dialog_xml(["Hello"]), encoding="utf-8")
    assert audit.classify_file(same, cache)["status"] == "exact"

    missing = tmp_path / "scripts" / "tGone.xml"
    missing.write_text(_dialog_xml(["x"]), encoding="utf-8")
    gone = audit.classify_file(missing, tmp_path / "empty-cache")
    assert gone["status"] == "missing_makein" and gone["makein"] is None


def test_audit_main_verdicts(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    scripts = root / "scripts"
    cache = root / "cache"
    scripts.mkdir(parents=True)
    monkeypatch.setattr(audit, "ROOT", root)

    class _Bare:
        def write(self, _text):
            return None

        def flush(self):
            return None

    captured_out = sys.stdout
    monkeypatch.setattr(sys, "stdout", _Bare())
    assert audit.main(["--scripts", str(tmp_path / "bare"), "--cache", str(cache), "--out", str(root / "bare.json")]) == 1
    monkeypatch.setattr(sys, "stdout", captured_out)

    assert audit.main(["--scripts", str(tmp_path / "nope"), "--cache", str(cache), "--out", str(root / "a.json")]) == 1
    assert "no t*.xml" in capsys.readouterr().err

    (scripts / "note.xml").write_text("<root/>", encoding="utf-8")
    assert audit.main(["--scripts", str(scripts), "--cache", str(cache), "--out", str(root / "b.json"), "--workers", "0"]) == 1

    def urlopen(req, timeout=30):
        url = getattr(req, "full_url", str(req))
        if str(url).endswith("/t000.xml"):
            return _Body(b"p" * 64)
        raise OSError("offline")

    _allow_urlopen(monkeypatch, urlopen)
    cache.mkdir(parents=True, exist_ok=True)

    (scripts / "tStub.xml").write_text(_dialog_xml([]), encoding="utf-8")
    (cache / "Done_tStub.xml").write_text(_dialog_xml([]), encoding="utf-8")
    out = root / "ok.json"
    assert audit.main(["--scripts", str(scripts), "--cache", str(cache), "--out", str(out), "--workers", "2"]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["verdict_100_pct_fan_equivalent"] is True
    assert report["fan_equivalent_dialog_pct"] == 0.0
    assert report["empty_stub_files"] == 1
    assert "T" in report["generated_at"]
    assert "Non-equivalent" not in capsys.readouterr().out

    (scripts / "tBad.xml").write_text(_dialog_xml(["one"]), encoding="utf-8")
    (cache / "Done_tBad.xml").write_text(_dialog_xml(["zzz"]), encoding="utf-8")
    (scripts / "tMiss.xml").write_text(_dialog_xml(["q"]), encoding="utf-8")
    bad_out = root / "bad.json"
    assert audit.main(["--scripts", str(scripts), "--cache", str(cache), "--out", str(bad_out)]) == 2
    bad = json.loads(bad_out.read_text(encoding="utf-8"))
    assert bad["verdict_100_pct_fan_equivalent"] is False
    assert "Non-equivalent" in capsys.readouterr().out
    assert bad["files_by_status"]["content_diff"] >= 1
    assert bad["files_by_status"]["missing_makein"] >= 1


# ---------------------------------------------------------------------------
# fit_ui_masters
# ---------------------------------------------------------------------------


def _arc_pkg(files: dict[str, bytes], *, extra_txt: bool = False) -> bytes:
    elements = [("A.arc", fi.darc(files), b"ARC ", True)]
    if extra_txt:
        elements.append(("n.txt", b"z", b"TXT ", False))
    return fi.package(elements)


def test_fit_helpers_and_main(tmp_path, monkeypatch, capsys):
    same = Image.new("RGBA", (4, 4), (1, 2, 3, 255))
    assert fit.fit_contain(same, 4, 4).size == (4, 4)
    fitted = fit.fit_contain(Image.new("RGBA", (2, 2), (9, 9, 9, 255)), 8, 8)
    assert fitted.size == (8, 8) and fitted.getpixel((3, 3))[3] == 255
    assert fit.fit_contain(Image.new("RGBA", (20, 10), (4, 5, 6, 255)), 8, 4).size == (8, 4)

    bclims = {
        "__foo": (1,),
        "foo": (1,),
        "c_bar": (1,),
        "alb_bar": (1,),
        "baz": (1,),
        "qux": (1,),
        "stem": (1,),
        "new_bar": (1,),
    }
    assert fit.guess_targets("__foo", bclims) == ["__foo", "foo"]
    assert fit.guess_targets("new_bar", bclims) == ["new_bar", "c_bar", "alb_bar"]
    assert fit.guess_targets("baz_upper", bclims) == ["baz"]
    assert fit.guess_targets("qux_rgba4", bclims) == ["qux"]
    assert fit.guess_targets("stem_eng", bclims) == ["stem"]
    assert fit.guess_targets("nope", bclims) == []

    decoded = fit.decode_bclim(fi.bclim(8, 8, 8))
    assert decoded is not None and decoded.size == (8, 8)
    assert fit.decode_bclim(fi.bclim(4, 4, 0xD, pixels=b"\x00" * 16)) is None

    root = tmp_path / "root"
    assets = root / "assets" / "images"
    monkeypatch.setattr(fit, "ROOT", root)
    monkeypatch.setattr(fit, "ASSETS", assets)
    monkeypatch.setattr(fit, "REPORT", root / "out" / "fit_ui_masters" / "fit_report.json")

    intro = _arc_pkg(
        {
            "timg/title.bclim": fi.bclim(8, 8, 8),
            "timg/fade_black.bclim": fi.bclim(4, 4, 0xD, pixels=b"\x00" * 8),
            "timg/mystery.bclim": fi.bclim(4, 4, 0x99, pixels=b"\x11" * 16),
            "timg/bad.bclim": b"NOPE",
            "note.txt": b"x",
        },
        extra_txt=True,
    )
    other = _arc_pkg({"timg/side.bclim": fi.bclim(4, 4, 8)})
    last = _arc_pkg({"timg/end.bclim": fi.bclim(4, 2, 8)})
    option = _arc_pkg(
        {
            "timg/hello.bclim": fi.bclim(8, 8, 8),
            "timg/fresh.bclim": fi.bclim(8, 8, 8),
            "timg/plate.bclim": fi.bclim(16, 8, 8),
            "timg/same.bclim": fi.bclim(4, 4, 8),
            "timg/bad.bclim": b"NOPE",
            "note.txt": b"x",
        }
    )
    img_path = tmp_path / "img.bin"
    title_pkg = _arc_pkg({"timg/unused.bclim": fi.bclim(4, 4, 8)})
    msel9 = _arc_pkg({"timg/other.bclim": fi.bclim(4, 4, 8)})
    img_path.write_bytes(
        fi.img({5192: intro, 5194: other, 5196: last, 5239: msel9, 5247: option, 5261: title_pkg})
    )
    monkeypatch.setattr(fit, "find_vanilla_img", lambda: img_path)

    meta = root / "out" / "fit_ui_masters"
    meta.mkdir(parents=True)
    (meta / "size_mismatch.json").write_text(
        json.dumps(
            [
                {"png": "assets/wide.png", "bclim": [8, 4]},
                {"png": "assets/missing.png", "bclim": [2, 2]},
            ]
        ),
        encoding="utf-8",
    )
    (meta / "no_bclim.json").write_text(
        json.dumps(
            [
                {"pkg": 5247, "png": "assets/images/option.check/timg/gone.png", "stem": "new_hello"},
                {"pkg": 5247, "png": "assets/images/option.check/timg/zzz.png", "stem": "zzz"},
                {"pkg": 5247, "png": "assets/images/option.check/timg/new_hello.png", "stem": "new_hello"},
                {"pkg": 5247, "png": "assets/images/option.check/timg/new_fresh.png", "stem": "new_fresh"},
            ]
        ),
        encoding="utf-8",
    )
    _png(root / "assets" / "wide.png", 20, 10)
    timg = assets / "option.check" / "timg"
    _png(timg / "hello.png", 2, 2)
    _png(timg / "new_hello.png", 12, 6, (0, 255, 0, 255))
    _png(timg / "new_fresh.png", 10, 10, (0, 0, 255, 255))
    _png(timg / "zzz.png", 6, 6)
    _png(timg / "plate.png", 40, 12)
    _png(timg / "same.png", 4, 4)
    _png(timg / "other.png", 5, 5)
    _png(assets / "Intro111.check" / "timg" / "mystery.png", 3, 3)
    _png(assets / "Title.check" / "timg" / "Com_M_Sel_Btn_Efe03.png", 30, 10, (255, 255, 0, 255))

    assert fit.main() == 0
    assert Image.open(root / "assets" / "wide.png").size == (8, 4)
    assert Image.open(timg / "hello.png").size == (8, 8)
    assert Image.open(timg / "fresh.png").size == (8, 8)
    assert Image.open(timg / "plate.png").size == (16, 8)
    assert not (assets / "Intro111.check" / "timg" / "mystery.png").exists()
    black = Image.open(assets / "Intro111.check" / "timg" / "fade_black.png")
    assert black.size == (4, 4) and black.getpixel((0, 0)) == (0, 0, 0, 255)
    assert (assets / "Intro111.check" / "timg" / "title.png").is_file()
    assert (assets / "Intro203.check" / "timg" / "side.png").is_file()
    assert (assets / "Intro304.check" / "timg" / "end.png").is_file()
    moved = assets / "NCommonMSel(9).check" / "timg" / "Com_M_Sel_Btn_Efe03.png"
    assert Image.open(moved).size == (218, 44)
    report = json.loads(fit.REPORT.read_text(encoding="utf-8"))
    ops = {row["op"] for row in report}
    assert {"resize", "remap", "intro_dump", "intro_black", "intro_skip_jp", "chrome_fit", "relocate"} <= ops
    assert "actions ->" in capsys.readouterr().out

    (meta / "size_mismatch.json").unlink()
    (meta / "no_bclim.json").unlink()
    assert fit.main() == 0


# ---------------------------------------------------------------------------
# translate_sms_en
# ---------------------------------------------------------------------------


def _mail_xml(rows: list[tuple[str, str]]) -> str:
    parts = ["<Dictionary>"]
    for hex_id, text in rows:
        parts.append(f'<Entry><JapaneseText hex="{hex_id}">{text}</JapaneseText></Entry>')
    parts.append("</Dictionary>")
    return "".join(parts)


def _install_openai(monkeypatch, create):
    seen: dict[str, str] = {}

    class _OpenAI:
        def __init__(self, api_key=None):
            seen["key"] = api_key
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))

    mod = types.ModuleType("openai")
    mod.OpenAI = _OpenAI
    monkeypatch.setitem(sys.modules, "openai", mod)
    return seen


def _chat_response(content):
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


def test_sms_parse_pack_and_map(tmp_path):
    path = tmp_path / "in.xml"
    path.write_text(
        "<Dictionary>"
        '<Entry><JapaneseText hex="1">line&#13;&#10;one</JapaneseText></Entry>'
        '<Entry><JapaneseText hex="2"></JapaneseText></Entry>'
        "<Entry><NoText/></Entry>"
        '<Entry><JapaneseText hex="3"/></Entry>'
        "</Dictionary>",
        encoding="utf-8",
    )
    rows = sms.parse_entries(path)
    assert rows[0] == ("1", "line\none")
    assert rows[1] == ("2", "")
    assert rows[2] == ("3", "")

    out = tmp_path / "out.xml"
    sms.write_xml(out, [("1", "Hello"), ("2", "")])
    written = sms.parse_entries(out)
    assert written[0] == ("1", "Hello")
    assert written[1][1] == ""

    blob = sms.pack_nlpmail([("", "Hi"), ("255", "A")])
    assert blob.startswith(b"NLPMAIL1") and len(blob) % 4 == 0
    assert struct.unpack_from("<I", blob, 8)[0] == 2
    assert struct.unpack_from("<Q", blob, 12)[0] == 0

    assert sms.load_map(tmp_path / "missing.json") == {}
    wrapped = tmp_path / "wrap.json"
    wrapped.write_text('{"translations": {"あ": "a"}}', encoding="utf-8")
    assert sms.load_map(wrapped) == {"あ": "a"}
    raw = tmp_path / "raw.json"
    raw.write_text('{"い": "b"}', encoding="utf-8")
    assert sms.load_map(raw) == {"い": "b"}
    dest = tmp_path / "sub" / "map.json"
    sms.save_map(dest, {"う": "c"})
    assert dest.read_text(encoding="utf-8").endswith("\n")

    src = tmp_path / "src.xml"
    src.write_text(_mail_xml([("1", "こんにちは"), ("2", "Hello"), ("3", "こんにちは")]), encoding="utf-8")
    assert sms.collect_pending([src], {"こんにちは": "hi"}) == []
    assert sms.collect_pending([src], {}) == ["こんにちは"]
    assert sms.apply_map([("1", "こんにちは"), ("2", "Hello")], {"こんにちは": "Hi"}) == [
        ("1", "Hi"),
        ("2", "Hello"),
    ]


def test_sms_translate_batch_shapes():
    def client_for(content):
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **_k: _chat_response(content))
            )
        )

    got = sms.sms_translate_batch(client_for('{"items":[{"i":5,"t":"Hi ◙ there"}]}'), "m", ["こんにちは"], 5)
    assert got == ["Hi \n there"]
    empty = sms.sms_translate_batch(client_for(None), "m", ["あ"], 0)
    assert empty == [None]
    missing = sms.sms_translate_batch(
        client_for('{"items":[{"i":1}, "nope", {"t":"x"}]}'), "m", ["あ", "い"], 0
    )
    assert missing == [None, None]
    no_items = sms.sms_translate_batch(client_for('{"other": 1}'), "m", ["あ"], 0)
    assert no_items == [None]
    rejected = sms.sms_translate_batch(client_for('{"items":[{"i":0,"t":"あああ"}]}'), "m", ["あいう"], 0)
    assert rejected == [None]


def test_sms_translate_flows(tmp_path, monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "openai":
            raise ImportError("blocked")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked)
    monkeypatch.delitem(sys.modules, "openai", raising=False)
    with pytest.raises(SystemExit, match="pip install openai"):
        sms.translate(argparse.Namespace(input=str(tmp_path), out=str(tmp_path / "o"), api_key="k", model="m", batch_size=1, workers=1, sleep=0, limit=0))
    monkeypatch.setattr(builtins, "__import__", real_import)

    seen = _install_openai(monkeypatch, lambda **_k: _chat_response("{}"))
    with pytest.raises(SystemExit, match="no maildic"):
        sms.translate(argparse.Namespace(input=str(tmp_path / "empty"), out=str(tmp_path / "o"), api_key="  test-key  ", model="m", batch_size=1, workers=1, sleep=0, limit=0))
    assert seen["key"] == "test-key"

    en_only = tmp_path / "enonly"
    en_only.mkdir()
    (en_only / "maildic_m.en.xml").write_text(_mail_xml([("1", "Hi")]), encoding="utf-8")
    with pytest.raises(SystemExit, match="no maildic"):
        sms.translate(argparse.Namespace(input=str(en_only), out=str(tmp_path / "o2"), api_key="k", model="m", batch_size=1, workers=1, sleep=0, limit=0))

    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "maildic_custom.xml").write_text(_mail_xml([("9", "Hello")]), encoding="utf-8")
    cout = tmp_path / "custom-out"
    assert sms.translate(argparse.Namespace(input=str(custom), out=str(cout), api_key="k", model="m", batch_size=1, workers=1, sleep=0, limit=0)) == 0
    assert (cout / "maildic_custom.en.xml").is_file()
    assert (cout / "maildic_custom.nlpmail").read_bytes().startswith(b"NLPMAIL1")
    assert "nothing to translate" in capsys.readouterr().out

    rt = tmp_path / "rt"
    rt.mkdir()
    (rt / "maildic_custom.roundtrip.xml").write_text(_mail_xml([("4", "Hello")]), encoding="utf-8")
    assert sms.translate(argparse.Namespace(input=str(rt), out=str(tmp_path / "rt-out"), api_key="k", model="m", batch_size=1, workers=1, sleep=0, limit=0)) == 0
    assert (tmp_path / "rt-out" / "maildic_custom.en.xml").is_file()

    preferred = tmp_path / "pref"
    preferred.mkdir()
    (preferred / "maildic_m.xml").write_text(_mail_xml([("1", "Hello")]), encoding="utf-8")
    (preferred / "maildic_m.roundtrip.xml").write_text(_mail_xml([("2", "Bye")]), encoding="utf-8")
    (preferred / "maildic_m.en.xml").write_text(_mail_xml([("3", "Skip")]), encoding="utf-8")
    pref_out = tmp_path / "pref-out"
    sms.translate(argparse.Namespace(input=str(preferred), out=str(pref_out), api_key="k", model="m", batch_size=1, workers=1, sleep=0, limit=0))
    text = (pref_out / "maildic_m.en.xml").read_text(encoding="utf-8")
    assert 'hex="1"' in text and 'hex="2"' not in text

    sleeps: list[float] = []
    monkeypatch.setattr(sms.time, "sleep", lambda n: sleeps.append(n))

    def batch(_client, _model, texts, start):
        if len(texts) > 1:
            raise RuntimeError("batch down")
        src = texts[0]
        if src.startswith("BAD"):
            raise RuntimeError("item down")
        if src.startswith("EMPTY"):
            return [None]
        if src.startswith("JP"):
            return ["ああああ"]
        return [f"Hello {start}"]

    monkeypatch.setattr(sms, "sms_translate_batch", batch)
    src_dir = tmp_path / "jp"
    src_dir.mkdir()
    (src_dir / "maildic_m.xml").write_text(
        _mail_xml(
            [
                ("1", "BADこんにちは"),
                ("2", "OKこんにちは"),
                ("3", "EMPTYこんにちは"),
                ("4", "JPこんにちは"),
                ("5", "LIMITこんにちは"),
            ]
        ),
        encoding="utf-8",
    )
    jp_out = tmp_path / "jp-out"
    assert (
        sms.translate(
            argparse.Namespace(
                input=str(src_dir),
                out=str(jp_out),
                api_key="k",
                model="gpt",
                batch_size=2,
                workers=0,
                sleep=0.01,
                limit=4,
            )
        )
        == 0
    )
    mapping = json.loads((jp_out / "translations.json").read_text(encoding="utf-8"))["translations"]
    assert mapping["OKこんにちは"].startswith("Hello")
    assert "BADこんにちは" not in mapping
    assert "JPこんにちは" not in mapping
    assert "LIMITこんにちは" not in mapping
    assert sleeps == [0.01, 0.01, 0.01, 0.01]
    log = capsys.readouterr().out
    assert "batch error" in log and "still_jp=" in log
    written = (jp_out / "maildic_m.en.xml").read_text(encoding="utf-8")
    assert "BAD" in written and "Hello" in written

    monkeypatch.setattr(sys, "argv", ["translate_sms_en.py", "--input", str(custom), "--out", str(tmp_path / "main-out"), "--api-key", "k"])
    with pytest.raises(SystemExit) as exc:
        sms.main()
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# restore_nlppatch_nickname_tokens
# ---------------------------------------------------------------------------


def _dbin(dialogs: list[str], *, entries: int = 1) -> bytes:
    if entries == 1:
        parts = [dialogs]
    else:
        parts = [dialogs[:1], dialogs[1:]]
    built = []
    for i, chunk in enumerate(parts):
        built.append(DbinEntry(i, i + 1, SDL2Data(key=2 + i, unknown=[], dialogs=list(chunk))))
    return build_dbin2(0x11, 0x22, built)


def test_restore_nlppatch_file_and_main(tmp_path, monkeypatch, capsys):
    assert rn.needs_token_restore("same", "same") is False
    assert rn.needs_token_restore("▲高嶺＊＊▲ hi", "totally different") is False
    assert rn.needs_token_restore("▲高嶺＊＊▲ hi", "Takane hi") is True
    assert rn.needs_token_restore("▲高嶺＊＊▲  hi", "▲高嶺＊＊▲ hi") is False

    xml = tmp_path / "mk.xml"
    xml.write_text("<root><Dialog>▲高嶺＊＊▲</Dialog><Dialog/><Dialog>▲姉ヶ崎＊▲</Dialog></root>", encoding="utf-8")
    assert rn.xml_dialogs(xml) == ["▲高嶺＊＊▲", "", "▲姉ヶ崎＊▲"]

    dbin = tmp_path / "t001.dbin2"
    dbin.write_bytes(_dbin(["Takane", "ok", "Nene"], entries=2))
    assert rn.dbin_dialogs(dbin) == ["Takane", "ok", "Nene"]
    stats = rn.restore_dbin_file(dbin, xml, dry_run=True)
    assert stats.restored == 2 and rn.dbin_dialogs(dbin) == ["Takane", "ok", "Nene"]
    stats = rn.restore_dbin_file(dbin, xml, dry_run=False)
    assert stats.restored == 2
    assert rn.dbin_dialogs(dbin) == ["▲高嶺＊＊▲", "ok", "▲姉ヶ崎＊▲"]

    short = tmp_path / "short.xml"
    short.write_text("<root><Dialog>only</Dialog></root>", encoding="utf-8")
    mismatch = rn.restore_dbin_file(dbin, short, dry_run=False)
    assert mismatch.skipped_count_mismatch is True

    src = tmp_path / "scripts"
    src.mkdir()
    with pytest.raises(SystemExit, match="scripts missing"):
        rn.main(["--src", str(tmp_path / "nope")])

    def fake_fetch(stem: str, cache: Path):
        path = cache / f"{stem}.xml"
        return path if path.is_file() else None

    monkeypatch.setattr(rn, "fetch_makein", fake_fetch)
    cache = tmp_path / "cache"
    cache.mkdir()
    (src / "tKeep.dbin2").write_bytes(_dbin(["Takane"]))
    (cache / "tKeep.xml").write_text("<root><Dialog>▲高嶺＊＊▲</Dialog></root>", encoding="utf-8")
    (src / "tSame.dbin2").write_bytes(_dbin(["Hello"]))
    (cache / "tSame.xml").write_text("<root><Dialog>Hello</Dialog></root>", encoding="utf-8")
    (src / "tBad.dbin2").write_bytes(_dbin(["one"]))
    (cache / "tBad.xml").write_text("<root><Dialog>a</Dialog><Dialog>b</Dialog></root>", encoding="utf-8")
    (src / "tMiss.dbin2").write_bytes(_dbin(["x"]))
    (src / "note.bin").write_bytes(b"nope")

    assert rn.main(["--src", str(src), "--cache", str(cache), "--dry-run", "--glob", "*.nope"]) == 0
    assert "would update 0 files" in capsys.readouterr().out

    assert rn.main(["--src", str(src), "--cache", str(cache), "--dry-run"]) == 0
    dry = capsys.readouterr().out
    assert "would update" in dry and "tKeep" in dry
    assert rn.dbin_dialogs(src / "tKeep.dbin2") == ["Takane"]
    assert "no Makein ref" in dry and "dialog-count mismatch" in dry

    assert rn.main(["--src", str(src), "--cache", str(cache)]) == 0
    assert rn.dbin_dialogs(src / "tKeep.dbin2") == ["▲高嶺＊＊▲"]
    assert "updated" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# export_progress_metrics
# ---------------------------------------------------------------------------


def _mdc(rows: list[tuple[int, str]]) -> bytes:
    out = bytearray(struct.pack("<H", len(rows)))
    for key, text in rows:
        payload = text.encode("utf-8") + b"\x00"
        out += key.to_bytes(8, "big") + (0).to_bytes(8, "big") + bytes([len(payload)]) + payload
    return bytes(out)


def _chunk(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack("<I", len(body)) + body


def _clean_indx() -> bytes:
    buf = bytearray(0x416)
    struct.pack_into("<I", buf, 4, 0x400)
    struct.pack_into("<I", buf, 0x400, 1)
    struct.pack_into("<I", buf, 0x404, 0x0C)
    struct.pack_into("<I", buf, 0x40C, 3)
    struct.pack_into("<HHH", buf, 0x410, 0, 1, 99)
    return bytes(buf)


def _messy_indx() -> bytes:
    buf = bytearray(0x480)
    struct.pack_into("<I", buf, 4, 0x100000)
    struct.pack_into("<I", buf, 8, 0x400)
    struct.pack_into("<I", buf, 0x400, 4)
    struct.pack_into("<I", buf, 0x404, 0)
    struct.pack_into("<I", buf, 0x408, 0x00FFFFF0)
    struct.pack_into("<I", buf, 0x40C, 0x20)
    struct.pack_into("<I", buf, 0x410, 0x40)
    struct.pack_into("<I", buf, 0x420, 3)
    struct.pack_into("<HHH", buf, 0x424, 0, 1, 1)
    struct.pack_into("<I", buf, 0x440, 10000)
    struct.pack_into("<I", buf, 12, 0x450)
    struct.pack_into("<I", buf, 0x450, 1)
    struct.pack_into("<I", buf, 0x454, 0)
    struct.pack_into("<I", buf, 16, 0x460)
    struct.pack_into("<I", buf, 0x460, 1000)
    return bytes(buf)


def _trb(entries: list[tuple[int, str]], indx: bytes) -> bytes:
    strb = bytearray()
    stri = bytearray()
    for flag, text in entries:
        if flag == 2:
            stri += struct.pack("<IHH", 0, 0, 2)
        else:
            off = len(strb)
            raw = text.encode("utf-8")
            strb += raw + b"\x00"
            stri += struct.pack("<IHH", off, len(raw), 1)
    return _chunk(b"STRI", bytes(stri)) + _chunk(b"STRB", bytes(strb)) + _chunk(b"INDX", indx)


_TRB_ENTRIES = [
    (1, "Hello"),
    (2, ""),
    (1, "こんにちは"),
    (1, "▲高嶺▲ hello"),
    (1, "quiz 「漢字」 please"),
    (1, "   "),
    (1, "hello・ー"),
    (1, "未訳"),
    (1, "まだ"),
]


def _metrics_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    images = root / "assets" / "images"
    _png(images / "title.check" / "timg" / "Word.png", 8, 4)
    (images / "option.check").mkdir(parents=True)
    _png(images / "shop" / "timg" / "Sign.png", 4, 4)
    (root / "release").mkdir(parents=True)
    return root


def _bind_metrics(monkeypatch, root: Path):
    monkeypatch.setattr(epm, "ROOT", root)
    monkeypatch.setattr(epm, "BAKE_IMG", root / "release" / "bake_img.bin")
    monkeypatch.setattr(epm, "DEFAULT_TRB", root / "missing-default.trb")
    monkeypatch.setattr(epm, "DEFAULT_TRANSLATIONS", root / "translations.json")
    monkeypatch.setattr(epm, "load_lookup", lambda _path: ["?"])
    monkeypatch.setattr(epm, "nlppatch_script_dir", lambda: root / "vendor-scripts")
    monkeypatch.setattr(epm, "nlppatch_stems", lambda: {"a001"})

    def resolve(pack, stem, eng_root):
        tags = {
            "t001": "manaka",
            "k001": "nlppatch",
            "a001": "contrib",
            "p001": "eng_p",
            "z001": "jp",
            "x001": "manaka",
        }
        return eng_root / pack / f"{stem}.dbin2", tags.get(stem, "jp")

    monkeypatch.setattr(epm, "resolve_script_source", resolve)


def test_export_helpers(tmp_path, monkeypatch):
    assert epm.route_for_stem("") == "other"
    assert epm.route_for_stem("t1") == "manaka"
    assert epm.route_for_stem("K2") == "rinko"
    assert epm.route_for_stem("a3") == "nene"
    assert epm.route_for_stem("p4") == "common"
    assert epm.route_for_stem("9") == "other"

    assert epm.parse_indx_categories(b"\x00" * 10) == {}
    messy = epm.parse_indx_categories(_messy_indx())
    assert 0 not in messy and 1 not in messy and 3 not in messy
    assert 0 in messy[2] and 1 in messy[2]

    root = _metrics_root(tmp_path)
    _bind_metrics(monkeypatch, root)
    assert epm.gemini_script_sources() == {}
    g_root = tmp_path / "gonly"
    monkeypatch.setattr(epm, "ROOT", g_root)
    (g_root / "assets" / "gemini_heroines" / "dbin2" / "script").mkdir(parents=True)
    (g_root / "assets" / "gemini_heroines" / "dbin2" / "script" / "q900.dbin2").write_bytes(b"d")
    assert epm.gemini_script_sources()["q900"].suffix == ".dbin2"
    (g_root / "assets" / "gemini_heroines" / "xml").mkdir()
    (g_root / "assets" / "gemini_heroines" / "xml" / "q900.xml").write_text("<x/>", encoding="utf-8")
    (g_root / "assets" / "gemini_heroines" / "xml" / "g900.xml").write_text("<x/>", encoding="utf-8")
    found = epm.gemini_script_sources()
    assert found["q900"].suffix == ".xml" and found["g900"].suffix == ".xml"

    monkeypatch.setattr(epm, "ROOT", root)
    script = root / "dbin" / "script"
    script.mkdir(parents=True)
    for stem in ("t001", "k001", "a001", "p001", "z001", "x001"):
        (script / f"{stem}.dbin2").write_bytes(b"d")
    (root / "assets" / "gemini_heroines" / "dbin2" / "script").mkdir(parents=True)
    (root / "assets" / "gemini_heroines" / "xml").mkdir(parents=True)
    (root / "assets" / "gemini_heroines" / "dbin2" / "script" / "q001.dbin2").write_bytes(b"d")
    (root / "assets" / "gemini_heroines" / "xml" / "q001.xml").write_text("<a/>", encoding="utf-8")
    (root / "assets" / "gemini_heroines" / "xml" / "g001.xml").write_text("<a/>", encoding="utf-8")
    metrics = epm.script_metrics(root / "dbin")
    assert metrics["english_files"] == 7
    assert metrics["nlppatch_stem_count"] == 1
    assert "vendor-scripts" in metrics["vendor_nlppatch"]
    jp = [row["stem"] for row in metrics["files"]["japanese"]]
    assert jp == ["z001"]
    sources = {row["stem"]: row for row in metrics["files"]["english"]}
    assert sources["g001"]["source"].endswith("g001.xml")
    assert sources["q001"]["source"].endswith("q001.xml")
    assert sources["k001"]["layer"] == "nlppatch"
    assert metrics["by_route"]["other"]["percent"] == 0.0
    assert metrics["by_route"]["manaka"]["total"] == 175

    monkeypatch.setattr(epm, "nlppatch_script_dir", lambda: None)
    monkeypatch.setattr(epm, "SCRIPT_PACK_TOTAL", 0)
    monkeypatch.setattr(epm, "VANILLA_ROUTE_TOTALS", {"manaka": 0, "rinko": 0, "nene": 0, "common": 0})
    empty = epm.script_metrics(tmp_path / "no-scripts")
    assert empty["percent"] == 0.0
    assert empty["vendor_nlppatch"]
    zeroed = epm.script_metrics(root / "dbin")
    assert zeroed["by_route"]["manaka"]["japanese"] == 0
    assert zeroed["by_route"]["manaka"]["percent"] == 0.0

    real_glob = Path.glob

    def glob(self, pattern):
        found = list(real_glob(self, pattern))
        if pattern == "*.dbin2" and self == script:
            found.append(self / "ghost.dbin2")
        return found

    monkeypatch.setattr(Path, "glob", glob)
    ghosted = epm.script_metrics(root / "dbin")
    monkeypatch.setattr(Path, "glob", real_glob)
    names = [row["stem"] for row in ghosted["files"]["english"] + ghosted["files"]["japanese"]]
    assert "ghost" not in names

    sms_dir = root / "assets" / "gemini_heroines" / "sms"
    sms_dir.mkdir(parents=True)
    gemini = {
        "manaka": sms_dir / "maildic_m.en.xml",
        "nene": sms_dir / "maildic_n.en.xml",
        "rinko": sms_dir / "maildic_r.en.xml",
    }
    monkeypatch.setattr(epm, "SMS_GEMINI", gemini)
    assert epm.gemini_sms_metrics() is None
    for path, text in (
        (gemini["manaka"], "Hello"),
        (gemini["nene"], "こんにちは"),
        (gemini["rinko"], ""),
    ):
        path.write_text(_mail_xml([("1", text)]), encoding="utf-8")
    gem = epm.gemini_sms_metrics()
    assert gem is not None and gem["english_messages"] == 2
    assert "/" in gem["by_hero"]["manaka"]["en_wip_source"]
    monkeypatch.setattr(epm, "SMS_TOTALS", {"manaka": 0, "nene": 0, "rinko": 0})
    for path in gemini.values():
        path.write_text("<Dictionary></Dictionary>", encoding="utf-8")
    assert epm.gemini_sms_metrics()["percent"] == 0.0
    monkeypatch.setattr(epm, "SMS_TOTALS", {"manaka": 599, "nene": 634, "rinko": 589})
    monkeypatch.setattr(
        epm,
        "SMS_GEMINI",
        {key: root / "gone" / f"{key}.xml" for key in ("manaka", "nene", "rinko")},
    )

    missing = epm.sms_metrics(root / "no-img.bin")
    assert missing["english_messages"] == 0 and missing["total_messages"] == 1822
    assert "missing" in missing["note"]

    long = "E" * 90
    pkg = fi.package(
        [
            ("maildic_m.mdc", _mdc([(1, "Hello"), (2, "こんにちは"), (3, long)])),
            ("maildic_n.mdc", _mdc([])),
        ]
    )
    img_path = tmp_path / "sms-img.bin"
    img_path.write_bytes(fi.img({92: pkg}))
    (root / "assets" / "sms_en").mkdir(parents=True)
    (root / "assets" / "sms_en" / "maildic_m.en.xml").write_text("<Dictionary/>", encoding="utf-8")
    parsed = epm.sms_metrics(img_path)
    assert parsed["by_hero"]["rinko"]["error"].startswith("missing")
    assert parsed["by_hero"]["nene"]["percent"] == 0.0
    assert parsed["by_hero"]["manaka"]["english_messages"] == 2
    assert parsed["by_hero"]["manaka"]["en_wip_source"]
    assert parsed["by_hero"]["nene"]["en_wip_source"] is None
    assert len(parsed["by_hero"]["manaka"]["messages"][2]["preview"]) == 80
    err_img = tmp_path / "err-img.bin"
    err_img.write_bytes(fi.img({92: fi.package([("other.mdc", b"xx")])}))
    assert epm.sms_metrics(err_img)["percent"] == 0.0

    trb_path = root / "textresource_jpn.trb"
    trb_path.write_bytes(_trb(_TRB_ENTRIES, _clean_indx()))
    trans = root / "translations.json"
    trans.write_text(json.dumps({"translations": {"未訳": "Not yet"}}), encoding="utf-8")
    main = epm.trb_metrics(trb_path, trans)
    assert main["english_entries"] == 7
    assert main["japanese_entries"] == 2
    assert 2 in main["japanese_stri_indices"] and 8 in main["japanese_stri_indices"]
    assert 7 in main["english_stri_indices"] and 3 in main["english_stri_indices"]
    assert "unassigned_stri" in main["by_indx_category"]
    assert main["by_indx_category"]["cat_001"]["stri_slots"] == 3
    assert "textresource_jpn.trb" in main["file"].replace("\\", "/")

    outside = tmp_path / "side.trb"
    outside.write_bytes(trb_path.read_bytes())
    assert epm.trb_metrics(outside, trans)["file"] == str(outside)
    assert epm.trb_metrics(trb_path, root / "absent.json")["translation_keys"] == 0
    (root / "list.json").write_text("[1]", encoding="utf-8")
    assert epm.trb_metrics(trb_path, root / "list.json")["translation_keys"] == 0
    (root / "raw.json").write_text(json.dumps({"まだ": "Still"}), encoding="utf-8")
    raw = epm.trb_metrics(trb_path, root / "raw.json")
    assert 8 in raw["english_stri_indices"] and raw["translation_keys"] == 1

    empty_trb = root / "empty.trb"
    empty_trb.write_bytes(_trb([], _clean_indx()))
    empty_m = epm.trb_metrics(empty_trb, trans)
    assert empty_m["percent"] == 0.0 and "unassigned_stri" not in empty_m["by_indx_category"]

    assert epm.resident_trb_metrics(root / "nope.trb")["present"] is False
    res = root / "resident.trb"
    res.write_bytes("hello\x00こんにちは\x00".encode())
    got = epm.resident_trb_metrics(res)
    assert got["present"] is True and got["english_fragments"] == 1 and got["japanese_fragments"] == 1
    side = tmp_path / "resident-side.trb"
    side.write_bytes(b"\x00\x00")
    side_m = epm.resident_trb_metrics(side)
    assert side_m["file"] == str(side) and side_m["percent"] == 0.0

    images = epm.image_metrics()
    assert images["by_folder"]["ncommonicon"]["asset_dir"] is None
    assert images["by_folder"]["option"]["png_masters"] == 0
    assert images["by_folder"]["title"]["png_masters"] == 1
    assert "shop" not in images["empty_image_map_keys"]
    assert "ncommonicon" in images["empty_image_map_keys"]
    assert images["mapped_folders_with_png"] >= 1
    assert "bake_img.bin" in images["gold_bake"].replace("\\", "/")

    combo = epm.combined_text_metrics(
        {"english_files": 1, "total_files": 2},
        {"english_messages": 1, "total_messages": 2},
    )
    assert combo["percent"] == 50.0 and combo["components"]["scripts"] == "1/2"


def test_export_main(tmp_path, monkeypatch, capsys):
    root = _metrics_root(tmp_path)
    _bind_metrics(monkeypatch, root)
    script = root / "dbin" / "script"
    script.mkdir(parents=True)
    (script / "t001.dbin2").write_bytes(b"d")
    trb = root / "textresource_jpn.trb"
    trb.write_bytes(_trb(_TRB_ENTRIES, _clean_indx()))
    (root / "translations.json").write_text("{}", encoding="utf-8")
    sms_dir = root / "assets" / "gemini_heroines" / "sms"
    sms_dir.mkdir(parents=True)
    gemini = {hero: sms_dir / name for hero, name in (
        ("manaka", "maildic_m.en.xml"),
        ("nene", "maildic_n.en.xml"),
        ("rinko", "maildic_r.en.xml"),
    )}
    monkeypatch.setattr(epm, "SMS_GEMINI", gemini)
    for path in gemini.values():
        path.write_text(_mail_xml([("1", "Hello")]), encoding="utf-8")
    dest = root / "out" / "progress_metrics.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["export_progress_metrics.py", "--json", str(dest), "--dbin", str(root / "dbin"), "--trb", str(trb), "--img", str(tmp_path / "ignored.bin")],
    )
    assert epm.main() == 0
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload["title_id"] == "00040000000F4E00"
    assert payload["sms_phone"]["english_messages"] == 3
    assert payload["trb_resident"]["present"] is False
    assert "TRB:" in capsys.readouterr().out
    assert payload["dialogue_plus_sms"]["english"] == payload["dialogue_scripts"]["english_files"] + 3

    monkeypatch.setattr(epm, "SMS_GEMINI", {key: root / "nope" / f"{key}.xml" for key in ("manaka", "nene", "rinko")})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_progress_metrics.py",
            "--json",
            str(root / "out" / "missing.json"),
            "--dbin",
            str(root / "dbin"),
            "--trb",
            str(root / "absent.trb"),
            "--img",
            str(root / "no-bake.bin"),
        ],
    )
    assert epm.main() == 0
    text = capsys.readouterr().out
    assert "TRB:" not in text
    missing = json.loads((root / "out" / "missing.json").read_text(encoding="utf-8"))
    assert missing["trb_main"] == {"error": "missing TRB"}
    assert missing["sms_phone"]["total_messages"] == 1822


# ---------------------------------------------------------------------------
# import_ui_buttons_bundle
# ---------------------------------------------------------------------------


def _bind_buttons(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "root"
    monkeypatch.setattr(ub, "ROOT", root)
    monkeypatch.setattr(ub, "ASSETS", root / "assets" / "images")
    monkeypatch.setattr(ub, "IMPORT_DIR", root / "cache" / "ui_buttons" / "import")
    monkeypatch.setattr(ub, "MANIFEST_PATH", root / "cache" / "ui_buttons" / "import" / "applied.json")
    monkeypatch.setattr(ub, "TRB_CSV_DST", root / "assets" / "textresource" / "ui_buttons_en.csv")
    monkeypatch.delenv("NLPP_UI_BUTTONS_ZIP", raising=False)
    return root


def _bundle_tree(dest: Path, *, with_csv: bool = True, with_png: bool = True) -> None:
    groups = {
        "graphics/package_5190_InputC_and_InputN_shared": ["A.png"] if with_png else [],
        "graphics/package_5380_Myroom_Back": ["readme.txt"],
        "graphics/Album_Delete": ["Del.png"] if with_png else [],
    }
    for folder, names in groups.items():
        (dest / folder).mkdir(parents=True, exist_ok=True)
        for name in names:
            target = dest / folder / name
            if name.endswith(".png"):
                target.write_bytes(_png_bytes())
            else:
                target.write_text("x", encoding="utf-8")
    (dest / "manifest.json").write_text(json.dumps({"png_assets": 2}), encoding="utf-8")
    if with_csv:
        (dest / "trb_buttons_en.csv").write_text("a,b\n\nc,d\n", encoding="utf-8")


def test_import_ui_finders(tmp_path, monkeypatch):
    root = _bind_buttons(monkeypatch, tmp_path)
    root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(SystemExit, match="manifest.json not found"):
        ub._find_bundle_root(root)
    extracted = root / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "readme.txt").write_text("x", encoding="utf-8")
    nested = extracted / "Inner"
    _bundle_tree(nested)
    real_iter = Path.iterdir

    def iterdir(self):
        return iter(sorted(real_iter(self), key=lambda path: path.is_dir()))

    monkeypatch.setattr(Path, "iterdir", iterdir)
    assert ub._find_bundle_root(extracted) == nested
    monkeypatch.setattr(Path, "iterdir", real_iter)
    assert ub._find_bundle_root(nested) == nested

    missing_zip = tmp_path / "no.zip"
    with pytest.raises(SystemExit, match="zip not found"):
        ub._find_zip(missing_zip)
    real_zip = tmp_path / "have.zip"
    real_zip.write_bytes(b"PK")
    assert ub._find_zip(real_zip) == real_zip.resolve()

    monkeypatch.setenv("NLPP_UI_BUTTONS_ZIP", str(tmp_path / "env-missing.zip"))
    with pytest.raises(SystemExit, match="NLPP_UI_BUTTONS_ZIP"):
        ub._find_zip(None)
    monkeypatch.setenv("NLPP_UI_BUTTONS_ZIP", str(real_zip))
    assert ub._find_zip(None) == real_zip.resolve()
    monkeypatch.delenv("NLPP_UI_BUTTONS_ZIP")

    cache = root / "cache" / "ui_buttons_only"
    (cache / "Child").mkdir(parents=True)
    (cache / "Child" / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="already extracted"):
        ub._find_zip(None)
    (cache / "Child" / "manifest.json").unlink()
    (cache / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="already extracted"):
        ub._find_zip(None)
    (cache / "manifest.json").unlink()

    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(ub.Path, "home", lambda: home)
    with pytest.raises(SystemExit, match="not found"):
        ub._find_zip(None)
    (home / "Downloads" / "NLPP_English_UI_Buttons_only_a.zip").write_bytes(b"a")
    (home / "Downloads" / "NLPP_English_UI_Buttons_only_b.zip").write_bytes(b"b")
    assert ub._find_zip(None).name.endswith("_b.zip")


def test_import_ui_commands(tmp_path, monkeypatch, capsys):
    root = _bind_buttons(monkeypatch, tmp_path)
    extracted = root / "bundle"
    _bundle_tree(extracted)
    assert ub.cmd_import(argparse.Namespace(extracted=str(extracted), zip=None)) == 0
    applied = json.loads(ub.MANIFEST_PATH.read_text(encoding="utf-8"))
    assert [row["bundle_dir"] for row in applied] == [
        "graphics/package_5190_InputC_and_InputN_shared",
        "graphics/Album_Delete",
    ]
    assert (ub.ASSETS / "InputCTexture.check" / "timg" / "A.png").is_file()
    assert (ub.ASSETS / "InputNTexture.check" / "timg" / "A.png").is_file()
    assert "a,b" in ub.TRB_CSV_DST.read_text(encoding="utf-8")
    assert ub.cmd_status(argparse.Namespace()) == 0
    status = capsys.readouterr().out
    assert "pkg 5190" in status and "TRB rows" in status and "warn:" in status

    ub.MANIFEST_PATH.write_text(
        json.dumps([{"folder_keys": ["x"], "package": None, "png_count": 1, "warning": ""}]),
        encoding="utf-8",
    )
    ub.TRB_CSV_DST.unlink()
    assert ub.cmd_status(argparse.Namespace()) == 0
    assert "   ?" in capsys.readouterr().out
    ub.MANIFEST_PATH.unlink()
    assert ub.cmd_status(argparse.Namespace()) == 1

    bare = root / "nocsv"
    _bundle_tree(bare, with_csv=False)
    assert ub.cmd_import(argparse.Namespace(extracted=str(bare), zip=None)) == 0
    assert "TRB reference" not in capsys.readouterr().out

    zip_path = tmp_path / "buttons.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Pack/manifest.json", json.dumps({"png_assets": 1}))
        zf.writestr("Pack/graphics/Album_Delete/Z.png", _png_bytes())
    monkeypatch.setattr(sys, "argv", ["import_ui_buttons_bundle.py", "import", "--zip", str(zip_path)])
    assert ub.main() == 0
    assert (ub.ASSETS / "Album.check" / "timg" / "Z.png").is_file()
    monkeypatch.setattr(sys, "argv", ["import_ui_buttons_bundle.py", "status"])
    assert ub.main() == 0

    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self, args=None, namespace=None: argparse.Namespace(cmd="nope"),
    )
    with pytest.raises(SystemExit, match="unknown command"):
        ub.main()


# ---------------------------------------------------------------------------
# import_nlppctr_textures
# ---------------------------------------------------------------------------


def _bind_nl(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "root"
    assets = root / "assets" / "images"
    assets.mkdir(parents=True)
    monkeypatch.setattr(nl, "ROOT", root)
    monkeypatch.setattr(nl, "ASSETS_IMAGES", assets)
    monkeypatch.setattr(nl, "IMPORT_DIR", root / "cache" / "nlppctr" / "import")
    monkeypatch.setattr(nl, "MANIFEST_PATH", root / "cache" / "nlppctr" / "import" / "manifest.json")
    monkeypatch.setattr(nl, "OVERRIDES_PATH", root / "cache" / "nlppctr" / "import" / "overrides.json")
    monkeypatch.setattr(nl, "PNG2BCLIM", root / "missing-png2bclim.exe")
    return root


def test_nlppctr_scoring_index_and_overrides(tmp_path, monkeypatch):
    root = _bind_nl(monkeypatch, tmp_path)
    assets = nl.ASSETS_IMAGES
    _png(assets / "title.check" / "timg" / "Keep.png", 8, 8, (255, 0, 0, 255))
    _png(assets / "title.check" / "timg" / "skip_jpn.png", 8, 8)
    _png(assets / "title.check" / "timg" / "skip(2).png", 8, 8)
    (assets / "title.check" / "timg" / "broken.png").write_bytes(b"not-a-png")
    _png(assets / "title.check" / "loose" / "Keep.png", 8, 8)
    _png(assets / "Images-Done" / "Title" / "FromDone.png", 6, 6)
    (assets / "Images-Done" / "orphan.png").write_bytes(_png_bytes())
    _png(assets / "Option" / "timg" / "InTimg.png", 4, 4)
    _png(assets / "Option" / "loose.png", 4, 4)
    _png(assets / "nope" / "skip.png", 4, 4)
    _png(assets / "Title" / "Also.png", 5, 5)
    (assets / "Album.check").mkdir()
    _png(assets / "Images-Done" / "NotAFolder" / "Nope.png", 4, 4)

    rows = nl.iter_asset_pngs()
    stems = {stem for _p, _k, stem in rows}
    assert "Keep" in stems and "FromDone" in stems and "loose" in stems and "Also" in stems
    assert "skip_jpn" not in stems and "skip(2)" not in stems
    assert sum(1 for _p, _k, stem in rows if stem == "Keep") == 1
    indexed = nl.index_assets_by_size()
    assert (8, 8) in indexed and all(p.stem != "broken" for p, _k, _s in indexed[(8, 8)])

    solid = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
    other = Image.new("RGBA", (2, 2), (0, 255, 0, 128))
    blank = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    assert nl.score_pair(blank, blank) == 0.0
    assert 0 < nl.score_pair(solid, other, alpha_only=True) <= 1
    assert nl.score_pair(solid, solid) == pytest.approx(1.0)
    assert nl.alpha_mask(solid).shape == (4, 4)
    assert nl.composite_rgba(solid).shape == (4, 4, 3)

    assert nl.parse_tex1("nope.png") is None
    assert nl.parse_tex1("tex1_8x8_abcd_3_mip0.png") == (8, 8, "ABCD", 3)
    assert nl.load_overrides() == {}
    nl.OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    nl.OVERRIDES_PATH.write_text(
        json.dumps(
            {
                "abcdef0123456789": {"folder": "title", "stem": "Keep"},
                "0011223344556677": ["option", "Plate"],
                "zzzzzzzzzzzzzzzz": "nope",
                "0101010101010101": ["only"],
            }
        ),
        encoding="utf-8",
    )
    overrides = nl.load_overrides()
    assert overrides["ABCDEF0123456789"] == ("title", "Keep")
    assert overrides["0011223344556677"] == ("option", "Plate")
    assert "ZZZZZZZZZZZZZZZZ" not in overrides

    (assets / "title.check" / "timg").mkdir(parents=True, exist_ok=True)
    (assets / "option" / "timg").mkdir(parents=True, exist_ok=True)
    (assets / "option" / "timg").mkdir(parents=True, exist_ok=True)
    assert "title.check" in nl.dest_relpath("title", "Word").replace("\\", "/")
    assert Path(nl.dest_relpath("option", "Plate")).parts[-3:] == ("option", "timg", "Plate.png")
    assert "mail.check" in nl.dest_relpath("mail", "Nope").replace("\\", "/")

    known = root / "tex1_16x16_F305C9338867CC37_11_mip0.png"
    _png(known, 16, 16)
    hit = nl.match_one(known, {}, None)
    assert hit.source == "known" and hit.best_stem == "Com_btn_m01_b" and hit.pkg == 5238

    over = root / "tex1_8x8_ABCDEF0123456789_0_mip0.png"
    _png(over, 8, 8)
    ov = nl.match_one(over, {}, None)
    assert ov.source == "override" and ov.best_folder == "title"

    with pytest.raises(ValueError, match="not a tex1"):
        nl.match_one(root / "nope.png", {}, None)
    (root / "nope.png").write_bytes(_png_bytes())

    lone = root / "tex1_3x5_1111111111111111_0_mip0.png"
    _png(lone, 3, 5)
    none = nl.match_one(lone, {}, None)
    assert none.source == "none" and none.best_score == 0.0

    bad = tmp_path / "bad.png"
    bad.write_bytes(b"xx")
    asset_idx = {(8, 8): [(bad, "title", "Broken"), (assets / "title.check" / "timg" / "Keep.png", "title", "Keep")]}
    citra = root / "tex1_8x8_2222222222222222_0_mip0.png"
    _png(citra, 8, 8, (255, 0, 0, 255))
    scored = nl.match_one(citra, asset_idx, None)
    assert scored.source == "assets" and scored.best_stem == "Keep" and scored.second_score is None

    second = assets / "title.check" / "timg" / "Other.png"
    _png(second, 8, 8, (0, 0, 255, 255))
    both = nl.match_one(citra, {(8, 8): asset_idx[(8, 8)] + [(second, "title", "Other")]}, None)
    assert both.second_score is not None

    bclim_png = tmp_path / "decoded.png"
    _png(bclim_png, 8, 8, (255, 0, 0, 255))
    from_b = nl.match_one(citra, {}, {(8, 8): [(bclim_png, "title", "FromB", 5261), (bad, "title", "Bad", 1)]})
    assert from_b.source == "bclim" and from_b.pkg == 5261


def test_nlppctr_bclim_helpers(tmp_path, monkeypatch):
    root = _bind_nl(monkeypatch, tmp_path)
    assert nl.bclim_to_png_bytes(b"abc", root / "out.png") is None

    exe = root / "png2bclim.exe"
    exe.write_bytes(b"exe")
    monkeypatch.setattr(nl, "PNG2BCLIM", exe)

    def fake_run(cmd, cwd=None, **_kwargs):
        name = Path(cmd[1]).name
        if "fail" in name:
            return subprocess.CompletedProcess(cmd, 1, "", "nope")
        png = Path(cwd) / Path(name).with_suffix(".png").name
        _png(png, 4, 4)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(nl.subprocess, "run", fake_run)
    assert nl.bclim_to_png_bytes(fi.bclim(4, 4, 8), root / "ok.png") == root / "ok.png"
    assert (root / "ok.bclim").exists() is False
    moved = nl.bclim_to_png_bytes(fi.bclim(4, 4, 8), root / "moved.dat")
    assert moved == root / "moved.dat" and moved.is_file()
    assert nl.bclim_to_png_bytes(fi.bclim(4, 4, 8), root / "fail.png") is None

    def no_png(cmd, cwd=None, **_kwargs):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(nl.subprocess, "run", no_png)
    assert nl.bclim_to_png_bytes(b"xyz", root / "absent.png") is None

    arc = fi.darc(
        {
            "timg/Word.bclim": fi.bclim(8, 8, 8),
            "timg/bad.bclim": b"NOPE",
            "note.txt": b"x",
        }
    )
    img_path = tmp_path / "ui.bin"
    img_path.write_bytes(fi.img({5190: fi.package([("Input.arc", arc)])}))
    monkeypatch.setattr(nl.subprocess, "run", fake_run)
    decoded = nl.index_bclims_from_img(img_path, root / "work")
    again = nl.index_bclims_from_img(img_path, root / "work")
    assert again[(8, 8)]
    monkeypatch.setattr(nl, "PNG2BCLIM", root / "missing-png2bclim.exe")
    assert nl.index_bclims_from_img(img_path, root / "work-none") == {}
    monkeypatch.setattr(nl, "PNG2BCLIM", exe)
    assert any(stem == "Word" for _p, _f, stem, pkg in decoded[(8, 8)])
    folders = {folder for _p, folder, _s, _pkg in decoded[(8, 8)]}
    assert "inputctexture" in folders and "inputntexture" in folders
    (nl.IMPORT_DIR / "size_lookup").mkdir(parents=True, exist_ok=True)
    assert nl.bclim_size_from_img(img_path, 5190, "Word") == (8, 8)
    assert nl.bclim_size_from_img(img_path, 5190, "missing") is None
    assert nl.bclim_size_from_img(tmp_path / "not-an-img.bin", 1, "Word") is None
    (tmp_path / "not-an-img.bin").write_bytes(b"nope")
    assert nl.bclim_size_from_img(tmp_path / "not-an-img.bin", 1, "Word") is None

    row = {"dest_relpath": "assets/images/have.png", "pkg": 5190, "best_stem": "Word", "best_folder": "title"}
    _png(root / "assets" / "images" / "have.png", 9, 3)
    assert nl.expected_size(row, None) == (9, 3)
    row2 = {"dest_relpath": "assets/images/absent.png", "pkg": 5190, "best_stem": "Word", "best_folder": "title"}
    assert nl.expected_size(row2, img_path) == (8, 8)
    decoded_png = nl.IMPORT_DIR / "bclim_work" / "decoded" / "title" / "Word.png"
    _png(decoded_png, 2, 6)
    row3 = {"dest_relpath": None, "pkg": None, "best_stem": "Word", "best_folder": "title"}
    assert nl.expected_size(row3, None) == (2, 6)
    _png(nl.IMPORT_DIR / "bclim_work" / "decoded" / "title" / "Nope.png", 3, 5)
    fallback = {"dest_relpath": None, "pkg": 5190, "best_stem": "Nope", "best_folder": "title"}
    assert nl.expected_size(fallback, tmp_path / "not-an-img.bin") == (3, 5)
    assert nl.expected_size({"dest_relpath": None, "best_stem": "nope", "best_folder": "nope"}, None) is None


def test_nlppctr_download_scan_review_apply(tmp_path, monkeypatch, capsys):
    root = _bind_nl(monkeypatch, tmp_path)
    assets = nl.ASSETS_IMAGES
    _png(assets / "title.check" / "timg" / "Keep.png", 8, 8, (255, 0, 0, 255))

    def urlopen(req, timeout=120):
        url = req.full_url
        if "api.github.com" in url:
            body = json.dumps(
                [
                    {"name": "tex1_8x8_AA_0_mip0.png", "size": 4},
                    {"name": "tex1_4x4_BBBB_1_mip0.png", "size": 999},
                    {"name": "notes.txt", "size": 1},
                ]
            ).encode()
            return _Body(body)
        return _Body(b"PNG-BYTES")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    tex = nl.IMPORT_DIR / "textures"
    tex.mkdir(parents=True)
    (tex / "tex1_8x8_AA_0_mip0.png").write_bytes(b"KEEP")
    paths = nl.download_textures(tex)
    assert (tex / "tex1_8x8_AA_0_mip0.png").read_bytes() == b"KEEP"
    assert (tex / "tex1_4x4_BBBB_1_mip0.png").read_bytes() == b"PNG-BYTES"
    assert not (tex / "notes.txt").exists()
    assert len(paths) == 2
    got = nl._http_get("https://api.github.com/example")
    assert got.startswith(b"[") or got.startswith(b"{")

    for stale in tex.glob("tex1_*.png"):
        stale.unlink()
    known = tex / "tex1_8x8_F305C9338867CC37_0_mip0.png"
    _png(known, 8, 8)
    lone = tex / "tex1_3x7_3333333333333333_0_mip0.png"
    _png(lone, 3, 7)
    monkeypatch.setattr(sys, "argv", ["import_nlppctr_textures.py", "scan", "--min-score", "0.99"])
    assert nl.main() == 0
    manifest = json.loads(nl.MANIFEST_PATH.read_text(encoding="utf-8"))
    by_name = {row["citra_name"]: row for row in manifest["matches"]}
    assert by_name[known.name]["source"] == "known"
    assert by_name[lone.name]["source"] == "none"
    assert "using cached" in capsys.readouterr().out

    missing_img = tmp_path / "no-img.bin"
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_nlppctr_textures.py", "scan", "--img-bin", str(missing_img)],
    )
    with pytest.raises(SystemExit, match="--img-bin not found"):
        nl.main()

    arc = fi.darc({"timg/Keep.bclim": fi.bclim(8, 8, 8), "timg/bad.bclim": b"NOPE"})
    img_path = tmp_path / "ui.bin"
    img_path.write_bytes(fi.img({5190: fi.package([("Input.arc", arc)])}))
    exe = root / "png2bclim.exe"
    exe.write_bytes(b"exe")
    monkeypatch.setattr(nl, "PNG2BCLIM", exe)

    def fake_run(cmd, cwd=None, **_kwargs):
        png = Path(cwd) / Path(cmd[1]).with_suffix(".png").name
        _png(png, 8, 8, (255, 0, 0, 255))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(nl.subprocess, "run", fake_run)

    def png_urlopen(req, timeout=120):
        url = req.full_url
        if "api.github.com" in url:
            body = json.dumps([{"name": "tex1_4x4_CCCC_0_mip0.png", "size": 1}]).encode()
            return _Body(body)
        return _Body(_png_bytes())

    monkeypatch.setattr(urllib.request, "urlopen", png_urlopen)
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_nlppctr_textures.py", "scan", "--img-bin", str(img_path), "--refresh", "--min-score", "0.2"],
    )
    assert nl.main() == 0
    assert "bclim index" in capsys.readouterr().out

    review_src = root / "citra" / "one.png"
    _png(review_src, 8, 8, (255, 0, 0, 255))
    dest = assets / "title.check" / "timg" / "Keep.png"
    _png(dest, 4, 4, (0, 255, 0, 255))
    review_manifest = root / "review.json"
    review_manifest.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "local_path": str(review_src.relative_to(root)),
                        "dest_relpath": str(dest.relative_to(root)),
                        "best_score": 0.9,
                        "best_folder": "title",
                        "best_stem": "Keep",
                        "citra_name": "one.png",
                    },
                    {
                        "local_path": "missing.png",
                        "dest_relpath": "assets/images/title.check/timg/Keep.png",
                        "best_score": 0.9,
                        "best_stem": "Keep",
                        "best_folder": "title",
                        "citra_name": "gone.png",
                    },
                    {
                        "local_path": str(review_src.relative_to(root)),
                        "dest_relpath": None,
                        "best_score": 0.1,
                        "best_stem": None,
                        "citra_name": "low.png",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    assert nl.cmd_review(argparse.Namespace(manifest=review_manifest, min_score=0.5)) == 0
    panel = nl.IMPORT_DIR / "review" / "one__Keep.png"
    assert Image.open(panel).size == (8 * 2 + 8, 8 + 40)
    assert (nl.IMPORT_DIR / "review" / "one.txt").is_file()

    bare = root / "bare-citra.png"
    _png(bare, 6, 6)
    no_dest = root / "nodes.json"
    no_dest.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "local_path": str(bare.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/Fresh.png",
                        "best_score": 0.8,
                        "best_folder": "title",
                        "best_stem": "Fresh",
                        "citra_name": "bare.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert nl.cmd_review(argparse.Namespace(manifest=no_dest, min_score=0.5)) == 0

    winner_src = root / "win.png"
    _png(winner_src, 8, 8)
    small = root / "small.png"
    _png(small, 2, 2)
    (assets / "Title").mkdir(parents=True, exist_ok=True)
    winners = root / "winners.json"
    winners.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "local_path": str(winner_src.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/Keep.png",
                        "best_score": 0.95,
                        "best_folder": "title",
                        "best_stem": "Keep",
                        "citra_name": "win.png",
                        "pkg": 5261,
                    },
                    {
                        "local_path": str(small.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/Keep.png",
                        "best_score": 0.4,
                        "best_folder": "title",
                        "best_stem": "Keep",
                        "citra_name": "small.png",
                        "pkg": 5261,
                    },
                    {
                        "local_path": "missing-citra.png",
                        "dest_relpath": "assets/images/title.check/timg/Other.png",
                        "best_score": 0.8,
                        "best_folder": "title",
                        "best_stem": "Other",
                        "citra_name": "gone.png",
                    },
                    {
                        "local_path": str(small.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/Sized.png",
                        "best_score": 0.8,
                        "best_folder": "title",
                        "best_stem": "Sized",
                        "citra_name": "small.png",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    _png(assets / "title.check" / "timg" / "Keep.png", 8, 8)
    _png(assets / "title.check" / "timg" / "Sized.png", 9, 9)
    appdata = tmp_path / "AppData"
    monkeypatch.setenv("APPDATA", str(appdata))
    assert nl.cmd_apply_winners(argparse.Namespace(manifest=winners, img_bin=None, min_score=0.5, dry_run=True)) == 0
    assert "dry-run" in capsys.readouterr().out
    assert not (nl.IMPORT_DIR / "applied.json").exists()

    az = appdata / "Azahar" / "load" / "mods" / "00040000000F4E00" / "romfs" / "img.bin"
    az.parent.mkdir(parents=True)
    az.write_bytes(b"fake")
    assert nl.cmd_apply_winners(argparse.Namespace(manifest=winners, img_bin=None, min_score=0.5, dry_run=False)) == 0
    assert (assets / "title.check" / "timg" / "Keep.png").is_file()
    assert not (assets / "Images-Done" / "Title" / "Keep.png").exists()
    assert (assets / "Title" / "Keep.png").is_file()
    copied = capsys.readouterr().out
    assert "size" in copied and "image_map keys" in copied
    log = json.loads((nl.IMPORT_DIR / "applied.json").read_text(encoding="utf-8"))
    assert log[0]["citra"] == "win.png"

    apply_manifest = root / "apply.json"
    apply_manifest.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "local_path": str(winner_src.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/A.png",
                        "best_score": 0.9,
                        "second_score": 0.7,
                        "citra_name": "first.png",
                    },
                    {
                        "local_path": str(small.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/A.png",
                        "best_score": 0.85,
                        "second_score": None,
                        "citra_name": "second.png",
                    },
                    {
                        "local_path": str(winner_src.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/B.png",
                        "best_score": 0.9,
                        "second_score": 0.5,
                        "citra_name": "clear.png",
                    },
                    {
                        "local_path": str(winner_src.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/E.png",
                        "best_score": 0.8,
                        "second_score": 0.79,
                        "citra_name": "ambig.png",
                    },
                    {
                        "local_path": str(winner_src.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/C.png",
                        "best_score": 0.2,
                        "citra_name": "low.png",
                    },
                    {"local_path": None, "dest_relpath": None, "best_score": 1, "citra_name": "blank.png"},
                ]
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(manifest=apply_manifest, min_score=0.7, min_gap=0.1, unique_target=True, dry_run=True)
    assert nl.cmd_apply(args) == 0
    applied = capsys.readouterr().out
    assert "duplicate target" in applied and "ambiguous" in applied
    args.dry_run = False
    args.unique_target = False
    assert nl.cmd_apply(args) == 0
    assert (assets / "title.check" / "timg" / "A.png").is_file()
    assert (assets / "title.check" / "timg" / "B.png").is_file()
    assert "Next:" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        ["import_nlppctr_textures.py", "apply", "--manifest", str(apply_manifest), "--allow-duplicate-targets", "--dry-run"],
    )
    assert nl.main() == 0
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_nlppctr_textures.py", "review", "--manifest", str(review_manifest)],
    )
    assert nl.main() == 0
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_nlppctr_textures.py", "apply-winners", "--manifest", str(winners), "--dry-run", "--img-bin", str(img_path)],
    )
    assert nl.main() == 0
    plain = root / "plain-winners.json"
    plain_dest = assets / "title.check" / "timg" / "Plain.png"
    _png(plain_dest, 8, 8)
    plain.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "local_path": str(winner_src.relative_to(root)),
                        "dest_relpath": "assets/images/title.check/timg/Plain.png",
                        "best_score": 0.9,
                        "best_folder": "title",
                        "best_stem": "Plain",
                        "citra_name": "win.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert nl.cmd_apply_winners(argparse.Namespace(manifest=plain, img_bin=None, min_score=0.5, dry_run=False)) == 0
    assert "next:" not in capsys.readouterr().out
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_nlppctr_textures.py", "apply", "--manifest", str(apply_manifest), "--dry-run"],
    )
    assert nl.main() == 0
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self, args=None, namespace=None: argparse.Namespace(cmd="nope"),
    )
    assert nl.main() == 1


# ---------------------------------------------------------------------------
# build_call_romaji_match
# ---------------------------------------------------------------------------

_SUCCESS_OBJDUMP = "\n".join(
    [
        "Idx Name Size",
        "0 .text.nlpp_call_exact 00000010 0",
        "0 .text.normalize 00000008 0",
        "0 .text.same 00000008 0",
        "0 .text.distance 00000008 0",
        "0 .text.nlpp_call_list 00000010 0",
        "0 .text.fold 00000008 0",
        "0 .text.scan 00000010 0",
        "0 .text.pad 00000000 0",
        "0 .data 00000000 0",
        "0 .bss 00000000 0",
        "0 .rodata 00000000 0",
        "header",
    ]
)
_SUCCESS_NM = "\n".join(
    [
        "00247b3c T nlpp_call_exact",
        "00247b40 T normalize",
        "00247e04 T nlpp_call_list",
        "00247e10 T fold",
        "00248f44 T scan",
    ]
)


class _Toolchain:
    def __init__(self) -> None:
        self.objdump = _SUCCESS_OBJDUMP
        self.nm = _SUCCESS_NM
        self.regions = {"A": b"\x11" * 16, "B": b"\x22" * 16, "C": b"\x33" * 16}

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(br, "_tool", lambda name: name)
        monkeypatch.setattr(br.subprocess, "run", self.run)

    def run(self, cmd, check=False, capture_output=False, text=False, **kwargs):
        tool = Path(cmd[0]).name
        if tool == "clang" and "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="clang version 18.1.8 fake\n", stderr="")
        if tool == "clang":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"o")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if tool == "llvm-objdump":
            return subprocess.CompletedProcess(cmd, 0, stdout=self.objdump, stderr="")
        if tool == "ld.lld":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"elf")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if tool == "llvm-objcopy":
            section = next(part for part in cmd if str(part).startswith("--only-section=."))
            name = str(section).rsplit(".", 1)[1]
            Path(cmd[-1]).write_bytes(self.regions[name])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if tool == "llvm-nm":
            return subprocess.CompletedProcess(cmd, 0, stdout=self.nm, stderr="")
        raise AssertionError(cmd)


def test_build_call_romaji_tools_and_errors(tmp_path, monkeypatch):
    digest = hashlib.sha256(br.SOURCE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert br.source_sha256() == digest
    script = br._linker_script()
    assert "0x247b3c" in script and "DISCARD" in script and ".text.nlpp_call_exact" in script

    monkeypatch.setattr(br.shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit, match="clang not found"):
        br._tool("clang")
    with pytest.raises(SystemExit, match="ld.lld not found"):
        br._tool("ld.lld")

    clang = tmp_path / "bin" / "clang.exe"
    clang.parent.mkdir()
    clang.write_text("clang", encoding="utf-8")
    ld = clang.with_name("ld.lld.exe")

    def which(name: str):
        if name == "clang":
            return str(clang)
        if name == "llvm-objdump":
            return str(tmp_path / "missing-objdump")
        return None

    monkeypatch.setattr(br.shutil, "which", which)
    with pytest.raises(SystemExit, match="llvm-objdump not found"):
        br._tool("llvm-objdump")
    with pytest.raises(SystemExit, match="ld.lld not found"):
        br._tool("ld.lld")
    ld.write_text("ld", encoding="utf-8")
    assert br._tool("ld.lld") == str(ld)
    assert Path(br._tool("clang")).name.startswith("clang")

    chain = _Toolchain()
    chain.install(monkeypatch)
    assert br.clang_version().startswith("clang version 18")

    chain.objdump = _SUCCESS_OBJDUMP + "\n0 .text.extra 00000004 0"
    with pytest.raises(SystemExit, match="unplaced code section"):
        br.build()
    chain.objdump = "0 .data 00000004 0\n"
    with pytest.raises(SystemExit, match="not allowed"):
        br.build()
    chain.objdump = _SUCCESS_OBJDUMP
    chain.regions["A"] = b""
    with pytest.raises(SystemExit, match="region A is empty"):
        br.build()
    chain.regions["A"] = b"\x00" * (0x2C8 + 1)
    with pytest.raises(SystemExit, match="region A is"):
        br.build()
    chain.regions["A"] = b"\x11" * 16
    chain.nm = "00000000 T nlpp_call_exact\n00247e04 T nlpp_call_list\n00248f44 T scan\n"
    with pytest.raises(SystemExit, match="nlpp_call_exact"):
        br.build()

    bad_regions = (
        ("A", 0x00147B3C, 0x00147E04, ("nope", "normalize", "same", "distance")),
        ("B", 0x00147E04, 0x001480A8, ("nlpp_call_list", "fold")),
        ("C", 0x00148F44, 0x001493F0, ("scan",)),
    )
    monkeypatch.setattr(br, "REGIONS", bad_regions)
    chain.objdump = _SUCCESS_OBJDUMP.replace(".text.nlpp_call_exact", ".text.nope")
    chain.nm = _SUCCESS_NM
    with pytest.raises(SystemExit, match="nlpp_call_exact"):
        br.build()


def test_build_call_romaji_main(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    root.mkdir()
    blob = root / "call_romaji_match_blob.py"
    monkeypatch.setattr(br, "ROOT", root)
    monkeypatch.setattr(br, "BLOB_PY", blob)
    monkeypatch.setattr(br.shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit, match="clang not found"):
        br.main([])
    assert not blob.exists()

    _Toolchain().install(monkeypatch)
    assert br.main([]) == 0
    text = blob.read_text(encoding="utf-8")
    assert "PIECES" in text and "normalize" in text and br.source_sha256() in text
    assert "wrote" in capsys.readouterr().out
    assert br.main(["--check"]) == 0
    blob.write_text(text + "\n# stale\n", encoding="utf-8")
    assert br.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# ab_mcp_server
# ---------------------------------------------------------------------------


def _bind_ab(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    inst = root / "instances"
    release = root / "release"
    ab_dir = root / "ab_test"
    ab_dir.mkdir(parents=True)
    (ab_dir / "make.ps1").write_text("echo hi\n", encoding="utf-8")
    release.mkdir()
    monkeypatch.setattr(ab, "REPO", root)
    monkeypatch.setattr(ab, "AB", ab_dir)
    monkeypatch.setattr(ab, "INSTANCES", inst)
    monkeypatch.setattr(ab, "RELEASE", release)
    return inst, release


def _mod_root(inst: Path, name: str) -> Path:
    return inst / name / "user" / "load" / "mods" / ab.TITLE_ID


def test_ab_mcp_status_diff_and_logs(tmp_path, monkeypatch):
    inst, release = _bind_ab(monkeypatch, tmp_path)
    assert ab.mcp.name == "nlpp-ab-azahar"
    assert "ab_make" in ab.mcp.tools
    with pytest.raises(ValueError, match="instance"):
        ab._inst("c")
    assert ab._inst("b") == inst / "b"
    assert ab._sha1(inst / "missing.bin") is None

    mod_a = _mod_root(inst, "a")
    mod_b = _mod_root(inst, "b")
    (mod_a / "romfs").mkdir(parents=True)
    (mod_a / "exefs").mkdir()
    (mod_b / "romfs").mkdir(parents=True)
    (mod_a / "romfs" / "img.bin").write_bytes(b"img-same")
    (release / "bake_img.bin").write_bytes(b"img-same")
    (mod_a / "exefs" / "code.bin").write_bytes(b"code-a")
    (release / "name_input_code.bin").write_bytes(b"code-rel")
    (mod_a / "romfs" / "same.txt").write_bytes(b"same")
    (mod_b / "romfs" / "same.txt").write_bytes(b"same")
    (mod_a / "romfs" / "diff.txt").write_bytes(b"aaa")
    (mod_b / "romfs" / "diff.txt").write_bytes(b"bbb")
    (mod_a / "romfs" / "onlya.txt").write_bytes(b"a")
    (mod_b / "romfs" / "onlyb.txt").write_bytes(b"b")
    (mod_a / "_bak").mkdir()
    (mod_a / "_bak" / "skip.bin").write_bytes(b"skip")
    (inst / "a" / "azahar.exe").parent.mkdir(parents=True, exist_ok=True)
    (inst / "a" / "azahar.exe").write_bytes(b"exe")
    log = inst / "a" / "user" / "log" / "azahar_log.txt"
    log.parent.mkdir(parents=True)
    lines = ["boot", "HIT one", "HIT two", "gap", "Data abort here", "fine"]
    log.write_text("\n".join(lines), encoding="utf-8")
    (log.parent / "azahar_log.old.txt").write_text("old HIT\n", encoding="utf-8")

    monkeypatch.setattr(ab, "_running_pids", lambda _instance: [4, 5])
    status = json.loads(ab.ab_status("a"))
    assert status["azahar_exe"] is True
    assert status["running_pids"] == [4, 5]
    assert status["files"]["romfs/img.bin"]["matches_release"] is True
    assert status["files"]["exefs/code.bin"]["matches_release"] is False
    assert status["files"]["code.bin"]["exists"] is False
    assert status["files"]["code.bin"]["matches_release"] is None
    assert status["log_size"] == log.stat().st_size
    bare = json.loads(ab.ab_status("b"))
    assert bare["azahar_exe"] is False and bare["log_mtime"] is None

    diff = json.loads(ab.ab_diff())
    assert diff["only_a"] == ["romfs/onlya.txt"] or "romfs/onlya.txt" in diff["only_a"]
    assert "romfs/onlyb.txt" in diff["only_b"]
    assert "romfs/diff.txt" in diff["differ"]
    assert "romfs/same.txt" not in diff["differ"]
    assert diff["identical_count"] >= 1
    assert "_bak/skip.bin" not in diff["only_a"]

    monkeypatch.setattr(ab, "INSTANCES", tmp_path / "empty-instances")
    assert json.loads(ab.ab_diff())["identical_count"] == 0
    monkeypatch.setattr(ab, "INSTANCES", inst)

    code = mod_a / "exefs" / "code.bin"
    code.write_bytes(b"\x01\x02" + b"Z" * 5000)
    assert "(+1)" in ab.ab_read_bytes("a", "exefs/code.bin", 0, 0)
    wide = ab.ab_read_bytes("a", "exefs/code.bin", 0, 9000)
    assert "(+4096)" in wide
    assert "must be inside" in ab.ab_read_bytes("a", "../outside.bin")
    assert ab.ab_read_bytes("a", ".").startswith("file must be inside")
    assert ab.ab_read_bytes("a", "exefs/missing.bin").startswith("missing:")

    assert ab.ab_log_tail("b").startswith("no log")
    assert "old HIT" in ab.ab_log_tail("a", previous=True)
    assert ab.ab_log_tail("a", lines=0).strip() == lines[-1]
    long = inst / "a" / "user" / "log" / "azahar_log.txt"
    long.write_text("\n".join(f"row {i}" for i in range(1200)), encoding="utf-8")
    assert len(ab.ab_log_tail("a", lines=5000).splitlines()) == 1000
    long.write_text("\n".join(lines), encoding="utf-8")

    assert ab.ab_log_search("b", "HIT").startswith("no log")
    assert ab.ab_log_search("a", "none").strip() == "no matches"
    found = ab.ab_log_search("a", "hit", context=0, max_matches=1)
    assert "HIT one" in found and "truncated" in found
    spaced = ab.ab_log_search("a", "HIT", context=0, max_matches=10)
    assert "--" in spaced
    overlap = ab.ab_log_search("a", "HIT", context=1, max_matches=10)
    assert "HIT one" in overlap and "HIT two" in overlap
    assert "old HIT" in ab.ab_log_search("a", "hit", previous=True)

    assert ab.ab_log_markers("b").startswith("no log")
    quiet = inst / "b" / "user" / "log" / "azahar_log.txt"
    quiet.parent.mkdir(parents=True)
    quiet.write_text("nothing to see\n", encoding="utf-8")
    assert ab.ab_log_markers("b") == "no markers"
    assert "Data abort" in ab.ab_log_markers("a")
    many = "\n".join([f"Error> {i}" for i in range(10)])
    log.write_text(many, encoding="utf-8")
    marked = ab.ab_log_markers("a", max_lines=4)
    assert "..." in marked and "Error> 0" in marked and "Error> 9" in marked


def test_ab_mcp_make_stop_and_powershell(tmp_path, monkeypatch):
    _bind_ab(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if kwargs.get("timeout") == 1:
            raise subprocess.TimeoutExpired(cmd, 1)
        stderr = "bad\n" if kwargs.get("timeout") == 5 else "   "
        return subprocess.CompletedProcess(cmd, 3, stdout="out\n", stderr=stderr)

    monkeypatch.setattr(ab.subprocess, "run", fake_run)
    assert "not allowed" in ab.ab_make("progress")
    assert calls == []
    assert "timed out" in ab.ab_make("paths", timeout_seconds=1)
    body = ab.ab_make("paths", timeout_seconds=5)
    assert "exit=3" in body and "[stderr]" in body and "bad" in body
    quiet = ab.ab_make("deploy-a", timeout_seconds=9)
    assert "[stderr]" not in quiet and "out" in quiet

    real_pids = ab._running_pids
    real_ps = ab._powershell
    monkeypatch.setattr(ab, "_running_pids", lambda instance: [] if instance == "b" else [9, 10])
    assert ab.ab_stop("b") == "not running"
    assert ab.ab_stop("a") == "stopped [9, 10]"
    assert any(cmd[0] == "taskkill" for cmd in calls)

    monkeypatch.setattr(ab, "_running_pids", real_pids)
    monkeypatch.setattr(ab, "_powershell", lambda script, timeout=30: subprocess.CompletedProcess(["powershell"], 0, "12\nnope\n34\n", ""))
    assert ab._running_pids("a") == [12, 34]
    monkeypatch.setattr(ab, "_powershell", lambda script, timeout=30: subprocess.CompletedProcess(["powershell"], 0, "", ""))
    assert ab._running_pids("a") == []

    monkeypatch.setattr(ab, "_powershell", real_ps)
    monkeypatch.setattr(ab.subprocess, "run", lambda cmd, **_k: subprocess.CompletedProcess(cmd, 0, "ok", ""))
    assert ab._powershell("Get-Date").stdout == "ok"
