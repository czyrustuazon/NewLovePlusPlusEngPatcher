#!/usr/bin/env python3
"""Small helper for New Love Plus+ English patch work."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
ASSETS = ROOT / "assets"
SCRIPTS = ASSETS / "scripts"
IMAGES = ASSETS / "images"
DEFAULT_OUT = ROOT / "out" / "patch"


def _safe_print(text: str) -> None:
    """Avoid Windows cp1252 crashes on Japanese dialog previews."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))

# Heuristic: leftover Japanese / untranslated placeholders in dialog lines.
JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
PLACEHOLDER_RE = re.compile(r"[○●…]{2,}|TODO|FIXME|MTL", re.I)


# Script inject policy (see script_inject.py): Manaka t* + p* + NLPPPATCH ~28%.
TRANSLATION_PREFIXES = frozenset({"t", "p"})


def iter_scripts() -> list[Path]:
    if not SCRIPTS.is_dir():
        return []
    return sorted(SCRIPTS.glob("*.xml"))


def cmd_status(_: argparse.Namespace) -> int:
    scripts = iter_scripts()
    pngs = list(IMAGES.rglob("*.png")) if IMAGES.is_dir() else []
    sources = []
    if IMAGES.is_dir():
        for ext in ("*.psd", "*.pdn", "*.xcf"):
            sources.extend(IMAGES.rglob(ext))
    by_prefix: dict[str, int] = {}
    for path in scripts:
        pref = path.stem[0].lower() if path.stem else "?"
        by_prefix[pref] = by_prefix.get(pref, 0) + 1
    manaka = by_prefix.get("t", 0)
    common = by_prefix.get("p", 0)
    nene = by_prefix.get("a", 0)
    rinko = by_prefix.get("k", 0)
    print(f"scripts (xml): {len(scripts)} in assets/scripts/")
    print(f"  t* Manaka:  {manaka}")
    print(f"  p* common:  {common}")
    print(f"  a* Nene:    {nene} (WIP if present - not gold-injected)")
    print(f"  k* Rinko:   {rinko} (WIP if present - not gold-injected)")
    print(f"Manaka layer: {manaka} t* from rebuild_dbin2 (overrides NLPPATCH)")
    try:
        from script_inject import coverage_summary, nlppatch_script_dir

        cov = coverage_summary()
        nlp = nlppatch_script_dir()
        print(f"NLPPPATCH vendor:    {nlp or '(missing — python tools/fetch_nlppatch_release.py)'}")
        print(
            f"script pack inject:  {cov['english_stems']}/{cov['total_stems']} EN "
            f"({cov['english_pct']}%) — nlppatch={cov['nlppatch']}, jp={cov['jp']}"
        )
    except ImportError:
        pass
    print(f"images (png):  {len(pngs)}")
    print(f"image sources: {len(sources)}  (psd/pdn/xcf, not used by build)")
    print(f"scripts dir:   {SCRIPTS}")
    print(f"images dir:    {IMAGES}")
    return 0


def _dialog_texts(path: Path) -> list[str]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"{path.name}: XML parse error: {exc}") from exc
    return [el.text or "" for el in root.iter("Dialog")]


