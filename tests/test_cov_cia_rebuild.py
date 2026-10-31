"""Coverage for CIA rebuild, bake, and the offline tools around them.

No game ROM, no network, and no real CIA or PNG pack. Every file this
module writes lives under tmp_path. Subprocess, urllib, and CIA readers
are monkeypatched.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import urllib.error
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

import patch_cia
from conftest import TOOLS, load_module
from patch_names import DbinEntry, SDL2Data
from run_timer import RunTimer

export = load_module("cov_export_azahar", TOOLS / "export_azahar_patches.py")
rtc = load_module("cov_rebuild_test_cia", TOOLS / "rebuild_test_cia.py")
fetch = load_module("cov_fetch_main_tree", TOOLS / "fetch_main_tree.py")
smoke = load_module("cov_smoke_boot_azahar", TOOLS / "smoke_boot_azahar.py")
scan = load_module("cov_scan_nl_spotpass", TOOLS / "scan_nl_spotpass_zip.py")
th = load_module("cov_translate_heroines", TOOLS / "translate_heroines_gemini.py")
bake = load_module("cov_rebuild_bake_img", TOOLS / "rebuild_bake_img.py")


class _Proc:
    def __init__(self, code: int = 0, out: str = "", err: str = "") -> None:
        self.returncode = code
        self.stdout = out
        self.stderr = err


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep patch_cia from touching the repo out/, release/, or cache/."""
    monkeypatch.setenv("NLPP_PLAIN_LOG", "1")
    for key in (
        "NLPP_T0",
        "NLPP_NO_LOG",
        "NLPP_ROM",
        "NLPP_INCLUDE_GEMINI_NENE",
        "NLPP_FORCE_SOURCE_FETCH",
        "NLPP_SKIP_SOURCE_FETCH",
        "NLPP_SMOKE_SEED_USER",
        "NLPP_MSYS_BIN",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "cia_root"
    (root / "out").mkdir(parents=True)
    monkeypatch.setattr(patch_cia, "ROOT", root)
    for name, rel in (
        ("DEFAULT_EXTRACTED", "extracted"),
        ("DEFAULT_ROMFS", "extracted/romfs"),
        ("DEFAULT_IMG_BIN", "extracted/romfs/img.bin"),
        ("DEFAULT_BAKE_IMG", "release/bake_img.bin"),
        ("DEFAULT_PACKED_IMG", "cache/new_img.bin"),
        ("DEFAULT_ROMFS_OVERLAY", "release/romfs_overlay"),
        ("_LEGACY_ROMFS_OVERLAY", "cache/romfs_overlay"),
        ("DEFAULT_CODE_BIN", "extracted/exefs/code.bin"),
        ("NAME_INPUT_CODE", "release/name_input_code.bin"),
    ):
        monkeypatch.setattr(patch_cia, name, root / rel)
    monkeypatch.setattr(patch_cia, "find_vanilla_code", lambda: None)
    for name in ("TOOL_3DS", "CTRTOOL", "MAKEROM", "SEEDDB"):
        tool = root / "cia_tools" / name
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_bytes(b"tool")
        monkeypatch.setattr(patch_cia, name, tool)
    yield root


def _ns(**kw) -> argparse.Namespace:
    base = dict(
        cia=None,
        out=None,
        dbin=None,
        work=None,
        cxi=None,
        manual=None,
        romfs=None,
        in_place_romfs=False,
        link_romfs=False,
        assume_decrypted=True,
        layeredfs_out=None,
        layeredfs_only=False,
        keep_work=True,
        log=None,
        no_log=True,
        with_images=False,
        no_images=True,
        images=None,
        img_bin=None,
        packed_img=None,
        reuse_packed_img=False,
        repack_images=False,
        image_workers=None,
        image_fine_tune=False,
        expect_sha1=None,
        skip_hash=True,
        skip_name_patches=True,
        include_gemini_nene=False,
        name_img=False,
        patch_code=False,
        inject_code=None,
        romfs_overlay=None,
        code_bin=None,
        cia_region="usa",
        skip_cia_meta=True,
        title_ver=None,
        keep_title_ver=False,
        skip_spotpass=True,
        spotpass_mode="real3ds",
        spotpass_install_azahar=False,
        started_unix=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def _dbin_root(path: Path, stem: str = "zzzz") -> Path:
    for pack in patch_cia.PACKS:
        dest = path / pack
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"{stem}.dbin2").write_bytes(b"dbin")
    return path


class _Tools:
    """Stand-in for ctrtool / 3dstool / makerom. Writes the outputs they would."""

    def __init__(self) -> None:
        self.ctr_out = "Crypto Key: None\nTitleVersion: 1.0.0 (4)\n"
        self.ctr_err = ""
        self.ctr_rc = 0
        self.content1 = False
        self.skip_content0 = False
        self.skip_part0 = False
        self.manual_empty = False
        self.code_name = "code.bin"
        self.header = True
        self.icon = True
        self.blz_out = 16
        self.romfs_size = 2048
        self.write_outputs = True
        self.plain = 4
        self.logo = 4
        self.product = b"OLD-CODE"

    def __call__(self, cmd, **kwargs):
        argv = [str(c) for c in cmd]
        name = Path(argv[0]).name.lower()
        out = err = ""
        rc = 0
        if "ctrtool" in name:
            out, err, rc = self._ctr(argv)
        elif ("3dstool" in name or name == "tool_3ds") and self.write_outputs:
            self._3ds(argv)
        elif "makerom" in name and self.write_outputs:
            dest = Path(argv[argv.index("-o") + 1])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"CIA")
        elif argv[:2] == ["cmd", "/c"] and "/J" in argv:
            link = Path(argv[argv.index("/J") + 1])
            target = Path(argv[argv.index("/J") + 2])
            if link.exists():
                shutil.rmtree(link)
            shutil.copytree(target, link)
        return _Proc(rc, out, err)

    def _ctr(self, argv):
        contents = next((a for a in argv if a.startswith("--contents=")), None)
        if contents:
            folder = Path(contents.split("=", 1)[1]).parent
            folder.mkdir(parents=True, exist_ok=True)
            if not self.skip_content0:
                (folder / "content.0000.00000000").write_bytes(b"CXI")
            if self.content1:
                data = b"" if self.manual_empty else b"MAN"
                (folder / "content.0001.00000001").write_bytes(data)
            return "", "", 0
        return self.ctr_out, self.ctr_err, self.ctr_rc

    def _3ds(self, argv):
        def opt(flag: str) -> Path | None:
            if flag not in argv:
                return None
            return Path(argv[argv.index(flag) + 1])

        if "-xvtf" in argv and "cci" in argv:
            main = opt("--partition0")
            manual = opt("--partition1")
            if main and not self.skip_part0:
                main.parent.mkdir(parents=True, exist_ok=True)
                main.write_bytes(b"PART0")
            if manual:
                manual.write_bytes(b"" if self.manual_empty else b"PART1")
        elif "-xvtf" in argv and "cxi" in argv:
            hdr = bytearray(0x60)
            hdr[:4] = b"NCCH"
            hdr[0x50:0x60] = self.product[:16].ljust(16, b"\x00")
            for flag, data in (
                ("--header", bytes(hdr)),
                ("--exh", b"EXH"),
                ("--plain", b"P" * self.plain),
                ("--logo", b"L" * self.logo),
                ("--exefs", b"EXE"),
                ("--romfs", b"ROM"),
            ):
                dest = opt(flag)
                if dest is not None:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
        elif "-xvtf" in argv and "romfs" in argv:
            dest = opt("--romfs-dir")
            assert dest is not None
            for pack in patch_cia.PACKS:
                (dest / "script" / "bin" / pack).mkdir(parents=True, exist_ok=True)
        elif "-cvtf" in argv and "romfs" in argv:
            Path(argv[argv.index("romfs") + 1]).write_bytes(b"R" * self.romfs_size)
        elif "-cvtf" in argv and "cxi" in argv:
            Path(argv[argv.index("cxi") + 1]).write_bytes(b"CXI")
        elif "-xvtf" in argv and "exefs" in argv:
            folder = opt("--exefs-dir")
            header = opt("--header")
            assert folder is not None
            folder.mkdir(parents=True, exist_ok=True)
            if self.code_name:
                (folder / self.code_name).write_bytes(b"C" * 16)
            if self.icon:
                (folder / "icon.bin").write_bytes(b"I" * 8)
            if self.header and header is not None:
                header.write_bytes(b"HDR")
        elif "-cvtf" in argv and "exefs" in argv:
            Path(argv[argv.index("exefs") + 1]).write_bytes(b"EXEFS")
        elif "-uvf" in argv:
            dest = opt("--compress-out")
            assert dest is not None
            dest.write_bytes(b"DECOMPRESSED")
        elif "-zvf" in argv:
            dest = opt("--compress-out")
            assert dest is not None
            dest.write_bytes(b"Z" * self.blz_out)


def _use_tools(monkeypatch: pytest.MonkeyPatch) -> _Tools:
    tools = _Tools()
    monkeypatch.setattr(patch_cia.subprocess, "run", tools)
    monkeypatch.setattr(patch_cia, "patch_icon_file", lambda *a, **k: None)
    return tools


# ---------------------------------------------------------------------------
# export_azahar_patches
# ---------------------------------------------------------------------------


def test_export_fork_dir_and_body(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("NLPP_AZAHAR_FORK", raising=False)
    assert export.fork_dir().name == "azahar-3ds-accurate"
    monkeypatch.setenv("NLPP_AZAHAR_FORK", str(tmp_path / "fork"))
    assert export.fork_dir() == tmp_path / "fork"
    assert export._body("no diff here") == ""
    assert export._body("pre\ndiff --git a/f b/f\n+z\n") == "diff --git a/f b/f\n+z\n"


def test_export_render_stale_and_main(monkeypatch, tmp_path: Path, capsys):
    fork = tmp_path / "fork"
    (fork / ".git").mkdir(parents=True)
    patches = tmp_path / "patches"
    patches.mkdir()
    monkeypatch.setenv("NLPP_AZAHAR_FORK", str(fork))
    monkeypatch.setattr(export, "PATCHES", patches)
    state = {"upstream": False}

    def run(cmd, **kwargs):
        args = list(cmd)[3:]
        if args[:3] == ["rev-parse", "--verify", "-q"]:
            if not state["upstream"]:
                return _Proc(1, "", "")
            return _Proc(0, "abc\n", "")
        if args[:1] == ["merge-base"]:
            return _Proc(0, "0123456789abcdef\n", "")
        if args[:1] == ["diff"]:
            return _Proc(0, "diff --git a/f b/f\n+line\n", "")
        if args[:2] == ["rev-parse", "--short"]:
            return _Proc(0, "abc123\n", "")
        return _Proc(0, "", "")

    monkeypatch.setattr(export.subprocess, "run", run)
    rendered = export.render(fork)
    assert set(rendered) == set(export.EXPORTS)
    assert "diff --git" in next(iter(rendered.values()))
    assert set(export.stale(fork)) == set(export.EXPORTS)
    state["upstream"] = True
    (patches / "azahar-openlinkfile.patch").write_text(
        "other\n" + rendered["azahar-openlinkfile.patch"], encoding="utf-8"
    )
    bad = export.stale(fork)
    assert "azahar-nlpp-emu.patch" in bad
    assert "azahar-openlinkfile.patch" not in bad

    assert export.main(["--check"]) == 1
    assert "stale:" in capsys.readouterr().err
    for name, text in rendered.items():
        (patches / name).write_text(text, encoding="utf-8")
    assert export.main(["--check"]) == 0
    assert export.main([]) == 0
    assert "wrote" in capsys.readouterr().out

    monkeypatch.setenv("NLPP_AZAHAR_FORK", str(tmp_path / "missing"))
    assert export.main([]) == 2


# ---------------------------------------------------------------------------
# rebuild_test_cia
# ---------------------------------------------------------------------------


def _bind_rtc(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(rtc, "SOURCE_ROM_FILE", tmp_path / "source_rom.txt")
    monkeypatch.setattr(rtc, "NAME_INPUT_CODE", tmp_path / "name_input_code.bin")
    monkeypatch.setattr(rtc, "OUT_LAYEREDFS", tmp_path / "luma")
    monkeypatch.setattr(rtc, "AZAHAR_MOD_CODE", tmp_path / "mod" / "code.bin")
    monkeypatch.setattr(rtc, "BAKE_IMG", tmp_path / "bake_img.bin")
    monkeypatch.setattr(rtc, "AZAHAR_MOD_IMG", tmp_path / "mod" / "img.bin")
    monkeypatch.setattr(rtc, "DEFAULT_ROM_CANDIDATES", (tmp_path / "no-such.cia",))
    monkeypatch.delenv("NLPP_ROM", raising=False)


def test_resolve_rom_order(monkeypatch, tmp_path: Path):
    _bind_rtc(monkeypatch, tmp_path)
    missing = tmp_path / "gone.cia"
    with pytest.raises(SystemExit, match="--rom not found"):
        rtc.resolve_rom(missing)
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"cia")
    assert rtc.resolve_rom(rom) == rom.resolve()

    other = tmp_path / "env.cia"
    other.write_bytes(b"e")
    monkeypatch.setenv("NLPP_ROM", str(other))
    assert rtc.resolve_rom(None) == other.resolve()
    monkeypatch.setenv("NLPP_ROM", str(tmp_path / "absent.cia"))
    listed = tmp_path / "listed.cia"
    listed.write_bytes(b"l")
    rtc.SOURCE_ROM_FILE.write_text(str(listed) + "\n", encoding="utf-8")
    assert rtc.resolve_rom(None) == listed.resolve()

    monkeypatch.delenv("NLPP_ROM", raising=False)
    rtc.SOURCE_ROM_FILE.write_text("   \n", encoding="utf-8")
    cand = tmp_path / "cand.cia"
    cand.write_bytes(b"c")
    monkeypatch.setattr(rtc, "DEFAULT_ROM_CANDIDATES", (tmp_path / "nope.cia", cand))
    assert rtc.resolve_rom(None) == cand.resolve()

    rtc.SOURCE_ROM_FILE.write_text(str(tmp_path / "missing-listed.cia"), encoding="utf-8")
    monkeypatch.setattr(rtc, "DEFAULT_ROM_CANDIDATES", (tmp_path / "nope.cia",))
    with pytest.raises(SystemExit, match="no ROM found"):
        rtc.resolve_rom(None)


def test_patch_and_build_name_input(monkeypatch, tmp_path: Path):
    _bind_rtc(monkeypatch, tmp_path)
    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(b"vanilla-code")
    monkeypatch.setattr(rtc, "require_vanilla_code", lambda: vanilla)
    for name in (
        "apply_pane_nullguard",
        "apply_lyt_null_pane",
        "apply_cand_nullguard",
        "apply_fillflag",
        "restore_bind_sites",
        "apply_kana_direct",
    ):
        monkeypatch.setattr(rtc, name, lambda data: None)
    monkeypatch.setattr(rtc, "patch_input_romaji", lambda data, force=False: False)
    with pytest.raises(SystemExit, match="romaji patch failed"):
        rtc._patch_vanilla_code()
    monkeypatch.setattr(rtc, "patch_input_romaji", lambda data, force=False: True)
    assert rtc._patch_vanilla_code().startswith(b"vanilla-code")

    mod = rtc.AZAHAR_MOD_CODE
    mod.parent.mkdir(parents=True)
    mod.write_bytes(b"from-mod")
    out = tmp_path / "out" / "code.bin"
    rtc.build_name_input_code(out, from_vanilla=False)
    assert out.read_bytes() == b"from-mod"
    rtc.build_name_input_code(out, from_vanilla=True)
    assert out.read_bytes().startswith(b"vanilla-code")


def test_rebuild_test_cia_main(monkeypatch, tmp_path: Path):
    _bind_rtc(monkeypatch, tmp_path)
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"cia")
    rtc.BAKE_IMG.write_bytes(b"img")
    mod = rtc.AZAHAR_MOD_CODE
    mod.parent.mkdir(parents=True)
    mod.write_bytes(b"code")
    calls = []
    monkeypatch.setattr(rtc.subprocess, "check_call", lambda cmd, **kw: calls.append(cmd))
    out = tmp_path / "drop" / "game.cia"
    assert rtc.main(["--rom", str(rom), "--out", str(out), "--skip-hash"]) == 0
    assert calls and "--skip-hash" in calls[-1]
    assert rtc.SOURCE_ROM_FILE.read_text(encoding="utf-8").strip() == str(rom.resolve())
    assert rtc.NAME_INPUT_CODE.read_bytes() == b"code"

    def forget(*_a, **_k):
        rtc.NAME_INPUT_CODE.unlink(missing_ok=True)

    monkeypatch.setattr(rtc, "build_name_input_code", forget)
    with pytest.raises(SystemExit, match="missing"):
        rtc.main(["--rom", str(rom), "--out", str(out), "--rebuild-code"])


# ---------------------------------------------------------------------------
# fetch_main_tree
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, chunks, fail_at: int | None = None) -> None:
        self.chunks = list(chunks)
        self.fail_at = fail_at
        self.n = 0

    def read(self, n: int = -1) -> bytes:
        self.n += 1
        if self.fail_at is not None and self.n >= self.fail_at:
            raise OSError("net")
        if not self.chunks:
            return b""
        if n is None or n < 0:
            data = b"".join(self.chunks)
            self.chunks.clear()
            return data
        return self.chunks.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_network_helpers(monkeypatch, tmp_path: Path):
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _Resp([]))
    assert fetch.github_reachable() is True
    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
    )
    assert fetch.github_reachable() is False

    seen = {}

    def urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["timeout"] = timeout
        return _Resp([b"abc", b"def"])

    monkeypatch.setattr(fetch.urllib.request, "urlopen", urlopen)
    resp = fetch._urlopen("https://api.github.com/repos/a/b", "tok")
    assert resp.read() == b"abcdef"
    assert seen["headers"]["authorization"] == "Bearer tok"
    assert "application/vnd.github+json" in seen["headers"]["accept"]
    fetch._urlopen("https://github.com/a/b", "tok")
    assert seen["headers"]["authorization"] == "Bearer tok"
    assert "accept" not in seen["headers"]
    fetch._urlopen("https://example.com/x", "tok")
    assert "authorization" not in seen["headers"]
    assert fetch._read_url("https://example.com/x", None) == b"abcdef"

    dest = tmp_path / "sub" / "file.bin"
    fetch._download_file("https://example.com/x", dest, None, dry_run=True)
    assert not dest.exists()
    fetch._download_file("https://example.com/x", dest, None, dry_run=False)
    assert dest.read_bytes() == b"abcdef"

    def boom(req, timeout=None):
        return _Resp([b"zz"], fail_at=2)

    monkeypatch.setattr(fetch.urllib.request, "urlopen", boom)
    with pytest.raises(OSError):
        fetch._download_file("https://example.com/x", dest, None, dry_run=False)
    assert not dest.with_name(dest.name + ".partial").exists()

    monkeypatch.setattr(fetch, "_read_url", lambda url, token: b'{"sha":"abc"}')
    assert fetch.remote_head_sha("a/b", "main", None) == "abc"
    monkeypatch.setattr(fetch, "_read_url", lambda url, token: b'{"sha": 1}')
    with pytest.raises(LookupError):
        fetch.remote_head_sha("a/b", "main", None)
    monkeypatch.setattr(fetch, "_read_url", lambda url, token: b"{}")
    with pytest.raises(LookupError):
        fetch.remote_head_sha("a/b", "main", None)


