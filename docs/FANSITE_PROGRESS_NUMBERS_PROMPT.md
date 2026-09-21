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

### Facts you must use (2026-09-20)

**Dialogue / SMS / TRB (unchanged vs Sep 1 shipping stack unless a fresh export says otherwise):**

| Bucket | EN / total | % |
|--------|------------|---|
| Dialogue scripts (`script/*.dbin2`) | 326 / 578 | 56.4% |
| Manaka `t*` | 175 / 175 | 100% |
| Common `p*` | 55 / 55 | 100% |
| Rinko `k*` | 48 / 174 | 27.6% (NLPPATCH layer) |
| Nene `a*` | 48 / 174 | 27.6% (NLPPATCH layer) |
| SMS (`maildic_*`, pkg 92) | 0 / 1822 | 0% (JP in gold bake) |
| Scripts + SMS rollup | 326 / 2400 | 13.6% |
| Main TRB STRI | 24872 / 25346 | 98.1% (machine pass, unreviewed) |

NLPPATCH “28%” = 169 / 578 dialogue files. That is still only Rinko+Nene coverage. Current 56.4% = that baseline + finished Manaka + common.

**UI PNG masters (updated — community English pack, audited):**

| Measure | Count | Notes |
|---------|------:|-------|
| Full mapped pack (`IMAGE_MAP`) | **1745** unique PNGs in **95 / 95** folders | What gold bake packs. Deduped by stem; prefer `.check`. |
| Chrome subset (site `images_ui` today) | **562** in **25 / 25** folders | What `export_progress_metrics.py` → `ui_png_masters_total` currently exports. Was **461**. |
| Sparse intros | `intro111`, `intro203`, `intro304` | Folders exist (11 / 5 / 3 PNGs). Not empty. |

These are **English masters present**, not “% of every vanilla BCLIM in `img.bin`”. Do not invent a texture %.

The `/progress/` UI table is driven by `images_ui.by_folder` (the chrome 25 keys). After a real import, `ui_png_masters_total` should read **562**, not 461. Optionally mention the full pack in prose:

> 562 English PNG masters in the 25 chrome packages the dashboard tracks (was 461). The shipping image map has **1745** unique masters across **all 95** folders. intro111 / intro203 / intro304 are sparse dumps, not missing folders.

Replace any volunteer/workbench copy that still says **~1210 PNGs / ~68 folders** or **1727 / 92 of 95** with **1745 / 95 of 95**.

**Do not treat as translation progress:**

- Resident TRB fragment % (JP date/time building blocks by design)
- `NLP_01` / `NLP_02` duplicate Manaka slots (excluded from the 578-file headline)
- Citra/Azahar custom texture packs

### Pages to touch

| Page | What to update |
|------|----------------|
| `/progress/` (`src/pages/progress.astro`) | Image blurb + optional milestone for the audited community UI PNG pack. After import, the table fills itself. |
| Homepage (`ProgressBar.astro`) | Comes from `progress.json` — no hardcoded 461. Leave script/SMS/TRB bars unless export changed them. |
| Volunteer (`volunteer.astro` / workbench sizes) | Image kit size if it still quotes 1210 / 68. |
| Changelog / devlog | Optional: note that UI masters are **1745** mapped / **562** chrome after rc-3 → main. |

### Tone

Same as the current Progress page: numbers are regenerated from the patcher, dialogue+SMS are the bottleneck, TRB 98% is a machine pass. Do not claim menus are “done” because TRB is high. Do not claim every in-game texture is English because 1745 masters exist.

### Output

1. Exact edits (file + snippet) **or** confirmation that `import-progress.mjs` is enough for the bars.
2. Ready-to-paste Progress-page image paragraph using 562 + 1745.
3. A one-line volunteer Images kit size if that page still has the old ~1210 figure.

### Do not include

Ghidra addresses, zlib/img.bin splice notes, LayeredFS paths, bake recipes, name-input cave offsets, Azahar NX patches.
