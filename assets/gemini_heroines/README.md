# Gemini heroine translations

Tracked archive of paid Gemini Nene/Rinko runs. Default output for `tools/translate_heroines_gemini.py`.

| File | Role |
|------|------|
| `xml/a*.xml` | Translated Nene scripts (NLPTextTool XML) |
| `translations.json` | JP→EN map used to resume a run |
| `jobs.json` | Pending-line list from `collect` / `run` |
| `rejected.json` | Marker-drop / empty-model failures |

Gold inject still uses copies under `assets/scripts/` → `rebuild_dbin2/` (allowlist `assets/nlppatch/stems.json`). Copy XML into `assets/scripts/` with `--write-xml`, then rebuild:

```bash
python tools/rebuild_dbin2_from_xml.py --glob "a*.xml"
python tools/rebuild_dbin2_from_xml.py --glob "k*.xml"
```

Nene `a*` from the 2026-09-13 run is already promoted. Rinko `k*` is not.
