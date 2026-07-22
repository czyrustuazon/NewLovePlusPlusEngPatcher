#!/usr/bin/env python3
"""OpenAI-translate NLPP SMS maildic dictionaries (Manaka/Nene/Rinko).

Reads ``sms_pack/maildic_{m,n,r}.roundtrip.xml`` (or --input), translates unique
Japanese bodies with the same OpenAI batcher as TRB, writes:

  assets/sms_en/maildic_{m,n,r}.en.xml
  assets/sms_en/translations.json   (JP→EN map, resumable)
  assets/sms_en/maildic_{m,n,r}.nlpmail  (NLPMAIL1 pack for round-trip / later inject)

Game install: ``tools/deploy_sms_maildic_en.py`` splices MDC into img.bin pkg **92**
(not ``romfs/dictionary/all2_u.bin``, which is an IME dict). NLPMAIL1 is not used in-game.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from patch_textresource import (  # noqa: E402
    JP_RE,
    load_openai_api_key,
    to_game_newlines,
)

SMS_PACK = ROOT.parent / "sms_pack"
LOC_SMS = ROOT.parent / "NewLovePlusPlusLocalizationProject" / "NLPP_sms_Need_clean_translation"
OUT = ROOT / "assets" / "sms_en"
STEMS = ("maildic_m", "maildic_n", "maildic_r")

SMS_SYSTEM_EXTRA = """
These are in-game SMS / mail dictionary lines from New Love Plus+ (girls texting the player: Manaka, Nene, or Rinko).
Priority: sound like a real person texting in natural, fluent modern English — not stiff, literal, or machine-translated.
- Casual phone-text voice: contractions, soft slang when it fits, warm/teasing/shy as the JP implies.
- Do NOT sound like a dictionary. Prefer “Morning!” / “You up?” over awkward calques.
- Preserve tokens exactly: ▲主人公＊▲, ▼, ?, ？, @, and any ▲…▲ placeholders (keep ▲主人公＊▲ as-is; do not replace with a name).
- Keep lines short enough for an SMS bubble (under ~300 UTF-8 bytes). One beat per message.
- Leading '?' in JP is often a dump/variant marker — drop it unless it is clearly a question mark for the sentence.
- Prefer ASCII punctuation; fullwidth '？' is OK for questions if the JP used it.
- Never leave Japanese characters unless a proper noun has no natural English form.
"""


def parse_entries(path: Path) -> list[tuple[str, str]]:
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


def write_xml(path: Path, entries: list[tuple[str, str]]) -> None:
    from xml.dom import minidom

    root = ET.Element("Dictionary")
    for hex_id, text in entries:
        entry = ET.SubElement(root, "Entry")
        jt = ET.SubElement(entry, "JapaneseText", {"hex": hex_id})
        if text:
            jt.text = text
    rough = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    path.write_bytes(pretty)


def pack_nlpmail(entries: list[tuple[str, str]]) -> bytes:
    import struct

    magic = b"NLPMAIL1"
    out = bytearray(magic)
    out += struct.pack("<I", len(entries))
    for hex_id, text in entries:
        hid = int(hex_id or "0") & 0xFFFFFFFFFFFFFFFF
        payload = text.encode("utf-8")
        out += struct.pack("<QH", hid, len(payload))
        out += payload
        while len(out) % 4:
            out += b"\x00"
    return bytes(out)


def load_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("translations", data))


def save_map(path: Path, mapping: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"translations": mapping}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def collect_pending(sources: list[Path], mapping: dict[str, str]) -> list[str]:
    pending: list[str] = []
    seen: set[str] = set()
    for path in sources:
        for _hid, text in parse_entries(path):
            if not text or not JP_RE.search(text):
                continue
            if text in mapping or text in seen:
                continue
            seen.add(text)
            pending.append(text)
    return pending


def apply_map(
    entries: list[tuple[str, str]], mapping: dict[str, str]
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for hid, text in entries:
        if text and text in mapping:
            out.append((hid, mapping[text]))
        else:
            out.append((hid, text))
    return out


def sms_translate_batch(client, model: str, texts: list[str], start_index: int) -> list[str | None]:
    """Like openai_translate_batch but with an SMS-focused user prompt."""
    import patch_textresource as ptr

    payload = [{"i": start_index + n, "s": s.replace("\n", "◙")} for n, s in enumerate(texts)]
    user = (
        "Translate each Japanese SMS/mail line into natural, conversational English "
        "as if a real girlfriend is texting. Avoid literal/stiff wording.\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    resp = client.chat.completions.create(
        model=model,
        temperature=0.35,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": ptr.SYSTEM_PROMPT + SMS_SYSTEM_EXTRA
                + '\nWrap the array in an object: {"items":[...]}',
            },
            {"role": "user", "content": user},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    data = json.loads(content)
    items = data.get("items", data if isinstance(data, list) else [])
    by_i: dict[int, str] = {}
    for item in items:
        if isinstance(item, dict) and "i" in item and "t" in item:
            by_i[int(item["i"])] = str(item["t"])
    out: list[str | None] = []
    for n, _src in enumerate(texts):
        en = by_i.get(start_index + n)
        if en is None:
            out.append(None)
            continue
        en = to_game_newlines(en)
        if len(JP_RE.findall(en)) > max(2, len(en) // 4):
            out.append(None)
            continue
        out.append(en)
    return out


def translate(args: argparse.Namespace) -> int:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("pip install openai") from exc

    api_key = load_openai_api_key(args.api_key)
    client = OpenAI(api_key=api_key)

    src_dir = Path(args.input)
    sources: list[Path] = []
    for stem in STEMS:
        for name in (f"{stem}.xml", f"{stem}.roundtrip.xml", f"{stem}.en.xml"):
            cand = src_dir / name
            if cand.is_file() and ".en." not in cand.name:
                sources.append(cand)
                break
    if not sources:
        sources = sorted(
            p
            for p in src_dir.glob("maildic_*.xml")
            if ".en." not in p.name and ".roundtrip." not in p.name
        )
    if not sources:
        sources = sorted(src_dir.glob("maildic_*.roundtrip.xml"))
    if not sources:
        raise SystemExit(f"no maildic XML under {src_dir}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    map_path = out_dir / "translations.json"
    mapping = load_map(map_path)

    pending = collect_pending(sources, mapping)
    print(f"[sms] sources={len(sources)} unique JP pending={len(pending)} map={len(mapping)}")
    if args.limit:
        pending = pending[: args.limit]
        print(f"[sms] --limit {len(pending)}")

    if not pending:
        print("[sms] nothing to translate")
    else:
        batch_size = max(1, args.batch_size)
        workers = max(1, args.workers)
        batches = [
            (i, pending[i : i + batch_size]) for i in range(0, len(pending), batch_size)
        ]
        errors = 0
        done = 0

        def run_batch(start: int, chunk: list[str]):
            try:
                return start, chunk, sms_translate_batch(client, args.model, chunk, start)
            except Exception as exc:
                print(f"[sms] batch error {start}: {exc!r}; one-by-one")
                results = []
                for n, s in enumerate(chunk):
                    try:
                        results.append(
                            sms_translate_batch(client, args.model, [s], start + n)[0]
                        )
                    except Exception as exc2:
                        print(f"[sms] item error: {exc2!r} {s[:40]!r}")
                        results.append(None)
                    time.sleep(args.sleep)
                return start, chunk, results

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(run_batch, s, c) for s, c in batches]
            finished = 0
            for fut in as_completed(futs):
                _s, chunk, results = fut.result()
                for src, dst in zip(chunk, results):
                    if not dst:
                        errors += 1
                        continue
                    # Keep SMS ASCII '?' unless JP used fullwidth — normalize lightly.
                    en = to_game_newlines(dst)
                    # Reject leftover JP.
                    if len(JP_RE.findall(en)) > max(2, len(en) // 4):
                        errors += 1
                        continue
                    mapping[src] = en
                    done += 1
                finished += len(chunk)
                save_map(map_path, mapping)
                print(
                    f"[sms] progress {finished}/{len(pending)} "
                    f"(map={len(mapping)} errors={errors} model={args.model})"
                )
        print(f"[sms] translated {done}; errors {errors}")

    # Write EN XML + nlpmail for each source
    for path in sources:
        entries = parse_entries(path)
        en_entries = apply_map(entries, mapping)
        still_jp = sum(1 for _, t in en_entries if t and JP_RE.search(t))
        stem = path.stem.replace(".roundtrip", "")
        if stem.endswith(".roundtrip"):
            stem = stem[: -len(".roundtrip")]
        # path.stem for maildic_m.roundtrip.xml is maildic_m.roundtrip
        stem = path.name.split(".")[0]
        xml_out = out_dir / f"{stem}.en.xml"
        bin_out = out_dir / f"{stem}.nlpmail"
        write_xml(xml_out, en_entries)
        bin_out.write_bytes(pack_nlpmail(en_entries))
        print(f"[sms] wrote {xml_out.name} + {bin_out.name} (still_jp={still_jp})")

    print("[sms] done →", out_dir)
    print(
        "Install with: python tools/deploy_sms_maildic_en.py"
    )
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input",
        default=str(LOC_SMS if LOC_SMS.is_dir() else SMS_PACK),
        help="folder with maildic_*.xml (default: LocalizationProject SMS folder)",
    )
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    raise SystemExit(translate(args))


if __name__ == "__main__":
    main()
