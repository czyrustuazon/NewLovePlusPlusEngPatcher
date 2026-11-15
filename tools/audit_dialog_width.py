#!/usr/bin/env python3
"""List English script lines too wide for the game, for the stems you name.

The game cuts talk text at 30 columns and choice buttons at 28, mid-word
(``src/dialog_wrap.py``). The patcher re-wraps those lines at spaces on
inject, so this is about wording, not crashes. Run it on each stem as it
goes into the patcher (ingest, review, proofread) and re-break or shorten
every line it lists. Older shipped text is left until its stem is added.

For each stem and script pack (``script``, ``NLP_01``, ``NLP_02``) it reads
the file the patcher ships: ``assets/script_contrib``, then Gemini for an
``a*`` / ``k*`` stem, then ``rebuild_dbin2``. Line numbers are the
workbench's ``#N`` (1-based across the whole script). ``fits as`` is the
re-break the patcher would make.

  python tools/audit_dialog_width.py a002 k007
  python tools/audit_dialog_width.py --contrib     # every reviewed stem

Exit status is 1 when any line is too wide.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dialog_wrap import (  # noqa: E402
    CHOICE_COLUMNS,
    TALK_COLUMNS,
    choice_dialogs,
    fit_font,
    over_width,
    wrap_dialog,
)
from patch_names import parse_dbin2  # noqa: E402

PACKS = ("script", "NLP_01", "NLP_02")
CONTRIB = ROOT / "assets" / "script_contrib" / "dbin2"
GEMINI = ROOT / "assets" / "gemini_heroines" / "dbin2"
ENG = ROOT / "rebuild_dbin2"


def shipped_path(
    pack: str,
    stem: str,
    *,
    contrib: Path = CONTRIB,
    gemini: Path = GEMINI,
    eng: Path = ENG,
) -> Path | None:
    for root, ok in ((contrib, True), (gemini, stem[:1] in ("a", "k")), (eng, True)):
        path = root / pack / f"{stem}.dbin2"
        if ok and path.is_file():
            return path
    return None


def audit_file(path: Path) -> list[dict]:
    """Too-wide dialogs in one ``.dbin2``, with the kit index (1-based)."""
    _, _, entries = parse_dbin2(path.read_bytes())
    found: list[dict] = []
    base = 0
    for entry in entries:
        choices = choice_dialogs(entry.sdl2)
        for i, text in enumerate(entry.sdl2.dialogs):
            width = CHOICE_COLUMNS if i in choices else TALK_COLUMNS
            over = over_width(text, width)
            if over:
                found.append(
                    {
                        "n": base + i + 1,
                        "width": width,
                        "over": over,
                        "text": text,
                        "fits": wrap_dialog(fit_font(text), width),
                    }
                )
        base += len(entry.sdl2.dialogs)
    return found


def audit_stem(stem: str, **roots: Path) -> list[tuple[Path, list[dict]]]:
    out: list[tuple[Path, list[dict]]] = []
    seen: set[bytes] = set()
    for pack in PACKS:
        path = shipped_path(pack, stem, **roots)
        if path is None:
            continue
        raw = path.read_bytes()
        if raw in seen:
            continue
        seen.add(raw)
        out.append((path, audit_file(path)))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stems", nargs="*", help="script ids such as a002 k007")
    parser.add_argument("--contrib", action="store_true", help="every stem under assets/script_contrib")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    stems = list(args.stems)
    if args.contrib:
        stems += sorted({p.stem for p in CONTRIB.glob("*/*.dbin2")} - set(stems))
    if not stems:
        parser.error("name at least one stem, or pass --contrib")
    total = 0
    for stem in stems:
        results = audit_stem(stem)
        if not results:
            print(f"[width] {stem}: no shipped script")
            continue
        for path, found in results:
            label = f"{path.parent.parent.name}/{path.parent.name}"
            if not found:
                print(f"[width] {stem} ({label}): ok")
                continue
            total += len(found)
            print(f"[width] {stem} ({label}): {len(found)} line(s) too wide")
            for hit in found:
                cols = ", ".join(f"line {n}: {c}" for n, c in hit["over"])
                kind = "choice" if hit["width"] == CHOICE_COLUMNS else "talk"
                print(f"  #{hit['n']} {kind} {hit['width']} max, {cols}")
                print("    now:  " + hit["text"].replace("\n", " / "))
                print("    fits as: " + hit["fits"].replace("\n", " / "))
    print(f"[width] {total} line(s) too wide")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
