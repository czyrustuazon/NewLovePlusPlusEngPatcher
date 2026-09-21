# NLPPPATCH baseline (~28%)

Community English scripts from the 2017 [LovePlusProject/NLPPPATCH](https://github.com/LovePlusProject/NLPPPATCH) release (**168/577** script IDs in their README).

## EngPatcher usage

Drop CIA injects the community layer from **`rebuild_dbin2/script/{a,k}*.dbin2`** (`assets/nlppatch/stems.json`). You do **not** need this vendor tree to patch.

- **Vendor path (re-import only):** `vendor/NLPPATCH/release/romfs/script/bin/script/*.dbin2` (~169 stems)
- **Integrate:** `tools/fetch_nlppatch_release.py` then `tools/integrate_nlppatch_into_rebuild.py`
- **Does not override** our `t*` / `p*` when both exist

Original NLPPPATCH GitHub releases may 404. Fallback: extract the script pack from [LovePlusProject/NLPPCTR](https://github.com/LovePlusProject/NLPPCTR) English patch.

## Coverage context

| Layer | Script pack EN |
|-------|----------------|
| NLPPPATCH alone | ~169 / 578 (~29%) |
| + Manaka 100% + common 100% | **326 / 578 (56.4%)** |

See `docs/TRANSLATION_PROGRESS.md` for SMS, TRB, and UI metrics.
