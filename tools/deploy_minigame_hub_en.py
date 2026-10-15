#!/usr/bin/env python3
"""EN in-room Mini-game hub — ETC1A4 game_text_* @ Myroom **5380** + header **5575**.

The girl's-room Mini-game menu shows ミニゲーム / ぱずるだま / ツインビー+ /
イーアルカンフー+. Zhoumaru painted EN masters in ``Myroom.check`` /
``MyroomHeader.check``, and ``pack_images`` can match them, but shared-ARC
last-writers rebuild those packages without these stems
(``deploy_schedule_header_en.py`` from vanilla on **5575**; other **5380**
deploys never re-apply Mini-game). Gold bake kept JP.

Zhoumaru:
  ``MyroomHeader.check/timg/game_text_title_RGBA4.png`` → Mini-Game
  ``Myroom.check/timg/game_text_twinbe_RGBA4.png`` → TwinBee+
  ``Myroom.check/timg/game_text_kanfu_RGBA4.png`` → Yie Ar Kung-Fu+

``game_text_puzzle`` Zhoumaru is mis-painted ``Subarudama`` (すばる≠ぱずる) —
re-render ``Puzzle-dama`` to match TRB.

Patch *live* packages so Schedule / Options / Map / WEB / My Data EN stay.
Bake last-writer after ``deploy_web_hub_en.py``.

  python tools/deploy_minigame_hub_en.py
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

from bclimutil import parse_bclim, png_to_bclim_etc1a4_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_exact_zopfli, try_fast_exact_slot  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import (  # noqa: E402
    AZAHAR_INSTANCES,
    chrome_font,
    find_ui_png,
    maybe_backup_img,
    iter_deploy_targets,
    render_header_aa,
    resolve_img_paths,
)

MOD_IMG, _VANILLA = resolve_img_paths()

OUT = ROOT / "out" / "minigame_hub_en"

# Zhoumaru dump says Subarudama — wrong for ぱずるだま / Puzzle-dama.
SKIP_UI_PNG = frozenset({"game_text_puzzle_RGBA4"})

# Match TwinBee+ / Yie Ar Kung-Fu+ Zhoumaru rows (ink 47, ~12px cores).
GAME_TEXT_INK = (47, 47, 47)
GAME_TEXT_CORE_PX = 17

# (pkg, asset folder, path, EN fallback)
JOBS: list[tuple[int, str, str, str]] = [
    (5575, "MyroomHeader.check", "timg/game_text_title_RGBA4.bclim", "Mini-Game"),
    (5380, "Myroom.check", "timg/game_text_puzzle_RGBA4.bclim", "Puzzle-dama"),
    (5380, "Myroom.check", "timg/game_text_twinbe_RGBA4.bclim", "TwinBee+"),
    (5380, "Myroom.check", "timg/game_text_kanfu_RGBA4.bclim", "Yie Ar Kung-Fu+"),
]


def render_game_text_row(w: int, h: int, text: str) -> Image.Image:
    """Darker, chunkier row label matching Zhoumaru TwinBee+/Kung-Fu+ pills.

    ``render_header_aa`` uses HEADER_INK (68) and a 15px cap — too light/small
    next to the Mini-game masters. Paint Heisei at 2×, hard-threshold, nearest
    down so cores sit near 12px like ``game_text_twinbe``.
    """
    import numpy as np
    from PIL import ImageDraw

    top = min(GAME_TEXT_CORE_PX, h + 2)
    for size in range(top, 7, -1):
        scale = 2
        big = Image.new("L", (w * scale, h * scale), 0)
        dr = ImageDraw.Draw(big)
        f = chrome_font(size * scale)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w * scale - 4:
            continue
        x = (w * scale - tw) // 2 - b[0]
        y = (h * scale - th) // 2 - b[1]
        dr.text((x, y), text, font=f, fill=255)
        ba = np.where(np.array(big) >= 140, 255, 0).astype(np.uint8)
        a = np.array(
            Image.fromarray(ba, "L").resize((w, h), Image.Resampling.NEAREST)
        )
        # Light fringe so ETC1A4 matches Zhoumaru mid-alpha buckets.
        soft = np.array(
            Image.fromarray(ba, "L")
            .resize((w, h), Image.Resampling.BILINEAR)
            .point(lambda p: int(p * 0.55) if p < 255 else 255)
        )
        a = np.maximum(a, soft).astype(np.uint8)
        rgb = Image.new("RGB", (w, h), GAME_TEXT_INK)
        return Image.merge("RGBA", (*rgb.split(), Image.fromarray(a, "L")))
    raise RuntimeError(f"cannot fit game-text {text!r} into {w}x{h}")


def _zero_all_darc_pads(data: bytes) -> bytes:
    """Zero every DARC inter-file pad, including prior urandom gap-salt."""
    darc = DarcArchive(data)
    spans = sorted((e.offset, e.offset + e.length) for e in darc.files)
    t = bytearray(data)
    for (_a0, a1), (b0, _b1) in zip(spans, spans[1:]):
        if b0 > a1:
            t[a1:b0] = b"\x00" * (b0 - a1)
    if spans and spans[-1][1] < len(data):
        t[spans[-1][1] :] = b"\x00" * (len(data) - spans[-1][1])
    return bytes(t)


def _compress_slot(patched: bytes, cmp_len: int) -> tuple[bytes, bytes]:
    candidates = [patched]
    zeroed = _zero_all_darc_pads(patched)
    if zeroed != patched:
        candidates.append(zeroed)
    last_err: Exception | None = None
    for i, cand in enumerate(candidates):
        label = "as-patched" if i == 0 else "unsalted pads"
        fast = try_fast_exact_slot(cand, cmp_len)
        if fast is not None:
            print(f"  hit exact-zlib fast-path ({label})", flush=True)
            return fast
        try:
            print(f"  escalating to zopfli ({label})", flush=True)
            return compress_exact_zopfli(cand, cmp_len)
        except RuntimeError as exc:
            last_err = exc
            print(f"  slot miss ({label}): {exc}", flush=True)
    assert last_err is not None
    raise last_err


def _deploy_targets() -> list[Path]:
    targets = list(iter_deploy_targets(MOD_IMG))
    inst_root = AZAHAR_INSTANCES
    seen = {p.resolve() for p in targets}
    for img in inst_root.glob("*/user/load/mods/00040000000F4E00/romfs/img.bin"):
        rp = img.resolve()
        if rp.is_file() and rp not in seen:
            targets.append(rp)
            seen.add(rp)
    return targets


def _rgba_for(folder: str, stem: str, en: str, w: int, h: int) -> tuple[Image.Image, str]:
    if stem in SKIP_UI_PNG:
        return render_game_text_row(w, h, en), f"render_game_text:{en}"
    master = find_ui_png((folder,), stem, (w, h))
    if master is not None:
        return Image.open(master).convert("RGBA"), str(master.relative_to(ROOT))
    return render_header_aa(w, h, en), f"render:{en}"


def _patch_arc(
    arc_bytes: bytes,
    jobs: list[tuple[str, str, str]],
    tmp: Path,
) -> bytes:
    darc = DarcArchive(bytearray(arc_bytes))
    for folder, path, en in jobs:
        entry = darc.find(path) or darc.find(Path(path).name)
        if entry is None:
            raise SystemExit(f"missing {path}")
        orig_b = darc.extract_file(entry)
        _pix, w, h, fmt, _ft = parse_bclim(orig_b)
        if fmt != 0xB:
            raise SystemExit(f"{path} fmt {fmt:#x} not ETC1A4")
        stem = Path(path).stem
        rgba, src = _rgba_for(folder, stem, en, w, h)
        if rgba.size != (w, h):
            rgba = rgba.resize((w, h), Image.Resampling.LANCZOS)
        png = tmp / f"{stem}.png"
        orig = tmp / f"{stem}.bclim"
        rgba.save(png)
        orig.write_bytes(orig_b)
        darc.replace_same_size(entry, png_to_bclim_etc1a4_same_size(png, orig))
        rgba.save(OUT / f"{stem}_en.png")
        print(f"OK {path} <- {src} ({w}x{h})", flush=True)
    return bytes(darc.data)


def _write_slot(src_pkg: Path, pkg: Package, tuned: bytes, slot: bytes) -> Path:
    blob = bytearray(src_pkg.read_bytes())
    entry_off = Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp or slot_len != len(slot) or len(tuned) != dec_len:
        raise SystemExit(
            f"ARC entry mismatch slot={slot_len}/{len(slot)} dec={dec_len}/{len(tuned)}"
        )
    blob[cmp_off : cmp_off + slot_len] = slot
    new_pkg = src_pkg.with_name(f"new_{src_pkg.name}")
    new_pkg.write_bytes(blob)

    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC):
            if b.parsed() != tuned:
                raise SystemExit("ARC mismatch")
        elif a.parsed() != b.parsed():
            raise SystemExit(f"DMST changed {a.fn}")
    print("DMST unchanged OK", flush=True)
    return new_pkg


def _patch_package(
    pkg_id: int,
    jobs: list[tuple[str, str, str]],
    pkg_dir: Path,
    tmp: Path,
) -> None:
    raw = MOD_IMG.read_bytes()
    img = ImgBin(str(MOD_IMG))
    img.parse(False)
    res = img.entries[pkg_id]
    if res is None:
        raise SystemExit(f"pkg {pkg_id} missing")
    src_pkg = pkg_dir / f"{pkg_id:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    arc_elem = next(e for e in pkg.entries if isinstance(e, ARC))
    cmp_len = arc_elem.fw.len()
    print(f"\nlive pkg {pkg_id} {arc_elem.fn} slot={cmp_len}", flush=True)

    live_arc = arc_elem.parsed()
    patched = _patch_arc(live_arc, jobs, tmp)
    tuned, slot = _compress_slot(patched, cmp_len)
    do = zlib.decompressobj()
    got = do.decompress(slot)
    if got != tuned or do.unused_data or not do.eof:
        raise SystemExit(f"pkg {pkg_id} exact zlib verify failed")
    print(f"  ARC exact zlib {len(slot)} unused_data=0", flush=True)
    _write_slot(src_pkg, pkg, tuned, slot)


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")

    bak = maybe_backup_img(MOD_IMG, "minigame_hub")

    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    tmp.mkdir(parents=True, exist_ok=True)

    by_pkg: dict[int, list[tuple[str, str, str]]] = {}
    for pkg_id, folder, path, en in JOBS:
        by_pkg.setdefault(pkg_id, []).append((folder, path, en))

    pkg_ids = list(by_pkg)
    for pkg_id in pkg_ids:
        _patch_package(pkg_id, by_pkg[pkg_id], pkg_dir, tmp)

    try:
        for dest in _deploy_targets():
            splice_packages_into_img(dest, pkg_dir, pkg_ids, dest)
            print("spliced", pkg_ids, "->", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("deployed Mini-game hub EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
