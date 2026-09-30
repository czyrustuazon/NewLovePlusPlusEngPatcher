"""Pinned console status, in the style of a Docker pull.

On a real terminal one bottom row holds the progress bar, the file being
read, and the elapsed time. Log lines scroll above it. A line that starts
with ``[tag]`` takes a color of its own (``[pack]`` and ``[trb]`` differ).
Piped output and ``NLPP_PLAIN_LOG=1`` keep the ordinary line-by-line log
(CI, pytest, redirected files). ``NO_COLOR`` turns the colors off.
"""

from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import threading
import time
from collections.abc import Callable
from typing import TextIO


def plain_log_requested() -> bool:
    return os.environ.get("NLPP_PLAIN_LOG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def enable_vt() -> bool:
    """Turn on ANSI sequences in the Windows console. No-op elsewhere."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        enable = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        for std_handle in (-11, -12):  # stdout, stderr
            handle = kernel32.GetStdHandle(std_handle)
            mode = ctypes.c_uint()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            if mode.value & enable:
                continue
            if not kernel32.SetConsoleMode(handle, mode.value | enable):
                return False
        return True
    except (AttributeError, OSError):
        return False


def relax_stdio_errors() -> None:
    """Don't abort on a cp1252 console when a log line has characters it can't encode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def latest_progress_line(chunk: str) -> str:
    """Last visible line from a chunk that may use ``\\r`` redraws."""
    last = ""
    for line in chunk.replace("\r", "\n").splitlines():
        if line.strip():
            last = line.strip()
    return last


def render_bar(done: int, total: int, *, prefix: str = "", width: int = 28) -> str:
    """Docker-style ``[=====>     ]  2/10 ( 20.0%)`` line."""
    total = max(1, int(total))
    done = max(0, min(int(done), total))
    frac = done / total
    filled = int(width * frac)
    if filled <= 0:
        bar = " " * width
    elif filled >= width:
        bar = "=" * width
    else:
        bar = "=" * (filled - 1) + ">" + " " * (width - filled)
    label = f"{prefix} " if prefix else ""
    return f"  {label}[{bar}] {done}/{total} ({frac * 100:5.1f}%)"


def render_percent(pct: float, *, detail: str = "", width: int = 28) -> str:
    """One bar for the whole job: ``overall [====>   ]  42.0%  12/40  profile``."""
    pct = min(100.0, max(0.0, float(pct)))
    width = max(1, int(width))
    filled = int(width * pct / 100.0)
    if filled <= 0:
        bar = " " * width
    elif filled >= width:
        bar = "=" * width
    else:
        bar = "=" * (filled - 1) + ">" + " " * (width - filled)
    tail = f"  {detail}" if detail else ""
    return f"  overall [{bar}] {pct:5.1f}%{tail}"


def _bar_body(frac: float, width: int) -> str:
    width = max(1, int(width))
    frac = min(1.0, max(0.0, float(frac)))
    filled = int(width * frac)
    if filled <= 0:
        return " " * width
    if filled >= width:
        return "=" * width
    return "=" * (filled - 1) + ">" + " " * (width - filled)


_BRACKET = re.compile(r"\[([^\[\]\r\n]{1,48})\]")
_ANSI = re.compile(r"\033\[[0-9;]*m")

# Common Drop tags stay far apart. Anything else hashes into the same palette.
_TAG_COLOR = {
    "pack": "36",
    "rebuild": "35",
    "bake": "32",
    "trb": "34",
    "timer": "33",
    "extract": "96",
    "romfs": "95",
    "inject": "94",
    "cia": "93",
    "images": "92",
    "hash": "37",
    "vanilla": "96",
    "exact-zlib": "36",
    "log": "90",
    "progress": "96",
    "fetch": "94",
    "warn": "33",
    "warning": "33",
    "fail": "91",
    "error": "91",
}
_TAG_PALETTE = ("36", "33", "35", "32", "34", "96", "93", "95", "92", "94", "37")


def colors_enabled() -> bool:
    return os.environ.get("NO_COLOR", "").strip() == ""


def tag_color(tag: str) -> str:
    key = tag.strip().lower()
    if "fail" in key or key in {"error", "err"}:
        return "91"
    known = _TAG_COLOR.get(key)
    if known is not None:
        return known
    total = sum(ord(ch) for ch in key)
    return _TAG_PALETTE[total % len(_TAG_PALETTE)]


def colorize_bracket_line(line: str) -> str:
    """Paint a whole ``[tag] ...`` line. The tag picks the color."""
    if not line or not colors_enabled() or "\033[" in line:
        return line
    match = _BRACKET.search(line)
    if match is None:
        return line
    return f"\033[{tag_color(match.group(1))}m{line}\033[0m"


def colorize_chunk(text: str) -> str:
    """Color each complete line that carries a ``[tag]``."""
    if not text or not colors_enabled() or "[" not in text:
        return text
    parts = text.split("\n")
    for i, part in enumerate(parts):
        if "[" in part:
            parts[i] = colorize_bracket_line(part)
    return "\n".join(parts)


def visible_len(text: str) -> int:
    return len(_ANSI.sub("", text))


def fit_visible(text: str, width: int) -> str:
    """Cut to ``width`` visible columns without splitting an ANSI sequence."""
    if width <= 0:
        return ""
    if visible_len(text) <= width:
        return text
    out: list[str] = []
    seen = 0
    i = 0
    limit = max(1, width - 1)
    while i < len(text) and seen < limit:
        match = _ANSI.match(text, i)
        if match:
            out.append(match.group())
            i = match.end()
            continue
        out.append(text[i])
        seen += 1
        i += 1
    out.append("…")
    if "\033[" in text:
        out.append("\033[0m")
    return "".join(out)


def _clip(original: str, shown: str) -> str:
    shown = shown.rstrip()
    if not shown or shown == original:
        return shown
    if len(shown) == 1:
        return "…"
    return shown[:-1] + "…"


def color_bar(frac: float, width: int) -> str:
    """``[====>    ]`` with the fill in green and the track in gray."""
    body = _bar_body(frac, width)
    if not colors_enabled():
        return f"[{body}]"
    painted: list[str] = []
    for ch in body:
        if ch == "=":
            painted.append(f"\033[32m{ch}")
        elif ch == ">":
            painted.append(f"\033[92m{ch}")
        else:
            painted.append(f"\033[90m{ch}")
    return "\033[90m[\033[0m" + "".join(painted) + "\033[0m\033[90m]\033[0m"


def paint(text: str, code: str) -> str:
    if not text or not colors_enabled():
        return text
    return f"\033[{code}m{text}\033[0m"


class StatusStream:
    """Turn ``\\r`` / newline progress into the latest visible line.

    Worker processes write here instead of the console so their updates can
    sit on one pinned row instead of scrolling.
    """

    encoding = "utf-8"

    def __init__(self, emit: Callable[[str], None], *, emit_all: bool = False) -> None:
        self._emit = emit
        self._emit_all = emit_all
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        if not s:
            return 0
        with self._lock:
            self._buf += s
            if "\r" not in self._buf and "\n" not in self._buf:
                return len(s)
            parts = re.split(r"[\r\n]", self._buf)
            ended = s.endswith("\r") or s.endswith("\n")
            if ended:
                self._buf = ""
                shown = [p.strip() for p in parts if p.strip()]
            else:
                self._buf = parts[-1]
                tail = parts[-1].strip()
                shown = [tail] if tail else [p.strip() for p in parts[:-1] if p.strip()]
            if not shown:
                return len(s)
            if self._emit_all and ended:
                for line in shown:
                    self._emit(line)
            else:
                self._emit(shown[-1])
        return len(s)

    def flush(self) -> None:
        with self._lock:
            pending = self._buf.strip()
            self._buf = ""
        if pending:
            self._emit(pending)

    def isatty(self) -> bool:
        return False


class _LockedStream:
    """Serialize log writes with footer repaints."""

    def __init__(self, status: LiveStatus) -> None:
        self._status = status

    def write(self, s: str) -> int:
        if not s:
            return 0
        with self._status._lock:
            self._status._write_raw(colorize_chunk(s))
            self._status._flush()
            if "\n" in s and self._status._installed:
                self._status._paint_unlocked()
        return len(s)

    def flush(self) -> None:
        with self._status._lock:
            self._status._flush()

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return self._status._raw.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._status._raw, "encoding", None) or "utf-8"

    def __getattr__(self, name: str):
        return getattr(self._status._raw, name)


