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

## Headline numbers (2026-10-23)

| Bucket | EN / total | % | Notes |
|--------|------------|---|--------|
| **Dialogue scripts** (`script` pack) | 522 / 578 | **90.3%** | Community layer + Gemini machine pass. 56 files are empty retail stubs |
| **SMS / phone** (`maildic_*.mdc`) | 1822 / 1822 | **100%** | Gemini machine pass. Still JP in the gold bake until `--include-sms` |
| **Scripts + SMS combined** | 2344 / 2400 | **97.7%** | Spoken files + phone messages. Gemini rows are unreviewed |
| **Main TRB** (`textresource_jpn.trb`) | 24549 / 25370 STRI | **96.8%** | Machine pass, unreviewed |
| **UI PNG masters** (chrome, site `images_ui`) | **564** in **25 / 25** folders | — | `ui_png_masters_total` (was 562 on 2026-09-20, 461 before that) |
| **UI PNG masters** (full `IMAGE_MAP`) | **1765** in **101 / 101** folders | — | What gold bake packs. `intro111` / `intro203` / `intro304` are sparse, not empty |

PNG counts are **English masters present** (deduped by stem under `assets/images/`, prefer `.check`). Not a percent of every BCLIM in vanilla `img.bin`. Do not blend TRB 98% into a single “translation done” headline.

Legacy **NLPPPATCH “28%”** = **169 / 578** script files (~29%) **alone**. Reviewed coverage on top of that is Manaka and common at 100% plus 48 Nene and 48 Rinko. The Gemini rows below are a machine pass, not proofread.

---

## Per-route dialogue (`rebuild_dbin2/script/*.dbin2`)

| Route | Prefix | EN / total | % | Layer |
|-------|--------|------------|---|--------|
| Manaka | `t*` | 175 / 175 | 100% | `rebuild_dbin2/` |
| Common | `p*` | 55 / 55 | 100% | `rebuild_dbin2/` |
| Rinko | `k*` | 146 / 174 | 83.9% | 48 community + 98 Gemini XML (`assets/gemini_heroines/xml/`). 28 empty stubs |
| Nene | `a*` | 146 / 174 | 83.9% | 48 community + 98 Gemini dbin2. Optional Drop inject. 28 empty stubs |

**Inject:** community Nene/Rinko always. Gemini Nene only when Drop opts in (`NLPP_INCLUDE_GEMINI_NENE=1`). Gemini Rinko XML is archived and not injected yet. (`scripts_deferred/` removed 2026-09-03.)

**Inject policy:** `src/script_inject.py` → `resolve_script_source()` (used by `patch_cia.py`).

---

## SMS / phone text (`img.bin` package **92**)

| Heroine | File | Messages | EN (Gemini, unreviewed) | EN (bake) |
|---------|------|----------|--------------------------|------------|
| Manaka | `maildic_m.mdc` | 599 | 599 | 0 |
| Nene | `maildic_n.mdc` | 634 | 634 | 0 |
| Rinko | `maildic_r.mdc` | 589 | 589 | 0 |

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

Chrome folder list: `progress_metrics.json` → `images_ui.ui_folder_keys` (25 keys). Full PNG lists: `images_ui.by_folder.<key>.png_files`. Mapped totals: `mapped_png_masters_total` / `mapped_folders_with_png` / `empty_image_map_keys` (now none).

---

## Fansite layout (suggested)

1. **Main game** — horizontal bars: Manaka, Rinko, Nene, Common, Total (script pack)
2. **Phone / SMS** — separate panel: `maildic_m` / `maildic_n` / `maildic_r`
3. **Rollup** — scripts + SMS message count (97.7% today; Gemini segments stay unreviewed)
4. **System strings** — TRB 96.8% (+ optional INDX category drill-down)
5. **UI textures** — chrome table from `images_ui.by_folder` (**564**); prose may also mention the full mapped pack (**1765** in **101 of 101**)

Do **not** show resident TRB fragment % as “translation progress” (mostly JP date/time building blocks by design).
