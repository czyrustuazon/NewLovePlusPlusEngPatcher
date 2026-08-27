#!/usr/bin/env python3
"""Rebuild textresource_jpn.trb for name-input kanji candidates.

Single-kanji → English *meaning* glosses (芽→Bud, 茄→eggplant) break name
entry. Rebuild from vanilla TRB applying translations.json but **skipping**
single CJK keys except a small UI allowlist (seasons / weekdays).

Deploys to Azahar LayeredFS romfs TextResource.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patch_textresource import (  # noqa: E402
    AZAHAR_DIR,
    DEFAULT_TRANSLATIONS,
    load_lookup,
    load_translations,
    rebuild_trb,
    update_config_size,
)
import shutil

VANILLA_TRB = (
    ROOT.parents[0]
    / "New Love Plus Plus"
    / "extracted"
    / "romfs"
    / "SystemData"
    / "TextResource"
    / "textresource_jpn.trb"
)
VANILLA_CFG = VANILLA_TRB.parent / "textresource_config.trb"
LOOKUP = ROOT / "tools" / "Trb2xlsx" / "TrbExport" / "lookup.txt"

# Keep these single-kanji EN strings for chrome (not name candidates).
UI_KANJI_ALLOW = set("冬春夏秋日月火水木金土")

_CJK1 = re.compile(r"^[\u3400-\u9fff\uf900-\ufaff]$")
# Gojūon keys must stay hiragana/katakana. translations.json maps あ→A / か→ka;
# the name-input font does not draw those Latin strings, so the grid is blank.
_KANA1 = re.compile(r"^[\u3040-\u30ff]$")


def filter_mapping(mapping: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    skipped = 0
    for k, v in mapping.items():
        if _KANA1.match(k) or (_CJK1.match(k) and k not in UI_KANJI_ALLOW):
            skipped += 1
            continue
        out[k] = v
    print(f"[name-kanji-trb] kept {len(out)} / {len(mapping)} (skipped {skipped} kana/kanji keys)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deploy-azahar", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not VANILLA_TRB.is_file():
        raise SystemExit(f"missing vanilla TRB {VANILLA_TRB}")
    mapping = filter_mapping(load_translations(DEFAULT_TRANSLATIONS))
    if args.dry_run:
        return 0

    lookup = load_lookup(LOOKUP)
    rebuilt, stats = rebuild_trb(VANILLA_TRB.read_bytes(), mapping, lookup)
    out = ROOT / "out" / "textresource_jpn_namekanji.trb"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(rebuilt)
    print(f"[name-kanji-trb] {stats} -> {out} ({len(rebuilt)} bytes)")

    cfg_out = ROOT / "out" / "textresource_config_namekanji.trb"
    size_value = max(len(rebuilt), 0xC0000)
    cfg_out.write_bytes(update_config_size(VANILLA_CFG.read_bytes(), size_value))
    print(f"[name-kanji-trb] config SIZE={size_value} -> {cfg_out}")

    if args.deploy_azahar:
        dest = AZAHAR_DIR / "textresource_jpn.trb"
        dest.parent.mkdir(parents=True, exist_ok=True)
        bak = dest.with_suffix(dest.suffix + ".bak_pre_namekanji")
        if dest.is_file() and not bak.exists():
            shutil.copy2(dest, bak)
        shutil.copy2(out, dest)
        shutil.copy2(cfg_out, AZAHAR_DIR / "textresource_config.trb")
        print(f"[name-kanji-trb] deployed {dest}")
        print("Fully quit Azahar. Name candidates should be kanji again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
