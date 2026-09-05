#!/usr/bin/env python3
"""Report layered English script coverage (Manaka + NLPPPATCH 28%)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from script_inject import (  # noqa: E402
    DEFAULT_ENG_DBIN,
    coverage_summary,
    nlppatch_script_dir,
    nlppatch_stems,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dbin", type=Path, default=DEFAULT_ENG_DBIN)
    args = ap.parse_args(argv)

    eng = args.dbin.resolve()
    s = coverage_summary(eng)
    nlp_dir = nlppatch_script_dir()

    print("=== Script coverage (target patch composition) ===")
    print(f"EngPatcher dbin:     {eng}")
    print(f"NLPPPATCH vendor:    {nlp_dir or '(missing — run tools/fetch_nlppatch_release.py)'}")
    print(f"NLPPPATCH stems:     {s['nlppatch_available']}")
    print()
    print(f"Unique script IDs:   {s['total_stems']} (script pack)")
    print(f"  Manaka t* (100%):  {s['manaka']}")
    print(f"  EngPatcher p*:     {s['eng_p']}")
    print(f"  NLPPPATCH layer:   {s['nlppatch']}")
    print(f"  Japanese (base):   {s['jp']}")
    print(f"English total:       {s['english_stems']} ({s['english_pct']}%)")
    print()
    print("Images / UI:         release/bake_img.bin (unchanged by this report)")
    print("TRB / menus:         release/textresource/ (unchanged)")

    if not nlp_dir:
        print()
        print("Fetch NLPPPATCH to enable the 28% layer:")
        print("  python tools/fetch_nlppatch_release.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
