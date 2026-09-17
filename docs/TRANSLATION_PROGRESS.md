# Translation progress metrics (fansite / status page)

Regenerate before publishing — numbers drift when scripts, SMS, TRB, or UI assets change.

```bash
python tools/export_progress_metrics.py --json out/progress_metrics.json
python tools/script_coverage_report.py          # console summary
python src/patcher.py status                    # XML + inject overview
```

Machine-readable export (all file names): `out/progress_metrics.json` (~1 MB, gitignored).

Fansite import: `docs/FANSITE_PROGRESS_NUMBERS_PROMPT.md`. Volunteer kit copy: `docs/VOLUNTEER_WORKBENCH_PAGE_PROMPT.md`.

---

## Headline numbers (2026-09-16 shipping stack)

| Bucket | EN / total | % | Notes |
|--------|------------|---|--------|
| **Dialogue scripts** (`script` pack) | 424 / 578 | **73.4%** | One `.dbin2` per script ID |
| **SMS / phone** (`maildic_*.mdc`) | 0 / 1822 | **0%** | JP in gold bake (audit) |
| **Scripts + SMS combined** | 424 / 2400 | **17.7%** | Use for “all spoken + phone text” rollup (Gemini Nene is unreviewed) |
| **Main TRB** (`textresource_jpn.trb`) | 24872 / 25346 STRI | **98.1%** | Machine pass, unreviewed |
| **UI PNG masters** (chrome, site `images_ui`) | **562** in **25 / 25** folders | — | `ui_png_masters_total` (was 461) |
| **UI PNG masters** (full `IMAGE_MAP`) | **1727** in **92 / 95** folders | — | What gold bake packs. Empty: `intro111`, `intro203`, `intro304` |

PNG counts are **English masters present** (deduped by stem under `assets/images/`, prefer `.check`). Not a percent of every BCLIM in vanilla `img.bin`. Do not blend TRB 98% into a single “translation done” headline.

Legacy **NLPPPATCH “28%”** = **169 / 578** script files (~29%) **alone**. The combined patch is higher because Manaka (`t*`) and common (`p*`) are 100%.

---

## Per-route dialogue (`rebuild_dbin2/script/*.dbin2`)

| Route | Prefix | EN / total | % | Layer |
|-------|--------|------------|---|--------|
| Manaka | `t*` | 175 / 175 | 100% | `rebuild_dbin2/` |
| Common | `p*` | 55 / 55 | 100% | `rebuild_dbin2/` |
| Rinko | `k*` | 48 / 174 | 27.6% | community `rebuild_dbin2/script/k*.dbin2` |
| Nene | `a*` | 146 / 174 | 83.9% | Gemini XML → `rebuild_dbin2/` (`a936` still community-only). **145 files are a machine pass, unreviewed** (teal on the fansite). |

**Not injected from XML:** Rinko (`k*`) — community binaries in `rebuild_dbin2` / JP ROM until promoted. (`scripts_deferred/` removed 2026-09-03.)

**Inject policy:** `src/script_inject.py` → `resolve_script_source()` (used by `patch_cia.py`).

---

## SMS / phone text (`img.bin` package **92**)

| Heroine | File | Messages | EN (bake) |
|---------|------|----------|-----------|
| Manaka | `maildic_m.mdc` | 599 | 0 |
| Nene | `maildic_n.mdc` | 634 | 0 |
| Rinko | `maildic_r.mdc` | 589 | 0 |

- **Deploy EN:** `tools/deploy_sms_maildic_en.py` (needs `assets/sms_en/maildic_{m,n,r}.en.xml`)
- **Restore JP:** `tools/restore_sms_maildic_jpn.py`
- **Gold bake:** SMS **off** unless `rebuild_bake_img.py --include-sms`

---

## TRB

| File | Role |
|------|------|
| `release/textresource/textresource_jpn.trb` | Main STRI table (98%+ EN) |
| `assets/textresource/translations.json` | 24k+ JP→EN keys (rebuild source) |
| `release/romfs_overlay/.../textresource_resident_jpn.trb` | Date/time + name fragments (`patch_names.py`) |

Per-category STRI bars: `progress_metrics.json` → `trb_main.by_indx_category` (`cat_000` …).

---

## UI images

- **Gold:** `release/bake_img.bin`
- **Masters:** `assets/images/<Folder>.check/timg/<stem>.png`
- **Map:** `src/image_map.py` (folder key → package index + `.arc` name)
- **NLPPCTR import:** `tools/import_nlppctr_textures.py` + `ab_test/` A/B
- **UI Buttons bundle:** `tools/import_ui_buttons_bundle.py` → pkgs 5190 / 5259 / 5380 / 4149

Chrome folder list: `progress_metrics.json` → `images_ui.ui_folder_keys` (25 keys). Full PNG lists: `images_ui.by_folder.<key>.png_files`. Mapped totals: `mapped_png_masters_total` / `mapped_folders_with_png` / `empty_image_map_keys`.

---

## Fansite layout (suggested)

1. **Main game** — horizontal bars: Manaka, Rinko, Nene, Common, Total (script pack)
2. **Phone / SMS** — separate panel: `maildic_m` / `maildic_n` / `maildic_r`
3. **Rollup** — scripts + SMS message count (17.7% today; Gemini Nene unreviewed)
4. **System strings** — TRB 98.1% (+ optional INDX category drill-down)
5. **UI textures** — chrome table from `images_ui.by_folder` (**562**); prose may also mention the full mapped pack (**1727** in **92 of 95**)

### Review caveat (yellow / teal bars)

The homepage already paints TRB as `statbar teal` with note **machine pass, unreviewed**. Dialogue Gemini Nene uses the same contract in `progress_metrics.json`:

| JSON field | Meaning | Site |
|------------|---------|------|
| `review_status` | `reviewed` / `machine_unreviewed` / `mixed` | rose vs teal |
| `caveat` | `"machine pass, unreviewed"` | bar note |
| `bar` | `rose` or `teal` | StatBar class |
| `fills` | stacked `{kind,count,percent,bar,note}` | pink reviewed + yellow MT |
| `english_reviewed` / `english_unreviewed` | file counts | stacked widths |
| per-file `review` | same enums | file table |

Gemini stems come from `assets/gemini_heroines/xml/`. After proofreading, add the stem to `assets/gemini_heroines/proofread.json` so it counts as rose.

Importer: `node scripts/import-progress.mjs` — if a route or fill has `bar: "teal"` / `caveat` set, use the teal StatBar (same as System & menu text).

Do **not** show resident TRB fragment % as “translation progress” (mostly JP date/time building blocks by design).
