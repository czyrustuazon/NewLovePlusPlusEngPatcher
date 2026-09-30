"""Shared deploy targets — primary img is bake/env; Azahar is optional mirror."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nlpp_paths import (  # noqa: E402
    AZAHAR_INSTANCES,
    AZAHAR_MOD_IMG,
    AZAHAR_MOD_TRB_DIR,
    BAKE_IMG,
    OVERLAY_TRB_DIR,
    RELEASE,
    ROMFS_OVERLAY,
    TEXTRESOURCE,
    TITLE_ID,
    find_vanilla_img,
    find_vanilla_resident_trb,
    require_vanilla_img,
)

# Bundled SIL OFL font (see assets/fonts/README.md). Replaces YuGothR.ttc.
UI_FONT = ROOT / "assets" / "fonts" / "MPLUS1p-Regular.ttf"
# NLPPPATCH Heisei Gothic — MultiWin white bars (Heart to Heart, Communication).
HEISEI_W5 = ROOT / "assets" / "fonts" / "reference" / "nlppatch-2025" / "df-heiseigothic-w5.ttc"
HEADER_INK = (68, 68, 68)
# Same start size as Girlfriend Comm. `render_header_aa` (gh ~12 on 192×16).
HEADER_CORE_PX = 15
HEADER_STRIP_H = 16

__all__ = [
    "AZAHAR_INSTANCES",
    "AZAHAR_MOD_IMG",
    "AZAHAR_MOD_TRB_DIR",
    "BAKE_IMG",
    "OVERLAY_TRB_DIR",
    "RELEASE",
    "ROMFS_OVERLAY",
    "ROOT",
    "TEXTRESOURCE",
    "UI_FONT",
    "HEISEI_W5",
    "HEADER_INK",
    "HEADER_CORE_PX",
    "HEADER_STRIP_H",
    "find_vanilla_img",
    "img_backup_path",
    "iter_deploy_targets",
    "maybe_backup_img",
    "require_vanilla_img",
    "resolve_img_paths",
    "resolve_resident_trb",
    "skip_full_img_backup",
    "ui_font",
    "chrome_font",
    "render_header_aa",
    "find_ui_png",
    "fit_png_to_canvas",
    "contain_no_upscale",
]


def ui_font(size: int):
    """Load the bundled EngPatcher UI font at ``size`` pt."""
    from PIL import ImageFont

    if not UI_FONT.is_file():
        raise SystemExit(
            f"missing UI font: {UI_FONT}\n"
            "Expected assets/fonts/MPLUS1p-Regular.ttf (SIL OFL)."
        )
    return ImageFont.truetype(str(UI_FONT), size=size)


def chrome_font(size: int):
    """Heisei Gothic P-face when present (same as MultiWin Heart to Heart)."""
    from PIL import ImageFont

    if HEISEI_W5.is_file():
        return ImageFont.truetype(str(HEISEI_W5), size=size, index=1)
    return ui_font(size)


def render_header_aa(w: int, h: int, text: str, *, max_size: int | None = None):
    """Dark gray AA like Zhoumaru Communication / Heart to Heart.

    Short titles keep ~13px cores so ETC1A4 does not fry them. Default
    ``max_size`` is ``HEADER_CORE_PX`` (15) — Heart to Heart at 192×16
    lands at glyph-height 12 after 2× bilinear.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    top = max_size if max_size is not None else min(HEADER_CORE_PX, h + 2)
    for size in range(top, 7, -1):
        scale = 2
        big = Image.new("L", (w * scale, h * scale), 0)
        dr = ImageDraw.Draw(big)
        f = chrome_font(size * scale)
        b = dr.textbbox((0, 0), text, font=f)
        tw, th = b[2] - b[0], b[3] - b[1]
        if tw > w * scale - 8:
            continue
        x = (w * scale - tw) // 2 - b[0]
        y = (h * scale - th) // 2 - b[1]
        dr.text((x, y), text, font=f, fill=255)
        alpha = np.array(
            big.resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32
        )
        peak = float(alpha.max())
        if peak > 0:
            alpha = np.clip(alpha * (255.0 / peak), 0, 255)
        a = alpha.astype(np.uint8)
        rgb = Image.new("RGB", (w, h), HEADER_INK)
        return Image.merge("RGBA", (*rgb.split(), Image.fromarray(a, "L")))
    raise RuntimeError(f"cannot fit header {text!r} into {w}x{h}")


