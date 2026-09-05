#!/usr/bin/env python3
"""One-click New Love Plus+ English patcher (CIA or 3DS/CCI in → CIA out).

Pipeline:
  decrypted CIA or .3ds/.cci -> extract CXI/RomFS -> inject EN .dbin2
  -> English heroine-name patches (scripts / resident TRB / img.bin table)
  -> optional single-pane name code.bin patch (--patch-code)
  -> rebuild RomFS/CXI/CIA (decrypted, CFW/emulator ready)

Decrypt your dump yourself first (GodMode9, Batch CIA 3DS Decryptor, etc.).
This tool does not ship or run proprietary decryptors.

NLPPGit (https://github.com/Makein/NLPPGit) is translation assets only.
img.bin: kiwiz/nlpp-tools (ie, pe, png2bclim, img module); TRB codebook: Trb2xlsx
lookup.txt only; DARC: src/darcutil.py. DBIN2 format: NLPTextTool lineage (pre-built
rebuild_dbin2/). CIA: ctrtool / makerom / 3dstool (no in-tree decryptor).
See README.md Credits for full third-party list.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from run_timer import RunTimer

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
TOOLS = ROOT / "tools"
CIA_TOOLS = TOOLS / "cia"
TOOL_3DS = CIA_TOOLS / "3dstool" / "3dstool.exe"
CTRTOOL = CIA_TOOLS / "ctrtool.exe"
MAKEROM = CIA_TOOLS / "makerom.exe"
SEEDDB = CIA_TOOLS / "seeddb.bin"

DEFAULT_DBIN = ROOT / "rebuild_dbin2"
DEFAULT_EXTRACTED = ROOT.parent / "New Love Plus Plus" / "extracted"
# Optional RomFS template (sibling dump). Copied by patch_cia — never mutated in-place.
DEFAULT_ROMFS = DEFAULT_EXTRACTED / "romfs"
DEFAULT_MAIN_CXI = DEFAULT_EXTRACTED / "main.cxi"
DEFAULT_IMG_BIN = DEFAULT_EXTRACTED / "romfs" / "img.bin"
DEFAULT_IMAGES = ROOT / "assets" / "images"
# Optional PNG-pack intermediate (not gold).
DEFAULT_PACKED_IMG = ROOT / "cache" / "new_img.bin"
# Gold bake + TRB overlay (durable release artifacts).
DEFAULT_BAKE_IMG = ROOT / "release" / "bake_img.bin"
DEFAULT_ROMFS_OVERLAY = ROOT / "release" / "romfs_overlay"
_LEGACY_ROMFS_OVERLAY = ROOT / "cache" / "romfs_overlay"
DEFAULT_CODE_BIN = DEFAULT_EXTRACTED / "exefs" / "code.bin"
TITLE_ID = "00040000000F4E00"
PACKS = ("NLP_01", "NLP_02", "script")

# Accepted SHA-1 digests for known New Love Plus+ dumps (CIA and/or .3ds/.cci).
# Typical decrypted CIAs will not match (by design).
# Some decrypted full .3ds dumps are listed (e.g. d138…) so cartridge dumps can hash-check.
# Encrypted dumps may still match SHA-1 but are rejected — decrypt yourself first.
ALLOWED_CIA_SHA1 = frozenset(
    {
        "a9fbd2e6d790b6cb6194f7820e1a71f597160f2b",  # encrypted CIA (headmasta) — hash only; reject at crypto gate
        "811d2f0f72c2a1437997256f30b18fbb2dea6cda",  # decrypted CIA
        "6af1751f8b4f9d074311f3a7cf2b5d3c5e807cc8",
        "d138d92fd9d522827cb9665bc2c954f1e8ba1f92",  # decrypted full .3ds
        "6428e72eefec31d19282d2c7f0cb5082723a3206",  # encrypted trim .3ds — hash only; reject at crypto gate
    }
)
ALLOWED_DUMP_SHA1 = ALLOWED_CIA_SHA1
# Primary / historically documented dump (kept for CLI help / display).
EXPECTED_CIA_SHA1 = "a9fbd2e6d790b6cb6194f7820e1a71f597160f2b"

_CCI_EXTS = {".3ds", ".cci"}
_CIA_EXTS = {".cia"}

ENCRYPTED_ROM_HELP = (
    "Input ROM is still encrypted. Decrypt it yourself first "
    "(GodMode9, Batch CIA 3DS Decryptor Redux, etc.), "
    "then drop the decrypted .cia or .3ds/.cci.\n"
    "This patcher does not include a decryptor."
)


class PatchError(RuntimeError):
    pass


def _run(cmd: list[str | Path], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    printable = " ".join(str(c) for c in cmd)
    print(f"  > {printable}")
    proc = subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout.strip():
        print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip(), file=sys.stderr)
    if check and proc.returncode != 0:
        raise PatchError(f"command failed ({proc.returncode}): {printable}")
    return proc


def _require_tools() -> None:
    missing = [p for p in (TOOL_3DS, CTRTOOL, MAKEROM, SEEDDB) if not p.is_file()]
    if missing:
        names = ", ".join(p.name for p in missing)
        raise PatchError(
            f"missing CIA tools: {names}\n"
            f"Run: python src/setup_tools.py\n"
            f"Expected under: {CIA_TOOLS}"
        )


def _ctrtool_info(path: Path) -> str:
    proc = _run([CTRTOOL, "--seeddb", SEEDDB, path], check=False)
    return (proc.stdout or "") + (proc.stderr or "")


def detect_rom_kind(path: Path) -> str:
    """Return 'cia' or 'cci' from extension / NCSD magic."""
    ext = path.suffix.lower()
    if ext in _CIA_EXTS:
        return "cia"
    if ext in _CCI_EXTS:
        return "cci"
    try:
        with path.open("rb") as fh:
            fh.seek(0x100)
            magic = fh.read(4)
        if magic == b"NCSD":
            return "cci"
    except OSError:
        pass
    raise PatchError(
        f"unsupported rom type: {path.name} "
        f"(expected .cia / .3ds / .cci)"
    )


def is_encrypted_cia(cia: Path) -> bool:
    """True if main NCCH still has a retail crypto key (CIA or CCI)."""
    info = _ctrtool_info(cia)
    # Decrypted NCCH shows "Crypto Key: None"; encrypted shows Secure/Fixed/...
    if re.search(r"Crypto Key\s+None", info):
        return False
    if re.search(r"Crypto Key\s+(Secure|Fixed|Key 0x)", info):
        return True
    if "NCCH" in info and "Crypto Key" in info:
        return "None" not in info.split("Crypto Key", 1)[-1][:40]
    raise PatchError(f"could not determine encryption state of {cia}")


is_encrypted_rom = is_encrypted_cia


def require_decrypted_rom(rom: Path, *, assume_decrypted: bool = False) -> None:
    """Refuse encrypted dumps — user must decrypt outside this tool."""
    if assume_decrypted or ("decrypted" in rom.name.lower()):
        print("[crypto] skipped check (flag / filename assumes decrypted)")
        return
    try:
        encrypted = is_encrypted_rom(rom)
    except PatchError as exc:
        raise PatchError(
            f"{exc}\n"
            "Pass --assume-decrypted only if you are sure the dump is already decrypted."
        ) from exc
    if encrypted:
        raise PatchError(ENCRYPTED_ROM_HELP)
    print("[crypto] OK — dump is decrypted")


def extract_cci_partitions(cci: Path, out_dir: Path) -> tuple[Path, Path | None]:
    """Extract partition0 (game CXI) and optional partition1 (manual) from CCI."""
    out_dir.mkdir(parents=True, exist_ok=True)
    main = out_dir / "partition0.cxi"
    manual = out_dir / "partition1.cfa"
    if main.is_file():
        print(f"[extract] reusing {main.name}")
        return main, (manual if manual.is_file() else None)

    print(f"[extract] extracting CCI partitions from {cci.name} ...")
    cmd: list[str | Path] = [
        TOOL_3DS,
        "-xvtf",
        "cci",
        cci,
        "--partition0",
        main,
    ]
    # Always request partition1; 3dstool skips missing slots quietly on some dumps.
    cmd.extend(["--partition1", manual])
    _run(cmd, check=False)
    if not main.is_file():
        raise PatchError(f"3dstool failed to extract partition0 from {cci}")
    return main, (manual if manual.is_file() and manual.stat().st_size > 0 else None)


def prepare_cxi_from_rom(
    rom: Path,
    work: Path,
    *,
    kind: str,
    assume_decrypted: bool = False,
) -> tuple[Path, Path | None, int | None]:
    """Extract rom → (cxi, manual, title_version). Requires a decrypted dump."""
    require_decrypted_rom(rom, assume_decrypted=assume_decrypted)
    title_ver = parse_title_version(rom)

    if kind == "cia":
        cxi, manual = extract_cia_contents(rom, work / "contents")
        title_ver = parse_title_version(rom) or title_ver
        return cxi, manual, title_ver

    cxi, manual = extract_cci_partitions(rom, work / "cci_parts")
    return cxi, manual, title_ver


def extract_cia_contents(cia: Path, out_dir: Path) -> tuple[Path, Path | None]:
    """Extract CIA content files; return (content0, content1|None)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("content.0000.*"))
    if existing:
        c0 = existing[0]
        c1s = sorted(out_dir.glob("content.0001.*"))
        print(f"[extract] reusing {c0.name}")
        return c0, (c1s[0] if c1s else None)

    print(f"[extract] extracting contents from {cia.name} ...")
    _run([CTRTOOL, "--seeddb", SEEDDB, f"--contents={out_dir / 'content'}", cia])
    c0s = sorted(out_dir.glob("content.0000.*"))
    if not c0s:
        raise PatchError("ctrtool --contents produced no content.0000.*")
    c1s = sorted(out_dir.glob("content.0001.*"))
    return c0s[0], (c1s[0] if c1s else None)


