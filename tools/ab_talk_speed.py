#!/usr/bin/env python3
"""A/B in-game TalkWindow Message Speed (code.bin only).

A = name-input stack + TalkWindow ÷4 table + voice/script cap (heroine/NPC)
B = same stack + ÷4 table, vanilla tick (cpy r6, r2) — player-only speed

Options preview 14/8/2/0 is on **both**. Img.bin is not touched.

  python tools/ab_talk_speed.py
  .\\make.ps1 talk-speed-ab
  .\\make.ps1 launch-a
  .\\make.ps1 launch-b
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from deploy_name_input_en import apply_name_input_stack  # noqa: E402
from nlpp_paths import TITLE_ID, azahar_mod_root, find_vanilla_code  # noqa: E402
from patch_message_speed import (  # noqa: E402
    TALK_PATCHED,
    TALK_TABLE_OFF,
    is_options_patched,
    is_sample_patched,
    is_talk_cap_patched,
    is_talk_cap_vanilla,
    is_talk_patched,
    revert_talk_cap,
)

INSTANCES = ROOT / "out" / "azahar_instances"


def _mod(letter: str) -> Path:
    user = INSTANCES / letter / "user"
    if not user.is_dir():
        raise SystemExit(
            f"missing instance {letter}: {user}\nRun: .\\make.ps1 instances"
        )
    return azahar_mod_root(TITLE_ID, user_dir=user)


def _write_code(mod: Path, data: bytes) -> Path:
    exefs = mod / "exefs"
    exefs.mkdir(parents=True, exist_ok=True)
    dest = exefs / "code.bin"
    dest.write_bytes(data)
    (mod / "code.bin").write_bytes(data)
    return dest


def _talk_dwords(data: bytes) -> tuple[int, ...]:
    n = len(TALK_PATCHED)
    return struct.unpack_from(f"<{n}I", data, TALK_TABLE_OFF)


def _build(*, cap: bool) -> bytearray:
    vanilla = find_vanilla_code()
    if vanilla is None:
        raise SystemExit("vanilla code.bin not found")
    data = bytearray(vanilla.read_bytes())
    apply_name_input_stack(data)
    if not is_talk_patched(data):
        raise SystemExit("expected TalkWindow table to be patched")
    if not is_options_patched(data):
        raise SystemExit("Options 14/8/2/0 missing — name-input stack incomplete")
    if not is_sample_patched(data):
        raise SystemExit("expected EN Text Speed sample sentence")
    if cap:
        if not is_talk_cap_patched(data):
            raise SystemExit("expected talk cap cave on A")
    else:
        revert_talk_cap(data)
        if not is_talk_cap_vanilla(data) or is_talk_cap_patched(data):
            raise SystemExit("failed to restore vanilla talk cap on B")
    return data


def _summarize(letter: str, data: bytes, *, cap: bool) -> None:
    got = _talk_dwords(data)
    if got != TALK_PATCHED:
        raise SystemExit(f"{letter}: talk table {got} != {TALK_PATCHED}")
    label = "cap min(table, voice)" if cap else "table only (heroine vanilla)"
    print(
        f"[talk-ab] {letter.upper()} {label}: @{TALK_TABLE_OFF:#x} "
        f"{'/'.join(str(v) for v in got)}  cap={is_talk_cap_patched(data)}  "
        f"options=14/8/2/0",
        flush=True,
    )


def main() -> int:
    builds = (("a", True), ("b", False))
    for letter, cap in builds:
        mod = _mod(letter)
        print(f"[talk-ab] patch {letter} -> {mod / 'exefs' / 'code.bin'}", flush=True)
        data = _build(cap=cap)
        _write_code(mod, data)
        _summarize(letter, data, cap=cap)

    print(
        "\nA/B ready. Same TalkWindow table (10/18/22/28/55); only the voice/script cap differs.\n"
        "A = min(table, script/voice delay). B = table for player, vanilla heroine pace.\n"
        "Compare a heroine date line vs a player line on both instances.\n"
        "  .\\make.ps1 launch-a\n"
        "  .\\make.ps1 launch-b\n",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
