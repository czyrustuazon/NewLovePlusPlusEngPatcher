"""MCP server for the Azahar a/b test workflow (ab_test/make.ps1).

Stdio server. Register via the repo-root .mcp.json; needs `pip install mcp`.
Every tool takes instance "a" or "b". Instance roots live under
ab_test/azahar_instances/{a,b}/user, same as make.ps1.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO = Path(__file__).resolve().parent.parent
AB = REPO / "ab_test"
INSTANCES = AB / "azahar_instances"
TITLE_ID = "00040000000F4E00"
RELEASE = REPO / "release"

# make.ps1 targets that are safe to run unattended. `progress` POSTs to the
# site, so it is left out on purpose; `progress-dry` is fine.
MAKE_TARGETS = {
    "paths", "instances", "build-azahar",
    "seed-a", "seed-b", "deploy-a", "deploy-b",
    "combine-a", "combine-b", "combine",
    "restore-a", "restore-b", "restore",
    "save-nene-a", "save-nene-b", "save-nene",
    "launch-a", "launch-b", "all-a", "all-b", "progress-dry",
}

LOG_MARKERS = re.compile(
    r"overriding built-in ExeFS|LayeredFS replacement file|clone offset=|"
    r"NLPP_EMU|data abort|Data abort|Unmapped|Write32|Cleaning up process|"
    r"Critical|Error>",
)

mcp = FastMCP("nlpp-ab-azahar")


def _inst(instance: str) -> Path:
    if instance not in ("a", "b"):
        raise ValueError("instance must be 'a' or 'b'")
    return INSTANCES / instance


def _mod(instance: str) -> Path:
    return _inst(instance) / "user" / "load" / "mods" / TITLE_ID


def _log(instance: str) -> Path:
    return _inst(instance) / "user" / "log" / "azahar_log.txt"


def _sha1(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _powershell(script: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
    )


def _running_pids(instance: str) -> list[int]:
    exe = str(_inst(instance) / "azahar.exe").replace("'", "''")
    r = _powershell(
        "Get-CimInstance Win32_Process -Filter \"Name='azahar.exe'\" | "
        f"Where-Object {{ $_.ExecutablePath -eq '{exe}' }} | "
        "ForEach-Object { $_.ProcessId }"
    )
    return [int(x) for x in r.stdout.split() if x.isdigit()]


@mcp.tool()
def ab_make(target: str, timeout_seconds: int = 600) -> str:
    """Run `ab_test/make.ps1 <target>` and return its output.

    Targets: paths, instances, build-azahar, seed-a/b, deploy-a/b, combine[-a/b],
    restore[-a/b], save-nene[-a/b], launch-a/b, all-a/b, progress-dry.
    deploy/seed need an existing bake (release/bake_img.bin etc.) and fail with
    the make.ps1 "a bake should be done first" message if it is missing.
    """
    if target not in MAKE_TARGETS:
        return f"target {target!r} not allowed. Allowed: {sorted(MAKE_TARGETS)}"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(AB / "make.ps1"), target],
            cwd=REPO, capture_output=True, text=True, stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return f"make.ps1 {target} timed out after {timeout_seconds}s"
    err = "\n[stderr]\n" + r.stderr if r.stderr.strip() else ""
    return f"exit={r.returncode}\n{r.stdout}{err}"


@mcp.tool()
def ab_status(instance: str) -> str:
    """JSON status of instance a or b: mod files (size, sha1), whether they match
    release/ post-bake files, azahar.exe presence, running PIDs, log mtime."""
    mod = _mod(instance)
    pairs = {
        "romfs/img.bin": RELEASE / "bake_img.bin",
        "exefs/code.bin": RELEASE / "name_input_code.bin",
        "code.bin": RELEASE / "name_input_code.bin",
    }
    files = {}
    for rel, src in pairs.items():
        p = mod / rel
        sha = _sha1(p)
        src_sha = _sha1(src)
        files[rel] = {
            "exists": p.is_file(),
            "size": p.stat().st_size if p.is_file() else None,
            "sha1": sha,
            "matches_release": (sha == src_sha) if sha and src_sha else None,
        }
    log = _log(instance)
    out = {
        "instance": instance,
        "azahar_exe": (_inst(instance) / "azahar.exe").is_file(),
        "running_pids": _running_pids(instance),
        "mod_root": str(mod),
        "files": files,
        "log_mtime": log.stat().st_mtime if log.is_file() else None,
        "log_size": log.stat().st_size if log.is_file() else None,
    }
    return json.dumps(out, indent=2)


@mcp.tool()
def ab_diff() -> str:
    """Compare every file under load/mods/<title> between instance A and B
    (by sha1). Lists files only in one side or differing."""
    def tree(inst: str) -> dict[str, str]:
        root = _mod(inst)
        if not root.is_dir():
            return {}
        return {
            str(p.relative_to(root)).replace("\\", "/"): _sha1(p) or ""
            for p in root.rglob("*") if p.is_file() and "_bak" not in p.parts
        }
    a, b = tree("a"), tree("b")
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    differ = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    return json.dumps(
        {"only_a": only_a, "only_b": only_b, "differ": differ,
         "identical_count": len(set(a) & set(b)) - len(differ)},
        indent=2,
    )


@mcp.tool()
def ab_read_bytes(instance: str, file: str = "exefs/code.bin", offset: int = 0,
                  length: int = 16) -> str:
    """Hex bytes at a file offset of a mod file (default exefs/code.bin).
    Runtime VA is roughly file offset + 0x100000. `file` is relative to
    load/mods/<title>/ and must stay inside it. Offset accepts decimal."""
    root = _mod(instance).resolve()
    p = (root / file).resolve()
    if root not in p.parents:
        return "file must be inside the instance mod root"
    if not p.is_file():
        return f"missing: {p}"
    length = max(1, min(length, 4096))
    with p.open("rb") as f:
        f.seek(offset)
        data = f.read(length)
    return f"{p.name} @0x{offset:X} (+{len(data)}): {data.hex(' ')}"


@mcp.tool()
def ab_log_tail(instance: str, lines: int = 80, previous: bool = False) -> str:
    """Last N lines of the instance's azahar_log.txt (previous=True reads
    azahar_log.old.txt, the prior run)."""
    p = _log(instance)
    if previous:
        p = p.with_name("azahar_log.old.txt")
    if not p.is_file():
        return f"no log: {p}"
    text = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(text[-max(1, min(lines, 1000)):])


@mcp.tool()
def ab_log_search(instance: str, pattern: str, context: int = 2, max_matches: int = 40,
                  previous: bool = False) -> str:
    """Regex search (case-insensitive) of the instance log with context lines."""
    p = _log(instance)
    if previous:
        p = p.with_name("azahar_log.old.txt")
    if not p.is_file():
        return f"no log: {p}"
    rx = re.compile(pattern, re.IGNORECASE)
    text = p.read_text(encoding="utf-8", errors="replace").splitlines()
    out, hits, last = [], 0, -1
    for i, line in enumerate(text):
        if not rx.search(line):
            continue
        hits += 1
        if hits > max_matches:
            out.append(f"... more matches truncated at {max_matches}")
            break
        lo, hi = max(0, i - context), min(len(text), i + context + 1)
        if lo <= last:
            lo = last + 1
        elif out:
            out.append("--")
        out.extend(f"{n + 1}: {text[n]}" for n in range(lo, hi))
        last = hi - 1
    return "\n".join(out) or "no matches"


@mcp.tool()
def ab_log_markers(instance: str, max_lines: int = 60) -> str:
    """Key lines from the last run: LayeredFS override confirmations,
    OpenLinkFile clone, NLPP_EMU hooks, aborts, heap smashes, process cleanup."""
    p = _log(instance)
    if not p.is_file():
        return f"no log: {p}"
    hits = [
        f"{i + 1}: {line}"
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines())
        if LOG_MARKERS.search(line)
    ]
    shown = hits[:max_lines // 2] + (["..."] if len(hits) > max_lines else []) + \
        (hits[-(max_lines // 2):] if len(hits) > max_lines else hits[max_lines // 2:])
    return "\n".join(shown) or "no markers"


@mcp.tool()
def ab_stop(instance: str) -> str:
    """Kill the azahar.exe belonging to this instance (matched by exe path, so
    the other instance and roaming Azahar are untouched)."""
    pids = _running_pids(instance)
    if not pids:
        return "not running"
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    return f"stopped {pids}"


if __name__ == "__main__":
    mcp.run()
