"""pip installs must not need a C compiler for PyYAML.

On a Python newer than PyYAML's wheels (3.15 at the time), pip builds it from
source and the libyaml extension build fails without MSVC, so Drop CIA stopped
at "Building wheel for PyYAML ... error". ``PYYAML_FORCE_LIBYAML=0`` makes it
build the pure-Python wheel.
"""

from __future__ import annotations

from conftest import ROOT, SRC, load_module

setup_tools = load_module("setup_tools", SRC / "setup_tools.py")

BAT = ROOT / "Drop CIA or 3DS Here to Patch.bat"


def test_pip_env_disables_libyaml(monkeypatch):
    monkeypatch.setenv("NLPP_MARK", "kept")
    env = setup_tools.pip_env()
    assert env["PYYAML_FORCE_LIBYAML"] == "0"
    assert env["NLPP_MARK"] == "kept"


def test_ensure_python_deps_passes_pip_env(monkeypatch):
    calls: list[dict] = []

    real_import = __import__

    def fake_import(name, *a, **k):
        if name == "yaml":
            raise ImportError(name)
        return real_import(name, *a, **k)

    class Ok:
        returncode = 0

    def fake_run(cmd, **kw):
        calls.append(kw)
        monkeypatch.setattr("builtins.__import__", real_import)
        return Ok()

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.setattr(setup_tools.subprocess, "run", fake_run)
    setup_tools.ensure_python_deps()
    assert calls and calls[0]["env"]["PYYAML_FORCE_LIBYAML"] == "0"


def test_drop_bat_disables_libyaml_before_pip():
    lines = BAT.read_text(encoding="utf-8").splitlines()
    pip = next(i for i, ln in enumerate(lines) if "-m pip install -r" in ln and "echo" not in ln)
    assert any(ln.strip() == 'set "PYYAML_FORCE_LIBYAML=0"' for ln in lines[:pip])
