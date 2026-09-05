#!/usr/bin/env python3
"""Restore heroine nickname tokens in Manaka (t*) script XML.

EngPatcher previously expanded ``▲高嶺＊＊▲`` to plain ``Takane`` in dialogue,
which keeps English readable but disables in-line nickname substitution.

For each ``assets/scripts/t*.xml``, compare dialog lines positionally against
Makein ``NLPP_scripts-Done``. When the only difference is heroine name tokens
vs plain English, copy the Makein token form back into EngPatcher XML.

Requires Makein reference copies under ``cache/makein_compare/Done_<stem>.xml``
(fetch on demand from NLPPGit).
"""
from __future__ import annotations

import argparse
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPTS = ROOT / "assets" / "scripts"
DEFAULT_CACHE = ROOT / "cache" / "makein_compare"
MAKEIN_BASE = (
    "https://raw.githubusercontent.com/Makein/NLPPGit/master/NLPP_scripts-Done"
)

DIALOG_RE = re.compile(r"(<Dialog>)(.*?)(</Dialog>)", re.DOTALL)

# Longest match first when normalizing heroine references to a shared slot.
_HERO_VARIANTS: list[tuple[str, str]] = [
    ("▲高嶺＊＊▲", "@HERO@"),
    ("▲Takane＊＊▲", "@HERO@"),
    ("▲高嶺＊＊", "@HERO@"),
    ("▲Takane＊＊", "@HERO@"),
    ("▲小早川＊▲", "@RINKO@"),
    ("▲Rinko＊▲", "@RINKO@"),
    ("▲小早川＊", "@RINKO@"),
    ("▲Rinko＊", "@RINKO@"),
    ("▲姉ヶ崎＊▲", "@NENE@"),
    ("▲Nene＊▲", "@NENE@"),
    ("▲姉ヶ崎＊", "@NENE@"),
    ("▲Nene＊", "@NENE@"),
    ("▲主人公＊▲", "@PLAYER@"),
    ("▲彼女＊＊▲", "@GIRLFRIEND@"),
    ("Takane", "@HERO@"),
    ("Rinko", "@RINKO@"),
    ("Nene", "@NENE@"),
]

_HERO_TOKENS = tuple(old for old, _ in _HERO_VARIANTS if old.startswith("▲"))


@dataclass
class FileStats:
    stem: str
    dialogs: int
    restored: int
    skipped_count_mismatch: bool = False


def normalize_hero_refs(text: str) -> str:
    out = re.sub(r"\s+", " ", text.strip())
    for old, new in _HERO_VARIANTS:
        out = out.replace(old, new)
    return out


def extract_dialog_inners(text: str) -> list[str]:
    return [m.group(2) for m in DIALOG_RE.finditer(text)]


def fetch_makein(stem: str, cache_dir: Path) -> Path | None:
    out = cache_dir / f"Done_{stem}.xml"
    if out.is_file() and out.stat().st_size > 500:
        return out
    url = f"{MAKEIN_BASE}/{stem}.xml"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    except OSError:
        return None
    if out.stat().st_size <= 500:
        return None
    return out


def restore_script_file(
    eng_path: Path,
    makein_path: Path,
    *,
    dry_run: bool,
) -> FileStats:
    eng_text = eng_path.read_text(encoding="utf-8")
    mk_inners = extract_dialog_inners(makein_path.read_text(encoding="utf-8"))
    eng_inners = extract_dialog_inners(eng_text)
    stats = FileStats(eng_path.stem, len(eng_inners), 0)
    if len(eng_inners) != len(mk_inners):
        stats.skipped_count_mismatch = True
        return stats

    mk_i = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal mk_i
        eng_inner = match.group(2)
        mk_inner = mk_inners[mk_i]
        mk_i += 1
        if eng_inner == mk_inner:
            return match.group(0)
        if normalize_hero_refs(eng_inner) != normalize_hero_refs(mk_inner):
            return match.group(0)
        stats.restored += 1
        return f"{match.group(1)}{mk_inner}{match.group(3)}"

    new_text = DIALOG_RE.sub(repl, eng_text)
    if stats.restored and not dry_run:
        eng_path.write_text(new_text, encoding="utf-8", newline="\n")
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scripts", type=Path, default=DEFAULT_SCRIPTS)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument(
        "--glob",
        default="t*.xml",
        help="script glob under --scripts (default: Manaka t*)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    scripts_dir = args.scripts.resolve()
    cache_dir = args.cache.resolve()
    results: list[FileStats] = []
    missing: list[str] = []

    for eng_path in sorted(scripts_dir.glob(args.glob)):
        mk_path = fetch_makein(eng_path.stem, cache_dir)
        if mk_path is None:
            missing.append(eng_path.stem)
            continue
        stats = restore_script_file(eng_path, mk_path, dry_run=args.dry_run)
        if stats.restored:
            results.append(stats)

    total_restored = sum(s.restored for s in results)
    touched = len(results)
    print(
        f"[restore] {'would update' if args.dry_run else 'updated'} "
        f"{touched} files, {total_restored} dialog lines"
    )
    if missing:
        tail = ", ".join(missing[:12])
        if len(missing) > 12:
            tail += "..."
        print(f"[restore] skipped {len(missing)} scripts (no Makein ref): {tail}")
    for s in sorted(results, key=lambda x: -x.restored)[:15]:
        print(f"  {s.stem}: {s.restored} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
