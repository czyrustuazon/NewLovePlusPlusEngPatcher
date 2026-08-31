#!/usr/bin/env python3
"""Deploy gojūon keyboard romaji display patch to Azahar LayeredFS code.bin.

Prefer the full stack: tools/deploy_name_input_en.py (or .\\make.ps1 deploy-a).
This wrapper only runs src/patch_input_romaji.py.
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
