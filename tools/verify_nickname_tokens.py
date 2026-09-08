#!/usr/bin/env python3
"""Verify Manaka nickname tokens in XML vs rebuild_dbin2."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from patch_names import parse_dbin2  # noqa: E402

HERO_TOKEN = "▲高嶺＊＊▲"
PLAIN_TAKANE = re.compile(r"(?<!▲)Takane(?!＊)")


def dialog_lines(path: Path) -> list[str]:
    _, _, entries = parse_dbin2(path.read_bytes())
    out: list[str] = []
    for entry in entries:
        out.extend(entry.sdl2.dialogs)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scripts", type=Path, default=ROOT / "assets" / "scripts")
    ap.add_argument("--dbin", type=Path, default=ROOT / "rebuild_dbin2" / "script")
    ap.add_argument("--glob", default="t*.xml")
    args = ap.parse_args(argv)

    scripts = sorted(args.scripts.glob(args.glob))
    token_mismatches: list[str] = []
    dual_form: list[str] = []
    xml_tokens = 0
    dbin_tokens = 0

    for xml_path in scripts:
        stem = xml_path.stem
        dbin_path = args.dbin / f"{stem}.dbin2"
        text = xml_path.read_text(encoding="utf-8")
        xt = text.count(HERO_TOKEN)
        xml_tokens += xt
        if not dbin_path.is_file():
            token_mismatches.append(f"{stem}: missing dbin2")
            continue
        dialogs = dialog_lines(dbin_path)
        joined = "\n".join(dialogs)
        dt = joined.count(HERO_TOKEN)
        dbin_tokens += dt
        if xt != dt:
            token_mismatches.append(f"{stem}: xml_tokens={xt} dbin_tokens={dt}")
        if xt > 0 and PLAIN_TAKANE.search(joined):
            dual_form.append(stem)

    print(f"Checked {len(scripts)} scripts")
    print(f"  XML  {HERO_TOKEN}: {xml_tokens}")
    print(f"  dbin2 {HERO_TOKEN}: {dbin_tokens}")
    if dual_form:
        print(
            f"  note: {len(dual_form)} scripts use both {HERO_TOKEN} and plain "
            f"'Takane' (expected in some lines)"
        )
    if token_mismatches:
        print(f"TOKEN MISMATCHES ({len(token_mismatches)}):")
        for line in token_mismatches[:30]:
            print(f"  {line}")
        if len(token_mismatches) > 30:
            print(f"  ... +{len(token_mismatches) - 30} more")
        return 1
    print("OK — dbin2 matches XML token counts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
