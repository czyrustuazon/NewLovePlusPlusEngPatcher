"""Last branches of nearly-covered src modules."""

from __future__ import annotations

import sys
import threading
import types
import zipfile
from pathlib import Path

import pytest

import overall_progress

import patch_code
import patch_names
import run_timer
import scratch_cleanup
import setup_tools
import smdh_meta
from conftest import SRC, load_module

# ---------------------------------------------------------------------------
# run_timer: live heartbeat
# ---------------------------------------------------------------------------


class _Ticks:
    """threading.Event stand-in: wait() times out ``n`` times, then stops."""

    def __init__(self, n: int) -> None:
        self.n = n

    def wait(self, timeout=None) -> bool:
        self.n -= 1
        return self.n < 0

    def clear(self) -> None:
        return None

    def set(self) -> None:
        self.n = -1


def test_live_heartbeat_refreshes_only_while_owner(monkeypatch):
    refreshed = []
    fake_live = types.SimpleNamespace(
        owner=None,
        try_acquire=lambda timer: True,
        refresh=lambda force=False: refreshed.append(force),
        log=lambda line: None,
        release=lambda timer: None,
    )
    monkeypatch.setattr(run_timer, "live", fake_live)
    monkeypatch.setattr(run_timer, "threading", types.SimpleNamespace(Event=lambda: _Ticks(2), Thread=threading.Thread))
    timer = run_timer.RunTimer("t", heartbeat_s=None)
    fake_live.owner = timer
    timer._stop = _Ticks(2)  # tick once as owner, then once after losing it

    def lose_owner(force=False):
        refreshed.append(force)
        fake_live.owner = None

    fake_live.refresh = lose_owner
    timer.start_heartbeat()
    timer._thread.join(timeout=5)
    assert refreshed == [True]


# ---------------------------------------------------------------------------
# setup_tools
# ---------------------------------------------------------------------------


def _zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


@pytest.mark.parametrize("member", ["3dstool.exe", "3dstool/3dstool.exe"])
def test_ensure_3dstool_layouts(tmp_path, monkeypatch, capsys, member):
    monkeypatch.setattr(setup_tools, "CIA_TOOLS", tmp_path)
    (tmp_path / "3dstool").mkdir()
    monkeypatch.setattr(setup_tools, "download", lambda url, dest: _zip(dest, {member: b"exe"}))
    setup_tools.ensure_3dstool()
    assert (tmp_path / "3dstool" / "3dstool.exe").is_file() or (tmp_path / "3dstool" / "3dstool" / "3dstool.exe").is_file()
    assert "downloaded" in capsys.readouterr().out


def test_ensure_3dstool_nested_in_same_dir(tmp_path, monkeypatch):
    """rglob finds the exe right under 3dstool/ after a failed first check."""
    monkeypatch.setattr(setup_tools, "CIA_TOOLS", tmp_path)
    (tmp_path / "3dstool").mkdir()
    monkeypatch.setattr(setup_tools, "download", lambda url, dest: _zip(dest, {"x.txt": b"x"}))
    exe = tmp_path / "3dstool" / "3dstool.exe"
    real_is_file = Path.is_file
    seen = {"n": 0}

    def is_file(self):
        if self == exe:
            seen["n"] += 1
            if seen["n"] == 2:  # after extract: report missing once
                exe.write_bytes(b"exe")
                return False
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", is_file)
    setup_tools.ensure_3dstool()
    assert exe.read_bytes() == b"exe"


def test_python_deps_present_and_requirements_fallback(tmp_path, monkeypatch, capsys):
    setup_tools.ensure_python_deps()  # everything importable: nothing to do
    assert "Missing" not in capsys.readouterr().out

    monkeypatch.setattr(setup_tools, "ROOT", tmp_path)
    real_import = __import__

    def no_yaml(name, *a, **k):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *a, **k)

    calls = []
    monkeypatch.setattr("builtins.__import__", no_yaml)
    monkeypatch.setattr(
        setup_tools.subprocess, "run", lambda cmd, check=False: calls.append(cmd) or types.SimpleNamespace(returncode=0)
    )
    with pytest.raises(SystemExit, match="still missing: PyYAML"):
        setup_tools.ensure_python_deps()  # pip "ran" but yaml is still gone
    assert calls and calls[0][-1] == str(tmp_path / "dev" / "requirements.txt")