class LiveStatus:
    """One pinned block at the bottom of the terminal."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._timers: list[object] = []
        self._owner: object | None = None
        self._jobs: dict[object, str] = {}
        self._progress: tuple[int, int, str] | None = None
        self._overall: tuple[float, str] | None = None
        self._installed = False
        self._anchored = False
        self._pin_rows = 0
        self._last_paint = 0.0
        self._raw: TextIO = sys.stdout
        self._wrapper: _LockedStream | None = None
        self._atexit = False

    @property
    def active(self) -> bool:
        return self._installed

    @property
    def owner(self) -> object | None:
        return self._owner

    def try_acquire(self, timer: object) -> bool:
        """Pin ``timer`` on the bottom row. False keeps the plain log."""
        if plain_log_requested():
            return False
        if not self._installed:
            out = sys.stdout
            is_tty = getattr(out, "isatty", lambda: False)()
            if not is_tty or not enable_vt():
                return False
            self._timers.append(timer)
            self._owner = timer
            self._install(out)
            self.refresh(force=True)
            return True
        self._timers.append(timer)
        self._owner = timer
        self._jobs.clear()
        self._progress = None
        self.refresh(force=True)
        return True

    def release(self, timer: object) -> None:
        if timer in self._timers:
            self._timers.remove(timer)
        if self._owner is timer:
            self._owner = self._timers[-1] if self._timers else None
            self._jobs.clear()
            self._progress = None
        if not self._timers:
            self.shutdown()
        else:
            self.refresh(force=True)

    def shutdown(self) -> None:
        """Restore the cursor and scroll region. Safe to call twice."""
        with self._lock:
            if not self._installed:
                return
            self._installed = False
            raw = self._raw
            try:
                size = shutil.get_terminal_size(fallback=(80, 24))
                rows = size.lines
                n = max(1, self._pin_rows)
                start = max(1, rows - n + 1)
                raw.write(f"\033[?25h\033[r\033[{start};1H\033[J")
                raw.flush()
            except (OSError, UnicodeError, ValueError):
                pass
            self._anchored = False
            self._pin_rows = 0
            if self._wrapper is not None and sys.stdout is self._wrapper:
                sys.stdout = raw

    def set_progress(self, done: int, total: int, prefix: str = "") -> None:
        if not self._installed:
            return
        with self._lock:
            self._progress = (done, total, prefix)
        self.refresh()

    def set_overall(self, pct: float, detail: str = "") -> None:
        """Percent of the whole Drop. Kept even when a nested timer takes the pin."""
        if not self._installed:
            return
        with self._lock:
            self._overall = (float(pct), detail)
        self.refresh()

    def set_job(self, key: object, text: str) -> None:
        if not self._installed:
            return
        clean = " ".join(text.split())
        if len(clean) > 180:
            clean = clean[:179] + "…"
        with self._lock:
            self._jobs.pop(key, None)
            self._jobs[key] = clean
        self.refresh()

    def clear_job(self, key: object) -> None:
        if not self._installed:
            return
        with self._lock:
            self._jobs.pop(key, None)
        self.refresh(force=True)

    def clear_jobs(self) -> None:
        if not self._installed:
            return
        with self._lock:
            self._jobs.clear()
        self.refresh(force=True)

    def log(self, text: str) -> None:
        """One permanent line above the pin (errors, stage changes)."""
        if not text:
            return
        if not self._installed:
            print(text, flush=True)
            return
        with self._lock:
            self._write_raw(colorize_bracket_line(text) + "\n")
            self._flush()
            self._paint_unlocked()

    def refresh(self, *, force: bool = False) -> None:
        if not self._installed:
            return
        now = time.monotonic()
        with self._lock:
            if not force and (now - self._last_paint) < 0.1:
                return
            self._paint_unlocked()
            self._last_paint = time.monotonic()

    def _install(self, out: TextIO) -> None:
        self._raw = out
        self._wrapper = _LockedStream(self)
        self._installed = True
        self._anchored = False
        self._pin_rows = 0
        sys.stdout = self._wrapper
        if not self._atexit:
            atexit.register(self.shutdown)
            self._atexit = True
        self._write_raw("\033[?25l")
        self._flush()

    def _clock(self) -> tuple[str, str]:
        """Elapsed time, and the run name that leads the row."""
        owner = self._owner
        if owner is None:
            return "", ""
        label = str(getattr(owner, "label", "") or "")
        # Drop stamps NLPP_T0 once. Step timers restart; the row must not.
        from run_timer import drop_elapsed_str

        elapsed = drop_elapsed_str()
        if elapsed is None:
            elapsed = owner.elapsed_str()  # type: ignore[attr-defined]
        return elapsed, label

    def _compose(self, cols: int, rows: int) -> list[str]:
        del rows  # one row, whatever the height (callers still require rows >= 8)
        line = self._status_line(cols)
        if not line:
            return []
        return [fit_visible(line, max(1, cols - 1))]

    def _status_line(self, cols: int) -> str:
        """Run name, elapsed time, bar, then the current file, on one row.

        The file text gives up columns first. The clock and the bar stay.
        """
        elapsed, label = self._clock()
        job = ""
        if self._jobs:
            job = list(self._jobs.values())[-1]
        frac: float | None = None
        count = ""
        detail = ""
        if self._overall is not None:
            pct, detail = self._overall
            frac = pct / 100.0
            count = f"{pct:.1f}%"
        elif self._progress is not None:
            done, total, prefix = self._progress
            total_n = max(1, int(total))
            done_n = max(0, min(int(done), total_n))
            frac = done_n / total_n
            count = f"{done_n}/{total_n}"
            detail = prefix
        if frac is None and not elapsed and not label and not job:
            return ""
        bar_w = 18 if cols >= 100 else (12 if cols >= 72 else 8)

        def _joined(width: int, detail_s: str, job_s: str) -> list[str]:
            parts: list[str] = []
            if label:
                parts.append(label)
            if elapsed:
                parts.append(elapsed)
            if frac is not None:
                parts.append("[" + ("x" * width) + "]")
                if count:
                    parts.append(count)
            if detail_s:
                parts.append(detail_s)
            if job_s:
                parts.append(job_s)
            return parts

        def _span(parts: list[str]) -> int:
            if not parts:
                return 0
            return 2 + sum(len(part) for part in parts) + 2 * (len(parts) - 1)

        while frac is not None and bar_w > 4 and _span(_joined(bar_w, "", "")) > cols - 1:
            bar_w -= 1
        detail_s = detail
        job_s = job
        while _span(_joined(bar_w, detail_s, job_s)) > cols - 1 and (detail_s or job_s):
            if len(job_s) >= len(detail_s) and job_s:
                job_s = job_s[:-1]
            else:
                detail_s = detail_s[:-1]
        detail_s = _clip(detail, detail_s)
        job_s = _clip(job, job_s)
        pieces: list[str] = []
        if label:
            pieces.append(paint(label, "33"))
        if elapsed:
            pieces.append(paint(elapsed, "33"))
        if frac is not None:
            pieces.append(color_bar(frac, bar_w))
            if count:
                pieces.append(paint(count, "1;97"))
        if detail_s:
            pieces.append(paint(detail_s, "36"))
        if job_s:
            if "[" in job_s:
                pieces.append(colorize_bracket_line(job_s))
            else:
                pieces.append(paint(job_s, "37"))
        return "  " + "  ".join(pieces)

    def _paint_unlocked(self) -> None:
        if not self._installed:
            return
        try:
            self._paint_body()
        except (OSError, UnicodeError, ValueError):
            return

    def _paint_body(self) -> None:
        size = shutil.get_terminal_size(fallback=(80, 24))
        cols, rows = size.columns, size.lines
        if rows < 8:
            return
        lines = self._compose(cols, rows)
        if not lines:
            return
        n = len(lines)
        bottom = max(1, rows - n)
        if self._anchored and n < self._pin_rows:
            old_bottom = max(1, rows - self._pin_rows)
            for row in range(old_bottom + 1, bottom + 1):
                self._write_raw(f"\033[{row};1H\033[2K")
        if not self._anchored:
            self._write_raw("\n" * n)
        elif n > self._pin_rows:
            self._write_raw("\n" * (n - self._pin_rows))
        growing = (not self._anchored) or n != self._pin_rows
        if growing:
            self._write_raw(f"\033[1;{bottom}r\033[{bottom};1H")
            self._anchored = True
            self._pin_rows = n
            self._draw_pin(lines, bottom)
            self._write_raw(f"\033[{bottom};1H")
            self._flush()
            return
        self._write_raw("\0337")
        self._write_raw(f"\033[1;{bottom}r")
        self._draw_pin(lines, bottom)
        self._write_raw("\0338")
        self._flush()

    def _draw_pin(self, lines: list[str], bottom: int) -> None:
        for i, line in enumerate(lines):
            self._write_raw(f"\033[{bottom + 1 + i};1H\033[2K{line}")

    def _write_raw(self, s: str) -> None:
        try:
            self._raw.write(s)
        except UnicodeEncodeError:
            enc = getattr(self._raw, "encoding", None) or "utf-8"
            safe = s.encode(enc, errors="replace").decode(enc, errors="replace")
            self._raw.write(safe)

    def _flush(self) -> None:
        try:
            self._raw.flush()
        except OSError:
            pass


live = LiveStatus()
