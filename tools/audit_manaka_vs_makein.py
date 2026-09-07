#!/usr/bin/env python3
"""Audit EngPatcher Manaka (t*) XML vs Makein/NLPPGit fan scripts.

Compares ``assets/scripts/t*.xml`` dialog lines to Makein
``NLPP_scripts-Done/<stem>.xml`` (cached under ``cache/makein_compare/``).

Categories per dialog / file:
  exact          — identical text (or both empty stubs)
  token_only     — same wording after heroine/player token + whitespace normalize
  content_diff   — real wording difference
  count_mismatch — different number of <Dialog> blocks
  missing_makein — no Makein reference on GitHub

Fan-equivalent = exact | token_only.

Writes ``out/manaka_makein_audit.json`` (+ console summary).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from restore_nickname_tokens import (  # noqa: E402
    DEFAULT_CACHE,
    DEFAULT_SCRIPTS,
    MAKEIN_BASE,
    extract_dialog_inners,
    normalize_hero_refs,
)

OUT_DEFAULT = ROOT / "out" / "manaka_makein_audit.json"


def fetch_makein_any(stem: str, cache_dir: Path) -> Path | None:
    """Fetch Makein XML; keep tiny empty stubs (``fetch_makein`` used to skip <500B)."""
    out = cache_dir / f"Done_{stem}.xml"
    if out.is_file() and out.stat().st_size > 50:
        return out
    url = f"{MAKEIN_BASE}/{stem}.xml"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "NLPP-EngPatcher-audit"})
        out.write_bytes(urllib.request.urlopen(req, timeout=30).read())
    except OSError:
        return None
    if out.stat().st_size <= 50:
        return None
    return out


def normalize_compare(text: str) -> str:
    """Heroine/player tokens + surrounding whitespace → comparable form."""
    out = normalize_hero_refs(text)
    out = re.sub(r"\s+", " ", out.strip())
    out = re.sub(
        r"\s*(@(?:HERO|RINKO|NENE|PLAYER|GIRLFRIEND)@)\s*",
        r" \1 ",
        out,
    )
    return re.sub(r"\s+", " ", out.strip())


def classify_file(eng_path: Path, cache_dir: Path) -> dict:
    stem = eng_path.stem
    mk_path = fetch_makein_any(stem, cache_dir)
    row: dict = {
        "stem": stem,
        "eng": str(eng_path.relative_to(ROOT)).replace("\\", "/"),
        "makein": None,
        "status": "missing_makein",
        "eng_dialogs": 0,
        "makein_dialogs": 0,
        "exact": 0,
        "token_only": 0,
        "content_diff": 0,
        "empty_stub": False,
        "diffs": [],
    }
    if mk_path is None:
        return row

    row["makein"] = str(mk_path.relative_to(ROOT)).replace("\\", "/")
    eng = extract_dialog_inners(eng_path.read_text(encoding="utf-8", errors="replace"))
    mk = extract_dialog_inners(mk_path.read_text(encoding="utf-8", errors="replace"))
    row["eng_dialogs"] = len(eng)
    row["makein_dialogs"] = len(mk)

    if not eng and not mk:
        row["empty_stub"] = True
        row["status"] = "exact"
        return row

    if len(eng) != len(mk):
        row["status"] = "count_mismatch"
        row["diffs"].append(
            {
                "i": None,
                "kind": "count_mismatch",
                "eng_n": len(eng),
                "makein_n": len(mk),
            }
        )
        return row

    for i, (e, m) in enumerate(zip(eng, mk)):
        if e == m:
            row["exact"] += 1
            continue
        if normalize_compare(e) == normalize_compare(m):
            row["token_only"] += 1
            if len(row["diffs"]) < 8:
                row["diffs"].append(
                    {
                        "i": i,
                        "kind": "token_only",
                        "eng": e[:180],
                        "makein": m[:180],
                    }
                )
            continue
        row["content_diff"] += 1
        if len(row["diffs"]) < 12:
            row["diffs"].append(
                {
                    "i": i,
                    "kind": "content_diff",
                    "eng": e[:220],
                    "makein": m[:220],
                }
            )

    if row["content_diff"]:
        row["status"] = "content_diff"
    elif row["token_only"]:
        row["status"] = "token_only"
    else:
        row["status"] = "exact"
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scripts", type=Path, default=DEFAULT_SCRIPTS)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    scripts = sorted(args.scripts.resolve().glob("t*.xml"))
    if not scripts:
        print(f"no t*.xml under {args.scripts}", file=sys.stderr)
        return 1

    cache = args.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)

    probe = urllib.request.Request(
        f"{MAKEIN_BASE}/t000.xml",
        headers={"User-Agent": "NLPP-EngPatcher-audit"},
    )
    urllib.request.urlopen(probe, timeout=30).read(64)

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = [pool.submit(classify_file, p, cache) for p in scripts]
        for fut in as_completed(futs):
            rows.append(fut.result())

    rows.sort(key=lambda r: r["stem"])
    status_counts = Counter(r["status"] for r in rows)
    dialog_totals = Counter()
    stubs = 0
    for r in rows:
        dialog_totals["exact"] += r["exact"]
        dialog_totals["token_only"] += r["token_only"]
        dialog_totals["content_diff"] += r["content_diff"]
        dialog_totals["eng_dialogs"] += r["eng_dialogs"]
        dialog_totals["makein_dialogs"] += r["makein_dialogs"]
        if r.get("empty_stub"):
            stubs += 1

    fan_equiv_files = status_counts.get("exact", 0) + status_counts.get("token_only", 0)
    fan_equiv_dialogs = dialog_totals["exact"] + dialog_totals["token_only"]
    comparable_dialogs = (
        dialog_totals["exact"] + dialog_totals["token_only"] + dialog_totals["content_diff"]
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference": "https://github.com/Makein/NLPPGit/tree/master/NLPP_scripts-Done",
        "eng_root": str(args.scripts.resolve()),
        "file_count": len(rows),
        "empty_stub_files": stubs,
        "files_by_status": dict(status_counts),
        "fan_equivalent_files": fan_equiv_files,
        "fan_equivalent_file_pct": round(100.0 * fan_equiv_files / len(rows), 2) if rows else 0.0,
        "dialogs": dict(dialog_totals),
        "fan_equivalent_dialogs": fan_equiv_dialogs,
        "fan_equivalent_dialog_pct": (
            round(100.0 * fan_equiv_dialogs / comparable_dialogs, 2)
            if comparable_dialogs
            else 0.0
        ),
        "exact_match_files": status_counts.get("exact", 0),
        "verdict_100_pct_fan_equivalent": (
            status_counts.get("missing_makein", 0) == 0
            and status_counts.get("count_mismatch", 0) == 0
            and status_counts.get("content_diff", 0) == 0
            and fan_equiv_files == len(rows)
        ),
        "note": (
            "token_only = same fan wording; EngPatcher may use plain 'Takane' while "
            "Makein keeps ▲高嶺＊＊▲ (pet-name token). Not a translation regression."
        ),
        "scripts": rows,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== Manaka vs Makein fan scripts ===")
    print(f"files: {len(rows)} (empty stubs: {stubs})")
    for k in (
        "exact",
        "token_only",
        "content_diff",
        "count_mismatch",
        "missing_makein",
    ):
        print(f"  {k}: {status_counts.get(k, 0)}")
    print(
        f"fan-equivalent files (exact|token_only): "
        f"{fan_equiv_files}/{len(rows)} ({report['fan_equivalent_file_pct']}%)"
    )
    print(
        f"dialogs exact={dialog_totals['exact']} token_only={dialog_totals['token_only']} "
        f"content_diff={dialog_totals['content_diff']} "
        f"fan-equiv={report['fan_equivalent_dialog_pct']}%"
    )
    print(f"verdict_100_pct_fan_equivalent: {report['verdict_100_pct_fan_equivalent']}")
    print(f"wrote {args.out}")

    bad = [r for r in rows if r["status"] in ("content_diff", "count_mismatch", "missing_makein")]
    if bad:
        print("\nNon-equivalent scripts:")
        for r in bad:
            print(
                f"  {r['stem']}: {r['status']} "
                f"(exact={r['exact']} token={r['token_only']} diff={r['content_diff']})"
            )
    return 0 if report["verdict_100_pct_fan_equivalent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
