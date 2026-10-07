"""Shared pytest fixtures for EngPatcher."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# CI has no release/bake_img.bin. Importing deploy_* modules must not exit.
os.environ.setdefault("NLPP_ALLOW_MISSING_DEPLOY_IMG", "1")
# Never mirror deploys into a real Azahar LayeredFS from a test. Tests of the
# mirror itself set or delete this with monkeypatch.
os.environ["NLPP_ALSO_AZAHAR"] = "0"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "local_data: needs vanilla game dumps or the Azahar fork; CI skips it. "
        'Coverage runs with -m "not local_data" so local and CI numbers match.',
    )


def load_module(name: str, path: Path):
    """Import a module by file path (for tools/ outside pythonpath)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
