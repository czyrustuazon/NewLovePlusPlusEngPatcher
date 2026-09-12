"""Wall-clock elapsed timer for long EngPatcher runs (bake / pack / CIA patch).

Prints ``[timer]`` lines at start, on stage marks, on a heartbeat while still
running, and a total at finish — so a multi-hour PNG pack is never silent.
"""

from __future__ import annotations

import threading
import time


def format_elapsed(seconds: float) -> str:
    """Human elapsed: ``12s``, ``3m05s``, or ``2h04m03s``."""
    sec = max(0, int(seconds))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


class RunTimer:
    """Track how long the current patcher/bake step has been running."""

    def __init__(
        self,
        label: str = "run",
        *,
        heartbeat_s: float | None = 60.0,
    ) -> None:
        self.label = label
        self.t0 = time.monotonic()
        self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self._hb_s = heartbeat_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        print(
            f"[timer] {label} started at {self.started_at}",
            flush=True,
        )
        if heartbeat_s is not None and heartbeat_s > 0:
            self.start_heartbeat()

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def elapsed_str(self) -> str:
        return format_elapsed(self.elapsed())

    def mark(self, msg: str) -> None:
        print(f"[timer] {self.elapsed_str()} — {msg}", flush=True)

    def start_heartbeat(self) -> None:
        if self._thread is not None:
            return
        interval = float(self._hb_s or 60.0)
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.wait(interval):
                print(
                    f"[timer] still running — elapsed {self.elapsed_str()} "
                    f"({self.label})",
                    flush=True,
                )

        self._thread = threading.Thread(
            target=_loop,
            name=f"timer-hb-{self.label}",
            daemon=True,
        )
        self._thread.start()

    def stop_heartbeat(self) -> None:
        self._stop.set()
        th = self._thread
        if th is not None:
            th.join(timeout=1.0)
            self._thread = None

    def finish(self, msg: str = "finished") -> None:
        self.stop_heartbeat()
        print(f"[timer] total {self.elapsed_str()} — {msg}", flush=True)

    def __enter__(self) -> RunTimer:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        if exc_type is KeyboardInterrupt:
            self.finish(f"{self.label} aborted")
        elif exc_type is not None:
            self.finish(f"{self.label} failed")
        else:
            self.finish(f"{self.label} OK")
        return False


if __name__ == "__main__":
    # Drop bat: python src/run_timer.py <unix_start>  →  4m32s
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("usage: run_timer.py <unix_start_seconds>")
    print(format_elapsed(time.time() - float(sys.argv[1])))
