# SMS maildic (disabled in gold bake)

English SMS bodies are **not** deployed by default (nickname / placeholder audit).

| Heroine | MDC file | Messages (vanilla count) |
|---------|----------|--------------------------|
| Manaka | `maildic_m.mdc` | 599 |
| Nene | `maildic_n.mdc` | 634 |
| Rinko | `maildic_r.mdc` | 589 |

**Storage:** `img.bin` package **92** (not `romfs/dictionary/all2_u.bin`).

- **Restore Japanese** in a live `img.bin`:  
  `python tools/restore_sms_maildic_jpn.py --all-targets`
- **Re-enable EN later**: `tools/translate_sms_en.py` → `assets/sms_en/maildic_{m,n,r}.en.xml` →  
  `python tools/rebuild_bake_img.py --include-sms` (or `deploy_sms_maildic_en.py`)

Progress export includes per-message lists: `python tools/export_progress_metrics.py`.
