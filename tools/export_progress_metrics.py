#!/usr/bin/env python3
"""Export fansite progress metrics (scripts, SMS, TRB, images) with file names.

Usage:
  python tools/export_progress_metrics.py
  python tools/export_progress_metrics.py --json out/progress_metrics.json
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from image_map import IMAGE_MAP  # noqa: E402
from pack_images import iter_asset_pngs, prefer_asset_folders  # noqa: E402
from script_inject import (  # noqa: E402
    DEFAULT_ENG_DBIN,
    LEGACY_NLPPATCH_SCRIPT,
    SCRIPT_PACK_TOTAL,
    nlppatch_script_dir,
    nlppatch_stems,
    resolve_script_source,
)
from patch_textresource import (  # noqa: E402
    DEFAULT_TRANSLATIONS,
    DEFAULT_TRB,
    dump_entries,
    load_lookup,
    parse_chunks,
)
from img import Image as ImgBin  # noqa: E402
from mdcutil import parse_mdc  # noqa: E402

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
BAKE_IMG = ROOT / "release" / "bake_img.bin"
SMS_PKG = 92
SMS_FILES = {
    "manaka": "maildic_m.mdc",
    "nene": "maildic_n.mdc",
    "rinko": "maildic_r.mdc",
}
SMS_EN_SOURCES = {
    "manaka": "assets/sms_en/maildic_m.en.xml",
    "nene": "assets/sms_en/maildic_n.en.xml",
    "rinko": "assets/sms_en/maildic_r.en.xml",
}

# UI chrome packages (documented + bake pipeline)
UI_FOLDER_KEYS: tuple[str, ...] = (
    "ncommonicon",
    "ncommonmsel(3)",
    "ncommonmsel(4)",
    "ncommonmsel(6)",
    "ncommonmsel(7)",
    "ncommonmsel(8)",
    "option",
    "option06",
    "title",
    "myroom",
    "myroomheader",
    "profile",
    "quest",
    "mail",
    "syspopup",
    "introcommon",
    "inputctexture",
    "inputntexture",
    "fileselect",
    "gallery_common",
    "myroomback",
    "album",
    "telephone",
    "scdstatus",
    "schedule",
)


# Vanilla script/bin/script stem counts (New Love Plus+). rebuild_dbin2 only
# stores English files; JP stems stay on the ROM and must still count here.
VANILLA_ROUTE_TOTALS = {
    "manaka": 175,
    "rinko": 174,
    "nene": 174,
    "common": 55,
}


def route_for_stem(stem: str) -> str:
    p = stem[0].lower() if stem else ""
    return {"t": "manaka", "k": "rinko", "a": "nene", "p": "common"}.get(p, "other")


def script_metrics(eng_root: Path) -> dict:
    script_dir = eng_root / "script"
    stems = sorted(p.stem for p in script_dir.glob("*.dbin2"))
    routes: dict[str, dict] = {}
    files: dict[str, list[dict]] = {
        "english": [],
        "japanese": [],
    }
    for stem in stems:
        route = route_for_stem(stem)
        src, tag = resolve_script_source("script", stem, eng_root)
        en = tag != "jp"
        rec = {
            "stem": stem,
            "file": f"script/{stem}.dbin2",
            "route": route,
            "layer": tag,
            "source": str(src) if src else None,
        }
        routes.setdefault(
            route,
            {"total": 0, "english": 0, "japanese": 0, "layers": {}},
        )
        if en:
            routes[route]["english"] += 1
            routes[route]["layers"][tag] = routes[route]["layers"].get(tag, 0) + 1
            files["english"].append(rec)
        else:
            files["japanese"].append(rec)

    for name, tot in VANILLA_ROUTE_TOTALS.items():
        routes.setdefault(name, {"total": 0, "english": 0, "japanese": 0, "layers": {}})
        en_n = routes[name]["english"]
        routes[name]["total"] = tot
        routes[name]["japanese"] = max(0, tot - en_n)

    en_total = len(files["english"])
    total = SCRIPT_PACK_TOTAL
    out_routes = {}
    for name, v in routes.items():
        out_routes[name] = {
            **v,
            "percent": round(100.0 * v["english"] / v["total"], 1) if v["total"] else 0.0,
        }
    return {
        "pack": "script",
        "path_glob": "rebuild_dbin2/script/*.dbin2",
        "vendor_nlppatch": str(nlppatch_script_dir() or LEGACY_NLPPATCH_SCRIPT),
        "nlppatch_stem_count": len(nlppatch_stems()),
        "total_files": total,
        "english_files": en_total,
        "japanese_files": total - en_total,
        "percent": round(100.0 * en_total / total, 1) if total else 0.0,
        "by_route": out_routes,
        "files": files,
    }


def sms_metrics(img_path: Path) -> dict:
    if not img_path.is_file():
        # Gold bake is gitignored; still emit the known JP-in-bake SMS headline
        # so image/script exports do not die on a missing 680 MB img.bin.
        by_hero = {
            "manaka": {
                "hero": "manaka",
                "mdc_file": "maildic_m.mdc",
                "img_bin_package": SMS_PKG,
                "total_messages": 599,
                "english_messages": 0,
                "japanese_messages": 599,
                "percent": 0.0,
            },
            "nene": {
                "hero": "nene",
                "mdc_file": "maildic_n.mdc",
                "img_bin_package": SMS_PKG,
                "total_messages": 634,
                "english_messages": 0,
                "japanese_messages": 634,
                "percent": 0.0,
            },
            "rinko": {
                "hero": "rinko",
                "mdc_file": "maildic_r.mdc",
                "img_bin_package": SMS_PKG,
                "total_messages": 589,
                "english_messages": 0,
                "japanese_messages": 589,
                "percent": 0.0,
            },
        }
        return {
            "storage": f"img.bin package {SMS_PKG}",
            "deploy_tool": "tools/deploy_sms_maildic_en.py",
            "restore_tool": "tools/restore_sms_maildic_jpn.py",
            "note": (
                f"EN disabled in gold bake by default; {img_path} missing — "
                "SMS counts are the documented JP bake headline (0/1822), not a live parse"
            ),
            "total_messages": 1822,
            "english_messages": 0,
            "percent": 0.0,
            "by_hero": by_hero,
        }

    im = ImgBin(str(img_path))
    im.parse(recursive=False)
    pak = im.entries[SMS_PKG]
    pak.parse(recursive=False)
    by_hero: dict[str, dict] = {}
    for hero, mdc_name in SMS_FILES.items():
        te = next((e for e in pak.entries if e.fn == mdc_name), None)
        if te is None:
            by_hero[hero] = {"error": f"missing {mdc_name}"}
            continue
        entries = parse_mdc(te.read())
        en_src = ROOT / SMS_EN_SOURCES[hero]
        wip = en_src.is_file()
        texts = []
        en_n = 0
        for i, ent in enumerate(entries):
            is_jp = bool(JP_RE.search(ent.text))
            if not is_jp:
                en_n += 1
            texts.append(
                {
                    "index": i,
                    "key": f"0x{ent.key:016x}",
                    "japanese": is_jp,
                    "preview": ent.text[:80],
                }
            )
        by_hero[hero] = {
            "hero": hero,
            "mdc_file": mdc_name,
            "img_bin_package": SMS_PKG,
            "en_wip_source": str(en_src.relative_to(ROOT)) if wip else None,
            "total_messages": len(entries),
            "english_messages": en_n,
            "japanese_messages": len(entries) - en_n,
            "percent": round(100.0 * en_n / len(entries), 1) if entries else 0.0,
            "messages": texts,
        }
    total = sum(h.get("total_messages", 0) for h in by_hero.values())
    en = sum(h.get("english_messages", 0) for h in by_hero.values())
    return {
        "storage": f"img.bin package {SMS_PKG}",
        "deploy_tool": "tools/deploy_sms_maildic_en.py",
        "restore_tool": "tools/restore_sms_maildic_jpn.py",
        "note": "EN disabled in gold bake by default; counts from release/bake_img.bin",
        "total_messages": total,
        "english_messages": en,
        "percent": round(100.0 * en / total, 1) if total else 0.0,
        "by_hero": by_hero,
    }


def parse_indx_categories(indx: bytes) -> dict[int, list[int]]:
    """Map category id -> list of STRI entry indices."""
    if len(indx) < 0x400:
        return {}
    cat_offs = [struct.unpack_from("<I", indx, i)[0] for i in range(0, 0x400, 4)]
    out: dict[int, list[int]] = {}
    for cat, off in enumerate(cat_offs):
        if off == 0 or off >= len(indx):
            continue
        sub_count = struct.unpack_from("<I", indx, off)[0]
        subs: list[int] = []
        base = off + 4
        for si in range(sub_count):
            if base + si * 4 + 4 > len(indx):
                break
            rel = struct.unpack_from("<I", indx, base + si * 4)[0]
            if rel == 0:
                continue
            subs.append(off + rel)
        indices: list[int] = []
        for sub_off in subs:
            if sub_off + 4 > len(indx):
                continue
            slot_count = struct.unpack_from("<I", indx, sub_off)[0]
            ptr = sub_off + 4
            for _ in range(slot_count):
                if ptr + 2 > len(indx):
                    break
                (stri_idx,) = struct.unpack_from("<H", indx, ptr)
                indices.append(stri_idx)
                ptr += 2
        if indices:
            out[cat] = sorted(set(indices))
    return out


def trb_metrics(trb_path: Path, translations_path: Path) -> dict:
    lookup = load_lookup(ROOT / "tools" / "Trb2xlsx" / "TrbExport" / "lookup.txt")
    data = trb_path.read_bytes()
    entries = dump_entries(data, lookup)
    trans: dict[str, str] = {}
    if translations_path.is_file():
        raw = json.loads(translations_path.read_text(encoding="utf-8"))
        trans = raw.get("translations", raw) if isinstance(raw, dict) else {}

    chunks = parse_chunks(data)
    cat_map = parse_indx_categories(chunks.get("INDX", b""))

    # Per STRI entry: translated if no JP in text OR key in translations.json
    def is_english(text: str, idx: int) -> bool:
        if not text or text.strip() == "":
            return True
        if text in trans:
            return True
        return not JP_RE.search(text)

    en_entries = []
    jp_entries = []
    for e in entries:
        text = e["text"]
        idx = e["idx"]
        rec = {"stri_index": idx, "preview": text[:80].replace("\n", "◙")}
        if is_english(text, idx):
            en_entries.append(rec)
        else:
            jp_entries.append(rec)

    by_category: dict[str, dict] = {}
    assigned: set[int] = set()
    for cat, indices in sorted(cat_map.items()):
        en = sum(1 for i in indices if i < len(entries) and is_english(entries[i]["text"], i))
        assigned.update(indices)
        by_category[f"cat_{cat:03d}"] = {
            "category_id": cat,
            "pack_hex": f"0x{cat:02x}00",
            "stri_slots": len(indices),
            "english_slots": en,
            "percent": round(100.0 * en / len(indices), 1) if indices else 0.0,
        }
    unassigned = [i for i in range(len(entries)) if i not in assigned]
    if unassigned:
        en_u = sum(1 for i in unassigned if is_english(entries[i]["text"], i))
        by_category["unassigned_stri"] = {
            "stri_slots": len(unassigned),
            "english_slots": en_u,
            "percent": round(100.0 * en_u / len(unassigned), 1),
        }

    return {
        "file": str(trb_path.relative_to(ROOT)) if trb_path.is_relative_to(ROOT) else str(trb_path),
        "translations_map": str(translations_path.relative_to(ROOT)),
        "translation_keys": len(trans),
        "total_stri_entries": len(entries),
        "english_entries": len(en_entries),
        "japanese_entries": len(jp_entries),
        "percent": round(100.0 * len(en_entries) / len(entries), 1) if entries else 0.0,
        "detection": "no Japanese chars in STRB text OR JP key present in translations.json",
        "by_indx_category": by_category,
        "english_stri_indices": [e["stri_index"] for e in en_entries],
        "japanese_stri_indices": [e["stri_index"] for e in jp_entries],
    }


def resident_trb_metrics(path: Path) -> dict:
    if not path.is_file():
        return {"file": str(path), "present": False}
    data = path.read_bytes()
    # TOP format: rough fragment count by null split
    frags = [f.decode("utf-8", errors="replace") for f in data.split(b"\x00") if f]
    jp = sum(1 for f in frags if JP_RE.search(f))
    en = len(frags) - jp
    return {
        "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "present": True,
        "fragments": len(frags),
        "english_fragments": en,
        "japanese_fragments": jp,
        "percent": round(100.0 * en / len(frags), 1) if frags else 0.0,
        "patch_tool": "src/patch_names.py + release/romfs_overlay/textresource_resident_jpn.trb",
    }


def image_metrics() -> dict:
    images_root = ROOT / "assets" / "images"
    folders = prefer_asset_folders(images_root)
    ui: dict[str, dict] = {}
    all_pngs: list[dict] = []
    for key in UI_FOLDER_KEYS:
        if key not in folders:
            ui[key] = {
                "folder_key": key,
                "asset_dir": None,
                "png_masters": 0,
                "png_files": [],
            }
            continue
        folder = folders[key]
        rel = str(folder.relative_to(ROOT))
        pkg_idx, arc_name = IMAGE_MAP.get(key, (None, None))
        pngs = iter_asset_pngs(folder)
        names = sorted(p.name for p in pngs)
        ui[key] = {
            "folder_key": key,
            "asset_dir": rel,
            "img_bin_package": pkg_idx,
            "arc_file": arc_name,
            "png_masters": len(names),
            "png_files": names,
        }
        for n in names:
            all_pngs.append({"folder_key": key, "png": n, "package": pkg_idx})

    total_ui_pngs = sum(v.get("png_masters", 0) for v in ui.values())
    mapped_png = 0
    mapped_hit = 0
    empty: list[str] = []
    for key in IMAGE_MAP:
        folder = folders.get(key)
        if folder is None:
            empty.append(key)
            continue
        n = len(iter_asset_pngs(folder))
        mapped_png += n
        if n:
            mapped_hit += 1
    return {
        "gold_bake": str(BAKE_IMG.relative_to(ROOT)),
        "source_root": "assets/images/<Folder>.check/",
        "image_map": "src/image_map.py",
        "ui_folder_keys": list(UI_FOLDER_KEYS),
        "ui_packages_with_png_masters": sum(1 for v in ui.values() if v.get("png_masters")),
        "ui_png_masters_total": total_ui_pngs,
        "mapped_png_masters_total": mapped_png,
        "mapped_folders_with_png": mapped_hit,
        "image_map_keys": len(IMAGE_MAP),
        "empty_image_map_keys": empty,
        "note": "Percent = EN PNG masters present / not full vanilla BCLIM inventory. ui_* = chrome subset; mapped_* = all IMAGE_MAP folders",
        "by_folder": ui,
        "all_png_files": all_pngs,
    }


def combined_text_metrics(scripts: dict, sms: dict) -> dict:
    s_en = scripts["english_files"]
    s_tot = scripts["total_files"]
    m_en = sms["english_messages"]
    m_tot = sms["total_messages"]
    return {
        "label": "Dialogue scripts + SMS messages",
        "english": s_en + m_en,
        "total": s_tot + m_tot,
        "percent": round(100.0 * (s_en + m_en) / (s_tot + m_tot), 1),
        "components": {
            "scripts": f"{s_en}/{s_tot}",
            "sms": f"{m_en}/{m_tot}",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=ROOT / "out" / "progress_metrics.json")
    ap.add_argument("--dbin", type=Path, default=DEFAULT_ENG_DBIN)
    ap.add_argument("--trb", type=Path, default=None)
    ap.add_argument("--img", type=Path, default=BAKE_IMG)
    args = ap.parse_args()

    trb = args.trb or (ROOT / "release" / "textresource" / "textresource_jpn.trb")
    if not trb.is_file():
        trb = DEFAULT_TRB

    resident = ROOT / "release" / "romfs_overlay" / "SystemData" / "TextResource" / "textresource_resident_jpn.trb"

    scripts = script_metrics(args.dbin.resolve())
    sms = sms_metrics(args.img.resolve())
    trb_m = trb_metrics(trb.resolve(), DEFAULT_TRANSLATIONS.resolve()) if trb.is_file() else {"error": "missing TRB"}
    resident_m = resident_trb_metrics(resident)
    images = image_metrics()

    payload = {
        "title_id": "00040000000F4E00",
        "repo": "NewLovePlusPlusEngPatcher",
        "generated_by": "tools/export_progress_metrics.py",
        "regenerate": "python tools/export_progress_metrics.py --json out/progress_metrics.json",
        "dialogue_scripts": scripts,
        "sms_phone": sms,
        "dialogue_plus_sms": combined_text_metrics(scripts, sms),
        "trb_main": trb_m,
        "trb_resident": resident_m,
        "images_ui": images,
    }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.json}")
    print(f"Scripts: {scripts['english_files']}/{scripts['total_files']} ({scripts['percent']}%)")
    print(f"SMS: {sms['english_messages']}/{sms['total_messages']} ({sms['percent']}%)")
    print(f"Scripts+SMS: {payload['dialogue_plus_sms']['english']}/{payload['dialogue_plus_sms']['total']} ({payload['dialogue_plus_sms']['percent']}%)")
    if "percent" in trb_m:
        print(f"TRB: {trb_m['english_entries']}/{trb_m['total_stri_entries']} ({trb_m['percent']}%)")
    print(f"UI PNG masters (chrome): {images['ui_png_masters_total']}")
    print(
        f"UI PNG masters (mapped): {images['mapped_png_masters_total']} "
        f"in {images['mapped_folders_with_png']}/{images['image_map_keys']} folders"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
