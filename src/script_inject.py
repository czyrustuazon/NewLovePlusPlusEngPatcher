"""Layered English script injection for CIA / LayeredFS.

Target patch composition (scripts only — img.bin / TRB unchanged):

1. **Contributor review** — ``assets/script_contrib/dbin2`` when a stem has
   one. Always on. Wins over Gemini and over the community file.
2. **Manaka 100%** — ``rebuild_dbin2`` for every ``t*`` (all packs).
3. **EngPatcher common** — ``rebuild_dbin2`` for ``p*`` when present.
4. **Optional Gemini Nene** — ``assets/gemini_heroines/dbin2`` ``a*`` in every
   pack when ``NLPP_INCLUDE_GEMINI_NENE=1`` / ``--include-gemini-nene`` (machine
   pass, unreviewed; see ``assets/gemini_heroines/README.md``).
   A stem that already has a contributor file keeps that file.
5. **Community ~28%** — ``rebuild_dbin2/script`` ``a*``/``k*`` (and any other
   stems listed in ``assets/nlppatch/stems.json``) from the historical NLPPATCH
   layer, now shipped inside EngPatcher (no ``vendor/NLPPATCH`` required).
   Skipped for stems already taken by (1) or (4).
6. **Japanese** — everything else left to the base ROM/CIA. When a vanilla
   script tree is supplied, nickname markers on those Japanese files are
   still swapped: Manaka's to ▲Takane＊＊▲ (including an exact 高嶺
   nameplate), Nene's to ▲Anegasaki＊▲ (including an exact 姉ヶ崎
   nameplate), and Rinko's to ▲Kobayaka＊▲ (an exact 小早川 nameplate
   becomes Kobayakawa).

Community scripts never shipped ``NLP_01`` / ``NLP_02``; only Manaka and common
apply there, plus a contributor file for that pack, and Gemini Nene when opted in.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import patch_names

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENG_DBIN = ROOT / "rebuild_dbin2"
COMMUNITY_MANIFEST = ROOT / "assets" / "nlppatch" / "stems.json"
GEMINI_NENE_ROOT = ROOT / "assets" / "gemini_heroines"
GEMINI_NENE_DBIN = GEMINI_NENE_ROOT / "dbin2"
GEMINI_NENE_MANIFEST = GEMINI_NENE_ROOT / "stems.json"
# Human ingest of a Gemini stem. Shipped whenever the file exists.
CONTRIB_DBIN = ROOT / "assets" / "script_contrib" / "dbin2"
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
_gemini_nene_stems: set[str] | None = None


def include_gemini_nene() -> bool:
    """True when Drop / patch_cia opted into the Gemini Nene machine pass."""
    return str(os.environ.get("NLPP_INCLUDE_GEMINI_NENE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def gemini_nene_stems() -> set[str]:
    """Allowlisted Gemini Nene ``a*`` stems (empty when the archive is missing)."""
    global _gemini_nene_stems
    if _gemini_nene_stems is not None:
        return _gemini_nene_stems

    stems: set[str] = set()
    if GEMINI_NENE_MANIFEST.is_file():
        try:
            data = json.loads(GEMINI_NENE_MANIFEST.read_text(encoding="utf-8"))
            stems = {str(s) for s in data.get("stems", [])}
        except (OSError, json.JSONDecodeError, TypeError):
            stems = set()
    if not stems and (GEMINI_NENE_DBIN / "script").is_dir():
        stems = {p.stem for p in (GEMINI_NENE_DBIN / "script").glob("a*.dbin2")}
    _gemini_nene_stems = stems
    return _gemini_nene_stems


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


def _rewrite_base_script(data: bytes, *, stem: str = "") -> bytes:
    """Point a base script at the live surname slots.

    Exact 姉ヶ崎, 高嶺, and 小早川 nameplates become Anegasaki, Takane, and
    Kobayakawa on every route. ``stem`` is kept for callers.
    """
    data = patch_names.rewrite_nene_surname_speakers(data)
    data = patch_names.rewrite_rinko_surname_speakers(data)
    return patch_names.rewrite_manaka_surname_speakers(data)


def _copy_script(src: Path, dest: Path) -> None:
    """Copy one script. Nickname markers track the live surname slots.

    Exact 姉ヶ崎, 高嶺, and 小早川 nameplates become Anegasaki, Takane, and
    Kobayakawa on every route.
    """
    raw = src.read_bytes()
    patched = _rewrite_base_script(raw, stem=src.stem)
    if patched == raw:
        shutil.copy2(src, dest)
        return
    dest.write_bytes(patched)


def apply_nene_marker_to_romfs(
    romfs_dir: Path,
    vanilla_bin: Path | None = None,
) -> int:
    """Point loaded scripts at the live Manaka, Nene, and Rinko surname slots.

    Files already under ``romfs_dir/script/bin`` are rewritten in place.
    When ``vanilla_bin`` is a ``script/bin`` tree, a Japanese file that is
    not already overlaid is copied in with those nickname edits. Exact
    姉ヶ崎, 高嶺, and 小早川 nameplates become Anegasaki, Takane, and
    Kobayakawa on every stem. An existing English overlay is not replaced.
    """
    changed = 0
    dest_root = romfs_dir / "script" / "bin"
    if dest_root.is_dir():
        for path in sorted(dest_root.rglob("*.dbin2")):
            raw = path.read_bytes()
            patched = _rewrite_base_script(raw, stem=path.stem)
            if patched != raw:
                path.write_bytes(patched)
                changed += 1
    if vanilla_bin is None or not vanilla_bin.is_dir():
        return changed
    for src in sorted(vanilla_bin.rglob("*.dbin2")):
        dest = dest_root / src.relative_to(vanilla_bin)
        if dest.is_file():
            continue
        raw = src.read_bytes()
        patched = _rewrite_base_script(raw, stem=src.stem)
        if patched == raw:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(patched)
        changed += 1
    return changed


class ScriptInjectError(Exception):
    """English dialog inject could not run (missing pack or destination)."""


def inject_scripts(
    romfs_dir: Path,
    eng_root: Path | None = None,
    *,
    create_dirs: bool = False,
    vanilla_bin: Path | None = None,
) -> int:
    """Copy the same EN ``.dbin2`` set the CIA gets into ``romfs_dir``.

    ``create_dirs=False`` matches a full extracted RomFS (CIA rebuild): each
    ``script/bin/<pack>`` folder must already exist. ``create_dirs=True`` is
    for Azahar LayeredFS, which only needs the English files overlaid on the
    vanilla ROM. Stems that stay Japanese are not replaced with a translation.
    ``vanilla_bin`` (a ``script/bin`` tree) overlays those Japanese files with
    Manaka's marker pointed at Takane (and exact 高嶺 plates), Nene's at
    Anegasaki (and exact 姉ヶ崎 plates), and Rinko's at Kobayaka (exact
    小早川 plates become Kobayakawa).
    """
    eng_root = eng_root or DEFAULT_ENG_DBIN
    total = 0
    layers: dict[str, int] = {
        "manaka": 0,
        "eng_p": 0,
        "gemini_nene": 0,
        "nlppatch": 0,
        "contrib": 0,
    }
    skipped = 0
    gemini_on = include_gemini_nene()
    if gemini_on:
        print(
            "[inject] Gemini Nene machine pass enabled "
            f"({len(gemini_nene_stems())} a* stems)",
            flush=True,
        )
    for pack in PACKS:
        src_dir = eng_root / pack
        if not src_dir.is_dir():
            raise ScriptInjectError(f"missing packed scripts: {src_dir}")
        dest_dir = romfs_dir / "script" / "bin" / pack
        if not dest_dir.is_dir():
            if not create_dirs:
                raise ScriptInjectError(f"RomFS missing script pack folder: {dest_dir}")
            dest_dir.mkdir(parents=True, exist_ok=True)
        stems = {p.stem for p in src_dir.glob("*.dbin2")}
        if not stems:
            raise ScriptInjectError(f"no .dbin2 files in {src_dir}")
        contrib_dir = CONTRIB_DBIN / pack
        if contrib_dir.is_dir():
            stems |= {p.stem for p in contrib_dir.glob("*.dbin2")}
        if gemini_on:
            gem_dir = GEMINI_NENE_DBIN / pack
            if gem_dir.is_dir():
                stems |= {p.stem for p in gem_dir.glob("a*.dbin2")}
        injected = 0
        pack_layers: dict[str, int] = {}
        for stem in sorted(stems):
            chosen, tag = resolve_script_source(pack, stem, eng_root)
            if chosen is None:
                skipped += 1
                continue
            _copy_script(chosen, dest_dir / f"{stem}.dbin2")
            total += 1
            injected += 1
            if tag in layers:
                layers[tag] += 1
                pack_layers[tag] = pack_layers.get(tag, 0) + 1
        layer_note = ", ".join(f"{k}={v}" for k, v in sorted(pack_layers.items()))
        print(
            f"[inject] {pack}: {injected} EN ({layer_note or 'none'})"
            f" — {len(stems) - injected} JP (base ROM)"
        )
    print(
        f"[inject] total EN: {total} "
        f"(manaka={layers['manaka']}, p*={layers['eng_p']}, "
        f"contrib={layers['contrib']}, "
        f"gemini_nene={layers['gemini_nene']}, nlppatch={layers['nlppatch']})"
    )
    if skipped:
        print(f"[inject] {skipped} script slot(s) left Japanese")
    markers = apply_nene_marker_to_romfs(romfs_dir, vanilla_bin)
    if markers:
        print(f"[inject] nickname markers updated in {markers} script(s)")
    return total


def resolve_script_source(
    pack: str,
    stem: str,
    eng_root: Path,
) -> tuple[Path | None, str]:
    """Return (source path, layer tag) or (None, 'jp')."""
    eng = eng_root / pack / f"{stem}.dbin2"
    pref = script_prefix(stem)

    # Human review of a Gemini (or any) stem. Always on, ahead of the machine pass.
    contrib = CONTRIB_DBIN / pack / f"{stem}.dbin2"
    if contrib.is_file():
        return contrib, "contrib"

    # Optional Gemini Nene (all packs). Wins over community a* for the same stem.
    if include_gemini_nene() and pref == "a":
        allow_g = gemini_nene_stems()
        gem = GEMINI_NENE_DBIN / pack / f"{stem}.dbin2"
        if gem.is_file() and (not allow_g or stem in allow_g):
            return gem, "gemini_nene"

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
    if CONTRIB_DBIN.is_dir():
        present |= {p.stem for p in CONTRIB_DBIN.glob("*/*.dbin2")}
    if include_gemini_nene():
        present |= gemini_nene_stems()

    layers: dict[str, int | bool | float] = {
        "manaka": 0,
        "eng_p": 0,
        "contrib": 0,
        "gemini_nene": 0,
        "nlppatch": 0,
        "jp": 0,
    }
    for stem in sorted(present):
        _, tag = resolve_script_source("script", stem, eng_root)
        if tag == "jp":
            continue
        layers[tag] = int(layers.get(tag, 0)) + 1

    en = (
        int(layers["manaka"])
        + int(layers["eng_p"])
        + int(layers["contrib"])
        + int(layers["gemini_nene"])
        + int(layers["nlppatch"])
    )
    layers["total_stems"] = SCRIPT_PACK_TOTAL
    layers["jp"] = max(0, SCRIPT_PACK_TOTAL - en)
    layers["nlppatch_available"] = len(community_stems())
    layers["nlppatch_vendor"] = nlppatch_script_dir() is not None
    layers["community_manifest"] = COMMUNITY_MANIFEST.is_file()
    layers["gemini_nene_available"] = len(gemini_nene_stems())
    layers["gemini_nene_enabled"] = include_gemini_nene()
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
    ap.add_argument(
        "--include-gemini-nene",
        action="store_true",
        help="Also inject assets/gemini_heroines/dbin2 a* (or set NLPP_INCLUDE_GEMINI_NENE=1)",
    )
    args = ap.parse_args(argv)
    if args.include_gemini_nene:
        os.environ["NLPP_INCLUDE_GEMINI_NENE"] = "1"
    vanilla_bin = ROOT / "cache" / "vanilla_from_rom" / "romfs" / "script" / "bin"
    try:
        count = inject_scripts(
            args.layeredfs,
            args.dbin,
            create_dirs=True,
            vanilla_bin=vanilla_bin if vanilla_bin.is_dir() else None,
        )
    except ScriptInjectError as exc:
        print(f"[inject] {exc}", file=sys.stderr)
        return 1
    print(f"[inject] layeredfs OK ({count} EN .dbin2)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
