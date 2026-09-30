"""Pinned terminal status: in-place progress and a bottom elapsed row."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from live_status import (
    LiveStatus,
    StatusStream,
    colorize_bracket_line,
    render_bar,
    render_percent,
    tag_color,
)


class _Mem:
    encoding = "utf-8"

    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, s: str) -> int:
        self.parts.append(s)
        return len(s)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def test_relax_stdio_errors_swallows_unencodable(monkeypatch):
    from live_status import relax_stdio_errors

    class _Cp1252:
        encoding = "cp1252"
        errors = "strict"

        def reconfigure(self, **kwargs):
            self.errors = kwargs.get("errors", self.errors)

        def write(self, s: str) -> int:
            s.encode(self.encoding, self.errors)
            return len(s)

    out = _Cp1252()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", out)
    relax_stdio_errors()
    out.write("day suffix \u65e5\u76ee")


def test_latest_progress_line_keeps_the_cr_tail():
    from live_status import latest_progress_line

    assert latest_progress_line("\r  one\r  two\n") == "two"
    assert latest_progress_line("only") == "only"


def test_render_bar_docker_style():
    line = render_bar(5, 10, prefix="packages", width=10)
    assert "packages " in line
    assert "[====>" in line
    assert "5/10" in line
    assert "50.0%" in line
    assert "[" + "=" * 10 + "]" in render_bar(10, 10, width=10)


def test_render_percent_clamps_and_names_the_step():
    line = render_percent(42, detail="12/40  profile", width=10)
    assert line.startswith("  overall [")
    assert "42.0%" in line
    assert "profile" in line
    assert "=" * 10 in render_percent(100, width=10)
    assert "0.0%" in render_percent(-5, width=10)


def test_status_stream_keeps_latest_cr_update():
    lines: list[str] = []
    stream = StatusStream(lines.append)
    stream.write("\r  [exact-zlib] first")
    stream.write("\r  [exact-zlib] second")
    assert lines[-1] == "[exact-zlib] second"


def test_status_stream_emit_all_keeps_every_line():
    lines: list[str] = []
    stream = StatusStream(lines.append, emit_all=True)
    stream.write("Traceback\nboom\n")
    assert lines == ["Traceback", "boom"]


def test_plain_log_env_disables_pin(monkeypatch):
    monkeypatch.setenv("NLPP_PLAIN_LOG", "1")
    status = LiveStatus()
    assert status.try_acquire(object()) is False
    assert status.active is False


def test_not_a_tty_stays_plain(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _Mem())
    status = LiveStatus()
    assert status.try_acquire(object()) is False
    assert status.active is False


def test_bracket_lines_keep_a_color_per_tag(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    pack = colorize_bracket_line("[pack] pkg 5245")
    trb = colorize_bracket_line("[trb] overlay")
    fail = colorize_bracket_line("[fail] boom")
    assert tag_color("pack") != tag_color("trb")
    assert f"\033[{tag_color('pack')}m" in pack
    assert f"\033[{tag_color('trb')}m" in trb
    assert pack != trb
    assert "\033[91m" in fail
    assert "[pack] pkg 5245" in pack
    again = colorize_bracket_line("[pack] pkg 5245")
    assert again == pack


def test_paint_pins_bar_jobs_and_elapsed_last(monkeypatch):
    import live_status

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(
        live_status.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((80, 24)),
    )
    raw = _Mem()
    status = LiveStatus()
    status._raw = raw
    status._installed = True
    status._owner = SimpleNamespace(
        label="PNG pack",
        stage="working",
        elapsed_str=lambda: "3s",
    )
    status._progress = (2, 10, "packages")
    status._jobs = {1: "5245 compressing"}
    status._paint_body()
    text = "".join(raw.parts)
    assert "\033[1;23r" in text
    assert "2/10" in text
    assert "5245 compressing" in text
    assert "3s" in text and "PNG pack" in text
    assert text.find("PNG pack") < text.find("3s")
    assert text.find("3s") < text.find("2/10")
    assert text.find("3s") < text.find("5245 compressing")
    pin = text.split("\033[2K", 1)[1]
    assert "2/10" in pin and "5245 compressing" in pin and "3s" in pin
    assert "\033[32m" in pin
    assert "\033[33m" in pin
    status._paint_body()
    assert "\0337" in "".join(raw.parts)


def test_overall_stays_above_the_timer_when_the_pin_is_short(monkeypatch):
    import live_status

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(
        live_status.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((120, 10)),
    )
    raw = _Mem()
    status = LiveStatus()
    status._raw = raw
    status._installed = True
    status._owner = SimpleNamespace(
        label="gold rebuild",
        stage="profile",
        elapsed_str=lambda: "9s",
    )
    status._progress = (2, 10, "packages")
    status._overall = (46.0, "12/40  profile")
    status._jobs = {1: "[pack] pkg 5245"}
    status._paint_body()
    text = "".join(raw.parts)
    assert "46.0%" in text
    assert "profile" in text
    assert "9s" in text
    assert "[pack] pkg 5245" in text
    assert text.find("gold rebuild") < text.find("9s")
    assert text.find("9s") < text.find("46.0%")
    assert text.find("9s") < text.find("[pack] pkg 5245")
    assert "2/10" not in text
    pin = text.split("\033[2K", 1)[1]
    assert f"\033[{tag_color('pack')}m" in pin


def test_pin_clock_follows_drop_start_not_the_step_timer(monkeypatch):
    import live_status
    import run_timer

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("NLPP_T0", "1000")
    monkeypatch.setattr(run_timer.time, "time", lambda: 2910.0)
    monkeypatch.setattr(
        live_status.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((120, 24)),
    )
    raw = _Mem()
    status = LiveStatus()
    status._raw = raw
    status._installed = True
    status._owner = SimpleNamespace(
        label="CIA patcher",
        stage="rebuilding patched CIA",
        elapsed_str=lambda: "3s",
    )
    status._overall = (90.0, "6/6  rebuild CIA")
    status._paint_body()
    text = "".join(raw.parts)
    assert "31m50s" in text
    assert text.find("31m50s") < text.find("90.0%")
    pin = text.split("\033[2K", 1)[1]
    assert "3s" not in pin


def test_live_mark_does_not_scroll_a_new_timer_line(monkeypatch, capsys):
    import run_timer

    logs: list[str] = []
    monkeypatch.setattr(run_timer.live, "try_acquire", lambda timer: True)
    monkeypatch.setattr(run_timer.live, "log", lambda text: logs.append(text))
    monkeypatch.setattr(run_timer.live, "refresh", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_timer.live, "release", lambda timer: None)
    timer = run_timer.RunTimer("unit-test", heartbeat_s=None)
    timer.mark("checkpoint")
    timer.finish("unit-test OK")
    out = capsys.readouterr().out
    assert "checkpoint" not in out
    assert "still running" not in out
    assert any("checkpoint" in line for line in logs)
    assert "[timer] total" in out
    assert "unit-test OK" in out
