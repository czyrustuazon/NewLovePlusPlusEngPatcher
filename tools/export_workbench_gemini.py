#!/usr/bin/env python3
"""Attach Gemini translations to the volunteer workbench kits.

Japanese ``baseline_dialogs`` / ``baseline`` stay put. Gemini is added beside
them (``gemini_dialogs`` on scripts, ``gemini`` on SMS). Save progress still
exports ``baseline`` plus the edited text, which ``ingest_pack.py`` can apply
onto a Gemini stem without treating the machine pass as a conflict.

  python tools/export_workbench_gemini.py
  python tools/export_workbench_gemini.py --workbench path/to/nlpp-localization-workbench
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKBENCH = ROOT.parent / "nlpp-localization-workbench"
GEMINI = ROOT / "assets" / "gemini_heroines"
DIALOG_RE = re.compile(r"<Dialog>(.*?)</Dialog>", re.DOTALL)

SMS_FILES = {
    "manaka": "maildic_m.en.xml",
    "nene": "maildic_n.en.xml",
    "rinko": "maildic_r.en.xml",
}


def _unescape_dialog(raw: str) -> str:
    return (
        raw.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def script_dialogs(path: Path) -> list[str]:
    """Dialog strings in file order. Regex keeps the same count as the kit."""
    text = path.read_text(encoding="utf-8")
    return [_unescape_dialog(match.group(1)) for match in DIALOG_RE.finditer(text)]


def sms_map(path: Path) -> dict[str, str]:
    tree = ET.parse(path)
    out: dict[str, str] = {}
    for entry in tree.getroot().findall("Entry"):
        node = entry.find("JapaneseText")
        if node is None:
            continue
        hex_key = (node.get("hex") or "").lower()
        if hex_key:
            out[hex_key] = node.text or ""
    return out


def _embed(html: str, element_id: str) -> tuple[str, dict, str]:
    marker = f'id="{element_id}">'
    start = html.find(marker)
    if start < 0:
        raise SystemExit(f"missing embedded JSON #{element_id}")
    start += len(marker)
    end = html.find("</script>", start)
    if end < 0:
        raise SystemExit(f"unclosed script for #{element_id}")
    data = json.loads(html[start:end])
    return html[:start], data, html[end:]


def _dump(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Keep a dialog that mentions the tag from closing the embed early.
    return raw.replace("<", "\\u003c")


def attach_scripts(data: dict, xml_dir: Path) -> dict[str, int]:
    attached = skipped = 0
    for item in data.get("items") or []:
        if item.get("kind") != "script":
            continue
        baseline = item.get("baseline_dialogs")
        path = xml_dir / f"{item.get('stem')}.xml"
        if not isinstance(baseline, list) or not path.is_file():
            item.pop("gemini_dialogs", None)
            skipped += 1
            continue
        gemini = script_dialogs(path)
        if len(gemini) != len(baseline):
            item.pop("gemini_dialogs", None)
            skipped += 1
            continue
        item["gemini_dialogs"] = gemini
        # Save progress reads baseline_dialogs. Leave the Japanese list alone.
        attached += 1
    stats = data.setdefault("stats", {})
    if isinstance(stats, dict):
        stats["gemini_scripts"] = attached
    return {"scripts": attached, "scripts_skipped": skipped}


def attach_sms(data: dict, sms_dir: Path) -> dict[str, int]:
    maps = {
        heroine: sms_map(sms_dir / name)
        for heroine, name in SMS_FILES.items()
        if (sms_dir / name).is_file()
    }
    attached = 0
    for item in data.get("items") or []:
        if item.get("kind") != "sms":
            continue
        key = str(item.get("key") or "").lower().removeprefix("0x")
        gemini = maps.get(item.get("heroine"), {}).get(key)
        if gemini is None:
            item.pop("gemini", None)
            continue
        item["gemini"] = gemini
        attached += 1
    stats = data.setdefault("stats", {})
    if isinstance(stats, dict):
        stats["gemini_sms"] = attached
    return {"sms": attached}


def write_embed(path: Path, element_id: str, mutate) -> dict[str, int]:
    html = path.read_text(encoding="utf-8")
    head, data, tail = _embed(html, element_id)
    counts = mutate(data)
    path.write_text(head + _dump(data) + tail, encoding="utf-8", newline="\n")
    return counts


def export_gemini(workbench: Path, gemini_root: Path = GEMINI) -> dict[str, int]:
    kit = workbench / "kit"
    counts = write_embed(
        kit / "NLPP_Translate.html",
        "embedded-workkit",
        lambda data: attach_scripts(data, gemini_root / "xml"),
    )
    counts.update(
        write_embed(
            kit / "NLPP_Translate_Strings.html",
            "embedded-strings",
            lambda data: attach_sms(data, gemini_root / "sms"),
        )
    )
    return counts


META_RE = re.compile(
    r'(<meta\s+name="nlpp-workbench-build"\s+content=")(\d+)(")',
    re.IGNORECASE,
)
PAGES = (
    "index.html",
    "kit/NLPP_Translate.html",
    "kit/NLPP_Translate_Strings.html",
    "kit/NLPP_Translate_Images/index.html",
)


def read_build(workbench: Path) -> int:
    path = workbench / "version.json"
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return 0
    try:
        return int(data.get("build") or 0)
    except (TypeError, ValueError):
        return 0


def stamp_build(workbench: Path, build: int) -> None:
    """Publish ``build`` so an open older page locks until refresh."""
    note = (
        "Gemini lines sit beside the Japanese. "
        "A newer build locks the open page until refresh."
    )
    (workbench / "version.json").write_text(
        json.dumps({"build": build, "note": note}, indent=2) + "\n",
        encoding="utf-8",
    )
    meta = f'<meta charset="utf-8" />\n  <meta name="nlpp-workbench-build" content="{build}" />'
    for rel in PAGES:
        page = workbench / rel
        if not page.is_file():
            continue
        text = page.read_text(encoding="utf-8")
        if META_RE.search(text):
            text = META_RE.sub(rf"\g<1>{build}\g<3>", text, count=1)
        else:
            text = text.replace('<meta charset="utf-8" />', meta, 1)
        page.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbench", type=Path, default=DEFAULT_WORKBENCH)
    parser.add_argument("--gemini-root", type=Path, default=GEMINI)
    args = parser.parse_args(argv)
    counts = export_gemini(args.workbench, args.gemini_root)
    build = read_build(args.workbench) + 1
    stamp_build(args.workbench, build)
    print(
        "[workbench] gemini attached "
        + " ".join(f"{key}={value}" for key, value in counts.items())
        + f" build={build}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