def split_cxi(cxi: Path, parts_dir: Path) -> dict[str, Path]:
    parts_dir.mkdir(parents=True, exist_ok=True)
    needed = {
        "header": parts_dir / "ncchheader.bin",
        "exh": parts_dir / "exheader.bin",
        "plain": parts_dir / "plain.bin",
        "logo": parts_dir / "logo.bin",
        "exefs": parts_dir / "exefs.bin",
        "romfs": parts_dir / "romfs.bin",
    }
    if all(p.is_file() for p in needed.values()):
        print("[cxi] reusing split NCCH parts")
        return needed

    print(f"[cxi] splitting {cxi.name} ...")
    _run(
        [
            TOOL_3DS,
            "-xvtf",
            "cxi",
            cxi,
            "--header",
            needed["header"],
            "--exh",
            needed["exh"],
            "--plain",
            needed["plain"],
            "--logo",
            needed["logo"],
            "--exefs",
            needed["exefs"],
            "--romfs",
            needed["romfs"],
        ]
    )
    return needed


def ensure_romfs_dir(romfs_bin: Path, romfs_dir: Path, reuse: Path | None) -> Path:
    if reuse and reuse.is_dir() and (reuse / "script" / "bin" / "script").is_dir():
        print(f"[romfs] using extracted tree: {reuse}")
        return reuse

    if romfs_dir.is_dir() and (romfs_dir / "script" / "bin" / "script").is_dir():
        print(f"[romfs] using existing work tree: {romfs_dir}")
        return romfs_dir

    print(f"[romfs] extracting {romfs_bin.name} (large, may take a few minutes) ...")
    romfs_dir.mkdir(parents=True, exist_ok=True)
    _run([TOOL_3DS, "-xvtf", "romfs", romfs_bin, "--romfs-dir", romfs_dir])
    return romfs_dir


# Layered inject: Manaka t* + EngPatcher p* + NLPPPATCH ~28% (see script_inject.py).
from script_inject import resolve_script_source  # noqa: E402


def inject_dbin2(romfs_dir: Path, dbin_root: Path) -> int:
    total = 0
    layers: dict[str, int] = {"manaka": 0, "eng_p": 0, "nlppatch": 0}
    skipped = 0
    for pack in PACKS:
        src_dir = dbin_root / pack
        if not src_dir.is_dir():
            raise PatchError(f"missing packed scripts: {src_dir}")
        dest_dir = romfs_dir / "script" / "bin" / pack
        if not dest_dir.is_dir():
            raise PatchError(f"RomFS missing script pack folder: {dest_dir}")
        files = sorted(src_dir.glob("*.dbin2"))
        if not files:
            raise PatchError(f"no .dbin2 files in {src_dir}")
        injected = 0
        pack_layers: dict[str, int] = {}
        for src in files:
            chosen, tag = resolve_script_source(pack, src.stem, dbin_root)
            if chosen is None:
                skipped += 1
                continue
            shutil.copy2(chosen, dest_dir / src.name)
            total += 1
            injected += 1
            if tag in layers:
                layers[tag] += 1
                pack_layers[tag] = pack_layers.get(tag, 0) + 1
        layer_note = ", ".join(f"{k}={v}" for k, v in sorted(pack_layers.items()))
        print(
            f"[inject] {pack}: {injected} EN ({layer_note or 'none'})"
            f" — {len(files) - injected} JP (base ROM)"
        )
    print(
        f"[inject] total EN: {total} "
        f"(manaka={layers['manaka']}, p*={layers['eng_p']}, nlppatch={layers['nlppatch']})"
    )
    if skipped:
        print(f"[inject] {skipped} script slot(s) left Japanese")
    return total


def rebuild_romfs(romfs_dir: Path, out_bin: Path) -> None:
    print("[romfs] rebuilding romfs.bin (large, may take several minutes) ...")
    if out_bin.exists():
        out_bin.unlink()
    _run([TOOL_3DS, "-cvtf", "romfs", out_bin, "--romfs-dir", romfs_dir])
    if not out_bin.is_file() or out_bin.stat().st_size < 1024:
        raise PatchError("romfs rebuild failed")


def rebuild_cxi(parts: dict[str, Path], new_romfs: Path, out_cxi: Path) -> None:
    print("[cxi] rebuilding patched CXI ...")
    if out_cxi.exists():
        out_cxi.unlink()
    cmd: list[str | Path] = [
        TOOL_3DS,
        "-cvtf",
        "cxi",
        out_cxi,
        "--header",
        parts["header"],
        "--exh",
        parts["exh"],
        "--exefs",
        parts["exefs"],
        "--romfs",
        new_romfs,
        "--not-encrypt",
    ]
    if parts["plain"].is_file() and parts["plain"].stat().st_size:
        cmd.extend(["--plain", parts["plain"]])
    if parts["logo"].is_file() and parts["logo"].stat().st_size:
        cmd.extend(["--logo", parts["logo"]])
    _run(cmd)
    if not out_cxi.is_file():
        raise PatchError("CXI rebuild failed")


def rebuild_cia(cxi: Path, manual: Path | None, out_cia: Path, title_ver: int | None) -> None:
    print(f"[cia] building {out_cia.name} ...")
    if out_cia.exists():
        out_cia.unlink()
    cmd: list[str | Path] = [
        MAKEROM,
        "-f",
        "cia",
        "-o",
        out_cia,
        "-ignoresign",
        "-target",
        "p",
        "-content",
        f"{cxi}:0:0",
    ]
    if manual and manual.is_file():
        cmd.extend(["-content", f"{manual}:1:1"])
    if title_ver is not None:
        cmd.extend(["-ver", str(title_ver)])
    _run(cmd)
    if not out_cia.is_file():
        raise PatchError("CIA rebuild failed")


