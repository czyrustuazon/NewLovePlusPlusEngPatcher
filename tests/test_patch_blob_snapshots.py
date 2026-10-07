"""Snapshot every pure code-cave builder (runs in CI; no ROM needed).

Any ``build_*`` / ``assemble_*`` function in ``src/patch_*.py`` that takes no
required arguments and returns bytes (or a tuple starting with bytes) is
hashed and compared with tests/snapshots/patch_blobs.json. New builders are
picked up automatically.

After an intended change to a cave, refresh and commit the snapshot:

    NLPP_UPDATE_SNAPSHOTS=1 python -m pytest tests/test_patch_blob_snapshots.py
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os

import pytest

from conftest import ROOT, SRC

SNAPSHOT = ROOT / "tests" / "snapshots" / "patch_blobs.json"


def _blob(result) -> bytes | None:
    if isinstance(result, tuple) and result:
        result = result[0]
    return bytes(result) if isinstance(result, (bytes, bytearray)) else None


def _builders():
    for path in sorted(SRC.glob("patch_*.py")):
        mod = importlib.import_module(path.stem)
        for name, fn in vars(mod).items():
            if not inspect.isfunction(fn) or fn.__module__ != mod.__name__:
                continue
            if not name.startswith(("build_", "assemble_")):
                continue
            required = [
                p
                for p in inspect.signature(fn).parameters.values()
                if p.default is p.empty and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
            ]
            if not required:
                yield f"{mod.__name__}.{name}", fn


def _hashes() -> dict[str, str]:
    out = {}
    for key, fn in _builders():
        blob = _blob(fn())
        if blob is not None:
            out[key] = hashlib.sha256(blob).hexdigest()
    return out


def test_builders_are_deterministic():
    assert _hashes() == _hashes()


def test_builder_output_matches_snapshot():
    got = _hashes()
    assert len(got) > 50, "builder discovery broke"
    if os.environ.get("NLPP_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return
    if not SNAPSHOT.is_file():
        pytest.fail(f"missing {SNAPSHOT.name}; run with NLPP_UPDATE_SNAPSHOTS=1")
    want = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    changed = sorted(k for k in want.keys() & got.keys() if want[k] != got[k])
    added = sorted(got.keys() - want.keys())
    removed = sorted(want.keys() - got.keys())
    if changed or added or removed:
        pytest.fail(
            f"cave bytes changed: {changed}\nnew builders: {added}\nremoved: {removed}\n"
            "If intended: NLPP_UPDATE_SNAPSHOTS=1 python -m pytest "
            "tests/test_patch_blob_snapshots.py"
        )