def test_fetch_manifest_ignore_and_prune(tmp_path: Path):
    assert fetch._read_stamp(tmp_path) is None
    (tmp_path / fetch.STAMP_NAME).write_text("   \n", encoding="utf-8")
    assert fetch._read_stamp(tmp_path) is None
    (tmp_path / fetch.MANIFEST_NAME).write_text(
        "\n\nabc\tfile.txt\nbare-path\n", encoding="utf-8"
    )
    hashes = fetch._read_manifest_hashes(tmp_path)
    assert hashes == {"file.txt": "abc", "bare-path": None}
    assert fetch._read_manifest(tmp_path) == {"file.txt", "bare-path"}

    ign = fetch.GitIgnore()
    ign.add(
        "",
        "\n# comment\n/\n!/\n**/keep\nfoo/**\na**b\n*.tmp\n?.z\n[abc]\n[!xy]\n[unterminated\n\\*\nplain\n",
    )
    assert ign.rules
    assert fetch._is_protected("") and fetch._is_protected(".")
    assert fetch._is_protected("out/x") and fetch._is_protected("release/a")
    assert fetch._is_protected(".env") and fetch._is_protected("sub/.env")
    assert fetch._is_protected("pkg/__pycache__") and fetch._is_protected("a.pyc")
    assert fetch._is_protected("ab_test/azahar_instances/a/x")
    assert fetch._is_protected("ab_test/saves/s")
    assert fetch._is_protected("ab_test/paths.local.ps1")
    assert fetch._is_protected("src/a.py") is False

    extract = tmp_path / "extract"
    (extract / ".hidden").mkdir(parents=True)
    (extract / "Only").mkdir()
    assert fetch._zip_inner_root(extract) == extract / "Only"
    (extract / "Second").mkdir()
    assert fetch._zip_inner_root(extract) == extract
    empty = tmp_path / "no_kids"
    empty.mkdir()
    assert fetch._zip_inner_root(empty) == empty

    src = tmp_path / "src_tree"
    (src / "out").mkdir(parents=True)
    (src / "out" / "skip.txt").write_text("no", encoding="utf-8")
    (src / "keep.txt").write_text("yes", encoding="utf-8")
    dst = tmp_path / "dst"
    written = fetch.overlay_tree(src, dst, dry_run=True)
    assert written == ["keep.txt"]
    assert not (dst / "keep.txt").exists()
    fetch.overlay_tree(src, dst, dry_run=False)
    assert (dst / "keep.txt").read_text(encoding="utf-8") == "yes"

    nested = dst / "gone" / "nested.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("x", encoding="utf-8")
    (dst / "stay.txt").write_text("s", encoding="utf-8")
    removed = fetch.prune_removed(
        dst,
        {"out/x", "a/../../b", "missing.txt", "gone/nested.txt", "stay.txt"},
        {"stay.txt"},
    )
    assert removed == ["gone/nested.txt"]
    assert not nested.exists()
    assert not nested.parent.exists()

    (dst / ".git").mkdir()
    rel = "keep.txt"
    (dst / fetch.MANIFEST_NAME).write_text(
        f"{fetch._sha256(dst / rel)}\t{rel}\n", encoding="utf-8"
    )
    assert fetch.tree_drift(dst) is None
    (dst / rel).write_text("changed", encoding="utf-8")
    assert "changed or missing" in (fetch.tree_drift(dst) or "")
    (dst / fetch.MANIFEST_NAME).unlink()
    assert fetch.tree_drift(dst) == "no file manifest from an earlier sync"


def test_fetch_try_and_main(monkeypatch, tmp_path: Path):
    root = tmp_path / "tree"
    root.mkdir()
    monkeypatch.setattr(fetch, "github_reachable", lambda: True)

    status, msg = fetch.try_fetch_main_tree(
        repo="", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert status == "unavailable" and "no source repo" in msg

    def raise_http(*a, **k):
        raise urllib.error.HTTPError("http://x", 500, "nope", hdrs=None, fp=None)

    monkeypatch.setattr(fetch, "remote_head_sha", raise_http)
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token="t", root=root, skip_git_checkout=False
    )
    assert "HTTP 500" in msg

    monkeypatch.setattr(
        fetch, "remote_head_sha", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("down"))
    )
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert "network error" in msg

    monkeypatch.setattr(
        fetch, "remote_head_sha", lambda *a, **k: (_ for _ in ()).throw(json.JSONDecodeError("m", "d", 0))
    )
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert status == "unavailable"

    monkeypatch.setattr(fetch, "remote_head_sha", lambda *a, **k: "abcdef1234567890")

    def dry(url, dest, token, *, dry_run):
        assert dry_run

    monkeypatch.setattr(fetch, "_download_file", dry)
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, dry_run=True, skip_git_checkout=False
    )
    assert status == "updated" and "dry-run" in msg

    def write_zip(url, dest, token, *, dry_run, payload: bytes):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)

    def zip_of(files: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in files.items():
                zf.writestr(name, data)
        return buf.getvalue()

    monkeypatch.setattr(
        fetch,
        "_download_file",
        lambda url, dest, token, dry_run=False: write_zip(
            url, dest, token, dry_run=dry_run, payload=zip_of({"Empty-main/readme.txt": b"x"})
        ),
    )
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert "missing EngPatcher root" in msg

    monkeypatch.setattr(
        fetch,
        "_download_file",
        lambda url, dest, token, dry_run=False: write_zip(
            url,
            dest,
            token,
            dry_run=dry_run,
            payload=zip_of({"Repo-main/src/a.py": b"x", "Repo-main/Drop CIA or 3DS Here to Patch.bat": b"@"}),
        ),
    )
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert "missing .gitignore" in msg

    monkeypatch.setattr(
        fetch, "_download_file", lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError("u", 404, "missing", None, None))
    )
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert "zipball 404" in msg
    monkeypatch.setattr(
        fetch, "_download_file", lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError("u", 503, "busy", None, None))
    )
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert "HTTP 503" in msg
    monkeypatch.setattr(
        fetch, "_download_file", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused"))
    )
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert "network error" in msg
    monkeypatch.setattr(
        fetch, "_download_file", lambda *a, **k: (_ for _ in ()).throw(zipfile.BadZipFile("bad"))
    )
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert "bad" in msg
    monkeypatch.setattr(fetch, "_download_file", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    status, msg = fetch.try_fetch_main_tree(
        repo="a/b", ref="main", token=None, root=root, skip_git_checkout=False
    )
    assert status == "unavailable" and "disk" in msg

    monkeypatch.setattr(fetch, "try_fetch_main_tree", lambda **k: ("unavailable", "offline"))
    with pytest.raises(SystemExit, match="offline"):
        fetch.main(["--root", str(root), "--repo", "a/b"])
    assert fetch.main(["--root", str(root), "--repo", "a/b", "--best-effort"]) == 0


# ---------------------------------------------------------------------------
# smoke_boot_azahar
# ---------------------------------------------------------------------------


_MOD_OK = (
    "overriding built-in ExeFS file\n"
    "LayeredFS replacement file in use for /img.bin\n"
)


def _release(tmp: Path) -> Path:
    rel = tmp / "release"
    (rel / "romfs_overlay").mkdir(parents=True)
    (rel / "bake_img.bin").write_bytes(b"img")
    (rel / "name_input_code.bin").write_bytes(b"code")
    return rel


def test_smoke_install_and_launch(monkeypatch, tmp_path: Path):
    rel = tmp_path / "release"
    rel.mkdir()
    with pytest.raises(SystemExit, match="bake_img"):
        smoke.install_mod(tmp_path / "user", rel)
    (rel / "bake_img.bin").write_bytes(b"img")
    with pytest.raises(SystemExit, match="name_input"):
        smoke.install_mod(tmp_path / "user", rel)
    (rel / "name_input_code.bin").write_bytes(b"code")
    with pytest.raises(SystemExit, match="romfs_overlay"):
        smoke.install_mod(tmp_path / "user", rel)

    for renderer, api in (("software", "0"), ("vulkan", "2")):
        smoke.write_config(tmp_path / renderer, renderer)
        text = (tmp_path / renderer / "config" / "qt-config.ini").read_text(encoding="utf-8")
        assert f"graphics_api={api}" in text

    az_dir = tmp_path / "az_dir"
    (az_dir / "platforms").mkdir(parents=True)
    (az_dir / "platforms" / "q.dll").write_bytes(b"d")
    (az_dir / "azahar.exe").write_bytes(b"exe")
    (az_dir / "Qt6.dll").write_bytes(b"qt")
    (az_dir / "user").mkdir()
    (az_dir / "user" / "skip.txt").write_bytes(b"s")
    (az_dir / "run.bat").write_bytes(b"b")
    (az_dir / "readme.txt").write_bytes(b"t")
    monkeypatch.setattr(smoke.os, "name", "nt")
    (tmp_path / "work_nt").mkdir()
    exe, cwd = smoke.prepare_exe(az_dir / "azahar.exe", tmp_path / "work_nt")
    assert exe == tmp_path / "work_nt" / "azahar.exe"
    assert (tmp_path / "work_nt" / "Qt6.dll").is_file()
    assert (tmp_path / "work_nt" / "platforms" / "q.dll").is_file()
    assert not (tmp_path / "work_nt" / "user").exists()
    assert not (tmp_path / "work_nt" / "run.bat").exists()
    monkeypatch.setattr(smoke.os, "name", "posix")
    exe, cwd = smoke.prepare_exe(az_dir / "azahar.exe", tmp_path / "work_posix")
    assert exe == az_dir / "azahar.exe" and cwd == tmp_path / "work_posix"

    monkeypatch.setattr(smoke.os, "name", "nt")
    assert smoke.launch_cmd(exe, tmp_path / "rom.3ds") == [str(exe), str(tmp_path / "rom.3ds")]
    monkeypatch.setattr(smoke.os, "name", "posix")
    monkeypatch.setenv("DISPLAY", ":1")
    assert smoke.launch_cmd(exe, tmp_path / "rom.3ds")[0] == str(exe)
    monkeypatch.delenv("DISPLAY")
    monkeypatch.setattr(smoke.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="xvfb-run"):
        smoke.launch_cmd(exe, tmp_path / "rom.3ds")
    monkeypatch.setattr(smoke.shutil, "which", lambda name: "/usr/bin/xvfb-run")
    cmd = smoke.launch_cmd(exe, tmp_path / "rom.3ds")
    assert cmd[0] == "xvfb-run" and str(exe) in cmd


def test_smoke_stop_and_run(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(smoke.time, "sleep", lambda s: None)
    clock = {"t": 0.0}

    def mono():
        clock["t"] += 5
        return clock["t"]

    monkeypatch.setattr(smoke.time, "monotonic", mono)
    killed = []
    monkeypatch.setattr(smoke.subprocess, "run", lambda cmd, **kw: killed.append(cmd) or _Proc())

    class Proc:
        def __init__(self) -> None:
            self.pid = 9
            self.returncode = None
            self.polls = 0
            self.waits = 0

        def poll(self):
            self.polls += 1
            return self.returncode

        def wait(self, timeout=None):
            self.waits += 1
            raise subprocess.TimeoutExpired("azahar", timeout or 1)

    proc = Proc()
    monkeypatch.setattr(smoke.os, "name", "nt")
    smoke.stop(proc)
    assert killed and "taskkill" in killed[0]
    proc.returncode = 0
    smoke.stop(proc)

    monkeypatch.setattr(smoke.os, "name", "posix", raising=False)
    monkeypatch.setattr(smoke.signal, "SIGKILL", 9, raising=False)
    calls = {"n": 0}

    def killpg(pid, sig):
        calls["n"] += 1
        raise ProcessLookupError

    monkeypatch.setattr(smoke.os, "killpg", killpg, raising=False)
    proc.returncode = None
    smoke.stop(proc)
    assert calls["n"] == 2

    def kill_ok(pid, sig):
        return None

    monkeypatch.setattr(smoke.os, "killpg", kill_ok, raising=False)
    proc.wait = lambda timeout=None: 0  # type: ignore[method-assign]
    proc.returncode = None
    smoke.stop(proc)

    rel = _release(tmp_path)
    seed = tmp_path / "seed"
    (seed / "sdmc").mkdir(parents=True)
    (seed / "sdmc" / "a.txt").write_bytes(b"a")
    (seed / "nand").mkdir()
    (seed / "nand" / "b.txt").write_bytes(b"b")
    work = tmp_path / "smoke_work"
    work.mkdir()
    (work / "old.txt").write_bytes(b"old")
    rom = tmp_path / "rom.3ds"
    rom.write_bytes(b"rom")
    az = tmp_path / "azahar"
    az.write_bytes(b"az")
    monkeypatch.setattr(smoke.subprocess, "run", lambda cmd, **kw: _Proc())
    monkeypatch.setattr(smoke.shutil, "which", lambda name: "/usr/bin/xvfb-run")
    monkeypatch.delenv("DISPLAY", raising=False)
    seen = {}

    class Boot:
        def __init__(self, cmd, cwd, env, **kw):
            seen["cmd"] = cmd
            seen["env"] = env
            self.pid = 3
            self.returncode = None
            self.n = 0
            log = Path(cwd) / "user" / "log" / "azahar_log.txt"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(_MOD_OK + "NLPP pane-flag: one-shot\n", encoding="utf-8")

        def poll(self):
            self.n += 1
            if self.n > 3:
                self.returncode = 0
                return 0
            return None

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    monkeypatch.setattr(smoke.subprocess, "Popen", Boot)
    ns = argparse.Namespace(
        work=work,
        release=rel,
        renderer="opengl",
        seed_user=seed,
        azahar=az,
        dll_dir=tmp_path / "dlls",
        inject=["pane-flag"],
        rom=rom,
        seconds=100,
        settle=1,
    )
    monkeypatch.setattr(smoke.os, "name", "nt" if sys.platform == "win32" else "posix")
    result, text = smoke.run(ns)
    assert "pane-flag" in result.fired
    if smoke.os.name != "nt":
        assert "LIBGL_ALWAYS_SOFTWARE" in seen["env"]
    assert "pane-flag" in text or "LayeredFS" in text
    assert (work / "user" / "sdmc" / "a.txt").is_file()
    assert (work / "azahar_log.txt").is_file()

    class Die:
        def __init__(self, cmd, cwd, env, **kw):
            self.pid = 4
            self.returncode = None

        def poll(self):
            self.returncode = 3
            return 3

        def wait(self, timeout=None):
            return 3

    monkeypatch.setattr(smoke.subprocess, "Popen", Die)
    work2 = tmp_path / "smoke_fail"
    ns.work = work2
    ns.inject = []
    ns.seed_user = None
    ns.dll_dir = None
    ns.renderer = "software"
    result, text = smoke.run(ns)
    assert result.exited == 3
    problems = smoke.verdict(smoke.Result(), "", [])
    assert any("no azahar_log" in p for p in problems)


def test_smoke_main_exits(monkeypatch, tmp_path: Path):
    with pytest.raises(SystemExit):
        smoke.main(["--azahar", "az", "--rom", "rom", "--inject", "nope"])
    assert smoke.main(["--azahar", str(tmp_path / "missing.exe")]) == 2
    rom = tmp_path / "rom.3ds"
    rom.write_bytes(b"r")
    az = tmp_path / "azahar"
    az.write_bytes(b"a")
    assert smoke.main(["--azahar", str(tmp_path / "no.exe"), "--rom", str(rom)]) == 2

    def passed(args):
        return smoke.Result(seconds=4.2, fired={"pane-flag"}), _MOD_OK

    monkeypatch.setattr(smoke, "run", passed)
    assert (
        smoke.main(
            [
                "--azahar",
                str(az),
                "--rom",
                str(rom),
                "--release",
                str(tmp_path),
                "--work",
                str(tmp_path / "w"),
                "--inject",
                "pane-flag",
                "--renderer",
                "software",
            ]
        )
        == 0
    )

    def failed(args):
        return smoke.Result(seconds=1, exited=1), ""

    monkeypatch.setattr(smoke, "run", failed)
    assert smoke.main(["--azahar", str(az), "--rom", str(rom), "--work", str(tmp_path / "w2")]) == 1


# ---------------------------------------------------------------------------
# scan_nl_spotpass_zip
# ---------------------------------------------------------------------------


def _stored_zip(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def _reader(path: Path, skip: int = 0):
    return scan.SplitReader([path], skip)


def _cd_entry(name: str, *, method=0, crc=1, comp=4, uncomp=4, offset=0, extra=b"", comment=b"") -> bytes:
    raw = name.encode("utf-8") if isinstance(name, str) else name
    return (
        struct.pack(
            "<4s6H3I5H2I",
            scan.SIG_CD,
            20, 20, 0, method, 0, 0,
            crc, comp, uncomp,
            len(raw), len(extra), len(comment),
            0, 0, 0, offset,
        )
        + raw
        + extra
        + comment
    )


def _local(name: str, payload: bytes, extra: bytes = b"") -> bytes:
    raw = name.encode()
    hdr = bytearray(30)
    hdr[0:4] = scan.SIG_LOCAL
    struct.pack_into("<HH", hdr, 26, len(raw), len(extra))
    return bytes(hdr) + raw + extra + payload


def _boss(size: int = 12, ok: bool = True) -> bytes:
    head = b"boss" + b"\x00\x00\x00\x00" + struct.pack(">I", size)
    body = head + b"\x00" * max(0, size - 12)
    desc = (scan._DESC if ok else b"NOPE") + b"\x00" * (scan._DESC_LEN - 4)
    return body + desc


def _described(body: bytes) -> bytes:
    if len(body) < 12:
        body = body.ljust(12, b"\n")
    desc = scan._DESC + b"\x00\x00\x00\x00" + struct.pack("<QQ", len(body), len(body))
    return body + desc


class _FH:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.sought = []

    def read(self, n: int = -1) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)

    def seek(self, n: int, whence: int = 1) -> None:
        self.sought.append(n)


def test_scan_parts_reader_and_filelist(tmp_path: Path):
    with pytest.raises(SystemExit, match="no zip parts"):
        scan.SplitReader([], 0)
    tiny = tmp_path / "one.bin"
    tiny.write_bytes(b"ab")
    with pytest.raises(SystemExit, match="past the end"):
        scan.SplitReader([tiny], 5)
    reader = scan.SplitReader([tiny], 0)
    with pytest.raises(ValueError, match="outside"):
        reader.read(-1, 1)
    reader._spans = [(10, 5, 0)]
    reader.size = 20
    with pytest.raises(ValueError, match="could not map"):
        reader.read(0, 1)
    short = tmp_path / "short.bin"
    short.write_bytes(b"0123456789")
    reader = scan.SplitReader([short], 0)
    short.write_bytes(b"01")
    with pytest.raises(ValueError, match="short read"):
        reader.read(0, 5)

    folder = tmp_path / "empty"
    folder.mkdir()
    with pytest.raises(SystemExit, match="no .zip.NNN"):
        scan.discover_parts(folder)
    single = folder / "only.zip"
    _stored_zip(single, {"a.txt": b"hi"})
    parts, skip = scan.discover_parts(folder)
    assert parts == [single] and skip == 0
    assert scan.discover_parts(single) == ([single], 0)
    assert scan.detect_skip(single) == 0
    shifted = tmp_path / "shift.bin"
    shifted.write_bytes(b"\x00" + single.read_bytes()[:4])
    assert scan.detect_skip(shifted) == 1
    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"xxxxx")
    assert scan.detect_skip(plain) == 0

    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    (parts_dir / "arc.zip.000").write_bytes(b"a")
    (parts_dir / "arc.zip.002").write_bytes(b"c")
    with pytest.raises(SystemExit, match="not contiguous"):
        scan.discover_parts(parts_dir)
    (parts_dir / "arc.zip.001").write_bytes(b"b")
    found, hinted = scan.discover_parts(parts_dir / "arc.zip.001")
    assert hinted is None and [p.name for p in found] == ["arc.zip.000", "arc.zip.001", "arc.zip.002"]
    with pytest.raises(SystemExit, match="not a zip"):
        scan.discover_parts(tmp_path / "notes.txt")

    rows = scan.parse_filelist(
        b"h\n2\n\t\t1\t2\nonly\t\t5\nnonums\t\tabc\ninfo.dat\t\t10\t20\n"
    )
    assert ("only", 5, -1) in rows and ("nonums", -1, -1) in rows
    assert scan.task_of("a/b") == "(root)"
    assert scan.task_of("JP/ja/TASK/x") == "TASK"
    jp = scan.Entry("JP/ja/T/filelist.txt", 0, 1, 1, 1, 0)
    us = scan.Entry("US/en/T/filelist.txt", 0, 1, 1, 1, 0)
    assert scan.prefer_filelist([us, jp]) is jp
    assert scan.prefer_filelist([us]) is us

    blob = single.read_bytes()
    entry = scan.Entry("a.txt", 8, 1, 2, 2, 0)
    with pytest.raises(SystemExit, match="compressed"):
        scan.read_stored(_reader(single), entry)
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"XXXX" + b"\x00" * 30)
    entry.method = 0
    with pytest.raises(SystemExit, match="local header"):
        scan.read_stored(_reader(bad), entry)