def _resolve_resident_trb(romfs_hint: Path | None) -> Path | None:
    candidates = []
    for overlay in (DEFAULT_ROMFS_OVERLAY, _LEGACY_ROMFS_OVERLAY):
        candidates.append(
            overlay
            / "SystemData"
            / "TextResource"
            / "textresource_resident_jpn.trb"
        )
    if romfs_hint is not None:
        candidates.append(
            romfs_hint
            / "SystemData"
            / "TextResource"
            / "textresource_resident_jpn.trb"
        )
    candidates.append(
        DEFAULT_ROMFS
        / "SystemData"
        / "TextResource"
        / "textresource_resident_jpn.trb"
    )
    candidates.append(
        DEFAULT_EXTRACTED
        / "romfs"
        / "SystemData"
        / "TextResource"
        / "textresource_resident_jpn.trb"
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def apply_name_patches(
    romfs_dir: Path,
    *,
    skip: bool = False,
) -> None:
    """English heroine names in scripts / resident TRB / img.bin name table."""
    if skip:
        print("[names] skipped (--skip-name-patches)")
        return
    from patch_names import apply_romfs_name_patches

    apply_romfs_name_patches(romfs_dir)


def _unpack_exefs(exefs_bin: Path, exefs_dir: Path) -> tuple[Path, Path]:
    """Unpack ExeFS; return (code.bin path, exefs.header path)."""
    if exefs_dir.exists():
        shutil.rmtree(exefs_dir)
    exefs_dir.mkdir(parents=True)
    header = exefs_dir / "exefs.header"
    print("[code] unpacking ExeFS ...")
    _run(
        [
            TOOL_3DS,
            "-xvtf",
            "exefs",
            exefs_bin,
            "--exefs-dir",
            exefs_dir,
            "--header",
            header,
        ]
    )
    code = exefs_dir / "code.bin"
    if not code.is_file():
        alt = exefs_dir / ".code"
        if alt.is_file():
            code = alt
        else:
            raise PatchError(f"no code.bin in unpacked ExeFS: {exefs_dir}")
    if not header.is_file():
        raise PatchError(f"no ExeFS header written: {header}")
    return code, header


def _repack_exefs(exefs_dir: Path, header: Path, out: Path) -> Path:
    if out.exists():
        out.unlink()
    print("[code] repacking ExeFS ...")
    _run(
        [
            TOOL_3DS,
            "-cvtf",
            "exefs",
            out,
            "--exefs-dir",
            exefs_dir,
            "--header",
            header,
        ]
    )
    if not out.is_file():
        raise PatchError("ExeFS rebuild failed")
    return out


def _blz_uncompress(src: Path, dest: Path) -> Path:
    """BLZ-decompress ExeFS .code (stock ~4.4MB -> ~8.1MB)."""
    if dest.exists():
        dest.unlink()
    _run(
        [
            TOOL_3DS,
            "-uvf",
            src,
            "--compress-type",
            "blz",
            "--compress-out",
            dest,
        ]
    )
    if not dest.is_file():
        raise PatchError(f"BLZ uncompress failed: {src}")
    return dest


def _blz_compress(src: Path, dest: Path, *, exact_size: int | None = None) -> Path:
    """BLZ-compress decompressed code.bin back into ExeFS slot size."""
    if dest.exists():
        dest.unlink()
    _run(
        [
            TOOL_3DS,
            "-zvf",
            src,
            "--compress-type",
            "blz",
            "--compress-out",
            dest,
        ]
    )
    if not dest.is_file():
        raise PatchError(f"BLZ compress failed: {src}")
    if exact_size is not None and dest.stat().st_size != exact_size:
        raise PatchError(
            f"BLZ compress size {dest.stat().st_size} != ExeFS slot {exact_size}. "
            "code.bin changes must stay BLZ-compatible with the stock compressed size."
        )
    return dest


def patch_exefs_code(exefs_bin: Path, work: Path) -> Path:
    """Unpack ExeFS, BLZ-decompress, apply name patch, recompress, repack."""
    from patch_code import patch_code_bin

    exefs_dir = work / "exefs_patched"
    code_cmp, header = _unpack_exefs(exefs_bin, exefs_dir)
    slot = code_cmp.stat().st_size
    code_dec = work / "code_namepatch_dec.bin"
    _blz_uncompress(code_cmp, code_dec)
    try:
        patch_code_bin(code_dec, force=True)
    except ValueError as exc:
        raise PatchError(str(exc)) from exc
    _blz_compress(code_dec, code_cmp, exact_size=slot)
    return _repack_exefs(exefs_dir, header, work / "exefs_namepatch.bin")


def inject_exefs_code(exefs_bin: Path, work: Path, code_src: Path) -> Path:
    """Replace ExeFS .code with a prebuilt binary (decompressed or already BLZ).

    Decompressed LayeredFS/Azahar code.bin (~8.1MB) is BLZ-compressed. Small
    patches that fill .text zero-pad may grow the compressed payload slightly;
    3dstool ExeFS/CXI rebuild accepts the larger .code section.
    """
    code_src = code_src.resolve()
    if not code_src.is_file():
        raise PatchError(f"--inject-code not found: {code_src}")
    exefs_dir = work / "exefs_injected"
    code_cmp, header = _unpack_exefs(exefs_bin, exefs_dir)
    slot = code_cmp.stat().st_size
    src_size = code_src.stat().st_size

    if src_size == slot:
        code_cmp.write_bytes(code_src.read_bytes())
        print(f"[code] injected compressed {code_src} ({src_size:,} bytes)")
    else:
        # Azahar/LayeredFS code.bin is decompressed (~8.1MB).
        print(f"[code] BLZ-compressing {code_src.name} ({src_size:,}; stock slot {slot:,}) ...")
        tmp = work / "code_inject_cmp.bin"
        _blz_compress(code_src, tmp, exact_size=None)
        new_size = tmp.stat().st_size
        if new_size != slot:
            print(
                f"[code] BLZ size {new_size:,} (was {slot:,}; "
                f"delta {new_size - slot:+d}) — ExeFS will grow"
            )
        code_cmp.write_bytes(tmp.read_bytes())
        print(f"[code] injected decompressed->BLZ {code_src}")
    return _repack_exefs(exefs_dir, header, work / "exefs_injected.bin")


def resolve_romfs_overlay(args: argparse.Namespace) -> Path | None:
    """Release/cache TRB overlay dir, if any."""
    if args.romfs_overlay:
        overlay = Path(args.romfs_overlay).resolve()
        return overlay if overlay.is_dir() else None
    if DEFAULT_ROMFS_OVERLAY.is_dir():
        return DEFAULT_ROMFS_OVERLAY
    if _LEGACY_ROMFS_OVERLAY.is_dir():
        return _LEGACY_ROMFS_OVERLAY
    return None


def apply_romfs_overlay(romfs_dir: Path, overlay: Path) -> int:
    """Copy files from overlay onto romfs_dir (files only; keeps relative paths)."""
    overlay = overlay.resolve()
    if not overlay.is_dir():
        raise PatchError(f"--romfs-overlay not a directory: {overlay}")
    count = 0
    for src in overlay.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(overlay)
        dest = romfs_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        count += 1
    print(f"[overlay] copied {count} files from {overlay}")
    return count


def write_layeredfs(
    out_dir: Path,
    dbin_root: Path,
    img_bin: Path | None = None,
    *,
    resident_src: Path | None = None,
    code_bin_src: Path | None = None,
    patch_code: bool = False,
    skip_name_patches: bool = False,
    romfs_overlay: Path | None = None,
) -> int:
    """Emit a Luma/Azahar LayeredFS drop (same format as Makein/NLPPATCH releases)."""
    title_root = out_dir / TITLE_ID
    title_romfs = title_root / "romfs"
    title_dir = title_romfs / "script" / "bin"
    count = 0
    for pack in PACKS:
        src_dir = dbin_root / pack
        if not src_dir.is_dir():
            raise PatchError(f"missing packed scripts: {src_dir}")
        dest = title_dir / pack
        dest.mkdir(parents=True, exist_ok=True)
        files = sorted(src_dir.glob("*.dbin2"))
        pack_injected = 0
        pack_layers: dict[str, int] = {}
        for src in files:
            chosen, tag = resolve_script_source(pack, src.stem, dbin_root)
            if chosen is None:
                continue
            shutil.copy2(chosen, dest / src.name)
            count += 1
            pack_injected += 1
            if tag != "jp":
                pack_layers[tag] = pack_layers.get(tag, 0) + 1
        skipped = len(files) - pack_injected
        layer_note = ", ".join(f"{k}={v}" for k, v in sorted(pack_layers.items()))
        note = f" ({layer_note})" if layer_note else ""
        skip_note = f", {skipped} JP" if skipped else ""
        print(f"[layeredfs] {pack}: {pack_injected} EN{note}{skip_note}")

    if resident_src and resident_src.is_file():
        dest_trb = (
            title_romfs
            / "SystemData"
            / "TextResource"
            / "textresource_resident_jpn.trb"
        )
        dest_trb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resident_src, dest_trb)
        print(f"[layeredfs] resident TRB <- {resident_src}")

    if img_bin and img_bin.is_file():
        title_romfs.mkdir(parents=True, exist_ok=True)
        dest_img = title_romfs / "img.bin"
        print(f"[layeredfs] copying img.bin ({img_bin.stat().st_size:,} bytes) ...")
        shutil.copy2(img_bin, dest_img)

    if patch_code:
        src = code_bin_src if code_bin_src and code_bin_src.is_file() else DEFAULT_CODE_BIN
        if not src.is_file():
            raise PatchError(
                f"--patch-code needs a vanilla code.bin (not found: {src}). "
                "Pass --code-bin PATH."
            )
        from patch_code import write_patched_code_bin

        dest_code = title_root / "code.bin"
        write_patched_code_bin(src, dest_code, force=True)
        print(f"[layeredfs] code.bin (single-pane name draw)")

    if romfs_overlay is not None:
        apply_romfs_overlay(title_romfs, romfs_overlay)

    # Patch names in the overlay tree (dbin tokens → plain Takane/Rinko/Nene, etc.)
    apply_name_patches(title_romfs, skip=skip_name_patches)

    readme = out_dir / "README.txt"
    title_folder = f"{TITLE_ID}"
    readme.write_text(
        "\n".join(
            [
                "New Love Plus+ English — Luma / LayeredFS install",
                f"Title ID: {TITLE_ID}",
                "",
                "=== Real 3DS (Luma CFW) ===",
                "",
                "1. You need New Love Plus+ already installed on the console",
                "   (retail cartridge or CIA from your own dump).",
                "",
                "2. On your SD card, open:",
                "     luma/titles/",
                "   (create the folders if they are missing)",
                "",
                f"3. Copy this entire folder onto the SD card:",
                f"     {title_folder}",
                "   so you end up with:",
                f"     SD:/luma/titles/{title_folder}/",
                "   (the folder must contain romfs/ and optionally code.bin)",
                "",
                "4. In Luma configuration, enable:",
                "     Enable game patching",
                "",
                "5. Boot the game from the Home Menu as usual.",
                "   LayeredFS overlays the English files on top of the install.",
                "",
                "=== Emulator (Azahar / Citra) ===",
                "",
                f"Copy the {title_folder} folder to:",
                "  %AppData%/Azahar/load/mods/",
                "  (or your Citra load/mods/ folder)",
                "",
                "=== What is inside ===",
                "",
                "  romfs/script/bin/{NLP_01,NLP_02,script}/*.dbin2  — English dialog",
                "  romfs/SystemData/.../textresource_resident_jpn.trb — heroine names",
                "  romfs/img.bin — English UI textures (when UI bake was included)",
                "  code.bin — optional name-input fix (only with --patch-code)",
                "Dialog nickname tokens (▲高嶺＊＊▲ etc.) are kept in scripts;",
                "resident TRB / img.bin use plain English heroine names — see src/patch_names.py.",
                "",
                "No CIA reinstall is required when using LayeredFS.",
                "Same install style as LovePlusProject/NLPPATCH releases.",
                "",
                "Note: the drop patcher writes this folder before rebuilding the CIA.",
                "If the CIA step fails, this Luma overlay is still kept on disk.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # Legacy name for anyone following older docs.
    legacy_readme = out_dir / "LAYEREDFS_README.txt"
    if legacy_readme != readme:
        legacy_readme.write_text(readme.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[layeredfs] wrote {count} scripts under {title_root}")
    return count


def _resolve_source_img_bin(args: argparse.Namespace) -> Path:
    """Vanilla img.bin used as the pack base (never overwrite the dump in-place)."""
    explicit = Path(args.img_bin).resolve() if args.img_bin else DEFAULT_IMG_BIN
    if explicit.is_file():
        return explicit
    if DEFAULT_IMG_BIN.is_file():
        return DEFAULT_IMG_BIN.resolve()
    raise PatchError(
        "No source img.bin for UI packing. Pass --img-bin path/to/romfs/img.bin "
        f"(tried {explicit})."
    )


def resolve_inject_img(args: argparse.Namespace) -> Path:
    """Prefer release/bake_img.bin; fall back to cache/new_img.bin / --packed-img."""
    explicit = Path(args.packed_img).resolve() if args.packed_img else None
    default_packed = DEFAULT_PACKED_IMG.resolve()
    # --repack-images always targets the optional PNG path (not gold bake).
    if args.repack_images:
        return explicit if explicit is not None else default_packed
    # Explicit non-default --packed-img wins.
    if explicit is not None and explicit != default_packed:
        return explicit
    if DEFAULT_BAKE_IMG.is_file():
        return DEFAULT_BAKE_IMG.resolve()
    if explicit is not None:
        return explicit
    return default_packed


def _title_pkg_has_eng_patch(img_path: Path, *, pkg_idx: int = 5261) -> bool:
    """True if Title.arc pkg contains ``timg/Eng_Patch.bclim`` (gold Eng badge)."""
    # Local imports: nlpp-tools + darcutil are heavy; only needed for this check.
    sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))
    sys.path.insert(0, str(ROOT / "src"))
    from darcutil import DarcArchive  # noqa: WPS433
    from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: WPS433

    raw = img_path.read_bytes()
    im = ImgBin(str(img_path))
    im.parse(False)
    if pkg_idx >= len(im.entries) or im.entries[pkg_idx] is None:
        return False
    res = im.entries[pkg_idx]
    blob = raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
    tmp = img_path.parent / f"_engpatch_check_{pkg_idx}.bin"
    tmp.write_bytes(blob)
    try:
        pkg = Package(FileWindow(str(tmp)), 0)
        pkg.parse(False)
        arc = next((e for e in pkg.entries if isinstance(e, ARC)), None)
        if arc is None:
            return False
        darc = DarcArchive(bytearray(arc.parsed()))
        return darc.find("timg/Eng_Patch.bclim") is not None
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _require_eng_patch(img_path: Path, *, context: str) -> None:
    if _title_pkg_has_eng_patch(img_path):
        print(f"[images] Eng Patch badge present in Title pkg 5261 ({context})")
        return
    raise PatchError(
        f"{context} missing Title Eng_Patch badge (pkg 5261): {img_path}\n"
        "  Stale LayeredFS/luma imgs often have EN menus but no badge.\n"
        "  Fix: python tools/deploy_title_engpatch_en.py\n"
        "       (NLPP_DEPLOY_IMG=release/bake_img.bin), then Drop with that bake."
    )


def _require_name_input_for_ui(args: argparse.Namespace) -> None:
    """Full UI CIA must inject Profile name-input ExeFS (no soft skip)."""
    if not args.inject_code and not args.patch_code:
        raise PatchError(
            "Profile name-input code.bin is required for a full UI patch.\n"
            "  Missing --inject-code / --patch-code.\n"
            "  Fix: python tools/rebuild_bake_img.py --rom your.cia|.3ds\n"
            "       (writes release/name_input_code.bin), then Drop again."
        )
    if args.inject_code and not Path(args.inject_code).is_file():
        raise PatchError(
            f"Profile name-input missing: {args.inject_code}\n"
            "  Fix: python tools/rebuild_bake_img.py --rom your.cia|.3ds"
        )


def pack_ui_images(args: argparse.Namespace, work: Path) -> Path:
    """Inject gold bake, or pack assets/images into cache/new_img.bin."""
    from pack_images import PackError, pack_images

    images = Path(args.images).resolve()
    out_img = resolve_inject_img(args)
    out_img.parent.mkdir(parents=True, exist_ok=True)
    img_work = work / "img_work"

    # Gold bake: inject as-is (regenerate via tools/rebuild_bake_img.py).
    if (
        not args.repack_images
        and out_img.resolve() == DEFAULT_BAKE_IMG.resolve()
        and DEFAULT_BAKE_IMG.is_file()
    ):
        print(f"[images] using gold bake: {out_img}")
        print("         (rebuild with: python tools/rebuild_bake_img.py)")
        _require_eng_patch(out_img, context="gold bake")
        return out_img

    # Default: reuse PNG cache when present. --repack-images forces a rebuild.
    reuse = (not args.repack_images) and (
        args.reuse_packed_img or out_img.is_file()
    )
    if reuse and out_img.is_file():
        print(f"[images] reusing packed img.bin: {out_img}")
        print("         (delete it or pass --repack-images to rebuild from assets/images)")
        print(
            "         (gold bake: python tools/rebuild_bake_img.py "
            "→ release/bake_img.bin)"
        )
        # Explicit --packed-img (rebuild_test_cia / luma / Azahar) must still
        # carry the Eng Patch badge — stale Aug LayeredFS imgs omit it.
        _require_eng_patch(out_img, context=f"packed img {out_img}")
        return out_img

    src_img = _resolve_source_img_bin(args)
    workers = getattr(args, "image_workers", None)
    fine_tune = bool(getattr(args, "image_fine_tune", False))
    if not DEFAULT_BAKE_IMG.is_file():
        print(
            "[images] NOTE: release/bake_img.bin missing — packing PNG-only "
            "cache/new_img.bin (incomplete vs gold). "
            "Prefer: python tools/rebuild_bake_img.py",
            flush=True,
        )
    print(f"[images] packing UI PNGs from {images}")
    print(f"         base img.bin: {src_img}")
    print(f"         output:       {out_img}")
    print(
        "         (same-size BCLIM; exact-zlib"
        f"{' + fine-tune' if fine_tune else '; fine-tune off — use --image-fine-tune to enable'})"
    )
    try:
        pack_images(
            images,
            src_img,
            img_work,
            out_img,
            only_keys=None,
            workers=workers,
            fine_tune=fine_tune,
        )
    except PackError as exc:
        raise PatchError(f"image packing failed: {exc}") from exc
    return out_img


def _layeredfs_img_fallback(args: argparse.Namespace) -> Path | None:
    """Existing bake/packed img when live UI packing failed."""
    try:
        candidate = resolve_inject_img(args)
        if candidate.is_file():
            return candidate
    except (OSError, PatchError):
        pass
    if args.packed_img:
        explicit = Path(args.packed_img).resolve()
        if explicit.is_file():
            return explicit
    if args.name_img:
        img_src = Path(args.img_bin).resolve()
        if img_src.is_file():
            return img_src
    return None


def _layeredfs_title_dir(out_dir: Path) -> Path:
    return out_dir / TITLE_ID


def _print_layeredfs_recovery(out_dir: Path) -> None:
    title_dir = _layeredfs_title_dir(out_dir)
    if not title_dir.is_dir():
        return
    print()
    print("=== Luma LayeredFS still available ===")
    print(f"Folder:  {title_dir}")
    print(f"Install: SD:/luma/titles/{TITLE_ID}/  (see {out_dir / 'README.txt'})")
    print("The CIA rebuild failed, but this overlay can still be used on Luma CFW.")


def rebuild_patched_cia(
    args: argparse.Namespace,
    *,
    rom_in: Path,
    kind: str,
    dbin_root: Path,
    work: Path,
    out_cia: Path,
    packed_img: Path | None,
    romfs_overlay: Path | None,
) -> None:
    """Extract, inject, and rebuild the output CIA. Raises PatchError on failure."""
    # 1–2) Extract game CXI (+ optional manual) from decrypted rom
    title_ver: int | None = None
    if args.cxi and Path(args.cxi).is_file():
        cxi = Path(args.cxi).resolve()
        manual = Path(args.manual).resolve() if args.manual else None
        title_ver = parse_title_version(rom_in)
        print(f"[extract] using provided CXI: {cxi}")
    elif (
        kind == "cia"
        and DEFAULT_EXTRACTED.is_dir()
        and any(DEFAULT_EXTRACTED.glob("content.0000.*"))
    ):
        c0 = sorted(DEFAULT_EXTRACTED.glob("content.0000.*"))[0]
        c1s = sorted(DEFAULT_EXTRACTED.glob("content.0001.*"))
        cxi, manual = c0, (c1s[0] if c1s else None)
        title_ver = parse_title_version(rom_in)
        print(f"[extract] using sibling extracted/: {cxi.name}")
    else:
        cxi, manual, title_ver = prepare_cxi_from_rom(
            rom_in,
            work,
            kind=kind,
            assume_decrypted=args.assume_decrypted,
        )

    parts = split_cxi(cxi, work / "ncch_parts")

    # 3) RomFS tree + inject
    reuse = Path(args.romfs).resolve() if args.romfs else (
        DEFAULT_ROMFS if DEFAULT_ROMFS.is_dir() else None
    )
    # Prefer linking/copying an existing RomFS tree; fall back to extracting romfs.bin.
    if args.in_place_romfs and reuse:
        romfs_dir = reuse
        print(f"[romfs] in-place inject into {romfs_dir}")
    else:
        romfs_work = work / "romfs"
        if reuse and (reuse / "script" / "bin" / "script").is_dir():
            if args.link_romfs:
                if romfs_work.exists():
                    # Only remove empty junction/dir we created previously
                    try:
                        romfs_work.rmdir()
                    except OSError:
                        shutil.rmtree(romfs_work)
                print(f"[romfs] junction -> {reuse}")
                _run(["cmd", "/c", "mklink", "/J", str(romfs_work), str(reuse)])
                romfs_dir = romfs_work
            elif (romfs_work / "script" / "bin" / "script").is_dir():
                print(f"[romfs] reusing work tree: {romfs_work}")
                romfs_dir = romfs_work
            else:
                print(f"[romfs] copying base tree from {reuse} (slow once) ...")
                if romfs_work.exists():
                    shutil.rmtree(romfs_work)
                shutil.copytree(reuse, romfs_work)
                romfs_dir = romfs_work
        else:
            romfs_dir = ensure_romfs_dir(parts["romfs"], romfs_work, reuse=None)

    injected = inject_dbin2(romfs_dir, dbin_root)
    print(f"[inject] total .dbin2 files: {injected}")

    if packed_img is not None:
        dest_img = romfs_dir / "img.bin"
        print(f"[inject] img.bin -> {dest_img}")
        shutil.copy2(packed_img, dest_img)
        _require_eng_patch(dest_img, context="injected img.bin")

    if romfs_overlay is not None:
        apply_romfs_overlay(romfs_dir, romfs_overlay)

    # Heroine names: plain English in dialog scripts + UI name tables.
    apply_name_patches(romfs_dir, skip=args.skip_name_patches)

    if args.inject_code and args.patch_code:
        raise PatchError("use either --inject-code or --patch-code, not both")
    if args.inject_code:
        parts = dict(parts)
        parts["exefs"] = inject_exefs_code(parts["exefs"], work, Path(args.inject_code))
    elif args.patch_code:
        parts = dict(parts)
        parts["exefs"] = patch_exefs_code(parts["exefs"], work)

    # 4) Rebuild containers
    new_romfs = work / "romfs_patched.bin"
    rebuild_romfs(romfs_dir, new_romfs)

    patched_cxi = work / "patched.cxi"
    rebuild_cxi(parts, new_romfs, patched_cxi)

    rebuild_cia(patched_cxi, manual, out_cia, title_ver)

    if not args.keep_work:
        cleanup_patch_artifacts(
            work,
            out_cia=out_cia,
            packed_img=packed_img,
        )


def parse_title_version(cia: Path) -> int | None:
    info = _ctrtool_info(cia)
    m = re.search(r"TitleVersion:\s*.*?\((\d+)\)", info)
    if m:
        return int(m.group(1))
    m = re.search(r"Version:\s*(\d+)", info)
    return int(m.group(1)) if m else None


def sha1_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_cia_sha1(
    cia: Path,
    expected: str | None = None,
    *,
    allowed: frozenset[str] | set[str] | None = None,
) -> str:
    """Verify CIA SHA-1 against one digest or the known-dump allowlist."""
    if expected:
        allowed_set = {expected.lower()}
    else:
        allowed_set = {h.lower() for h in (allowed or ALLOWED_CIA_SHA1)}

    print(f"[hash] computing SHA-1 of {cia.name} ...")
    digest = sha1_file(cia)
    print(f"[hash] got:      {digest}")
    if len(allowed_set) == 1:
        only = next(iter(allowed_set))
        print(f"[hash] expected: {only}")
    else:
        print(f"[hash] allowed:  {len(allowed_set)} known dumps")

    if digest.lower() not in allowed_set:
        listed = "\n".join(f"    {h}" for h in sorted(allowed_set))
        raise PatchError(
            "Dump SHA-1 mismatch - refusing to patch.\n"
            f"  file:     {cia}\n"
            f"  got:      {digest}\n"
            f"  allowed:\n{listed}\n"
            "Use a matching New Love Plus+ dump (.cia / .3ds / .cci). "
            "Many decrypted CIAs will not match these hashes."
        )
    print("[hash] OK")
    return digest


def emit_spotpass_inject(args: argparse.Namespace) -> None:
    """Build SpotPass boss info.dat into out/ (default: real3ds). Soft-fail on errors."""
    if getattr(args, "skip_spotpass", False):
        print("[spotpass] skipped (--skip-spotpass)")
        return
    mode = getattr(args, "spotpass_mode", "real3ds") or "real3ds"
    script = TOOLS / "build_spotpass_inject.py"
    if not script.is_file():
        print(f"[spotpass] warning: missing {script}")
        return
    # Importable API (same process) so patch_cia does not depend on PATH.
    import importlib.util

    spec = importlib.util.spec_from_file_location("nlpp_build_spotpass_inject", script)
    if spec is None or spec.loader is None:
        print(f"[spotpass] warning: cannot load {script}")
        return
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        install = None
        if getattr(args, "spotpass_install_azahar", False):
            install = True
        flat = mod.build_inject(mode, install_azahar_sdmc=install)
        print(f"[spotpass] wrote {flat}")
    except Exception as exc:
        print(f"[spotpass] warning: {exc}")


def _summary_line(status: str, label: str, detail: str = "") -> str:
    """One summary row: status is OK / SKIPPED / OFF / WARN."""
    mark = {
        "OK": "[OK]     ",
        "SKIPPED": "[SKIPPED]",
        "OFF": "[OFF]    ",
        "WARN": "[WARN]   ",
    }.get(status, f"[{status}]")
    if detail:
        return f"  {mark} {label}: {detail}"
    return f"  {mark} {label}"


def build_patch_summary(
    *,
    out_cia: Path | None,
    packed_img: Path | None,
    layered_img: Path | None,
    layeredfs_out: Path | None,
    romfs_overlay: Path | None,
    args: argparse.Namespace,
    layeredfs_only: bool = False,
    eng_patch: bool | None = None,
) -> list[str]:
    """Human-readable include/skip report for the end of a patch run.

    Callers may pass ``eng_patch`` when already known; otherwise the packed img
    is probed (None = not applicable / not checked).
    """
    lines: list[str] = [
        "",
        "=" * 60,
        "  PATCH SUMMARY — read this before testing",
        "=" * 60,
    ]

    lines.append(_summary_line("OK", "Dialog scripts (.dbin2)", "injected"))

    if args.no_images or not args.with_images:
        lines.append(
            _summary_line(
                "SKIPPED",
                "UI img.bin (menus / Eng Patch)",
                "--no-images or images disabled — menus stay JP",
            )
        )
        lines.append(
            _summary_line(
                "SKIPPED",
                "Eng Patch title badge",
                "needs gold bake img.bin",
            )
        )
    elif packed_img is not None and packed_img.is_file():
        kind = (
            "gold bake"
            if packed_img.resolve() == DEFAULT_BAKE_IMG.resolve()
            else "packed img"
        )
        lines.append(
            _summary_line("OK", "UI img.bin (menus / chrome)", f"{kind}: {packed_img}")
        )
        if eng_patch is None:
            try:
                eng_patch = _title_pkg_has_eng_patch(packed_img)
            except Exception:  # noqa: BLE001 — summary must not crash the run
                eng_patch = None
        if eng_patch is True:
            lines.append(
                _summary_line(
                    "OK", "Eng Patch title badge", "Title pkg 5261 has Eng_Patch"
                )
            )
        elif eng_patch is False:
            lines.append(
                _summary_line(
                    "WARN",
                    "Eng Patch title badge",
                    "MISSING in injected img — should have hard-failed",
                )
            )
        else:
            lines.append(
                _summary_line("WARN", "Eng Patch title badge", "could not verify")
            )
    else:
        lines.append(
            _summary_line(
                "SKIPPED",
                "UI img.bin (menus / Eng Patch)",
                "not injected — menus stay JP",
            )
        )

    if getattr(args, "inject_code", None):
        p = Path(args.inject_code)
        if p.is_file():
            lines.append(_summary_line("OK", "Profile name-input code.bin", str(p)))
        else:
            lines.append(
                _summary_line("WARN", "Profile name-input code.bin", f"missing: {p}")
            )
    elif getattr(args, "patch_code", False):
        lines.append(
            _summary_line("OK", "Profile name-input", "--patch-code (single-pane)")
        )
    else:
        lines.append(
            _summary_line(
                "SKIPPED",
                "Profile name-input code.bin",
                "no --inject-code / --patch-code",
            )
        )

    if romfs_overlay is not None and Path(romfs_overlay).is_dir():
        lines.append(
            _summary_line("OK", "RomFS overlay (TRB etc.)", str(romfs_overlay))
        )
    else:
        lines.append(
            _summary_line("SKIPPED", "RomFS overlay (TRB etc.)", "none applied")
        )

    if getattr(args, "skip_name_patches", False):
        lines.append(
            _summary_line(
                "SKIPPED", "Heroine name table patches", "--skip-name-patches"
            )
        )
    else:
        lines.append(_summary_line("OK", "Heroine name table patches", "applied"))

    if getattr(args, "skip_hash", False):
        lines.append(_summary_line("SKIPPED", "Input CIA SHA-1 check", "--skip-hash"))
    else:
        lines.append(_summary_line("OK", "Input CIA SHA-1 check", "verified"))

    if layeredfs_only:
        lines.append(_summary_line("OFF", "Output CIA", "LayeredFS-only mode"))
    elif out_cia is not None and out_cia.is_file():
        lines.append(
            _summary_line(
                "OK",
                "Output CIA",
                f"{out_cia} ({out_cia.stat().st_size:,} bytes)",
            )
        )
    else:
        lines.append(_summary_line("WARN", "Output CIA", "missing"))

    if layeredfs_out is not None and _layeredfs_title_dir(layeredfs_out).is_dir():
        lines.append(
            _summary_line(
                "OK",
                "Luma LayeredFS",
                str(_layeredfs_title_dir(layeredfs_out)),
            )
        )
    elif layeredfs_out is not None and layered_img is None:
        lines.append(
            _summary_line(
                "WARN",
                "Luma LayeredFS",
                "path set but UI img.bin was not included",
            )
        )
    elif layeredfs_out is not None:
        lines.append(_summary_line("OK", "Luma LayeredFS", str(layeredfs_out)))
    else:
        lines.append(_summary_line("SKIPPED", "Luma LayeredFS", "not requested"))

    lines.append("=" * 60)
    images_off = args.no_images or not args.with_images or packed_img is None
    name_on = bool(
        getattr(args, "inject_code", None) or getattr(args, "patch_code", False)
    )
    if images_off and name_on:
        lines.append(
            "  !! Name-input ON but UI img OFF → JP menus, no Eng Patch badge."
        )
        lines.append(
            "  !! That is not a full English patch. Re-run with release/bake_img.bin."
        )
        lines.append("=" * 60)
    lines.append("")
    return lines


def print_patch_summary(lines: list[str]) -> None:
    for line in lines:
        print(line, flush=True)


def cmd_patch(args: argparse.Namespace) -> int:
    _require_tools()

    rom_in = Path(args.cia).resolve()
    if not rom_in.is_file():
        raise PatchError(f"ROM not found: {rom_in}")
    kind = detect_rom_kind(rom_in)

    dbin_root = Path(args.dbin).resolve()
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    out_cia = Path(args.out).resolve()
    out_cia.parent.mkdir(parents=True, exist_ok=True)

    timer = RunTimer("CIA patcher", heartbeat_s=60.0)
    print("=== NLPP English Patcher (→ CIA) ===")
    print(f"input:  {rom_in} ({kind})")
    print(f"dbin:   {dbin_root}")
    print(f"work:   {work}")
    print(f"output: {out_cia}")
    print()

    try:
        return _cmd_patch_body(args, rom_in, kind, dbin_root, work, out_cia, timer)
    except Exception:
        timer.finish("CIA patcher failed")
        raise
    except KeyboardInterrupt:
        timer.finish("CIA patcher aborted")
        raise


def _cmd_patch_body(
    args: argparse.Namespace,
    rom_in: Path,
    kind: str,
    dbin_root: Path,
    work: Path,
    out_cia: Path,
    timer: RunTimer,
) -> int:
    # Verify dump identity before extract / image / RomFS work.
    if args.skip_hash:
        print("[hash] skipped (--skip-hash)")
    else:
        verify_cia_sha1(rom_in, expected=args.expect_sha1)
    print()
    timer.mark("hash OK")

    packed_img: Path | None = None
    layered_img: Path | None = None
    if args.with_images and not args.no_images:
        # Hard-fail on image errors. Swallowing PatchError and continuing
        # scripts-only ships name-input code.bin + vanilla JP menus / no Eng
        # Patch badge — the Sep 2026 Desktop CIA regression.
        timer.mark("resolving / packing UI img.bin")
        packed_img = pack_ui_images(args, work)
        layered_img = packed_img
        timer.mark("UI img.bin ready")
        _require_name_input_for_ui(args)
    elif args.no_images:
        print("[images] skipped (--no-images)")

    romfs_hint = Path(args.romfs).resolve() if args.romfs else (
        DEFAULT_ROMFS if DEFAULT_ROMFS.is_dir() else None
    )
    resident_src = _resolve_resident_trb(romfs_hint)

    if layered_img is None and args.name_img:
        img_src = Path(args.img_bin).resolve()
        if img_src.is_file():
            layered_img = img_src
        else:
            print(f"[names] --name-img requested but img.bin missing: {img_src}")

    code_bin_src = Path(args.code_bin).resolve() if args.code_bin else DEFAULT_CODE_BIN

    if args.layeredfs_only and not args.layeredfs_out:
        args.layeredfs_out = str(ROOT / "out" / "luma")

    romfs_overlay = resolve_romfs_overlay(args)

    layeredfs_out: Path | None = None
    layeredfs_written = False
    if args.layeredfs_out:
        layeredfs_out = Path(args.layeredfs_out).resolve()
        timer.mark("writing LayeredFS")
        write_layeredfs(
            layeredfs_out,
            dbin_root,
            layered_img,
            resident_src=resident_src,
            code_bin_src=code_bin_src,
            patch_code=args.patch_code,
            skip_name_patches=args.skip_name_patches,
            romfs_overlay=romfs_overlay,
        )
        layeredfs_written = _layeredfs_title_dir(layeredfs_out).is_dir()

    if args.layeredfs_only:
        print()
        print("Done (LayeredFS only). No CIA rebuilt.")
        print_patch_summary(
            build_patch_summary(
                out_cia=None,
                packed_img=packed_img,
                layered_img=layered_img,
                layeredfs_out=layeredfs_out,
                romfs_overlay=romfs_overlay,
                args=args,
                layeredfs_only=True,
            )
        )
        if args.keep_work:
            emit_spotpass_inject(args)
        else:
            cleanup_out_dir(out_cia=out_cia)
            print("  SpotPass: python tools/build_spotpass_inject.py  (optional)")
        timer.finish("CIA patcher OK (LayeredFS only)")
        return 0

    try:
        timer.mark("rebuilding patched CIA")
        rebuild_patched_cia(
            args,
            rom_in=rom_in,
            kind=kind,
            dbin_root=dbin_root,
            work=work,
            out_cia=out_cia,
            packed_img=packed_img,
            romfs_overlay=romfs_overlay,
        )
    except PatchError:
        if layeredfs_written and layeredfs_out is not None:
            _print_layeredfs_recovery(layeredfs_out)
        raise

    print()
    print("=== Done ===")
    print(f"Patched CIA: {out_cia}")
    print(f"Size:        {out_cia.stat().st_size:,} bytes")
    if packed_img is not None and packed_img.is_file():
        print(f"Packed UI:   {packed_img}")
    if layeredfs_out is not None and layeredfs_out.is_dir():
        print(f"LayeredFS:   {layeredfs_out}")
    print_patch_summary(
        build_patch_summary(
            out_cia=out_cia,
            packed_img=packed_img,
            layered_img=layered_img,
            layeredfs_out=layeredfs_out,
            romfs_overlay=romfs_overlay,
            args=args,
            layeredfs_only=False,
        )
    )
    print("Notes:")
    print("  - Output is a decrypted CIA (works with FBI on CFW, Azahar, Citra).")
    print("  - Retail NCCH re-encryption is not done here; use Decrypt9WIP")
    print("    'CIA Encryptor (NCCH)' on a 3DS if you specifically need that.")
    if packed_img is None:
        print("  - UI images were SKIPPED — Main Menu stays Japanese.")
    elif packed_img.resolve() == DEFAULT_BAKE_IMG.resolve():
        print("  - UI images from gold bake (release/bake_img.bin), not PNG scratch.")
    else:
        print(f"  - UI images from packed img: {packed_img}")
    if args.keep_work:
        print("  - Scratch kept (--keep-work).")
        emit_spotpass_inject(args)
    else:
        cleanup_out_dir(out_cia=out_cia)
        print("  - out/ cleaned (kept *.cia, luma/, azahar_instances/).")
        print("  - SpotPass (optional): python tools/build_spotpass_inject.py")
    timer.finish("CIA patcher OK")
    return 0


def _is_reparse_dir(path: Path) -> bool:
    """True for symlinks / Windows directory junctions (Py3.10-safe)."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            return bool(is_junction())
        except OSError:
            return False
    if sys.platform == "win32" and path.is_dir():
        try:
            import ctypes

            GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
            GetFileAttributesW.argtypes = (ctypes.c_wchar_p,)
            GetFileAttributesW.restype = ctypes.c_uint32
            attrs = GetFileAttributesW(str(path))
            FILE_ATTRIBUTE_REPARSE_POINT = 0x400
            INVALID = 0xFFFFFFFF
            return attrs != INVALID and bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
        except Exception:
            return False
    return False


def cleanup_patch_artifacts(
    work: Path,
    *,
    out_cia: Path,
    packed_img: Path | None = None,
) -> None:
    """Remove patch scratch after a successful CIA write; keep the finished CIA."""
    work = work.resolve()
    out_cia = out_cia.resolve()
    keep: set[Path] = {out_cia}
    if packed_img is not None:
        try:
            keep.add(packed_img.resolve())
        except OSError:
            pass

    def _safe_rm_tree(path: Path) -> None:
        if not path.exists():
            return
        try:
            if path.resolve() == out_cia.parent.resolve() and path.name == "out":
                print(f"[cleanup] refusing to delete entire out/: {path}")
                return
        except OSError:
            pass
        # Drop junctions/symlinks first so we do not recurse into external RomFS trees.
        romfs = path / "romfs"
        if romfs.exists():
            try:
                if _is_reparse_dir(romfs):
                    # Junction/symlink: unlink/rmdir removes the link, not the target.
                    try:
                        romfs.unlink()
                    except OSError:
                        romfs.rmdir()
            except OSError:
                pass
        print(f"[cleanup] removing {path} ...")
        shutil.rmtree(path, ignore_errors=True)

    if not work.is_dir():
        return
    try:
        if out_cia == work or out_cia.parent == work:
            # CIA lives inside work — only purge sibling scratch, not the CIA.
            for child in list(work.iterdir()):
                if child.resolve() in keep:
                    continue
                if child.is_dir():
                    _safe_rm_tree(child)
                else:
                    try:
                        child.unlink()
                    except OSError as exc:
                        print(f"[cleanup] warning: {child.name}: {exc}")
        else:
            _safe_rm_tree(work)
    except OSError as exc:
        print(f"[cleanup] warning: work dir: {exc}")


# Dirs under out/ that survive post-patch cleanup (not patch scratch).
_OUT_KEEP_DIRS = frozenset(
    {
        "luma",  # LayeredFS drop
        "azahar_instances",  # a/b test workflow (ab_test/)
    }
)


def cleanup_out_dir(*, out_cia: Path) -> None:
    """Wipe EngPatcher out/ except finished CIA(s), luma/, and a/b instances."""
    out_root = (ROOT / "out").resolve()
    if not out_root.is_dir():
        return

    keep: set[Path] = set()
    try:
        keep.add(out_cia.resolve())
    except OSError:
        pass
    for cia in out_root.glob("*.cia"):
        try:
            keep.add(cia.resolve())
        except OSError:
            pass
    for name in _OUT_KEEP_DIRS:
        p = out_root / name
        if p.exists():
            try:
                keep.add(p.resolve())
            except OSError:
                pass

    removed = 0
    for child in list(out_root.iterdir()):
        try:
            resolved = child.resolve()
        except OSError:
            continue
        if resolved in keep or child.name in _OUT_KEEP_DIRS:
            continue
        if child.is_file() and child.suffix.lower() == ".cia":
            continue
        try:
            if child.is_dir():
                print(f"[cleanup] removing out/{child.name}/")
                shutil.rmtree(child, ignore_errors=True)
            else:
                print(f"[cleanup] removing out/{child.name}")
                try:
                    child.unlink()
                except FileNotFoundError:
                    pass
            removed += 1
        except OSError as exc:
            print(f"[cleanup] warning: {child.name}: {exc}")
    if removed:
        print(
            f"[cleanup] out/ kept: *.cia, luma/, azahar_instances/ "
            f"({removed} other item(s) removed)"
        )
    else:
        print("[cleanup] out/ already clean (CIA + luma + azahar_instances only)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Patch New Love Plus+ from a decrypted .cia or .3ds/.cci and rebuild "
            "a decrypted English CIA. Decrypt the dump yourself first."
        ),
    )
    p.add_argument(
        "--cia",
        required=True,
        help="Path to decrypted input .cia / .3ds / .cci",
    )
    p.add_argument(
        "--out",
        default=str(ROOT / "out" / "NewLovePlusPlus-EN.cia"),
        help="Output patched CIA path",
    )
    p.add_argument(
        "--dbin",
        default=str(DEFAULT_DBIN),
        help="Folder with NLP_01/NLP_02/script *.dbin2 (default: rebuild_dbin2/)",
    )
    p.add_argument(
        "--work",
        default=str(ROOT / "out" / "cia_work"),
        help="Scratch directory",
    )
    p.add_argument("--cxi", help="Optional pre-extracted main content/CXI")
    p.add_argument("--manual", help="Optional content.0001 manual CFA")
    p.add_argument(
        "--romfs",
        help="Optional already-extracted RomFS directory to copy from",
    )
    p.add_argument(
        "--in-place-romfs",
        action="store_true",
        help="Inject into --romfs directly (mutates that tree)",
    )
    p.add_argument(
        "--link-romfs",
        action="store_true",
        help="Junction work/romfs to --romfs instead of copying (mutates linked tree)",
    )
    p.add_argument(
        "--assume-decrypted",
        action="store_true",
        help="Skip encryption check (only if you are sure the dump is decrypted)",
    )
    p.add_argument(
        "--layeredfs-out",
        default=None,
        help="Also write a Luma/Azahar LayeredFS overlay here (off by default)",
    )
    p.add_argument(
        "--layeredfs-only",
        action="store_true",
        help="Only write LayeredFS overlay (skip CIA rebuild)",
    )
    p.add_argument(
        "--keep-work",
        action="store_true",
        help="Keep out/ scratch after a successful build "
        "(default: leave only *.cia, out/luma/, out/azahar_instances/)",
    )
    p.add_argument(
        "--with-images",
        action="store_true",
        default=True,
        help="Inject release/bake_img.bin when present, else pack cache/new_img.bin (default: on)",
    )
    p.add_argument(
        "--no-images",
        action="store_true",
        help="Skip UI packing / img.bin inject (scripts-only CIA)",
    )
    p.add_argument(
        "--images",
        default=str(DEFAULT_IMAGES),
        help="UI PNG root (default: assets/images) — drop your translated PNGs here",
    )
    p.add_argument(
        "--img-bin",
        default=str(DEFAULT_IMG_BIN),
        help="Vanilla source romfs/img.bin to pack from (default: sibling extracted/)",
    )
    p.add_argument(
        "--packed-img",
        default=str(DEFAULT_PACKED_IMG),
        help="Packed img path (default: cache/new_img.bin; bake preferred when present)",
    )
    p.add_argument(
        "--reuse-packed-img",
        action="store_true",
        help="Reuse --packed-img if present (default behavior when the file exists)",
    )
    p.add_argument(
        "--repack-images",
        action="store_true",
        help="Force rebuild cache/new_img.bin from assets/images (does not refresh gold bake)",
    )
    p.add_argument(
        "--image-workers",
        type=int,
        default=None,
        help="Parallel PNG→BCLIM workers for UI packing (default: CPU count, max 32)",
    )
    p.add_argument(
        "--image-fine-tune",
        action="store_true",
        help="Opt-in per-byte zopfli fine-tune during UI pack (very slow; off by default)",
    )
    p.add_argument(
        "--expect-sha1",
        default=None,
        help=(
            "Require this exact dump SHA-1. "
            "Default: accept any hash in ALLOWED_DUMP_SHA1 "
            f"(primary: {EXPECTED_CIA_SHA1})."
        ),
    )
    p.add_argument(
        "--skip-hash",
        action="store_true",
        help="Skip the input dump SHA-1 check (not recommended)",
    )
    p.add_argument(
        "--skip-name-patches",
        action="store_true",
        help="Skip English heroine-name patches (▲高嶺＊＊▲ → Takane, resident/img tables)",
    )
    p.add_argument(
        "--name-img",
        action="store_true",
        help="Include img.bin in LayeredFS and patch its name table (even without --with-images)",
    )
    p.add_argument(
        "--patch-code",
        action="store_true",
        help="Apply single-pane English name-draw patch to ExeFS code.bin (see src/patch_code.py)",
    )
    p.add_argument(
        "--inject-code",
        help="Replace ExeFS .code with this binary (decompressed ~8.1MB Azahar/LayeredFS "
        "code.bin is BLZ-compressed to the stock slot; already-compressed also OK)",
    )
    p.add_argument(
        "--romfs-overlay",
        default=None,
        help="RomFS overlay dir (default: release/romfs_overlay if present; "
        "e.g. SystemData/TextResource TRBs)",
    )
    p.add_argument(
        "--code-bin",
        default=str(DEFAULT_CODE_BIN),
        help="Vanilla code.bin for LayeredFS --patch-code (default: sibling extracted/exefs/code.bin)",
    )
    p.add_argument(
        "--skip-spotpass",
        action="store_true",
        help="Skip building SpotPass boss info.dat into out/spotpass_*/",
    )
    p.add_argument(
        "--spotpass-mode",
        choices=("real3ds", "azahar", "azahar_exact"),
        default="real3ds",
        help="SpotPass inject mode (default: real3ds -> out/spotpass_real3ds/)",
    )
    p.add_argument(
        "--spotpass-install-azahar",
        action="store_true",
        help="Also sync SpotPass info.dat into Azahar AppData sdmc extdata 00000321/boss/",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return cmd_patch(args)
    except PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
