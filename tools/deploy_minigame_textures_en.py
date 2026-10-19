#!/usr/bin/env python3
"""EN mini-game screens — raw ``.l2mgtex`` textures in img.bin pkgs **94–155**.

The mini-games (Puzzle-dama / TwinBee+ / Yie Ar Kung-Fu+) do not use BCLIMs.
Each package holds a ``*.l2rg`` layout and ``NNN.l2mgtex`` textures
(``src/l2mgtex.py``), one zlib element per texture:

  pkg 95  AttentionStart  005  256×64  ETC1A4  A-button line + L/R quit line
                          006  512×32  ETC1A4  3DS本体をよこに持ちかえてください
                          007  256×64  ETC1A4  A-button line only
                          008  512×256 ETC1A4  full-screen composite
  pkg 94  AttentionEnd    005  256×32  ETC1A4  A-button line under 楽しかったよ…
  pkg 117 InstCard        000  512×256 RGBA8   Puzzle-dama how-to-play card
                                               (controls + secret balls)
  pkg 125 Title           006–011      RGBA4444 Puzzle-dama logo pieces: bubbles
                                               M / O / E, PUZZLE-DAMA, MORE heart,
                                               BATTLE burst
  pkg 120 Select          137–147 / 149–159  ETC1A4 character-select name
                                               plates, blue (PLAYER) / red (COM)
                          070 / 071    ETC1A4 BEGINNER / ADVANCED COURSE plates
                          015          ETC1A4 Choose an attack pattern! prompt
                          122 / 123    ETC1A4 footer Ⓐ DECIDE / ✚ SELECT

Masters in ``assets/images/minigame/`` were cut from EN mockups
(``tools/cut_minigame_*.py``). Each texture is spliced into the vanilla
package at the same ``cmp_len``; a master that does not fit is an error.
Moving other streams to make room hung the game (``docs/technical.md``).
No other deploy writes these packages.

  python tools/deploy_minigame_textures_en.py
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

import l2mgtex  # noqa: E402
from img import FileWindow, Image as ImgBin, Package  # noqa: E402
from exact_zlib import pad_closed_zlib_stream  # noqa: E402
from nlpp_paths import find_vanilla_img  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    AZAHAR_INSTANCES,
    iter_deploy_targets,
    maybe_backup_img,
    resolve_img_paths,
)

MOD_IMG, _FALLBACK_VANILLA = resolve_img_paths()
MASTERS = ROOT / "assets" / "images" / "minigame"
OUT = ROOT / "out" / "minigame_textures_en"

# pkg -> {element name: master PNG}
JOBS: dict[int, dict[str, str]] = {
    95: {
        "005.l2mgtex": "AttentionStart_005.png",
        "006.l2mgtex": "AttentionStart_006.png",
        "007.l2mgtex": "AttentionStart_007.png",
        "008.l2mgtex": "AttentionStart_008.png",
    },
    94: {
        "005.l2mgtex": "AttentionEnd_005.png",
    },
    117: {
        "000.l2mgtex": "InstCard_Puzzle.png",
    },
    125: {f"{n}.l2mgtex": f"PuzzleTitle_{n}.png" for n in ("006", "007", "008", "009", "010", "011")},
    120: {f"{n:03d}.l2mgtex": f"PuzzleSelect_{n:03d}.png" for n in (15, 70, 71, 122, 123, *range(137, 148), *range(149, 160))},
}


def _vanilla_src() -> Path:
    """Vanilla img for the package blobs, so re-runs start from JP again."""
    vanilla = find_vanilla_img()
    if vanilla is not None:
        return vanilla.resolve()
    print("[minigame] no vanilla img.bin; using primary (these pkgs are only written here)")
    return _FALLBACK_VANILLA.resolve()


def _deploy_targets() -> list[Path]:
    targets = list(iter_deploy_targets(MOD_IMG))
    seen = {p.resolve() for p in targets}
    for img in AZAHAR_INSTANCES.glob("*/user/load/mods/00040000000F4E00/romfs/img.bin"):
        rp = img.resolve()
        if rp.is_file() and rp not in seen:
            targets.append(rp)
            seen.add(rp)
    return targets


def try_compress_to_slot(data: bytes, slot_len: int) -> bytes | None:
    """zlib stream of exactly ``slot_len`` bytes, padded with empty deflate blocks.

    The texture bytes are never touched (no gap salt): zero runs here are
    transparent ETC1A4 blocks, not DARC padding. None when it does not fit.
    """
    import zopfli.zlib as zopfli_zlib

    for label, make in (
        ("zlib-9", lambda: zlib.compress(data, 9)),
        ("zopfli", lambda: zopfli_zlib.compress(data)),
    ):
        stream = make()
        if len(stream) > slot_len:
            continue
        out = pad_closed_zlib_stream(stream, slot_len, expected=data)
        if out is not None:
            print(f"  {label} {len(stream)} -> padded to {slot_len}", flush=True)
            return out
    return None


def compress_to_slot(data: bytes, slot_len: int) -> bytes:
    out = try_compress_to_slot(data, slot_len)
    if out is None:
        raise SystemExit(f"texture does not fit its {slot_len}-byte zlib slot")
    return out


def _entry_offsets(blob: bytes) -> dict[int, int]:
    """Entry-table offset keyed by each element's compressed data offset."""
    cnt = Package.parse_header(blob[: Package.ENTRY_SIZE])[1]
    out: dict[int, int] = {}
    for i in range(cnt):
        off = Package.ENTRY_SIZE * (1 + i)
        cmp_off = Package.parse_entry(blob[off : off + Package.ENTRY_SIZE])[6]
        out[cmp_off] = off
    return out


