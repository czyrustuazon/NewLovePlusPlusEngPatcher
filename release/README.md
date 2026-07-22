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
python tools/rebuild_bake_img.py --rom path\to\game.cia
python tools/rebuild_bake_img.py --rom path\to\game.3ds
```

Vanilla `img.bin` comes from (first match): `NLPP_VANILLA_IMG`, sibling `New Love Plus Plus/extracted/`, `cache/vanilla_from_rom/` (auto-filled from `--rom`), or the dropped ROM when the bat auto-rebuilds.
First full rebuild often takes **~16 hours** (CPU-bound PNG pack / exact-zlib).
