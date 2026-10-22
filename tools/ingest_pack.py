#!/usr/bin/env python3
"""Apply a volunteer Scripts pack (``nlpp-contrib`` JSON) onto EngPatcher dialogue.

Dry-run by default. ``--apply`` writes only the lines a volunteer changed, and
only where the repo line is still the Japanese baseline they edited. A line
that already differs (an existing English script) is reported and left alone
unless ``--force``.

A stem that Gemini already translated is not written back onto the Gemini
files or onto ``rebuild_dbin2``. The merged script goes to
``assets/script_contrib/``, which the patcher ships on its own.

  python tools/ingest_pack.py path/to/nlpp-contrib.json
  python tools/ingest_pack.py path/to/nlpp-contrib.json --apply

Nickname tokens (``▲…▲``, including an unclosed ``▲``) must keep the same
multiset as the baseline. A drop in ``※`` or ``▼`` is rejected. A ``●`` count
change is a warning. Circle and punctuation placeholders are locked.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from patch_names import build_dbin2, parse_dbin2  # noqa: E402
from rebuild_dbin2_from_xml import entries_to_xml, xml_to_entries  # noqa: E402

SCHEMA = 1
PACK_KIND = "nlpp-contrib"
STEM_RE = re.compile(r"^[aktp]\d{3}$")
TOKEN_RE = re.compile(r"▲[^▲]*▲|▲[^▲]*")
LOCKED_RE = re.compile(r"^[○〇\s。、．.・ー！？!?…,，]+$")
DIALOG_RE = re.compile(r"<Dialog>(.*?)</Dialog>", re.DOTALL)
PACK_ORDER = ("script", "NLP_01", "NLP_02")
DEFAULT_CONTRIB = ROOT / "assets" / "script_contrib"
DEFAULT_GEMINI = ROOT / "assets" / "gemini_heroines"


class IngestError(Exception):
    """The pack itself cannot be read or is the wrong kind."""


@dataclass
class LineDecision:
    index: int
    action: str
    baseline: str
    current: str
    proposed: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class ItemPlan:
    stem: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    decisions: list[LineDecision] = field(default_factory=list)
    skipped: str = ""
    xml_path: Path | None = None
    dbin_paths: list[Path] = field(default_factory=list)
    shells: list[Path] = field(default_factory=list)
    source_xml: Path | None = None
    dest_scripts: Path | None = None
    dest_dbin_root: Path | None = None
    separate: bool = False
    current: list[str] = field(default_factory=list)
    proposed: list[str] = field(default_factory=list)

    @property
    def applied(self) -> list[LineDecision]:
        return [d for d in self.decisions if d.action == "apply"]


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _tokens(dialogs: list[str]) -> Counter[str]:
    bag: Counter[str] = Counter()
    for dialog in dialogs:
        bag.update(TOKEN_RE.findall(dialog))
    return bag


def _mark_count(dialogs: list[str], mark: str) -> int:
    return sum(dialog.count(mark) for dialog in dialogs)


def _trailing_newlines(text: str) -> int:
    count = 0
    while text.endswith("\n"):
        count += 1
        text = text[:-1]
    return count


def _as_dialogs(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise IngestError(f"{label} must be a list of strings")
    return [_norm(item) for item in value]


def load_pack(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IngestError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise IngestError("pack root must be an object")
    if data.get("schema") != SCHEMA:
        raise IngestError(f"schema must be {SCHEMA}, got {data.get('schema')!r}")
    if data.get("kind") != PACK_KIND:
        raise IngestError(
            f"kind must be {PACK_KIND!r} (this tool is the Scripts pack), "
            f"got {data.get('kind')!r}"
        )
    items = data.get("items")
    if not isinstance(items, list):
        raise IngestError("items must be a list")
    return data


def _xml_dialogs(path: Path) -> list[str]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise IngestError(f"{path.name}: XML parse error: {exc}") from exc
    return [_norm(el.text or "") for el in root.iter("Dialog")]


def _dbin_dialogs(path: Path) -> list[str]:
    try:
        _, _, entries = parse_dbin2(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise IngestError(f"{path}: {exc}") from exc
    return [_norm(dialog) for entry in entries for dialog in entry.sdl2.dialogs]


def _dbin_paths(dbin_root: Path, stem: str) -> list[Path]:
    found: list[Path] = []
    for pack in PACK_ORDER:
        path = dbin_root / pack / f"{stem}.dbin2"
        if path.is_file():
            found.append(path)
    if dbin_root.is_dir():
        for path in sorted(dbin_root.glob(f"*/{stem}.dbin2")):
            if path not in found:
                found.append(path)
    return found


def _validate_pair(baseline: list[str], proposed: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if len(baseline) != len(proposed):
        errors.append(
            f"dialog count {len(proposed)} != baseline {len(baseline)}"
        )
        return errors, warnings
    base_tokens = _tokens(baseline)
    new_tokens = _tokens(proposed)
    if base_tokens != new_tokens:
        missing = base_tokens - new_tokens
        extra = new_tokens - base_tokens
        errors.append(
            "nickname token multiset changed"
            + (f" missing {dict(missing)}" if missing else "")
            + (f" extra {dict(extra)}" if extra else "")
        )
    for mark in ("※", "▼"):
        old = _mark_count(baseline, mark)
        new = _mark_count(proposed, mark)
        if new < old:
            errors.append(f"{mark} count dropped {old} -> {new}")
        elif new > old:
            warnings.append(f"{mark} count rose {old} -> {new}")
    old_bullets = _mark_count(baseline, "●")
    new_bullets = _mark_count(proposed, "●")
    if old_bullets != new_bullets:
        warnings.append(f"● count {old_bullets} -> {new_bullets}")
    for index, (old, new) in enumerate(zip(baseline, proposed)):
        if old != new and LOCKED_RE.fullmatch(old):
            errors.append(f"line {index} is a locked placeholder")
    return errors, warnings


def _line_warnings(baseline: str, proposed: str) -> list[str]:
    warnings: list[str] = []
    if _trailing_newlines(proposed) > _trailing_newlines(baseline):
        warnings.append("trailing blank line")
    return warnings


def gemini_translated(stem: str, gemini_root: Path) -> bool:
    """True when this Gemini tree already has a machine translation of ``stem``."""
    manifest = gemini_root / "stems.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if stem in {str(item) for item in data.get("stems", [])}:
                return True
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
            pass
    if (gemini_root / "xml" / f"{stem}.xml").is_file():
        return True
    return bool(_dbin_paths(gemini_root / "dbin2", stem))


def _tree(
    xml: Path, dbin_root: Path, stem: str
) -> tuple[list[str], Path | None, list[Path], list[Path]] | None:
    """Dialogs, the XML they came from, matching dbins, and dbins that disagree."""
    dbins = _dbin_paths(dbin_root, stem)
    if xml.is_file():
        current = _xml_dialogs(xml)
        xml_used: Path | None = xml
    elif dbins:
        current = _dbin_dialogs(dbins[0])
        xml_used = None
    else:
        return None
    match: list[Path] = []
    bad: list[Path] = []
    for path in dbins:
        if _dbin_dialogs(path) == current:
            match.append(path)
        else:
            bad.append(path)
    return current, xml_used, match, bad


def _note_mismatch(plan: ItemPlan, bad: list[Path], xml_used: Path | None) -> None:
    for path in bad:
        plan.errors.append(
            f"{path.name} in {path.parent.name} does not match the "
            f"{'XML' if xml_used else 'script-pack'} dialogs"
        )


def _decide(plan: ItemPlan, baseline: list[str], proposed: list[str], current: list[str], *, force: bool) -> None:
    if len(current) != len(baseline):
        plan.errors.append(
            f"repo dialog count {len(current)} != baseline {len(baseline)}"
        )
        return
    plan.current = current
    plan.proposed = proposed
    for index, (old, new, live) in enumerate(zip(baseline, proposed, current)):
        if old == new:
            continue
        warnings = _line_warnings(old, new)
        if live == new:
            action = "already"
        elif live == old or force:
            action = "apply"
        else:
            action = "conflict"
        plan.decisions.append(
            LineDecision(index, action, old, live, new, warnings)
        )


def plan_item(
    item: object,
    *,
    scripts_dir: Path,
    dbin_root: Path,
    force: bool,
    contrib_root: Path = DEFAULT_CONTRIB,
    gemini_root: Path = DEFAULT_GEMINI,
) -> ItemPlan:
    if not isinstance(item, dict):
        plan = ItemPlan(stem="?")
        plan.errors.append("item is not an object")
        return plan
    stem = str(item.get("stem") or "")
    plan = ItemPlan(stem=stem)
    if item.get("kind") not in (None, "script"):
        plan.errors.append(f"item kind must be 'script', got {item.get('kind')!r}")
        return plan
    if not STEM_RE.fullmatch(stem):
        plan.errors.append(f"stem {stem!r} is not an a/k/t/p script id")
        return plan
    if item.get("dirty") is False:
        plan.skipped = "not dirty"
        return plan
    try:
        baseline = _as_dialogs(item.get("baseline_dialogs"), f"{stem} baseline_dialogs")
        proposed = _as_dialogs(item.get("dialogs"), f"{stem} dialogs")
    except IngestError as exc:
        plan.errors.append(str(exc))
        return plan

    errors, warnings = _validate_pair(baseline, proposed)
    plan.errors.extend(errors)
    plan.warnings.extend(warnings)
    if plan.errors:
        return plan

    xml_path = scripts_dir / f"{stem}.xml"
    dbins = _dbin_paths(dbin_root, stem)
    separate = gemini_translated(stem, gemini_root)
    plan.separate = separate
    contrib_xml = contrib_root / "xml" / f"{stem}.xml"
    contrib_dbin = contrib_root / "dbin2"

    if separate:
        plan.dest_scripts = contrib_root / "xml"
        plan.dest_dbin_root = contrib_dbin
        try:
            existing = _tree(contrib_xml, contrib_dbin, stem)
            branched = None
            if existing is None:
                branched = _tree(xml_path, dbin_root, stem)
                if branched is None:
                    branched = _tree(
                        gemini_root / "xml" / f"{stem}.xml",
                        gemini_root / "dbin2",
                        stem,
                    )
        except IngestError as exc:
            plan.errors.append(str(exc))
            return plan
        if existing is not None:
            current, xml_used, match, bad = existing
            _note_mismatch(plan, bad, xml_used)
            if plan.errors:
                return plan
            plan.xml_path = xml_used
            plan.dbin_paths = match
        else:
            if branched is None:
                plan.errors.append(
                    f"no {stem} script under {scripts_dir}, {dbin_root}, or {gemini_root}"
                )
                return plan
            current, xml_used, match, bad = branched
            _note_mismatch(plan, bad, xml_used)
            if plan.errors:
                return plan
            try:
                for path in _dbin_paths(gemini_root / "dbin2", stem):
                    if path not in match and _dbin_dialogs(path) == current:
                        match.append(path)
            except IngestError as exc:
                plan.errors.append(str(exc))
                return plan
            plan.shells = match
            plan.source_xml = xml_used if not match else None
            if not match and xml_used is None:
                plan.errors.append(f"no {stem} dialog shell to copy")
                return plan
    else:
        plan.dest_scripts = scripts_dir
        plan.dest_dbin_root = dbin_root
        if xml_path.is_file():
            plan.xml_path = xml_path
            try:
                current = _xml_dialogs(xml_path)
            except IngestError as exc:
                plan.errors.append(str(exc))
                return plan
        elif dbins:
            try:
                current = _dbin_dialogs(dbins[0])
            except IngestError as exc:
                plan.errors.append(str(exc))
                return plan
        else:
            plan.errors.append(f"no {xml_path.name} and no {stem}.dbin2 under {dbin_root}")
            return plan
        try:
            _note_mismatch(plan, [path for path in dbins if _dbin_dialogs(path) != current], plan.xml_path)
        except IngestError as exc:
            plan.errors.append(str(exc))
            return plan
        if plan.errors:
            return plan
        plan.dbin_paths = [path for path in dbins if _dbin_dialogs(path) == current]

    _decide(plan, baseline, proposed, current, force=force)
    return plan


def _escape_dialog(text: str) -> str:
    if "</Dialog>" in text or "<Dialog" in text:
        raise IngestError("dialog text contains a Dialog tag")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _write_xml_dialogs(path: Path, proposed: list[str]) -> None:
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8")
    matches = list(DIALOG_RE.finditer(text))
    if len(matches) != len(proposed):
        raise IngestError(
            f"{path.name}: found {len(matches)} <Dialog> tags, expected {len(proposed)}"
        )
    pieces: list[str] = []
    cursor = 0
    for match, new in zip(matches, proposed):
        pieces.append(text[cursor : match.start(1)])
        old = _norm(match.group(1))
        if old == new:
            pieces.append(match.group(1))
        else:
            pieces.append(_escape_dialog(new).replace("\n", newline))
        cursor = match.end(1)
    pieces.append(text[cursor:])
    path.write_bytes("".join(pieces).encode("utf-8"))


def _write_dbin_dialogs(
    path: Path, proposed: list[str], dest: Path | None = None
) -> None:
    data = path.read_bytes()
    key, unknown, entries = parse_dbin2(data)
    flat_index = 0
    for entry in entries:
        count = len(entry.sdl2.dialogs)
        entry.sdl2.dialogs = proposed[flat_index : flat_index + count]
        flat_index += count
    if flat_index != len(proposed):
        raise IngestError(f"{path.name}: dialog count changed while writing")
    out = dest or path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_dbin2(key, unknown, entries))


def _write_new_xml(path: Path, dbin_path: Path, proposed: list[str]) -> None:
    key, unknown, entries = parse_dbin2(dbin_path.read_bytes())
    flat_index = 0
    for entry in entries:
        count = len(entry.sdl2.dialogs)
        entry.sdl2.dialogs = proposed[flat_index : flat_index + count]
        flat_index += count
    text = entries_to_xml(key, unknown, entries).replace("\n", "\r\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _write_new_dbin(path: Path, xml_path: Path) -> None:
    key, unknown, entries = xml_to_entries(xml_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_dbin2(key, unknown, entries))


def apply_plan(plan: ItemPlan) -> list[Path]:
    """Write one planned item. Returns paths written.

    Gemini stems land under ``plan.dest_scripts`` / ``plan.dest_dbin_root``
    and do not modify the Gemini archive or ``rebuild_dbin2``.
    """
    if not plan.applied:
        return []
    written: list[Path] = []
    merged = list(plan.current)
    for decision in plan.applied:
        merged[decision.index] = decision.proposed

    if (
        plan.source_xml is not None
        and plan.dest_scripts is not None
        and not plan.shells
        and not plan.dbin_paths
    ):
        dest_xml = plan.dest_scripts / f"{plan.stem}.xml"
        dest_xml.parent.mkdir(parents=True, exist_ok=True)
        if not dest_xml.exists():
            dest_xml.write_bytes(plan.source_xml.read_bytes())
        _write_xml_dialogs(dest_xml, merged)
        written.append(dest_xml)
        if plan.dest_dbin_root is not None:
            dest = plan.dest_dbin_root / "script" / f"{plan.stem}.dbin2"
            _write_new_dbin(dest, dest_xml)
            written.append(dest)

    if plan.xml_path is not None:
        _write_xml_dialogs(plan.xml_path, merged)
        written.append(plan.xml_path)
    if plan.dbin_paths:
        for path in plan.dbin_paths:
            _write_dbin_dialogs(path, merged)
            written.append(path)
    elif (
        plan.xml_path is not None
        and plan.dest_dbin_root is not None
        and not plan.shells
    ):
        dest = plan.dest_dbin_root / "script" / f"{plan.stem}.dbin2"
        _write_new_dbin(dest, plan.xml_path)
        written.append(dest)

    if plan.shells and plan.dest_dbin_root is not None:
        for shell in plan.shells:
            dest = plan.dest_dbin_root / shell.parent.name / f"{plan.stem}.dbin2"
            _write_dbin_dialogs(shell, merged, dest)
            written.append(dest)
        if (
            plan.xml_path is None
            and plan.source_xml is None
            and plan.dest_scripts is not None
        ):
            dest_xml = plan.dest_scripts / f"{plan.stem}.xml"
            _write_new_xml(dest_xml, plan.shells[0], merged)
            written.append(dest_xml)

    if (
        plan.xml_path is None
        and plan.source_xml is None
        and not plan.shells
        and plan.dbin_paths
        and plan.dest_scripts is not None
    ):
        dest_xml = plan.dest_scripts / f"{plan.stem}.xml"
        if not dest_xml.exists():
            _write_new_xml(dest_xml, plan.dbin_paths[0], merged)
            written.append(dest_xml)
    return written


def _short(text: str, limit: int = 72) -> str:
    flat = text.replace("\n", "\\n")
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3] + "..."


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _print_plan(plan: ItemPlan) -> None:
    if plan.skipped:
        print(f"[ingest] {plan.stem}: skipped ({plan.skipped})")
        return
    if plan.errors:
        print(f"[ingest] {plan.stem}: rejected")
        for error in plan.errors:
            print(f"  error: {error}")
        return
    if plan.separate:
        print(
            f"[ingest] {plan.stem}: Gemini translation — "
            f"separate file under {plan.dest_dbin_root.parent if plan.dest_dbin_root else 'script_contrib'}"
        )
    counts = Counter(decision.action for decision in plan.decisions)
    print(
        f"[ingest] {plan.stem}: {len(plan.decisions)} edited, "
        f"apply {counts['apply']}, already {counts['already']}, "
        f"conflict {counts['conflict']}"
    )
    for warning in plan.warnings:
        print(f"  warn: {warning}")
    visible = [decision for decision in plan.decisions if decision.action != "already"]
    for shown, decision in enumerate(visible):
        if shown >= 40:
            print(f"  ... {len(visible) - shown} more")
            break
        suffix = ""
        if decision.warnings:
            suffix = " (" + "; ".join(decision.warnings) + ")"
        print(
            f"  {decision.action} #{decision.index}{suffix}: "
            f"{_short(decision.proposed)}"
        )
        if decision.action == "conflict":
            print(f"    repo: {_short(decision.current)}")


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path, help="nlpp-contrib JSON from the Scripts workbench")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write matching lines (default is a dry-run report)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="also replace lines whose repo text already differs from the baseline",
    )
    parser.add_argument("--scripts", type=Path, default=ROOT / "assets" / "scripts")
    parser.add_argument("--dbin-root", type=Path, default=ROOT / "rebuild_dbin2")
    parser.add_argument(
        "--contrib-root",
        type=Path,
        default=DEFAULT_CONTRIB,
        help="where a Gemini stem's review is written (default: assets/script_contrib)",
    )
    parser.add_argument(
        "--gemini-root",
        type=Path,
        default=DEFAULT_GEMINI,
        help="Gemini archive used to decide which stems stay untouched",
    )
    args = parser.parse_args(argv)

    try:
        pack = load_pack(args.pack)
    except IngestError as exc:
        print(f"[ingest] {exc}")
        return 1

    author = str(pack.get("author") or "").strip() or "(none)"
    print(f"[ingest] {PACK_KIND} schema {SCHEMA} author {author}")
    note = str(pack.get("note") or "").strip()
    if note:
        print(f"[ingest] note: {_short(note, 120)}")

    plans = [
        plan_item(
            item,
            scripts_dir=args.scripts,
            dbin_root=args.dbin_root,
            force=args.force,
            contrib_root=args.contrib_root,
            gemini_root=args.gemini_root,
        )
        for item in pack["items"]
    ]
    if not plans:
        print("[ingest] no items")
        return 0

    for plan in plans:
        _print_plan(plan)

    errors = [plan for plan in plans if plan.errors]
    if errors:
        print(f"[ingest] rejected {len(errors)} item(s); nothing written")
        return 1

    writable = [plan for plan in plans if plan.applied]
    if not args.apply:
        print("[ingest] dry-run (pass --apply to write)")
        return 0
    if not writable:
        print("[ingest] nothing to write")
        return 0

    written: list[Path] = []
    try:
        for plan in writable:
            written.extend(apply_plan(plan))
    except (IngestError, OSError, ValueError, ET.ParseError) as exc:
        print(f"[ingest] write failed: {exc}")
        return 1
    for path in written:
        try:
            shown = path.relative_to(ROOT)
        except ValueError:
            shown = path
        print(f"[ingest] wrote {shown.as_posix()}")
    print(
        "[ingest] review the script diff, then rebuild the bake / CIA. "
        "This command does not bake."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
