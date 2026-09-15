# Gemini heroine translations

Tracked archive of paid Gemini Nene/Rinko runs. Default output for `tools/translate_heroines_gemini.py`.

| File | Role |
|------|------|
| `xml/a*.xml` | Translated Nene scripts (NLPTextTool XML) |
| `translations.json` | JP→EN map used to resume a run |
| `jobs.json` | Pending-line list from `collect` / `run` |
| `proofread.json` | Stems a human has reviewed (empty = all Gemini XML is teal / unreviewed) |

Gold inject still uses copies under `assets/scripts/` → `rebuild_dbin2/` (allowlist `assets/nlppatch/stems.json`). Copy XML into `assets/scripts/` with `--write-xml`, then rebuild:

```bash
python tools/rebuild_dbin2_from_xml.py --glob "a*.xml"
python tools/rebuild_dbin2_from_xml.py --glob "k*.xml"
```

Nene `a*` from the 2026-09-13 run is already promoted. It is a **machine pass** until a stem is listed in `proofread.json` — fansite bars should use teal / “machine pass, unreviewed” (same as TRB). Rinko `k*` is not in this archive.
