#!/usr/bin/env python3
"""Regenerate ab_test/patches/azahar-*.patch from the azahar-3ds-accurate fork.

The fork (github.com/czyrustuazon/azahar-3ds-accurate, local checkout
../azahar-3ds-accurate, branch main) is the source of truth for
hardware-accurate Azahar changes. Branch upstream holds pristine upstream
snapshots, so the export is diff(merge-base(main, upstream)..main).
These patch files are exports of it for make.ps1 build-azahar.

  python tools/export_azahar_patches.py            # write the files
  python tools/export_azahar_patches.py --check    # exit 1 if they are stale
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / "ab_test" / "patches"
FORK_URL = "https://github.com/czyrustuazon/azahar-3ds-accurate"
BRANCH = "main"
UPSTREAM = "upstream"  # pristine azahar-emu/azahar snapshots (origin/upstream in a fresh clone)

# patch file -> (header, fork paths it covers)
EXPORTS = {
    "azahar-openlinkfile.patch": (
        "File::OpenLinkFile clones the source session (NLPP extra-data hang).",
        ["src/core/hle/service/fs/"],
    ),
    "azahar-nlpp-emu.patch": (
        "NLPP_EMU_* hardware-crash replays + FAR/DFSR in the exception report.\n"
        "Apply after azahar-openlinkfile.patch.\n"
        "Used by ab_test launches and tools/smoke_boot_azahar.py --inject.",
        ["src/core/CMakeLists.txt", "src/core/arm/"],
    ),
}


def fork_dir() -> Path:
    return Path(os.environ.get("NLPP_AZAHAR_FORK") or ROOT.parent / "azahar-3ds-accurate")


def _git(fork: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(fork), *args], check=True, capture_output=True, text=True
    ).stdout


def render(fork: Path) -> dict[str, str]:
    """Patch file name -> expected contents."""
    upstream = UPSTREAM
    if subprocess.run(["git", "-C", str(fork), "rev-parse", "--verify", "-q", upstream],
                      capture_output=True).returncode != 0:
        upstream = f"origin/{UPSTREAM}"
    base = _git(fork, "merge-base", BRANCH, upstream).strip()
    out = {}
    for name, (header, paths) in EXPORTS.items():
        diff = _git(fork, "diff", "--full-index", f"{base}..{BRANCH}", "--", *paths)
        out[name] = (
            f"{header}\nSource: {FORK_URL} ({BRANCH} @ {_git(fork, 'rev-parse', '--short', BRANCH).strip()})\n"
            f"Base: fork branch {UPSTREAM} @ {base[:9]} (pristine upstream Azahar)\n\n{diff}"
        )
    return out


def _body(text: str) -> str:
    """The diff itself: header lines and line endings do not count."""
    text = text.replace("\r\n", "\n")
    i = text.find("diff --git")
    return text[i:] if i >= 0 else ""


def stale(fork: Path) -> list[str]:
    bad = []
    for name, text in render(fork).items():
        path = PATCHES / name
        if not path.is_file() or _body(path.read_text(encoding="utf-8")) != _body(text):
            bad.append(name)
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    fork = fork_dir()
    if not (fork / ".git").exists():
        print(f"no fork checkout at {fork} (git clone {FORK_URL} there, or set NLPP_AZAHAR_FORK)",
              file=sys.stderr)
        return 2
    if args.check:
        bad = stale(fork)
        for name in bad:
            print(f"stale: ab_test/patches/{name}", file=sys.stderr)
        return 1 if bad else 0
    for name, text in render(fork).items():
        (PATCHES / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote ab_test/patches/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
