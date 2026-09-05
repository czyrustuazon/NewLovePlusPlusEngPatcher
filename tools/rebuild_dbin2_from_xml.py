#!/usr/bin/env python3
"""Rebuild ``rebuild_dbin2/`` from NLPTextTool-compatible XML (``assets/scripts/``).

Uses ``src/patch_names.py`` DBIN2 encoder (NLPTextTool lineage). Dialog tokens such
as ``▲高嶺＊＊▲`` are preserved — no ``patch_names --strip-dialog-tokens``.

  python tools/rebuild_dbin2_from_xml.py
  python tools/rebuild_dbin2_from_xml.py --glob "t*.xml"
  python tools/rebuild_dbin2_from_xml.py --verify-only
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from patch_names import (  # noqa: E402
    DbinEntry,
    SDL2Data,
    SectionAEntry,
    UnknownEntry,
    build_dbin2,
    parse_dbin2,
)

DEFAULT_SCRIPTS = ROOT / "assets" / "scripts"
DEFAULT_OUT = ROOT / "rebuild_dbin2"
DEFAULT_VANILLA = ROOT.parent / "New Love Plus Plus" / "extracted" / "romfs" / "script" / "bin"
PACKS = ("script", "NLP_01", "NLP_02")

HERO_TOKEN = "▲高嶺＊＊▲"
PLAIN_TAKANE_RE = __import__("re").compile(r"(?<!▲)Takane(?!＊)")


@dataclass
class BuildResult:
    stem: str
    pack: str
    ok: bool
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    xml_tokens: int = 0
    dbin_tokens: int = 0


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _uint_attr(el: ET.Element, name: str) -> int:
    return int(el.attrib[name])


def xml_to_entries(path: Path) -> tuple[int, int, list[DbinEntry]]:
    root = ET.parse(path).getroot()
    if root.tag != "DBIN2":
        raise ValueError(f"{path.name}: root tag must be DBIN2, got {root.tag!r}")
    key = _uint_attr(root, "Key")
    unknown = _uint_attr(root, "Unknown")
    entries_el = root.find("Entries")
    if entries_el is None:
        raise ValueError(f"{path.name}: missing <Entries>")

    entries: list[DbinEntry] = []
    for entry_el in entries_el.findall("Entry"):
        unk0 = _uint_attr(entry_el, "Unknown0")
        unk1 = _uint_attr(entry_el, "Unknown1")
        sdl2_el = entry_el.find("SDL2")
        if sdl2_el is None:
            raise ValueError(f"{path.name}: entry missing <SDL2>")
        sdl2_key = _uint_attr(sdl2_el, "Key")

        unknown_entries: list[UnknownEntry] = []
        unknown_el = sdl2_el.find("Unknown")
        if unknown_el is not None:
            for unk_entry in unknown_el.findall("Entry"):
                values: list[SectionAEntry] = []
                values_el = unk_entry.find("Values")
                if values_el is not None:
                    for value_el in values_el.findall("Entry"):
                        values.append(
                            SectionAEntry(
                                int(_text(value_el.find("Value0")) or "0"),
                                int(_text(value_el.find("Value1")) or "0"),
                            )
                        )
                unknown_entries.append(
                    UnknownEntry(
                        values,
                        int(_text(unk_entry.find("Value0")) or "0"),
                        int(_text(unk_entry.find("Value1")) or "0"),
                    )
                )

        dialogs_el = sdl2_el.find("Dialogs")
        if dialogs_el is None:
            raise ValueError(f"{path.name}: SDL2 missing <Dialogs>")
        dialogs = [(d.text or "") for d in dialogs_el.findall("Dialog")]

        entries.append(DbinEntry(unk0, unk1, SDL2Data(sdl2_key, unknown_entries, dialogs)))
    return key, unknown, entries


def count_tokens_in_xml(path: Path) -> int:
    return path.read_text(encoding="utf-8").count(HERO_TOKEN)


def count_tokens_in_dbin(path: Path) -> int:
    _, _, entries = parse_dbin2(path.read_bytes())
    total = 0
    for entry in entries:
        for dialog in entry.sdl2.dialogs:
            total += dialog.count(HERO_TOKEN)
    return total


def packs_for_stem(stem: str, vanilla_bin: Path | None) -> list[str]:
    if vanilla_bin is None or not vanilla_bin.is_dir():
        return list(PACKS)
    out = []
    for pack in PACKS:
        if (vanilla_bin / pack / f"{stem}.dbin2").is_file():
            out.append(pack)
    return out or list(PACKS)


def build_one(
    xml_path: Path,
    out_root: Path,
    vanilla_bin: Path | None,
    *,
    verify: bool,
) -> list[BuildResult]:
    stem = xml_path.stem
    results: list[BuildResult] = []
    xml_tokens = count_tokens_in_xml(xml_path)
    try:
        key, unknown, entries = xml_to_entries(xml_path)
        blob = build_dbin2(key, unknown, entries)
    except (ET.ParseError, ValueError, KeyError) as exc:
        for pack in packs_for_stem(stem, vanilla_bin):
            results.append(BuildResult(stem, pack, False, str(exc)))
        return results

    for pack in packs_for_stem(stem, vanilla_bin):
        dest = out_root / pack / f"{stem}.dbin2"
        dest.parent.mkdir(parents=True, exist_ok=True)
        res = BuildResult(stem, pack, True, xml_tokens=xml_tokens)
        if verify and dest.is_file():
            old_tokens = count_tokens_in_dbin(dest)
            if old_tokens != xml_tokens:
                res.warnings.append(f"was dbin_tokens={old_tokens}")
        if not verify:
            dest.write_bytes(blob)
            res.dbin_tokens = count_tokens_in_dbin(dest)
            if res.dbin_tokens != xml_tokens:
                res.warnings.append(
                    f"token mismatch xml={xml_tokens} dbin={res.dbin_tokens}"
                )
        results.append(res)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scripts", type=Path, default=DEFAULT_SCRIPTS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--vanilla-bin", type=Path, default=DEFAULT_VANILLA)
    ap.add_argument("--glob", default="*.xml", help="script glob (default: all active xml)")
    ap.add_argument(
        "--verify-only",
        action="store_true",
        help="report token counts without writing dbin2",
    )
    args = ap.parse_args(argv)

    scripts_dir = args.scripts.resolve()
    out_root = args.out.resolve()
    vanilla = args.vanilla_bin.resolve() if args.vanilla_bin else None
    if not scripts_dir.is_dir():
        raise SystemExit(f"scripts dir missing: {scripts_dir}")

    xml_files = sorted(scripts_dir.glob(args.glob))
    if not xml_files:
        raise SystemExit(f"no files match {args.glob} in {scripts_dir}")

    all_results: list[BuildResult] = []
    for xml_path in xml_files:
        all_results.extend(
            build_one(xml_path, out_root, vanilla, verify=args.verify_only)
        )

    ok = sum(1 for r in all_results if r.ok)
    failed = [r for r in all_results if not r.ok]
    warned = [r for r in all_results if r.warnings]

    # XML-level token audit for Manaka scripts
    t_xml = sorted(scripts_dir.glob("t*.xml"))
    t_with_token = sum(1 for p in t_xml if HERO_TOKEN in p.read_text(encoding="utf-8"))
    t_plain = sum(
        1 for p in t_xml if PLAIN_TAKANE_RE.search(p.read_text(encoding="utf-8"))
    )

    print(
        f"[rebuild] {'verify' if args.verify_only else 'built'} "
        f"{len(xml_files)} xml -> {ok} dbin2 slot(s)"
    )
    print(f"[tokens] t* xml: {len(t_xml)} files, {t_with_token} with {HERO_TOKEN}, {t_plain} with plain Takane")
    if failed:
        print(f"[rebuild] FAILED {len(failed)}:")
        for r in failed[:10]:
            print(f"  {r.stem}/{r.pack}: {r.error}")
    if warned:
        print(f"[rebuild] warnings {len(warned)}:")
        for r in warned[:15]:
            print(f"  {r.stem}/{r.pack}: {', '.join(r.warnings)}")

    report = {
        "xml_files": len(xml_files),
        "dbin_slots": ok,
        "failed": len(failed),
        "warnings": len(warned),
        "t_with_hero_token": t_with_token,
        "t_with_plain_takane": t_plain,
        "verify_only": args.verify_only,
    }
    if not args.verify_only:
        (out_root / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
