#!/usr/bin/env python3
"""Integrate NLPPATCH community scripts into EngPatcher ``rebuild_dbin2``.

Copies the historical ~28% community layer (Rinko/Nene + overlap) from
``vendor/NLPPATCH/release/romfs/script/bin/script`` into
``rebuild_dbin2/script/``, then removes leftover machine-translated ``a*``/``k*``
so Drop no longer needs a separate vendor tree.

Policy after integrate (see ``src/script_inject.py``):
  - Manaka ``t*`` / EngPatcher ``p*`` stay EngPatcher (never overwritten)
  - NLPPATCH ``a*``/``k*`` (and any other NLPPATCH stems not covered above)
    live in ``rebuild_dbin2/script/``
  - Remaining routes stay Japanese (file absent → ROM)

  python tools/integrate_nlppatch_into_rebuild.py
  python tools/integrate_nlppatch_into_rebuild.py --src path\\to\\scripts
  python tools/integrate_nlppatch_into_rebuild.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = (
    ROOT / "vendor" / "NLPPATCH" / "release" / "romfs" / "script" / "bin" / "script"
)
DEFAULT_DST = ROOT / "rebuild_dbin2" / "script"
MANIFEST = ROOT / "assets" / "nlppatch" / "stems.json"
README = ROOT / "assets" / "nlppatch" / "README.md"
PACKS = ("NLP_01", "NLP_02", "script")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--dst", type=Path, default=DEFAULT_DST)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    src = args.src.resolve()
    dst = args.dst.resolve()
    if not src.is_dir():
        print(f"NLPPATCH script dir missing: {src}", file=sys.stderr)
        print("Run: python tools/fetch_nlppatch_release.py", file=sys.stderr)
        return 1

    community = sorted(src.glob("*.dbin2"))
    if len(community) < 100:
        print(f"expected ~169 scripts, found {len(community)} in {src}", file=sys.stderr)
        return 1

    # Never overwrite Manaka / EngPatcher common from NLPPATCH.
    protect = set()
    for p in dst.glob("t*.dbin2"):
        protect.add(p.stem)
    for p in dst.glob("p*.dbin2"):
        protect.add(p.stem)

    to_copy: list[Path] = []
    skipped_protect: list[str] = []
    for f in community:
        if f.stem in protect:
            skipped_protect.append(f.stem)
            continue
        to_copy.append(f)

    community_stems = {f.stem for f in to_copy}
    # Also record protected overlap for the manifest (informational).
    overlap = sorted(skipped_protect)

    # Remove MT a*/k* in script pack that are not in the community set.
    to_delete: list[Path] = []
    if dst.is_dir():
        for pref in ("a", "k"):
            for f in dst.glob(f"{pref}*.dbin2"):
                if f.stem not in community_stems:
                    to_delete.append(f)

    # Strip a*/k* from NLP_01 / NLP_02 (NLPPPATCH never shipped those packs;
    # leftover MT there must not be injectable).
    nlp_delete: list[Path] = []
    rebuild_root = dst.parent
    for pack in ("NLP_01", "NLP_02"):
        pack_dir = rebuild_root / pack
        if not pack_dir.is_dir():
            continue
        for pref in ("a", "k"):
            nlp_delete.extend(pack_dir.glob(f"{pref}*.dbin2"))

    print(f"[integrate] src={src} ({len(community)} files)")
    print(f"[integrate] copy {len(to_copy)} community scripts -> {dst}")
    print(f"[integrate] skip {len(overlap)} NLPPATCH stems protected (t*/p* EngPatcher)")
    print(f"[integrate] delete {len(to_delete)} non-community a*/k* from script/")
    print(f"[integrate] delete {len(nlp_delete)} a*/k* from NLP_01/NLP_02")

    if args.dry_run:
        print("[integrate] dry-run — no writes")
        return 0

    dst.mkdir(parents=True, exist_ok=True)
    for f in to_copy:
        shutil.copy2(f, dst / f.name)

    for f in to_delete + nlp_delete:
        f.unlink(missing_ok=True)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    by_prefix: dict[str, list[str]] = {"a": [], "k": [], "p": [], "t": [], "other": []}
    for stem in sorted(community_stems):
        pref = stem[0].lower() if stem else "?"
        by_prefix.setdefault(pref if pref in by_prefix else "other", []).append(stem)

    MANIFEST.write_text(
        json.dumps(
            {
                "description": (
                    "Community NLPPATCH-era scripts integrated into rebuild_dbin2/script. "
                    "Source historically LovePlusProject/NLPPATCH; mirrored via NLPPCTR when "
                    "the release zip 404s. Manaka t* and EngPatcher p* are NOT in this set."
                ),
                "count": len(community_stems),
                "stems": sorted(community_stems),
                "by_prefix": {k: v for k, v in by_prefix.items() if v},
                "nlppatch_overlap_skipped_t_p": overlap,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    README.write_text(
        "\n".join(
            [
                "# Community script layer (ex-NLPPATCH)",
                "",
                "The old ~28% community English scripts live **inside** EngPatcher now:",
                "",
                "- Binaries: `rebuild_dbin2/script/{a,k}*.dbin2` (stems listed in `stems.json`)",
                "- Inject: `src/script_inject.py` (Manaka `t*` + common `p*` override; then these)",
                "",
                "You do **not** need `vendor/NLPPATCH` or a network fetch to Drop a CIA.",
                "",
                "Re-import from an offline dump / NLPPCTR (maintainer only):",
                "",
                "```bash",
                "python tools/fetch_nlppatch_release.py          # optional hydrate to vendor/",
                "python tools/integrate_nlppatch_into_rebuild.py",
                "```",
                "",
                "Credits: LovePlusProject/NLPPATCH contributors (see their repo credits).",
                "",
            ]
        ),
        encoding="utf-8",
    )

    # Coverage smoke check
    sys.path.insert(0, str(ROOT / "src"))
    from script_inject import coverage_summary, nlppatch_script_dir  # noqa: E402

    # Clear cached stems if module was partially imported earlier in-process
    import script_inject as si

    si._nlppatch_stems = None
    cov = coverage_summary()
    print(f"[integrate] wrote {MANIFEST.relative_to(ROOT)}")
    print(f"[integrate] coverage={cov}")
    if nlppatch_script_dir() is not None:
        print(
            "[integrate] note: vendor/NLPPATCH still present on disk "
            "(optional; inject prefers rebuild community files after script_inject update)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
