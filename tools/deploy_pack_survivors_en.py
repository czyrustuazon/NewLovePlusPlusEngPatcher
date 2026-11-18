#!/usr/bin/env python3
"""Re-apply PNG masters that a later step left Japanese (runs last in the bake).

``pack_images`` writes every ``assets/images`` master into its ARC first, but
several deploys then splice their whole package back from *vanilla*
(``deploy_gallery_common_en`` 5153, ``deploy_multiwin_headers_en`` and friends
on NCommon 5237, ``deploy_profile_en`` 5252, ``deploy_mail_*`` 5207).
NCommonMSel 5240-5245, which the pack slot-skips, get their rows from
deploy_msel_menus_en / deploy_msel_options_en instead (masters do not fit). The masters below were reviewed against vanilla (2026-11-19): each
is an English version of a Japanese texture that still shipped Japanese
(ロック/解除, 拡大/縮小, はい, 登録中, クリア, 氏名/名前/あだな, プロフィール ...).

For each listed master whose BCLIM is still byte-identical to vanilla in the
bake, this encodes it at the vanilla size/format and injects it into the ARC as
the deploys left it, then recompresses the ARC into its own zlib slot. A
texture a deploy already replaced is left alone, so this never undoes a
deploy. An ARC that does not fit its slot is an error.

  python tools/deploy_pack_survivors_en.py
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import png_to_bclim_same_size
from darcutil import DarcArchive
from deploy_common import iter_deploy_targets, maybe_backup_img, resolve_img_paths
from exact_zlib import compress_to_exact_slot
from image_map import resolve_folder
from img import FileWindow, Package
from img import Image as ImgBin

from pack_images import PackError, splice_packages_into_img

MOD_IMG, _VANILLA = resolve_img_paths()
ASSETS = ROOT / "assets" / "images"
OUT = ROOT / "out" / "pack_survivors_en"

SURVIVORS: dict[str, list[str]] = {
    "Gallery_Common.check": [
        "Com_btn_rk01_b", "Com_btn_rk01_bON", "Com_btn_rk02_b", "Com_btn_rk02_bON",
        "Gal_Kakudai01", "Gal_Kakudai03", "Gallery_txt07",
    ],
    "Mail.check": ["C_Com_icon_Repry2"],
    "NCommon.check": [
        "Com_btn_Check01_a", "Com_btn_Check01_b", "Com_btn_Check03_b", "Com_PassMarker02",
        "Com_M_Sel_Plate_Icon00_00_00", "Com_M_Sel_Plate_Icon02_01_04",
        "Com_M_Sel_Plate_Icon03_04_00", "Com_M_Sel_Plate_Icon03_05_00",
        "Com_MultiWin_W01_Text01",
        *[f"Com_MultiWin_W01_Text03_{n:02d}_00" for n in (0, 1, 2, 3, 4, 6)],
        *[f"Com_MultiWin_W01_Text05_{n:02d}_00" for n in (0, 2, 3, 4, 5)],
        "Com_MultiWin_W01_Text06_00_00",
    ],
    # Format-3 labels are LA8 (white text, soft shadow); bclimutil encodes fmt 3 as LA8.
    "Profile.check": [
        "Profile_Btn_Clear_Off", "Profile_Btn_Clear_On",
        *[f"Profile_Btn_Com01_Text{n:02d}" for n in range(1, 8)],
        "Profile_Btn_Com02_Text09", "Profile_Btn_Com02_Text10", "Profile_Btn_Com02_Text11",
        "Profile_Btn_Com03_Text01", "Profile_Plate_Text01",
    ],
}


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


def _arc(pkg_path: Path, arc_name: str):
    pkg = Package(FileWindow(str(pkg_path)), 0)
    pkg.parse(False)
    for elem in pkg.entries:
        if elem.fn == arc_name:
            return elem
    raise SystemExit(f"{pkg_path.name}: no {arc_name}")


def inject(van_arc: bytes, cur_arc: bytes, masters: list[Path], work: Path) -> tuple[bytes, list[str]]:
    """``cur_arc`` with each master whose texture is still vanilla replaced.
    Returns ``(arc, names applied)``."""
    van, cur = DarcArchive(van_arc), DarcArchive(bytearray(cur_arc))
    applied = []
    work.mkdir(parents=True, exist_ok=True)
    for png in masters:
        rel = f"timg/{png.stem}.bclim"
        v_entry, c_entry = van.find(rel), cur.find(rel)
        if v_entry is None or c_entry is None:
            raise SystemExit(f"{png.stem}: no {rel} in the ARC")
        vanilla_bclim = van.extract_file(v_entry)
        if cur.extract_file(c_entry) != vanilla_bclim:
            print(f"  {png.stem}: already replaced by a deploy, kept", flush=True)
            continue
        orig = work / f"{png.stem}.bclim"
        orig.write_bytes(vanilla_bclim)
        cur.replace_same_size(c_entry, png_to_bclim_same_size(png, orig))
        applied.append(png.stem)
    return bytes(cur.data), applied


def patch_package(pkg: int, jobs: list[tuple[str, str, list[Path]]], pkg_dir: Path) -> bool:
    """Write ``pkg_dir/new_<pkg>`` from the bake's package; False when nothing applied."""
    van_path, cur_path = pkg_dir / f"vanilla_{pkg:04d}", pkg_dir / f"{pkg:04d}"
    van_path.write_bytes(_pkg_bytes(_VANILLA, pkg))
    cur_path.write_bytes(_pkg_bytes(MOD_IMG, pkg))
    blob = bytearray(cur_path.read_bytes())
    changed = False
    for folder, arc_name, masters in jobs:
        v_elem, c_elem = _arc(van_path, arc_name), _arc(cur_path, arc_name)
        new_arc, applied = inject(v_elem.read(), c_elem.read(), masters, pkg_dir / f"_{pkg}_{folder}")
        if not applied:
            continue
        slot_len, off = c_elem.fw.len(), c_elem.fw.base_offset
        try:
            slot = compress_to_exact_slot(new_arc, slot_len)
        except Exception as exc:
            raise SystemExit(f"pkg {pkg} {arc_name}: {len(applied)} master(s) do not fit its {slot_len}-byte slot ({exc})") from exc
        if len(zlib.decompress(slot)) != len(new_arc):
            raise SystemExit(f"pkg {pkg} {arc_name}: slot stream has the wrong length")
        blob[off : off + slot_len] = slot
        changed = True
        print(f"OK pkg {pkg} {arc_name} <- {folder}: {', '.join(applied)}", flush=True)
    if changed:
        (pkg_dir / f"new_{pkg:04d}").write_bytes(blob)
    return changed


