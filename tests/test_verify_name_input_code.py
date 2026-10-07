"""verify_name_input_code gates the gold Release on the reviewed snapshot."""

from __future__ import annotations

import hashlib
import json

from conftest import TOOLS, load_module

verify_mod = load_module("verify_name_input_code", TOOLS / "verify_name_input_code.py")


def _setup(tmp_path, vanilla: bytes, code: bytes, want_code: bytes):
    snap = tmp_path / "snap.json"
    snap.write_text(
        json.dumps(
            {
                "vanilla_sha256": hashlib.sha256(vanilla).hexdigest(),
                "final_sha256": hashlib.sha256(want_code).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    v = tmp_path / "vanilla.bin"
    v.write_bytes(vanilla)
    c = tmp_path / "code.bin"
    c.write_bytes(code)
    return snap, v, c


def test_matching_build_passes(tmp_path):
    snap, v, c = _setup(tmp_path, b"vanilla", b"patched", b"patched")
    assert verify_mod.verify(c, v, snap) == []


def test_changed_output_fails(tmp_path):
    snap, v, c = _setup(tmp_path, b"vanilla", b"patched-differently", b"patched")
    problems = verify_mod.verify(c, v, snap)
    assert len(problems) == 1 and "snapshot" in problems[0]


def test_wrong_vanilla_fails(tmp_path):
    snap, _v, c = _setup(tmp_path, b"vanilla", b"patched", b"patched")
    other = tmp_path / "other.bin"
    other.write_bytes(b"some other dump")
    problems = verify_mod.verify(c, other, snap)
    assert len(problems) == 1 and "wrong dump" in problems[0]


def test_missing_build_fails(tmp_path):
    snap, v, _c = _setup(tmp_path, b"vanilla", b"patched", b"patched")
    problems = verify_mod.verify(tmp_path / "nope.bin", v, snap)
    assert problems == [f"missing {tmp_path / 'nope.bin'}"]

