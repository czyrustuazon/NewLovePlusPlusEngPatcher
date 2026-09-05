# NLPPPATCH baseline (~28%)

Community English scripts from the 2017 [LovePlusProject/NLPPPATCH](https://github.com/LovePlusProject/NLPPPATCH) release (**168/577** script IDs in their README).

## EngPatcher usage

- **Vendor path:** `vendor/NLPPPATCH/release/romfs/script/bin/script/*.dbin2` (~169 stems)
- **Inject:** `src/script_inject.py` — used after Manaka `t*` and common `p*` from `rebuild_dbin2/`
- **Does not override** our `t*` / `p*` when both exist

Original NLPPPATCH GitHub releases may 404. Fallback: extract the script pack from [LovePlusProject/NLPPCTR](https://github.com/LovePlusProject/NLPPCTR) English patch.

## Coverage context

| Layer | Script pack EN |
|-------|----------------|
| NLPPPATCH alone | ~169 / 578 (~29%) |
| + Manaka 100% + common 100% | **326 / 578 (56.4%)** |

See `docs/TRANSLATION_PROGRESS.md` for SMS, TRB, and UI metrics.
