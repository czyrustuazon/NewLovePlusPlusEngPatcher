"""smoke_boot_azahar log verdicts and LayeredFS layout (no emulator needed)."""

from __future__ import annotations

from conftest import TOOLS, load_module

smoke = load_module("smoke_boot_azahar", TOOLS / "smoke_boot_azahar.py")

MOD_OK = (
    "Service.FS <Warning> ... code.bin overriding built-in ExeFS file\n"
    "Service.FS <Info> ... LayeredFS replacement file in use for /img.bin\n"
)


def _verdict(text: str, inject=(), exited=None):
    r = smoke.Result(exited=exited)
    smoke.scan(text, list(inject), r)
    return smoke.verdict(r, text, list(inject)), r


def test_clean_boot_passes():
    problems, _ = _verdict(MOD_OK + "HW.GPU <Critical> Texture size (1x1) is not multiple of 4\n")
    assert problems == []


def test_exception_report_fails_once():
    text = MOD_OK + "Exception Type: Data Abort\nFAR 0x5F\nException Type: Data Abort\n"
    problems, _ = _verdict(text)
    assert len(problems) == 1 and "abort" in problems[0]


def test_name_walk_abort_line_fails():
    text = MOD_OK + (
        "Core <Critical> NLPP name-walk data abort (dump 2026-10-01 18:36) "
        "FAR 0x162b70b8 offset 0x00746954 PC 0x00644d78\n"
    )
    problems, _ = _verdict(text, inject=["name-walk"])
    assert any("name-walk guard missing" in p for p in problems)


def test_unmapped_access_and_err_f_fail():
    problems, _ = _verdict(MOD_OK + "Core.Memory <Error> unmapped Read32 @ 0x00000000\n")
    assert any("unmapped" in p for p in problems)
    problems, _ = _verdict(MOD_OK + "Service.ERR <Critical> fatal error\n")
    assert any("ERR:f" in p for p in problems)


def test_injection_must_fire():
    problems, _ = _verdict(MOD_OK, inject=["pane-flag"])
    assert any("pane-flag hook never fired" in p for p in problems)
    fired = MOD_OK + "Core <Warning> NLPP pane-flag: one-shot null r6 before 0x003c5fcc\n"
    problems, r = _verdict(fired, inject=["pane-flag"])
    assert problems == [] and r.fired == {"pane-flag"}


def test_mod_not_loaded_or_early_exit_fails():
    problems, _ = _verdict("boot without mods\n")
    assert any("code.bin was not loaded" in p for p in problems)
    assert any("img.bin was not loaded" in p for p in problems)
    problems, _ = _verdict(MOD_OK, exited=3)
    assert any("exited early" in p for p in problems)


def test_install_mod_matches_ab_seed_layout(tmp_path, monkeypatch):
    rel = tmp_path / "release"
    (rel / "romfs_overlay" / "SystemData").mkdir(parents=True)
    (rel / "bake_img.bin").write_bytes(b"img")
    (rel / "name_input_code.bin").write_bytes(b"code")
    (rel / "romfs_overlay" / "SystemData" / "x.trb").write_bytes(b"trb")
    calls = []
    monkeypatch.setattr(smoke.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    user = tmp_path / "user"
    smoke.install_mod(user, rel)
    mod = user / "load" / "mods" / smoke.TITLE_ID
    assert (mod / "romfs" / "img.bin").read_bytes() == b"img"
    assert (mod / "exefs" / "code.bin").read_bytes() == b"code"
    assert (mod / "code.bin").read_bytes() == b"code"
    assert (mod / "romfs" / "SystemData" / "x.trb").read_bytes() == b"trb"
    assert calls and calls[0][-2:] == ["--layeredfs", str(mod / "romfs")]


def test_config_enables_exception_handler_and_null_audio(tmp_path):
    smoke.write_config(tmp_path, "opengl")
    ini = (tmp_path / "config" / "qt-config.ini").read_text(encoding="utf-8")
    assert "enable_exception_handler=true" in ini
    assert "graphics_api=1" in ini
    assert "output_type=1" in ini
    assert "confirmClose=false" in ini
