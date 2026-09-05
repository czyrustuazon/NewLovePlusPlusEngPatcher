# Release artifacts (gold)

This folder holds **patch-critical** build products the CIA path consumes.
Unlike `out/` (wipeable scratch) and `cache/` (optional PNG pack), treat these as the durable source of truth.

| Path | Role |
|------|------|
| `bake_img.bin` | Gold English `img.bin` (PNG pack + deploy chrome + day-counter; SMS **off** unless `--include-sms`) |
| `name_input_code.bin` | Profile name-input ExeFS stack (romaji + direct insert); drop-bat `--inject-code` |
| `romfs_overlay/` | RomFS files auto-injected by `patch_cia` (TRBs under `SystemData/TextResource/`) |
| `textresource/` | Regenerated TRBs / working copies (from `assets/textresource/translations.json`) |

Large binaries are gitignored. Translation **source** lives in:

`assets/textresource/translations.json`

Regenerate everything (also auto-run by the drop bat when bake is missing):

```bash
python tools/rebuild_bake_img.py
python tools/rebuild_bake_img.py --rom path\to\game.cia
python tools/rebuild_bake_img.py --rom path\to\game.3ds
```

Vanilla `img.bin` comes from (first match): `NLPP_VANILLA_IMG`, sibling `New Love Plus Plus/extracted/`, `cache/vanilla_from_rom/` (auto-filled from `--rom`), or the dropped ROM when the bat auto-rebuilds.
First full rebuild often takes **~16 hours** (CPU-bound PNG pack / exact-zlib).
A second full pack with unchanged assets reuses ``cache/img_pack/`` (BCLIM + exact-zlib
slots) and is typically minutes. Wipe that dir or pass ``--no-cache`` to force re-encode.

**Handing off without the 16h wait:** the **nlpp-gold** repo’s Ubuntu self-hosted CI
uploads `bake_img.bin` + `romfs_overlay.zip` to GitHub Releases on tags `v*` (see
`infra/` pointer + nlpp-gold docs), or zip those with a clone. Recipients:

```bash
python tools/fetch_release_bake.py --repo OWNER/nlpp-gold
```

then drop their CIA on the bat (Windows). Safe to delete `bake_img.bin.bak_pre_*`
sidecars before sharing.

**Progress metrics:** `python tools/export_progress_metrics.py` — see `docs/TRANSLATION_PROGRESS.md`.
