# LLM prompt — update fansite progress numbers

Copy everything below the line into another chat with the **newloveplus.loc.moe** site source attached (`new-love-plus-site`, especially `src/data/progress.json`, `src/pages/progress.astro`, `src/pages/volunteer.astro`, `src/components/ProgressBar.astro`, `scripts/import-progress.mjs`).

---

## Prompt

You are updating **newloveplus.loc.moe** progress numbers for the New Love Plus+ English patch (title `00040000000F4E00`). Patcher repo: NewLovePlusPlusEngPatcher. Site repo: new-love-plus-site.

### Goal

Refresh the Progress page, homepage summary bars, and any volunteer copy that still quotes old UI PNG counts. Do **not** invent percentages. Prefer the site’s existing data pipeline over hand-editing giant JSON.

### How numbers actually get onto the site

Do this first if the patcher workspace is available:

```bash
# in NewLovePlusPlusEngPatcher
python tools/export_progress_metrics.py --json out/progress_metrics.json

# in new-love-plus-site
node scripts/import-progress.mjs
# or: node scripts/import-progress.mjs path/to/progress_metrics.json
```

`src/data/progress.json` is a **trimmed committed copy** of that export. `src/lib/progress.ts` recomputes bar percents from raw counts. Homepage `ProgressBar.astro` and `/progress/` both read that file.

The live homepage **script** bar can also be POSTed by nlpp-gold-maker / Drop CIA (`GET /api/progress`). Graphics/menus on the site admin stay **manual**. Do not blend TRB ~98% into a single “translation done” headline.

If you cannot re-export, apply the **Facts** below to copy and to `images_ui` headlines only. Do not hand-rewrite the 5k-line script file tables.

### Facts you must use (2026-10-23)

**Dialogue / SMS / TRB.** Gemini rows are an unreviewed machine pass. The 28 Nene and 28 Rinko files with no English are empty retail stubs.

| Bucket | EN / total | % |
|--------|------------|---|
| Dialogue scripts (`script/*.dbin2` + Gemini archive) | 522 / 578 | 90.3% |
| Manaka `t*` | 175 / 175 | 100% |
| Common `p*` | 55 / 55 | 100% |
| Rinko `k*` | 146 / 174 | 83.9% (48 community + 98 Gemini XML, not injected) |
| Nene `a*` | 146 / 174 | 83.9% (48 community + 98 Gemini, optional at Drop) |
| SMS (`maildic_*`, pkg 92) | 1822 / 1822 | 100% Gemini; still JP in the gold bake |
| Scripts + SMS rollup | 2344 / 2400 | 97.7% |
| Main TRB STRI | 24549 / 25370 | 96.8% (machine pass, unreviewed) |

NLPPATCH “28%” = 169 / 578 dialogue files. Reviewed coverage is that baseline plus Manaka, common, and 48 Nene / 48 Rinko. The rest of the 90.3% is Gemini.

**UI PNG masters (updated — community English pack, audited):**

| Measure | Count | Notes |
|---------|------:|-------|
| Full mapped pack (`IMAGE_MAP`) | **1765** unique PNGs in **101 / 101** folders | What gold bake packs. Deduped by stem; prefer `.check`. Recounted 2026-10-20 (was 1745 / 95). |
| Chrome subset (site `images_ui` today) | **564** in **25 / 25** folders | What `export_progress_metrics.py` → `ui_png_masters_total` currently exports. Was **562**, then **461**. |
| Sparse intros | `intro111`, `intro203`, `intro304` | Folders exist (11 / 5 / 3 PNGs). Not empty. |

These are **English masters present**, not “% of every vanilla BCLIM in `img.bin`”. Do not invent a texture %.

The `/progress/` UI table is driven by `images_ui.by_folder` (the chrome 25 keys). After a real import, `ui_png_masters_total` should read **564**, not 562 or 461. Optionally mention the full pack in prose:

> 564 English PNG masters in the 25 chrome packages the dashboard tracks (was 562). The shipping image map has **1765** unique masters across **all 101** folders. intro111 / intro203 / intro304 are sparse dumps, not missing folders.

Replace any volunteer/workbench copy that still says **~1210 PNGs / ~68 folders**, **1727 / 92 of 95**, or **1745 / 95 of 95** with **1765 / 101 of 101**.

**Do not treat as translation progress:**

- Resident TRB fragment % (JP date/time building blocks by design)
- `NLP_01` / `NLP_02` duplicate Manaka slots (excluded from the 578-file headline)
- Citra/Azahar custom texture packs

### Pages to touch

| Page | What to update |
|------|----------------|
| `/progress/` (`src/pages/progress.astro`) | Image blurb + optional milestone for the audited community UI PNG pack. After import, the table fills itself. |
| Homepage (`ProgressBar.astro`) | Comes from `progress.json`. A fresh export moves dialogue to **522 / 578** and SMS to **1822 / 1822** (Gemini, unreviewed). |
| Volunteer (`volunteer.astro` / workbench sizes) | Image kit size if it still quotes 1210 / 68. |
| Changelog / devlog | Optional: note that UI masters are **1765** mapped / **564** chrome (2026-10-20 recount). |

### Tone

Same as the current Progress page: numbers are regenerated from the patcher, dialogue+SMS are the bottleneck, TRB 98% is a machine pass. Do not claim menus are “done” because TRB is high. Do not claim every in-game texture is English because 1765 masters exist.

### Output

1. Exact edits (file + snippet) **or** confirmation that `import-progress.mjs` is enough for the bars.
2. Ready-to-paste Progress-page image paragraph using 564 + 1765.
3. A one-line volunteer Images kit size if that page still has the old ~1210 figure.

### Do not include

Ghidra addresses, zlib/img.bin splice notes, LayeredFS paths, bake recipes, name-input cave offsets, Azahar NX patches.