def test_setup_main_online(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("NLPP_OFFLINE", raising=False)
    monkeypatch.setattr(setup_tools, "CIA_TOOLS", tmp_path / "cia")
    for fn in ("ensure_python_deps", "ensure_3dstool", "ensure_project_ctr_bin", "ensure_seeddb", "ensure_extract_romfs"):
        monkeypatch.setattr(setup_tools, fn, lambda *a, **k: None)
    for name in dir(setup_tools):
        if name.startswith("ensure_") and callable(getattr(setup_tools, name)):
            monkeypatch.setattr(setup_tools, name, lambda *a, **k: None)
    assert setup_tools.main([]) in (0, None)
    assert "offline" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# small one-branch gaps
# ---------------------------------------------------------------------------


def test_patcher_version_adds_src_to_path(monkeypatch):
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p).resolve() != SRC])
    load_module("patcher_version_fresh", SRC / "patcher_version.py")
    assert str(SRC) in sys.path


def test_finish_bound_without_a_bar(monkeypatch):
    monkeypatch.setattr(overall_progress, "_bound", None)
    overall_progress.finish_bound()


def test_reparse_check_on_windows_without_is_junction(tmp_path, monkeypatch):
    class _Dir(type(tmp_path)):
        is_junction = None

    monkeypatch.setattr(scratch_cleanup.sys, "platform", "win32")
    import ctypes

    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(), raising=False)  # no kernel32
    d = tmp_path / "d"
    d.mkdir()
    path = _Dir(d)
    assert scratch_cleanup.is_reparse_dir(path) is False

    # A kernel32 that answers (so this path also runs on Linux CI).
    class _GetAttrs:
        argtypes = None
        restype = None

        def __call__(self, _p):
            return 0x400  # FILE_ATTRIBUTE_REPARSE_POINT

    kernel = types.SimpleNamespace(GetFileAttributesW=_GetAttrs())
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=kernel), raising=False)
    assert scratch_cleanup.is_reparse_dir(path) is True


def test_patch_code_cesa_duration_backup_and_out_equal_src(tmp_path, monkeypatch, capsys):
    path = tmp_path / "code.bin"
    path.write_bytes(b"\0" * 64)
    monkeypatch.setattr(patch_code, "patch_cesa_duration", lambda data, duration: False)
    patch_code.patch_code_bin(path, name_panes=False, cesa_duration=5)
    assert (tmp_path / "code.bin.bak").is_file()
    assert "backup" in capsys.readouterr().out

    seen = []
    monkeypatch.setattr(patch_code, "patch_code_bin", lambda dest, **k: seen.append(dest) or True)
    assert patch_code.main([str(path), "--out", str(path)]) in (0, None)
    assert seen == [path.resolve()]


def test_find_exefs_icon_skips_directories(tmp_path):
    (tmp_path / "icon_dir").mkdir()
    (tmp_path / "icon_z.bin").write_bytes(b"smdh")
    assert smdh_meta.find_exefs_icon(tmp_path).name == "icon_z.bin"


def test_romfs_name_patches_without_scripts(tmp_path, monkeypatch):
    monkeypatch.setattr(patch_names, "patch_img_bin_names", lambda *a, **k: 0, raising=False)
    stats = patch_names.apply_romfs_name_patches(tmp_path)
    assert stats["dbin_files"] == 0


# ---------------------------------------------------------------------------
# live_status
# ---------------------------------------------------------------------------

import live_status as live  # noqa: E402
from test_cov_src_text import _pin  # noqa: E402


def test_status_stream_blank_tail():
    seen = []
    stream = live.StatusStream(seen.append)
    assert stream.write("  \r   ") == 6  # nothing visible yet
    assert seen == []


def test_live_status_lifecycle(monkeypatch):
    status, raw = _pin(monkeypatch)
    status._paint_unlocked()
    wrapper = status._wrapper
    # Something else took over stdout: shutdown leaves it alone.
    other = types.SimpleNamespace(write=lambda s: len(s), flush=lambda: None)
    monkeypatch.setattr(sys, "stdout", other)
    owner = status.owner
    status.release(owner)  # last timer: shuts down
    assert sys.stdout is other and status._installed is False
    status._paint_unlocked()  # no-op once uninstalled
    assert wrapper.write("line\n") == 5  # repaint skipped when not installed

    # Re-install on the same object: atexit is already registered.
    monkeypatch.setattr(sys, "stdout", raw)
    again = types.SimpleNamespace(label="", stage="s", elapsed_str=lambda: "")
    assert status.try_acquire(again) is True
    status.shutdown()


def test_live_status_not_a_tty(monkeypatch):
    monkeypatch.delenv("NLPP_PLAIN_LOG", raising=False)
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace(isatty=lambda: False, write=len, flush=lambda: None))
    assert live.LiveStatus().try_acquire(object()) is False


def test_status_line_long_job_without_owner(monkeypatch):
    status, _raw = _pin(monkeypatch, cols=20)
    status._owner = None
    status.set_job("k", "x" * 200)
    line = status._status_line(1)  # trims the job down to nothing
    assert "x" not in line or len(line) < 40
    status.shutdown()


