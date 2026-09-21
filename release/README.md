# Release artifacts (gold)

This folder holds **patch-critical** build products the CIA path consumes.
Unlike `out/` (wipeable scratch) and `cache/` (optional PNG pack), treat these as the durable source of truth.

| Path | Role |
|------|------|
| `bake_img.bin` | Gold English `img.bin` (PNG pack + deploy chrome + day-counter; SMS **off** unless `--include-sms`) |
| `bake_stamp.txt` | `PATCHER_RELEASE` + UI PNG fingerprint; Drop ignores leftover bake on mismatch |
| `name_input_code.bin` | Profile name-input ExeFS stack (romaji + Message Speed + title-loop guard); bake **always** rebuilds this; Drop injects it |
| `romfs_overlay/` | RomFS files auto-injected by `patch_cia` (TRBs under `SystemData/TextResource/`) |
| `textresource/` | Regenerated TRBs / working copies (from `assets/textresource/translations.json`) |

Large binaries are gitignored. Translation **source** lives in:

`assets/textresource/translations.json`

This tree on **main** is still stamped **`v1.0.0-rc3`** (`PATCHER_RELEASE` / Eng Patch badge / `CIA_TITLE_VERSION` **3**) until the next bump.

Regenerate everything (also auto-run by the drop bat when bake is missing or the stamp mismatches):

```bash
python tools/rebuild_bake_img.py
python tools/rebuild_bake_img.py --rom path\to\game.cia
python tools/rebuild_bake_img.py --rom path\to\game.3ds
```

Vanilla `img.bin` comes from (first match): `NLPP_VANILLA_IMG`, sibling `New Love Plus Plus/extracted/`, `cache/vanilla_from_rom/` (auto-filled from `--rom`), or the dropped ROM when the bat auto-rebuilds.

A cold PNG pack is typically **under an hour** on a multi-core desktop (measured **~27 min** on a high-thread machine; historically ~16h sequential zopfli — see `technical.md` §12.5.3). Watch `[timer]` lines. A second full pack with unchanged assets reuses `cache/img_pack/` (BCLIM + exact-zlib slots) and is typically minutes. Wipe that dir or pass `--no-cache` to force re-encode.

**Handing off without the cold-pack wait:** push to EngPatcher **`main`** → **nlpp-gold-maker** Ubuntu CI uploads `bake_img.bin` + `romfs_overlay.zip` to rolling Release tag **`gold`** (`infra/README.md`). Recipients:

```bash
python tools/fetch_release_bake.py --repo OWNER/nlpp-gold-maker --tag gold
```

then drop their CIA on the bat (Windows). Safe to delete `bake_img.bin.bak_pre_*` sidecars before sharing.

**Progress metrics:** `python tools/export_progress_metrics.py` — see `docs/TRANSLATION_PROGRESS.md`.
