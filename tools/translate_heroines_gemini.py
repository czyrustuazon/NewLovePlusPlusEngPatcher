#!/usr/bin/env python3
"""Feed untranslated Nene / Rinko text to Gemini and write EN XML / SMS.

Default model is Gemini 3.1 Pro Preview (quality; price no object). Game
control tokens (player/heroine name wrappers, wait marks) are sentinel-
protected so the model cannot drop them.

  python tools/translate_heroines_gemini.py status
  python tools/translate_heroines_gemini.py collect --heroine both
  python tools/translate_heroines_gemini.py run --dry-run
  python tools/translate_heroines_gemini.py run --heroine nene --limit 20
  python tools/translate_heroines_gemini.py run --write-xml

Default output is ``assets/gemini_heroines/`` (git-tracked). Gold inject still
needs ``--write-xml`` into ``assets/scripts/`` plus rebuild + stems.json.

Scripts: vanilla JP .dbin2 + existing EN overlay (rebuild_dbin2 / XML).
SMS: maildic XML if present (optional ``--source sms`` / ``all``).

GEMINI_API_KEY lives in .env (see .env.example).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TOOLS))

from gemini_translate import (  # noqa: E402
    DEFAULT_GEMINI_MODEL,
    TranslateResult,
    has_japanese,
    load_gemini_api_key,
    load_gemini_model,
    make_gemini_client,
    needs_translation,
    prepare_items,
    should_skip_line,
    translate_prepared,
)
from nlpp_paths import find_vanilla_script_dir  # noqa: E402
from patch_names import parse_dbin2  # noqa: E402
from rebuild_dbin2_from_xml import entries_to_xml, xml_to_entries  # noqa: E402

OUT_DEFAULT = ROOT / "assets" / "gemini_heroines"
ASSETS_SCRIPTS = ROOT / "assets" / "scripts"
REBUILD_SCRIPT = ROOT / "rebuild_dbin2" / "script"
SMS_EN = ROOT / "assets" / "sms_en"
LOC_SMS = ROOT.parent / "NewLovePlusPlusLocalizationProject" / "NLPP_sms_Need_clean_translation"
SMS_PACK = ROOT.parent / "sms_pack"

HEROINE_PREFIX = {"nene": "a", "rinko": "k"}
PREFIX_HEROINE = {"a": "nene", "k": "rinko"}
SMS_STEM = {"nene": "maildic_n", "rinko": "maildic_r"}


@dataclass
class Job:
    id: str
    heroine: str
    source: str  # script | sms
    stem: str
    entry: int
    dialog: int
    jp: str
    current: str


def _safe_print(text: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def heroines_from_arg(name: str) -> list[str]:
    if name == "both":
        return ["nene", "rinko"]
    if name in HEROINE_PREFIX:
        return [name]
    raise SystemExit(f"unknown heroine {name!r}; use nene, rinko, or both")


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_translation_map(path: Path) -> dict[str, str]:
    data = load_json(path)
    raw = data.get("translations", data)
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def parse_script_blob(path: Path) -> tuple[int, int, list]:
    if path.suffix.lower() == ".xml":
        return xml_to_entries(path)
    return parse_dbin2(path.read_bytes())


def overlay_path(stem: str) -> Path | None:
    xml = ASSETS_SCRIPTS / f"{stem}.xml"
    if xml.is_file():
        return xml
    dbin = REBUILD_SCRIPT / f"{stem}.dbin2"
    if dbin.is_file():
        return dbin
    return None


def flatten_dialogs(entries) -> list[tuple[int, int, str]]:
    rows: list[tuple[int, int, str]] = []
    for ei, entry in enumerate(entries):
        for di, text in enumerate(entry.sdl2.dialogs):
            rows.append((ei, di, text))
    return rows


def collect_script_jobs(vanilla_dir: Path, heroines: list[str]) -> list[Job]:
    jobs: list[Job] = []
    for heroine in heroines:
        prefix = HEROINE_PREFIX[heroine]
        files = sorted(vanilla_dir.glob(f"{prefix}*.dbin2"))
        for path in files:
            key, unknown, entries = parse_dbin2(path.read_bytes())
            del key, unknown
            overlay = overlay_path(path.stem)
            over_rows: dict[tuple[int, int], str] = {}
            if overlay is not None:
                try:
                    _k, _u, over_entries = parse_script_blob(overlay)
                    for ei, di, text in flatten_dialogs(over_entries):
                        over_rows[(ei, di)] = text
                except (ValueError, OSError, ET.ParseError):
                    over_rows = {}
            for ei, di, jp in flatten_dialogs(entries):
                current = over_rows.get((ei, di), jp)
                if not needs_translation(current):
                    continue
                # Overlay still JP (or missing): translate the JP source.
                src = jp if has_japanese(jp) else current
                if not needs_translation(src):
                    continue
                jobs.append(
                    Job(
                        id=f"script:{path.stem}:{ei}:{di}",
                        heroine=heroine,
                        source="script",
                        stem=path.stem,
                        entry=ei,
                        dialog=di,
                        jp=src,
                        current=current,
                    )
                )
    return jobs


def find_sms_xml(stem: str) -> Path | None:
    names = (f"{stem}.xml", f"{stem}.roundtrip.xml")
    dirs = (
        LOC_SMS,
        SMS_PACK,
        ROOT / "out" / "sms_pack",
        SMS_EN,
    )
    for folder in dirs:
        if not folder.is_dir():
            continue
        for name in names:
            cand = folder / name
            if cand.is_file() and ".en." not in cand.name:
                return cand
    return None


def parse_sms_entries(path: Path) -> list[tuple[str, str]]:
    root = ET.parse(path).getroot()
    rows: list[tuple[str, str]] = []
    for entry in root.findall("Entry"):
        jt = entry.find("JapaneseText")
        if jt is None:
            continue
        hex_id = jt.attrib.get("hex", "")
        text = (jt.text or "").replace("\r\n", "\n").replace("\r", "\n")
        rows.append((hex_id, text))
    return rows


def collect_sms_jobs(heroines: list[str]) -> list[Job]:
    jobs: list[Job] = []
    en_map = load_translation_map(SMS_EN / "translations.json")
    for heroine in heroines:
        stem = SMS_STEM[heroine]
        path = find_sms_xml(stem)
        if path is None:
            continue
        for idx, (hex_id, text) in enumerate(parse_sms_entries(path)):
            if text in en_map and not has_japanese(en_map[text]):
                continue
            if not needs_translation(text):
                continue
            jobs.append(
                Job(
                    id=f"sms:{stem}:{hex_id or idx}",
                    heroine=heroine,
                    source="sms",
                    stem=stem,
                    entry=idx,
                    dialog=0,
                    jp=text,
                    current=en_map.get(text, text),
                )
            )
    return jobs


def collect_jobs(args: argparse.Namespace) -> list[Job]:
    heroines = heroines_from_arg(args.heroine)
    jobs: list[Job] = []
    if args.source in ("scripts", "all"):
        vanilla = Path(args.vanilla_script) if args.vanilla_script else find_vanilla_script_dir()
        if vanilla is None or not vanilla.is_dir():
            raise SystemExit(
                "vanilla script dir missing. Pass --vanilla-script "
                "(extracted/romfs/script/bin/script) or drop a CIA so cache/vanilla_from_rom exists."
            )
        jobs.extend(collect_script_jobs(vanilla, heroines))
    if args.source in ("sms", "all"):
        jobs.extend(collect_sms_jobs(heroines))
    return jobs


def group_script_jobs(jobs: list[Job]) -> dict[str, list[Job]]:
    grouped: dict[str, list[Job]] = {}
    for job in jobs:
        if job.source != "script":
            continue
        grouped.setdefault(job.stem, []).append(job)
    return grouped


def cmd_status(args: argparse.Namespace) -> int:
    jobs = collect_jobs(args)
    scripts = [j for j in jobs if j.source == "script"]
    sms = [j for j in jobs if j.source == "sms"]
    by_h: dict[str, int] = {}
    stems: set[str] = set()
    for job in jobs:
        by_h[job.heroine] = by_h.get(job.heroine, 0) + 1
        if job.source == "script":
            stems.add(job.stem)
    print(f"pending lines: {len(jobs)}")
    print(f"  scripts: {len(scripts)} lines in {len(stems)} files")
    print(f"  sms:     {len(sms)} messages")
    for name in ("nene", "rinko"):
        print(f"  {name}:   {by_h.get(name, 0)}")
    print(f"model: {load_gemini_model(args.model)}")
    key = None
    try:
        key = load_gemini_api_key(args.api_key)
    except SystemExit:
        key = None
    print(f"GEMINI_API_KEY: {'set' if key else 'MISSING - paste into .env'}")
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    jobs = collect_jobs(args)
    out = Path(args.out)
    payload = [asdict(j) for j in jobs]
    save_json(out / "jobs.json", payload)
    print(f"wrote {len(jobs)} jobs -> {out / 'jobs.json'}")
    return 0


def _load_vanilla_script(vanilla_dir: Path, stem: str):
    path = vanilla_dir / f"{stem}.dbin2"
    if not path.is_file():
        raise FileNotFoundError(path)
    return parse_dbin2(path.read_bytes())


def translate_one_script(
    client,
    model: str,
    stem: str,
    pending: list[Job],
    vanilla_dir: Path,
    mapping: dict[str, str],
    args: argparse.Namespace,
) -> tuple[str, list[TranslateResult], list[str]]:
    _key, _unknown, entries = _load_vanilla_script(vanilla_dir, stem)
    overlay = overlay_path(stem)
    texts: list[str] = []
    need: list[bool] = []
    pending_by_loc = {(j.entry, j.dialog): j for j in pending}
    for ei, entry in enumerate(entries):
        over_dialogs = None
        if overlay is not None:
            try:
                _k, _u, over_entries = parse_script_blob(overlay)
                if ei < len(over_entries):
                    over_dialogs = over_entries[ei].sdl2.dialogs
            except (ValueError, OSError, ET.ParseError):
                over_dialogs = None
        for di, jp in enumerate(entry.sdl2.dialogs):
            current = jp
            if over_dialogs is not None and di < len(over_dialogs):
                current = over_dialogs[di]
            if jp in mapping:
                texts.append(mapping[jp])
                need.append(False)
                continue
            if (ei, di) in pending_by_loc:
                texts.append(jp)
                need.append(True)
            else:
                texts.append(current)
                need.append(False)

    heroine = PREFIX_HEROINE.get(stem[:1], "common")
    items = prepare_items(texts, need)
    results = translate_prepared(
        client,
        model,
        items,
        heroine=heroine,
        context=f"Script {stem}. Neighbor lines are scene context; only translate need=true.",
        temperature=args.temperature,
        thinking_level=args.thinking,
        repair=not args.no_repair,
        chunk_size=max(1, args.batch_size),
    )
    errors = [r.error for r in results if r.english is None and items[r.index].need]
    return stem, results, errors


def apply_script_results(
    stem: str,
    results: list[TranslateResult],
    vanilla_dir: Path,
    xml_dir: Path,
    mapping: dict[str, str],
) -> tuple[int, int]:
    key, unknown, entries = _load_vanilla_script(vanilla_dir, stem)
    overlay = overlay_path(stem)
    over_entries = None
    if overlay is not None:
        try:
            _k, _u, over_entries = parse_script_blob(overlay)
        except (ValueError, OSError, ET.ParseError):
            over_entries = None

    idx = 0
    written = 0
    failed = 0
    for ei, entry in enumerate(entries):
        new_dialogs: list[str] = []
        for di, jp in enumerate(entry.sdl2.dialogs):
            res = results[idx]
            idx += 1
            if res.english is not None and res.english != jp:
                new_dialogs.append(res.english)
                if needs_translation(jp) and not has_japanese(res.english):
                    mapping[jp] = res.english
                    written += 1
            elif over_entries is not None and ei < len(over_entries) and di < len(
                over_entries[ei].sdl2.dialogs
            ):
                new_dialogs.append(over_entries[ei].sdl2.dialogs[di])
                if res.english is None:
                    failed += 1
            else:
                new_dialogs.append(jp)
                if res.english is None:
                    failed += 1
        entry.sdl2.dialogs = new_dialogs
    xml_dir.mkdir(parents=True, exist_ok=True)
    (xml_dir / f"{stem}.xml").write_text(
        entries_to_xml(key, unknown, entries), encoding="utf-8"
    )
    return written, failed


def translate_sms_unique(
    client,
    model: str,
    jobs: list[Job],
    mapping: dict[str, str],
    args: argparse.Namespace,
) -> tuple[int, int]:
    pending_texts: list[str] = []
    seen: set[str] = set()
    for job in jobs:
        if job.jp in mapping or job.jp in seen:
            continue
        seen.add(job.jp)
        pending_texts.append(job.jp)
    if args.limit:
        pending_texts = pending_texts[: args.limit]

    done = 0
    errors = 0
    batch = max(1, args.batch_size)
    for start in range(0, len(pending_texts), batch):
        chunk = pending_texts[start : start + batch]
        heroine = jobs[0].heroine if jobs else "common"
        items = prepare_items(chunk)
        results = translate_prepared(
            client,
            model,
            items,
            heroine=heroine,
            context="These are in-game SMS / mail lines. Phone-text voice; keep them short.",
            temperature=args.temperature,
            thinking_level=args.thinking,
            repair=not args.no_repair,
        )
        for src, res in zip(chunk, results):
            if not res.english:
                errors += 1
                continue
            mapping[src] = res.english
            done += 1
        print(f"[sms] {min(start + len(chunk), len(pending_texts))}/{len(pending_texts)} map={len(mapping)} errors={errors}")
    return done, errors


def write_sms_xml(heroines: list[str], mapping: dict[str, str], out_dir: Path) -> None:
    from xml.dom import minidom

    out_dir.mkdir(parents=True, exist_ok=True)
    for heroine in heroines:
        stem = SMS_STEM[heroine]
        src = find_sms_xml(stem)
        if src is None:
            continue
        entries = parse_sms_entries(src)
        root = ET.Element("Dictionary")
        still_jp = 0
        for hex_id, text in entries:
            en = mapping.get(text, text)
            if has_japanese(en):
                still_jp += 1
            entry = ET.SubElement(root, "Entry")
            jt = ET.SubElement(entry, "JapaneseText", {"hex": hex_id})
            if en:
                jt.text = en
        pretty = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(
            indent="  ", encoding="utf-8"
        )
        dest = out_dir / f"{stem}.en.xml"
        dest.write_bytes(pretty)
        print(f"[sms] wrote {dest} (still_jp={still_jp})")


def cmd_run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = collect_jobs(args)
    if args.limit and args.source in ("scripts", "all"):
        # Limit whole scripts so scene context stays intact: first N pending lines,
        # then include every job that shares those stems.
        script_jobs = [j for j in jobs if j.source == "script"]
        sms_jobs = [j for j in jobs if j.source == "sms"]
        take = script_jobs[: args.limit]
        stems = {j.stem for j in take}
        script_jobs = [j for j in script_jobs if j.stem in stems] if stems else []
        jobs = script_jobs + sms_jobs
        print(f"[limit] keeping {len(script_jobs)} script lines across {len(stems)} file(s)")
    save_json(out / "jobs.json", [asdict(j) for j in jobs])

    print(f"pending: {len(jobs)}  model={load_gemini_model(args.model)}")
    if args.dry_run:
        by_stem: dict[str, int] = {}
        for job in jobs:
            if job.source == "script":
                by_stem[job.stem] = by_stem.get(job.stem, 0) + 1
        for stem, n in sorted(by_stem.items())[:20]:
            print(f"  {stem}: {n} lines")
        if len(by_stem) > 20:
            print(f"  ... +{len(by_stem) - 20} scripts")
        sms_n = sum(1 for j in jobs if j.source == "sms")
        if sms_n:
            print(f"  sms: {sms_n}")
        print("dry-run: no API calls")
        return 0

    api_key = load_gemini_api_key(args.api_key)
    model = load_gemini_model(args.model)
    client = make_gemini_client(api_key)
    map_path = out / "translations.json"
    mapping = load_translation_map(map_path)
    rejected: list[dict] = []

    vanilla = Path(args.vanilla_script) if args.vanilla_script else find_vanilla_script_dir()
    xml_dir = out / "xml"
    script_jobs = [j for j in jobs if j.source == "script"]
    sms_jobs = [j for j in jobs if j.source == "sms"]

    grouped = group_script_jobs(script_jobs)
    stems = sorted(grouped)
    xml_dir.mkdir(parents=True, exist_ok=True)
    if not args.force:
        existing = {p.stem for p in xml_dir.glob("*.xml")}
        skipped = [s for s in stems if s in existing]
        stems = [s for s in stems if s not in existing]
        if skipped:
            print(f"[scripts] resume skip {len(skipped)} existing xml")
    workers = max(1, args.workers)
    translated_lines = 0
    failed_lines = 0
    map_lock = threading.Lock()

    def run_stem(stem: str):
        return translate_one_script(
            client, model, stem, grouped[stem], vanilla, mapping, args
        )

    if stems:
        if vanilla is None:
            raise SystemExit("vanilla script dir required for script translation")
        print(f"[scripts] {len(stems)} files, workers={workers}, thinking={args.thinking}")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(run_stem, stem) for stem in stems]
            finished = 0
            for fut in as_completed(futs):
                try:
                    stem, results, errors = fut.result()
                except Exception as exc:  # noqa: BLE001 — one script must not kill the run
                    print(f"[scripts] worker crashed: {exc!r}", flush=True)
                    failed_lines += 1
                    finished += 1
                    continue
                with map_lock:
                    w, f = apply_script_results(stem, results, vanilla, xml_dir, mapping)
                    translated_lines += w
                    failed_lines += f
                    for res in results:
                        if res.english is None:
                            rejected.append(
                                {
                                    "stem": stem,
                                    "jp": res.source,
                                    "error": res.error,
                                    "missing": res.missing_markers,
                                }
                            )
                    finished += 1
                    save_json(map_path, {"translations": mapping})
                    print(
                        f"[scripts] {finished}/{len(stems)} {stem} "
                        f"+{w} en  fail={f}  map={len(mapping)}"
                    )
                    if errors:
                        _safe_print(f"  errors: {errors[:6]}")

    if sms_jobs:
        d, e = translate_sms_unique(client, model, sms_jobs, mapping, args)
        translated_lines += d
        failed_lines += e
        save_json(map_path, {"translations": mapping})
        write_sms_xml(heroines_from_arg(args.heroine), mapping, out / "sms")

    save_json(map_path, {"translations": mapping})
    save_json(out / "rejected.json", rejected)
    print(
        f"done: translated~{translated_lines} failed={failed_lines} "
        f"rejected={len(rejected)} xml={xml_dir if stems else '(none)'}"
    )

    if args.write_xml and xml_dir.is_dir():
        copied = 0
        ASSETS_SCRIPTS.mkdir(parents=True, exist_ok=True)
        for path in xml_dir.glob("*.xml"):
            dest = ASSETS_SCRIPTS / path.name
            dest.write_bytes(path.read_bytes())
            copied += 1
        print(f"copied {copied} xml -> {ASSETS_SCRIPTS}")
        print("Rebuild + allowlist required before Drop CIA injects these stems:")
        print("  python tools/rebuild_dbin2_from_xml.py --glob \"a*.xml\"")
        print("  python tools/rebuild_dbin2_from_xml.py --glob \"k*.xml\"")
        print("  then add new stems to assets/nlppatch/stems.json")
    return 0 if failed_lines == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--heroine", choices=("nene", "rinko", "both"), default="both")
        p.add_argument(
            "--source",
            choices=("scripts", "sms", "all"),
            default="scripts",
            help="scripts = a*/k* dialogue (default); sms = maildic; all = both",
        )
        p.add_argument("--vanilla-script", default=None, help="folder of JP a*.dbin2 / k*.dbin2")
        p.add_argument("--out", default=str(OUT_DEFAULT))
        p.add_argument("--api-key", default=None)
        p.add_argument("--model", default=None, help=f"default: {DEFAULT_GEMINI_MODEL}")

    p_status = sub.add_parser("status", help="count untranslated Nene/Rinko lines")
    add_common(p_status)
    p_status.set_defaults(func=cmd_status)

    p_collect = sub.add_parser("collect", help="write jobs.json without calling Gemini")
    add_common(p_collect)
    p_collect.set_defaults(func=cmd_collect)

    p_run = sub.add_parser("run", help="translate pending lines with Gemini")
    add_common(p_run)
    p_run.add_argument("--dry-run", action="store_true", help="collect + print; no API")
    p_run.add_argument("--limit", type=int, default=0, help="cap pending script lines (keeps whole files)")
    p_run.add_argument("--batch-size", type=int, default=40, help="lines per Gemini call (scripts + SMS)")
    p_run.add_argument("--workers", type=int, default=2, help="parallel scripts")
    p_run.add_argument("--temperature", type=float, default=0.4)
    p_run.add_argument(
        "--thinking",
        default="HIGH",
        help="Gemini thinking level: HIGH (default), MEDIUM, LOW, MINIMAL, OFF",
    )
    p_run.add_argument("--no-repair", action="store_true", help="do not retry dropped markers")
    p_run.add_argument(
        "--force",
        action="store_true",
        help="re-translate scripts even if xml already exists in --out",
    )
    p_run.add_argument(
        "--write-xml",
        action="store_true",
        help="copy translated XML into assets/scripts/ for rebuild / inject",
    )
    p_run.set_defaults(func=cmd_run)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
