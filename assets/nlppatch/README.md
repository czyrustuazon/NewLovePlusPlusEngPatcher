# Community + promoted heroine scripts

English `a*` / `k*` that Drop CIA injects live **inside** EngPatcher:

- Binaries: `rebuild_dbin2/{NLP_01,NLP_02,script}/{a,k}*.dbin2` (stems listed in `stems.json`)
- Inject: `src/script_inject.py` (Manaka `t*` + common `p*` override; then these)
- Nene `a*`: Gemini XML in `assets/scripts/` rebuilt with `tools/rebuild_dbin2_from_xml.py` — **machine pass, not proofread** (not a finished route)
- Rinko `k*`: still the historical NLPPATCH-era community layer

You do **not** need `vendor/NLPPATCH` or a network fetch to Drop a CIA.

Re-import Rinko / overlap from an offline dump / NLPPCTR (maintainer only):

```bash
python tools/fetch_nlppatch_release.py          # optional hydrate to vendor/
python tools/integrate_nlppatch_into_rebuild.py
```

`integrate_nlppatch_into_rebuild.py` copies community binaries only. Do not use it to overwrite Gemini Nene `a*` after a promote.

Credits: LovePlusProject/NLPPATCH contributors (see their repo credits); Nene remainder from the Gemini heroine pipeline.