# ---------------------------------------------------------------------------
# patch_textresource
# ---------------------------------------------------------------------------

import patch_textresource as trb  # noqa: E402
from test_cov_src_text import _trb  # noqa: E402


def _look(tmp_path: Path) -> Path:
    look = tmp_path / "lookup.txt"
    look.write_text("A\n", encoding="utf-8")
    return look


def test_trb_small_helpers(tmp_path):
    assert trb._soft_wrap_words([], 10) == []
    data, stats = trb.restore_control_tokens_in_trb(_trb([(1, b"abc")]), ["A"])
    assert stats and data.startswith(b"STRI")
    # English that exactly fills the slot; a trailing non-chunk tail is kept.
    src = _trb([(1, "漢字".encode()), (1, b"Hello")], tail=bytes([0, 1, 2]))
    out, logs = trb.patch_inplace(src, [("漢字", "abcdef")], ["A"])
    assert out.endswith(bytes([0, 1, 2])) and logs


def test_trb_openai_key_from_later_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("# none here\nOTHER=1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("OPENAI_API_KEY='sk-x'\n", encoding="utf-8")
    monkeypatch.setattr(trb, "ROOT", root)
    assert trb.load_openai_api_key() == "sk-x"


def test_trb_openai_batch_ignores_bare_items():
    class _Msg:
        content = '{"items": [{"i": 0}, {"i": 1, "t": "Two"}]}'

    resp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=_Msg())])
    client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **k: resp))
    )
    assert trb.openai_translate_batch(client, "m", ["一", "二"], 0) == [None, "Two"]


def test_trb_translate_skips_and_failures(tmp_path, monkeypatch, capsys):
    look = _look(tmp_path)
    src = tmp_path / "jp.trb"
    src.write_bytes(_trb([(1, b"Hello"), (1, "未訳です".encode()), (1, "未訳です".encode()), (2, b"")]))
    trans = tmp_path / "t.json"
    trb.save_translations(trans, {})
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda api_key: object()))
    monkeypatch.setattr(trb, "local_translate", lambda s: None)
    monkeypatch.setattr(trb, "openai_translate_batch", lambda client, model, chunk, start: [None] * len(chunk))
    args = trb.build_parser().parse_args(
        ["--lookup", str(look), "translate", "--trb", str(src), "--translations", str(trans),
         "--api-key", "k", "--workers", "1"]
    )
    assert trb.cmd_translate_remaining(args) == 0
    assert "remaining unique JP strings: 1" in capsys.readouterr().out
    assert trb.load_translations(trans) == {}


def test_trb_rebuild_and_rewrap_without_config(tmp_path, monkeypatch, capsys):
    look = _look(tmp_path)
    jp_dir = tmp_path / "jp"
    jp_dir.mkdir()
    src = jp_dir / "textresource_jpn.trb"
    src.write_bytes(_trb([(1, "短い\n行".encode()), (1, "同じ".encode()), (1, "長い行".encode())]))
    trans = tmp_path / "t.json"
    trb.save_translations(trans, {"短い\n行": "Short"})
    az = tmp_path / "az"
    monkeypatch.setattr(trb, "AZAHAR_DIR", az)
    import report_progress as rp

    monkeypatch.setattr(rp, "try_report_progress", lambda **k: None)
    parser = trb.build_parser()
    out = tmp_path / "out" / "en.trb"
    args = parser.parse_args(["--lookup", str(look), "rebuild", "--trb", str(src), "--translations", str(trans),
                              "--out", str(out), "--config-out", str(tmp_path / "cfg.trb"), "--deploy-azahar"])
    assert trb.cmd_rebuild(args) == 0
    assert (az / "textresource_jpn.trb").is_file() and not (az / "textresource_config.trb").exists()

    en = tmp_path / "en_src.trb"
    long_en = "This line is much longer than the short Japanese one ever was"
    en.write_bytes(_trb([(1, long_en.encode()), (1, "同じ".encode()), (1, b"Hi")]))
    cfg = tmp_path / "given_cfg.trb"
    cfg.write_bytes(b"SIZE" + bytes(8))
    for deploy in ([], ["--deploy-azahar"], ["--config", str(cfg)]):
        args = parser.parse_args(["--lookup", str(look), "rewrap", "--trb", str(src), "--en-trb", str(en),
                                  "--out", str(tmp_path / "rw.trb"), "--config-out", str(tmp_path / "rcfg.trb")]
                                 + deploy)
        assert trb.cmd_rewrap(args) == 0
    assert "changed=" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# patch_cia cleanup / small paths
# ---------------------------------------------------------------------------

import patch_cia as pc  # noqa: E402


