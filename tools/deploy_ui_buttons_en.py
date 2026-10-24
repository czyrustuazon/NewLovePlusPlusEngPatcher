#!/usr/bin/env python3
"""EN UI button PNGs → img.bin packages (exact-zlib splice).

Sources: desktop NLPP_English_UI_Buttons_only (staged under assets/images/*.check/timg):

| Group | Packages / ARCs | Notes |
|-------|-----------------|-------|
| Keyboard labels | **5190** InputCTexture + InputNTexture | same 9 PNGs in both; RGBA4444 |
| SysPopup | **5259** SysPopup.arc | Yes/No/Ok/Cancel/Next/Previous; fmt 8 + Release fmt 3 |
| Myroom Back | **5380** Myroom.arc | common_modoru + C_Com_icon_m{,ON}; ETC1A4 |
| Album | **4149** Album.arc | Delete / Search / Export / popups + every Zhoumaru Album.check master |

Does not touch SysPopup node/file outside the listed button stems, except
``Lyt_C_Com_Win01.bclyt``: its ``Tex_Sentence`` pane is made 1024 tall
(``tall_sentence_pane``). The message box builds its text texture from that
pane's size rounded up to a power of two (``0x0024E7E0``), so vanilla's 256
held about 16 lines; the Main Menu localization credits need more
(``src/patch_title_engpatch_info.py``).
"""
from __future__ import annotations

import shutil
import struct
import sys
import zlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import parse_bclim, png_to_bclim_same_size  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from exact_zlib import compress_exact_zopfli  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from pack_images import PackError, splice_packages_into_img  # noqa: E402

from deploy_common import maybe_backup_img, iter_deploy_targets, resolve_img_paths  # noqa: E402

MOD_IMG, VANILLA = resolve_img_paths()
OUT = ROOT / "out" / "ui_buttons_en"
SRC_DESKTOP = Path.home() / "Desktop" / "NLPP_English_UI_Buttons_only" / "graphics"
ASSETS = ROOT / "assets" / "images"

SENTENCE_LAYOUT = "blyt/Lyt_C_Com_Win01.bclyt"
SENTENCE_PANE = b"Tex_Sentence"
SENTENCE_H_VANILLA = 256.0
SENTENCE_H = 1024.0  # largest 3DS texture side

