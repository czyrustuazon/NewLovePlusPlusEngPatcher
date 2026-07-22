"""Canonical EngPatcher paths — self-contained; Azahar is optional for testing only."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Durable release artifacts (gold bake + RomFS overlays). Not wipeable scratch.
RELEASE = ROOT / "release"
BAKE_IMG = RELEASE / "bake_img.bin"
ROMFS_OVERLAY = RELEASE / "romfs_overlay"
TEXTRESOURCE = RELEASE / "textresource"
OVERLAY_TRB_DIR = ROMFS_OVERLAY / "SystemData" / "TextResource"

# Optional PNG-pack intermediate (may be wiped; not gold).
CACHE = ROOT / "cache"
CACHE_NEW_IMG = CACHE / "new_img.bin"

# Scratch
OUT = ROOT / "out"

# Commit-worthy translation source (regenerates release TRBs).
ASSETS_TEXTRESOURCE = ROOT / "assets" / "textresource"
TRANSLATIONS_JSON = ASSETS_TEXTRESOURCE / "translations.json"

DEFAULT_EXTRACTED = ROOT.parent / "New Love Plus Plus" / "extracted"
DEFAULT_VANILLA_IMG = DEFAULT_EXTRACTED / "romfs" / "img.bin"
DEFAULT_VANILLA_ROMFS = DEFAULT_EXTRACTED / "romfs"
DEFAULT_VANILLA_RESIDENT_TRB = (
    DEFAULT_EXTRACTED / "romfs" / "SystemData" / "TextResource" / "textresource_resident_jpn.trb"
)
DEFAULT_VANILLA_MAIN_TRB = (
    DEFAULT_EXTRACTED / "romfs" / "SystemData" / "TextResource" / "textresource_jpn.trb"
)

TITLE_ID = "00040000000F4E00"
AZAHAR_MOD_IMG = (
    Path.home() / "AppData" / "Roaming" / "Azahar" / "load" / "mods" / TITLE_ID / "romfs" / "img.bin"
)
AZAHAR_MOD_TRB_DIR = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "Azahar"
    / "load"
    / "mods"
    / TITLE_ID
    / "romfs"
    / "SystemData"
    / "TextResource"
)


def find_vanilla_img() -> Path | None:
    env = os.environ.get("NLPP_VANILLA_IMG")
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
    for c in (
        DEFAULT_VANILLA_IMG,
        ROOT / "extracted" / "romfs" / "img.bin",
    ):
        if c.is_file():
            return c.resolve()
    return None


def require_vanilla_img() -> Path:
    p = find_vanilla_img()
    if p is None:
        raise FileNotFoundError(
            "vanilla romfs/img.bin not found. Set NLPP_VANILLA_IMG or place the dump at:\n"
            f"  {DEFAULT_VANILLA_IMG}"
        )
    return p


def find_translations_json() -> Path | None:
    env = os.environ.get("NLPP_TRANSLATIONS_JSON")
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
    for c in (
        TRANSLATIONS_JSON,
        TEXTRESOURCE / "translations.json",
        OVERLAY_TRB_DIR / "translations.json",
    ):
        if c.is_file():
            return c.resolve()
    return None


def require_translations_json() -> Path:
    p = find_translations_json()
    if p is None:
        raise FileNotFoundError(
            "translations.json not found. Expected:\n"
            f"  {TRANSLATIONS_JSON}"
        )
    return p


def find_vanilla_main_trb() -> Path | None:
    env = os.environ.get("NLPP_VANILLA_TRB")
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
    for c in (
        DEFAULT_VANILLA_MAIN_TRB,
        ROOT / "extracted" / "romfs" / "SystemData" / "TextResource" / "textresource_jpn.trb",
    ):
        if c.is_file():
            return c.resolve()
    return None
