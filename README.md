# NewLovePlusPlusEngPatcher

One-click English patcher for **New Love Plus+** (3DS), plus the finished translation assets it ships.

Translation work-in-progress lives elsewhere ([Makein/NLPPGit](https://github.com/Makein/NLPPGit), localization project). This repo holds **completed** scripts/images and a toolchain that turns an official **CIA or .3ds/.cci** dump into a playable English **CIA**.

**License:** EngPatcher original work is [MIT](LICENSE) for the community. That license covers **only** this project’s own code and assets — not third-party tools, fonts, or vendored trees (see [Credits](#credits) and `LICENSE`).

---

## What it can do

Drop in a **decrypted** dump (`.cia` or `.3ds` / `.cci`) and it will:

1. **Verify** the dump (SHA-1) before touching anything  
2. **Reject encrypted dumps** — decrypt yourself first (GodMode9, Batch CIA 3DS Decryptor, etc.)  
3. **Inject English scripts** (pre-packed `.dbin2` from finished XML)  
4. **English heroine names** — rewrite dialog tokens (`▲高嶺＊＊▲` → `Takane`, etc.) and patch UI name tables in `textresource_resident_jpn.trb` / `img.bin`  
5. **Optionally patch `code.bin`** — single-pane player-name draw so roman letters aren’t one-glyph-per-box (`--patch-code`)  
6. **Inject gold UI** from `release/bake_img.bin` when present (PNG pack + menu chrome + CESA + SMS/day-counter) and Profile name-input from `release/name_input_code.bin` when present  
7. **Apply TRB overlay** from `release/romfs_overlay/` when present  
8. **Rebuild** a decrypted **CIA** for FBI / Azahar / Citra (even when the input was `.3ds`)  
9. **Clean** `out/` to the finished CIA + `luma/` LayeredFS (optional SpotPass via `build_spotpass_inject.py`)

| Included assets | Approx. count |
|-----------------|--------------:|
| Finished dialog scripts (XML → `.dbin2`) | 480 scripts → 1644 `.dbin2` across `NLP_01` / `NLP_02` / `script` |
| Finished UI PNGs | ~2574 |
| UI packages patched into `img.bin` (last pack) | 49 packages / ~1190 textures applied |

Title ID: `00040000000F4E00`

---

## Quick start (drag and drop)

1. Double-click **`Drop CIA or 3DS Here to Patch.bat`**
2. Drop your **decrypted** `.cia` / `.3ds` / `.cci` on the window (or use Browse → Patch)  
   — or drag the file directly onto the `.bat`

With a ready gold bake (`release/bake_img.bin` + overlay), patching usually finishes in **a few minutes**.

### Sharing a build (skip the 16-hour bake)

`release/bake_img.bin` is **gitignored** (too large for GitHub). Assets under `assets/` **are** in the repo.

**Preferred:** push/merge to EngPatcher **`main`** → **nlpp-gold** Ubuntu runner
builds `release/` and updates GitHub Release tag `gold`. See
[`infra/README.md`](infra/README.md). Collaborators:

```bash
python tools/fetch_release_bake.py --repo OWNER/nlpp-gold --tag gold
# or: set NLPP_GITHUB_REPO=OWNER/nlpp-gold
```

Manual handoff still works:

1. Clone / zip this repo (includes `assets/`, scripts, tools).  
2. Also give them your finished **`release/`** pack:
   - `release/bake_img.bin` — English UI bake  
   - `release/romfs_overlay/` — TRB overlay  
   - `release/textresource/` — optional but useful  
3. They supply **their own** matching dump and run the drop bat.

Do **not** ship the game dump, `cache/`, `out/`, or `*.bak_pre_*` sidecars. CIA patching stays on **Windows**.

### Azahar a/b testing (devs / agents)

Dual isolated Azahar user dirs for LayeredFS experiments (no fighting roaming AppData):

```powershell
.\make.ps1 instances
.\make.ps1 deploy-a    # default: name-input stack → instance A
.\make.ps1 launch-a
.\make.ps1 restore-a
```

Full guide: [`ab_test/README.md`](ab_test/README.md). Paths: copy `ab_test/paths.local.ps1.example` → `ab_test/paths.local.ps1`. Name-input RE: `technical.md` §17.

### Companion site progress bar

Script-text % on [newloveplus.loc.moe](https://newloveplus.loc.moe) is computed by
`src/report_progress.py` (EN TRB vs vanilla JP). It auto-POSTs after a TRB
`rebuild`, after a successful Drop CIA run, and from **nlpp-gold** CI — when
`NLPP_PROGRESS_ENDPOINT` + `NLPP_PROGRESS_TOKEN` are set (local `.env` or
nlpp-gold Actions secrets). Graphics/menus stay manual in the site admin.
See [`infra/README.md`](infra/README.md). Manual: `.\make.ps1 progress`.

### First-time gold bake (only if `release/bake_img.bin` is missing)

If bake is absent, the drop bat auto-runs:

```bash
python tools/rebuild_bake_img.py --rom path\to\game.cia   # or .3ds / .cci
```

That regenerates bake + TRBs from sources. Historically **~16 hours** when every ARC ran zopfli sequentially; as of 2026-09-05 the pack prefers stdlib zlib empty-block padding and parallelizes packages (`--pkg-workers`) — see `technical.md` §12.5.3. Progress lines mean it is still working.

- Vanilla `img.bin` is taken from the dropped ROM when sibling `extracted/` is missing (`cache/vanilla_from_rom/`).  
- Resume after pack finishes: `python tools/rebuild_bake_img.py --skip-pack` (from **repo root**).  
- Scripts-only CIA (no UI inject): `set NLPP_WITH_IMAGES=0`.

Details / pitfalls: `technical.md` §15, `release/README.md`.

### Required dump

**Decrypt the dump yourself first.** This patcher does not ship `decrypt.exe`.

Known New Love Plus+ dumps (SHA-1). Encrypted hashes may still match the allowlist but are **rejected** at the crypto gate:

```
a9fbd2e6d790b6cb6194f7820e1a71f597160f2b  # encrypted CIA (decrypt first)
811d2f0f72c2a1437997256f30b18fbb2dea6cda  # decrypted CIA
6af1751f8b4f9d074311f3a7cf2b5d3c5e807cc8
d138d92fd9d522827cb9665bc2c954f1e8ba1f92  # decrypted full .3ds
6428e72eefec31d19282d2c7f0cb5082723a3206  # encrypted trim .3ds (decrypt first)
```

Many other decrypted CIAs will fail the hash check (by design). Use `--expect-sha1 <hash>` to require one specific dump, or `--skip-hash` to bypass (not recommended).

### Requirements

- Windows x64  
- Python 3.10+ (the drop bat finds `python`, `py -3`, or common install folders)  
- `pip install -r requirements.txt` (Pillow, numpy, zopfli, **etcpak** — drop-bat runs this)  
- A few GB free disk (RomFS rebuild is large)  
- A **decrypted** dump (GodMode9, Batch CIA 3DS Decryptor Redux, etc.)  
- First run verifies vendored `tools/cia/` bins (`3dstool` / `ctrtool` / `makerom` / `seeddb`); downloads only if a bin is missing  
- UI glyph font is bundled: `assets/fonts/MPLUS1p-Regular.ttf` (SIL OFL)  

If you see **Python not found**: install from [python.org](https://www.python.org/downloads/) with **Add python.exe to PATH** checked, open a **new** Command Prompt, and confirm `py -3 --version` works. Turning off Windows “App execution aliases” for `python.exe` only helps after a real install exists.

### Outputs

| Path | Description |
|------|-------------|
| `out/NewLovePlusPlus-EN.cia` | Patched **decrypted** CIA — install with FBI, or open in Azahar/Citra |
| `out/luma/00040000000F4E00/` | Luma LayeredFS overlay — copy to `SD:/luma/titles/` |
| `out/luma/README.txt` | Install steps for Luma / Azahar |
| `release/bake_img.bin` | Gold UI `img.bin` (preferred by drop-bat / `patch_cia`) |
| `release/romfs_overlay/` | Durable RomFS overlay (TRBs); auto-applied if present |
| `release/textresource/` | Durable TRB / translation work |
| `cache/new_img.bin` | Optional PNG-pack scratch (incomplete vs gold) |
| `cache/vanilla_from_rom/` | Vanilla RomFS extracted from a dropped ROM when needed |

After a successful patch, `out/` is cleaned to **CIA + `luma/`** (plus `azahar_instances/` if present). Pass `--keep-work` to retain scratch. SpotPass inject is optional: `python tools/build_spotpass_inject.py` → `out/spotpass_real3ds/`.

**LayeredFS install**

- **Luma (3DS):** copy `out/luma/00040000000F4E00` to `SD:/luma/titles/` and enable *Enable game patching*  
- **Azahar / Citra:** copy that folder into the emulator’s `load/mods/` directory  

Deploy scripts mirror into Azahar LayeredFS by default when that mod `img.bin` exists (`NLPP_ALSO_AZAHAR=0` to opt out). For iterative testing prefer `ab_test/` instances (`.\make.ps1 deploy-a`) over roaming AppData — see [`ab_test/README.md`](ab_test/README.md).

### Known issues

- **Boop / network install:** Installing the patched CIA over the network with Boop does not work. Copy `out/NewLovePlusPlus-EN.cia` to the SD card and install with FBI, or open the CIA in Azahar/Citra.

---

## SpotPass (とわのウォッチャー / boot check)

SpotPass is **not** the in-game **Communication** menu (Girlfriend Comm / Business Card / Wireless Battle — those are StreetPass / local wireless). NLPP checks for SpotPass NsData at **cold boot** and shows either an apply prompt or **“No SpotPass data found.”**

Archived BOSS content (「とわのウォッチャー」第28号) is vendored under `tools/spotpass/` — **thank you to Cetaceaqua** for providing that SpotPass dump. Full RE notes: [`technical.md` §16](technical.md).

**Included in the patch workflow:** LayeredFS + CIA by default. SpotPass inject is **optional** afterward:

```bash
python tools/build_spotpass_inject.py          # → out/spotpass_real3ds/info.dat
python tools/build_spotpass_inject.py --azahar # emulator-padded + optional SDMC sync
```

Or pass `--keep-work` to `patch_cia` / use `--spotpass-mode` with `--keep-work` if you want inject left under `out/` after a patch.

### How the inject file is made (shareable summary)

For title `00040000000F4E00`, the archived payload is a raw NsData blob (`tools/spotpass/info.dat`, **2324** bytes). The game does not use that file alone on disk — BOSS expects it as extdata:

`extdata/00000000/00000321/boss/info.dat`

**What we do to the file:** we do **not** change the payload contents. We prepend a **0x34-byte Boss header** (program ID, datatype `0x10001`, size, NsDataId `1`, version `0x500`) in front of the original 2324 bytes → **2376** bytes total for hardware / exact mode.

**On Azahar**, stock HLE has two issues:

1. The game tries to `ReadNsData` with a huge buffer (`0x7D004`) while the real payload is small — so we **zero-pad** the file to that size for the emulator (`--azahar`), or use an Azahar build that allows short reads (`--azahar-exact`).
2. `GetNsDataNewFlag` always returns `0`, so the boot prompt never treats the data as new — that needs a small Azahar fix/patch so the flag returns `1` when NsDataId `1` exists.

**On a real 3DS**, use the **exact** (unpadded) header+payload file, and put it **only** under `…/00000321/boss/` (create `boss` on PC/GodMode9 if FBI does not show it). Do **not** paste it into normal Extra Data / `user/` or you will break additional data.

### Build inject files (standalone)

```bash
# Real 3DS (default — exact size)
python tools/build_spotpass_inject.py
python tools/build_spotpass_inject.py --real3ds

# Azahar stock HLE (pads ReadNsData buffer to 0x7D004; also syncs AppData sdmc)
python tools/build_spotpass_inject.py --azahar

# Azahar with short-read HLE fix (exact size)
python tools/build_spotpass_inject.py --azahar-exact
```

| Mode | Output | Size | Use on |
|------|--------|-----:|--------|
| `--real3ds` (default) | `out/spotpass_real3ds/` | 2376 B | CFW 3DS |
| `--azahar` | `out/spotpass_azahar/` + live SDMC | ~512 KiB | Stock Azahar |
| `--azahar-exact` | `out/spotpass_azahar_exact/` | 2376 B | Azahar with short-read patch |

### Azahar

1. Build with `--azahar` (or `--azahar-exact` if your build clamps `ReadNsData`).
2. Default install path:

   `%AppData%\Azahar\sdmc\Nintendo 3DS\…\extdata\00000000\00000321\boss\info.dat`

3. **Stock Azahar** also stubs `GetNsDataNewFlag` as always `0`, so the game never treats injected data as new. You need either:
   - a build where `GetNsDataNewFlag` returns `1` when NsDataId `1` exists under boss extdata, or  
   - a binary patch of that stub (same idea as the Localization Studio fork patch used during RE).
4. Relaunch Azahar, cold-boot NLPP, confirm log lines show `ns_data_new_flag=0x01` and a successful `ReadNsData`.

### Real 3DS (CFW)

1. `python tools/build_spotpass_inject.py` (default = real3ds).
2. Run NLPP once so extdata **`00000321`** exists; enable SpotPass in network settings if the game exposes it.
3. Put `out/spotpass_real3ds/info.dat` **only** under  
   `Nintendo 3DS/<ID0>/<ID1>/extdata/00000000/00000321/boss/`  
   (create `boss` via PC or GodMode9 — FBI often has no SpotPass/`boss` browse path).
4. Leave `user/` alone. Fully close the game, cold-boot.

Do **not** paste the Azahar-padded (~512 KiB) file onto hardware. If the boot dialog still says no data was found, BOSS may not have marked NsDataId `1` as “new” (hardware tracks that separately from the file bytes).

---

## Pipeline (what runs under the hood)

```
decrypted .cia  OR  decrypted .3ds/.cci
  → SHA-1 check
  → crypto gate (refuse if still encrypted)
  → extract CXI (ctrtool contents / 3dstool partitions)
  → extract RomFS (3dstool)
  → inject rebuild_dbin2/*.dbin2 into script/bin/{NLP_01,NLP_02,script}/
  → name patches (plain Takane/Rinko/Nene in scripts + resident/img tables)
  → inject gold bake img.bin + romfs_overlay TRBs
  → rebuild RomFS → CXI → CIA (makerom, decrypted)
  → clean out/ (keep *.cia + luma/; azahar_instances/ preserved)
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

- Input must already be **decrypted** (`Crypto Key: None`). Encrypted dumps are refused.  
- Output is a **decrypted** CIA — correct for CFW and emulators.  
- True retail NCCH re-encryption is **not** done here; use Decrypt9WIP *CIA Encryptor (NCCH)* on a console if you specifically need that.

**UI bake (gold `img.bin`)**

- Put translated UI PNGs under `assets/images`.  
- **Gold path:** `python tools/rebuild_bake_img.py` → `release/bake_img.bin` (+ `release/name_input_code.bin`)  
  PNG pack + main TRB from `assets/textresource/translations.json` + ordered `deploy_*` chrome (Options / menus / Confirm / softkeys / multiwin / gallery / UI buttons / keyboard tabs / Title / CESA / …) + SMS + day-counter + overlay + Profile name-input `code.bin`.  
- No sibling dump needed: pass `--rom game.cia|.3ds|.cci` (drop-bat does this automatically).  
- Drop-bat **auto-runs a full rebuild** if bake is missing, then patches the CIA.  
- Drop-bat / `patch_cia.py` **prefer `release/bake_img.bin`** when present; inject `release/name_input_code.bin` when present.  
- **Cold PNG pack** is CPU-bound exact-zlib (see `technical.md` §12.5.3): empty-block-first + `--pkg-workers`. Warm `cache/img_pack/` re-packs are typically minutes. Progress lines mean it is still working.  
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
| Gallery girl-select / multiwin headers | **5153** / **5237** | `deploy_gallery_common_en.py` / `deploy_multiwin_headers_en.py` |
| Softkeys Back / Next / Confirm | **5238** | `deploy_softkey_back_next_en.py` + `deploy_confirm_btn_en.py` |
| Options chrome | **5245** | `deploy_msel_options_en.py` |
| Boot CESA warning | **90** | `deploy_cesa_en.py` (not auto PNG-pack) |
| Profile name-input (romaji) | ExeFS `code.bin` | `deploy_name_input_en.py` → `release/name_input_code.bin` |
| “Main Menu” title string | TRB | Already EN via textresource |

---

## Credits

Thank you to everyone whose work this patcher builds on. Their materials keep **their own** licenses; the MIT grant in [`LICENSE`](LICENSE) is only for EngPatcher original work.

### CIA / RomFS tooling

| Component | Credit |
|-----------|--------|
| `3dstool` / `ctrtool` / `makerom` / `seeddb.bin` | Vendored under `tools/cia/` ([CREDITS](tools/cia/CREDITS.md)); `setup_tools.py` fetches only if missing |
| `ctrtool` / `makerom` | [3DSGuy/Project_CTR](https://github.com/3DSGuy/Project_CTR) (auto-fetched) |
| `seeddb.bin` | [ihaveamac/3DS-rom-tools](https://github.com/ihaveamac/3DS-rom-tools) (auto-fetched) |

### Image packing / UI

| Component | Credit |
|-----------|--------|
| `nlpp-tools` (`ie`, `pe`, `png2bclim`, `png2texi`, …) | **[kiwiz/nlpp-tools](https://github.com/kiwiz/nlpp-tools)** — thank you to **kiwiz** |
| Name-select screen buttons (OK / Yes / No / Options) | **lolipop221** |
| UI glyph font `MPLUS1p-Regular.ttf` | [M PLUS 1p](https://fonts.google.com/specimen/M+PLUS+1p) / [Coji / M+ FONTS](https://github.com/coz-m/MPLUS_FONTS), SIL OFL 1.1 (`assets/fonts/OFL.txt`) |
| Other fonts under `assets/fonts/` (Pixelify Sans, Press Start 2P, Silkscreen, VT323) | [Google Fonts](https://fonts.google.com/) / respective OFL authors (editor / optional assets) |

### Text / scripts / localization community

| Component | Credit |
|-----------|--------|
| NLPPATCH (historical community patch) | [LovePlusProject/NLPPATCH](https://github.com/LovePlusProject/NLPPATCH) and contributors (see [their credits](https://github.com/LovePlusProject/NLPPATCH/issues/1)) — EngPatcher ships its own `rebuild_dbin2/` + `assets/` |
| NLPTextTool (XML ↔ `.dbin2`) | [LovePlusProject/NLPTextTool](https://github.com/LovePlusProject/NLPTextTool) (orig. [gdkchan](https://github.com/gdkchan)) |
| NLPUnpacker | [LovePlusProject/NLPUnpacker](https://github.com/LovePlusProject/NLPUnpacker) (orig. [gdkchan](https://github.com/gdkchan)) |
| Translation asset repo (reference) | [Makein/NLPPGit](https://github.com/Makein/NLPPGit) |
| `Trb2xlsx` / `lookup.txt` (TRB character codebook) | [deaknaew/Trb2xlsx](https://github.com/deaknaew/Trb2xlsx) (vendored under `tools/Trb2xlsx/`) |
| SpotPass / とわのウォッチャー archive (`tools/spotpass/`) | **Cetaceaqua** — thank you for providing the SpotPass dump |

Python packages used at runtime: [Pillow](https://python-pillow.org/), [NumPy](https://numpy.org/), [zopfli](https://github.com/google/zopfli) (`python-zopfli`), [etcpak](https://github.com/K0lb3/etcpak) (ETC1/ETC1A4 for BCLIM).

---

## Layout

```
Drop CIA or 3DS Here to Patch.bat   ← only end-user entry point
Makefile / make.ps1                 ← shim → ab_test/make.ps1
README.md
technical.md                 RE notes (§15 gold bake, §16 SpotPass, §17 name-input, §18 a/b)
ab_test/
  README.md                  Azahar dual-instance workflow
  make.ps1                   instances / seed / deploy / launch / restore
  setup_azahar_instances.ps1
  paths.local.ps1.example    → paths.local.ps1 (gitignored)
assets/
  scripts/                   finished DBIN2 XML
  images/                    finished UI PNGs (+ editor sources)
  textresource/              translations.json (source for main TRB rebuild)
  fonts/                     MPLUS1p + OFL (UI deploy glyph font)
src/
  patch_cia.py               CIA extract → inject → rebuild (decrypted input only)
  patch_names.py             heroine names (dbin2 / resident TRB / img.bin)
  patch_code.py              single-pane name draw (ExeFS code.bin)
  patch_input_*.py           Profile name-input code.bin patches (§17)
  pack_images.py             PNG → img.bin
  exact_zlib.py              exact-length zlib/zopfli for ARC slots
  extract_vanilla_from_rom.py  vanilla img/TRB from dropped ROM
  darcutil.py / bclimutil.py / image_map.py
  setup_tools.py             verify vendored CIA bins (no decrypt.exe)
  drop_zone.ps1              WinForms drop window
tools/
  rebuild_bake_img.py        regenerate bake + TRBs from sources
  deploy_*.py / restore_*.py / rebuild_test_cia.py
  build_spotpass_inject.py   SpotPass boss info.dat for Azahar / real 3DS
  spotpass/                  archived BOSS dump + README
  nlpp-tools/                vendored img.bin helpers (kiwiz/nlpp-tools)
  cia/                       3dstool / ctrtool / makerom / seeddb (see CREDITS.md)
rebuild_dbin2/               finished English .dbin2 scripts
release/                     gold bake + TRB overlay (binaries gitignored; see release/README.md)
cache/                       PNG scratch + vanilla_from_rom (gitignored)
out/                         wipeable scratch + azahar_instances (gitignored)
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

# Name-input LayeredFS (Azahar a/b)
.\make.ps1 deploy-a
.\make.ps1 launch-a
# or: python tools/deploy_name_input_en.py

# Hub main menu / CESA only (onto release/bake_img.bin)
python tools/deploy_title_main_menu_en.py
python tools/deploy_cesa_en.py

# SpotPass inject (boot NsData — see technical.md §16)
# Default after patch_cia / drop-bat: real3ds → out/spotpass_real3ds/
python tools/build_spotpass_inject.py
python tools/build_spotpass_inject.py --azahar
# patch_cia flags: --skip-spotpass | --spotpass-mode azahar | --spotpass-install-azahar

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
- A dump of the game — you must supply your own matching **decrypted** CIA / `.3ds`.  
- A ROM decryptor — decrypt outside this tool, then drop the clear dump.  
- An on-console retail re-encryptor.  
- A GitHub-hosted gold bake — ship `release/bake_img.bin` separately if you want others to skip a cold local rebuild.
