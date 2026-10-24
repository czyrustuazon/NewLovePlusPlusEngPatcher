"""Slideshow BGM value pane ``Tex_BGM`` is only 155px wide.

Long EN track titles expand the white plate over the ←/→ arrows
(``Lyt_Gal_slideshow.bclyt`` @ pkg 5153). Keep BGM-key EN short enough
to fit Heisei W5 size 14 — do not widen the BCLYT for this.
"""

from __future__ import annotations

import json

from PIL import Image, ImageDraw, ImageFont

from conftest import ROOT

TEX_BGM_W = 155
TRANSLATIONS = ROOT / "assets" / "textresource" / "translations.json"
HEISEI = (
    ROOT
    / "assets"
    / "fonts"
    / "reference"
    / "nlppatch-2025"
    / "df-heiseigothic-w5.ttc"
)

# Screenshot family + siblings that used to overflow Tex_BGM.
SHORT_BGM_TITLES = {
    "愛花のテーマ・片思い": "Manaka Unrequited Love",
    "凛子のテーマ・片思い": "Rinko Unrequited Love",
    "寧々のテーマ・片思い": "Nene Unrequited Love",
    "愛花のテーマ(温・動)": "Manaka (Warm/Active)",
    "旅行・旅館のテーマ(日中)": "Inn Theme (Daytime)",
    "日常・早春(夜/C-Type・NEW)": "Early Spring (N/C NEW)",
}


def _font():
    return ImageFont.truetype(str(HEISEI), 14, index=1)


def _width(text: str, font) -> int:
    dr = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    return dr.textbbox((0, 0), text, font=font)[2]


def _bgm_entries(mapping: dict[str, str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in mapping.items():
        if not isinstance(v, str):
            continue
        if "\n" in v or "◙" in k:
            continue
        if "テーマ" in k or k.startswith("日常") or "旅館" in k:
            out.append((k, v))
    return out


def test_unrequited_theme_titles_use_short_copy():
    mapping = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))["translations"]
    for jp, en in SHORT_BGM_TITLES.items():
        assert mapping[jp] == en


def test_slideshow_bgm_titles_fit_tex_bgm_pane():
    mapping = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))["translations"]
    font = _font()
    overflows = []
    for jp, en in _bgm_entries(mapping):
        w = _width(en, font)
        if w > TEX_BGM_W:
            overflows.append(f"{w}px {en!r} <- {jp}")
    assert not overflows, (
        "Slideshow Tex_BGM is 155px; shorten these EN titles:\n"
        + "\n".join(overflows)
    )


def test_long_aika_theme_copy_is_gone():
    """Guard the exact overflowing string from the Slideshow screenshot."""
    text = TRANSLATIONS.read_text(encoding="utf-8")
    assert "Aika's Theme - Unrequited Love" not in text
    assert "Rinko's Theme - Unrequited Love" not in text
    assert "Nene's Theme - Unrequited Love" not in text
