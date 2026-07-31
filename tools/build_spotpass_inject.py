#!/usr/bin/env python3
"""Build SpotPass boss extdata injects for NLPP (00040000000F4E00).

Default mode is ``real3ds`` (exact BossHeader + 0x914 payload → out/spotpass_real3ds/).
Also callable from ``src/patch_cia.py`` after a successful patch.

Modes:
  real3ds       Exact size for CFW 3DS / FBI Ext Save Data (default)
  azahar        Pad to 0x7D004 for stock Azahar ReadNsData HLE
  azahar_exact  Exact size for Azahar with short-read HLE fix

Source assets live in tools/spotpass/.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path
from typing import Literal

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SPOTPASS_DIR = Path(__file__).resolve().parent / "spotpass"
OUT_ROOT = ROOT / "out"

PROGRAM_ID = 0x00040000000F4E00
EXTDATA_ID = 0x321
HLE_PAD_SIZE = 0x7D004  # NLPP ReadNsData buffer capacity
BOSS_HEADER_LEN = 0x34

Mode = Literal["real3ds", "azahar", "azahar_exact"]

AZAHAR_BOSS = Path.home() / (
    "AppData/Roaming/Azahar/sdmc/Nintendo 3DS/"
    "00000000000000000000000000000000/"
    "00000000000000000000000000000000/"
    f"extdata/00000000/{EXTDATA_ID:08x}/boss"
)

REAL3DS_README = """New Love Plus+ SpotPass inject (real 3DS)

Title: 00040000000F4E00
Extdata: 00000321  (boss/)
File: info.dat   (BossHeader 0x34 + payload 0x914, exact — not Azahar-padded)

Install (Luma CFW + FBI):
  1. Run the game once so extdata 00000321 exists.
  2. Enable SpotPass in-game network settings if available.
  3. Copy this folder's boss/info.dat to the SD (any temp folder is fine).
  4. FBI → Ext Save Data → New Love Plus+ → SpotPass/boss → Paste info.dat.
  5. Fully close the game, then cold-boot.

StreetPass "Communication" (Girlfriend Comm / Business Card / Wireless Battle)
is unrelated — SpotPass is checked at boot.

