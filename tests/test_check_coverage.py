"""Coverage ratchet rules (dev/check_coverage.py) and the committed floors."""

from __future__ import annotations

import json

from conftest import ROOT, load_module

cc = load_module("check_coverage", ROOT / "dev" / "check_coverage.py")
T = cc.TOTAL


def test_new_file_must_be_full():
    assert cc.check({"src/a.py": 100.0}, 100.0, {T: 0}) == []
    errs = cc.check({"src/new.py": 99.5}, 99.5, {T: 0})
    assert len(errs) == 1 and "new files must be at 100%" in errs[0]


def test_file_and_total_may_not_drop_below_floor():
    errs = cc.check({"src/a.py": 49.9}, 49.9, {T: 50, "src/a.py": 50})
    assert len(errs) == 2
    assert cc.check({"src/a.py": 50.0}, 50.0, {T: 50, "src/a.py": 50}) == []


def test_stale_floors_fail():
    errs = cc.check({"src/a.py": 100.0}, 100.0, {T: 0, "src/a.py": 40, "src/gone.py": 10})
    assert any("now at 100%" in e for e in errs)
    assert any("no longer exists" in e for e in errs)


def test_update_only_raises_and_drops():
    floors = {T: 30, "src/a.py": 60, "src/b.py": 10, "src/full.py": 90, "src/gone.py": 5}
    files = {"src/a.py": 40.0, "src/b.py": 25.7, "src/full.py": 100.0, "src/new.py": 50.0}
    new = cc.raised(files, 31.9, floors)
    assert new == {T: 30, "src/a.py": 60, "src/b.py": 25}


def test_update_keeps_slack_for_platform_files():
    path = next(p for p in cc.SLACK if p != T)
    new = cc.raised({path: 80.4}, 80.4, {T: 0, path: 0})
    assert new[path] == 80 - cc.SLACK[path]
    assert new[T] == 80 - cc.SLACK[T]


def test_committed_floors_are_well_formed():
    floors = json.loads(cc.FLOOR_FILE.read_text(encoding="utf-8"))
    assert T in floors
    for path, floor in floors.items():
        assert isinstance(floor, int) and 0 <= floor < 100, (path, floor)
        if path != T:
            assert (ROOT / path).is_file(), f"floor for missing file {path}"
            assert path.startswith(("src/", "tools/")), path
