# NLPPPATCH reference fonts (2025)

Typography reference from `[NLPPPATCH]_Graphics&Text_Reference_(2025).zip`
(LovePlusProject / NLPPPATCH community). Use these when rendering or matching
in-game UI text instead of guessing a substitute.

**Not for redistribution.** Most files are commercial/game fonts (Dynacomware DF
Gothic family, Morisawa Kozuka Gothic, etc.) bundled for personal romhack reference.
EngPatcher’s default deploy font remains `../MPLUS1p-Regular.ttf` (SIL OFL).

## Quick picker

| Font file | Typical use |
|-----------|-------------|
| `df-heiseigothic-w5.ttc` | Body UI — regular weight (Heisei Gothic) |
| `df-heiseigothic-w7.ttc` | Emphasis / section headers |
| `df-heiseigothic-w9.ttc` | Bold titles |
| `df-kakougothic-w5.ttc` | Alternate Gothic (角ゴ) |
| `df-chubutomarugothic-w7.ttc` | Rounded UI (丸ゴ) |
| `dfg-kakougothic-w5.ttc` | Proportional Kakugo variant |
| `dfg-chubutomarugothic-w7.ttc` | Proportional rounded variant |
| `dfp-kakougothic-w5.ttc` | Proportional Kakugo (P) |
| `dfp-chubutomarugothic-w7.ttc` | Proportional rounded (P) |
| `KozGoPr6NRegular.otf` | Kozuka Gothic Pr6N — menu-like labels |
| `DFPOPMix-W5-WINP-RKSJ-H.ttf` | Pop / mixed display |
| `Geomanist-Regular.ttf` / `Geomanist-Medium.ttf` | Latin UI (reference screenshots) |
| `amira-*.otf` / `amiraparadiso.ttf` | Decorative / accent (see PSD sheet) |

See also `nlppatch-2025/` font specimen: parent Graphics zip includes
`[NLPPPATCH]_Fonts Reference Sheet (2025)_251119.psd` (not stored here — large).

## Python (PIL)

```python
from pathlib import Path
from PIL import ImageFont

FONTS = Path("assets/fonts/reference/nlppatch-2025")
font = ImageFont.truetype(str(FONTS / "df-heiseigothic-w5.ttc"), size=18, index=0)
```

TTC files may contain multiple faces; try `index=0, 1, …` if glyphs look wrong.

## Source

Extracted from user’s local copy of:
`[NLPPPATCH]_Graphics&Text_Reference_(2025).zip` → `[NLPPPATCH]_FONTs.zip`