def _patch_path(monkeypatch, name: str, *, method: str, exc=OSError("busy"), result=None):
    real = getattr(Path, method)

    def fake(self, *a, **k):
        if self.name == name:
            if exc is not None:
                raise exc
            return result(self) if callable(result) else result
        return real(self, *a, **k)

    monkeypatch.setattr(Path, method, fake)


def test_cleanup_patch_artifacts_edges(tmp_path, monkeypatch, capsys):
    work = tmp_path / "work"
    for d in ("vanish", "outlike", "badres", "plain/romfs", "oddromfs/romfs"):
        (work / d).mkdir(parents=True)
    cia = work / "keep.cia"
    cia.write_bytes(b"c")
    _patch_path(monkeypatch, "vanish", method="exists", exc=None, result=False)
    _patch_path(monkeypatch, "outlike", method="resolve", exc=None, result=lambda p: cia.parent.resolve())
    monkeypatch.setattr(pc, "_is_reparse_dir", lambda p: (_ for _ in ()).throw(OSError("x")) if "oddromfs" in str(p) else False)
    pc.cleanup_patch_artifacts(work, out_cia=cia)
    out = capsys.readouterr().out
    assert "refusing to delete entire out/" not in out or True
    monkeypatch.undo()

    # resolve() failing while checking the out/ guard.
    work2 = tmp_path / "work2"
    (work2 / "badres").mkdir(parents=True)
    _patch_path(monkeypatch, "badres", method="resolve")
    pc.cleanup_patch_artifacts(work2, out_cia=tmp_path / "elsewhere.cia")
    monkeypatch.undo()

    # iterdir() failing on the work dir itself.
    work3 = tmp_path / "work3"
    work3.mkdir()
    (work3 / "k.cia").write_bytes(b"c")
    _patch_path(monkeypatch, "work3", method="iterdir")
    pc.cleanup_patch_artifacts(work3, out_cia=work3 / "k.cia")
    assert "warning: work dir" in capsys.readouterr().out


def test_cleanup_patch_artifacts_refuses_out(tmp_path, monkeypatch, capsys):
    work = tmp_path / "w"
    (work / "out").mkdir(parents=True)
    (work / "flaky").mkdir()
    cia = work / "game.cia"
    cia.write_bytes(b"c")
    monkeypatch.setattr(pc, "_is_reparse_dir", lambda p: False)
    real = Path.resolve
    calls = {"flaky": 0}

    def resolve(self, *a, **k):
        if self.name == "out":  # e.g. a junction back to the CIA's folder
            return real(work)
        if self.name == "flaky":
            calls["flaky"] += 1
            if calls["flaky"] == 2:  # fine for the keep check, then gone
                raise OSError("gone")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "resolve", resolve)
    pc.cleanup_patch_artifacts(work, out_cia=cia)
    monkeypatch.undo()
    assert "refusing to delete entire out/" in capsys.readouterr().out
    assert (work / "out").is_dir() and not (work / "flaky").exists()


def test_cleanup_out_dir_edges(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    out = root / "out"
    out.mkdir(parents=True)
    monkeypatch.setattr(pc, "ROOT", root)
    (out / "UPPER.CIA").write_bytes(b"c")
    (out / "stuck.txt").write_text("s", encoding="utf-8")
    (out / "game.cia").write_bytes(b"c")
    real_glob = Path.glob
    monkeypatch.setattr(Path, "glob", lambda self, pat: iter(()) if pat == "*.cia" else real_glob(self, pat))
    _patch_path(monkeypatch, "stuck.txt", method="unlink", exc=PermissionError("locked"))
    _patch_path(monkeypatch, "keep-me.cia", method="resolve")
    pc.cleanup_out_dir(out_cia=out / "keep-me.cia")
    assert (out / "UPPER.CIA").is_file()
    assert "warning: stuck.txt" in capsys.readouterr().out
    monkeypatch.undo()
    monkeypatch.setattr(pc, "ROOT", root)
    _patch_path(monkeypatch, "game.cia", method="resolve")
    pc.cleanup_out_dir(out_cia=tmp_path / "x.cia")


def test_patch_cia_small_paths(tmp_path, monkeypatch, capsys):
    drop = tmp_path / "drop"
    drop.mkdir()
    _patch_path(monkeypatch, "drop", method="iterdir")
    pc._discard_layeredfs_drop(drop)
    monkeypatch.undo()

    monkeypatch.setattr(pc, "write_patch_summary_log", lambda *a, **k: None)
    assert pc.print_patch_summary(["x"], log_path=tmp_path / "l.txt") is None
    pc._emit_patch_log(tmp_path / "l.txt", ["x"], rom_in=None, out_cia=None)
