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


def test_run_timer_cli_now():
    import subprocess
    import sys
    import time
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "run_timer.py"
    before = int(time.time())
    out = subprocess.check_output(
        [sys.executable, str(src), "--now"],
        text=True,
    ).strip()
    after = int(time.time())
    stamp = int(out)
    assert before <= stamp <= after


def test_cmd_drop_timer_tempfile_roundtrip(tmp_path):
    """Drop bat start/elapsed must not use FOR /F around quoted python -c."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    import pytest

    if os.name != "nt":
        pytest.skip("cmd.exe quoting")

    src = Path(__file__).resolve().parents[1] / "src" / "run_timer.py"
    t0_file = tmp_path / "nlpp_t0.txt"
    elapsed_file = tmp_path / "nlpp_elapsed.txt"
    bat = tmp_path / "timer.bat"
    bat.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal EnableExtensions EnableDelayedExpansion",
                f'set "PYTHON={sys.executable}"',
                f'set "TIMER={src}"',
                f'set "NLPP_T0_FILE={t0_file}"',
                f'set "NLPP_ELAPSED_FILE={elapsed_file}"',
                'set "NLPP_T0="',
                'set "NLPP_ELAPSED="',
                '"%PYTHON%" "%TIMER%" --now > "%NLPP_T0_FILE%"',
                'set /p NLPP_T0=<"%NLPP_T0_FILE%"',
                '"%PYTHON%" "%TIMER%" !NLPP_T0! > "%NLPP_ELAPSED_FILE%"',
                'set /p NLPP_ELAPSED=<"%NLPP_ELAPSED_FILE%"',
                "echo T0=!NLPP_T0!",
                "echo ELAPSED=!NLPP_ELAPSED!",
            ]
        )
        + "\r\n",
        encoding="utf-8",
    )
    out = subprocess.check_output(
        ["cmd.exe", "/c", str(bat)],
        text=True,
        stderr=subprocess.STDOUT,
    )
    lines = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    assert lines["T0"].isdigit()
    assert lines["ELAPSED"].endswith("s")
