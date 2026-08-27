#!/usr/bin/env python3
"""Deploy gojūon keyboard romaji display patch to Azahar LayeredFS code.bin.

See src/patch_input_romaji.py. Fully quit Azahar after running.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patch_input_romaji import main  # noqa: E402

if __name__ == "__main__":
    # default: deploy to Azahar
    argv = sys.argv[1:]
    if "--deploy-azahar" not in argv and "-h" not in argv and "--help" not in argv:
        argv = ["--deploy-azahar", *argv]
    raise SystemExit(main(argv))