def patch_package(pkg_raw: bytes, jobs: dict[str, str], masters: Path = MASTERS) -> bytes:
    """Return ``pkg_raw`` with each job's l2mgtex replaced at the same cmp_len."""
    tmp = OUT / "_pkg"
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "src.pkg"
    src.write_bytes(pkg_raw)
    pkg = Package(FileWindow(str(src)), 0)
    pkg.parse(False)
    by_cmp_off = _entry_offsets(pkg_raw)
    blob = bytearray(pkg_raw)
    done = set()
    overflow = []
    for elem in pkg.entries:
        if elem.fn not in jobs:
            continue
        entry_off = by_cmp_off.get(elem.fw.base_offset)
        if entry_off is None:
            raise SystemExit(f"{elem.fn}: entry for cmp_off {elem.fw.base_offset:#x} not found")
        _typ, dec_len, _do, _fl, is_cmp, cmp_len, cmp_off = Package.parse_entry(
            bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
        )
        if not is_cmp:
            raise SystemExit(f"{elem.fn} is not zlib-compressed")
        orig = elem.parsed()
        im = Image.open(masters / jobs[elem.fn]).convert("RGBA")
        new = l2mgtex.encode_like(orig, im)
        if len(new) != dec_len:
            raise SystemExit(f"{elem.fn}: {len(new)} bytes != dec_len {dec_len}")
        slot = try_compress_to_slot(new, cmp_len)
        if slot is None:
            overflow.append(elem.fn)
        else:
            blob[cmp_off : cmp_off + cmp_len] = slot
            print(f"OK {elem.fn} <- {jobs[elem.fn]} (slot {cmp_len})", flush=True)
        done.add(elem.fn)
    missing = set(jobs) - done
    if missing:
        raise SystemExit(f"missing elements: {sorted(missing)}")
    if overflow:
        # Moving streams to make room (same package length, offsets updated)
        # hung the game after the Puzzle-dama title, so masters must fit.
        raise SystemExit(f"{overflow} do not fit their zlib slots; shrink the masters")

    # Every other element must decompress unchanged.
    chk = tmp / "new.pkg"
    chk.write_bytes(blob)
    pkg2 = Package(FileWindow(str(chk)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if a.fn in jobs:
            d = zlib.decompressobj()
            d.decompress(b.unparsed())
            if d.unused_data or not d.eof:
                raise SystemExit(f"{a.fn}: zlib slot not exact")
        elif a.parsed() != b.parsed():
            raise SystemExit(f"{a.fn} changed")
    return bytes(blob)


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    bak = maybe_backup_img(MOD_IMG, "minigame_textures")
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    src_img = _vanilla_src()
    raw = src_img.read_bytes()
    img = ImgBin(str(src_img))
    img.parse(False)
    for pkg_id, jobs in JOBS.items():
        res = img.entries[pkg_id]
        if res is None:
            raise SystemExit(f"pkg {pkg_id} missing")
        pkg_raw = raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
        print(f"\npkg {pkg_id} from {src_img}", flush=True)
        (pkg_dir / f"new_{pkg_id:04d}").write_bytes(patch_package(pkg_raw, jobs))

    try:
        for dest in _deploy_targets():
            splice_packages_into_img(dest, pkg_dir, list(JOBS), dest)
            print("spliced", list(JOBS), "->", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("deployed mini-game textures EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
