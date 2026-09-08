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


def test_run_timer_cli_formats_elapsed():
    import subprocess
    import sys
    import time
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "run_timer.py"
    t0 = int(time.time()) - 65
    out = subprocess.check_output(
        [sys.executable, str(src), str(t0)],
        text=True,
    ).strip()
    assert out in ("1m04s", "1m05s", "1m06s")