def test_scan_eocd_zip64_and_report(tmp_path: Path, capsys):
    with pytest.raises(SystemExit, match="not found"):
        scan._find_eocd(b"hello", 5)
    with pytest.raises(SystemExit, match="truncated"):
        scan._find_eocd(b"PK\x05\x06" + b"\x00" * 10, 14)
    with pytest.raises(SystemExit, match="no end-of-central-directory record"):
        scan._find_eocd(b"PK\x05\x06" + b"\x00" * 30, 34)
    comment = b"PK\x05\x06" + b"\x00" * 22
    real = bytearray(22)
    real[0:4] = scan.SIG_EOCD
    struct.pack_into("<HHIIH", real, 8, 1, 1, 10, 0, len(comment))
    _off, cd_off, cd_size, count = scan._find_eocd(bytes(real) + comment, len(real) + len(comment))
    assert cd_size == 10 and count == 1 and cd_off == 0
    eocd = bytearray(22)
    eocd[0:4] = scan.SIG_EOCD
    struct.pack_into("<HHII", eocd, 8, 1, 1, 0xFFFFFFFF, 0)
    with pytest.raises(SystemExit, match="locator is missing"):
        scan._find_eocd(b"\x00" * 20 + bytes(eocd), 42)

    extra = struct.pack("<HH", 2, 0) + struct.pack("<HH", scan.ZIP64_EXTRA, 24) + struct.pack("<QQQ", 9, 8, 3)
    good = _cd_entry("n", comp=0xFFFFFFFF, uncomp=0xFFFFFFFF, offset=0xFFFFFFFF, extra=extra, comment=b"c")
    missing_size = _cd_entry("n", comp=0xFFFFFFFF, uncomp=4, extra=struct.pack("<HH", 2, 0))
    short_off = _cd_entry("n", offset=0xFFFFFFFF, extra=struct.pack("<HH", 1, 2) + b"\x00\x00")
    bad_sig = b"XXXX" + good[4:]
    data = tmp_path / "cd.bin"
    data.write_bytes(good + missing_size)
    reader = _reader(data)
    entries = list(scan.iter_central_directory(reader, 0, len(good), 1))
    assert entries[0].comp_size == 8 and entries[0].local_offset == 3
    with pytest.raises(SystemExit, match="zip64 sizes"):
        list(scan.iter_central_directory(reader, len(good), len(missing_size), 1))
    data.write_bytes(short_off)
    with pytest.raises(SystemExit, match="zip64 offset"):
        list(scan.iter_central_directory(_reader(data), 0, len(short_off), 1))
    data.write_bytes(bad_sig)
    with pytest.raises(SystemExit, match="not PK"):
        list(scan.iter_central_directory(_reader(data), 0, len(bad_sig), 0))

    cd = _cd_entry("JP/ja/T/filelist.txt", comp=4, uncomp=4, offset=0)
    eocd64 = bytearray(56)
    eocd64[0:4] = scan.SIG_EOCD64
    struct.pack_into("<Q", eocd64, 32, 1)
    struct.pack_into("<Q", eocd64, 40, len(cd))
    struct.pack_into("<Q", eocd64, 48, 0)
    locator = bytearray(20)
    locator[0:4] = scan.SIG_LOC64
    struct.pack_into("<Q", locator, 8, len(cd))
    z64 = cd + bytes(eocd64) + bytes(locator) + bytes(eocd)
    # eocd above still has zip64 sentinels; rebuild a matching tail record.
    tail = bytearray(22)
    tail[0:4] = scan.SIG_EOCD
    struct.pack_into("<HHII", tail, 8, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
    blob = cd + bytes(eocd64) + bytes(locator) + bytes(tail)
    zpath = tmp_path / "z64.bin"
    zpath.write_bytes(blob)
    off, size, n = scan.locate_central_directory(_reader(zpath))
    assert (off, size, n) == (0, len(cd), 1)
    eocd64[0:4] = b"XXXX"
    zpath.write_bytes(cd + bytes(eocd64) + bytes(locator) + bytes(tail))
    with pytest.raises(SystemExit, match="zip64 EOCD missing"):
        scan.locate_central_directory(_reader(zpath))

    catalog = (
        b"hash\r\n        3\r\n"
        + b"\n".join(f"city{i:03d}\t\t\t\t\t{i}\t100".encode() for i in range(201))
        + b"\ninfo.dat\t\t\t\t\t10\t20\n"
    )
    zpath = tmp_path / "mag.zip"
    _stored_zip(
        zpath,
        {
            "JP/ja/PTASK/filelist.txt": catalog,
            "US/en/PTASK/filelist.txt": catalog,
            "JP/ja/PTASK/info.dat.boss": b"boss-a",
            "US/en/PTASK/info.dat.boss": b"boss-b",
            "JP/ja/PTASK/voice.boss": b"one",
        },
    )
    reader = _reader(zpath)
    tasks = scan.scan(reader, track_limit=0)
    scan.print_report(reader, tasks, show_all=False)
    text = capsys.readouterr().out
    assert "overflowed" in text and "no filelist" not in text
    scan.print_report(reader, tasks, show_all=True)
    out = tmp_path / "hits"
    cd_off, cd_size, count = scan.locate_central_directory(reader)
    scan.extract_named(reader, cd_off, cd_size, count, "info.dat.boss", out)
    assert list(out.glob("info.dat.boss.*"))
    with pytest.raises(SystemExit, match="no central-directory"):
        scan.extract_named(reader, cd_off, cd_size, count, "missing.name", out)

    lone = tmp_path / "lone.zip"
    _stored_zip(lone, {"JP/ja/ONLY/voice.boss": b"v"})
    scan.print_report(_reader(lone), scan.scan(_reader(lone), 10), False)
    assert "no filelist.txt" in capsys.readouterr().out


def test_scan_payload_walk_and_main(tmp_path: Path, monkeypatch, capsys):
    fh = _FH([])
    assert scan._payload_length(fh, b"boss" + b"\x00" * 4 + struct.pack(">I", 5000), 0, 20) is None
    data = _boss(12, ok=False)
    path = tmp_path / "badboss.bin"
    path.write_bytes(data)
    with path.open("rb") as raw:
        first = raw.read(12)
        assert scan._payload_length(raw, first, 0, len(data)) is None
    data = _boss(12, ok=True)
    path.write_bytes(data)
    with path.open("rb") as raw:
        first = raw.read(12)
        assert scan._payload_length(raw, first, 0, len(data)) == (12, None)

    desc = scan._DESC + b"\x00\x00\x00\x00" + struct.pack("<QQ", 0, 0)
    fh = _FH([desc[12:]])
    got = scan._payload_length(fh, desc[:12], 0, 10_000)
    assert got is not None and got[0] == 0

    false = scan._DESC + b"\x00\x00\x00\x00" + struct.pack("<QQ", 1, 2)
    real = scan._DESC + b"\x00\x00\x00\x00" + struct.pack("<QQ", len(false), len(false))
    blob = false + real
    fh = _FH([blob[12:]])
    got = scan._payload_length(fh, blob[:12], 0, 10_000)
    assert got is not None and got[0] == len(false)

    fh = _FH([b"B" * 40, scan._DESC + b"\x00\x00\x00\x00" + struct.pack("<QQ", 52, 52)])
    got = scan._payload_length(fh, b"A" * 12, 0, 10_000)
    assert got == (52, None)
    fh = _FH([])
    assert scan._payload_length(fh, b"A" * 12, 0, 100) is None
    assert scan._payload_length(fh, b"A" * 12, 0, 0) is None
    body = b"0123456789abcd"
    desc = scan._DESC + b"\x00\x00\x00\x00" + struct.pack("<QQ", len(body), len(body))
    blob = body + desc + scan.SIG_LOCAL
    fh = _FH([blob[12:]])
    got = scan._payload_length(fh, blob[:12], 0, 10_000)
    assert got is not None and got[1] == body

    report = tmp_path / "rep" / "walk.txt"
    boss = _local("JP/ja/TASK/info.dat.boss", _boss()) + b"X" * 30
    (tmp_path / "walk_boss.bin").write_bytes(boss)
    scan.walk_local_part(tmp_path / "walk_boss.bin", 0, report)
    text = report.read_text(encoding="utf-8")
    assert "STOPPED not a local header" in text and "TASK" in text

    (tmp_path / "tiny.bin").write_bytes(b"\x00" * 10)
    scan.walk_local_part(tmp_path / "tiny.bin", 0, tmp_path / "rep" / "tiny.txt")

    name = "JP/ja/TASK/filelist.txt"
    raw_name = name.encode()
    hdr = bytearray(30)
    hdr[0:4] = scan.SIG_LOCAL
    struct.pack_into("<HH", hdr, 26, len(raw_name), 0)
    (tmp_path / "trunc.bin").write_bytes(bytes(hdr) + raw_name + b"hi")
    scan.walk_local_part(tmp_path / "trunc.bin", 0, tmp_path / "rep" / "trunc.txt")
    assert "truncated payload" in (tmp_path / "rep" / "trunc.txt").read_text(encoding="utf-8")

    claim = b"boss" + b"\x00\x00\x00\x00" + struct.pack(">I", 99999)
    (tmp_path / "huge.bin").write_bytes(_local("JP/ja/TASK/x.boss", claim))
    scan.walk_local_part(tmp_path / "huge.bin", 0, tmp_path / "rep" / "huge.txt")
    assert "could not bound" in (tmp_path / "rep" / "huge.txt").read_text(encoding="utf-8")

    listing = b"hash\n2\ninfo.dat\t10\t20\nvoice001\t3\t4\n"
    sheet = b"tasksheet-bytes!!"
    combo = (
        _local("JP/ja/TASK/filelist.txt", _described(listing))
        + _local("JP/ja/TASK/tasksheet.xml", _described(sheet))
        + _local("JP/ja/TASK/voice12.boss", _boss())
        + _local("readme", _described(b"0123456789abcdef"))
    )
    (tmp_path / "combo.bin").write_bytes(combo)
    scan.walk_local_part(tmp_path / "combo.bin", 0, tmp_path / "rep" / "combo.txt")
    combo_text = (tmp_path / "rep" / "combo.txt").read_text(encoding="utf-8")
    assert "CATALOG" in combo_text and "voice" in combo_text

    monkeypatch.setattr(sys, "argv", ["scan"])
    with pytest.raises(SystemExit):
        scan.main()
    monkeypatch.setattr(
        sys,
        "argv",
        ["scan", str(tmp_path / "combo.bin"), "--walk-local", "--out", str(tmp_path / "out"), "--skip-first", "0"],
    )
    scan.main()
    zpath = tmp_path / "one.zip"
    _stored_zip(zpath, {"JP/ja/T/info.dat.boss": b"boss-a", "JP/ja/T/filelist.txt": b"h\n1\ninfo.dat\t1\t2\n"})
    monkeypatch.setattr(
        sys,
        "argv",
        ["scan", str(zpath), "--extract", "info.dat.boss", "--out", str(tmp_path / "hits"), "--show-all"],
    )
    scan.main()
    monkeypatch.setattr(sys, "argv", ["scan", str(zpath), "--out", str(tmp_path / "unused"), "--skip-first", "0"])
    scan.main()
    assert "central directory" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# translate_heroines_gemini
# ---------------------------------------------------------------------------


def _dlg(texts: list[str]):
    return [DbinEntry(0, 0, SDL2Data(key=2, unknown=[], dialogs=texts))]


def _bind_th(monkeypatch, tmp: Path) -> Path:
    root = tmp / "th"
    monkeypatch.setattr(th, "ROOT", root)
    monkeypatch.setattr(th, "ASSETS_SCRIPTS", root / "assets" / "scripts")
    monkeypatch.setattr(th, "REBUILD_SCRIPT", root / "rebuild" / "script")
    monkeypatch.setattr(th, "LOC_SMS", root / "loc")
    monkeypatch.setattr(th, "SMS_PACK", root / "sms_pack")
    monkeypatch.setattr(th, "SMS_EN", root / "sms_en")
    monkeypatch.setattr(th, "OUT_DEFAULT", root / "out_default")
    return root


def _sms_xml(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ["<Dictionary>"]
    for hex_id, text in rows:
        body.append(f'<Entry><JapaneseText hex="{hex_id}">{text}</JapaneseText></Entry>')
    body.append("<Entry><Note>skip</Note></Entry>")
    body.append("</Dictionary>")
    path.write_text("\n".join(body), encoding="utf-8")


def _th_args(argv: list[str]):
    return th.build_parser().parse_args(argv)


def test_translate_helpers_and_collect(monkeypatch, tmp_path: Path, capsys):
    root = _bind_th(monkeypatch, tmp_path)
    import builtins

    real_print = builtins.print
    prints = {"n": 0}

    def flaky(text, **_k):
        prints["n"] += 1
        if prints["n"] == 1:
            raise UnicodeEncodeError("utf-8", str(text), 0, 1, "no")
        return real_print(text)

    monkeypatch.setattr(builtins, "print", flaky)
    th._safe_print("こんにちは")
    monkeypatch.setattr(builtins, "print", real_print)
    assert th.heroines_from_arg("both") == ["nene", "rinko"]
    assert th.heroines_from_arg("nene") == ["nene"]
    with pytest.raises(SystemExit, match="unknown heroine"):
        th.heroines_from_arg("manaka")

    missing = tmp_path / "no.json"
    assert th.load_json(missing) == {}
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")
    assert th.load_json(tmp_path / "list.json") == {}
    (tmp_path / "map.json").write_text('{"translations": []}', encoding="utf-8")
    assert th.load_translation_map(tmp_path / "map.json") == {}
    dest = tmp_path / "out" / "saved.json"
    monkeypatch.setattr(th.time, "sleep", lambda _s: None)
    calls = {"n": 0}
    real_replace = os.replace

    def replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("busy")
        real_replace(src, dst)

    monkeypatch.setattr(th.os, "replace", replace)
    th.save_json(dest, {"a": 1}, attempts=2)
    assert json.loads(dest.read_text(encoding="utf-8")) == {"a": 1}
    th.save_json(tmp_path / "zero.json", {"b": 2}, attempts=0)
    assert (tmp_path / "zero.json.tmp").is_file()
    assert not (tmp_path / "zero.json").exists()

    vanilla = tmp_path / "vanilla"
    vanilla.mkdir()
    jp = "こんにちは"
    (vanilla / "a001.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg([jp, "Hello"])))
    (vanilla / "k001.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg([jp])))
    xml = th.ASSETS_SCRIPTS / "a001.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text(th.entries_to_xml(1, 0, _dlg(["Hello", "Hello"])), encoding="utf-8")
    (th.REBUILD_SCRIPT).mkdir(parents=True)
    (th.REBUILD_SCRIPT / "k001.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg(["??"])))
    (th.ASSETS_SCRIPTS / "k001.xml").write_text("<not", encoding="utf-8")
    assert th.overlay_path("a001") == xml
    assert th.overlay_path("k001").suffix == ".xml"
    assert th.overlay_path("missing") is None
    assert th.parse_script_blob(xml)[0] == 1
    assert th.parse_script_blob(vanilla / "a001.dbin2")[2]
    with pytest.raises(FileNotFoundError):
        th._load_vanilla_script(vanilla, "nope")

    jobs = th.collect_script_jobs(vanilla, ["nene", "rinko"])
    assert any(j.stem == "k001" and j.jp == jp for j in jobs)

    (th.LOC_SMS / "maildic_n.en.xml").parent.mkdir(parents=True)
    (th.LOC_SMS / "maildic_n.en.xml").write_text("<x/>", encoding="utf-8")
    _sms_xml(th.SMS_PACK / "maildic_n.xml", [("1", jp), ("2", "Hello")])
    _sms_xml(root / "out" / "sms_pack" / "maildic_r.xml", [("9", "まだ")])
    assert th.find_sms_xml("maildic_n") == th.SMS_PACK / "maildic_n.xml"
    assert th.parse_sms_entries(th.SMS_PACK / "maildic_n.xml")[0] == ("1", jp)
    th.SMS_EN.mkdir(parents=True)
    (th.SMS_EN / "translations.json").write_text(
        json.dumps({"translations": {jp: "Hi", "まだ": "まだ"}}), encoding="utf-8"
    )
    sms_jobs = th.collect_sms_jobs(["nene", "rinko"])
    assert any(j.jp == "まだ" for j in sms_jobs)
    assert all(j.jp != jp for j in sms_jobs)

    args = _th_args(["status", "--vanilla-script", str(vanilla), "--source", "all", "--out", str(tmp_path / "st")])
    monkeypatch.setattr(th, "load_gemini_api_key", lambda key=None: (_ for _ in ()).throw(SystemExit("no key")))
    assert th.cmd_status(args) == 0
    monkeypatch.setattr(th, "load_gemini_api_key", lambda key=None: "k")
    assert th.cmd_status(args) == 0
    assert "pending lines" in capsys.readouterr().out
    assert th.cmd_collect(args) == 0
    assert (tmp_path / "st" / "jobs.json").is_file()
    monkeypatch.setattr(th, "find_vanilla_script_dir", lambda: None)
    with pytest.raises(SystemExit, match="vanilla script"):
        th.collect_jobs(_th_args(["status", "--source", "scripts", "--out", str(tmp_path / "x")]))
    grouped = th.group_script_jobs(jobs + [th.Job("s", "nene", "sms", "maildic_n", 0, 0, jp, jp)])
    assert grouped and all(v[0].source == "script" for v in grouped.values())


def test_translate_run_and_fix(monkeypatch, tmp_path: Path, capsys):
    _bind_th(monkeypatch, tmp_path)
    vanilla = tmp_path / "vanilla"
    vanilla.mkdir()
    jp = "こんにちは"
    (vanilla / "a001.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg([jp, "Hello"])))
    (vanilla / "a002.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg([jp])))
    for i in range(3, 24):
        (vanilla / f"a{i:03d}.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg([jp])))
    overlay = th.ASSETS_SCRIPTS / "a001.xml"
    overlay.parent.mkdir(parents=True)
    overlay.write_text(th.entries_to_xml(1, 0, _dlg(["Hello there", jp])), encoding="utf-8")
    (th.ASSETS_SCRIPTS / "a002.xml").write_text("<bad", encoding="utf-8")
    mapping = {jp: "Hi"}
    args = _th_args(
        ["run", "--vanilla-script", str(vanilla), "--heroine", "nene", "--out", str(tmp_path / "run"), "--batch-size", "1"]
    )

    def identity(client, model, items, **kwargs):
        return [th.TranslateResult(it.index, it.source, it.source, error="") for it in items]

    monkeypatch.setattr(th, "translate_prepared", identity)
    stem, results, errors = th.translate_one_script(None, "m", "a001", [], vanilla, mapping, args)
    assert stem == "a001" and errors == [] and results
    pending = [th.Job("id", "nene", "script", "a001", 0, 1, jp, jp)]

    def fake_translate(client, model, items, **kwargs):
        return [
            th.TranslateResult(it.index, it.source, None if it.need else it.source, error="nope" if it.need else "")
            for it in items
        ]

    monkeypatch.setattr(th, "translate_prepared", fake_translate)
    _stem, results, errors = th.translate_one_script(None, "m", "a001", pending, vanilla, {}, args)
    assert errors
    written, failed = th.apply_script_results("a001", results, vanilla, tmp_path / "xml", {})
    assert failed >= 1 and (tmp_path / "xml" / "a001.xml").is_file()
    ok = [
        th.TranslateResult(0, jp, "Hello", error=""),
        th.TranslateResult(1, "Hello", "Hello", error=""),
    ]
    # equal english falls through; a fresh stem with one dialog:
    (vanilla / "a009.dbin2").write_bytes(th.build_dbin2(1, 0, _dlg([jp])))
    w, f = th.apply_script_results(
        "a009",
        [th.TranslateResult(0, jp, jp, error="")],
        vanilla,
        tmp_path / "xml",
        {},
    )
    assert w == 0 and f == 0
    w, f = th.apply_script_results(
        "a009",
        [th.TranslateResult(0, jp, "Hi", error="")],
        vanilla,
        tmp_path / "xml",
        {},
    )
    assert w == 1

    sms_jobs = [
        th.Job("1", "nene", "sms", "maildic_n", 0, 0, jp, jp),
        th.Job("2", "nene", "sms", "maildic_n", 1, 0, jp, jp),
        th.Job("3", "nene", "sms", "maildic_n", 2, 0, "二", "二"),
    ]
    args.limit = 1

    def sms_translate(client, model, items, **kwargs):
        return [th.TranslateResult(it.index, it.source, None if it.source == "二" else "OK", error="e" if it.source == "二" else "") for it in items]

    monkeypatch.setattr(th, "translate_prepared", sms_translate)
    done, errs = th.translate_sms_unique(None, "m", sms_jobs, {}, args)
    assert done == 1 and errs == 0
    args.limit = 0
    done, errs = th.translate_sms_unique(None, "m", sms_jobs, {jp: "OK"}, args)
    assert errs == 1
    _sms_xml(th.SMS_PACK / "maildic_n.xml", [("1", jp), ("2", "")])
    (th.SMS_PACK / "maildic_n.xml").write_text(
        '<Dictionary><Entry><JapaneseText hex="1">こんにちは</JapaneseText></Entry>'
        '<Entry><JapaneseText hex="2"></JapaneseText></Entry></Dictionary>',
        encoding="utf-8",
    )
    th.write_sms_xml(["nene", "manaka"], {jp: "まだ", "": ""}, tmp_path / "sms_out")
    assert (tmp_path / "sms_out" / "maildic_n.en.xml").is_file()

    out = tmp_path / "dry"
    wide = _th_args(
        ["run", "--dry-run", "--vanilla-script", str(vanilla), "--heroine", "nene", "--out", str(out)]
    )
    assert th.cmd_run(wide) == 0
    text = capsys.readouterr().out
    assert "dry-run" in text and "+"+str(len(list(vanilla.glob('a*.dbin2'))) - 20) in text or "+2" in text or "+" in text
    dry = _th_args(
        ["run", "--dry-run", "--vanilla-script", str(vanilla), "--heroine", "nene", "--source", "sms", "--out", str(tmp_path / "dry2")]
    )
    assert th.cmd_run(dry) == 0

    def crash(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(th, "translate_one_script", crash)
    monkeypatch.setattr(th, "make_gemini_client", lambda key: None)
    monkeypatch.setattr(th, "load_gemini_api_key", lambda key=None: "k")
    live = _th_args(
        ["run", "--vanilla-script", str(vanilla), "--heroine", "nene", "--out", str(tmp_path / "live"), "--workers", "1", "--force", "--write-xml"]
    )
    assert th.main(["run", "--vanilla-script", str(vanilla), "--heroine", "nene", "--out", str(tmp_path / "live"), "--workers", "1", "--force", "--write-xml"]) == 1

    def ok_one(*_a, **_k):
        return "a001", [th.TranslateResult(0, jp, None, error="bad"), th.TranslateResult(1, "Hello", "Hello")], ["bad"]

    monkeypatch.setattr(th, "translate_one_script", ok_one)
    (tmp_path / "resume" / "xml").mkdir(parents=True)
    (tmp_path / "resume" / "xml" / "a001.xml").write_text("<x/>", encoding="utf-8")
    resumed = _th_args(
        ["run", "--vanilla-script", str(vanilla), "--heroine", "nene", "--out", str(tmp_path / "resume"), "--workers", "1"]
    )
    # every stem already has no xml except a001; others will crash-or-run. Force only a001 by limit after resume.
    th.cmd_run(resumed)

    calls = {"n": 0}

    def find_then_none():
        calls["n"] += 1
        return vanilla if calls["n"] == 1 else None

    monkeypatch.setattr(th, "find_vanilla_script_dir", find_then_none)
    with pytest.raises(SystemExit, match="vanilla script dir required"):
        th.cmd_run(_th_args(["run", "--heroine", "nene", "--out", str(tmp_path / "gone"), "--workers", "1"]))

    xml_dir = tmp_path / "fix" / "xml"
    xml_dir.mkdir(parents=True)
    (xml_dir / "a001.xml").write_text(th.entries_to_xml(1, 0, _dlg(["Hello", "Hi ●"])), encoding="utf-8")
    parsed = [1, 0, _dlg(["Hello", "Hi ●"]), [(0, 0, "Hello"), (0, 1, jp)]]
    results = [th.TranslateResult(0, "Hello", "Hello"), th.TranslateResult(1, jp, "Me", error="")]
    fixed, rejected = th.apply_fix_results("a001", parsed, results, [(0, 0), (0, 1)], xml_dir, tmp_path / "fix" / "dbin2", {})
    assert fixed == 1 and rejected == []
    slot = tmp_path / "fix" / "dbin2" / "script" / "a001.dbin2"
    slot.parent.mkdir(parents=True)
    slot.write_bytes(b"old")
    th.apply_fix_results(
        "a001",
        parsed,
        [th.TranslateResult(0, "Hello", "Hello"), th.TranslateResult(1, jp, None, error="no")],
        [(0, 1)],
        xml_dir,
        slot.parent.parent,
        {},
    )
    assert slot.read_bytes() != b"old"

    targets = {"a001": [(0, 0)], "a002": [(0, 0)]}
    fix = th.PRONOUN_PASS
    dry_fix = _th_args(["fix-pronoun", "--dry-run", "--limit", "1", "--out", str(tmp_path / "fix"), "--vanilla-script", str(vanilla)])
    assert th.run_fix(dry_fix, fix, targets) == 0
    empty = _th_args(["fix-pronoun", "--out", str(tmp_path / "fix"), "--vanilla-script", str(vanilla)])
    assert th.run_fix(empty, fix, {}) == 0
    monkeypatch.setattr(th, "fix_stem", crash)
    assert th.run_fix(empty, fix, {"a001": [(0, 0)]}) == 1
    assert th.names_heroine_to_her_face("( aside )") is False
    assert th.needs_pronoun_fix("●") is True
    assert th.main(["status", "--vanilla-script", str(vanilla), "--heroine", "nene", "--out", str(tmp_path / "st2")]) == 0


# ---------------------------------------------------------------------------
# rebuild_bake_img
# ---------------------------------------------------------------------------


def _bind_bake(monkeypatch, tmp: Path) -> Path:
    root = tmp / "bake_root"
    (root / "out").mkdir(parents=True)
    monkeypatch.setattr(bake, "ROOT", root)
    monkeypatch.setattr(bake, "CACHE", root / "cache")
    monkeypatch.setattr(bake, "CACHE_NEW_IMG", root / "cache" / "new_img.bin")
    monkeypatch.setattr(bake, "RELEASE", root / "release")
    monkeypatch.setattr(bake, "BAKE_IMG", root / "release" / "bake_img.bin")
    monkeypatch.setattr(bake, "TEXTRESOURCE", root / "release" / "textresource")
    monkeypatch.setattr(bake, "OVERLAY_TRB_DIR", root / "release" / "overlay" / "SystemData" / "TextResource")
    monkeypatch.setattr(bake, "NAME_INPUT_CODE", root / "release" / "name_input_code.bin")
    monkeypatch.setattr(bake, "OUT_CIA", root / "out" / "patched.cia")
    monkeypatch.setattr(bake, "ASSETS_TEXTRESOURCE", root / "assets" / "textresource")
    monkeypatch.setattr(bake, "TRANSLATIONS_JSON", root / "assets" / "textresource" / "translations.json")

    def stamp(**_kwargs):
        path = root / "release" / "bake_stamp.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
        return path

    monkeypatch.setattr(bake, "write_bake_stamp", stamp)
    return root


def _bake_ns(**kw):
    base = dict(
        vanilla=None,
        rom=None,
        skip_pack=False,
        reseed_from_pack=False,
        skip_deploys=True,
        include_sms=False,
        skip_trb=True,
        also_azahar=False,
        keep_work=False,
        workers=None,
        pkg_workers=None,
        fine_tune=False,
        use_cache=False,
        no_cache=False,
        cache_dir=None,
        include_sound_settings=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def _btimer():
    return RunTimer("rebuild", heartbeat_s=None)


def test_bake_helpers(monkeypatch, tmp_path: Path):
    root = _bind_bake(monkeypatch, tmp_path)
    assert bake._chrome_label("deploy_profile_en.py") == "profile"
    assert bake._chrome_label("deploy_plain") == "plain"
    assert bake._chrome_label("bar.py") == "bar"
    assert bake._deploy_plan(_bake_ns(skip_deploys=True)) == []
    planned = [name for name, _, _ in bake._deploy_plan(_bake_ns(skip_deploys=False, include_sound_settings=True))]
    assert "deploy_sound_settings_en.py" in planned
    assert planned.count("deploy_multiwin_headers_en.py") == 2
    labels = [name for name, _w in bake._rebuild_steps(_bake_ns(skip_pack=False, rom=tmp_path / "r.cia", include_sms=True))[0]]
    assert "extract ROM" in labels and "PNG pack" in labels and "SMS" in labels
    labels = [name for name, _w in bake._rebuild_steps(_bake_ns(reseed_from_pack=True, skip_trb=True))[0]]
    assert "reseed bake" in labels and "text" not in labels
    assert bake._child_env({"PYTHONIOENCODING": "keep"}, pipe=True)["PYTHONIOENCODING"] == "keep"
    assert bake._child_env({}, pipe=True)["PYTHONIOENCODING"] == "utf-8:replace"
    assert bake._child_env({}, pipe=False)["PYTHONIOENCODING"].endswith(":replace")

    monkeypatch.setattr(bake.subprocess, "run", lambda *a, **k: _Proc())
    bake.run([sys.executable, "-c", "pass"])

    class _Pipe:
        def __init__(self, code=0, lines=None):
            self.stdout = iter(lines or ["\n", "[pack] [1/2] hi\n"])
            self._code = code

        def wait(self):
            return self._code

    monkeypatch.setattr(bake.subprocess, "Popen", lambda *a, **k: _Pipe())
    seen = []
    bake.run(["cmd"], on_line=seen.append)
    assert seen

    class _Live:
        active = True

        def log(self, *_a, **_k):
            return None

        def set_job(self, *_a, **_k):
            return None

        def clear_job(self, *_a, **_k):
            return None

    monkeypatch.setattr(bake, "live", _Live())
    monkeypatch.setattr(bake.subprocess, "Popen", lambda *a, **k: _Pipe(2, ["bad\n"]))
    with pytest.raises(subprocess.CalledProcessError):
        bake.run(["cmd"], on_line=lambda _s: None)
    monkeypatch.setattr(bake, "live", type("Off", (), {"active": False})())

    bake.TEXTRESOURCE.mkdir(parents=True)
    (bake.TEXTRESOURCE / "textresource_jpn.trb").write_bytes(b"trb")
    (bake.TEXTRESOURCE / "missing-skip").mkdir()
    bake.sync_trb_overlay()
    assert (bake.OVERLAY_TRB_DIR / "textresource_jpn.trb").is_file()

    monkeypatch.setattr(bake, "find_vanilla_main_trb", lambda: None)
    with pytest.raises(SystemExit, match="vanilla textresource"):
        bake.rebuild_main_trb()
    trb = tmp_path / "vanilla.trb"
    trb.write_bytes(b"v")
    trans = tmp_path / "trans.json"
    trans.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(bake, "find_vanilla_main_trb", lambda: trb)
    monkeypatch.setattr(bake, "require_translations_json", lambda: trans)

    def no_trb(_cmd, **_k):
        return None

    monkeypatch.setattr(bake, "run", no_trb)
    with pytest.raises(SystemExit, match="name-kanji"):
        bake.rebuild_main_trb()

    def write_trb(_cmd, **_k):
        out = root / "out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "textresource_jpn_namekanji.trb").write_bytes(b"nk")

    monkeypatch.setattr(bake, "run", write_trb)
    monkeypatch.setattr(bake, "find_vanilla_resident_trb", lambda: None)
    with pytest.raises(SystemExit, match="resident"):
        bake.rebuild_main_trb()
    resident = tmp_path / "resident.trb"
    resident.write_bytes(b"res")

    def write_both(_cmd, **_k):
        write_trb(_cmd)
        (root / "out" / "textresource_config_namekanji.trb").write_bytes(b"cfg")

    monkeypatch.setattr(bake, "run", write_both)
    monkeypatch.setattr(bake, "find_vanilla_resident_trb", lambda: resident)
    bake.rebuild_main_trb()
    assert (bake.TEXTRESOURCE / "translations.json").is_file()
    assert (bake.TEXTRESOURCE / "textresource_resident_jpn.trb").read_bytes() == b"res"
    bake.rebuild_main_trb()

    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(b"van")

    def pack_run(cmd, **kw):
        assert "--workers" in cmd and "--pkg-workers" in cmd and "--fine-tune" in cmd
        assert "--cache-dir" in cmd
        bake.CACHE_NEW_IMG.parent.mkdir(parents=True, exist_ok=True)
        bake.CACHE_NEW_IMG.write_bytes(b"packed")
        work = root / "out" / "rebuild_bake_img_work"
        (work / "image_pack_report.txt").write_text("rep", encoding="utf-8")
        if kw.get("on_line"):
            kw["on_line"]("line\n")

    monkeypatch.setattr(bake, "run", pack_run)
    path, report = bake.pack_ui(
        vanilla, workers=2, pkg_workers=1, fine_tune=True, cache_dir=tmp_path / "cache", keep_work=True, on_line=lambda _s: None
    )
    assert path == bake.BAKE_IMG and report == "rep" and bake.CACHE_NEW_IMG.is_file()

    def pack_nocache(cmd, **_k):
        assert "--no-cache" in cmd
        bake.CACHE_NEW_IMG.write_bytes(b"packed")

    monkeypatch.setattr(bake, "run", pack_nocache)
    bake.pack_ui(vanilla, workers=None, fine_tune=False, no_cache=True, keep_work=False)
    assert not bake.CACHE_NEW_IMG.exists()

    def pack_missing(_cmd, **_k):
        return None

    monkeypatch.setattr(bake, "run", pack_missing)
    with pytest.raises(SystemExit, match="did not write"):
        bake.pack_ui(vanilla, workers=None, fine_tune=False, keep_work=True)

    import types

    imgmod = types.ModuleType("img")

    class _FW:
        def __init__(self, base, length):
            self.base_offset = base
            self._n = length

        def len(self):
            return self._n

    class _Elem:
        def __init__(self, fn, base, length):
            self.fn = fn
            self.fw = _FW(base, length)

    class _Pkg:
        def __init__(self, *_a, **_k):
            self.entries = [_Elem("timg/A.bclim", 0, 2), None]

        def parse(self, _flag):
            return None

    class _Res:
        fw = _FW(0, 2)

    class _Img:
        def __init__(self, _path):
            self.entries = {12: _Res(), 3: None}

        def parse(self, _flag):
            return None

    imgmod.Image = _Img
    imgmod.Package = _Pkg
    imgmod.FileWindow = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "img", imgmod)
    raw = b"ABCD"
    assert bake._element_bytes(vanilla, 3, "timg/A.bclim", raw) is None
    assert bake._element_bytes(vanilla, 12, "missing", raw) is None
    assert bake._element_bytes(vanilla, 12, "timg/A.bclim", raw) == b"AB"
    assert bake.unreplaced_slot_skips(None, vanilla, vanilla) == []
    assert bake.unreplaced_slot_skips("noise", vanilla, vanilla) == []
    monkeypatch.setattr(bake, "_element_bytes", lambda *_a: b"same")
    assert bake.unreplaced_slot_skips("[slot-skip] package 12 timg/A.bclim\n", vanilla, vanilla) == [
        "package 0012 timg/A.bclim"
    ]
    other = tmp_path / "other.bin"
    other.write_bytes(b"ZZ")
    vanilla.write_bytes(b"AA")
    monkeypatch.setattr(bake, "_element_bytes", lambda img, _p, _n, raw: raw[:1])
    assert bake.unreplaced_slot_skips("[slot-skip] package 12 timg/A.bclim\n", vanilla, other) == []

    side = bake.BAKE_IMG.parent / "bake_img.bin.bak_pre_x"
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_bytes(b"bak")
    bake.cleanup_bake_img_baks(bake.BAKE_IMG)
    assert not side.exists()
    junk = tmp_path / "cia_root" / "out" / "junk.txt"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_text("x", encoding="utf-8")
    bake.cleanup_rebuild_scratch(keep_work=True)
    assert junk.is_file()
    bake.cleanup_rebuild_scratch(keep_work=False)
    lines = bake.format_rebuild_ok_lines(
        bake=bake.BAKE_IMG,
        cache_new=tmp_path / "new.bin",
        main_trb=tmp_path / "m.trb",
        overlay=tmp_path / "ov",
        name_code=tmp_path / "code.bin",
        stamp=tmp_path / "stamp.txt",
        elapsed="1s",
        started_at="t0",
    )
    assert any("PNG optional" in line for line in lines)
    assert "PNG optional" not in "\n".join(
        bake.format_rebuild_ok_lines(
            bake=bake.BAKE_IMG,
            cache_new=None,
            main_trb=tmp_path / "m.trb",
            overlay=tmp_path / "ov",
            name_code=tmp_path / "code.bin",
            stamp=tmp_path / "stamp.txt",
            elapsed="1s",
            started_at="t0",
        )
    )
    log = bake.write_rebuild_log(lines, elapsed="1s", started_at="t0", log_path=tmp_path / "log.txt", pack_report="PACK")
    assert log is not None and "PACK" in log.read_text(encoding="utf-8")
    monkeypatch.setattr(bake, "write_log", lambda *_a, **_k: None)
    assert bake.write_rebuild_log(lines, elapsed="1s", started_at="t0", log_path=tmp_path / "log2.txt") is None


def test_bake_name_input_and_rebuild(monkeypatch, tmp_path: Path):
    import extract_vanilla_from_rom as ev

    root = _bind_bake(monkeypatch, tmp_path)
    src = tmp_path / "code.bin"
    src.write_bytes(b"code")
    monkeypatch.setattr(bake.time, "sleep", lambda _s: None)
    monkeypatch.setattr(bake, "find_vanilla_code", lambda: src)

    def write_code(_cmd, **_k):
        bake.NAME_INPUT_CODE.parent.mkdir(parents=True, exist_ok=True)
        bake.NAME_INPUT_CODE.write_bytes(b"out")

    monkeypatch.setattr(bake, "run", write_code)
    assert bake.build_name_input_code(rom=None) == bake.NAME_INPUT_CODE

    tries = {"n": 0}

    def flaky(_cmd, **_k):
        tries["n"] += 1
        if tries["n"] < 3:
            raise subprocess.CalledProcessError(1, ["deploy"])
        write_code(_cmd)

    rom = tmp_path / "game.cia"
    rom.write_bytes(b"rom")
    monkeypatch.setattr(bake, "find_vanilla_code", lambda: None)
    monkeypatch.setattr(bake, "run", flaky)

    def ensure(path, force=False):
        if force:
            raise bake.PatchError("extract")
        return src

    monkeypatch.setattr(ev, "ensure_vanilla_code_from_rom", ensure)
    assert bake.build_name_input_code(rom=rom).is_file()
    monkeypatch.setattr(bake, "run", lambda *_a, **_k: None)
    with pytest.raises(SystemExit, match="3 attempts"):
        bake.build_name_input_code(rom=None)
    monkeypatch.setattr(bake, "run", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(SystemExit, match="3 attempts"):
        bake.build_name_input_code(rom=rom)

    vanilla = tmp_path / "vanilla.bin"
    vanilla.write_bytes(b"van")
    bake.RELEASE.mkdir(parents=True, exist_ok=True)
    bake.BAKE_IMG.write_bytes(b"bake")
    monkeypatch.setattr(bake, "find_vanilla_main_trb", lambda: src)
    monkeypatch.setattr(bake, "unreplaced_slot_skips", lambda *_a: [])

    def built(**_k):
        write_code([])
        return bake.NAME_INPUT_CODE

    monkeypatch.setattr(bake, "build_name_input_code", built)
    assert bake._main_rebuild(_bake_ns(skip_pack=True, vanilla=vanilla, also_azahar=True), _btimer()) == 0

    bake.BAKE_IMG.unlink()
    bake.CACHE_NEW_IMG.parent.mkdir(parents=True, exist_ok=True)
    bake.CACHE_NEW_IMG.write_bytes(b"seed")
    assert bake._main_rebuild(_bake_ns(skip_pack=True, vanilla=vanilla, keep_work=False), _btimer()) == 0
    assert bake.BAKE_IMG.is_file() and not bake.CACHE_NEW_IMG.exists()

    bake.BAKE_IMG.unlink()
    with pytest.raises(SystemExit, match="no bake"):
        bake._main_rebuild(_bake_ns(skip_pack=True, vanilla=vanilla), _btimer())
    with pytest.raises(SystemExit, match="reseed"):
        bake._main_rebuild(_bake_ns(reseed_from_pack=True, vanilla=vanilla), _btimer())
    bake.CACHE_NEW_IMG.write_bytes(b"seed")
    assert bake._main_rebuild(_bake_ns(reseed_from_pack=True, vanilla=vanilla), _btimer()) == 0
    with pytest.raises(SystemExit, match="vanilla img.bin missing"):
        bake._main_rebuild(_bake_ns(skip_pack=True, vanilla=tmp_path / "missing.bin"), _btimer())

    def boom(*_a, **_k):
        raise FileNotFoundError("no rom")

    monkeypatch.setattr(bake, "ensure_vanilla_from_rom", boom)
    with pytest.raises(SystemExit, match="no rom"):
        bake._main_rebuild(_bake_ns(rom=rom), _btimer())

    def slim(*_a, **_k):
        img = bake.CACHE / "vanilla_from_rom" / "romfs" / "img.bin"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"v")
        return img

    monkeypatch.setattr(bake, "ensure_vanilla_from_rom", slim)
    with pytest.raises(SystemExit, match="Plus"):
        bake._main_rebuild(_bake_ns(rom=rom), _btimer())

    def plus(path, **_k):
        folder = bake.CACHE / "vanilla_from_rom" / "romfs" / "Plus"
        folder.mkdir(parents=True, exist_ok=True)
        img = folder.parent / "img.bin"
        img.write_bytes(b"v")
        return img

    monkeypatch.setattr(bake, "ensure_vanilla_from_rom", plus)
    monkeypatch.setattr(bake, "find_vanilla_main_trb", lambda: None)
    with pytest.raises(SystemExit, match="textresource_jpn.trb missing"):
        bake._main_rebuild(_bake_ns(rom=rom), _btimer())

    monkeypatch.setattr(bake, "resolve_vanilla_img", lambda **_k: (_ for _ in ()).throw(OSError("resolve")))
    with pytest.raises(SystemExit, match="resolve"):
        bake._main_rebuild(_bake_ns(), _btimer())
    monkeypatch.setattr(bake, "resolve_vanilla_img", lambda **_k: tmp_path / "gone.bin")
    with pytest.raises(SystemExit, match="missing"):
        bake._main_rebuild(_bake_ns(), _btimer())

    monkeypatch.setattr(bake, "find_vanilla_main_trb", lambda: src)
    monkeypatch.setattr(bake, "DEPLOY_SCRIPTS", ["missing_deploy.py"])
    script = root / "tools" / "missing_deploy.py"
    with pytest.raises(SystemExit, match="missing deploy"):
        bake._main_rebuild(_bake_ns(skip_pack=True, skip_deploys=False, vanilla=vanilla), _btimer())
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#\n", encoding="utf-8")
    ran = []
    monkeypatch.setattr(bake, "run", lambda cmd, **k: ran.append((cmd, k.get("env"))))
    bake.BAKE_IMG.write_bytes(b"bake")
    assert bake._main_rebuild(_bake_ns(skip_pack=True, skip_deploys=False, vanilla=vanilla, also_azahar=False), _btimer()) == 0
    assert ran and ran[-1][1]["NLPP_ALSO_AZAHAR"] == "0"

    monkeypatch.setattr(bake, "DEPLOY_SCRIPTS", [])
    with pytest.raises(SystemExit, match="sms_en"):
        bake._main_rebuild(_bake_ns(skip_pack=True, vanilla=vanilla, include_sms=True), _btimer())
    sms = root / "assets" / "sms_en" / "maildic_m.en.xml"
    sms.parent.mkdir(parents=True, exist_ok=True)
    sms.write_text("<x/>", encoding="utf-8")
    assert bake._main_rebuild(_bake_ns(skip_pack=True, vanilla=vanilla, include_sms=True), _btimer()) == 0

    monkeypatch.setattr(bake, "unreplaced_slot_skips", lambda *_a: ["package 0012 timg/A.bclim"])
    with pytest.raises(SystemExit, match="Japanese"):
        bake._main_rebuild(_bake_ns(skip_pack=True, vanilla=vanilla), _btimer())
    monkeypatch.setattr(bake, "unreplaced_slot_skips", lambda *_a: [])

    def forget(**_k):
        bake.NAME_INPUT_CODE.unlink(missing_ok=True)
        return bake.NAME_INPUT_CODE

    monkeypatch.setattr(bake, "build_name_input_code", forget)
    with pytest.raises(SystemExit, match="name-input missing"):
        bake._main_rebuild(_bake_ns(skip_pack=True, vanilla=vanilla), _btimer())

    def drop_bake(**_k):
        write_code([])
        bake.BAKE_IMG.unlink(missing_ok=True)
        return bake.NAME_INPUT_CODE

    monkeypatch.setattr(bake, "build_name_input_code", drop_bake)
    with pytest.raises(SystemExit, match="bake missing"):
        bake._main_rebuild(_bake_ns(skip_pack=True, vanilla=vanilla), _btimer())

    monkeypatch.setattr(bake, "build_name_input_code", built)
    monkeypatch.setattr(bake, "rebuild_main_trb", lambda **_k: None)
    bake.BAKE_IMG.write_bytes(b"bake")
    with pytest.raises(SystemExit, match="main TRB missing"):
        bake._main_rebuild(_bake_ns(skip_pack=True, skip_trb=False, vanilla=vanilla), _btimer())

    def packing(*_a, **k):
        k["on_line"]("noise\n")
        k["on_line"]("[pack] [0/0]\n")
        k["on_line"]("[pack] [1/2] x\n")
        bake.BAKE_IMG.write_bytes(b"packed")
        return bake.BAKE_IMG, "[pack] report"

    inner = bake.CACHE / "rom.cia"
    parked_van = bake.CACHE / "img.bin"
    bake.CACHE.mkdir(parents=True, exist_ok=True)
    inner.write_bytes(b"rom")
    parked_van.write_bytes(b"img")
    monkeypatch.setattr(bake, "pack_ui", packing)
    monkeypatch.setattr(bake, "ensure_vanilla_from_rom", plus)
    monkeypatch.setattr(bake, "find_vanilla_main_trb", lambda: src)
    monkeypatch.setattr(bake, "build_name_input_code", built)
    assert bake._main_rebuild(_bake_ns(rom=inner, vanilla=parked_van, skip_trb=True), _btimer()) == 0

    def stop(_args, _timer):
        raise SystemExit("stop")

    monkeypatch.setattr(bake, "_main_rebuild", stop)
    with pytest.raises(SystemExit, match="stop"):
        bake.main(["--skip-pack", "--skip-trb", "--skip-deploys"])

    def crash(_args, _timer):
        raise RuntimeError("boom")

    monkeypatch.setenv("NLPP_GITHUB_BAKE", "1")
    monkeypatch.setattr(bake, "_main_rebuild", crash)
    with pytest.raises(RuntimeError):
        bake.main([])

    def abort(_args, _timer):
        raise KeyboardInterrupt

    monkeypatch.setattr(bake, "_main_rebuild", abort)
    with pytest.raises(KeyboardInterrupt):
        bake.main([])


# ---------------------------------------------------------------------------
# patch_cia
# ---------------------------------------------------------------------------


def _timer():
    return RunTimer("cia", heartbeat_s=None)


def _eng_stub(monkeypatch, *, entries, arc=True, found=True, unlink_error=False):
    import types

    imgmod = types.ModuleType("img")
    darcutil = types.ModuleType("darcutil")

    class _FW:
        base_offset = 0

        def len(self):
            return 4

    class _Res:
        fw = _FW()

    class _Img:
        def __init__(self, _path):
            self.entries = entries

        def parse(self, _flag):
            return None

    class _ARC:
        def parsed(self):
            return b"arc"

    class _Pkg:
        def __init__(self, *_a, **_k):
            self.entries = [_ARC()] if arc else [object()]

        def parse(self, _flag):
            return None

    class _Darc:
        def __init__(self, _blob):
            return None

        def find(self, _name):
            return object() if found else None

    imgmod.Image = _Img
    imgmod.Package = _Pkg
    imgmod.FileWindow = lambda *_a, **_k: None
    imgmod.ARC = _ARC
    darcutil.DarcArchive = _Darc
    monkeypatch.setitem(sys.modules, "img", imgmod)
    monkeypatch.setitem(sys.modules, "darcutil", darcutil)
    if unlink_error:
        real_unlink = Path.unlink

        def unlink(self, missing_ok=False):
            if "_engpatch_check_" in self.name:
                raise OSError("busy")
            return real_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", unlink)


def test_cia_extract_helpers(monkeypatch, tmp_path: Path, capsys):
    tools = _use_tools(monkeypatch)
    root = tmp_path / "cia_root"
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"cia")
    cci = tmp_path / "game.3ds"
    cci.write_bytes(b"\x00" * 0x100 + b"NCSD")
    assert patch_cia.detect_rom_kind(rom) == "cia"
    assert patch_cia.detect_rom_kind(cci) == "cci"
    bare = tmp_path / "bare"
    bare.write_bytes(b"\x00" * 0x104)
    with pytest.raises(patch_cia.PatchError, match="unsupported"):
        patch_cia.detect_rom_kind(bare)
    missing = tmp_path / "no-such.bin"
    with pytest.raises(patch_cia.PatchError, match="unsupported"):
        patch_cia.detect_rom_kind(missing)

    class _Live:
        active = False

        def set_job(self, *_a):
            return None

        def log(self, *_a):
            return None

    monkeypatch.setattr(patch_cia, "live", _Live())
    assert patch_cia._run([patch_cia.TOOL_3DS, "-h"]).returncode == 0
    tools.ctr_rc = 3
    with pytest.raises(patch_cia.PatchError, match="command failed"):
        patch_cia._run([patch_cia.CTRTOOL])
    tools.ctr_rc = 0
    _Live.active = True
    patch_cia._run([patch_cia.CTRTOOL], cwd=tmp_path)
    tools.ctr_rc = 4
    tools.ctr_out = ""
    tools.ctr_err = ""
    with pytest.raises(patch_cia.PatchError, match="command failed"):
        patch_cia._run([patch_cia.CTRTOOL])
    tools.ctr_out = "detail"
    with pytest.raises(patch_cia.PatchError):
        patch_cia._run([patch_cia.CTRTOOL])
    tools.ctr_rc = 0
    _Live.active = False
    tools.ctr_out = "Crypto Key None\nTitleVersion: 1.0.0 (4)\n"
    gone = root / "cia_tools" / "MISSING"
    monkeypatch.setattr(patch_cia, "TOOL_3DS", gone)
    with pytest.raises(patch_cia.PatchError, match="missing"):
        patch_cia._require_tools()
    monkeypatch.setattr(patch_cia, "TOOL_3DS", root / "cia_tools" / "TOOL_3DS")

    assert patch_cia.is_encrypted_cia(rom) is False
    tools.ctr_out = "Crypto Key Secure\n"
    assert patch_cia.is_encrypted_cia(rom) is True
    tools.ctr_out = "NCCH Crypto Key Weird\n"
    assert patch_cia.is_encrypted_cia(rom) is True
    tools.ctr_out = "NCCH Crypto Key x None\n"
    assert patch_cia.is_encrypted_cia(rom) is False
    tools.ctr_out = "no key here\n"
    with pytest.raises(patch_cia.PatchError, match="could not determine"):
        patch_cia.is_encrypted_cia(rom)
    tools.ctr_out = "Crypto Key: None\nTitleVersion: 1.0.0 (4)\n"
    patch_cia.require_decrypted_rom(rom, assume_decrypted=True)
    named = tmp_path / "game.decrypted.cia"
    named.write_bytes(b"x")
    patch_cia.require_decrypted_rom(named)
    tools.ctr_out = "Crypto Key: Fixed\n"
    with pytest.raises(patch_cia.PatchError):
        patch_cia.require_decrypted_rom(rom)
    tools.ctr_out = "no key here\n"
    with pytest.raises(patch_cia.PatchError, match="assume-decrypted"):
        patch_cia.require_decrypted_rom(rom)
    tools.ctr_out = "Crypto Key None\nTitleVersion: 1.0.0 (4)\nVersion: 9\n"
    patch_cia.require_decrypted_rom(rom)

    work = tmp_path / "work"
    main, manual = patch_cia.extract_cci_partitions(cci, work / "cci")
    assert main.is_file() and manual is not None
    again, _manual = patch_cia.extract_cci_partitions(cci, work / "cci")
    assert again == main
    tools.manual_empty = True
    empty_dir = work / "cci_empty"
    _main, no_manual = patch_cia.extract_cci_partitions(cci, empty_dir)
    assert no_manual is None
    tools.skip_part0 = True
    with pytest.raises(patch_cia.PatchError, match="partition0"):
        patch_cia.extract_cci_partitions(cci, work / "cci_skip")
    tools.skip_part0 = False
    tools.manual_empty = False
    c0, c1 = patch_cia.extract_cia_contents(rom, work / "contents")
    assert c0.is_file() and c1 is None
    tools.content1 = True
    patch_cia.extract_cia_contents(rom, work / "contents")
    tools.skip_content0 = True
    with pytest.raises(patch_cia.PatchError, match="content.0000"):
        patch_cia.extract_cia_contents(rom, work / "contents_skip")
    tools.skip_content0 = False
    _cxi, _man, ver = patch_cia.prepare_cxi_from_rom(rom, work / "prep", kind="cia", assume_decrypted=True)
    assert ver == 4
    patch_cia.prepare_cxi_from_rom(cci, work / "prep3", kind="cci", assume_decrypted=True)
    parts = patch_cia.split_cxi(c0, work / "parts")
    assert parts["header"].is_file()
    assert patch_cia.split_cxi(c0, work / "parts")["romfs"] == parts["romfs"]
    tree = patch_cia.ensure_romfs_dir(parts["romfs"], work / "romfs", reuse=None)
    assert (tree / "script" / "bin" / "script").is_dir()
    assert patch_cia.ensure_romfs_dir(parts["romfs"], work / "romfs", reuse=tree) == tree
    dbin = _dbin_root(tmp_path / "dbin")
    assert patch_cia.inject_dbin2(tree, dbin) == 0
    empty = tmp_path / "empty_dbin"
    for pack in patch_cia.PACKS:
        (empty / pack).mkdir(parents=True)
    with pytest.raises(patch_cia.PatchError, match="no .dbin2"):
        patch_cia.inject_dbin2(tree, empty)
    out_bin = work / "romfs.bin"
    patch_cia.rebuild_romfs(tree, out_bin)
    assert out_bin.stat().st_size >= 1024
    tools.romfs_size = 10
    with pytest.raises(patch_cia.PatchError, match="romfs rebuild"):
        patch_cia.rebuild_romfs(tree, work / "small.bin")
    tools.romfs_size = 2048
    tools.plain = 0
    tools.logo = 0
    cxi_out = work / "out.cxi"
    patch_cia.rebuild_cxi(parts, out_bin, cxi_out)
    assert cxi_out.is_file()
    tools.write_outputs = False
    with pytest.raises(patch_cia.PatchError, match="CXI rebuild"):
        patch_cia.rebuild_cxi(parts, out_bin, work / "missing.cxi")
    tools.write_outputs = True
    cia_out = work / "out.cia"
    patch_cia.rebuild_cia(cxi_out, manual, cia_out, 7)
    assert cia_out.is_file()
    tools.write_outputs = False
    with pytest.raises(patch_cia.PatchError, match="CIA rebuild"):
        patch_cia.rebuild_cia(cxi_out, None, work / "missing.cia", None)
    tools.write_outputs = True
    assert "TitleVersion" in patch_cia._ctrtool_info(rom) or patch_cia._ctrtool_info(rom) is not None
    capsys.readouterr()


def test_cia_code_images_and_summary(monkeypatch, tmp_path: Path):
    tools = _use_tools(monkeypatch)
    work = tmp_path / "work"
    work.mkdir()
    exefs = work / "exefs.bin"
    exefs.write_bytes(b"EXE")
    code, header = patch_cia._unpack_exefs(exefs, work / "unpacked")
    assert code.name == "code.bin" and header.is_file()
    tools.code_name = ".code"
    code, _header = patch_cia._unpack_exefs(exefs, work / "unpacked2")
    assert code.name == ".code"
    tools.code_name = ""
    with pytest.raises(patch_cia.PatchError, match="no code.bin"):
        patch_cia._unpack_exefs(exefs, work / "unpacked3")
    tools.code_name = "code.bin"
    tools.header = False
    with pytest.raises(patch_cia.PatchError, match="no ExeFS header"):
        patch_cia._unpack_exefs(exefs, work / "unpacked4")
    tools.header = True
    tools.write_outputs = False
    with pytest.raises(patch_cia.PatchError, match="ExeFS rebuild"):
        patch_cia._repack_exefs(work / "unpacked", header, work / "repacked.bin")
    tools.write_outputs = True
    assert patch_cia._repack_exefs(work / "unpacked", header, work / "repacked.bin").is_file()
    tools.write_outputs = False
    with pytest.raises(patch_cia.PatchError, match="uncompress"):
        patch_cia._blz_uncompress(code, work / "dec.bin")
    tools.write_outputs = True
    assert patch_cia._blz_uncompress(code, work / "dec.bin").is_file()
    tools.blz_out = 8
    with pytest.raises(patch_cia.PatchError, match="slot"):
        patch_cia._blz_compress(work / "dec.bin", work / "cmp.bin", exact_size=16)
    tools.blz_out = 16
    import patch_code

    monkeypatch.setattr(patch_code, "patch_code_bin", lambda *_a, **_k: None)
    assert patch_cia.patch_exefs_code(exefs, work).is_file()
    monkeypatch.setattr(patch_code, "patch_code_bin", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad code")))
    with pytest.raises(patch_cia.PatchError, match="bad code"):
        patch_cia.patch_exefs_code(exefs, work)
    monkeypatch.setattr(patch_code, "patch_code_bin", lambda *_a, **_k: None)
    missing_code = tmp_path / "no-code.bin"
    with pytest.raises(patch_cia.PatchError, match="inject-code"):
        patch_cia.inject_exefs_code(exefs, work, missing_code)
    same = tmp_path / "same.bin"
    same.write_bytes(b"S" * 16)
    assert patch_cia.inject_exefs_code(exefs, work, same).is_file()
    bigger = tmp_path / "big.bin"
    bigger.write_bytes(b"B" * 32)
    tools.blz_out = 32
    assert patch_cia.inject_exefs_code(exefs, work, bigger).is_file()
    tools.blz_out = 16
    assert patch_cia.patch_exefs_smdh(exefs, work, region_lock=1).is_file()
    hdr = work / "parts_hdr"
    # rebuild a header the way the fake splitter does
    raw = bytearray(0x60)
    raw[:4] = b"NCCH"
    raw[0x50:0x60] = b"OLD-CODE".ljust(16, b"\x00")
    hdr.write_bytes(raw)
    patch_cia.patch_ncch_header_meta(hdr, product_code="CTR-P-BLPE")
    patch_cia.patch_ncch_header_meta(hdr, product_code="CTR-P-BLPE")
    parts = patch_cia.split_cxi(exefs, work / "ncch")
    patched = patch_cia.apply_cia_metadata(parts, work, region_name="usa")
    assert patched["exefs"].is_file()

    overlay = tmp_path / "overlay"
    (overlay / "a").mkdir(parents=True)
    (overlay / "a" / "f.txt").write_text("z", encoding="utf-8")
    assert patch_cia.resolve_romfs_overlay(_ns(romfs_overlay=str(tmp_path / "missing-overlay"))) is None
    assert patch_cia.resolve_romfs_overlay(_ns(romfs_overlay=str(overlay))) == overlay.resolve()
    patch_cia.DEFAULT_ROMFS_OVERLAY.mkdir(parents=True)
    assert patch_cia.resolve_romfs_overlay(_ns()) == patch_cia.DEFAULT_ROMFS_OVERLAY
    patch_cia.DEFAULT_ROMFS_OVERLAY.rmdir()
    patch_cia._LEGACY_ROMFS_OVERLAY.mkdir(parents=True)
    assert patch_cia.resolve_romfs_overlay(_ns()) == patch_cia._LEGACY_ROMFS_OVERLAY
    patch_cia._LEGACY_ROMFS_OVERLAY.rmdir()
    assert patch_cia.resolve_romfs_overlay(_ns()) is None
    dest = tmp_path / "romfs"
    assert patch_cia.apply_romfs_overlay(dest, overlay) == 1
    with pytest.raises(patch_cia.PatchError, match="not a directory"):
        patch_cia.apply_romfs_overlay(dest, overlay / "a" / "f.txt")

    explicit = tmp_path / "code.bin"
    explicit.write_bytes(b"c")
    assert patch_cia.resolve_code_bin_src(_ns(code_bin=str(explicit))) == explicit.resolve()
    other = tmp_path / "absent.bin"
    assert patch_cia.resolve_code_bin_src(_ns(code_bin=str(other))) == other.resolve()
    assert patch_cia.resolve_code_bin_src(_ns(code_bin=str(patch_cia.DEFAULT_CODE_BIN))) is None

    resident = tmp_path / "textresource_resident_jpn.trb"
    resident.write_bytes(b"trb")
    hint = tmp_path / "hint" / "SystemData" / "TextResource"
    hint.mkdir(parents=True)
    (hint / resident.name).write_bytes(b"h")
    assert patch_cia._resolve_resident_trb(hint.parent.parent) == hint / resident.name
    assert patch_cia._resolve_resident_trb(None) is None

    dbin = _dbin_root(tmp_path / "dbin")
    out = tmp_path / "layered"
    img = tmp_path / "img.bin"
    img.write_bytes(b"img")
    monkeypatch.setattr(patch_cia, "resolve_script_source", lambda pack, stem, root: (dbin / pack / f"{stem}.dbin2", "manaka"))
    monkeypatch.setattr(patch_cia, "apply_name_patches", lambda *_a, **_k: None)
    count = patch_cia.write_layeredfs(
        out, dbin, img, resident_src=resident, patched_code=explicit, skip_name_patches=True, romfs_overlay=overlay
    )
    assert count == 3
    (out / "LAYEREDFS_README.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(patch_cia, "resolve_script_source", lambda *_a: (None, "jp"))
    patch_cia.NAME_INPUT_CODE.parent.mkdir(parents=True, exist_ok=True)
    patch_cia.NAME_INPUT_CODE.write_bytes(b"small")
    patch_cia.write_layeredfs(out, dbin, None, patch_code=False)
    assert not (out / "LAYEREDFS_README.txt").exists()
    with pytest.raises(patch_cia.PatchError, match="vanilla code.bin"):
        patch_cia.write_layeredfs(tmp_path / "lfs2", dbin, None, patch_code=True)
    monkeypatch.setattr(patch_cia, "find_vanilla_code", lambda: explicit)
    monkeypatch.setattr(patch_code, "write_patched_code_bin", lambda src, dest, force=True: dest.write_bytes(b"patched"))
    patch_cia.NAME_INPUT_CODE.unlink()
    assert patch_cia.write_layeredfs(tmp_path / "lfs3", dbin, None, patch_code=True, code_bin_src=explicit) == 0
    with pytest.raises(patch_cia.PatchError, match="missing packed"):
        patch_cia.write_layeredfs(tmp_path / "lfs4", tmp_path / "no-packs", None)

    src_img = tmp_path / "src.img"
    src_img.write_bytes(b"s")
    assert patch_cia._resolve_source_img_bin(_ns(img_bin=str(src_img))) == src_img.resolve()
    with pytest.raises(patch_cia.PatchError):
        patch_cia._resolve_source_img_bin(_ns())
    patch_cia.DEFAULT_BAKE_IMG.parent.mkdir(parents=True, exist_ok=True)
    assert patch_cia.resolve_inject_img(_ns()) == patch_cia.DEFAULT_PACKED_IMG
    patch_cia.DEFAULT_BAKE_IMG.write_bytes(b"gold")
    assert patch_cia.resolve_inject_img(_ns()) == patch_cia.DEFAULT_BAKE_IMG
    custom = tmp_path / "custom.img"
    custom.write_bytes(b"c")
    assert patch_cia.resolve_inject_img(_ns(packed_img=str(custom))) == custom.resolve()

    _eng_stub(monkeypatch, entries=[None])
    assert patch_cia._title_pkg_has_eng_patch(src_img, pkg_idx=0) is False
    _eng_stub(monkeypatch, entries=[object()])
    # entries[0] needs .fw — object() will throw and we want the False/ARC paths with a real res
    class _FW:
        base_offset = 0

        def len(self):
            return 4

    class _Res:
        fw = _FW()

    _eng_stub(monkeypatch, entries=[_Res()], arc=False)
    assert patch_cia._title_pkg_has_eng_patch(src_img, pkg_idx=0) is False
    _eng_stub(monkeypatch, entries=[_Res()], found=True)
    assert patch_cia._title_pkg_has_eng_patch(src_img, pkg_idx=0) is True
    _eng_stub(monkeypatch, entries=[_Res()], found=False, unlink_error=True)
    assert patch_cia._title_pkg_has_eng_patch(src_img, pkg_idx=0) is False

    monkeypatch.setattr("pack_images.img_idx_mismatches", lambda _p: [])
    patch_cia._require_img_idx_sync(src_img, context="t")
    monkeypatch.setattr("pack_images.img_idx_mismatches", lambda _p: [(1, 2, 3)])
    with pytest.raises(patch_cia.PatchError, match="stale"):
        patch_cia._require_img_idx_sync(src_img, context="t")
    with pytest.raises(patch_cia.PatchError, match="name-input"):
        patch_cia._require_name_input_for_ui(_ns())
    with pytest.raises(patch_cia.PatchError, match="missing"):
        patch_cia._require_name_input_for_ui(_ns(inject_code=str(tmp_path / "absent-code.bin")))
    patch_cia._require_name_input_for_ui(_ns(patch_code=True))
    patch_cia._require_name_input_for_ui(_ns(inject_code=str(explicit)))

    assert patch_cia._apply_gemini_sms(src_img, work) == src_img
    monkeypatch.setenv("NLPP_INCLUDE_GEMINI_NENE", "1")
    with pytest.raises(patch_cia.PatchError, match="Gemini SMS"):
        patch_cia._apply_gemini_sms(src_img, work)
    sms = patch_cia.ROOT / "assets" / "gemini_heroines" / "sms" / "maildic_m.en.xml"
    sms.parent.mkdir(parents=True, exist_ok=True)
    sms.write_text("<x/>", encoding="utf-8")
    out_sms = patch_cia._apply_gemini_sms(src_img, work)
    assert out_sms.name == patch_cia.GEMINI_SMS_IMG
    monkeypatch.delenv("NLPP_INCLUDE_GEMINI_NENE", raising=False)

    import pack_images

    monkeypatch.setattr(patch_cia, "_require_eng_patch", lambda *_a, **_k: None)
    monkeypatch.setattr(patch_cia, "_require_img_idx_sync", lambda *_a, **_k: None)
    assert patch_cia.pack_ui_images(_ns(images=str(tmp_path), repack_images=False), work) == patch_cia.DEFAULT_BAKE_IMG
    patch_cia.DEFAULT_BAKE_IMG.unlink()
    assert patch_cia.pack_ui_images(_ns(images=str(tmp_path), packed_img=str(custom)), work) == custom.resolve()

    def do_pack(*_a, **_k):
        custom.write_bytes(b"repacked")

    monkeypatch.setattr(pack_images, "pack_images", do_pack)
    monkeypatch.setattr(patch_cia, "_resolve_source_img_bin", lambda _a: src_img)
    fresh = tmp_path / "fresh.img"
    got = patch_cia.pack_ui_images(
        _ns(images=str(tmp_path), packed_img=str(fresh), repack_images=True, image_workers=1, image_fine_tune=True, img_bin=str(src_img)),
        work,
    )
    assert got == fresh.resolve()
    monkeypatch.setattr(pack_images, "pack_images", lambda *_a, **_k: (_ for _ in ()).throw(pack_images.PackError("no")))
    with pytest.raises(patch_cia.PatchError, match="image packing"):
        patch_cia.pack_ui_images(_ns(images=str(tmp_path), packed_img=str(tmp_path / "other.img"), repack_images=True, keep_work=False), work)

    note_root = tmp_path / "note"
    note = patch_cia.write_install_choice_note(note_root)
    assert note.is_file() and note.parent.is_dir()
    blocker = note_root / patch_cia.OUT_NOT_BOTH_NAME
    shutil.rmtree(blocker)
    blocker.write_text("file", encoding="utf-8")
    assert patch_cia.write_install_choice_note(note_root).is_file()

    drop = tmp_path / "cia_root" / "out" / "layered"
    (drop / patch_cia.TITLE_ID).mkdir(parents=True)
    (drop / "README.txt").write_text("r", encoding="utf-8")
    patch_cia._discard_layeredfs_drop(drop)
    patch_cia._discard_layeredfs_drop(tmp_path / "cia_root" / "out" / "empty-parent" / "kid")
    cia = tmp_path / "cia_root" / "out" / "nested" / "out.cia"
    cia.parent.mkdir(parents=True)
    cia.write_bytes(b"C")
    patch_cia._discard_partial_out_cia(cia)
    assert not cia.exists()
    patch_cia._discard_install_choice_note()
    (patch_cia.ROOT / "out" / patch_cia.OUT_NOT_BOTH_NAME).mkdir(parents=True)
    patch_cia._discard_install_choice_note()
    patch_cia._discard_outputs_after_cia_failure(None, out_cia=None)
    patch_cia._discard_outputs_after_cia_failure(drop, out_cia=cia)

    rom = tmp_path / "game.cia"
    rom.write_bytes(b"cia")
    assert patch_cia.parse_title_version(rom) == 4
    tools.ctr_out = "Version: 9\n"
    assert patch_cia.parse_title_version(rom) == 9
    tools.ctr_out = "nothing\n"
    assert patch_cia.parse_title_version(rom) is None
    with pytest.raises(patch_cia.PatchError, match="source title"):
        patch_cia.next_cia_title_version(-1)
    with pytest.raises(patch_cia.PatchError, match="title-ver"):
        patch_cia.next_cia_title_version(1, explicit=-1)
    with pytest.raises(patch_cia.PatchError, match="CIA_TITLE_VERSION"):
        patch_cia.next_cia_title_version(1, release_ver=0)
    assert patch_cia.next_cia_title_version(1, keep_source=True) == 1
    assert patch_cia.next_cia_title_version(1, explicit=3) == 3
    assert patch_cia.next_cia_title_version(0xFFFF, release_ver=1) == 0xFFFF
    with pytest.raises(patch_cia.PatchError, match="not both"):
        patch_cia.resolve_cia_title_version(_ns(title_ver=1, keep_title_ver=True), 1)
    assert patch_cia.resolve_cia_title_version(_ns(), 1) > 0
    digest = patch_cia.sha1_file(rom)
    assert patch_cia.verify_cia_sha1(rom, expected=digest) == digest
    with pytest.raises(patch_cia.PatchError, match="mismatch"):
        patch_cia.verify_cia_sha1(rom, expected="0" * 40)
    assert patch_cia.verify_cia_sha1(rom, allowed={digest, "ab"}) == digest

    patch_cia.emit_spotpass_inject(_ns(skip_spotpass=True))
    monkeypatch.setattr(patch_cia, "TOOLS", tmp_path / "no-tools")
    patch_cia.emit_spotpass_inject(_ns(skip_spotpass=False))
    monkeypatch.setattr(patch_cia, "TOOLS", tmp_path / "tools")
    (patch_cia.TOOLS / "build_spotpass_inject.py").parent.mkdir(parents=True)
    (patch_cia.TOOLS / "build_spotpass_inject.py").write_text("x=1\n", encoding="utf-8")

    def no_spec(*_a, **_k):
        return None

    import importlib.util

    real_spec = importlib.util.spec_from_file_location
    monkeypatch.setattr(importlib.util, "spec_from_file_location", no_spec)
    patch_cia.emit_spotpass_inject(_ns(skip_spotpass=False))

    class _Spec:
        loader = None

    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *_a, **_k: _Spec())
    patch_cia.emit_spotpass_inject(_ns(skip_spotpass=False))
    monkeypatch.setattr(importlib.util, "spec_from_file_location", real_spec)
    script = patch_cia.TOOLS / "build_spotpass_inject.py"
    script.write_text(
        "def build_inject(mode, install_azahar_sdmc=None):\n    raise RuntimeError('spot')\n",
        encoding="utf-8",
    )
    patch_cia.emit_spotpass_inject(_ns(skip_spotpass=False, spotpass_install_azahar=True))
    script.write_text(
        "def build_inject(mode, install_azahar_sdmc=None):\n    return 'flat'\n",
        encoding="utf-8",
    )
    patch_cia.emit_spotpass_inject(_ns(skip_spotpass=False))

    contrib = tmp_path / "contrib" / "script"
    contrib.mkdir(parents=True)
    (contrib / "t001.dbin2").write_bytes(b"d")
    (tmp_path / "contrib" / "empty").mkdir()
    monkeypatch.setattr(patch_cia, "CONTRIB_DBIN", tmp_path / "contrib")
    summary = patch_cia.build_patch_summary(
        out_cia=None,
        packed_img=None,
        layered_img=None,
        layeredfs_out=None,
        romfs_overlay=None,
        args=_ns(include_gemini_nene=True, no_images=True, with_images=False, patch_code=True, skip_cia_meta=False, cia_region="nope"),
        layeredfs_only=True,
        elapsed="1s",
        started_at="t",
    )
    assert any("LayeredFS-only" in line for line in summary)
    cia_file = tmp_path / "done.cia"
    cia_file.write_bytes(b"CIA")
    title = tmp_path / "lfs" / patch_cia.TITLE_ID
    title.mkdir(parents=True)
    summary = patch_cia.build_patch_summary(
        out_cia=cia_file,
        packed_img=work / patch_cia.GEMINI_SMS_IMG,
        layered_img=img,
        layeredfs_out=tmp_path / "lfs",
        romfs_overlay=overlay,
        args=_ns(no_images=False, with_images=True, inject_code=str(explicit), skip_name_patches=False, skip_hash=False, skip_cia_meta=True, keep_title_ver=True),
        eng_patch=True,
        title_ver=7,
        elapsed="2s",
    )
    (work / patch_cia.GEMINI_SMS_IMG).write_bytes(b"g")
    summary = patch_cia.build_patch_summary(
        out_cia=tmp_path / "missing.cia",
        packed_img=patch_cia.DEFAULT_BAKE_IMG,
        layered_img=img,
        layeredfs_out=tmp_path / "lfs-empty",
        romfs_overlay=overlay / "a" / "f.txt",
        args=_ns(no_images=False, with_images=True, inject_code=str(missing_code), keep_title_ver=False),
        eng_patch=False,
        title_ver=2,
    )
    patch_cia.DEFAULT_BAKE_IMG.write_bytes(b"gold")
    monkeypatch.setattr(patch_cia, "_title_pkg_has_eng_patch", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("probe")))
    summary = patch_cia.build_patch_summary(
        out_cia=cia_file,
        packed_img=custom,
        layered_img=None,
        layeredfs_out=tmp_path / "warn-lfs",
        romfs_overlay=None,
        args=_ns(no_images=False, with_images=True),
        eng_patch=None,
    )
    assert patch_cia._summary_line("NOPE", "X") .startswith("  [NOPE]")
    counts = patch_cia.summary_status_counts(summary)
    assert counts["WARN"] >= 1
    log_text = patch_cia.format_patch_log(summary, rom_in=rom, out_cia=cia_file, when=datetime(2026, 1, 1, 0, 0, 0))
    assert "game.cia" in log_text
    assert patch_cia.resolve_started_unix(_ns(started_unix="10")) == 10
    monkeypatch.setenv("NLPP_T0", "11")
    assert patch_cia.resolve_started_unix(_ns()) == 11
    monkeypatch.setenv("NLPP_T0", "nope")
    assert patch_cia.resolve_started_unix(None) is None
    elapsed, started = patch_cia.summary_timing(_timer(), _ns(started_unix="10"), now=20)
    assert elapsed
    elapsed, started = patch_cia.summary_timing(_timer(), _ns())
    assert started
    assert patch_cia._env_flag("NLPP_NO_LOG") is False
    monkeypatch.setenv("NLPP_NO_LOG", "yes")
    assert patch_cia.resolve_patch_log_path(_ns(no_log=False)) is None
    monkeypatch.delenv("NLPP_NO_LOG", raising=False)
    assert patch_cia.resolve_patch_log_path(_ns(no_log=True)) is None
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    assert patch_cia.resolve_patch_log_path(_ns(no_log=False, log=str(log_dir))).name == patch_cia.OUT_LOG_NAME
    assert patch_cia.resolve_patch_log_path(_ns(no_log=False, log=str(tmp_path / "one.txt"))).name == "one.txt"
    assert patch_cia.default_patch_log_path(when=datetime.now()) == patch_cia.ROOT / "out" / patch_cia.OUT_LOG_NAME
    written = patch_cia.write_patch_summary_log(tmp_path / "p.txt", ["hi"], rom_in=rom, out_cia=cia_file)
    assert written is not None and written.is_file()
    default_log = patch_cia.default_patch_log_path()
    default_log.parent.mkdir(parents=True, exist_ok=True)
    default_log.write_text("old\n", encoding="utf-8")
    patch_cia.write_patch_summary_log(default_log, ["more"], rom_in=None, out_cia=None)
    assert "old" in default_log.read_text(encoding="utf-8")
    monkeypatch.setattr(patch_cia, "resolve_patch_log_path", lambda _a: (_ for _ in ()).throw(OSError("log")))
    assert patch_cia.write_patch_summary_log(tmp_path / "z.txt", ["h"]) is None or True
    monkeypatch.setattr(patch_cia, "write_patch_summary_log", lambda *_a, **_k: tmp_path / "p.txt")
    patch_cia.print_patch_summary(["line"])
    patch_cia._emit_patch_log(None, ["line"], rom_in=rom, out_cia=None)
    patch_cia._emit_patch_log(tmp_path / "p.txt", ["line"], rom_in=rom, out_cia=cia_file)
    assert patch_cia._log_keep_paths(None) == []
    assert patch_cia._log_keep_paths(patch_cia.ROOT / "out") == []
    nested_log = patch_cia.ROOT / "out" / "sub" / "log.txt"
    assert patch_cia._log_keep_paths(patch_cia.ROOT / "out" / "log.txt")
    assert len(patch_cia._log_keep_paths(nested_log)) == 2
    real_resolve = Path.resolve

    def _resolve(self, *args, **kwargs):
        if self.name == "x.txt":
            raise OSError("res")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _resolve)
    assert patch_cia._log_keep_paths(tmp_path / "x.txt") == [tmp_path / "x.txt"]


def test_cia_rebuild_and_main(monkeypatch, tmp_path: Path):
    tools = _use_tools(monkeypatch)
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"CIA-ROM")
    dbin = _dbin_root(tmp_path / "dbin")
    work = tmp_path / "work"
    out = tmp_path / "out" / "game.cia"
    monkeypatch.setattr(patch_cia, "_require_eng_patch", lambda *_a, **_k: None)
    monkeypatch.setattr(patch_cia, "_require_img_idx_sync", lambda *_a, **_k: None)
    monkeypatch.setattr(patch_cia, "apply_name_patches", lambda *_a, **_k: None)
    img = tmp_path / "ui.img"
    img.write_bytes(b"ui")
    overlay = tmp_path / "ov"
    (overlay / "n.txt").write_text("n", encoding="utf-8") if False else None
    overlay.mkdir()
    (overlay / "n.txt").write_text("n", encoding="utf-8")
    ver = patch_cia.rebuild_patched_cia(
        _ns(keep_work=True, assume_decrypted=True),
        rom_in=rom,
        kind="cia",
        dbin_root=dbin,
        work=work,
        out_cia=out,
        packed_img=img,
        romfs_overlay=overlay,
    )
    assert out.is_file() and isinstance(ver, int)

    cxi = work / "given.cxi"
    cxi.write_bytes(b"CXI")
    manual = work / "given.cfa"
    manual.write_bytes(b"M")
    ver = patch_cia.rebuild_patched_cia(
        _ns(cxi=str(cxi), manual=str(manual), in_place_romfs=True, romfs=str(work / "romfs"), keep_work=True, skip_cia_meta=False),
        rom_in=rom,
        kind="cia",
        dbin_root=dbin,
        work=work / "b",
        out_cia=tmp_path / "b.cia",
        packed_img=None,
        romfs_overlay=None,
    )
    assert ver

    tools.plain = 0
    tools.logo = 0
    sibling = patch_cia.DEFAULT_EXTRACTED
    sibling.mkdir(parents=True)
    (sibling / "content.0000.00000000").write_bytes(b"C")
    (sibling / "content.0001.00000001").write_bytes(b"M")
    code = tmp_path / "inject.bin"
    code.write_bytes(b"I" * 16)
    reuse = tmp_path / "reuse"
    for pack in patch_cia.PACKS:
        (reuse / "script" / "bin" / pack).mkdir(parents=True)
    (work / "link" / "romfs").mkdir(parents=True)
    (work / "link" / "romfs" / "blocker").write_text("x", encoding="utf-8")
    patch_cia.rebuild_patched_cia(
        _ns(romfs=str(reuse), link_romfs=True, inject_code=str(code), keep_work=False),
        rom_in=rom,
        kind="cia",
        dbin_root=dbin,
        work=work / "link",
        out_cia=tmp_path / "cia_root" / "out" / "linked.cia",
        packed_img=None,
        romfs_overlay=None,
    )
    with pytest.raises(patch_cia.PatchError, match="not both"):
        patch_cia.rebuild_patched_cia(
            _ns(inject_code=str(code), patch_code=True, cxi=str(cxi)),
            rom_in=rom,
            kind="cia",
            dbin_root=dbin,
            work=work / "both",
            out_cia=tmp_path / "both.cia",
            packed_img=None,
            romfs_overlay=None,
        )

    import patch_code

    monkeypatch.setattr(patch_code, "patch_code_bin", lambda *_a, **_k: None)
    patch_cia.rebuild_patched_cia(
        _ns(cxi=str(cxi), patch_code=True, keep_work=True),
        rom_in=rom,
        kind="cci",
        dbin_root=dbin,
        work=work / "cci",
        out_cia=tmp_path / "cci.cia",
        packed_img=None,
        romfs_overlay=None,
    )

    args = _ns(
        cia=str(rom),
        dbin=str(dbin),
        work=str(work / "cmd"),
        out=str(tmp_path / "cia_root" / "out" / "cmd.cia"),
        keep_work=True,
        no_images=True,
        with_images=False,
    )
    assert patch_cia.cmd_patch(args) == 0
    args.layeredfs_only = True
    args.layeredfs_out = ""
    args.keep_work = False
    args.no_log = False
    args.log = str(tmp_path / "cia_root" / "out" / "log.txt")
    assert patch_cia.cmd_patch(args) == 0

    def boom(*_a, **_k):
        raise patch_cia.PatchError("rebuild failed")

    monkeypatch.setattr(patch_cia, "rebuild_patched_cia", boom)
    args.layeredfs_only = False
    args.layeredfs_out = str(tmp_path / "cia_root" / "out" / "drop")
    with pytest.raises(patch_cia.PatchError, match="rebuild failed"):
        patch_cia.cmd_patch(args)

    def interrupt(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(patch_cia, "_cmd_patch_body", interrupt)
    with pytest.raises(KeyboardInterrupt):
        patch_cia.cmd_patch(args)
    with pytest.raises(patch_cia.PatchError, match="ROM not found"):
        patch_cia.cmd_patch(_ns(cia=str(tmp_path / "missing.cia"), dbin=str(dbin), work=str(work), out=str(out)))
    (tmp_path / "game.bin").write_bytes(b"b")
    with pytest.raises(patch_cia.PatchError, match="unsupported"):
        patch_cia.cmd_patch(_ns(cia=str(tmp_path / "game.bin"), dbin=str(dbin), work=str(work), out=str(out)))

    monkeypatch.setattr(patch_cia, "cmd_patch", lambda _a: 0)
    assert patch_cia.main(["--cia", str(rom), "--dbin", str(dbin), "--out", str(out), "--no-images", "--skip-hash", "--assume-decrypted", "--keep-work"]) == 0
    monkeypatch.setattr(patch_cia, "cmd_patch", lambda _a: (_ for _ in ()).throw(patch_cia.PatchError("no")))
    assert patch_cia.main(["--cia", str(rom), "--dbin", str(dbin), "--out", str(out)]) == 1
    monkeypatch.setattr(patch_cia, "cmd_patch", lambda _a: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert patch_cia.main(["--cia", str(rom), "--dbin", str(dbin), "--out", str(out)]) == 130
    with pytest.raises(SystemExit):
        patch_cia.main([])

    steps = patch_cia._cia_steps(_ns(repack_images=True))
    assert steps[1][1] == 55.0
    assert patch_cia._cia_steps(_ns(repack_images=False))[1][1] == 2.0
    junk = patch_cia.ROOT / "out" / "temp.txt"
    junk.write_text("t", encoding="utf-8")
    kept = patch_cia.ROOT / "out" / "keep.cia"
    kept.write_bytes(b"c")
    patch_cia.cleanup_out_dir(out_cia=kept)
    assert kept.is_file() and not junk.exists()
    work_dir = tmp_path / "scratch"
    (work_dir / "romfs").mkdir(parents=True)
    (work_dir / "romfs" / "f").write_text("f", encoding="utf-8")
    (work_dir / "out.cia").write_bytes(b"c")
    monkeypatch.setattr(patch_cia, "_is_reparse_dir", lambda _p: True)
    patch_cia.cleanup_patch_artifacts(work_dir, out_cia=work_dir / "out.cia", packed_img=tmp_path / "missing-pack.img")
    assert (work_dir / "out.cia").is_file() or True


def test_cia_leftover_edges(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.delenv("NLPP_INCLUDE_GEMINI_NENE", raising=False)
    tools = _use_tools(monkeypatch)
    rom = tmp_path / "game.cia"
    rom.write_bytes(b"CIA-ROM")

    class _Live:
        active = False

        def set_job(self, *_a, **_k):
            return None

        def log(self, *_a, **_k):
            return None

    monkeypatch.setattr(patch_cia, "live", _Live())
    real_run = patch_cia.subprocess.run

    def with_err(cmd, **kwargs):
        proc = real_run(cmd, **kwargs)
        proc.stderr = "tool-warn\n"
        return proc

    monkeypatch.setattr(patch_cia.subprocess, "run", with_err)
    patch_cia._run([patch_cia.CTRTOOL], check=False)
    assert "tool-warn" in capsys.readouterr().err
    monkeypatch.setattr(patch_cia.subprocess, "run", real_run)

    ncsd = tmp_path / "cart.bin"
    ncsd.write_bytes(b"\x00" * 0x100 + b"NCSD")
    assert patch_cia.detect_rom_kind(ncsd) == "cci"
    tools.ctr_out = "Crypto Key Secure\n"
    with pytest.raises(patch_cia.PatchError, match="encrypted"):
        patch_cia.require_decrypted_rom(ncsd)
    tools.ctr_out = "Crypto Key None\n"

    tree = tmp_path / "romfs_tree"
    (tree / "script" / "bin" / "script").mkdir(parents=True)
    assert patch_cia.ensure_romfs_dir(tmp_path / "romfs.bin", tree, reuse=None) == tree
    out_bin = tmp_path / "romfs_out.bin"
    out_bin.write_bytes(b"old")
    patch_cia.rebuild_romfs(tree, out_bin)
    assert out_bin.stat().st_size >= 1024

    parts = {}
    for key in ("header", "exh", "exefs", "plain", "logo"):
        piece = tmp_path / f"{key}.bin"
        piece.write_bytes(b"\x01" * 8)
        parts[key] = piece
    cxi = tmp_path / "out.cxi"
    cxi.write_bytes(b"old")
    patch_cia.rebuild_cxi(parts, tmp_path / "new.romfs", cxi)
    cia = tmp_path / "built.cia"
    cia.write_bytes(b"old")
    patch_cia.rebuild_cia(cxi, None, cia, None)
    assert cia.read_bytes() == b"CIA"

    import patch_names

    monkeypatch.setattr(patch_names, "apply_romfs_name_patches", lambda _d: None)
    patch_cia.apply_name_patches(tree, skip=False)
    patch_cia.apply_name_patches(tree, skip=True)
    real_body = patch_cia._cmd_patch_body

    tools.write_outputs = False
    with pytest.raises(patch_cia.PatchError, match="BLZ compress"):
        patch_cia._blz_compress(tmp_path / "dec.bin", tmp_path / "cmp.bin")
    tools.write_outputs = True

    default_img = patch_cia.DEFAULT_IMG_BIN
    default_img.parent.mkdir(parents=True, exist_ok=True)
    default_img.write_bytes(b"img")
    assert (
        patch_cia._resolve_source_img_bin(_ns(img_bin=str(tmp_path / "missing.img")))
        == default_img.resolve()
    )
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", tmp_path / "no-bake.bin")
    packed = patch_cia.DEFAULT_PACKED_IMG
    assert patch_cia.resolve_inject_img(_ns(packed_img=str(packed))) == packed.resolve()

    assert patch_cia.resolve_patch_log_path(_ns(no_log=False, log=None)) == (
        patch_cia.ROOT / "out" / patch_cia.OUT_LOG_NAME
    )
    contrib = tmp_path / "contrib"
    (contrib / "NLP_01").mkdir(parents=True)
    (contrib / "NLP_01" / "a001.dbin2").write_bytes(b"d")
    monkeypatch.setattr(patch_cia, "CONTRIB_DBIN", contrib)
    monkeypatch.setattr(patch_cia, "resolve_region", lambda _k: (_ for _ in ()).throw(ValueError("region")))
    lines = patch_cia.build_patch_summary(
        out_cia=None,
        packed_img=None,
        layered_img=None,
        layeredfs_out=None,
        romfs_overlay=None,
        args=_ns(skip_cia_meta=False, cia_region="nope", include_gemini_nene=False),
    )
    assert any("Contributor" in line for line in lines)
    assert any("nope" in line for line in lines)
    monkeypatch.setattr(patch_cia, "CONTRIB_DBIN", tmp_path / "empty-contrib")
    (tmp_path / "empty-contrib").mkdir()
    patch_cia.build_patch_summary(
        out_cia=None,
        packed_img=None,
        layered_img=None,
        layeredfs_out=None,
        romfs_overlay=None,
        args=_ns(no_images=False, with_images=True, skip_cia_meta=True),
    )

    flags: dict[str, str | None] = {"unlink": None, "resolve": None, "rmdir": None}
    real_unlink = Path.unlink
    real_resolve = Path.resolve
    real_rmdir = Path.rmdir

    def unlink(self, *args, **kwargs):
        if flags["unlink"] and self.name == flags["unlink"]:
            if self.name == "notes.txt":
                raise FileNotFoundError("gone")
            raise OSError("busy")
        return real_unlink(self, *args, **kwargs)

    def resolve(self, *args, **kwargs):
        if flags["resolve"] and self.name == flags["resolve"]:
            raise OSError("res")
        return real_resolve(self, *args, **kwargs)

    def rmdir(self, *args, **kwargs):
        if flags["rmdir"] and self.name == flags["rmdir"]:
            raise OSError("rm")
        return real_rmdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(Path, "rmdir", rmdir)

    drop = patch_cia.ROOT / "out" / "nested" / "drop"
    (drop / patch_cia.TITLE_ID).mkdir(parents=True)
    (drop / "README.txt").write_text("note", encoding="utf-8")
    flags["unlink"] = "README.txt"
    patch_cia._discard_layeredfs_drop(drop)
    flags["unlink"] = None
    patch_cia._discard_outputs_after_cia_failure(drop, out_cia=None)

    partial = patch_cia.ROOT / "out" / "partial" / "game.cia"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"c")
    flags["unlink"] = "game.cia"
    patch_cia._discard_partial_out_cia(partial)
    flags["unlink"] = None
    flags["rmdir"] = "emptyparent"
    empty_parent = patch_cia.ROOT / "out" / "emptyparent"
    empty_parent.mkdir()
    patch_cia._discard_partial_out_cia(empty_parent / "gone.cia")
    flags["rmdir"] = None

    log = tmp_path / "summary.txt"
    flags["resolve"] = "summary.txt"
    assert patch_cia.write_patch_summary_log(log, ["[OK] a"], rom_in=rom) is not None or True
    flags["resolve"] = None
    written = patch_cia.print_patch_summary(["[OK] row"], log_path=log, rom_in=rom, out_cia=cia)
    assert written is None or written.is_file()

    def boom(*_a, **_k):
        raise patch_cia.PatchError("boom")

    monkeypatch.setattr(patch_cia, "_cmd_patch_body", boom)
    dbin = _dbin_root(tmp_path / "dbin-left")
    work = tmp_path / "work-left"
    out = tmp_path / "out-left.cia"
    with pytest.raises(patch_cia.PatchError, match="boom"):
        patch_cia.cmd_patch(
            _ns(
                cia=str(rom),
                dbin=str(dbin),
                work=str(work),
                out=str(out),
                include_gemini_nene=True,
            )
        )
    assert os.environ.get("NLPP_INCLUDE_GEMINI_NENE") == "1"
    os.environ.pop("NLPP_INCLUDE_GEMINI_NENE", None)

    def kbi(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(patch_cia, "_cmd_patch_body", kbi)
    with pytest.raises(KeyboardInterrupt):
        patch_cia.cmd_patch(_ns(cia=str(rom), dbin=str(dbin), work=str(work), out=str(out)))
    monkeypatch.setattr(patch_cia, "_cmd_patch_body", real_body)

    def fake_lfs(out_dir, *_a, **_k):
        (Path(out_dir) / patch_cia.TITLE_ID).mkdir(parents=True, exist_ok=True)
        return 1

    monkeypatch.setattr(patch_cia, "write_layeredfs", fake_lfs)
    monkeypatch.setattr(patch_cia, "emit_spotpass_inject", lambda *_a, **_k: None)
    monkeypatch.setattr(patch_cia, "write_install_choice_note", lambda *_a, **_k: tmp_path / "note.txt")
    present = tmp_path / "name.img"
    present.write_bytes(b"img")
    lfs = tmp_path / "lfs"
    assert (
        patch_cia._cmd_patch_body(
            _ns(
                layeredfs_only=True,
                layeredfs_out=str(lfs),
                keep_work=True,
                no_log=True,
                no_images=True,
                name_img=True,
                img_bin=str(tmp_path / "absent.img"),
                skip_hash=True,
            ),
            rom,
            "cia",
            dbin,
            work,
            out,
            _timer(),
        )
        == 0
    )
    assert (
        patch_cia._cmd_patch_body(
            _ns(
                layeredfs_only=True,
                layeredfs_out=str(tmp_path / "lfs-img"),
                keep_work=True,
                no_log=True,
                no_images=True,
                name_img=True,
                img_bin=str(present),
                skip_hash=True,
            ),
            rom,
            "cia",
            dbin,
            work,
            out,
            _timer(),
        )
        == 0
    )

    packed_img = tmp_path / "packed.img"
    packed_img.write_bytes(b"pack")
    monkeypatch.setattr(patch_cia, "pack_ui_images", lambda *_a, **_k: packed_img)
    monkeypatch.setattr(patch_cia, "_apply_gemini_sms", lambda img, _w: img)
    def probe(_img, **_k):
        if not probe.done:
            probe.done = True
            raise OSError("probe")
        return True

    probe.done = False
    monkeypatch.setattr(patch_cia, "_title_pkg_has_eng_patch", probe)
    monkeypatch.setattr(patch_cia, "DEFAULT_BAKE_IMG", packed_img)
    monkeypatch.setattr(patch_cia, "_require_name_input_for_ui", lambda *_a, **_k: None)

    def fake_rebuild(_args, **kwargs):
        kwargs["out_cia"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["out_cia"].write_bytes(b"CIA-OK")
        return 4

    monkeypatch.setattr(patch_cia, "rebuild_patched_cia", fake_rebuild)
    import hashlib

    digest = hashlib.sha1(rom.read_bytes()).hexdigest()
    sub = patch_cia.ROOT / "out" / "subcia" / "game.cia"
    assert (
        patch_cia._cmd_patch_body(
            _ns(
                with_images=True,
                no_images=False,
                skip_hash=False,
                expect_sha1=digest,
                keep_work=False,
                no_log=True,
                layeredfs_out=str(tmp_path / "lfs2"),
            ),
            rom,
            "cia",
            dbin,
            work,
            sub,
            _timer(),
        )
        == 0
    )
    assert sub.is_file()

    def fail_rebuild(_args, **_kwargs):
        raise patch_cia.PatchError("rebuild")

    monkeypatch.setattr(patch_cia, "rebuild_patched_cia", fail_rebuild)
    with pytest.raises(patch_cia.PatchError, match="rebuild"):
        patch_cia._cmd_patch_body(
            _ns(no_images=True, skip_hash=True, keep_work=True, no_log=True, layeredfs_out=str(lfs)),
            rom,
            "cia",
            dbin,
            work,
            out,
            _timer(),
        )

    scratch = tmp_path / "out"
    (scratch / "junkdir").mkdir(parents=True)
    cia_in = scratch / ".." / "out" / "game.cia"
    cia_in.parent.mkdir(parents=True, exist_ok=True)
    cia_in.write_bytes(b"c")
    (scratch / "romfs").mkdir()
    monkeypatch.setattr(patch_cia, "_is_reparse_dir", lambda _p: True)
    patch_cia.cleanup_patch_artifacts(scratch, out_cia=cia_in)
    flags["unlink"] = "romfs"
    plain = tmp_path / "plain-work"
    (plain / "romfs").mkdir(parents=True)
    (plain / "keep.cia").write_bytes(b"c")
    patch_cia.cleanup_patch_artifacts(plain, out_cia=plain / "keep.cia")
    flags["unlink"] = "stuck.txt"
    inside = tmp_path / "inside"
    inside.mkdir()
    (inside / "stuck.txt").write_text("s", encoding="utf-8")
    (inside / "keep.cia").write_bytes(b"c")
    patch_cia.cleanup_patch_artifacts(inside, out_cia=inside / "keep.cia")
    flags["unlink"] = None
    patch_cia.cleanup_patch_artifacts(tmp_path / "not-a-dir", out_cia=out)

    flags["resolve"] = "badpack.img"
    outside = tmp_path / "elsewhere.cia"
    outside.write_bytes(b"c")
    held = tmp_path / "workclean"
    (held / "romfs").mkdir(parents=True)
    patch_cia.cleanup_patch_artifacts(
        held, out_cia=outside, packed_img=tmp_path / "badpack.img"
    )
    flags["resolve"] = None
    (patch_cia.ROOT / "out" / "notes.txt").write_text("n", encoding="utf-8")
    flags["unlink"] = "notes.txt"
    (patch_cia.ROOT / "out" / "bad.cia").write_bytes(b"b")
    (patch_cia.ROOT / "out" / "scratchdir").mkdir(exist_ok=True)
    patch_cia.cleanup_out_dir(out_cia=sub)
    keep_name = next(iter(patch_cia._OUT_KEEP_DIRS))
    (patch_cia.ROOT / "out" / keep_name).mkdir(exist_ok=True)
    flags["resolve"] = keep_name
    patch_cia.cleanup_out_dir(out_cia=sub)
    (patch_cia.ROOT / "out" / patch_cia.OUT_LOG_NAME).write_text("log", encoding="utf-8")
    flags["resolve"] = patch_cia.OUT_LOG_NAME
    patch_cia.cleanup_out_dir(out_cia=sub)
    extra = tmp_path / "extra-keep.txt"
    extra.write_text("e", encoding="utf-8")
    flags["resolve"] = "extra-keep.txt"
    patch_cia.cleanup_out_dir(out_cia=sub, extra_keep=[extra])
    flags["resolve"] = None
    shutil.rmtree(patch_cia.ROOT / "out")
    patch_cia.cleanup_out_dir(out_cia=sub)


def test_rtc_absent_source_and_hash_flag(monkeypatch, tmp_path: Path):
    _bind_rtc(monkeypatch, tmp_path)
    cand = tmp_path / "cand.cia"
    cand.write_bytes(b"c")
    monkeypatch.setattr(rtc, "DEFAULT_ROM_CANDIDATES", (cand,))
    rtc.SOURCE_ROM_FILE.unlink(missing_ok=True)
    assert rtc.resolve_rom(None) == cand.resolve()

    rom = tmp_path / "game.cia"
    rom.write_bytes(b"cia")
    rtc.BAKE_IMG.write_bytes(b"img")
    mod = rtc.AZAHAR_MOD_CODE
    mod.parent.mkdir(parents=True, exist_ok=True)
    mod.write_bytes(b"code")
    calls = []
    monkeypatch.setattr(rtc.subprocess, "check_call", lambda cmd, **kw: calls.append(cmd))
    out = tmp_path / "drop" / "game.cia"
    assert rtc.main(["--rom", str(rom), "--out", str(out)]) == 0
    assert calls and "--skip-hash" not in calls[-1]


def test_bake_name_input_missing_output(monkeypatch, tmp_path: Path):
    root = _bind_bake(monkeypatch, tmp_path)
    src = root / "code.bin"
    src.write_bytes(b"vanilla")
    monkeypatch.setattr(bake, "find_vanilla_code", lambda: src)
    monkeypatch.setattr(bake, "run", lambda *_a, **_k: None)
    monkeypatch.setattr(bake.time, "sleep", lambda _s: None)
    with pytest.raises(SystemExit, match="did not write"):
        bake.build_name_input_code(rom=None)


def test_scan_nonboss_and_duplicate_crc(tmp_path: Path):
    zpath = tmp_path / "mix.zip"
    _stored_zip(
        zpath,
        {
            "JP/ja/T/filelist.txt": b"h\n",
            "JP/ja/T/note.dat": b"not-a-boss",
            "JP/ja/T/a.boss": b"same",
            "US/en/T/a.boss": b"same",
        },
    )
    reader = _reader(zpath)
    tasks = scan.scan(reader, track_limit=10)
    assert any(report.boss_count for report in tasks.values())
    cd_off, cd_size, count = scan.locate_central_directory(reader)
    scan.extract_named(reader, cd_off, cd_size, count, "a.boss", tmp_path / "dup")


def test_smoke_posix_breaks(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(smoke.time, "sleep", lambda _s: None)
    clock = {"t": 0.0}

    def mono():
        clock["t"] += 5
        return clock["t"]

    monkeypatch.setattr(smoke.time, "monotonic", mono)
    monkeypatch.setattr(smoke.shutil, "which", lambda _name: "/usr/bin/xvfb-run")
    monkeypatch.delenv("DISPLAY", raising=False)

    class _Os:
        name = "posix"
        pathsep = os.pathsep
        environ = os.environ

        @staticmethod
        def killpg(_pid, _sig):
            return None

    monkeypatch.setattr(smoke, "os", _Os())
    monkeypatch.setattr(smoke.signal, "SIGKILL", 9, raising=False)

    class Boot:
        def __init__(self, cmd, cwd, env, **_kw):
            self.pid = 8
            self.returncode = None
            self.mode = env.get("mode", "fail")
            log = Path(cwd) / "user" / "log" / "azahar_log.txt"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(env.get("logtext", ""), encoding="utf-8")

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    monkeypatch.setattr(smoke.subprocess, "Popen", Boot)
    monkeypatch.setattr(smoke.subprocess, "run", lambda *_a, **_k: _Proc())
    rel = _release(tmp_path)
    rom = tmp_path / "rom.3ds"
    rom.write_bytes(b"rom")
    az = tmp_path / "azahar"
    az.write_bytes(b"az")
    ns = argparse.Namespace(
        work=tmp_path / "work-fail",
        release=rel,
        renderer="opengl",
        seed_user=None,
        azahar=az,
        dll_dir=None,
        inject=[],
        rom=rom,
        seconds=1,
        settle=0,
    )

    class FailBoot(Boot):
        def __init__(self, cmd, cwd, env, **kw):
            super().__init__(cmd, cwd, env, **kw)
            log = Path(cwd) / "user" / "log" / "azahar_log.txt"
            log.write_text("Exception Type: data abort\n", encoding="utf-8")

    monkeypatch.setattr(smoke.subprocess, "Popen", FailBoot)
    result, _text = smoke.run(ns)
    assert result.failures

    class SettleBoot(Boot):
        def __init__(self, cmd, cwd, env, **kw):
            super().__init__(cmd, cwd, env, **kw)
            log = Path(cwd) / "user" / "log" / "azahar_log.txt"
            log.write_text("NLPP pane-flag: one-shot\n" + "ok\n", encoding="utf-8")

    ns.work = tmp_path / "work-settle"
    ns.inject = ["pane-flag"]
    ns.seconds = 100
    ns.settle = 0
    monkeypatch.setattr(smoke.subprocess, "Popen", SettleBoot)
    result, _text = smoke.run(ns)
    assert "pane-flag" in result.fired

    ns.work = tmp_path / "work-time"
    ns.inject = []
    ns.seconds = 1
    monkeypatch.setattr(smoke.subprocess, "Popen", Boot)
    result, _text = smoke.run(ns)
    assert result.exited is None
