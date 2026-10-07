"""Whole-stack code.bin guards (needs a vanilla code.bin; skipped in CI).

Runs the gold name-input stack on vanilla, step by step, and checks:

* no step overwrites another step's code (only its zero/NOP pad);
* no patched branch leaves .text (the .rodata cave prefetch abort, Luma
  PC 0x007E6A78), and only listed steps write past .text at all;
* each step refuses to patch when its target bytes are not what it expects;
* re-running the stack on its own output changes nothing;
* every step's written bytes match tests/snapshots/code_patch_map.json.

After an intended patch change, refresh the snapshot and commit it with the
change so the review shows which addresses moved:

    NLPP_UPDATE_SNAPSHOTS=1 python -m pytest tests/test_code_patch_map.py
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import struct

import pytest

from code_patch_trace import (
    FILLER_WORDS,
    branch_target,
    changed_words,
    load_deploy,
    step_functions,
    trace_stack,
)
from conftest import ROOT, SRC, load_module

cave_map = load_module("patch_input_cave_map", SRC / "patch_input_cave_map.py")
from nlpp_paths import find_vanilla_code  # noqa: E402

# Needs local data; excluded from coverage (see dev/check_coverage.py).
pytestmark = pytest.mark.local_data

TEXT_END = cave_map.TEXT_PAGE_END
SNAPSHOT = ROOT / "tests" / "snapshots" / "code_patch_map.json"

# Steps allowed to write past .text. These write data only (delay tables,
# password table, SpotPass payload/strings); nothing may branch there.
DATA_WRITERS = {"apply_message_speed", "apply_spotpass_embed", "apply_password_uribo"}

# Written ranges a step does not check before overwriting. These are dead
# bodies behind an entry hook that *is* checked. Ratchet: counts may only go
# down. A new step must check every range it writes.
UNGUARDED_ALLOWANCE = {
    "apply_name_pane_patches": 5,
    "apply_chunk_walk": 2,
    "apply_spotpass_embed": 22,
}


def _skip(reason: str):
    """Skip on dev machines and CI. The gold runner sets
    NLPP_REQUIRE_CODE_CHECKS=1 so a missing or wrong vanilla fails the bake."""
    if os.environ.get("NLPP_REQUIRE_CODE_CHECKS") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


def _vanilla() -> bytes:
    src = find_vanilla_code()
    if src is None:
        _skip("no vanilla code.bin (set NLPP_VANILLA_CODE or run rebuild_bake_img --rom)")
    return src.read_bytes()


@pytest.fixture(scope="module")
def trace():
    return trace_stack(_vanilla())


def _hex_ranges(ranges):
    return [f"{a:#08x}-{b:#08x}" for a, b in ranges]


def test_steps_only_reuse_filler_from_earlier_steps(trace):
    owner: dict[int, tuple[str, bytes]] = {}
    clobbers = []
    for step in trace.steps:
        for w in step.words:
            prev = owner.get(w)
            if prev and prev[0] != step.name and prev[1] not in FILLER_WORDS:
                clobbers.append(f"{w:#x}: {step.name} overwrote {prev[0]} code {prev[1].hex()}")
            owner[w] = (step.name, step.after[w : w + 4])
    assert not clobbers, "\n".join(clobbers[:20])


def test_patched_branches_stay_in_text(trace):
    bad = []
    for step in trace.steps:
        for w in step.words:
            if w >= TEXT_END:
                continue
            word = struct.unpack_from("<I", trace.final, w)[0]
            tgt = branch_target(word, w)
            if tgt is not None and not 0 <= tgt < TEXT_END:
                bad.append(f"{step.name} {w:#x} {word:08x} -> {tgt:#x}")
    assert not bad, "branch into non-executable pages:\n" + "\n".join(bad)


def test_only_data_steps_write_past_text(trace):
    past = sorted({s.name for s in trace.steps if s.words and s.words[-1] >= TEXT_END})
    unexpected = [n for n in past if n not in DATA_WRITERS]
    assert not unexpected, (
        f"{unexpected} write past .text ({TEXT_END:#x}). Code caves must sit in "
        "RX pages (patch_input_cave_map.py). If this is data, add it to DATA_WRITERS."
    )


def test_steps_refuse_unexpected_target_bytes(trace):
    """Corrupt the first word of each written range; the step must not write
    over it. Raising is the usual guard; skipping the site is caught by the
    snapshot test instead."""
    originals = step_functions(load_deploy())
    seen: set[str] = set()
    over = []
    for step in trace.steps:
        if step.name in seen or not step.words:
            continue
        seen.add(step.name)
        fn = originals[step.name]
        unguarded = []
        for a, b in step.ranges():
            state = bytearray(step.before)
            state[a] ^= 0xA5
            corrupted = bytes(state[a:b])
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    fn(state)
            except (ValueError, SystemExit, AssertionError, RuntimeError):
                continue
            if state[a:b] != corrupted:
                unguarded.append(a)
        allowed = UNGUARDED_ALLOWANCE.get(step.name, 0)
        if len(unguarded) > allowed:
            over.append(f"{step.name}: {len(unguarded)} unchecked > {allowed}: "
                        + ", ".join(f"{a:#x}" for a in unguarded[:10]))
        elif len(unguarded) < allowed:
            over.append(f"{step.name}: only {len(unguarded)} unchecked; "
                        f"lower UNGUARDED_ALLOWANCE to {len(unguarded)}")
    assert not over, "\n".join(over)


def test_stack_is_idempotent(trace):
    """Azahar deploys re-run the stack on an already-patched code.bin."""
    again = trace_stack(trace.final)
    diff = changed_words(trace.final, again.final)
    assert not diff, "second run changed " + ", ".join(f"{w:#x}" for w in diff[:20])


def _snapshot(trace) -> dict:
    return {
        "vanilla_sha256": hashlib.sha256(trace.vanilla).hexdigest(),
        "final_sha256": hashlib.sha256(trace.final).hexdigest(),
        "steps": [
            {
                "name": s.name,
                "written_sha256": s.written_sha256(),
                "ranges": _hex_ranges(s.ranges()),
            }
            for s in trace.steps
            if s.words
        ],
    }


def test_written_bytes_match_snapshot(trace):
    got = _snapshot(trace)
    if os.environ.get("NLPP_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
        return
    if not SNAPSHOT.is_file():
        pytest.fail(f"missing {SNAPSHOT.name}; run with NLPP_UPDATE_SNAPSHOTS=1")
    want = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if want["vanilla_sha256"] != got["vanilla_sha256"]:
        _skip("vanilla code.bin differs from the snapshot's dump")
    if want == got:
        return
    want_steps = {s["name"]: s for s in want["steps"]}
    got_steps = {s["name"]: s for s in got["steps"]}
    lines = []
    for name in dict.fromkeys([*want_steps, *got_steps]):
        w, g = want_steps.get(name), got_steps.get(name)
        if w == g:
            continue
        if w is None or g is None:
            lines.append(f"{name}: {'added' if w is None else 'removed'}")
            continue
        moved = sorted(set(w["ranges"]) ^ set(g["ranges"]))
        lines.append(f"{name}: bytes changed" + (f"; ranges moved {moved[:6]}" if moved else ""))
    if [s["name"] for s in want["steps"]] != [s["name"] for s in got["steps"]]:
        lines.append("step order changed")
    pytest.fail(
        "code.bin output changed:\n  " + "\n  ".join(lines or ["final hash only"])
        + "\nIf intended: NLPP_UPDATE_SNAPSHOTS=1 python -m pytest tests/test_code_patch_map.py"
    )
