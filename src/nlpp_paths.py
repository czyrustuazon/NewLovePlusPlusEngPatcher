"""Canonical EngPatcher paths — self-contained; Azahar is optional for testing only."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Durable release artifacts (gold bake + RomFS overlays). Not wipeable scratch.
RELEASE = ROOT / "release"
BAKE_IMG = RELEASE / "bake_img.bin"
NAME_INPUT_CODE = RELEASE / "name_input_code.bin"
ROMFS_OVERLAY = RELEASE / "romfs_overlay"
TEXTRESOURCE = RELEASE / "textresource"
OVERLAY_TRB_DIR = ROMFS_OVERLAY / "SystemData" / "TextResource"

# Optional PNG-pack intermediate (may be wiped; not gold).
CACHE = ROOT / "cache"
CACHE_NEW_IMG = CACHE / "new_img.bin"
# Content-addressed BCLIM + exact-zlib slots for pack_images (see img_pack_cache.py).
CACHE_IMG_PACK = CACHE / "img_pack"
# Vanilla RomFS extracted from a dropped .cia/.3ds when sibling dump is absent.
CACHE_VANILLA_ROMFS = CACHE / "vanilla_from_rom" / "romfs"
CACHE_VANILLA_IMG = CACHE_VANILLA_ROMFS / "img.bin"
CACHE_VANILLA_MAIN_TRB = (
    CACHE_VANILLA_ROMFS / "SystemData" / "TextResource" / "textresource_jpn.trb"
)
CACHE_VANILLA_EXEFS = CACHE / "vanilla_from_rom" / "exefs"
CACHE_VANILLA_CODE = CACHE_VANILLA_EXEFS / "code.bin"
CACHE_VANILLA_RESIDENT_TRB = (
    CACHE_VANILLA_ROMFS
    / "SystemData"
    / "TextResource"
    / "textresource_resident_jpn.trb"
)
CACHE_VANILLA_SCRIPT = CACHE_VANILLA_ROMFS / "script" / "bin" / "script"

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
DEFAULT_VANILLA_SCRIPT = DEFAULT_EXTRACTED / "romfs" / "script" / "bin" / "script"

TITLE_ID = "00040000000F4E00"


def azahar_user_dir() -> Path:
    """Azahar user root (mods, saves, config). Override with NLPP_AZAHAR_USER_DIR."""
    env = os.environ.get("NLPP_AZAHAR_USER_DIR") or os.environ.get("AZAHAR_USER_DIR")
    if env:
        return Path(env).expanduser().resolve()
    appdata = os.environ.get("APPDATA")
    if appdata:
        return (Path(appdata) / "Azahar").resolve()
    return (Path.home() / "AppData" / "Roaming" / "Azahar").resolve()


def azahar_mod_root(title_id: str = TITLE_ID, user_dir: Path | None = None) -> Path:
    root = user_dir or azahar_user_dir()
    return root / "load" / "mods" / title_id


_AZAHAR_MOD = azahar_mod_root()
AZAHAR_MOD_ROOT = _AZAHAR_MOD
AZAHAR_MOD_EXEFS = _AZAHAR_MOD / "exefs"
AZAHAR_MOD_CODE = AZAHAR_MOD_EXEFS / "code.bin"
AZAHAR_MOD_ROMFS = _AZAHAR_MOD / "romfs"
AZAHAR_MOD_IMG = AZAHAR_MOD_ROMFS / "img.bin"
AZAHAR_MOD_TRB_DIR = AZAHAR_MOD_ROMFS / "SystemData" / "TextResource"
DEFAULT_VANILLA_CODE = DEFAULT_EXTRACTED / "exefs" / "code.bin"
DEFAULT_VANILLA_CODE_BAK = DEFAULT_EXTRACTED / "exefs" / "code.bin.bak"


def find_vanilla_code() -> Path | None:
    env = os.environ.get("NLPP_VANILLA_CODE")
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
    for c in (
        DEFAULT_VANILLA_CODE_BAK,
        DEFAULT_VANILLA_CODE,
        ROOT / "extracted" / "exefs" / "code.bin.bak",
        ROOT / "extracted" / "exefs" / "code.bin",
        CACHE_VANILLA_CODE,
    ):
        if c.is_file():
            return c.resolve()
    return None


def require_vanilla_code() -> Path:
    p = find_vanilla_code()
    if p is None:
        raise FileNotFoundError(
            "vanilla exefs/code.bin not found.\n"
            "Provide one of:\n"
            "  • python tools/rebuild_bake_img.py --rom path\\to\\game.cia|.3ds|.cci\n"
            "    (fills cache/vanilla_from_rom/exefs/code.bin)\n"
            "  • set NLPP_VANILLA_CODE\n"
            "  • place a dump at:\n"
            f"      {DEFAULT_VANILLA_CODE_BAK} or {DEFAULT_VANILLA_CODE}\n"
            "  • or cache extract at:\n"
            f"      {CACHE_VANILLA_CODE}"
        )
    return p


def find_vanilla_img() -> Path | None:
    env = os.environ.get("NLPP_VANILLA_IMG")
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
    for c in (
        DEFAULT_VANILLA_IMG,
        ROOT / "extracted" / "romfs" / "img.bin",
        CACHE_VANILLA_IMG,
    ):
        if c.is_file():
            return c.resolve()
    return None


def require_vanilla_img() -> Path:
    p = find_vanilla_img()
    if p is None:
        raise FileNotFoundError(
            "vanilla romfs/img.bin not found.\n"
            "Provide one of:\n"
            "  • python tools/rebuild_bake_img.py --rom path\\to\\game.cia|.3ds|.cci\n"
            "  • set NLPP_VANILLA_IMG to a vanilla img.bin\n"
            "  • place a dump at:\n"
            f"      {DEFAULT_VANILLA_IMG}\n"
            f"  • or cache extract at:\n"
            f"      {CACHE_VANILLA_IMG}"
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
        CACHE_VANILLA_MAIN_TRB,
    ):
        if c.is_file():
            return c.resolve()
    return None


def find_vanilla_resident_trb() -> Path | None:
    env = os.environ.get("NLPP_VANILLA_RESIDENT_TRB")
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
    for c in (
        DEFAULT_VANILLA_RESIDENT_TRB,
        ROOT
        / "extracted"
        / "romfs"
        / "SystemData"
        / "TextResource"
        / "textresource_resident_jpn.trb",
        CACHE_VANILLA_RESIDENT_TRB,
    ):
        if c.is_file():
            return c.resolve()
    return None


def find_vanilla_script_dir() -> Path | None:
    """Directory of Japanese .dbin2 scripts (prefer CIA cache over EN-patched dump)."""
    env = os.environ.get("NLPP_VANILLA_SCRIPT")
    if env:
        p = Path(env)
        if p.is_dir():
            return p.resolve()
    # Cache from extract_vanilla_from_rom first — sibling extracted/ is often EN-overwritten.
    for c in (CACHE_VANILLA_SCRIPT, DEFAULT_VANILLA_SCRIPT):
        if c.is_dir() and any(c.glob("*.dbin2")):
            return c.resolve()
    return None
