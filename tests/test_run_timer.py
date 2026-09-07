"""Tests for run_timer elapsed formatting / basic lifecycle."""

from __future__ import annotations

from run_timer import RunTimer, format_elapsed


def test_format_elapsed_seconds():
    assert format_elapsed(0) == "0s"
    assert format_elapsed(12) == "12s"


def test_format_elapsed_minutes_hours():
    assert format_elapsed(65) == "1m05s"
    assert format_elapsed(3723) == "1h02m03s"


def test_run_timer_mark_and_finish(capsys):
    timer = RunTimer("unit-test", heartbeat_s=None)
    timer.mark("checkpoint")
    timer.finish("unit-test OK")
    out = capsys.readouterr().out
    assert "[timer] unit-test started at" in out
    assert "— checkpoint" in out
    assert "[timer] total" in out
    assert "unit-test OK" in out
