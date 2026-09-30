"""Overall Drop percent: weighted steps, and a 0–80 / 80–100 split across processes."""

from __future__ import annotations

import overall_progress
from overall_progress import OverallBar


def test_plain_log_prints_only_when_the_integer_percent_changes(capsys, monkeypatch):
    monkeypatch.delenv("NLPP_OVERALL_LO", raising=False)
    monkeypatch.delenv("NLPP_OVERALL_HI", raising=False)
    bar = OverallBar([("pack", 100)])
    bar.goto("pack", 0.0)
    bar.goto("pack", 0.01)
    bar.goto("pack", 0.015)
    bar.goto("pack", 1.0)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "overall" in ln]
    assert len(lines) == 3
    assert "0.0%" in lines[0]
    assert "1.0%" in lines[1]
    assert "100.0%" in lines[2]
    assert "1/1  pack" in lines[1]


def test_span_maps_onto_the_drop_slice(capsys, monkeypatch):
    monkeypatch.setenv("NLPP_OVERALL_LO", "80")
    monkeypatch.setenv("NLPP_OVERALL_HI", "100")
    bar = OverallBar([("a", 1), ("b", 1)])
    bar.goto("a", 1.0)
    assert "90.0%" in capsys.readouterr().out


def test_reversed_span_is_swapped(monkeypatch):
    monkeypatch.setenv("NLPP_OVERALL_LO", "100")
    monkeypatch.setenv("NLPP_OVERALL_HI", "80")
    bar = OverallBar([("a", 1)])
    assert bar.lo == 80.0
    assert bar.hi == 100.0


def test_unknown_step_does_not_print(capsys, monkeypatch):
    monkeypatch.delenv("NLPP_OVERALL_LO", raising=False)
    monkeypatch.delenv("NLPP_OVERALL_HI", raising=False)
    bar = OverallBar([("a", 1)])
    bar.goto("missing", 1.0)
    assert capsys.readouterr().out == ""


def test_scope_unbinds(capsys, monkeypatch):
    monkeypatch.delenv("NLPP_OVERALL_LO", raising=False)
    monkeypatch.delenv("NLPP_OVERALL_HI", raising=False)
    with overall_progress.overall_scope([("hash", 1)]):
        overall_progress.tick("hash", 1.0)
    overall_progress.tick("hash", 1.0)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "overall" in ln]
    assert len(lines) == 1
    assert overall_progress._bound is None


def test_live_updates_the_pin_instead_of_printing(capsys, monkeypatch):
    calls: list[tuple[float, str]] = []
    monkeypatch.setattr(overall_progress.live, "_installed", True)
    monkeypatch.setattr(
        overall_progress.live,
        "set_overall",
        lambda pct, detail="": calls.append((pct, detail)),
    )
    monkeypatch.delenv("NLPP_OVERALL_LO", raising=False)
    monkeypatch.delenv("NLPP_OVERALL_HI", raising=False)
    bar = OverallBar([("a", 1), ("b", 3)])
    bar.goto("b", 0.0)
    assert capsys.readouterr().out == ""
    assert calls[-1][0] == 25.0
    assert "2/2  b" in calls[-1][1]