def resolve_img_paths() -> tuple[Path, Path]:
    """Return (primary_img, vanilla_img) for deploy_* scripts.

    Primary resolution (self-sustaining first):
      1. NLPP_DEPLOY_IMG
      2. release/bake_img.bin if present
      3. Azahar LayeredFS img.bin (optional test convenience)

    Vanilla resolution:
      1. NLPP_VANILLA_IMG / sibling extracted
      2. primary.bak_pre_msel5245 (legacy sidecar)
      3. primary itself
    """
    env = os.environ.get("NLPP_DEPLOY_IMG")
    if env:
        primary = Path(env).resolve()
        if not primary.is_file():
            raise SystemExit(f"NLPP_DEPLOY_IMG not found: {primary}")
    elif BAKE_IMG.is_file():
        primary = BAKE_IMG.resolve()
    elif AZAHAR_MOD_IMG.is_file():
        primary = AZAHAR_MOD_IMG.resolve()
    else:
        raise SystemExit(
            "No deploy img.bin target. Run tools/rebuild_bake_img.py first, or set "
            "NLPP_DEPLOY_IMG, or place gold at:\n"
            f"  {BAKE_IMG}"
        )

    vanilla = find_vanilla_img()
    if vanilla is None:
        bak = img_backup_path(primary, "msel5245")
        if bak.is_file():
            vanilla = bak.resolve()
        else:
            vanilla = primary
    return primary, vanilla


def img_backup_path(img: Path, tag: str) -> Path:
    """Sidecar next to ``img``, e.g. ``img.bin.bak_pre_confirm_btn``."""
    return img.with_suffix(f".bin.bak_pre_{tag}")


def skip_full_img_backup(img: Path) -> bool:
    """True for gold bake / ``NLPP_NO_IMG_BACKUP`` — a full copy is ~680MB."""
    env = os.environ.get("NLPP_NO_IMG_BACKUP", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    try:
        return img.resolve() == BAKE_IMG.resolve()
    except OSError:
        return False


def maybe_backup_img(img: Path, tag: str) -> Path:
    """Copy ``img`` once for LayeredFS rollback. Skip gold bake.

    Drop CIA / ``rebuild_bake_img.py`` target ``release/bake_img.bin``. Twenty-plus
    feature sidecars used to fill the disk (~17GB) and abort mid-bake. Vanilla
    ARCs come from ``find_vanilla_img()``; rollback for gold is rebuild.

    Returns the sidecar path whether or not a copy was written.
    """
    bak = img_backup_path(img, tag)
    if skip_full_img_backup(img):
        print(f"skip img backup: {bak.name}", flush=True)
        return bak
    if not bak.is_file():
        if not img.is_file():
            raise SystemExit(f"missing {img}")
        bak.write_bytes(img.read_bytes())
        print("created", bak, flush=True)
    return bak


def iter_deploy_targets(primary: Path) -> list[Path]:
    """Imgs to splice into: primary, bake, and Azahar LayeredFS when present.

    Azahar is mirrored by default so in-emulator tests match the gold bake.
    Opt out: set NLPP_ALSO_AZAHAR=0.
    """
    targets: list[Path] = [primary.resolve()]
    seen = {targets[0]}

    def _add(p: Path) -> None:
        rp = p.resolve()
        if rp.is_file() and rp not in seen:
            targets.append(rp)
            seen.add(rp)

    _add(BAKE_IMG)
    also = os.environ.get("NLPP_ALSO_AZAHAR", "1").strip().lower()
    if also not in ("0", "false", "no", "off"):
        _add(AZAHAR_MOD_IMG)
        if AZAHAR_INSTANCES.is_dir():
            for img in AZAHAR_INSTANCES.glob(
                f"*/user/load/mods/{TITLE_ID}/romfs/img.bin"
            ):
                _add(img)
    return targets


def resolve_resident_trb() -> Path:
    """Working resident TRB for day-counter (prefers release/; seeds from vanilla)."""
    import shutil

    env = os.environ.get("NLPP_RESIDENT_TRB")
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
        raise SystemExit(f"NLPP_RESIDENT_TRB not found: {p}")

    durable = TEXTRESOURCE / "textresource_resident_jpn.trb"
    for c in (
        durable,
        OVERLAY_TRB_DIR / "textresource_resident_jpn.trb",
        AZAHAR_MOD_TRB_DIR / "textresource_resident_jpn.trb",
    ):
        if c.is_file():
            # Prefer a writable release copy; seed durable if we only have overlay.
            if c.resolve() != durable.resolve():
                TEXTRESOURCE.mkdir(parents=True, exist_ok=True)
                if not durable.is_file():
                    shutil.copy2(c, durable)
                    print(f"[trb] seeded resident -> {durable}", flush=True)
                return durable.resolve()
            return c.resolve()

    vanilla = find_vanilla_resident_trb()
    if vanilla is not None:
        TEXTRESOURCE.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vanilla, durable)
        print(f"[trb] seeded resident from vanilla -> {durable}", flush=True)
        return durable.resolve()

    raise SystemExit(
        "resident TRB not found.\n"
        "Provide one of:\n"
        "  • set NLPP_RESIDENT_TRB\n"
        "  • place at release/textresource/textresource_resident_jpn.trb\n"
        "  • extract via rebuild --rom (cache/vanilla_from_rom/.../textresource_resident_jpn.trb)\n"
        "  • sibling New Love Plus Plus/extracted/romfs/SystemData/TextResource/"
    )


