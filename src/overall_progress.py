"""One percent bar for a whole Drop CIA run.

Rebuild and the CIA patch are separate processes. Each maps its own 0–100%
onto ``NLPP_OVERALL_LO``..``NLPP_OVERALL_HI`` (Drop uses 0–80 while a rebuild
is actually running, then 80–100 for the CIA step). Unset env means this
process owns the full 0–100%.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from live_status import live, render_percent

_bound: OverallBar | None = None


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def span_from_env() -> tuple[float, float]:
    """Slice of the Drop bar this process should fill."""
    lo = min(100.0, max(0.0, _env_float("NLPP_OVERALL_LO", 0.0)))
    hi = min(100.0, max(0.0, _env_float("NLPP_OVERALL_HI", 100.0)))
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


class OverallBar:
    """Weighted steps, drawn as one percent of the whole job."""

    def __init__(self, steps: list[tuple[str, float]]) -> None:
        self.steps = [
            (str(name), float(weight)) for name, weight in steps if float(weight) > 0
        ]
        self.total = sum(weight for _, weight in self.steps) or 1.0
        self.lo, self.hi = span_from_env()
        self._last_pct = -1

    def goto(self, name: str, frac: float = 0.0, *, detail: str | None = None) -> None:
        for index, (step, _weight) in enumerate(self.steps):
            if step == name:
                self._show(index, frac, detail if detail is not None else step)
                return

    def finish(self) -> None:
        if not self.steps:
            return
        self._emit(self.hi, f"{len(self.steps)}/{len(self.steps)}  done", force=True)

    def _show(self, index: int, frac: float, label: str) -> None:
        frac = min(1.0, max(0.0, float(frac)))
        done = sum(weight for _, weight in self.steps[:index])
        done += self.steps[index][1] * frac
        local = done / self.total
        pct = self.lo + (self.hi - self.lo) * local
        self._emit(pct, f"{index + 1}/{len(self.steps)}  {label}")

    def _emit(self, pct: float, detail: str, *, force: bool = False) -> None:
        if live.active:
            live.set_overall(pct, detail)
            self._last_pct = int(pct)
            return
        shown = int(pct)
        if not force and shown == self._last_pct:
            return
        self._last_pct = shown
        print(render_percent(pct, detail=detail), flush=True)


def bind(bar: OverallBar | None) -> None:
    global _bound
    _bound = bar


def tick(name: str, frac: float = 0.0, *, detail: str | None = None) -> None:
    """Move the bar bound for this process. No-op when nothing is bound."""
    bar = _bound
    if bar is not None:
        bar.goto(name, frac, detail=detail)


def finish_bound() -> None:
    bar = _bound
    if bar is not None:
        bar.finish()


@contextmanager
def overall_scope(steps: list[tuple[str, float]]) -> Iterator[OverallBar]:
    bar = OverallBar(steps)
    bind(bar)
    try:
        yield bar
    finally:
        bind(None)