Do not use out/spotpass_azahar/ on hardware.
"""


def _load_sources() -> tuple[bytes, bytes]:
    info_path = SPOTPASS_DIR / "info.dat"
    dec_path = SPOTPASS_DIR / "info.dat.boss.decrypted"
    if not info_path.is_file() or not dec_path.is_file():
        raise FileNotFoundError(
            f"Missing SpotPass sources under {SPOTPASS_DIR}\n"
            "Expected info.dat and info.dat.boss.decrypted"
        )
    return info_path.read_bytes(), dec_path.read_bytes()


def parse_payload_header(decrypted_boss: bytes, info: bytes) -> dict:
    pid = PROGRAM_ID.to_bytes(8, "big")
    off = decrypted_boss.find(pid)
    if off < 0:
        raise ValueError("program ID not found in decrypted boss file")
    program_id, unk, datatype, size, nsid, ver = struct.unpack_from(">QIIIII", decrypted_boss, off)
    if program_id != PROGRAM_ID or size != len(info) or nsid != 1:
        raise ValueError(
            f"unexpected header @ {off:#x}: pid={program_id:#x} size={size} "
            f"nsid={nsid:#x} info_len={len(info)}"
        )
    return {
        "offset": off,
        "program_id": program_id,
        "unk": unk,
        "datatype": datatype,
        "payload_size": size,
        "ns_data_id": nsid,
        "version": ver,
    }


def build_boss_header(meta: dict, payload_size: int, download_date: int = 0) -> bytes:
    """Citra/Azahar + 3dbrew extdata layout: 0x18 prefix + 0x1C payload content header."""
    hdr = bytearray(BOSS_HEADER_LEN)
    hdr[0] = 0x18
    struct.pack_into(">I", hdr, 0x0C, 1)
    struct.pack_into(">I", hdr, 0x10, download_date & 0xFFFFFFFF)
    struct.pack_into(">Q", hdr, 0x18, meta["program_id"])
    struct.pack_into(">I", hdr, 0x24, meta["datatype"])
    struct.pack_into(">I", hdr, 0x28, payload_size)
    struct.pack_into(">I", hdr, 0x2C, meta["ns_data_id"])
    struct.pack_into(">I", hdr, 0x30, meta["version"])
    return bytes(hdr)


def build_blob(meta: dict, info: bytes, *, pad_hle: bool) -> bytes:
    payload_size = HLE_PAD_SIZE if pad_hle else len(info)
    payload = info if not pad_hle else info + b"\x00" * (HLE_PAD_SIZE - len(info))
    return build_boss_header(meta, payload_size) + payload


def write_tree(out_dir: Path, blob: bytes, *, include_readme: bool) -> Path:
    boss_dir = out_dir / f"{EXTDATA_ID:08x}" / "boss"
    boss_dir.mkdir(parents=True, exist_ok=True)
    dest = boss_dir / "info.dat"
    dest.write_bytes(blob)
    (out_dir / "info.dat").write_bytes(blob)
    if include_readme:
        (out_dir / "README.txt").write_text(REAL3DS_README, encoding="utf-8")
    return dest


def install_azahar(blob: bytes) -> Path:
    AZAHAR_BOSS.mkdir(parents=True, exist_ok=True)
    (AZAHAR_BOSS.parent / "user").mkdir(parents=True, exist_ok=True)
    meta_path = AZAHAR_BOSS.parent / "metadata"
    if not meta_path.exists():
        meta_path.write_bytes(b"\x00" * 0x20)
    dest = AZAHAR_BOSS / "info.dat"
    dest.write_bytes(blob)
    return dest


def build_inject(
    mode: Mode = "real3ds",
    *,
    out_dir: Path | None = None,
    install_azahar_sdmc: bool | None = None,
    quiet: bool = False,
) -> Path:
    """Build SpotPass inject. Returns path to flat ``info.dat`` under the out dir.

    Default ``mode='real3ds'``. Azahar modes sync live SDMC unless
    ``install_azahar_sdmc=False``; real3ds only syncs if ``install_azahar_sdmc=True``.
    """
    if mode not in ("real3ds", "azahar", "azahar_exact"):
        raise ValueError(f"unknown SpotPass mode: {mode!r}")

    info, decrypted = _load_sources()
    meta = parse_payload_header(decrypted, info)

    pad = mode == "azahar"
    label = {
        "real3ds": "spotpass_real3ds",
        "azahar": "spotpass_azahar",
        "azahar_exact": "spotpass_azahar_exact",
    }[mode]
    readme = mode == "real3ds"
    if install_azahar_sdmc is None:
        do_azahar = mode != "real3ds"
    else:
        do_azahar = install_azahar_sdmc

    blob = build_blob(meta, info, pad_hle=pad)
    target = out_dir if out_dir is not None else OUT_ROOT / label
    dest = write_tree(target, blob, include_readme=readme)
    flat = target / "info.dat"

    if not quiet:
        print(f"[spotpass] mode={mode} size={len(blob)} → {flat}")
        if mode == "real3ds":
            print(
                "[spotpass] FBI: Ext Save Data → New Love Plus+ → SpotPass/boss → paste info.dat"
            )
        elif pad:
            print("[spotpass] padded for stock Azahar HLE (not for hardware)")

    if do_azahar:
        az = install_azahar(blob)
        if not quiet:
            print(f"[spotpass] Azahar SDMC: {az}")

    return flat


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = ap.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--real3ds",
        action="store_true",
        help="Exact-size inject for CFW 3DS (default) → out/spotpass_real3ds/",
    )
    mode.add_argument(
        "--azahar",
        action="store_true",
        help="HLE-padded inject for stock Azahar → out/spotpass_azahar/",
    )
    mode.add_argument(
        "--azahar-exact",
        action="store_true",
        help="Exact-size inject for Azahar with short-read fix → out/spotpass_azahar_exact/",
    )
    ap.add_argument(
        "--install-azahar",
        action="store_true",
        help="Also write into Azahar AppData sdmc extdata 00000321/boss/",
    )
    ap.add_argument(
        "--no-install-azahar",
        action="store_true",
        help="Skip live Azahar SDMC sync (azahar modes sync by default)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Override output directory (default: out/spotpass_<mode>/)",
    )
    args = ap.parse_args(argv)

    if args.azahar:
        selected: Mode = "azahar"
    elif args.azahar_exact:
        selected = "azahar_exact"
    else:
        selected = "real3ds"  # default, including bare --real3ds

    if args.no_install_azahar:
        install: bool | None = False
    elif args.install_azahar:
        install = True
    else:
        install = None

    try:
        build_inject(selected, out_dir=args.out, install_azahar_sdmc=install)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