def plan(survivors: dict[str, list[str]] | None = None) -> dict[int, list[tuple[str, str, list[Path]]]]:
    """``{pkg: [(folder, arc, master PNGs)]}``; every listed master must exist."""
    out: dict[int, list[tuple[str, str, list[Path]]]] = {}
    for folder, names in (SURVIVORS if survivors is None else survivors).items():
        mapping = resolve_folder(folder)
        if mapping is None:
            raise SystemExit(f"{folder}: not in image_map")
        pkg, arc = mapping
        pngs = [ASSETS / folder / "timg" / f"{n}.png" for n in names]
        missing = [p.name for p in pngs if not p.is_file()]
        if missing:
            raise SystemExit(f"{folder}: missing masters {missing}")
        out.setdefault(pkg, []).append((folder, arc, pngs))
    return out


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing {MOD_IMG}")
    if not _VANILLA.is_file():
        raise SystemExit(f"missing vanilla {_VANILLA}")
    bak = maybe_backup_img(MOD_IMG, "pack_survivors")
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    patched = [pkg for pkg, jobs in sorted(plan().items()) if patch_package(pkg, jobs, pkg_dir)]
    if not patched:
        print("pack survivors: nothing left vanilla", flush=True)
        return 0
    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, patched, dest)
            print("spliced", patched, "->", dest, flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