# stem → asset folder (prefer .check)
GROUPS: list[dict] = [
    {
        "pkg": 5190,
        "arcs": ("InputCTexture.arc", "InputNTexture.arc"),
        "asset_dirs": (
            ASSETS / "InputCTexture.check" / "timg",
            ASSETS / "InputNTexture.check" / "timg",
        ),
        "desktop": SRC_DESKTOP / "package_5190_InputC_and_InputN_shared",
        "stems": [
            "Profile_Btn_Clear_Off",
            "Profile_Btn_Clear_On",
            "Profile_Btn_Com01_Text01",
            "Profile_Btn_Com01_Text02",
            "Profile_Btn_Com01_Text03",
            "Profile_Btn_Com01_Text04",
            "Profile_Btn_Com01_Text05",
            "Profile_Btn_Com01_Text06",
            "Profile_Btn_Com01_Text07",
        ],
        # virgin package — keyboard not previously EN-baked as a set
        "from_live": False,
    },
    {
        "pkg": 5259,
        "arcs": ("SysPopup.arc",),
        "asset_dirs": (ASSETS / "SysPopup.check" / "timg",),
        "desktop": SRC_DESKTOP / "package_5259_SysPopup",
        "stems": [
            "C_Com_Win01_Btn01_Next_Off",
            "C_Com_Win01_Btn01_Next_Press",
            "C_Com_Win01_Btn01_Next_Release",
            "C_Com_Win01_Btn01_Off",
            "C_Com_Win01_Btn01_Ok_Press",
            "C_Com_Win01_Btn01_Ok_Release",
            "C_Com_Win01_Btn02_Cancel_Off",
            "C_Com_Win01_Btn02_Cancel_Press",
            "C_Com_Win01_Btn02_Cancel_Release",
            "C_Com_Win01_Btn02_Next_Off",
            "C_Com_Win01_Btn02_Next_Press",
            "C_Com_Win01_Btn02_Next_Release",
            "C_Com_Win01_Btn02_Ok_Off",
            "C_Com_Win01_Btn02_Ok_Press",
            "C_Com_Win01_Btn02_Ok_Release",
            "C_Com_Win01_Btn02_Previous_Off",
            "C_Com_Win01_Btn02_Previous_Press",
            "C_Com_Win01_Btn02_Previous_Release",
            "C_Com_Win01_Btn03_Cancel_Press",
            "C_Com_Win01_Btn03_Cancel_Release",
            "C_Com_Win01_Btn03_Off",
            "C_Com_Win_Btn_NoR_Off",
            "C_Com_Win_Btn_NoR_Press",
            "C_Com_Win_Btn_NoR_Release",
            "C_Com_Win_Btn_No_Off",
            "C_Com_Win_Btn_No_Press",
            "C_Com_Win_Btn_No_Release",
            "C_Com_Win_Btn_YesL_Off",
            "C_Com_Win_Btn_YesL_Press",
            "C_Com_Win_Btn_YesL_Release",
            "C_Com_Win_Btn_Yes_Off",
            "C_Com_Win_Btn_Yes_Press",
            "C_Com_Win_Btn_Yes_Release",
        ],
        "from_live": False,
        "layouts": {SENTENCE_LAYOUT: "tall_sentence_pane"},
    },
    {
        "pkg": 5380,
        "arcs": ("Myroom.arc",),
        "asset_dirs": (ASSETS / "Myroom.check" / "timg",),
        "desktop": SRC_DESKTOP / "package_5380_Myroom_Back",
        "stems": [
            "common_modoru_RGBA4",
            "C_Com_icon_m",
            "C_Com_icon_mON",
        ],
        # keep existing Schedule/Sleep/Mail/Phone EN in bake
        "from_live": True,
    },
    {
        "pkg": 4149,
        "arcs": ("Album.arc",),
        "asset_dirs": (ASSETS / "Album.check" / "timg",),
        "desktop": SRC_DESKTOP / "Album_Delete",
        # Rebuilt from vanilla, so every Zhoumaru Album.check master must be
        # listed here or the bake ships it Japanese (Search, Export, popups…).
        # ``new_*`` PNGs duplicate listed masters and have no BCLIM.
        "stems": [
            "C_Btn_AllDelete_Off",
            "C_Btn_AllDelete_On",
            "C_Btn_Delete_Off",
            "C_Btn_Delete_On",
            "C_Btn_Search_Off",
            "C_Btn_Search_On",
            "C_Btn_Search02_Off",
            "C_Btn_Search02_On",
            "C_Btn_Output_Off",
            "C_Btn_Output_On",
            "Alb_DataBtn02_OffT",
            "Alb_DataBtn02_OnT",
            "Alb_DataBtn03_Off",
            "Alb_DataBtn03_On",
            "Alb_DataBtn04_Off",
            "Alb_DataBtn04_On",
            "Alb_DataPnl01c",
            "Alb_Mark05",
            "Alb_Mark06",
            "Alb_PopTxt03",
            "Alb_Popup_o02",
            "Alb_Search01b",
            "Alb_Search01c",
            "Alb_Search01d",
            "C_Com_Win01_Btn02_Cancel_Off",
            "C_Com_Win01_Btn02_Cancel_Press",
            "C_Com_Win01_Btn02_Ok_Off",
            "C_Com_Win01_Btn02_Ok_Press",
            "C_Com_Win01_t02",
            "Wall_Txt01a",
            "Wall_Txt01b",
            "Wall_Txt01c",
            "Wall_Txt01d",
            "Wall_Txt03",
            "Wall_Type0_Off",
            "Wall_Type0_On",
            "Wall_Type1_Off",
            "Wall_Type1_On",
            "Wall_Type2_Off",
            "Wall_Type2_On",
            "Wall_Type3_Off",
            "Wall_Type3_On",
        ],
        "from_live": False,
    },
]


