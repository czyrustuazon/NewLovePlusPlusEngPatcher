# Tools used by the CIA patcher

## Present here

| Path | Source | Role |
|------|--------|------|
| `cia/` | Vendored [3dstool](https://github.com/dnasdw/3dstool) / [Project_CTR](https://github.com/3DSGuy/Project_CTR) / `seeddb.bin` (see `cia/CREDITS.md`) | Split/rebuild NCCH/RomFS, makerom CIA |
| `nlpp-tools/` | **[kiwiz/nlpp-tools](https://github.com/kiwiz/nlpp-tools)** (vendored) | `img.bin` / package / BCLIM helpers (`ie`, `pe`, `png2bclim`, …) |
| `mdcutil.py` | EngPatcher | SMS maildic MDC pack / unpack |
| `Trb2xlsx/` | [deaknaew/Trb2xlsx](https://github.com/deaknaew/Trb2xlsx) | `lookup.txt` codebook for `patch_textresource.py` |
| `NLPTextTool/` | [LovePlusProject/NLPTextTool](https://github.com/LovePlusProject/NLPTextTool) | XML ↔ `.dbin2` (needs .NET SDK to build) |
| `NLPUnpacker/` | [LovePlusProject/NLPUnpacker](https://github.com/LovePlusProject/NLPUnpacker) | Older `img.bin` unpacker (C#) |
| `../assets/fonts/MPLUS1p-Regular.ttf` | M PLUS 1p (SIL OFL) | UI glyph renders for deploy scripts |
| `spotpass/` + `build_spotpass_inject.py` | Archived NLPP SpotPass BOSS dump | Build `info.dat` inject for Azahar or real 3DS (`--real3ds` → `out/spotpass_real3ds/`) |

Full credit list: see root [`README.md`](../README.md#credits).

### SpotPass inject

```bash
python tools/build_spotpass_inject.py --real3ds    # CFW + FBI Ext Save Data
python tools/build_spotpass_inject.py --azahar     # emulator (HLE-padded)
```

Details: [`spotpass/README.md`](spotpass/README.md).

## Setup

```bash
python src/setup_tools.py
python src/setup_tools.py --offline   # no GitHub fallback
```

Verifies vendored `tools/cia/` bins and only downloads OSS CIA tools if
something is missing (skipped with `--offline`). **Decrypt your ROM yourself** —
this repo does not ship `decrypt.exe`.

## Notes on Makein/NLPPGit

[Makein/NLPPGit](https://github.com/Makein/NLPPGit) is a **translation asset** repo (XML scripts + UI art). Releases are LayeredFS overlays, not a CIA rebuild toolchain.

`nlpp-tools` originates from **[kiwiz/nlpp-tools](https://github.com/kiwiz/nlpp-tools)**. The packing stack listed by [LovePlusProject/NLPPATCH](https://github.com/LovePlusProject/NLPPATCH) also includes NLPTextTool, nlpp-tools, NLPUnpacker, png2texi, trb2xlsx, nlpp-fmt.

## Image packing notes

- In-tree `opt/bin/darctool` is a **Linux ELF**; Windows packing uses `darcutil.py` instead.
- `png2bclim.exe` often expands compressed BCLIM formats (size grows) — DARC rebuild handles that.
- `pack_images.py` does selective `img.bin` rewrite (only patched package indices).


## Optional local clones / one-off imports (not required for Drop CIA)

| Path / script | Source | Note |
|------|--------|------|
| `NLPTextTool/` | [LovePlusProject/NLPTextTool](https://github.com/LovePlusProject/NLPTextTool) | Rebuild `assets/scripts/*.xml` → `.dbin2` offline; patch pipeline injects pre-built `rebuild_dbin2/` |
| `NLPUnpacker/` | [LovePlusProject/NLPUnpacker](https://github.com/LovePlusProject/NLPUnpacker) | Legacy img.bin unpacker; superseded by `nlpp-tools` `ie`/`pe` |
| `import_nlppctr_textures.py` | uses [LovePlusProject/NLPPCTR](https://github.com/LovePlusProject/NLPPCTR) | Dev-only texture import / A/B compare (`ab_test/`) |
| `import_ui_buttons_bundle.py` | `NLPP_English_UI_Buttons_only.zip` | Copy keyboard/SysPopup/Back/Album PNGs → `assets/images/*.check/timg/` |
| `deploy_ui_buttons_en.py` | EngPatcher | Pack imported UI Buttons (pkg 5190/5259/5380/4149) |
| `src/deploy_nlppatch_scripts.py` | optional `vendor/NLPPATCH/` | LayeredFS deploy of community baseline scripts |
