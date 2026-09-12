"""Patcher release id + gold-bake stamp.

During RC, Drop ignores leftover ``release/bake_img.bin`` unless
``release/bake_stamp.txt`` matches ``PATCHER_RELEASE``. That way unzipping a
new RC over an old folder does not silently inject yesterday's menus.

Bump ``PATCHER_RELEASE`` together with the title Eng Patch badge.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHER_RELEASE = "v1.0.0-rc2"
BAKE_STAMP = ROOT / "release" / "bake_stamp.txt"
ENG_PATCH_LINE = f"Eng Patch {PATCHER_RELEASE}"


def bake_stamp_matches(path: Path | None = None) -> bool:
    p = path if path is not None else BAKE_STAMP
    if not p.is_file():
        return False
    return p.read_text(encoding="utf-8").strip() == PATCHER_RELEASE


def write_bake_stamp(path: Path | None = None) -> Path:
    p = path if path is not None else BAKE_STAMP
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(PATCHER_RELEASE + "\n", encoding="utf-8")
    return p


if __name__ == "__main__":
    # Drop bat: exit 0 if leftover bake belongs to this RC, else 2.
    raise SystemExit(0 if bake_stamp_matches() else 2)
