# Translation progress metrics (fansite / status page)

Regenerate before publishing — numbers drift when scripts, SMS, TRB, or UI assets change.

```bash
python tools/export_progress_metrics.py --json out/progress_metrics.json
python tools/script_coverage_report.py          # console summary
python src/patcher.py status                    # XML + inject overview
```

Machine-readable export (all file names): `out/progress_metrics.json` (~1 MB, gitignored).

---

## Headline numbers (2026-09-01 shipping stack)

| Bucket | EN / total | % | Notes |
|--------|------------|---|--------|
| **Dialogue scripts** (`script` pack) | 326 / 578 | **56.4%** | One `.dbin2` per script ID |
| **SMS / phone** (`maildic_*.mdc`) | 0 / 1822 | **0%** | JP in gold bake (audit) |
| **Scripts + SMS combined** | 326 / 2400 | **13.6%** | Use for “all spoken + phone text” rollup |
| **Main TRB** (`textresource_jpn.trb`) | 24872 / 25346 STRI | **98.1%** | Menus, stats, quests, system strings |
| **UI PNG masters** (chrome folders) | 461 files | — | See `images_ui` in JSON; not % of all BCLIMs yet |

Legacy **NLPPPATCH “28%”** = **169 / 578** script files (~29%) **alone**. The combined patch is higher because Manaka (`t*`) and common (`p*`) are 100%.

---

## Per-route dialogue (`rebuild_dbin2/script/*.dbin2`)

| Route | Prefix | EN / total | % | Layer |
|-------|--------|------------|---|--------|
| Manaka | `t*` | 175 / 175 | 100% | `rebuild_dbin2/` |
| Common | `p*` | 55 / 55 | 100% | `rebuild_dbin2/` |
| Rinko | `k*` | 48 / 174 | 27.6% | `vendor/NLPPPATCH/.../*.dbin2` |
| Nene | `a*` | 48 / 174 | 27.6% | `vendor/NLPPPATCH/.../*.dbin2` |

**Not injected from XML:** Rinko/Nene — NLPPATCH / JP ROM until promoted. (`scripts_deferred/` removed 2026-09-03.)

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

Full PNG lists: `progress_metrics.json` → `images_ui.by_folder.<key>.png_files`.

---

## Fansite layout (suggested)

1. **Main game** — horizontal bars: Manaka, Rinko, Nene, Common, Total (script pack)
2. **Phone / SMS** — separate panel: `maildic_m` / `maildic_n` / `maildic_r`
3. **Rollup** — scripts + SMS message count (13.6% today)
4. **System strings** — TRB 98.1% (+ optional INDX category drill-down)
5. **UI textures** — per-folder PNG master counts (461 total)

Do **not** show resident TRB fragment % as “translation progress” (mostly JP date/time building blocks by design).
