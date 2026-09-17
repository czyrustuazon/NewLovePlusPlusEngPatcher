"""Fit Zhoumaru PNGs onto vanilla BCLIM canvases; dump empty intro packages."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "nlpp-tools"))

from bclimutil import decode_bclim_to_image, parse_bclim  # noqa: E402
from darcutil import DarcArchive  # noqa: E402
from image_map import IMAGE_MAP  # noqa: E402
from img import ARC, FileWindow, Image as ImgBin, Package  # noqa: E402
from nlpp_paths import find_vanilla_img  # noqa: E402

ASSETS = ROOT / "assets" / "images"
REPORT = ROOT / "out" / "fit_ui_masters" / "fit_report.json"


def load_img(path: Path) -> tuple[bytes, ImgBin]:
    raw = path.read_bytes()
    img = ImgBin(str(path))
    img.parse(False)
    return raw, img


def extract_arcs(raw: bytes, img: ImgBin, pkg: int, tmp: Path) -> list[bytes]:
    res = img.entries[pkg]
    blob = raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
    pkg_path = tmp / f"{pkg:04d}"
    pkg_path.write_bytes(blob)
    package = Package(FileWindow(str(pkg_path)), 0)
    package.parse(False)
    return [e.read() for e in package.entries if isinstance(e, ARC)]


def bclim_index(arcs: list[bytes]) -> dict[str, tuple[int, int, int, bytes]]:
    out: dict[str, tuple[int, int, int, bytes]] = {}
    for arc in arcs:
        darc = DarcArchive(arc)
        for f in darc.files:
            if not f.name.lower().endswith(".bclim"):
                continue
            raw = darc.extract_file(f)
            try:
                _pix, w, h, fmt, _ = parse_bclim(raw)
            except ValueError:
                continue
            out[Path(f.name).stem.lower()] = (w, h, fmt, raw)
    return out


def fit_contain(im: Image.Image, w: int, h: int) -> Image.Image:
    src = im.convert("RGBA")
    if src.size == (w, h):
        return src
    scale = min(w / src.width, h / src.height)
    nw = max(1, int(round(src.width * scale)))
    nh = max(1, int(round(src.height * scale)))
    if nw > w:
        nw = w
    if nh > h:
        nh = h
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2), resized)
    return canvas


def decode_bclim(raw: bytes) -> Image.Image | None:
    return decode_bclim_to_image(raw)


def guess_targets(stem: str, bclims: dict[str, tuple]) -> list[str]:
    s = stem.lower()
    cands = [s]
    if s.startswith("__"):
        cands.append(s[2:])
    if s.startswith("new_"):
        rest = s[4:]
        cands += [rest, f"c_{rest}", f"alb_{rest}"]
    if s.endswith("_upper"):
        cands.append(s[: -len("_upper")])
    if s.endswith("_rgba4"):
        cands.append(s[: -len("_rgba4")])
    if s.endswith("_eng"):
        cands.append(s[: -len("_eng")])
    out = []
    seen = set()
    for c in cands:
        if c in bclims and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def main() -> int:
    vanilla = find_vanilla_img()
    raw, img = load_img(vanilla)
    tmp = Path(tempfile.mkdtemp(prefix="fit_apply_"))
    actions: list[dict] = []

    size_path = ROOT / "out" / "fit_ui_masters" / "size_mismatch.json"
    no_path = ROOT / "out" / "fit_ui_masters" / "no_bclim.json"
    size_rows = json.loads(size_path.read_text(encoding="utf-8")) if size_path.is_file() else []
    no_bclim = json.loads(no_path.read_text(encoding="utf-8")) if no_path.is_file() else []

    # --- 1. exact canvas fit for known size mismatches ---
    for row in size_rows:
        png = ROOT / row["png"]
        w, h = row["bclim"]
        if not png.is_file():
            continue
        with Image.open(png) as im:
            fitted = fit_contain(im, w, h)
        fitted.save(png)
        actions.append({"op": "resize", "png": row["png"], "to": [w, h]})
        print(f"[resize] {png.relative_to(ROOT)} -> {w}x{h}")

    # --- 2. remap new_* / extra stems onto real BCLIM names ---
    pkg_index: dict[int, dict[str, tuple]] = {}
    for row in no_bclim:
        pkg = int(row["pkg"])
        if pkg not in pkg_index:
            pkg_index[pkg] = bclim_index(extract_arcs(raw, img, pkg, tmp))
        bclims = pkg_index[pkg]
        src = ROOT / row["png"]
        if not src.is_file():
            continue
        targets = guess_targets(row["stem"], bclims)
        if not targets:
            continue
        with Image.open(src) as im:
            src_im = im.convert("RGBA")
        for tstem in targets:
            w, h, _fmt, _b = bclims[tstem]
            dest = src.parent / f"{tstem}.png"
            existing = list(src.parent.glob(f"{tstem}.png"))
            if existing:
                dest = existing[0]
            fitted = fit_contain(src_im, w, h)
            fitted.save(dest)
            actions.append(
                {
                    "op": "remap",
                    "from": row["png"],
                    "to": str(dest.relative_to(ROOT)),
                    "stem": tstem,
                    "size": [w, h],
                }
            )
            print(f"[remap] {src.name} -> {dest.name} {w}x{h}")

    # --- 3. dump empty intro packages ---
    for key in ("intro111", "intro203", "intro304"):
        idx, _arc = IMAGE_MAP[key]
        folder = ASSETS / f"{key[:1].upper() + key[1:]}.check" / "timg"
        # Intro111.check etc.
        folder = ASSETS / {
            "intro111": "Intro111.check",
            "intro203": "Intro203.check",
            "intro304": "Intro304.check",
        }[key] / "timg"
        folder.mkdir(parents=True, exist_ok=True)
        bclims = bclim_index(extract_arcs(raw, img, idx, tmp))
        for stem, (w, h, fmt, braw) in bclims.items():
            dest = folder / f"{stem}.png"
            decoded = decode_bclim(braw)
            if decoded is None:
                if "black" in stem.lower():
                    decoded = Image.new("RGBA", (w, h), (0, 0, 0, 255))
                    actions.append(
                        {
                            "op": "intro_black",
                            "stem": stem,
                            "fmt": fmt,
                            "size": [w, h],
                        }
                    )
                    print(f"[intro] {key} {stem} black {w}x{h} fmt={fmt}")
                    decoded.save(dest)
                else:
                    if dest.is_file():
                        dest.unlink()
                    actions.append(
                        {
                            "op": "intro_skip_jp",
                            "stem": stem,
                            "fmt": fmt,
                            "size": [w, h],
                        }
                    )
                    print(f"[intro] {key} {stem} fmt={fmt} leave JP (no decoder)")
                continue
            else:
                actions.append(
                    {
                        "op": "intro_dump",
                        "stem": stem,
                        "fmt": fmt,
                        "size": [w, h],
                    }
                )
                print(f"[intro] {key} {stem} dumped {w}x{h} fmt={fmt}")
            decoded.save(dest)

    # --- 4. chrome: HelpBtn / MultiWin already named; fit if size differs ---
    chrome_folders = [
        (5247, ASSETS / "option.check" / "timg"),
        (5248, ASSETS / "Option06.check" / "timg"),
        (5237, ASSETS / "NCommon.check" / "timg"),
        (5261, ASSETS / "Title.check" / "timg"),
        (5238, ASSETS / "NCommonIcon.check" / "timg"),
        (5245, ASSETS / "NCommonMSel(3).check" / "timg"),
        (5239, ASSETS / "NCommonMSel(9).check" / "timg"),
        (4185, ASSETS / "Commu_Option.check"),
    ]
    for pkg, folder in chrome_folders:
        if not folder.is_dir():
            continue
        bclims = bclim_index(extract_arcs(raw, img, pkg, tmp))
        for png in folder.glob("*.png"):
            rec = bclims.get(png.stem.lower())
            if rec is None:
                continue
            w, h, _fmt, _b = rec
            with Image.open(png) as im:
                if im.size == (w, h):
                    continue
                fitted = fit_contain(im, w, h)
            fitted.save(png)
            actions.append(
                {
                    "op": "chrome_fit",
                    "png": str(png.relative_to(ROOT)),
                    "to": [w, h],
                }
            )
            print(f"[chrome] {png.name} -> {w}x{h}")

    # --- 5. copy leftover Title/camera extras into the package that owns the BCLIM ---
    relocates = [
        (
            ASSETS / "Title.check" / "timg" / "Com_M_Sel_Btn_Efe03.png",
            ASSETS / "NCommonMSel(9).check" / "timg" / "Com_M_Sel_Btn_Efe03.png",
            (218, 44),
        ),
        (
            ASSETS / "Title.check" / "timg" / "Commu_Op_Text02.png",
            ASSETS / "Commu_Option.check" / "timg" / "Commu_Op_Text02.png",
            (128, 32),
        ),
        (
            ASSETS / "Title.check" / "timg" / "Commu_Op_Text04.png",
            ASSETS / "Commu_Option.check" / "timg" / "Commu_Op_Text04.png",
            (128, 32),
        ),
        (
            ASSETS / "Title.check" / "timg" / "Gallery_txt07.png",
            ASSETS / "Gallery_Common.check" / "timg" / "Gallery_txt07.png",
            (32, 16),
        ),
        (
            ASSETS / "Title.check" / "timg" / "Opt_Time_tex2.png",
            ASSETS / "Option06.check" / "timg" / "Opt_Time_tex2.png",
            (16, 16),
        ),
        (
            ASSETS / "Title.check" / "timg" / "album_top_tex.png",
            ASSETS / "MyroomHeader.check" / "timg" / "album_top_tex.png",
            (128, 16),
        ),
        (
            ASSETS / "Title.check" / "timg" / "mydata_toptex_RGBA4.png",
            ASSETS / "MyroomHeader.check" / "timg" / "mydata_toptex_RGBA4.png",
            (128, 16),
        ),
        (
            ASSETS / "DateEditBase01.check" / "timg" / "Com_btn_dt01.png",
            ASSETS / "dateeditbase02.check" / "timg" / "Com_btn_dt01.png",
            (64, 64),
        ),
        (
            ASSETS / "Camera_Btn01.check" / "timg" / "Btn_kamae_a_upper.png",
            ASSETS / "Camera_Btn01.check" / "timg" / "Btn_kamae_a.png",
            (64, 64),
        ),
        (
            ASSETS / "Camera_Btn01.check" / "timg" / "Btn_kamae_b_upper.png",
            ASSETS / "Camera_Btn01.check" / "timg" / "Btn_kamae_b.png",
            (64, 64),
        ),
    ]
    for src, dest, (w, h) in relocates:
        if not src.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            fitted = fit_contain(im.convert("RGBA"), w, h)
        fitted.save(dest)
        actions.append(
            {
                "op": "relocate",
                "from": str(src.relative_to(ROOT)),
                "to": str(dest.relative_to(ROOT)),
                "size": [w, h],
            }
        )
        print(f"[relocate] {src.name} -> {dest.relative_to(ASSETS)}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(actions, indent=2), encoding="utf-8")
    print(f"\n{len(actions)} actions -> {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
