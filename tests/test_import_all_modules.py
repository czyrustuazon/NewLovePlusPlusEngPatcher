"""Every src/ and tools/ module must import without side-effect crashes.

Catches broken imports in scripts that have no test of their own. Runs in a
subprocess so module-level sys.path / env tweaks do not leak into other tests.
Scripts must keep their work under ``if __name__ == "__main__":``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from conftest import ROOT, SRC, TOOLS

# Third-party packages that only some dev tools need and CI does not install
# (dev/requirements-dev.txt). A missing one is fine; anything else missing is
# a real break.
OPTIONAL_DEPS = {
    "mcp",  # tools/ab_mcp_server.py (A/B Azahar MCP server)
}

PROBE = r"""
import importlib, json, sys, traceback
sys.path[:0] = [sys.argv[1], sys.argv[2]]
failed = {}
for name in sys.argv[3:]:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        failed[name] = {"missing": (exc.name or "").split(".")[0],
                        "error": f"ModuleNotFoundError: {exc}"}
    except BaseException:
        failed[name] = {"missing": "",
                        "error": traceback.format_exc(limit=3).strip().splitlines()[-1]}
print(json.dumps(failed))
"""


def test_all_modules_import():
    names = sorted(p.stem for p in [*SRC.glob("*.py"), *TOOLS.glob("*.py")])
    env = {**os.environ, "NLPP_ALLOW_MISSING_DEPLOY_IMG": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", PROBE, str(SRC), str(TOOLS), *names],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    failed = json.loads(proc.stdout.strip().splitlines()[-1])
    broken = {k: v["error"] for k, v in failed.items() if v["missing"] not in OPTIONAL_DEPS}
    assert not broken, "\n".join(f"{k}: {v}" for k, v in broken.items())