def _ensure_staged(group: dict) -> Path:
    """Return directory with PNGs (asset dirs preferred; desktop fallback)."""
    for d in group["asset_dirs"]:
        if d.is_dir() and any(d.glob("*.png")):
            return d
    desk = group["desktop"]
    if desk.is_dir() and any(desk.glob("*.png")):
        dest = group["asset_dirs"][0]
        dest.mkdir(parents=True, exist_ok=True)
        for p in desk.glob("*.png"):
            shutil.copy2(p, dest / p.name)
        return dest
    raise SystemExit(f"missing PNGs for pkg {group['pkg']}: {desk}")


def _png_for(stem: str, src_dir: Path) -> Path:
    p = src_dir / f"{stem}.png"
    if not p.is_file():
        raise SystemExit(f"missing PNG {p}")
    return p


def _patch_arc(
    arc_bytes: bytes,
    stems: list[str],
    src_dir: Path,
    tmp: Path,
) -> bytes:
    darc = DarcArchive(bytearray(arc_bytes))
    for stem in stems:
        path = f"timg/{stem}.bclim"
        entry = darc.find(path) or darc.find(f"{stem}.bclim")
        if entry is None:
            raise SystemExit(f"missing BCLIM {path}")
        raw = darc.extract_file(entry)
        _pix, w, h, fmt, _ = parse_bclim(raw)
        png_src = _png_for(stem, src_dir)
        im = Image.open(png_src).convert("RGBA")
        if im.size != (w, h):
            print(f"  resize {stem}: {im.size} -> {w}x{h} (fmt={fmt})", flush=True)
            im = im.resize((w, h), Image.Resampling.LANCZOS)
        work_png = tmp / f"{stem}.png"
        work_bclim = tmp / f"{stem}.bclim"
        im.save(work_png)
        work_bclim.write_bytes(raw)
        new = png_to_bclim_same_size(work_png, work_bclim)
        if len(new) != len(raw):
            raise SystemExit(f"size change {stem}: {len(raw)} -> {len(new)}")
        darc.replace_same_size(entry, new)
        print(f"  OK {stem} {w}x{h} fmt={fmt}", flush=True)
    return bytes(darc.data)


def tall_sentence_pane(lyt: bytes) -> bytes:
    """Raise the message box's Tex_Sentence pic from 256 to SENTENCE_H tall."""
    out = bytearray(lyt)
    off = struct.unpack_from("<H", out, 6)[0]
    hits = 0
    for _ in range(struct.unpack_from("<I", out, 0x10)[0]):
        size = struct.unpack_from("<I", out, off + 4)[0]
        name = bytes(out[off + 12 : off + 28]).rstrip(bytes(1))
        if out[off : off + 4] == b"pic1" and name == SENTENCE_PANE:
            h = struct.unpack_from("<f", out, off + 72)[0]
            if h not in (SENTENCE_H_VANILLA, SENTENCE_H):
                raise SystemExit(f"Tex_Sentence height {h}, expected {SENTENCE_H_VANILLA}")
            struct.pack_into("<f", out, off + 72, SENTENCE_H)
            hits += 1
        off += size
    if hits != 1:
        raise SystemExit(f"Tex_Sentence pic found {hits} times")
    return bytes(out)


def _patch_layouts(arc_bytes: bytes, layouts: dict[str, str]) -> bytes:
    darc = DarcArchive(bytearray(arc_bytes))
    for path, fn_name in layouts.items():
        entry = darc.find(path)
        if entry is None:
            raise SystemExit(f"missing {path}")
        new = globals()[fn_name](bytes(darc.extract_file(entry)))
        darc.replace_same_size(entry, new)
        print(f"  OK {path} ({fn_name})", flush=True)
    return bytes(darc.data)


def _write_arc_slot(pkg_blob: bytearray, entry_index: int, tuned: bytes, slot: bytes) -> None:
    entry_off = (entry_index + 1) * Package.ENTRY_SIZE
    _typ, dec_len, _do, _fl, is_cmp, slot_len, cmp_off = Package.parse_entry(
        bytes(pkg_blob[entry_off : entry_off + Package.ENTRY_SIZE])
    )
    if not is_cmp:
        raise SystemExit(f"entry {entry_index} not compressed")
    if slot_len != len(slot) or len(tuned) != dec_len:
        raise SystemExit(
            f"entry {entry_index} mismatch slot={slot_len}/{len(slot)} "
            f"dec={dec_len}/{len(tuned)}"
        )
    pkg_blob[cmp_off : cmp_off + slot_len] = slot


