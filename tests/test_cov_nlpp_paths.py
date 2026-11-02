"""Branch coverage for nlpp_paths finders.

Every dump / cache location is pointed at an empty tmp tree first, so the
same branches run on a dev box with game dumps and on CI without them. The
Windows drive scan is driven through a fake ``os`` / ``ctypes`` so it runs on
Linux too.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import nlpp_paths as paths

CANDIDATES = (
    "DEFAULT_VANILLA_CODE_BAK",
    "DEFAULT_VANILLA_CODE",
    "CACHE_VANILLA_CODE",
    "DEFAULT_VANILLA_IMG",
    "CACHE_VANILLA_IMG",
    "TRANSLATIONS_JSON",
    "TEXTRESOURCE",
    "OVERLAY_TRB_DIR",
    "DEFAULT_VANILLA_MAIN_TRB",
    "CACHE_VANILLA_MAIN_TRB",
    "DEFAULT_VANILLA_RESIDENT_TRB",
    "CACHE_VANILLA_RESIDENT_TRB",
    "CACHE_VANILLA_SCRIPT",
    "DEFAULT_VANILLA_SCRIPT",
)
ENVS = (
    "NLPP_VANILLA_CODE",
    "NLPP_VANILLA_IMG",
    "NLPP_TRANSLATIONS_JSON",
    "NLPP_VANILLA_TRB",
    "NLPP_VANILLA_RESIDENT_TRB",
    "NLPP_VANILLA_SCRIPT",
    "NLPP_LUMA_TITLE",
    "NLPP_AZAHAR_USER_DIR",
    "AZAHAR_USER_DIR",
    "APPDATA",
)


@pytest.fixture
def empty(tmp_path, monkeypatch):
    """All finders see nothing; returns the tmp root."""
    for env in ENVS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(paths, "ROOT", tmp_path / "root")
    for name in CANDIDATES:
        monkeypatch.setattr(paths, name, tmp_path / "none" / name)
    monkeypatch.setattr(paths, "_windows_drive_roots", lambda: [])
    return tmp_path


def _touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_azahar_user_dir_falls_back_to_home(empty, monkeypatch):
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: empty / "home"))
    assert paths.azahar_user_dir() == (empty / "home" / "AppData" / "Roaming" / "Azahar").resolve()


def test_windows_drive_roots(monkeypatch):
    monkeypatch.setattr(paths, "os", SimpleNamespace(name="posix", environ=os.environ))
    assert paths._windows_drive_roots() == []
    monkeypatch.setattr(paths, "os", SimpleNamespace(name="nt", environ=os.environ))
    kernel = SimpleNamespace(GetLogicalDrives=lambda: 0b101)  # A: and C:
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    assert paths._windows_drive_roots() == [Path("A:/"), Path("C:/")]


def test_luma_title_code_env_variants(empty, monkeypatch):
    code = _touch(empty / "card" / "code.bin")
    monkeypatch.setenv("NLPP_LUMA_TITLE", str(code))
    assert paths.luma_title_code() == code.resolve()

    monkeypatch.setenv("NLPP_LUMA_TITLE", str(code.parent))
    assert paths.luma_title_code() == code.resolve()

    exefs = _touch(empty / "card2" / "exefs" / "code.bin")
    monkeypatch.setenv("NLPP_LUMA_TITLE", str(empty / "card2"))
    assert paths.luma_title_code() == exefs.resolve()

    (empty / "card3").mkdir()
    monkeypatch.setenv("NLPP_LUMA_TITLE", str(empty / "card3"))
    assert paths.luma_title_code() == (empty / "card3" / "code.bin").resolve()


def test_luma_title_code_scans_drives(empty, monkeypatch):
    class _Unreadable:
        def __truediv__(self, rel):
            return self

        def is_file(self):
            raise OSError("drive not ready")

    hit = _touch(empty / "sd" / "luma" / "titles" / paths.TITLE_ID / "exefs" / "code.bin")
    monkeypatch.setattr(paths, "_windows_drive_roots", lambda: [_Unreadable(), empty / "sd"])
    assert paths.luma_title_code() == hit.resolve()
    monkeypatch.setattr(paths, "_windows_drive_roots", lambda: [_Unreadable()])
    assert paths.luma_title_code() is None


def test_install_luma_title_code(empty, monkeypatch, capsys):
    with pytest.raises(FileNotFoundError):
        paths.install_luma_title_code(empty / "missing.bin")
    src = _touch(empty / "new" / "code.bin", b"N" * 1_000_001)
    assert paths.install_luma_title_code(src) is None
    assert "no SD card" in capsys.readouterr().out

    dest = _touch(empty / "card" / "code.bin", b"old")
    _touch(dest.with_name("code.bin.bak_pre_name_walk"), b"older")
    monkeypatch.setenv("NLPP_LUMA_TITLE", str(dest))
    assert paths.install_luma_title_code(src) == dest.resolve()
    assert dest.with_name("code.bin.bak_pre_name_walk").read_bytes() == b"older"


def test_code_and_img_finders(empty, monkeypatch):
    monkeypatch.setenv("NLPP_VANILLA_CODE", str(empty / "nope.bin"))
    monkeypatch.setenv("NLPP_VANILLA_IMG", str(empty / "nope.bin"))
    assert paths.find_vanilla_code() is None
    assert paths.find_vanilla_img() is None
    code = _touch(paths.CACHE_VANILLA_CODE)
    img = _touch(paths.CACHE_VANILLA_IMG)
    assert paths.require_vanilla_code() == code.resolve()
    assert paths.require_vanilla_img() == img.resolve()


def test_translations_json(empty, monkeypatch):
    with pytest.raises(FileNotFoundError):
        paths.require_translations_json()
    monkeypatch.setenv("NLPP_TRANSLATIONS_JSON", str(empty / "nope.json"))
    assert paths.find_translations_json() is None
    env = _touch(empty / "t.json")
    monkeypatch.setenv("NLPP_TRANSLATIONS_JSON", str(env))
    assert paths.find_translations_json() == env.resolve()
    monkeypatch.delenv("NLPP_TRANSLATIONS_JSON")
    found = _touch(paths.OVERLAY_TRB_DIR / "translations.json")
    assert paths.require_translations_json() == found.resolve()


def test_trb_finders(empty, monkeypatch):
    monkeypatch.setenv("NLPP_VANILLA_TRB", str(empty / "nope.trb"))
    monkeypatch.setenv("NLPP_VANILLA_RESIDENT_TRB", str(empty / "nope.trb"))
    assert paths.find_vanilla_main_trb() is None
    assert paths.find_vanilla_resident_trb() is None

    env = _touch(empty / "resident.trb")
    monkeypatch.setenv("NLPP_VANILLA_RESIDENT_TRB", str(env))
    assert paths.find_vanilla_resident_trb() == env.resolve()
    monkeypatch.delenv("NLPP_VANILLA_RESIDENT_TRB")
    cached = _touch(paths.CACHE_VANILLA_RESIDENT_TRB)
    assert paths.find_vanilla_resident_trb() == cached.resolve()


def test_script_finder(empty, monkeypatch):
    monkeypatch.setenv("NLPP_VANILLA_SCRIPT", str(empty / "nope"))
    paths.CACHE_VANILLA_SCRIPT.mkdir(parents=True)  # present but empty
    assert paths.find_vanilla_script_dir() is None
    _touch(paths.DEFAULT_VANILLA_SCRIPT / "a001.dbin2")
    assert paths.find_vanilla_script_dir() == paths.DEFAULT_VANILLA_SCRIPT.resolve()


def test_main_trb_finder(empty, monkeypatch):
    assert paths.find_vanilla_main_trb() is None
    cached = _touch(paths.CACHE_VANILLA_MAIN_TRB)
    assert paths.find_vanilla_main_trb() == cached.resolve()
    env = _touch(empty / "main.trb")
    monkeypatch.setenv("NLPP_VANILLA_TRB", str(env))
    assert paths.find_vanilla_main_trb() == env.resolve()


def test_luma_env_that_is_neither_file_nor_dir(empty, monkeypatch):
    monkeypatch.setenv("NLPP_LUMA_TITLE", str(empty / "unplugged"))
    assert paths.luma_title_code() is None


def test_install_luma_ignores_short_stand_in(empty):
    assert paths.install_luma_title_code(_touch(empty / "short.bin")) is None
