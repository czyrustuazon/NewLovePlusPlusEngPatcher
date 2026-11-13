#!/usr/bin/env python3
"""Rebuild the volunteer workbench from the patcher.

The patcher is the source of truth.

* Script baselines are the current vanilla Japanese, when that file has the
  same number of lines as the text the patcher ships.
* The edit box is that shipped text: ``assets/script_contrib`` when a stem
  has a review, otherwise Gemini ``dbin2`` for an ``a*`` / ``k*`` stem that
  has one (the Drop opt-in), otherwise ``rebuild_dbin2``. A stem listed in
  ``proofread.json`` is done. Any other contributor file still needs a look
  on lines that match the Gemini pass, and on indexes in
  ``assets/script_contrib/unreviewed.json`` (an agent rewrote the machine
  line; that is not a proofread).
* Gemini XML is rewritten to that same ``dbin2`` when the line counts match,
  and the Gemini translation map is updated for those lines.
* TRB rows whose Japanese is already a key in ``translations.json`` are
  removed. A truncated workbench string is replaced with the full vanilla
  STRI text. SMS rows stay; their Gemini text is already the patcher file.
* The images kit stays removed.

  python tools/sync_workbench.py
  python tools/sync_workbench.py --workbench path/to/nlpp-localization-workbench
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from export_workbench_gemini import (  # noqa: E402
    stamp_build,
    write_embed,
)
from ingest_pack import (  # noqa: E402
    _dbin_dialogs,
    _norm,
    _write_xml_dialogs,
    _xml_dialogs,
)
from nlpp_paths import find_vanilla_main_trb, find_vanilla_script_dir  # noqa: E402
from patch_names import parse_dbin2  # noqa: E402
from rebuild_dbin2_from_xml import entries_to_xml  # noqa: E402
from script_inject import DEFAULT_ENG_DBIN, resolve_script_source  # noqa: E402

DEFAULT_WORKBENCH = ROOT.parent / "nlpp-localization-workbench"
GEMINI = ROOT / "assets" / "gemini_heroines"
TRANSLATIONS = ROOT / "assets" / "textresource" / "translations.json"

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
JP_IGNORABLE_RE = re.compile(r"[ー・]")
TOKEN_RE = re.compile(r"▲[^▲]+▲")
NAME_TOKEN_RE = re.compile(r"▲[^▲\n]*＊+[^▲\n]*(?:▲|[！!？?…]*)")
PUNCT_RE = re.compile(
    r"^[\s.。．…‥!！?？、,，~～ー−–—ｰ\-・･'\"`「」『』()（）【】[\]▼▲♪♡♥★☆…]+$"
)
CIRCLE_RE = re.compile(r"^[○●◯〇\s]+$")
STRING_PUNCT_RE = re.compile(
    r"^[\s.。．…‥!！?？、,，~～ー−–—ｰ\-・･'\"`「」『』()（）【】[\]▼▲♪♡♥★☆…]+$"
)


def has_jp(text: str) -> bool:
    return bool(JP_RE.search(JP_IGNORABLE_RE.sub("", text or "")))


def text_without_tokens(text: str) -> str:
    return TOKEN_RE.sub("", NAME_TOKEN_RE.sub("", text or ""))


def is_punct_only(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and bool(PUNCT_RE.fullmatch(stripped))


def is_token_only(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or "▲" not in stripped:
        return False
    if not NAME_TOKEN_RE.search(stripped) and not TOKEN_RE.search(stripped):
        return False
    rest = text_without_tokens(stripped).replace("▲", "")
    rest = re.sub(
        r"[\s.。．…‥!！?？、,，~～ー−–—ｰ\-・･'\"「」『』()（）【】[\]▼]+",
        " ",
        rest,
    ).strip()
    if not rest:
        return True
    return all(re.fullmatch(r"[A-Za-z]{1,12}", word) for word in rest.split())


def is_locked(text: str) -> bool:
    stripped = (text or "").strip()
    return (
        is_token_only(text)
        or bool(stripped and CIRCLE_RE.fullmatch(stripped))
        or is_punct_only(text)
    )


def needs_translation(text: str) -> bool:
    """Scripts-kit rule: Japanese outside tokens, placeholders, and punctuation."""
    if is_locked(text):
        return False
    if is_punct_only(text_without_tokens(text)):
        return False
    return has_jp(text_without_tokens(text))


def string_needs_translation(text: str) -> bool:
    """Strings-kit rule. Punctuation-only lines are finished."""
    if is_punct_only_string(text):
        return False
    return has_jp(text)


def is_punct_only_string(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and bool(STRING_PUNCT_RE.fullmatch(stripped))


def tokens_in(text: str) -> list[str]:
    names = NAME_TOKEN_RE.findall(text or "")
    rest = NAME_TOKEN_RE.sub("", text or "")
    return names + TOKEN_RE.findall(rest)


def safe_suggestion(jp: str, en: str) -> bool:
    if is_locked(jp):
        return False
    if tokens_in(jp) != tokens_in(en):
        return False
    for mark in ("※", "▼"):
        if en.count(mark) < jp.count(mark):
            return False
    return True


def seeded_dialogs(baseline: list[str], gemini: list[str] | None) -> list[str]:
    """Edit box the Scripts page builds when ``dialogs`` is absent."""
    dialogs = list(baseline)
    if gemini is not None and len(gemini) == len(baseline):
        for index, (jp, en) in enumerate(zip(baseline, gemini)):
            if safe_suggestion(jp, en):
                dialogs[index] = en
    return dialogs


def fill_script_item(
    item: dict,
    *,
    vanilla: list[str] | None,
    working: list[str],
    gemini: list[str] | None,
    layer: str,
    unreviewed: list[int] | None = None,
) -> dict:
    """Point one kit script at the patcher.

    ``working`` is the text the patcher ships for this stem. ``vanilla`` is
    the Japanese reference when it has the same line count.
    """
    if vanilla is not None and len(vanilla) == len(working):
        baseline = list(vanilla)
    else:
        baseline = list(working)
    item["baseline_dialogs"] = baseline
    item["dialog_count"] = len(baseline)
    item["source"] = f"patcher:{layer}"
    item.pop("original_dialogs", None)
    item.pop("xml", None)
    if gemini is not None and len(gemini) == len(baseline):
        item["gemini_dialogs"] = list(gemini)
    else:
        item.pop("gemini_dialogs", None)
    seeded = seeded_dialogs(baseline, item.get("gemini_dialogs"))
    if seeded == list(working):
        item.pop("dialogs", None)
    else:
        item["dialogs"] = list(working)
    held = {
        index
        for index in (unreviewed or [])
        if isinstance(index, int) and 0 <= index < len(working)
    }
    if held:
        item["unreviewed"] = sorted(held)
    else:
        item.pop("unreviewed", None)
    needs = 0
    gemini_lines = item.get("gemini_dialogs")
    for index, line in enumerate(working):
        gem = ""
        if isinstance(gemini_lines, list) and index < len(gemini_lines):
            gem = gemini_lines[index]
        shown = item["dialogs"][index] if "dialogs" in item else seeded[index]
        if index in held or needs_translation(shown) or (
            gem and shown == gem and needs_translation(baseline[index])
        ):
            needs += 1
    item["jp_dialogs"] = needs
    return item


def translation_keys(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    table = raw.get("translations", raw) if isinstance(raw, dict) else {}
    if not isinstance(table, dict):
        return {}
    return {str(key): value for key, value in table.items() if isinstance(value, str)}


def _key_forms(text: str) -> tuple[str, ...]:
    forms = [text, text.replace("\n", "◙"), text.replace("◙", "\n")]
    out: list[str] = []
    for form in forms:
        if form not in out:
            out.append(form)
    return tuple(out)


def already_translated(text: str, table: dict[str, str]) -> bool:
    return any(form in table for form in _key_forms(text))


def refresh_trb_items(
    items: list[dict],
    vanilla_by_index: dict[int, str],
    table: dict[str, str],
) -> tuple[list[dict], dict[str, int]]:
    """Drop TRB rows the patcher has already translated. Keep SMS rows."""
    kept: list[dict] = []
    dropped = refreshed = missing = 0
    for item in items:
        if item.get("kind") != "trb":
            kept.append(item)
            continue
        try:
            index = int(item.get("stri_index"))
        except (TypeError, ValueError):
            dropped += 1
            continue
        full = vanilla_by_index.get(index)
        if full is None:
            missing += 1
            dropped += 1
            continue
        if already_translated(full, table) or not string_needs_translation(full):
            dropped += 1
            continue
        row = dict(item)
        if row.get("baseline") != full or row.get("jp_key") != full:
            refreshed += 1
        row["baseline"] = full
        row["text"] = full
        row["jp_key"] = full
        row["dirty"] = False
        row.pop("gemini", None)
        kept.append(row)
    stats = {
        "trb_kept": sum(1 for item in kept if item.get("kind") == "trb"),
        "trb_dropped": dropped,
        "trb_refreshed": refreshed,
        "trb_missing_from_vanilla": missing,
    }
    return kept, stats


def patcher_working(
    stem: str,
    *,
    vanilla_dir: Path | None,
    eng_root: Path,
    gemini_root: Path,
    contrib_root: Path | None = None,
) -> tuple[list[str] | None, str]:
    """Text this stem ships as, and the layer name.

    A file under ``assets/script_contrib`` is the reviewed text. It wins over
    the Gemini machine pass, so the workbench does not ask for that stem again.
    """
    contrib = (contrib_root or (ROOT / "assets" / "script_contrib")) / "dbin2" / "script" / f"{stem}.dbin2"
    if contrib.is_file():
        return _dbin_dialogs(contrib), "contrib"
    gpath = gemini_root / "dbin2" / "script" / f"{stem}.dbin2"
    if stem[:1] in ("a", "k") and gpath.is_file():
        return _dbin_dialogs(gpath), "gemini"
    chosen, tag = resolve_script_source("script", stem, eng_root)
    if chosen is not None:
        return _dbin_dialogs(chosen), tag
    if vanilla_dir is not None:
        vpath = vanilla_dir / f"{stem}.dbin2"
        if vpath.is_file():
            return _dbin_dialogs(vpath), "jp"
    return None, "missing"


def align_gemini_xml(
    gemini_root: Path,
    vanilla_dir: Path | None,
) -> dict[str, int | list[str]]:
    """Make Gemini XML and its translation map match the shipped ``dbin2``."""
    xml_dir = gemini_root / "xml"
    dbin_dir = gemini_root / "dbin2" / "script"
    xml_dir.mkdir(parents=True, exist_ok=True)
    map_path = gemini_root / "translations.json"
    mapping: dict[str, str] = {}
    map_text = ""
    if map_path.is_file():
        map_text = map_path.read_text(encoding="utf-8")
        raw = json.loads(map_text)
        table = raw.get("translations", {})
        if isinstance(table, dict):
            mapping = {str(key): str(value) for key, value in table.items()}
    updated = created = map_keys = 0
    length_mismatch: list[str] = []
    created_stems: list[str] = []
    for dpath in sorted(dbin_dir.glob("*.dbin2")):
        stem = dpath.stem
        shipped = _dbin_dialogs(dpath)
        xpath = xml_dir / f"{stem}.xml"
        if not xpath.is_file():
            key, unknown, entries = parse_dbin2(dpath.read_bytes())
            text = entries_to_xml(key, unknown, entries)
            if "\r\n" not in text:
                text = text.replace("\n", "\r\n")
            xpath.write_bytes(text.encode("utf-8"))
            created += 1
            created_stems.append(stem)
            continue
        current = _xml_dialogs(xpath)
        if current == shipped:
            continue
        if len(current) != len(shipped):
            length_mismatch.append(stem)
            continue
        _write_xml_dialogs(xpath, shipped)
        updated += 1
    # The phrase map is what a later Gemini run writes back. Point every
    # mapped Japanese line at the English the script pack already ships.
    # A line that ships as two different English strings is left unchanged.
    pending: dict[str, set[str]] = {}
    for dpath in sorted(dbin_dir.glob("*.dbin2")):
        if vanilla_dir is None:
            break
        vpath = vanilla_dir / f"{dpath.stem}.dbin2"
        if not vpath.is_file():
            continue
        vanilla = _dbin_dialogs(vpath)
        shipped_rows = _dbin_dialogs(dpath)
        if len(vanilla) != len(shipped_rows):
            continue
        for jp, new in zip(vanilla, shipped_rows):
            for form in _key_forms(jp):
                # Every shipped English counts. Skipping the one that already
                # matches the cache made a two-way line look like one update
                # and overwrote the other wording.
                if form not in mapping:
                    continue
                pending.setdefault(form, set()).add(_norm(new))
    conflicts = 0
    for form, choices in pending.items():
        if len(choices) != 1:
            conflicts += 1
            continue
        new = next(iter(choices))
        if _norm(mapping.get(form, "")) == new:
            continue
        map_text, mapping, wrote = _point_map_at_shipped(map_text, mapping, form, new)
        map_keys += wrote
    if map_keys:
        map_path.write_text(map_text, encoding="utf-8")
    manifest = gemini_root / "stems.json"
    if manifest.is_file() and created_stems:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        stems = {str(stem) for stem in data.get("stems", [])}
        stems.update(created_stems)
        data["stems"] = sorted(stems)
        data["count"] = len(data["stems"])
        manifest.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return {
        "xml_updated": updated,
        "xml_created": created,
        "xml_created_stems": created_stems,
        "map_keys": map_keys,
        "map_conflicts": conflicts,
        "xml_length_mismatch": length_mismatch,
    }


def _point_map_at_shipped(
    text: str, mapping: dict[str, str], jp: str, shipped: str
) -> tuple[str, dict[str, str], int]:
    """Point one mapped Japanese line at the English the script pack ships.

    Shared lines that already disagree across scripts are left alone.
    """
    wrote = 0
    for form in _key_forms(jp):
        current = mapping.get(form)
        if current is None or _norm(current) == shipped:
            continue
        replaced = _replace_map_value(text, form, current, shipped)
        if replaced is None:
            continue
        text = replaced
        mapping[form] = shipped
        wrote += 1
    return text, mapping, wrote


def _replace_map_value(text: str, key: str, old: str, new: str) -> str | None:
    """Replace one translation value without rewriting the rest of the file."""
    old_frag = json.dumps(key, ensure_ascii=False) + ": " + json.dumps(old, ensure_ascii=False)
    new_frag = json.dumps(key, ensure_ascii=False) + ": " + json.dumps(new, ensure_ascii=False)
    if old_frag not in text:
        return None
    return text.replace(old_frag, new_frag, 1)


def _proofread_stems() -> set[str]:
    path = ROOT / "assets" / "gemini_heroines" / "proofread.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    stems = data.get("stems") if isinstance(data, dict) else None
    if not isinstance(stems, list):
        return set()
    return {str(stem) for stem in stems}


def _unreviewed_map() -> dict[str, list[int]]:
    """Dialog indexes an agent rewrote. A human has not signed those lines."""
    path = ROOT / "assets" / "script_contrib" / "unreviewed.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[int]] = {}
    for stem, indexes in data.items():
        if isinstance(indexes, list):
            out[str(stem)] = [n for n in indexes if isinstance(n, int)]
    return out


def _gemini_script(gemini_root: Path, stem: str) -> list[str] | None:
    path = gemini_root / "dbin2" / "script" / f"{stem}.dbin2"
    if not path.is_file():
        return None
    return _dbin_dialogs(path)


def _vanilla_dialogs(vanilla_dir: Path | None, stem: str) -> list[str] | None:
    if vanilla_dir is None:
        return None
    path = vanilla_dir / f"{stem}.dbin2"
    if not path.is_file():
        return None
    return _dbin_dialogs(path)


def sync_script_embed(
    data: dict,
    *,
    vanilla_dir: Path | None,
    eng_root: Path,
    gemini_root: Path,
) -> dict[str, int]:
    items = data.get("items")
    if not isinstance(items, list):
        raise SystemExit("script kit has no items list")
    layers: dict[str, int] = {}
    missing = unaligned = embedded = 0
    needs_scripts = 0
    proofread = _proofread_stems()
    unreviewed_map = _unreviewed_map()
    for item in items:
        if not isinstance(item, dict) or item.get("kind") != "script":
            continue
        stem = str(item.get("stem") or "")
        working, layer = patcher_working(
            stem,
            vanilla_dir=vanilla_dir,
            eng_root=eng_root,
            gemini_root=gemini_root,
        )
        if working is None:
            missing += 1
            continue
        vanilla = _vanilla_dialogs(vanilla_dir, stem)
        if vanilla is None or len(vanilla) != len(working):
            unaligned += 1
        # A proofread stem is signed off. Any other contributor file keeps the
        # Gemini pass beside it, so a machine line still needs a human.
        if layer == "gemini":
            gemini = working
        elif layer == "contrib" and stem not in proofread:
            gemini = _gemini_script(gemini_root, stem)
        else:
            gemini = None
        pending = unreviewed_map.get(stem) if gemini is not None else None
        fill_script_item(
            item,
            vanilla=vanilla,
            working=working,
            gemini=gemini,
            layer=layer,
            unreviewed=pending,
        )
        if "dialogs" in item:
            embedded += 1
        layers[layer] = layers.get(layer, 0) + 1
        if item.get("jp_dialogs"):
            needs_scripts += 1
    stats = data.setdefault("stats", {})
    if isinstance(stats, dict):
        stats["scripts"] = sum(
            1 for item in items if isinstance(item, dict) and item.get("kind") == "script"
        )
        stats["gemini_scripts"] = sum(
            1
            for item in items
            if isinstance(item, dict) and item.get("gemini_dialogs")
        )
        stats["original_scripts"] = sum(
            1
            for item in items
            if isinstance(item, dict) and item.get("original_dialogs")
        )
        stats["jp_dialogs"] = sum(
            int(item.get("jp_dialogs") or 0)
            for item in items
            if isinstance(item, dict)
        )
        stats["needs_scripts"] = needs_scripts
    data["synced"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["note"] = (
        "Baselines are vanilla Japanese when the line count matches. "
        "The edit box and Gemini lines are the current patcher text."
    )
    return {
        "scripts": int(stats.get("scripts", 0)) if isinstance(stats, dict) else 0,
        "needs_scripts": needs_scripts,
        "unaligned": unaligned,
        "missing": missing,
        "embedded_dialogs": embedded,
        **{f"layer_{name}": count for name, count in layers.items()},
    }


def sync_string_embed(data: dict, trb_path: Path, translations_path: Path) -> dict[str, int]:
    from patch_textresource import dump_entries, load_lookup

    lookup = load_lookup(ROOT / "tools" / "Trb2xlsx" / "TrbExport" / "lookup.txt")
    entries = dump_entries(trb_path.read_bytes(), lookup)
    by_index = {int(entry["idx"]): entry["text"] for entry in entries}
    table = translation_keys(translations_path)
    items = data.get("items")
    if not isinstance(items, list):
        raise SystemExit("strings kit has no items list")
    kept, stats = refresh_trb_items(items, by_index, table)
    data["items"] = kept
    sms = sum(1 for item in kept if item.get("kind") == "sms")
    trb = stats["trb_kept"]
    box = data.setdefault("stats", {})
    if isinstance(box, dict):
        box["sms"] = sms
        box["trb"] = trb
        box["total"] = sms + trb
        box["jp_left"] = sms + trb
    data["synced"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"sms": sms, **stats}


def sync(
    workbench: Path,
    *,
    gemini_root: Path = GEMINI,
    eng_root: Path = DEFAULT_ENG_DBIN,
    vanilla_dir: Path | None = None,
    trb_path: Path | None = None,
    translations_path: Path = TRANSLATIONS,
    align_xml: bool = True,
) -> dict[str, object]:
    if vanilla_dir is None:
        vanilla_dir = find_vanilla_script_dir()
    report: dict[str, object] = {}
    if align_xml:
        report["gemini_xml"] = align_gemini_xml(gemini_root, vanilla_dir)
    report["scripts"] = write_embed(
        workbench / "kit" / "NLPP_Translate.html",
        "embedded-workkit",
        lambda data: sync_script_embed(
            data,
            vanilla_dir=vanilla_dir,
            eng_root=eng_root,
            gemini_root=gemini_root,
        ),
    )
    if trb_path is None:
        trb_path = find_vanilla_main_trb()
    if trb_path is None or not trb_path.is_file():
        raise SystemExit("vanilla textresource_jpn.trb not found")
    report["strings"] = write_embed(
        workbench / "kit" / "NLPP_Translate_Strings.html",
        "embedded-strings",
        lambda data: sync_string_embed(data, trb_path, translations_path),
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbench", type=Path, default=DEFAULT_WORKBENCH)
    parser.add_argument("--gemini-root", type=Path, default=GEMINI)
    parser.add_argument("--eng-root", type=Path, default=DEFAULT_ENG_DBIN)
    parser.add_argument("--no-align-xml", action="store_true")
    args = parser.parse_args(argv)
    report = sync(
        args.workbench,
        gemini_root=args.gemini_root,
        eng_root=args.eng_root,
        align_xml=not args.no_align_xml,
    )
    from export_workbench_gemini import read_build

    build = read_build(args.workbench) + 1
    stamp_build(args.workbench, build)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[workbench] synced build={build}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
