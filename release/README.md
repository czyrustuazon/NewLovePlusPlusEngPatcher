# Release artifacts (gold)

This folder holds **patch-critical** build products the CIA path consumes.
Unlike `out/` (wipeable scratch) and `cache/` (optional PNG pack), treat these as the durable source of truth.

| Path | Role |
|------|------|
| `bake_img.bin` | Gold English `img.bin` (PNG pack + deploy chrome + SMS/day-counter) |
| `romfs_overlay/` | RomFS files auto-injected by `patch_cia` (TRBs under `SystemData/TextResource/`) |
| `textresource/` | Regenerated TRBs / working copies (from `assets/textresource/translations.json`) |

Large binaries are gitignored. Translation **source** lives in:

`assets/textresource/translations.json`

Regenerate everything (also auto-run by the drop bat when bake is missing):

```bash
python tools/rebuild_bake_img.py
```

Requires vanilla dump at sibling `New Love Plus Plus/extracted/` (or `NLPP_VANILLA_IMG` / `NLPP_VANILLA_TRB`).