def cmd_validate(_: argparse.Namespace) -> int:
    bad_xml = 0
    flagged = 0
    total_dialogs = 0

    for path in iter_scripts():
        if path.stem and path.stem[0].lower() not in TRANSLATION_PREFIXES:
            continue
        try:
            dialogs = _dialog_texts(path)
        except ValueError as exc:
            print(f"[xml] {exc}")
            bad_xml += 1
            continue

        total_dialogs += len(dialogs)
        hits = []
        for i, text in enumerate(dialogs, 1):
            reasons = []
            if JP_RE.search(text) and "▲" not in text:
                # Keep remaining control tokens (e.g. ▲主人公＊▲) out of the hard
                # fail list; heroine names are plain Takane/Rinko/Nene now.
                jp_chars = len(JP_RE.findall(text))
                if jp_chars >= 4:
                    reasons.append("japanese")
            if PLACEHOLDER_RE.search(text):
                reasons.append("placeholder")
            if reasons:
                hits.append((i, ",".join(reasons), text.replace("\n", "\\n")[:80]))

        if hits:
            flagged += 1
            _safe_print(f"[review] {path.name} ({len(hits)} line(s))")
            for idx, reason, preview in hits[:8]:
                _safe_print(f"  #{idx} ({reason}): {preview}")
            if len(hits) > 8:
                print(f"  ... +{len(hits) - 8} more")

    en_scripts = [
        p for p in iter_scripts()
        if p.stem and p.stem[0].lower() in TRANSLATION_PREFIXES
    ]
    print()
    print(f"checked scripts: {len(en_scripts)} (t*/p* only; k*/a* out of scope)")
    print(f"dialog lines:    {total_dialogs}")
    print(f"xml errors:      {bad_xml}")
    print(f"scripts flagged: {flagged}")
    return 1 if bad_xml else 0


def cmd_dialogs(args: argparse.Namespace) -> int:
    paths = iter_scripts()
    if args.script:
        name = args.script if args.script.endswith(".xml") else f"{args.script}.xml"
        paths = [SCRIPTS / name]
        if not paths[0].is_file():
            print(f"missing script: {paths[0]}", file=sys.stderr)
            return 1

    lines: list[str] = []
    for path in paths:
        try:
            dialogs = _dialog_texts(path)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        lines.append(f"===== {path.name} ({len(dialogs)} dialogs) =====")
        for i, text in enumerate(dialogs, 1):
            flat = text.replace("\r\n", "\n").replace("\r", "\n")
            lines.append(f"{i:04d}|{flat}")
        lines.append("")

    out = "\n".join(lines)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out, encoding="utf-8")
        print(f"wrote {out_path}")
    else:
        print(out)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    out = Path(args.out)
    scripts_out = out / "scripts"
    images_out = out / "images"

    if out.exists() and args.clean:
        shutil.rmtree(out)
    scripts_out.mkdir(parents=True, exist_ok=True)
    images_out.mkdir(parents=True, exist_ok=True)

    script_count = 0
    for src in iter_scripts():
        shutil.copy2(src, scripts_out / src.name)
        script_count += 1

    image_count = 0
    if IMAGES.is_dir():
        for src in IMAGES.rglob("*.png"):
            rel = src.relative_to(IMAGES)
            dest = images_out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            image_count += 1

    manifest = out / "MANIFEST.txt"
    manifest.write_text(
        "\n".join(
            [
                "New Love Plus+ English patch package",
                f"scripts: {script_count}",
                f"images:  {image_count}",
                "",
                "Next step: pack these into the game containers (DBIN/ARC)",
                "using your usual NLPP packing toolchain, then install on device.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"built package -> {out}")
    print(f"  scripts: {script_count}")
    print(f"  images:  {image_count}")
    print(f"  manifest:{manifest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="patcher",
        description="Organize and check finished English patch assets for New Love Plus+.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="Count finished scripts/images")
    s.set_defaults(func=cmd_status)

    v = sub.add_parser("validate", help="XML parse + quick untranslated heuristics")
    v.set_defaults(func=cmd_validate)

    d = sub.add_parser("dialogs", help="Dump <Dialog> lines for review")
    d.add_argument("--script", help="Single script name, e.g. a002 or a002.xml")
    d.add_argument("--out", help="Write to file instead of stdout")
    d.set_defaults(func=cmd_dialogs)

    b = sub.add_parser("build", help="Copy game-ready assets into an output folder")
    b.add_argument("--out", default=str(DEFAULT_OUT), help=f"Output dir (default: {DEFAULT_OUT})")
    b.add_argument("--clean", action="store_true", help="Delete output dir before building")
    b.set_defaults(func=cmd_build)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not ASSETS.is_dir():
        print(f"missing assets folder: {ASSETS}", file=sys.stderr)
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
