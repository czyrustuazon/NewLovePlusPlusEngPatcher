#!/usr/bin/env python3
"""Record where each shipped line of a contributor script came from.

The workbench shows this next to every line card, so credit goes only to the
lines a contributor's wording actually ships on. Codes in
``assets/script_contrib/line_credits.json``:

  c    the contributor's line (punctuation and line breaks may differ)
  c+   the contributor's line, edited in review
  g    the Gemini machine line
  g+   the Gemini line, improved in review
  n    the community (NLPPATCH) line Gemini kept
  n+   the community line, improved in review
  ""   no label (nameplates and ○○○○ placeholders)

Only wording counts. A line that differs from its source only in punctuation,
case, or line breaks keeps the source's code.

  python tools/line_credits.py a002 --name "Armando Esteban Quito" --pack pack.json
  python tools/line_credits.py k007 --name Dnnz.Cstr --pack old.json --pack new.json --edited 21,49

``--pack`` may repeat (several packs for one stem by the same person).
``--edited`` forces ``c+`` on lines an agent changed from the contributor's
wording when the original pack is gone. ``--reviewed`` forces ``g+`` / ``n+``
on lines where review dropped the contributor's wording and rewrote the
source line from the Japanese.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nlpp_paths import find_vanilla_script_dir  # noqa: E402
from patch_names import parse_dbin2  # noqa: E402

CREDITS = ROOT / "assets" / "script_contrib" / "line_credits.json"
CONTRIB = ROOT / "assets" / "script_contrib" / "dbin2" / "script"
GEMINI = ROOT / "assets" / "gemini_heroines" / "dbin2" / "script"
COMMUNITY = ROOT / "rebuild_dbin2" / "script"
NAMEPLATES = {"姉ヶ崎", "小早川", "高嶺"}
_MARK_RE = re.compile(r"▲[^▲]*▲")


def words(text: str) -> str:
    """Wording only: marks kept as one symbol, letters and digits lower-cased."""
    return re.sub(r"[^a-z0-9#]", "", _MARK_RE.sub("#", text).lower())


def dialogs(path: Path) -> list[str] | None:
    if not path.is_file():
        return None
    return [d for e in parse_dbin2(path.read_bytes())[2] for d in e.sdl2.dialogs]


def _close(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, words(a), words(b)).ratio()


def classify(
    final: str,
    jp: str,
    gemini: str,
    community: str | None,
    contributor: list[str],
    *,
    edited: bool = False,
    reviewed: bool = False,
) -> str:
    """One line's code. ``contributor`` holds that person's wordings for it."""
    if jp in NAMEPLATES or re.fullmatch(r"[○〇]+", jp or ""):
        return ""
    base = "n" if community is not None and words(community) == words(gemini) else "g"
    mine = [c for c in contributor if c and words(c) != words(gemini)]
    if reviewed:
        return base + "+"
    if any(words(final) == words(c) for c in mine):
        return "c+" if edited else "c"
    if words(final) == words(gemini):
        return base
    if edited:
        return "c+"
    if mine and max(_close(final, c) for c in mine) >= _close(final, gemini):
        return "c+"
    return base + "+"


def build(
    stem: str,
    packs: list[list[str]],
    *,
    edited: set[int] = frozenset(),
    reviewed: set[int] = frozenset(),
    jp: list[str] | None = None,
) -> list[str]:
    final = dialogs(CONTRIB / f"{stem}.dbin2")
    gemini = dialogs(GEMINI / f"{stem}.dbin2")
    if final is None or gemini is None or len(final) != len(gemini):
        raise SystemExit(f"{stem}: need a contrib and a Gemini script of the same length")
    community = dialogs(COMMUNITY / f"{stem}.dbin2")
    if community is not None and len(community) != len(final):
        community = None
    for pack in packs:
        if len(pack) != len(final):
            raise SystemExit(f"{stem}: a pack has {len(pack)} lines, the script has {len(final)}")
    if not jp or len(jp) != len(final):
        vanilla_dir = find_vanilla_script_dir()
        vanilla = dialogs(vanilla_dir / f"{stem}.dbin2") if vanilla_dir else None
        jp = vanilla if vanilla and len(vanilla) == len(final) else [""] * len(final)
    return [
        classify(
            final[i],
            jp[i],
            gemini[i],
            community[i] if community else None,
            [p[i] for p in packs],
            edited=i in edited,
            reviewed=i in reviewed,
        )
        for i in range(len(final))
    ]


def load_credits() -> dict:
    if not CREDITS.is_file():
        return {}
    return json.loads(CREDITS.read_text(encoding="utf-8"))


def save_credits(data: dict) -> None:
    body = {k: data[k] for k in sorted(data)}
    text = "{\n" + ",\n".join(
        f'  {json.dumps(k)}: {{"name": {json.dumps(v["name"], ensure_ascii=False)}, '
        f'"lines": {json.dumps(v["lines"])}}}'
        for k, v in body.items()
    ) + "\n}\n"
    CREDITS.write_text(text, encoding="utf-8", newline="\n")


def _pack_lines(path: Path, stem: str) -> tuple[list[str], list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data.get("items", []):
        if item.get("stem") == stem:
            return list(item["dialogs"]), list(item.get("baseline_dialogs") or [])
    raise SystemExit(f"{path}: no item for {stem}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stem")
    ap.add_argument("--name", required=True, help="contributor credited on c / c+ lines")
    ap.add_argument("--pack", type=Path, action="append", default=[], help="nlpp-contrib JSON")
    ap.add_argument("--edited", default="", help="comma list of indexes forced to c+")
    ap.add_argument("--reviewed", default="", help="comma list of indexes forced to g+ / n+")
    args = ap.parse_args(argv)
    packs, jp = [], None
    for path in args.pack:
        lines, baseline = _pack_lines(path, args.stem)
        packs.append(lines)
        jp = jp or baseline
    edited = {int(n) for n in args.edited.split(",") if n.strip()}
    reviewed = {int(n) for n in args.reviewed.split(",") if n.strip()}
    codes = build(args.stem, packs, edited=edited, reviewed=reviewed, jp=jp)
    data = load_credits()
    data[args.stem] = {"name": args.name, "lines": codes}
    save_credits(data)
    counts = {c or "-": codes.count(c) for c in sorted(set(codes))}
    print(f"[line-credits] {args.stem} {args.name}: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