def _deploy_group(group: dict, pkg_dir: Path, tmp: Path) -> Path:
    pkg_idx = group["pkg"]
    src_dir = _ensure_staged(group)
    base_img = MOD_IMG if group["from_live"] else (
        VANILLA if VANILLA.is_file() else MOD_IMG
    )
    print(
        f"\n=== pkg {pkg_idx} from {base_img.name} arcs={group['arcs']} ===",
        flush=True,
    )

    raw = base_img.read_bytes()
    img = ImgBin(str(base_img))
    img.parse(False)
    res = img.entries[pkg_idx]
    src_pkg = pkg_dir / f"{pkg_idx:04d}"
    src_pkg.write_bytes(raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()])

    pkg = Package(FileWindow(str(src_pkg)), 0)
    pkg.parse(False)
    blob = bytearray(src_pkg.read_bytes())

    wanted = {n.lower() for n in group["arcs"]}
    patched_any = False
    for i, elem in enumerate(pkg.entries):
        if not isinstance(elem, ARC):
            continue
        if elem.fn.lower() not in wanted:
            continue
        cmp_len = elem.fw.len()
        print(f"ARC {elem.fn} slot={cmp_len} dec={len(elem.parsed())}", flush=True)
        # For dual InputC/InputN, each asset_dirs[i] mirrors the same stems;
        # use matching folder when lengths align, else shared src_dir.
        use_dir = src_dir
        if len(group["asset_dirs"]) == len(group["arcs"]):
            for arc_name, ad in zip(group["arcs"], group["asset_dirs"]):
                if arc_name.lower() == elem.fn.lower() and ad.is_dir():
                    use_dir = ad
                    break
        tuned = _patch_arc(bytes(elem.parsed()), group["stems"], use_dir, tmp)
        if group.get("layouts"):
            tuned = _patch_layouts(tuned, group["layouts"])
        tuned2, slot = compress_exact_zopfli(tuned, cmp_len)
        do = zlib.decompressobj()
        got = do.decompress(slot)
        if got != tuned2 or do.unused_data or not do.eof:
            raise SystemExit(f"zlib verify failed for {elem.fn}")
        print(f"  exact zlib {len(slot)}", flush=True)
        _write_arc_slot(blob, i, tuned2, slot)
        patched_any = True

    if not patched_any:
        raise SystemExit(f"no matching ARCs in pkg {pkg_idx}")

    new_pkg = pkg_dir / f"new_{pkg_idx:04d}"
    new_pkg.write_bytes(blob)

    # Verify non-target entries unchanged vs source package bytes for DMST etc.
    pkg2 = Package(FileWindow(str(new_pkg)), 0)
    pkg2.parse(False)
    for a, b in zip(pkg.entries, pkg2.entries):
        if isinstance(a, ARC) and a.fn.lower() in wanted:
            continue
        if a.parsed() != b.parsed():
            raise SystemExit(f"non-target changed: {getattr(a, 'fn', type(a))}")
    print(f"pkg {pkg_idx} non-target entries OK", flush=True)
    return new_pkg


def main() -> int:
    if not MOD_IMG.is_file():
        raise SystemExit(f"missing deploy img: {MOD_IMG}")
    bak = maybe_backup_img(MOD_IMG, "ui_buttons")

    OUT.mkdir(parents=True, exist_ok=True)
    pkg_dir = OUT / "img_data"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_fit"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    indices: list[int] = []
    for group in GROUPS:
        _deploy_group(group, pkg_dir, tmp)
        indices.append(group["pkg"])

    # Prefer new_* blobs for splice (pack_images looks for new_NNNN)
    try:
        for dest in iter_deploy_targets(MOD_IMG):
            splice_packages_into_img(dest, pkg_dir, indices, dest)
            print(f"spliced {indices} -> {dest}", flush=True)
    except PackError as exc:
        raise SystemExit(f"splice failed: {exc}") from exc

    print("deployed UI buttons EN ->", MOD_IMG, flush=True)
    print("Rollback:", bak, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
