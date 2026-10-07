"""Trace which code.bin words each step of the name-input stack writes.

``trace_stack`` runs ``deploy_name_input_en.apply_name_input_stack`` on a copy
of vanilla code.bin. Every ``apply_*`` / ``patch_*`` / ``restore_*`` function
the deploy module imports is wrapped, so new steps are traced without editing
this file. Each step records the 4-byte-aligned words it changed.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import struct
from dataclasses import dataclass, field

from conftest import TOOLS, load_module

STEP_PREFIXES = ("apply_", "patch_", "restore_")

# Bytes a step may leave behind as pad that a later step is allowed to reuse.
FILLER_WORDS = frozenset(
    {
        b"\x00\x00\x00\x00",
        bytes.fromhex("00f020e3"),  # nop
        bytes.fromhex("0000a0e1"),  # mov r0, r0
    }
)


@dataclass
class Step:
    name: str
    before: bytes
    after: bytes
    words: list[int] = field(default_factory=list)

    def ranges(self) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for w in self.words:
            if out and out[-1][1] == w:
                out[-1] = (out[-1][0], w + 4)
            else:
                out.append((w, w + 4))
        return out

    def written_sha256(self) -> str:
        h = hashlib.sha256()
        for a, b in self.ranges():
            h.update(struct.pack("<II", a, b))
            h.update(self.after[a:b])
        return h.hexdigest()


@dataclass
class Trace:
    vanilla: bytes
    final: bytes
    steps: list[Step]


def changed_words(a: bytes, b: bytes) -> list[int]:
    out: list[int] = []
    chunk = 0x1000
    for i in range(0, len(a), chunk):
        if a[i : i + chunk] == b[i : i + chunk]:
            continue
        for w in range(i, min(i + chunk, len(a)), 4):
            if a[w : w + 4] != b[w : w + 4]:
                out.append(w)
    return out


def load_deploy():
    return load_module("deploy_name_input_en", TOOLS / "deploy_name_input_en.py")


def step_functions(deploy) -> dict[str, object]:
    return {
        name: fn
        for name, fn in vars(deploy).items()
        if callable(fn)
        and name.startswith(STEP_PREFIXES)
        and name != "apply_name_input_stack"
    }


def trace_stack(vanilla: bytes) -> Trace:
    deploy = load_deploy()
    originals = step_functions(deploy)
    steps: list[Step] = []

    def wrap(name, fn):
        def traced(data, *args, **kwargs):
            before = bytes(data)
            result = fn(data, *args, **kwargs)
            after = bytes(data)
            steps.append(Step(name, before, after, changed_words(before, after)))
            return result

        return traced

    data = bytearray(vanilla)
    try:
        for name, fn in originals.items():
            setattr(deploy, name, wrap(name, fn))
        with contextlib.redirect_stdout(io.StringIO()):
            deploy.apply_name_input_stack(data)
    finally:
        for name, fn in originals.items():
            setattr(deploy, name, fn)
    return Trace(vanilla=vanilla, final=bytes(data), steps=steps)


def branch_target(word: int, here: int) -> int | None:
    """Target of an ARM B/BL/BLX immediate at ``here``, else None."""
    if (word >> 25) == 0x7D:  # BLX imm (cond 1111, 101H)
        off = word & 0xFFFFFF
        if off & 0x800000:
            off -= 0x1000000
        return here + 8 + (off << 2) + (((word >> 24) & 1) << 1)
    if ((word >> 25) & 7) == 5 and (word >> 28) != 0xF:  # B / BL
        off = word & 0xFFFFFF
        if off & 0x800000:
            off -= 0x1000000
        return here + 8 + (off << 2)
    return None
