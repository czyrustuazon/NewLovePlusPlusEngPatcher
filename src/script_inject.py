"""Layered English script injection for CIA / LayeredFS.

Target patch composition (scripts only — img.bin / TRB unchanged):

1. **Manaka 100%** — ``rebuild_dbin2`` for every ``t*`` (all packs).
2. **EngPatcher common** — ``rebuild_dbin2`` for ``p*`` when present.
3. **Community ~28%** — ``rebuild_dbin2/script`` ``a*``/``k*`` (and any other
   stems listed in ``assets/nlppatch/stems.json``) from the historical NLPPATCH
   layer, now shipped inside EngPatcher (no ``vendor/NLPPATCH`` required).
4. **Japanese** — everything else left to the base ROM/CIA.

Community scripts never shipped ``NLP_01`` / ``NLP_02``; only (1)+(2) apply there.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENG_DBIN = ROOT / "rebuild_dbin2"
COMMUNITY_MANIFEST = ROOT / "assets" / "nlppatch" / "stems.json"
# Legacy offline mirror (optional). Prefer rebuild_dbin2 + stems.json.
LEGACY_NLPPATCH_SCRIPT = (
    ROOT
    / "vendor"
    / "NLPPATCH"
    / "release"
    / "romfs"
    / "script"
    / "bin"
    / "script"
)
# Older callers (export_progress_metrics, etc.)

PACKS = ("NLP_01", "NLP_02", "script")
MANAKA_PREFIX = "t"
ENG_PREFIXES = frozenset({"t", "p"})
COMMUNITY_PREFIXES = frozenset({"a", "k"})
# Vanilla RomFS ``script/bin/script`` stem count (New Love Plus+).
SCRIPT_PACK_TOTAL = 578

_community_stems: set[str] | None = None


def community_stems() -> set[str]:
    """Stems from the integrated NLPPATCH-era layer (allowlist)."""
    global _community_stems
    if _community_stems is not None:
        return _community_stems

    stems: set[str] = set()
    if COMMUNITY_MANIFEST.is_file():
        try:
            data = json.loads(COMMUNITY_MANIFEST.read_text(encoding="utf-8"))
            stems = {str(s) for s in data.get("stems", [])}
        except (OSError, json.JSONDecodeError, TypeError):
            stems = set()

    if not stems and LEGACY_NLPPATCH_SCRIPT.is_dir():
        stems = {p.stem for p in LEGACY_NLPPATCH_SCRIPT.glob("*.dbin2")}

    _community_stems = stems
    return _community_stems


def nlppatch_stems() -> set[str]:
    """Alias kept for older callers / progress metrics."""
    return community_stems()


def nlppatch_script_dir() -> Path | None:
    """Legacy vendor path if present (optional fallback only)."""
    if LEGACY_NLPPATCH_SCRIPT.is_dir() and any(LEGACY_NLPPATCH_SCRIPT.glob("*.dbin2")):
        return LEGACY_NLPPATCH_SCRIPT
    return None


def script_prefix(stem: str) -> str:
    return stem[0].lower() if stem else ""


class ScriptInjectError(Exception):
    """English dialog inject could not run (missing pack or destination)."""


def inject_scripts(
    romfs_dir: Path,
    eng_root: Path | None = None,
    *,
    create_dirs: bool = False,
) -> int:
    """Copy the same EN ``.dbin2`` set the CIA gets into ``romfs_dir``.

    ``create_dirs=False`` matches a full extracted RomFS (CIA rebuild): each
    ``script/bin/<pack>`` folder must already exist. ``create_dirs=True`` is
    for Azahar LayeredFS, which only needs the English files overlaid on the
    vanilla ROM. Stems that stay Japanese are not written.
    """
    eng_root = eng_root or DEFAULT_ENG_DBIN
    total = 0
    layers: dict[str, int] = {"manaka": 0, "eng_p": 0, "nlppatch": 0}
    skipped = 0
    for pack in PACKS:
        src_dir = eng_root / pack
        if not src_dir.is_dir():
            raise ScriptInjectError(f"missing packed scripts: {src_dir}")
        dest_dir = romfs_dir / "script" / "bin" / pack
        if not dest_dir.is_dir():
            if not create_dirs:
                raise ScriptInjectError(f"RomFS missing script pack folder: {dest_dir}")
            dest_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(src_dir.glob("*.dbin2"))
        if not files:
            raise ScriptInjectError(f"no .dbin2 files in {src_dir}")
        injected = 0
        pack_layers: dict[str, int] = {}
        for src in files:
            chosen, tag = resolve_script_source(pack, src.stem, eng_root)
            if chosen is None:
                skipped += 1
                continue
            shutil.copy2(chosen, dest_dir / src.name)
            total += 1
            injected += 1
            if tag in layers:
                layers[tag] += 1
                pack_layers[tag] = pack_layers.get(tag, 0) + 1
        layer_note = ", ".join(f"{k}={v}" for k, v in sorted(pack_layers.items()))
        print(
            f"[inject] {pack}: {injected} EN ({layer_note or 'none'})"
            f" — {len(files) - injected} JP (base ROM)"
        )
    print(
        f"[inject] total EN: {total} "
        f"(manaka={layers['manaka']}, p*={layers['eng_p']}, nlppatch={layers['nlppatch']})"
    )
    if skipped:
        print(f"[inject] {skipped} script slot(s) left Japanese")
    return total


def resolve_script_source(
    pack: str,
    stem: str,
    eng_root: Path,
) -> tuple[Path | None, str]:
    """Return (source path, layer tag) or (None, 'jp')."""
    eng = eng_root / pack / f"{stem}.dbin2"
    pref = script_prefix(stem)

    if pack != "script":
        if pref in ENG_PREFIXES and eng.is_file():
            tag = "manaka" if pref == MANAKA_PREFIX else "eng_p"
            return eng, tag
        return None, "jp"

    if pref == MANAKA_PREFIX and eng.is_file():
        return eng, "manaka"
    if pref == "p" and eng.is_file():
        return eng, "eng_p"

    # Community layer: prefer files already integrated into rebuild_dbin2.
    allow = community_stems()
    if eng.is_file():
        if allow:
            if stem in allow:
                return eng, "nlppatch"
        elif pref in COMMUNITY_PREFIXES:
            # Pre-manifest checkout: only a*/k* left in rebuild are community.
            return eng, "nlppatch"

    # Optional legacy vendor fallback (pre-integrate checkouts).
    nlp_dir = nlppatch_script_dir()
    if nlp_dir is not None:
        nlp = nlp_dir / f"{stem}.dbin2"
        if nlp.is_file() and (not allow or stem in allow):
            return nlp, "nlppatch"

    return None, "jp"


def coverage_summary(eng_root: Path | None = None) -> dict[str, int | bool]:
    """Counts inject layers against the full vanilla script-pack stem count."""
    eng_root = eng_root or DEFAULT_ENG_DBIN
    script_dir = eng_root / "script"
    present: set[str] = set()
    if script_dir.is_dir():
        present = {p.stem for p in script_dir.glob("*.dbin2")}
    # Include allowlisted community stems even if a file is temporarily missing.
    present |= community_stems()

    layers: dict[str, int | bool | float] = {
        "manaka": 0,
        "eng_p": 0,
        "nlppatch": 0,
        "jp": 0,
    }
    for stem in sorted(present):
        _, tag = resolve_script_source("script", stem, eng_root)
        if tag == "jp":
            continue
        layers[tag] = int(layers.get(tag, 0)) + 1

    en = int(layers["manaka"]) + int(layers["eng_p"]) + int(layers["nlppatch"])
    layers["total_stems"] = SCRIPT_PACK_TOTAL
    layers["jp"] = max(0, SCRIPT_PACK_TOTAL - en)
    layers["nlppatch_available"] = len(community_stems())
    layers["nlppatch_vendor"] = nlppatch_script_dir() is not None
    layers["community_manifest"] = COMMUNITY_MANIFEST.is_file()
    layers["english_stems"] = en
    layers["english_pct"] = round(100.0 * en / SCRIPT_PACK_TOTAL, 1)
    return layers


def main(argv: list[str] | None = None) -> int:
    """Overlay CIA-equivalent English dialog onto an Azahar LayeredFS romfs tree."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--layeredfs",
        type=Path,
        required=True,
        help="Azahar instance romfs directory (script/bin folders are created)",
    )
    ap.add_argument(
        "--dbin",
        type=Path,
        default=DEFAULT_ENG_DBIN,
        help="English .dbin2 root (default: rebuild_dbin2)",
    )
    args = ap.parse_args(argv)
    try:
        count = inject_scripts(args.layeredfs, args.dbin, create_dirs=True)
    except ScriptInjectError as exc:
        print(f"[inject] {exc}", file=sys.stderr)
        return 1
    print(f"[inject] layeredfs OK ({count} EN .dbin2)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
