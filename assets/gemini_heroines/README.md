# Gemini heroine translations

Tracked archive of paid Gemini Nene/Rinko runs. Default output for `tools/translate_heroines_gemini.py`.

| File | Role |
|------|------|
| `xml/a*.xml` | Translated Nene scripts (NLPTextTool XML) |
| `dbin2/{NLP_01,NLP_02,script}/a*.dbin2` | Prebuilt inject binaries (from the XML) |
| `stems.json` | Allowlist of Gemini Nene stems |
| `translations.json` | JP→EN map used to resume a run |
| `jobs.json` | Pending-line list from `collect` / `run` |
| `proofread.json` | Stems a human has reviewed (empty = all Gemini XML is teal / unreviewed) |

## Optional Drop CIA inject

Default Drop CIA keeps the community ~28% Nene/Rinko layer (`assets/nlppatch/stems.json` → `rebuild_dbin2/script`).

To also ship this Gemini machine pass (Nene `a*` scripts, Rinko `k*` scripts, and SMS `maildic_{m,n,r}`, **unreviewed**):

- Answer **y** when Drop asks after the gold-bake question, or
- Set `NLPP_INCLUDE_GEMINI_NENE=1`, or
- Pass `python src/patch_cia.py … --include-gemini-nene`

That injects `dbin2/` into every matching pack via `src/script_inject.py`, and splices SMS into a copy of `img.bin`. It does **not** overwrite the community binaries under `rebuild_dbin2/` or the files in this folder.

A human review of one of these stems is not written back into this folder. `tools/ingest_pack.py` puts it in `assets/script_contrib/`, and the patcher includes that file on its own, ahead of Gemini. A reviewed SMS dictionary in `assets/sms_contrib/maildic_{m,n,r}.en.xml` likewise replaces that heroine's Gemini SMS without editing `sms/`. Gemini stays optional for every stem that has no contributor file.

Rebuild from XML (maintainer):

```bash
python tools/rebuild_dbin2_from_xml.py --glob "a*.xml" --xml-dir assets/gemini_heroines/xml
```

Nene and Rinko stay a **machine pass** until a stem is listed in `proofread.json`. Phone text is `sms/maildic_{m,n,r}.en.xml` and ships with the same Drop yes.
