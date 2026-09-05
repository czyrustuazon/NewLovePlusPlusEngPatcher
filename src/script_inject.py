"""Layered English script injection for CIA / LayeredFS.

Target patch composition (scripts only — img.bin / TRB unchanged):

1. **Manaka 100%** — ``rebuild_dbin2`` for every ``t*`` (all packs).
2. **EngPatcher common** — ``rebuild_dbin2`` for ``p*`` when present.
3. **NLPPPATCH ~28%** — vendored ``vendor/NLPPPATCH/.../script/*.dbin2`` for any
   other stem in their set (``script`` pack only; includes some ``k*``/``a*``/``p*``).
4. **Japanese** — everything else left to the base ROM/CIA.

NLPPPATCH never shipped ``NLP_01`` / ``NLP_02``; only (1)+(2) apply there.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENG_DBIN = ROOT / "rebuild_dbin2"
NLPPPATCH_SCRIPT = (
    ROOT
    / "vendor"
    / "NLPPPATCH"
    / "release"
    / "romfs"
    / "script"
    / "bin"
    / "script"
)

PACKS = ("NLP_01", "NLP_02", "script")
MANAKA_PREFIX = "t"
ENG_PREFIXES = frozenset({"t", "p"})

_nlppatch_stems: set[str] | None = None


def nlppatch_script_dir() -> Path | None:
    if NLPPPATCH_SCRIPT.is_dir() and any(NLPPPATCH_SCRIPT.glob("*.dbin2")):
        return NLPPPATCH_SCRIPT
    return None


def nlppatch_stems() -> set[str]:
    global _nlppatch_stems
    if _nlppatch_stems is None:
        d = nlppatch_script_dir()
        _nlppatch_stems = {p.stem for p in d.glob("*.dbin2")} if d else set()
    return _nlppatch_stems


def script_prefix(stem: str) -> str:
    return stem[0].lower() if stem else ""


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

    nlp_dir = nlppatch_script_dir()
    if nlp_dir is not None and stem in nlppatch_stems():
        nlp = nlp_dir / f"{stem}.dbin2"
        if nlp.is_file():
            return nlp, "nlppatch"

    return None, "jp"


def coverage_summary(eng_root: Path | None = None) -> dict[str, int | bool]:
    """Counts unique script stems by inject layer (script pack view)."""
    eng_root = eng_root or DEFAULT_ENG_DBIN
    script_dir = eng_root / "script"
    stems: set[str] = set()
    if script_dir.is_dir():
        stems = {p.stem for p in script_dir.glob("*.dbin2")}
    nlp = nlppatch_stems()
    layers = {"manaka": 0, "eng_p": 0, "nlppatch": 0, "jp": 0}
    for stem in sorted(stems):
        _, tag = resolve_script_source("script", stem, eng_root)
        layers[tag] = layers.get(tag, 0) + 1
    layers["total_stems"] = len(stems)
    layers["nlppatch_available"] = len(nlp)
    layers["nlppatch_vendor"] = nlppatch_script_dir() is not None
    en = layers["manaka"] + layers["eng_p"] + layers["nlppatch"]
    layers["english_stems"] = en
    if stems:
        layers["english_pct"] = round(100.0 * en / len(stems), 1)
    else:
        layers["english_pct"] = 0.0
    return layers
