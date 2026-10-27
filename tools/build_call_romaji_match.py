#!/usr/bin/env python3
"""Compile src/call_romaji_match.c into src/call_romaji_match_blob.py.

The romaji Called-name lookup is C, not hand-encoded ARM. Its three pieces go
into dead vanilla code (see the C header and docs/technical.md §17.8):

  A  file 0x147B3C  nlpp_call_exact at FUN_00147b3c's entry + helpers
  B  file 0x147E04  nlpp_call_list at FUN_00147e04's entry
  C  file 0x148F44  scan, in FUN_00148f44 (only FUN_00147e04 called it)

Needs clang + ld.lld + llvm-objcopy with the ARM target (llvm-mingw has
them). The deploy never compiles: it applies the committed blob.
tests/test_call_romaji_match.py fails when the C source changes without a
rebuild.

  python tools/build_call_romaji_match.py
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "call_romaji_match.c"
BLOB_PY = ROOT / "src" / "call_romaji_match_blob.py"

VA = 0x00100000  # code.bin file offset 0 is VA 0x100000
# (name, file start, file end, sections). The first section sits at start.
REGIONS = (
    ("A", 0x00147B3C, 0x00147E04, ("nlpp_call_exact", "normalize", "same", "distance")),
    ("B", 0x00147E04, 0x001480A8, ("nlpp_call_list", "fold")),
    ("C", 0x00148F44, 0x001493F0, ("scan",)),
)
CFLAGS = (
    "--target=armv6k-none-eabi",
    "-mcpu=mpcore",
    "-marm",
    "-mfloat-abi=soft",
    "-Oz",
    "-ffreestanding",
    "-fno-builtin",
    "-fno-stack-protector",
    "-fno-unwind-tables",
    "-fno-asynchronous-unwind-tables",
    "-fno-exceptions",
    "-ffunction-sections",
    "-Wall",
    "-Wextra",
    "-Werror",
)


def source_sha256() -> str:
    return hashlib.sha256(SOURCE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _tool(name: str) -> str:
    clang = shutil.which("clang")
    if name == "clang":
        if not clang:
            raise SystemExit("clang not found (install llvm-mingw or LLVM)")
        return clang
    found = shutil.which(name) or (
        str(Path(clang).with_name(name + Path(clang).suffix)) if clang else None
    )
    if not found or not Path(found).exists():
        raise SystemExit(f"{name} not found next to clang")
    return found


def clang_version() -> str:
    out = subprocess.run([_tool("clang"), "--version"], capture_output=True, text=True, check=True)
    return out.stdout.splitlines()[0].strip()


def _linker_script() -> str:
    lines = ["SECTIONS {"]
    for name, start, _end, sections in REGIONS:
        body = " ".join(f"*(.text.{s})" for s in sections)
        lines.append(f"  .{name} {VA + start:#x} : {{ {body} }}")
    lines.append("  /DISCARD/ : { *(.ARM.exidx*) *(.comment) *(.note*) *(.llvm_addrsig) }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def build() -> tuple[tuple[tuple[int, bytes], ...], dict[str, int]]:
    """Return ((file offset, bytes) per region, symbol -> file offset)."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        obj, elf, ld = t / "m.o", t / "m.elf", t / "m.ld"
        ld.write_text(_linker_script(), encoding="ascii")
        subprocess.run([_tool("clang"), *CFLAGS, "-c", str(SOURCE), "-o", str(obj)], check=True)
        sections = subprocess.run(
            [_tool("llvm-objdump"), "-h", str(obj)], capture_output=True, text=True, check=True
        ).stdout
        placed = {s for _n, _a, _b, secs in REGIONS for s in secs}
        for line in sections.splitlines():
            parts = line.split()
            if len(parts) > 2 and parts[1].startswith(".text.") and int(parts[2], 16):
                if parts[1][len(".text.") :] not in placed:
                    raise SystemExit(f"unplaced code section {parts[1]} (add it to REGIONS)")
            if len(parts) > 2 and parts[1] in (".data", ".bss", ".rodata") and int(parts[2], 16):
                raise SystemExit(f"{parts[1]} is not allowed: the blob has no data segment")
        subprocess.run(
            [_tool("ld.lld"), "-T", str(ld), "-e", "nlpp_call_exact", "--no-undefined", "-o", str(elf), str(obj)],
            check=True,
        )
        pieces = []
        for name, start, end, _secs in REGIONS:
            out = t / f"{name}.bin"
            subprocess.run(
                [_tool("llvm-objcopy"), "-O", "binary", f"--only-section=.{name}", str(elf), str(out)],
                check=True,
            )
            data = out.read_bytes()
            if not data:
                raise SystemExit(f"region {name} is empty")
            if start + len(data) > end:
                raise SystemExit(
                    f"region {name} is {len(data):#x} bytes, room {end - start:#x}"
                )
            pieces.append((start, data))
        nm = subprocess.run(
            [_tool("llvm-nm"), str(elf)], capture_output=True, text=True, check=True
        ).stdout
        symbols = {}
        for line in nm.splitlines():
            addr, _kind, sym = line.split()
            symbols[sym] = int(addr, 16) - VA
    for entry, (_name, start, _end, secs) in zip(("nlpp_call_exact", "nlpp_call_list", "scan"), REGIONS):
        if symbols[entry] != start or secs[0] != entry:
            raise SystemExit(f"{entry} is at {symbols[entry]:#x}, expected {start:#x}")
    return tuple(pieces), symbols


def render(pieces, symbols, version: str, sha: str) -> str:
    lines = [
        '"""Generated by tools/build_call_romaji_match.py from src/call_romaji_match.c.',
        "",
        "Do not edit. Rebuild after changing the C source.",
        '"""',
        "",
        f"CLANG_VERSION = {version!r}",
        f"SOURCE_SHA256 = {sha!r}",
        "",
        "# (code.bin file offset, bytes)",
        "PIECES = (",
    ]
    for start, data in pieces:
        hexs = data.hex()
        chunks = [hexs[i : i + 64] for i in range(0, len(hexs), 64)]
        lines.append(f"    (0x{start:08X}, bytes.fromhex(")
        lines.extend(f'        "{c}"' for c in chunks)
        lines.append("    )),")
    lines.append(")")
    lines.append("")
    lines.append("SYMBOLS = {")
    for sym in sorted(symbols, key=symbols.get):
        lines.append(f'    "{sym}": 0x{symbols[sym]:08X},')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if the committed blob is stale")
    args = ap.parse_args(argv)
    pieces, symbols = build()
    text = render(pieces, symbols, clang_version(), source_sha256())
    if args.check:
        if BLOB_PY.read_text(encoding="utf-8") != text:
            print("call_romaji_match_blob.py is stale", file=sys.stderr)
            return 1
        return 0
    BLOB_PY.write_text(text, encoding="utf-8", newline="\n")
    for (name, start, end, _s), (_a, data) in zip(REGIONS, pieces):
        print(f"[call-romaji-match] {name} @{start:#x} {len(data):#x} / {end - start:#x}")
    print(f"wrote {BLOB_PY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
