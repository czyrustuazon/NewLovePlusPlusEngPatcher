# Community script layer (ex-NLPPATCH)

The old ~28% community English scripts live **inside** EngPatcher now:

- Binaries: `rebuild_dbin2/script/{a,k}*.dbin2` (stems listed in `stems.json`)
- Inject: `src/script_inject.py` (Manaka `t*` + common `p*` override; then these)

You do **not** need `vendor/NLPPATCH` or a network fetch to Drop a CIA.

Re-import from an offline dump / NLPPCTR (maintainer only):

```bash
python tools/fetch_nlppatch_release.py          # optional hydrate to vendor/
python tools/integrate_nlppatch_into_rebuild.py
```

Credits: LovePlusProject/NLPPATCH contributors (see their repo credits).
