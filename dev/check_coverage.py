"""Coverage ratchet: coverage may only go up, toward 100%.

Run after the tests:
    python -m coverage run -m pytest tests/
    python dev/check_coverage.py            # check
    python dev/check_coverage.py --update   # raise floors after adding tests

tests/snapshots/coverage_floor.json holds a floor (whole percent, line + branch)
for every file that was under 100% when the ratchet started, plus "_total".
- A file with a floor must not drop below it.
- A file without a floor (new file) must be at 100%.
- A floor for a file that is gone or now at 100% must be removed (--update does it).
- --update only raises floors and removes entries; it never lowers or adds one.

Coverage is measured with -m "not local_data", so it counts only tests that
also run in CI (no vanilla dumps, fonts or Azahar fork). Cover new code with
tests like that. Local (Windows) and CI (Linux) numbers then differ only on
platform branches; SLACK keeps floors for those files a few points lower.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOOR_FILE = ROOT / "tests" / "snapshots" / "coverage_floor.json"
TOTAL = "_total"

# Files that branch on os.name / sys.platform: Windows and Linux runs cover
# different lines. Floors stay this many points under the measured value.
SLACK = {
    TOTAL: 1,
    "src/live_status.py": 3,
    "src/nlpp_paths.py": 3,
    "src/scratch_cleanup.py": 3,
    "tools/restore_azahar_extdata.py": 3,
    "tools/smoke_boot_azahar.py": 3,
}


def measure() -> tuple[dict[str, float], float]:
    """Per-file and total percent from the .coverage data in ROOT."""
    import coverage

    cov = coverage.Coverage(config_file=str(ROOT / ".coveragerc"), data_file=str(ROOT / ".coverage"))
    cov.load()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "coverage.json"
        cov.json_report(outfile=str(out))
        data = json.loads(out.read_text(encoding="utf-8"))
    files = {
        Path(name).as_posix(): f["summary"]["percent_covered"]
        for name, f in data["files"].items()
    }
    return files, data["totals"]["percent_covered"]


def check(files: dict[str, float], total: float, floors: dict[str, int]) -> list[str]:
    errors = []
    if total < floors.get(TOTAL, 0):
        errors.append(f"total {total:.2f}% is below the floor {floors[TOTAL]}%")
    for path, pct in sorted(files.items()):
        floor = floors.get(path)
        if floor is None and pct < 100:
            errors.append(f"{path}: {pct:.2f}% (new files must be at 100%)")
        elif floor is not None and pct < floor:
            errors.append(f"{path}: {pct:.2f}% is below its floor {floor}%")
    for path in sorted(floors):
        if path == TOTAL:
            continue
        if path not in files:
            errors.append(f"{path}: has a floor but no longer exists (run --update)")
        elif files[path] >= 100:
            errors.append(f"{path}: now at 100%, remove its floor (run --update)")
    return errors


def raised(files: dict[str, float], total: float, floors: dict[str, int]) -> dict[str, int]:
    """New floors: raised to current coverage, entries at 100% or deleted dropped."""
    def target(path: str, pct: float) -> int:
        return max(0, math.floor(pct) - SLACK.get(path, 0))

    new = {TOTAL: max(floors.get(TOTAL, 0), target(TOTAL, total))}
    for path, floor in floors.items():
        if path == TOTAL or path not in files or files[path] >= 100:
            continue
        new[path] = max(floor, target(path, files[path]))
    return new


def load_floors() -> dict[str, int]:
    return json.loads(FLOOR_FILE.read_text(encoding="utf-8"))


def save_floors(floors: dict[str, int]) -> None:
    body = {TOTAL: floors[TOTAL], **{k: floors[k] for k in sorted(floors) if k != TOTAL}}
    FLOOR_FILE.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--update", action="store_true", help="raise floors to current coverage")
    args = ap.parse_args(argv)

    files, total = measure()
    floors = load_floors()
    print(f"[coverage] total {total:.2f}% (floor {floors.get(TOTAL, 0)}%, goal 100%)")

    if args.update:
        new = raised(files, total, floors)
        for path in sorted(set(floors) | set(new)):
            if floors.get(path) != new.get(path):
                print(f"  {path}: {floors.get(path)} -> {new.get(path, 'removed')}")
        save_floors(new)
        floors = new

    errors = check(files, total, floors)
    for e in errors:
        print(f"  FAIL {e}")
    if errors:
        print("[coverage] ratchet failed. Add tests; floors only go up.")
        return 1
    if not args.update and raised(files, total, floors) != floors:
        print("[coverage] coverage went up: run `python dev/check_coverage.py --update` and commit the floors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
