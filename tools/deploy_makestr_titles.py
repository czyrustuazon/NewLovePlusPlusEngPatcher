#!/usr/bin/env python3
"""Restore FUN_0024842c; hook MakeStr with Options/Gallery/clock title remaps."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import patch_clock_text as c  # noqa: E402
import patch_ui_titles as t  # noqa: E402

MOD = (
    Path.home()
    / "AppData/Roaming/Azahar/load/mods/00040000000F4E00/exefs/code.bin"
)
BAK = MOD.with_suffix(".bin.bak_titles")
LFS = (
    ROOT
    / "out/layeredfs/00040000000F4E00/code.bin"
)


def main() -> int:
    if not BAK.is_file():
        raise SystemExit(f"missing {BAK}")
    shutil.copy2(BAK, MOD)
    print("restored FUN_0024842c from bak_titles")

    lookup = t.load_lookup()
    pairs: list[tuple[bytes, bytes]] = []
    seen: set[bytes] = set()
    for jp, en, also_nlp in t.TITLE_PAIRS:
        en_b = en.encode("utf-8")
        variants = [jp.encode("utf-8")]
        if also_nlp:
            variants.append(t.nlp_encode(jp, lookup))
        for jp_b in variants:
            if jp_b in seen:
                continue
            seen.add(jp_b)
            pairs.append((jp_b, en_b))

    c.PAIRS = pairs
    data = bytearray(MOD.read_bytes())
    # Clear old title cave / any prior MakeStr cave
    data[c.CAVE_ADDR : c.CAVE_ADDR + 2052] = b"\x00" * 2052
    # Ensure MakeStr has original head before we assemble (assemble doesn't check)
    if data[c.ADDR_MAKE_STR : c.ADDR_MAKE_STR + 4] != c.ORIG_MAKESTR_HEAD:
        # may already be hooked from old experiment — restore from bak
        data[c.ADDR_MAKE_STR : c.ADDR_MAKE_STR + 4] = c.ORIG_MAKESTR_HEAD

    cave = c.assemble_cave()
    print(f"pairs={len(pairs)} cave={len(cave)} @ {c.CAVE_ADDR:#x}")
    if len(cave) > 2052:
        raise SystemExit(f"cave too large: {len(cave)}")

    data[c.CAVE_ADDR : c.CAVE_ADDR + len(cave)] = cave
    data[c.ADDR_MAKE_STR : c.ADDR_MAKE_STR + 4] = c.b_ins(c.ADDR_MAKE_STR, c.CAVE_ADDR)
    MOD.write_bytes(data)
    shutil.copy2(MOD, LFS)
    print(f"MakeStr hooked -> {MOD}")
    print(f"synced {LFS}")
    print(
        "heads:",
        "MakeStr",
        data[c.ADDR_MAKE_STR : c.ADDR_MAKE_STR + 4].hex(),
        "DrawTitle",
        data[0x24842C : 0x24842C + 4].hex(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
