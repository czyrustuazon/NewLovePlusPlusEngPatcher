"""Shared deploy targets — primary img is bake/env; Azahar is optional mirror."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nlpp_paths import (  # noqa: E402
    AZAHAR_MOD_IMG,
    AZAHAR_MOD_TRB_DIR,
    BAKE_IMG,
    OVERLAY_TRB_DIR,
    RELEASE,
    ROMFS_OVERLAY,
    TEXTRESOURCE,
    find_vanilla_img,
    find_vanilla_resident_trb,
    require_vanilla_img,
)

# Bundled SIL OFL font (see assets/fonts/README.md). Replaces YuGothR.ttc.
UI_FONT = ROOT / "assets" / "fonts" / "MPLUS1p-Regular.ttf"

__all__ = [
    "AZAHAR_MOD_IMG",
    "AZAHAR_MOD_TRB_DIR",
    "BAKE_IMG",
    "OVERLAY_TRB_DIR",
    "RELEASE",
    "ROMFS_OVERLAY",
    "ROOT",
    "TEXTRESOURCE",
    "UI_FONT",
    "find_vanilla_img",
    "iter_deploy_targets",
    "require_vanilla_img",
    "resolve_img_paths",
    "resolve_resident_trb",
    "ui_font",
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
        bak = primary.with_suffix(".bin.bak_pre_msel5245")
        if bak.is_file():
            vanilla = bak.resolve()
        else:
            vanilla = primary
    return primary, vanilla


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