def _ui_fit_dest(png: Path, size: tuple[int, int]) -> Path:
    w, h = size
    dest = ROOT / "out" / "_ui_png_fit" / f"{png.stem}_{w}x{h}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def _glyph_bbox(src) -> tuple[int, int, int, int]:
    """Ink box: alpha when the master is A8/transparent; else the full frame."""
    bbox = src.getchannel("A").getbbox()
    if bbox is None:
        return (0, 0, src.width, src.height)
    return bbox


def _glyph_fill_needed(src_size: tuple[int, int], size: tuple[int, int], bbox) -> bool:
    """True when a strip master is going onto a different BCLIM canvas.

    MultiWin bars are 192×16 native paint. Never resample a plate (or any
    other canvas) onto that size — LANCZOS-filling 8px glyphs fries the
    Girlfriend Communication header.
    """
    w, h = size
    if src_size == (w, h):
        return False
    if (w, h) == (192, 16):
        return False
    return True


def contain_no_upscale(
    png: Path,
    size: tuple[int, int],
    *,
    max_scale: float = 1.0,
) -> "Image.Image":
    """Scale ``png`` to fit ``size`` without cropping glyphs or upscaling.

    Used for Girlfriend Communication: the plate PNG is a 192×16 strip, but
    the live BCLIM is 144×28. Glyph-filling that 8px paint fries the header.
    """
    from PIL import Image

    w, h = size
    with Image.open(png) as im:
        src = im.convert("RGBA")
    scale = min(w / src.width, h / src.height, max_scale)
    nw = max(1, min(w, int(round(src.width * scale))))
    nh = max(1, min(h, int(round(src.height * scale))))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2), resized)
    return canvas


def fit_png_to_canvas(
    png: Path, size: tuple[int, int], dest: Path | None = None
) -> Path:
    """Contain-resize painted UI onto ``size``. Never overwrites ``png``.

    Crops to the alpha/glyph bbox first so a 192×16 Zhoumaru strip can fill a
    144×28 MSel plate (or a 192×16 MultiWin bar) instead of sitting letterboxed.
    """
    from PIL import Image

    w, h = size
    dest = dest or _ui_fit_dest(png, size)
    with Image.open(png) as im:
        src = im.convert("RGBA")
        bbox = _glyph_bbox(src)
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        full = bw >= src.width - 1 and bh >= src.height - 1
        crop = src if full else src.crop(bbox)
        pad_x = 2 if w <= 192 else 4
        pad_y = 1 if h <= 16 else max(2, h // 10)
        inner_w = max(1, w - 2 * pad_x)
        inner_h = max(1, h - 2 * pad_y)
        scale = min(inner_w / crop.width, inner_h / crop.height)
        nw = max(1, min(w, int(round(crop.width * scale))))
        nh = max(1, min(h, int(round(crop.height * scale))))
        resized = crop.resize((nw, nh), Image.Resampling.LANCZOS)
        if not full:
            # Upscaled A8/MultiWin paint: keep a solid coverage mask so LANCZOS
            # fringes don't vanish (or blow the zlib slot as soft AA).
            alpha = resized.getchannel("A").point(
                lambda p: 255 if p >= 40 else 0
            )
            rgb = Image.new("RGB", resized.size, (255, 255, 255))
            resized = Image.merge("RGBA", (*rgb.split(), alpha))
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2), resized)
        canvas.save(dest)
    return dest


def find_ui_png(
    folder_names: tuple[str, ...] | list[str],
    stem: str,
    size: tuple[int, int] | None = None,
) -> Path | None:
    """Community / .check PNG master for a BCLIM stem.

    If ``size`` is set, glyph-fit onto that canvas when the master would
    otherwise letterbox. Writes the result under ``out/_ui_png_fit/`` — never
    mutates ``assets/images``.
    """
    from PIL import Image

    assets = ROOT / "assets" / "images"
    ranked: list[tuple[int, Path]] = []
    for name in folder_names:
        folder = assets / name
        if not folder.is_dir():
            continue
        for png in folder.rglob(f"{stem}.png"):
            parts_l = {p.lower() for p in png.relative_to(folder).parts}
            rank = 0 if "timg" in parts_l else 1
            ranked.append((rank, png))
    ranked.sort(key=lambda t: (t[0], str(t[1]).lower()))
    for _rank, png in ranked:
        if size is None:
            return png
        try:
            with Image.open(png) as im:
                src = im.convert("RGBA")
                src_size = src.size
                bbox = _glyph_bbox(src)
        except OSError:
            continue
        if not _glyph_fill_needed(src_size, size, bbox):
            if src_size == size:
                return png
            continue
        try:
            return fit_png_to_canvas(png, size)
        except OSError:
            continue
    return None

