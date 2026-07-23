# NewLovePlusPlusEngPatcher

One-click English patcher for **New Love Plus+** (3DS), plus the finished translation assets it ships.

Translation work-in-progress lives elsewhere ([Makein/NLPPGit](https://github.com/Makein/NLPPGit), localization project). This repo holds **completed** scripts/images and a toolchain that turns an official **CIA or .3ds/.cci** dump into a playable English **CIA**.

**License:** EngPatcher original work is [MIT](LICENSE) for the community. That license covers **only** this project’s own code and assets — not third-party tools, fonts, or vendored trees (see [Credits](#credits) and `LICENSE`).

---

## What it can do

Drop in a known dump (`.cia` or encrypted/decrypted `.3ds` / `.cci`) and it will:

1. **Verify** the dump (SHA-1) before touching anything  
2. **Decrypt** if needed (CIA or cartridge NCCH via Batch Decryptor tools)  
3. **Inject English scripts** (pre-packed `.dbin2` from finished XML)  
4. **English heroine names** — rewrite dialog tokens (`▲高嶺＊＊▲` → `Takane`, etc.) and patch UI name tables in `textresource_resident_jpn.trb` / `img.bin`  
5. **Optionally patch `code.bin`** — single-pane player-name draw so roman letters aren’t one-glyph-per-box (`--patch-code`)  
6. **Inject gold UI** from `release/bake_img.bin` when present (PNG pack + menu chrome + CESA + SMS/day-counter)  
7. **Apply TRB overlay** from `release/romfs_overlay/` when present  
8. **Rebuild** a decrypted **CIA** for FBI / Azahar / Citra (even when the input was `.3ds`)  
9. **Clean up** the scratch work dir afterward (keeps the finished CIA; pass `--keep-work` / `--layeredfs-out` if you also want those)

| Included assets | Approx. count |
|-----------------|--------------:|
| Finished dialog scripts (XML → `.dbin2`) | 480 scripts → 1644 `.dbin2` across `NLP_01` / `NLP_02` / `script` |
| Finished UI PNGs | ~2574 |
| UI packages patched into `img.bin` (last pack) | 49 packages / ~1190 textures applied |

Title ID: `00040000000F4E00`

---

## Quick start (drag and drop)

1. Double-click **`Drop CIA or 3DS Here to Patch.bat`**
2. Drop your `.cia` / `.3ds` / `.cci` on the window (or use Browse → Patch)  
   — or drag the file directly onto the `.bat`

With a ready gold bake (`release/bake_img.bin` + overlay), patching usually finishes in **a few minutes**.

### Sharing a build (skip the 16-hour bake)

`release/bake_img.bin` is **gitignored** (too large for GitHub). Assets under `assets/` **are** in the repo.

To let someone else patch without rebuilding gold:

1. Clone / zip this repo (includes `assets/`, scripts, tools).  
2. Also give them your finished **`release/`** pack:
   - `release/bake_img.bin` — English UI bake  
   - `release/romfs_overlay/` — TRB overlay  
   - `release/textresource/` — optional but useful  
3. They supply **their own** matching dump and run the drop bat.

Do **not** ship the game dump, `cache/`, `out/`, or `*.bak_pre_*` sidecars.

### First-time gold bake (only if `release/bake_img.bin` is missing)

If bake is absent, the drop bat auto-runs:

```bash
python tools/rebuild_bake_img.py --rom path\to\game.cia   # or .3ds / .cci
```

That regenerates bake + TRBs from sources. **Often ~16 hours** (CPU-bound PNG pack / exact-zlib). Progress lines mean it is still working.

- Vanilla `img.bin` is taken from the dropped ROM when sibling `extracted/` is missing (`cache/vanilla_from_rom/`).  
- Resume after pack finishes: `python tools/rebuild_bake_img.py --skip-pack` (from **repo root**).  
- Scripts-only CIA (no UI inject): `set NLPP_WITH_IMAGES=0`.

Details / pitfalls: `technical.md` §15, `release/README.md`.

### Required dump

Only these known New Love Plus+ dumps are accepted (SHA-1):

```
a9fbd2e6d790b6cb6194f7820e1a71f597160f2b  # encrypted CIA
811d2f0f72c2a1437997256f30b18fbb2dea6cda  # decrypted CIA
6af1751f8b4f9d074311f3a7cf2b5d3c5e807cc8
d138d92fd9d522827cb9665bc2c954f1e8ba1f92  # decrypted full .3ds
6428e72eefec31d19282d2c7f0cb5082723a3206  # encrypted trim .3ds
```

Many other decrypted CIAs will fail the hash check (by design). The patcher decrypts encrypted dumps for you after verification. Use `--expect-sha1 <hash>` to require one specific dump, or `--skip-hash` to bypass (not recommended).

### Requirements

- Windows x64  
- Python 3.10+ (the drop bat finds `python`, `py -3`, or common install folders)  
- `pip install -r requirements.txt` (Pillow, numpy, zopfli, **etcpak** — drop-bat runs this)  
- A few GB free disk (RomFS rebuild is large)  
- First run auto-fetches OSS CIA tools (`3dstool`, `ctrtool`, `makerom`, `seeddb.bin`) and installs vendored `decrypt.exe`  
- `decrypt.exe` credit: [davidmorom](https://github.com/davidmorom) / [Batch CIA 3DS Decryptor Redux](https://github.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux) (`tools/Batch-CIA-3DS-Decryptor-Redux/`)  
- UI glyph font is bundled: `assets/fonts/MPLUS1p-Regular.ttf` (SIL OFL)  

If you see **Python not found**: install from [python.org](https://www.python.org/downloads/) with **Add python.exe to PATH** checked, open a **new** Command Prompt, and confirm `py -3 --version` works. Turning off Windows “App execution aliases” for `python.exe` only helps after a real install exists.

### Outputs

| Path | Description |
|------|-------------|
| `out/NewLovePlusPlus-EN.cia` | Patched **decrypted** CIA — install with FBI, or open in Azahar/Citra |
| `out/layeredfs/…` | Optional (`--layeredfs-out`); not written by the drop bat by default |
| `release/bake_img.bin` | Gold UI `img.bin` (preferred by drop-bat / `patch_cia`) |
| `release/romfs_overlay/` | Durable RomFS overlay (TRBs); auto-applied if present |
| `release/textresource/` | Durable TRB / translation work |
| `cache/new_img.bin` | Optional PNG-pack scratch (incomplete vs gold) |
| `cache/vanilla_from_rom/` | Vanilla RomFS extracted from a dropped ROM when needed |
| `out/cia_work/` | Scratch only — deleted after a successful CIA unless `--keep-work` |

**LayeredFS install**

- **Luma (3DS):** copy `00040000000F4E00` to `SD:/luma/titles/` and enable *Enable game patching*  
- **Azahar / Citra:** copy that folder into the emulator’s `load/mods/` directory  

Deploy scripts mirror into Azahar LayeredFS by default when that mod `img.bin` exists (`NLPP_ALSO_AZAHAR=0` to opt out). Fully quit Azahar after updating mods.

---

## Pipeline (what runs under the hood)

```
encrypted/decrypted .cia  OR  encrypted/decrypted .3ds/.cci
  → SHA-1 check
  → decrypt if needed (Batch CIA 3DS Decryptor tools)
       CIA  → decrypted CIA → content0 CXI
       .3ds → tmp.Main.ncch (CXI) [+ Manual]
       already-decrypted .3ds → 3dstool partition0/1
  → extract RomFS (3dstool)
  → inject rebuild_dbin2/*.dbin2 into script/bin/{NLP_01,NLP_02,script}/
  → name patches (plain Takane/Rinko/Nene in scripts + resident/img tables)
  → inject gold bake img.bin + romfs_overlay TRBs
  → rebuild RomFS → CXI → CIA (makerom, decrypted)
  → delete scratch work dir (keep finished CIA)
```

CLI example (cartridge dump → English CIA):

```bash
python src/patch_cia.py --cia "C:\path\to\00040000000F4E00_v00.3ds" --out out/NewLovePlusPlus-EN.cia
```

**Heroine names**

- Finished XML under `assets/scripts` uses plain **Takane** / **Rinko** / **Nene** (not `▲高嶺＊＊▲`).  
  Player tokens like `▲主人公＊▲` are unchanged.  
- At patch time, `src/patch_names.py` also rewrites any leftover tokens inside `.dbin2` and patches the resident TRB + `img.bin` name table.  
- Standalone:  
  `python src/patch_names.py --romfs path\to\romfs`  
  `python src/patch_names.py --xml assets/scripts`  
  `python src/patch_names.py --dbin rebuild_dbin2`  
- Skip with `--skip-name-patches`. For LayeredFS without a full UI pack but with the name table: `--name-img`.

**Player name UI (`code.bin`)**

- Opt-in: `--patch-code` rewrites `SetNameCharsToPanes` / clear / backspace so the whole name draws in one pane (max still 8).  
- Standalone: `python src/patch_code.py path\to\code.bin`  
- LayeredFS installs `code.bin` next to `romfs/` (Azahar/Luma ExeFS overlay).  
- CIA builds unpack/repack ExeFS via `3dstool`.

**Encryption notes**

- Input must be the hashed encrypted dump; decryption is automatic.  
- Output is a **decrypted** CIA (`Crypto Key: None`) — correct for CFW and emulators.  
- True retail NCCH re-encryption is **not** done here; use Decrypt9WIP *CIA Encryptor (NCCH)* on a console if you specifically need that.

**UI bake (gold `img.bin`)**

- Put translated UI PNGs under `assets/images`.  
- **Gold path:** `python tools/rebuild_bake_img.py` → `release/bake_img.bin`  
  PNG pack + main TRB from `assets/textresource/translations.json` + ordered `deploy_*` chrome (Options / menus / Confirm / Title main menu / CESA / …) + SMS + day-counter + overlay.  
- No sibling dump needed: pass `--rom game.cia|.3ds|.cci` (drop-bat does this automatically).  
- Drop-bat **auto-runs a full rebuild** if bake is missing, then patches the CIA.  
- Drop-bat / `patch_cia.py` **prefer `release/bake_img.bin`** when present.  
- **Expect about 16 hours** for a full bake rebuild. Progress lines mean it is still working.  
- Resume deploys only: `python tools/rebuild_bake_img.py --skip-pack`.  
- Optional PNG-only scratch: `cache/new_img.bin` via `pack_images` / `NLPP_REPACK_IMAGES=1` — incomplete vs gold; does not refresh bake.  
- Scripts-only: `set NLPP_WITH_IMAGES=0` or `--no-images`.  
- Parallel convert: `--workers` / `--image-workers`. Fine-tune opt-in: `--fine-tune` / `--image-fine-tune` (very slow).  
- Exact-length zlib for compressed ARCs: `src/exact_zlib.py` (see `technical.md` §12.5 / §15).  
- The drop bat does **not** mutate your RomFS dump in-place.

**Main Menu vs submenus**

| Screen | Package | Notes |
|--------|---------|--------|
| Main Menu **rows** (Game Start, Options, …) | **5261** `Title.arc` | `deploy_title_main_menu_en.py` |
| Gallery / Communication / Data Management homes | **5244 / 5241 / 5242** | `deploy_msel_menus_en.py` |
| Options chrome | **5245** | `deploy_msel_options_en.py` |
| Boot CESA warning | **90** | `deploy_cesa_en.py` (not auto PNG-pack) |
| “Main Menu” title string | TRB | Already EN via textresource |

---

## Credits

Thank you to everyone whose work this patcher builds on. Their materials keep **their own** licenses; the MIT grant in [`LICENSE`](LICENSE) is only for EngPatcher original work.

### CIA / RomFS tooling

| Component | Credit |
|-----------|--------|
| `3dstool` | [dnasdw/3dstool](https://github.com/dnasdw/3dstool) (auto-fetched by `setup_tools.py`) |
| `ctrtool` / `makerom` | [3DSGuy/Project_CTR](https://github.com/3DSGuy/Project_CTR) (auto-fetched) |
| `seeddb.bin` | [ihaveamac/3DS-rom-tools](https://github.com/ihaveamac/3DS-rom-tools) (auto-fetched) |
| `decrypt.exe` | [davidmorom](https://github.com/davidmorom); packaged in [xxmichibxx/Batch-CIA-3DS-Decryptor-Redux](https://github.com/xxmichibxx/Batch-CIA-3DS-Decryptor-Redux); original batch decryptor [matiffeder/3DS-stuff](https://github.com/matiffeder/3DS-stuff). Vendored at `tools/Batch-CIA-3DS-Decryptor-Redux/` — see `CREDITS.md` |

### Image packing / UI

| Component | Credit |
|-----------|--------|
| `nlpp-tools` (`ie`, `pe`, `png2bclim`, `png2texi`, …) | **[kiwiz/nlpp-tools](https://github.com/kiwiz/nlpp-tools)** — thank you to **kiwiz** |
| UI glyph font `MPLUS1p-Regular.ttf` | [M PLUS 1p](https://fonts.google.com/specimen/M+PLUS+1p) / [Coji / M+ FONTS](https://github.com/coz-m/MPLUS_FONTS), SIL OFL 1.1 (`assets/fonts/OFL.txt`) |
| Other fonts under `assets/fonts/` (Pixelify Sans, Press Start 2P, Silkscreen, VT323) | [Google Fonts](https://fonts.google.com/) / respective OFL authors (editor / optional assets) |

### Text / scripts / localization community

| Component | Credit |
|-----------|--------|
| NLPPATCH (scripts / TRB / code plugin; offline under `vendor/NLPPATCH/`) | [LovePlusProject/NLPPATCH](https://github.com/LovePlusProject/NLPPATCH) and contributors (see [their credits](https://github.com/LovePlusProject/NLPPATCH/issues/1)) |
| NLPTextTool (XML ↔ `.dbin2`) | [LovePlusProject/NLPTextTool](https://github.com/LovePlusProject/NLPTextTool) (orig. [gdkchan](https://github.com/gdkchan)) |
| NLPUnpacker | [LovePlusProject/NLPUnpacker](https://github.com/LovePlusProject/NLPUnpacker) (orig. [gdkchan](https://github.com/gdkchan)) |
| Translation asset repo (reference) | [Makein/NLPPGit](https://github.com/Makein/NLPPGit) |
| `Trb2xlsx` / `lookup.txt` (TRB character codebook) | [deaknaew/Trb2xlsx](https://github.com/deaknaew/Trb2xlsx) (vendored under `tools/Trb2xlsx/`) |

Deploy NLPPATCH dialogue with: `python src/deploy_nlppatch_scripts.py`.

Python packages used at runtime: [Pillow](https://python-pillow.org/), [NumPy](https://numpy.org/), [zopfli](https://github.com/google/zopfli) (`python-zopfli`), [etcpak](https://github.com/K0lb3/etcpak) (ETC1/ETC1A4 for BCLIM).

---

## Layout

```
Drop CIA or 3DS Here to Patch.bat   ← only user-facing entry point
README.md
technical.md                 RE notes + gold-bake retrospective (§15)
assets/
  scripts/                   finished DBIN2 XML
  images/                    finished UI PNGs (+ editor sources)
  textresource/              translations.json (source for main TRB rebuild)
  fonts/                     MPLUS1p + OFL (UI deploy glyph font)
src/
  patch_cia.py               CIA decrypt → inject → rebuild
  patch_names.py             heroine names (dbin2 / resident TRB / img.bin)
  patch_code.py              single-pane name draw (ExeFS code.bin)
  pack_images.py             PNG → img.bin
  exact_zlib.py              exact-length zlib/zopfli for ARC slots
  extract_vanilla_from_rom.py  vanilla img/TRB from dropped ROM
  darcutil.py / bclimutil.py / image_map.py
  setup_tools.py             fetch 3dstool + wire decryptor bins
  drop_zone.ps1              WinForms drop window
tools/
  rebuild_bake_img.py        regenerate bake + TRBs from sources
  deploy_*.py                chrome / Title / CESA / SMS / day-counter
  nlpp-tools/                vendored img.bin helpers (kiwiz/nlpp-tools)
  Batch-CIA-3DS-Decryptor-Redux/  vendored decrypt.exe + CREDITS
rebuild_dbin2/               finished English .dbin2 scripts
release/                     gold bake + TRB overlay (binaries gitignored; see release/README.md)
cache/                       PNG scratch + vanilla_from_rom (gitignored)
vendor/NLPPATCH/             offline NLPPATCH snapshot
out/                         wipeable scratch (gitignored)
```

Finished `.dbin2` scripts used at patch time live in `rebuild_dbin2/` (generated from `assets/scripts`).

---

## Advanced CLI

```bash
# Tool setup
python src/setup_tools.py

# Rebuild gold bake (from repo root)
python tools/rebuild_bake_img.py
python tools/rebuild_bake_img.py --rom path\to\game.cia
python tools/rebuild_bake_img.py --skip-pack          # resume after PNG pack

# Full CIA patch (prefers release/bake_img.bin; same as the .bat)
python src/patch_cia.py --cia "path\to\game.cia"

# Optional PNG-only scratch rebuild (does not refresh gold bake)
python src/patch_cia.py --cia "path\to\game.cia" --repack-images

# Scripts only (skip UI inject)
python src/patch_cia.py --cia "path\to\game.cia" --no-images

# LayeredFS only
python src/patch_cia.py --cia "path\to\game.cia" --layeredfs-only

# UI bank only
python src/pack_images.py
python src/pack_images.py --only title mail

# Skip SHA-1 (not recommended)
python src/patch_cia.py --cia "..." --skip-hash

# Name patches only
python src/patch_names.py --romfs "path\to\romfs"
python src/patch_names.py --dbin rebuild_dbin2

# Hub main menu / CESA only (onto release/bake_img.bin)
python tools/deploy_title_main_menu_en.py
python tools/deploy_cesa_en.py

# Patch code.bin only
python src/patch_code.py "..\New Love Plus Plus\extracted\exefs\code.bin"

# Asset helpers
python src/patcher.py status
python src/patcher.py validate
python src/patcher.py dialogs --script a002
python src/patcher.py build --clean
```

`patcher.py build` only stages loose `assets/` → `out/patch/`. CIA / LayeredFS work is the drop bat / `src/patch_cia.py`.

---

## What this is not

- A full 100% translation of every line and texture (skipped UI formats stay Japanese).  
- A dump of the game — you must supply your own matching CIA / `.3ds`.  
- An on-console retail re-encryptor.  
- A GitHub-hosted gold bake — ship `release/bake_img.bin` separately if you want others to skip the ~16h rebuild.
