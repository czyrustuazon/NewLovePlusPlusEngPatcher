#!/usr/bin/env python3
"""Trip-mode voice-hint bubbles read in romaji (img.bin pkgs 5398 / 5438).

On a trip the mic bubbles (ねえねえ, おはよう, おなかすいたな…) come from
``.tmb`` tables, one per destination and heroine, plus the overnight
name-calling lists (ネネサン, コバヤカワ…):

  pkg 5398  tripmode_keyword_{atami,hakone,nikko}_{ang,kby,tkn}.tmb
  pkg 5438  tripmode_overnight_keyword_{ang,kby,tkn}.tmb

Each table ends in two parallel NUL-terminated lists: Shift-JIS readings the
recognizer listens for, then the UTF-8 bubbles (row i shows row i's reading).
Day-trip tables start with a u32 field count (12) and 12 u32 fields: [4] is
the row count, [10] and [11] the offsets of the reading and bubble lists.
Overnight tables start with a u16 row count, and the bubble list's offset is
the u32 at 12; readings start at 16. The bubble list runs to the end.

As in ``deploy_voice_keywords_en.py`` (Love Plus mode, pkg 4073), the
recognizer only hears Japanese, so each bubble becomes the romaji of its own
row's reading from ``assets/voice_keywords/romaji.json``: what to say. Rows
keep their order and count; the bytes romaji saves become one spaces row
after the last, so every table keeps its vanilla length and each is
recompressed into its own vanilla zlib slot. No other deploy writes these
packages.

  python tools/deploy_trip_keywords_en.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

import deploy_voice_keywords_en as vk
from deploy_common import iter_deploy_targets, maybe_backup_img, resolve_img_paths
from deploy_minigame_textures_en import try_compress_to_slot
from img import FileWindow, Package
from img import Image as ImgBin

from pack_images import PackError, splice_packages_into_img

MOD_IMG, _VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "trip_keywords_en"
DAY_TRIP = [f"tripmode_keyword_{p}_{h}.tmb" for p in ("atami", "hakone", "nikko") for h in ("ang", "kby", "tkn")]
OVERNIGHT = [f"tripmode_overnight_keyword_{h}.tmb" for h in ("ang", "kby", "tkn")]
PKGS = {5398: DAY_TRIP, 5438: OVERNIGHT}


def layout(blob: bytes) -> tuple[int, int, int]:
    """``(rows, readings offset, bubbles offset)`` for either table layout."""
    if struct.unpack_from("<I", blob, 0)[0] == 12:
        fields = struct.unpack_from("<13I", blob, 0)
        return fields[5], fields[11], fields[12]
    return struct.unpack_from("<H", blob, 0)[0], 16, struct.unpack_from("<I", blob, 12)[0]


def split_rows(blob: bytes, name: str) -> tuple[list[str], list[str]]:
    """``(readings, bubbles)``, ``count`` rows each. A deployed table may end
    in one spare filler row (spaces / ``-``) past the counted rows."""
    count, heard_at, shown_at = layout(blob)
    heard = vk._split(blob[heard_at:shown_at], "cp932")
    shown = vk._split(blob[shown_at:], "utf-8")
    if len(shown) == count + 1 and shown[-1].strip(" -") == "":
        shown = shown[:-1]
    if not len(heard) == len(shown) == count:
        raise ValueError(f"{name}: {len(heard)} readings, {len(shown)} bubbles, header says {count}")
    return heard, shown


def build_table(blob: bytes, readings: dict[str, str], name: str) -> bytes:
    """Vanilla table -> same-length table with romaji bubbles."""
    heard, shown = split_rows(blob, name)
    out = []
    for display, kana in zip(shown, heard):
        if display in vk.NO_BUBBLE or not vk._JP.search(display):
            out.append(display.translate(vk._FULLWIDTH))
            continue
        if kana not in readings:
            raise KeyError(f"{name}: no romaji for {kana} ({display})")
        out.append(vk.bubble_text(display, readings[kana]))
    shown_at = layout(blob)[2]
    return blob[:shown_at] + vk._join(out, len(blob) - shown_at, name)


def _pkg_bytes(img_path: Path, pkg: int) -> bytes:
    img = ImgBin(str(img_path))
    try:
        img.parse(False)
        ent = img.entries[pkg]
        if ent is None:
            raise SystemExit(f"pkg {pkg} missing in {img_path}")
        return ent.fw.read()
    finally:
        img.fh.close()


def _entries(pkg_path: Path) -> dict[str, bytes]:
    """TMB entries by name. Texture names repeat (TEXI + TEX), so only TMB
    entries are keyed; the splice walks positions instead."""
    pkg = Package(FileWindow(str(pkg_path)), 0)
    pkg.parse(False)
    return {e.fn: e.read() for e in pkg.entries if e.typ == b"TMB "}


def exact_slot(data: bytes, slot_len: int) -> tuple[bytes, bytes]:
    """``(table, zlib stream of exactly slot_len)``. Romaji tables run a few
    bytes over their slot at zlib -9, so zopfli first (padded with empty
    blocks, table untouched), then the spare-row salting of pkg 4073."""
    slot = try_compress_to_slot(data, slot_len)
    if slot is not None:
        return data, slot
    return vk.exact_slot(data, slot_len)


def splice(pkg_raw: bytes, built: dict[str, bytes], pkg_path: Path) -> bytes:
    """Recompress each built TMB into its own vanilla zlib slot, by entry
    position (``vk.splice_tables`` keys positions by name, which breaks on
    the repeated texture names in pkg 5398). ``built`` gets the tables as
    stored (spare-row filler may change)."""
    pkg = Package(FileWindow(str(pkg_path)), 0)
    pkg.parse(False)
    blob = bytearray(pkg_raw)
    for i, elem in enumerate(pkg.entries):
        if elem.typ != b"TMB " or elem.fn not in built:
            continue
        off = Package.ENTRY_SIZE * (i + 1)
        _typ, dec_len, _do, _fl, is_cmp, cmp_len, cmp_off = Package.parse_entry(
            bytes(blob[off : off + Package.ENTRY_SIZE])
        )
        data = built[elem.fn]
        if not is_cmp or len(data) != dec_len:
            raise SystemExit(f"{elem.fn}: cmp={is_cmp} dec {len(data)}/{dec_len}")
        built[elem.fn], slot = exact_slot(data, cmp_len)
        blob[cmp_off : cmp_off + cmp_len] = slot
        print(f"  {elem.fn}: slot {cmp_len}", flush=True)
    return bytes(blob)


def deploy_pkg(pkg: int, names: list[str], romaji: dict[str, str], pkg_dir: Path) -> None:
    """Write ``pkg_dir/new_<pkg>`` from the vanilla and current packages."""
    vanilla_path = pkg_dir / f"vanilla_{pkg:04d}"
    vanilla_path.write_bytes(_pkg_bytes(_VANILLA, pkg))
    vanilla = _entries(vanilla_path)
    built = {n: build_table(vanilla[n], romaji, n) for n in names}

    src = pkg_dir / f"{pkg:04d}"
    src.write_bytes(_pkg_bytes(MOD_IMG, pkg))
    current = _entries(src)
    if list(current) != list(vanilla):
        raise SystemExit(f"pkg {pkg} entries differ from vanilla")
    for name, data in current.items():
        if name not in built and data != vanilla[name]:
            raise SystemExit(f"pkg {pkg} {name} is not vanilla")

    new_pkg = pkg_dir / f"new_{pkg:04d}"
    new_pkg.write_bytes(splice(src.read_bytes(), built, src))
    for name, data in _entries(new_pkg).items():
        if data != built.get(name, vanilla[name]):
            raise SystemExit(f"round-trip mismatch {name}")


def main() -> None:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    if not _VANILLA.is_file():
        raise SystemExit(f"missing vanilla {_VANILLA}")
    bak = maybe_backup_img(MOD_IMG, "trip_keywords")
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    romaji = vk.load_romaji()["readings"]
    for pkg, names in PKGS.items():
        print(f"pkg {pkg}", flush=True)
        deploy_pkg(pkg, names, romaji, pkg_dir)
    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, list(PKGS), dest)
            print("spliced", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed romaji trip voice-hint bubbles ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)


if __name__ == "__main__":
    main()
