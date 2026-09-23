# NewLovePlusPlusEngPatcher

One-click English patcher for **New Love Plus+** (3DS), plus the finished translation assets it ships.

Fansite & community hub: [newloveplus.loc.moe](https://newloveplus.loc.moe)

Translation work-in-progress lives elsewhere ([Makein/NLPPGit](https://github.com/Makein/NLPPGit), localization project) and in the **volunteer HTML workbench** (see [Volunteer localization workbench](#volunteer-localization-workbench)). This repo holds **completed** scripts/images, HTML *templates*, and a toolchain that turns an official **CIA or .3ds/.cci** dump into a playable English **CIA**.

**License:** EngPatcher original work is [MIT](LICENSE) for the community. That license covers **only** this project’s own code and assets — not third-party tools, fonts, or vendored trees (see [Credits](#credits) and `LICENSE`).

---

## What it can do

Drop in a **decrypted** dump (`.cia` or `.3ds` / `.cci`) and it will:

1. **Verify** the dump (SHA-1) before touching anything  
2. **Wipe `out/` and `release/`** completely, then recreate both empty. That deletes the previous CIA, logs, `out/azahar_instances/`, `out/extdata_backup/`, gold bake, TRB overlay, and name-input `code.bin`. `cache/` is left in place. `python src/patch_cia.py` on its own does not do this wipe  
3. **Reject encrypted dumps** — decrypt yourself first (GodMode9, Batch CIA 3DS Decryptor, etc.)  
4. **Inject English scripts** — layered: Manaka `t*` + common `p*` from `rebuild_dbin2/`, plus community ~28% Rinko/Nene stems (ex-NLPPATCH, also in `rebuild_dbin2/script/`; see `assets/nlppatch/`) via `src/script_inject.py`  
5. **English heroine names** — rewrite dialog tokens (`▲高嶺＊＊▲` → `Takane`, etc.) and patch UI name tables in `textresource_resident_jpn.trb` / `img.bin`  
6. **Inject Profile name-input `code.bin`** from `release/name_input_code.bin` when present (romaji keyboard, Message Speed, title-loop guard). Older single-pane `--patch-code` is still available and is **not** this stack  
7. **Inject gold UI** from `release/bake_img.bin` when present (PNG pack + menu chrome + CESA + SMS/day-counter)  
8. **Apply TRB overlay** from `release/romfs_overlay/` when present  
9. **Rebuild** a decrypted **CIA** for FBI / Azahar / Citra (even when the input was `.3ds`) and a Luma **LayeredFS** folder at `out/1_[Either use this-LayerFS]/luma/` (includes `code.bin`). Use one install path  
10. **Clean** `out/` to numbered LayeredFS + CIA folders + `3_but not both` + `logs/` (SpotPass Watcher #28 is baked into `code.bin`; `build_spotpass_inject.py` is optional)  
11. **Write a PATCH SUMMARY log** to `out/logs/` (timestamped + `latest.txt`; `--no-log` / `NLPP_NO_LOG=1` to skip)

| Included assets | Approx. count |
|-----------------|--------------:|
| Finished dialog scripts (XML → `.dbin2`) | 480 scripts → 1644 `.dbin2` across `NLP_01` / `NLP_02` / `script` |
| Unique EN UI PNG masters (`IMAGE_MAP`) | **1745** in **95 / 95** folders |
| Chrome subset (site “UI textures”) | **562** in **25 / 25** folders |

PNG counts are **audited English masters present** (deduped by stem under `assets/images/`, prefer `.check`; 2026-09-20). Not a percent of every BCLIM in vanilla `img.bin`. Chrome = the 25 folders `tools/export_progress_metrics.py` posts as UI textures. Full mapped pack is what gold bake packs. All 95 `IMAGE_MAP` keys have an asset folder (`intro111` / `intro203` / `intro304` are sparse dumps).

Title ID: `00040000000F4E00`

---

## Why this rebuilds a CIA

Most 3DS mods ship as a Luma LayeredFS folder. You copy the changed files to `sdmc:/luma/titles/<titleid>/`, the stock install or cartridge stays untouched, and a bad mod is removed by deleting the folder. That became the usual path because a lot of games store textures and text as loose RomFS files, a public mod page can host those files without hosting the game, and rebuilding a CIA means unpacking the RomFS, rebuilding its hash tree, and reinstalling through FBI.

This project started from the other problem: images, dialog, and `code.bin` each had their own patch, and nothing required them to be the same game. Copying one of them left English names and script on Japanese menus. Drop CIA injects the gold `img.bin`, the script and TRB overlay, and `name_input_code.bin` together, and it stops if the bake is missing instead of emitting that half-English title. A LayeredFS folder of whichever piece you happened to have would still have been those separate routes.

The English release is also its own installable title, which a loose overlay does not produce.

- **HOME menu, region, and product code live in the CIA.** Vanilla shows ニューラブプラス＋, region Japan, product code `CTR-P-BLPJ`. LayeredFS does not rewrite the SMDH or the NCCH header. The rebuilt CIA sets the English title **New Love Plus+**, a USA region lock by default, and product code `CTR-P-BLPE`. The title ID stays `00040000000F4E00`, so existing saves still match. Other regions: `--cia-region japan|europe|free`.
- **Menus are one archive.** UI chrome sits inside `img.bin` (about 680 MB), so a LayeredFS copy of the English UI is still that whole file. Drop CIA deletes `release/` at the start of every build and packs a new `release/bake_img.bin` before inject.
- **FBI, Azahar, and Citra install a CIA.** A dropped `.3ds` / `.cci` is rebuilt into the same CIA. The patcher also writes `out/1_[Either use this-LayerFS]/` for a Luma overlay on a stock install, or for emulator tests. Use that folder **or** the CIA. Stacking them applies the English files twice (`out/3_but not both`).

The git repo still does not contain a dump. You bring your own decrypted CIA or `.3ds`. `release/bake_img.bin` and the finished CIA are generated on your machine (or fetched as a bake by collaborators) and are not committed.

---

## Quick start (drag and drop)

1. Double-click **`Drop CIA or 3DS Here to Patch.bat`**
2. Drop your **decrypted** `.cia` / `.3ds` / `.cci` on the window (or use Browse → Patch)  
   — or drag the file directly onto the `.bat`

Drop CIA **deletes `out/` and `release/` completely** before it starts, then packs a new gold bake. A previous bake, CIA, log, Azahar copy under `out/`, or extra-data backup in those folders is removed. `cache/` stays. Expect a full pack (typically under an hour; see below) on every drop.

### Sharing a build (skip the cold PNG pack)

`release/bake_img.bin` is **gitignored** (too large for GitHub). Assets under `assets/` **are** in the repo.

**Preferred:** push/merge to EngPatcher **`main`** → **nlpp-gold-maker** Ubuntu runner
builds `release/` and updates GitHub Release tag `gold`. See
[`infra/README.md`](infra/README.md). Collaborators:

```bash
python tools/fetch_release_bake.py --repo OWNER/nlpp-gold-maker --tag gold
# or: set NLPP_GITHUB_REPO=OWNER/nlpp-gold-maker
```

Manual handoff still works:

1. Clone / zip this repo (includes `assets/`, scripts, tools).  
2. Also give them your finished **`release/`** pack:
   - `release/bake_img.bin` — English UI bake  
   - `release/romfs_overlay/` — TRB overlay  
   - `release/textresource/` — optional but useful  
3. They supply **their own** matching dump.

Running the drop bat deletes that copied `release/` and packs again from `assets/`. To inject a bake already on disk, run `python src/patch_cia.py` (that command does not wipe `out/` or `release/`).

Do **not** ship the game dump, `cache/`, `out/`, or `*.bak_pre_*` sidecars. CIA patching stays on **Windows**.

### Azahar a/b testing (devs / agents)

Dual isolated Azahar user dirs for LayeredFS experiments (no fighting roaming AppData):

```powershell
.\make.ps1 instances
.\make.ps1 deploy-a    # default: name-input stack → instance A
.\make.ps1 save-nene   # shared Nene title save → A and B
.\make.ps1 launch-a
.\make.ps1 restore-a
```

Full guide: [`ab_test/README.md`](ab_test/README.md). Paths: copy `ab_test/paths.local.ps1.example` → `ab_test/paths.local.ps1`. Name-input RE: `technical.md` §17.

### Companion site progress bar

Script-text % on [newloveplus.loc.moe](https://newloveplus.loc.moe) is computed by
`src/report_progress.py` (EN TRB vs vanilla JP). It auto-POSTs after a TRB
`rebuild`, after a successful Drop CIA run, and from **nlpp-gold-maker** CI — when
`NLPP_PROGRESS_ENDPOINT` + `NLPP_PROGRESS_TOKEN` are set (local `.env` or
nlpp-gold-maker Actions secrets). Graphics/menus stay manual in the site admin —
use **562** (chrome) or **1745** (all mapped UI masters) from the table above.
See [`infra/README.md`](infra/README.md). Manual: `.\make.ps1 progress`.
Recount: `python tools/export_progress_metrics.py` (`images_ui.ui_png_masters_total` is the chrome subset).

### Gold bake (every Drop CIA)

**Drop CIA wipes `out/` and `release/` first.** The previous `release/bake_img.bin` and `release/bake_stamp.txt` are deleted, so the bat always packs from this tree. `PATCHER_RELEASE` is **`v1.0.0-rc3`** on main; Eng Patch badge / `CIA_TITLE_VERSION` is **3**. `cache/` (including `cache/img_pack`) is not wiped. Warm pack: `set NLPP_USE_PACK_CACHE=1`. `set NLPP_REUSE_BAKE=1` skips the stamp check after the wipe; the local bake is already gone, so that flag only lets the bat poll GitHub before the local pack. `rebuild_bake_img.py --skip-pack` does **not** refresh the PNG fingerprint when PNGs changed, and it does not wipe `out/` or `release/`.

The drop bat then runs:

```bash
python tools/rebuild_bake_img.py --rom path\to\game.cia   # or .3ds / .cci
```

That regenerates bake + TRBs from sources. A cold pack is typically **under an hour** on a multi-core desktop (measured **~27 min** on a high-thread machine; historically ~16h sequential zopfli). Empty-block-first + `--pkg-workers` + zopfli undershoot pad; see `technical.md` §12.5.3. Console prints live ``[timer]`` elapsed every stage / every 60s — use that for actual finish time.

- Vanilla `img.bin` is taken from the dropped ROM when sibling `extracted/` is missing (`cache/vanilla_from_rom/`).  
- Resume after pack finishes: `python tools/rebuild_bake_img.py --skip-pack` (from **repo root**).  
- Scripts-only CIA (no UI inject): `set NLPP_WITH_IMAGES=0`.

Details / pitfalls: `technical.md` §15.

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
- `pip install -r requirements.txt` (Pillow, numpy, zopfli, **etcpak**, PyYAML — drop-bat runs this)  
- A few GB free disk (RomFS rebuild is large)  
- A **decrypted** dump (GodMode9, Batch CIA 3DS Decryptor Redux, etc.)  
- First run verifies vendored `tools/cia/` bins (`3dstool` / `ctrtool` / `makerom` / `seeddb`); downloads only if a bin is missing  
- UI glyph font is bundled: `assets/fonts/MPLUS1p-Regular.ttf` (SIL OFL)  

If you see **Python not found**: install from [python.org](https://www.python.org/downloads/) with **Add python.exe to PATH** checked, open a **new** Command Prompt, and confirm `py -3 --version` works. Turning off Windows “App execution aliases” for `python.exe` only helps after a real install exists.

### Git commit signing (contributors)

PRs into `main` require **verified** commit signatures. Prefer **GPG** (GitHub verifies these reliably). Use the same email as your commits (GitHub noreply is fine).

```bash
# 1) Create a key (interactive). Choose RSA 4096, set email to your GitHub noreply
#    e.g. 12345678+USERNAME@users.noreply.github.com
gpg --full-generate-key

# 2) Copy the KEYID from the sec line (example: rsa4096/ABCDEF1234567890 → ABCDEF1234567890)
gpg --list-secret-keys --keyid-format LONG

# 3) Upload the public key: GitHub → Settings → SSH and GPG keys → New GPG key
gpg --armor --export KEYID

# 4) Tell git to sign with that key (replace KEYID with the real id from step 2)
git config --global gpg.format openpgp
git config --global user.signingkey KEYID
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

Probe: `git commit --allow-empty -S -m "gpg probe"` then `git log -1 --show-signature` (should show a good signature). Remove the probe with `git reset --hard HEAD~1`.

To re-sign an existing PR branch onto `main` after enabling GPG:

```bash
git fetch origin
git rebase --force-rebase -S origin/main
git push --force-with-lease origin HEAD
```

SSH commit signing is optional and not documented here — GitHub may leave SSH-signed commits **Unverified** (`unknown_key`) even when the Signing key fingerprint matches.

### Outputs

| Path | Description |
|------|-------------|
| `out/1_[Either use this-LayerFS]/luma/00040000000F4E00/` | Luma LayeredFS overlay — copy to `SD:/luma/titles/` (**or** install the CIA, not both) |
| `out/1_[Either use this-LayerFS]/luma/README.txt` | Install steps for Luma / Azahar |
| `out/2_[Or this]/NewLovePlusPlus-EN.cia` | Patched **decrypted** CIA — install with FBI, or open in Azahar/Citra (**or** use LayeredFS, not both) |
| `out/3_but not both` | Reminder: pick LayeredFS **or** the CIA |
| `out/logs/latest.txt` | PATCH SUMMARY from the last successful run (timestamped copies alongside) |
| `release/bake_img.bin` | Gold UI `img.bin` (preferred by drop-bat / `patch_cia`) |
| `release/romfs_overlay/` | Durable RomFS overlay (TRBs); auto-applied if present |
| `release/textresource/` | Durable TRB / translation work |
| `cache/new_img.bin` | Optional PNG-pack scratch (incomplete vs gold) |
| `cache/vanilla_from_rom/` | Vanilla RomFS extracted from a dropped ROM when needed |

Before that build starts, Drop CIA deletes **`out/` and `release/` completely** (previous CIA, logs, `azahar_instances/`, `extdata_backup/`, gold bake, overlay, name-input `code.bin`) and recreates both empty. `cache/` is not part of that wipe. After a successful patch, `out/` is cleaned again to **numbered LayeredFS + CIA folders + `3_but not both` + `logs/`**. Large intermediates (unpacked packages, extracted CXI/RomFS, duplicate `img.bin` copies) are deleted **as soon as each step finishes**, not only at the end. Pass `--keep-work` to `patch_cia.py` to retain scratch from that inject step; it does not skip the Drop CIA wipe. Towano Watcher #28 ships in `release/name_input_code.bin` (no boss paste). Optional real-extdata inject: `python tools/build_spotpass_inject.py` → `out/spotpass_real3ds/`.

**Pick one install path** (see `out/3_but not both`): LayeredFS on top of the English CIA applies the patch twice.

**LayeredFS install**

- **Luma (3DS):** copy `out/1_[Either use this-LayerFS]/luma/00040000000F4E00` to `SD:/luma/titles/` and enable *Enable game patching*  
- **Azahar / Citra:** copy that folder into the emulator’s `load/mods/` directory  

**Why the folder’s `code.bin` has to be the one this repo built**

Retail `code.bin` already loads textures. A BCLIM in `romfs/img.bin` is accepted only when its pointer is 128-byte aligned, the `CLIM` header and `imag` block match, and the format byte hits a GPU row (A8, RGBA4444, ETC1A4, and the rest). A valid English texture gets that far on an unpatched executable. Details: [`technical.md` §5.4](technical.md).

This overlay still needs `release/name_input_code.bin` beside `romfs/`, because two English graphics are outside that loader:

1. **Main Menu Eng Patch badge.** The title layout adds a picture pane retail does not have. When the hub rebuilds, that pane can be a null child, and retail `FindPaneByName` jumps to address 0. The menu aborts before it finishes drawing. The patched executable skips that attach ([`technical.md` §15.7](technical.md)).
2. **CESA thank-you blurb.** Retail draws the companion logo as a 400×400 quad. The English texture is 240×320. The patched executable keeps that real size so the blurb stays on the pane ([`technical.md` §12.7](technical.md)).

Drop CIA copies that file to `code.bin` in the LayeredFS folder. Luma and Azahar pick it up only when it is there. A folder with English `img.bin` and no `code.bin` runs the retail ExeFS: the textures are present, then the hub aborts and the thank-you quad is the wrong size. If a CIA rebuild fails and the overlay has no `code.bin`, that LayeredFS folder is deleted.

Use the `code.bin` from the same Drop CIA run. It is rebuilt from vanilla during the bake (`deploy_name_input_en.py`). An older ExeFS can miss one of those two hooks. The same file also carries the romaji name keyboard, Message Speed, and the SpotPass Watcher embed.  

Deploy scripts mirror into Azahar LayeredFS by default when that mod `img.bin` exists (`NLPP_ALSO_AZAHAR=0` to opt out). For iterative testing prefer `ab_test/` instances (`.\make.ps1 deploy-a`) over roaming AppData — see [`ab_test/README.md`](ab_test/README.md).

### Known issues

- **Boop / network install:** Installing the patched CIA over the network with Boop does not work. Copy `out/2_[Or this]/NewLovePlusPlus-EN.cia` to the SD card and install with FBI, or open the CIA in Azahar/Citra.

---

## SpotPass (とわのウォッチャー / boot check)

SpotPass is **not** the in-game **Communication** menu (Girlfriend Comm / Business Card / Wireless Battle — those are StreetPass / local wireless). NLPP checks for SpotPass NsData at **cold boot** and used to show either an apply prompt or **“No SpotPass data found.”**

Archived BOSS content (「とわのウォッチャー」第28号) is vendored under `tools/spotpass/` — **thank you to Cetaceaqua** for providing that SpotPass dump. Full RE notes: [`technical.md` §16](technical.md).

**Ship path — no inject.** Drop CIA / `release/name_input_code.bin` embeds the 2324-byte payload and spoofs BOSS `GetNsDataNewFlag` / `ReadNsData` after a save is loaded (`src/patch_spotpass_skip.py` + `src/patch_spotpass_embed.py`). The boot nag is suppressed; Watcher / city / meal tables merge once via the stock apply path. You do **not** need to paste `extdata/…/00000321/boss/info.dat`. Enoshima is already on-cart (script `t146`) and uses extra data `00000f4e`, not this blob.

**Optional BOSS-shaped file** (hardware BOSS DBs / Azahar HLE experiments only — not required for the English CIA):

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
  → write PATCH SUMMARY log to out/logs/
  → clean out/ (keep numbered LayeredFS/CIA folders + 3_but not both + logs/; azahar_instances/ preserved)
```

CLI example (cartridge dump → English CIA):

```bash
python src/patch_cia.py --cia "C:\path\to\00040000000F4E00_v00.3ds" --out "out/2_[Or this]/NewLovePlusPlus-EN.cia"
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

- **Default (gold / Drop CIA):** inject `release/name_input_code.bin` from `deploy_name_input_en.py` — romaji Profile keyboard, Message Speed, title-loop null-pane guard (`technical.md` §17 / §21). Bake always rebuilds it from vanilla.  
- Older opt-in `--patch-code` only rewrites `SetNameCharsToPanes` / clear / backspace so the whole name draws in one pane (max still 8). It is **not** the name-input stack.  
- Standalone (legacy): `python src/patch_code.py` (uses `cache/vanilla_from_rom` or sibling dump) or `python src/patch_code.py path\to\code.bin`  
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
- **Cold PNG pack** is CPU-bound exact-zlib (see `technical.md` §12.5.3): empty-block-first + `--pkg-workers` + zopfli empty-block pad. Watch live ``[timer]`` elapsed / heartbeat lines. Measured **~27 min** on a high-thread desktop; typical multi-core is often **under an hour** (historically ~16h sequential zopfli). Warm `cache/img_pack/` re-packs are typically minutes.  
- Resume deploys only: `python tools/rebuild_bake_img.py --skip-pack`.  
- Optional PNG-only scratch: `cache/new_img.bin` via `pack_images` / `NLPP_REPACK_IMAGES=1` — incomplete vs gold; does not refresh bake.  
- Scripts-only: `set NLPP_WITH_IMAGES=0` or `--no-images`.  
- Parallel convert: `--workers` / `--image-workers`. Fine-tune opt-in: `--fine-tune` / `--image-fine-tune` (very slow).  
- Exact-length zlib for compressed ARCs: `src/exact_zlib.py` (see `technical.md` §12.5 / §15).  
- The drop bat does **not** mutate your RomFS dump in-place.

**Main Menu vs submenus**

| Screen | Package | Notes |
|--------|---------|--------|
| Main Menu **rows** + Eng Patch badge | **5261** `Title.arc` | `deploy_title_engpatch_en.py` (replaces labels-only `deploy_title_main_menu_en.py` in bake) |
| Gallery / Communication / Data Management homes | **5244 / 5241 / 5242** | `deploy_msel_menus_en.py` |
| Gallery girl-select / multiwin headers | **5153** / **5237** | `deploy_gallery_common_en.py` / `deploy_multiwin_headers_en.py` |
| Softkeys Back / Next / Confirm / Quit / Restore Default | **5238** | `deploy_softkey_back_next_en.py` + `deploy_confirm_btn_en.py` + `deploy_softkey_quit_en.py` + `deploy_softkey_defaults_en.py` |
| Options chrome | **5245** | `deploy_msel_options_en.py` |
| In-room Options overlay | **5380** + **5575** | `deploy_myroom_options_en.py` (`optn_tex_*`, Zhoumaru) |
| Password entry window | **5251** `OptionPassword.arc` | `deploy_optionpassword_en.py` (`Pass_Win01`) |
| Password entry header | **5245** | `Password Input` (`Plate_Text03_05`) |
| Boot CESA warning | **90** | `deploy_cesa_en.py` (not auto PNG-pack) |
| Profile name-input (romaji) | ExeFS `code.bin` | `deploy_name_input_en.py` → `release/name_input_code.bin` |
| “Main Menu” title string | **5261** `Title_menu_word` | Render gray EN (do not pack Zhoumaru RGB dump) |

---

## Credits

Thank you to everyone whose work this patcher builds on. Their materials keep **their own** licenses; the MIT grant in [`LICENSE`](LICENSE) is only for EngPatcher original work.

### EngPatcher contributors

New work on **this** patcher. Not the 2016–17 NLPPATCH / tooling lineage in the tables below.

| Person | Contribution |
|--------|----------------|
| **Zhoumaru** | A large UI overhaul and translation work |
| **D.** | Debugging and testing the patch |
| **i need help here...** | Knowledge sharing |
| **( ˘ ᵕ˘(˘ᵕ ˘ )** | Shared save files that allowed quicker access to postgame context |

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

Python packages used at runtime: [Pillow](https://python-pillow.org/), [NumPy](https://numpy.org/), [zopfli](https://github.com/google/zopfli) (`python-zopfli`), [etcpak](https://github.com/K0lb3/etcpak) (ETC1/ETC1A4 for BCLIM), [PyYAML](https://pyyaml.org/) (`yaml` — required by vendored `ie` / nlpp-tools).

---

## Layout

```
Drop CIA or 3DS Here to Patch.bat   ← only end-user entry point
Makefile / make.ps1                 ← shim → ab_test/make.ps1
README.md
technical.md                 RE notes (§15 gold bake, §16 SpotPass, §17 name-input, §18 a/b)
ab_test/
  README.md                  Azahar dual-instance workflow
  make.ps1                   instances / seed / deploy / launch / restore / save-nene
  setup_azahar_instances.ps1
  paths.local.ps1.example    → paths.local.ps1 (gitignored)
  saves/nene/                shared Nene title save (`.\make.ps1 save-nene`)
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
  deploy_*.py / restore_*.py / import_azahar_save.py / rebuild_test_cia.py
  build_spotpass_inject.py   SpotPass boss info.dat for Azahar / real 3DS
  spotpass/                  archived BOSS dump + README
  nlpp-tools/                vendored img.bin helpers (kiwiz/nlpp-tools)
  cia/                       3dstool / ctrtool / makerom / seeddb (see CREDITS.md)
rebuild_dbin2/               finished English .dbin2 scripts
release/                     gold bake + TRB overlay; Drop CIA deletes this folder before each build (binaries gitignored; technical.md §15.5)
cache/                       PNG scratch + vanilla_from_rom (gitignored; not wiped by Drop CIA)
out/                         Drop CIA deletes this folder before each build; the run then writes the CIA, LayeredFS drop, and logs/ (gitignored)
```

Finished `.dbin2` scripts used at patch time live in `rebuild_dbin2/` (generated from `assets/scripts`).

---

## Volunteer localization workbench

Browser kits so translators can help **without Python**. Three sibling trees:

| Tree | Who | What |
|------|-----|------|
| [`nlpp-localization-workbench`](https://github.com/czyrustuazon/nlpp-localization-workbench) | Volunteers | Hub + built kits under `kit/` — open `index.html` |
| `nlpp-localization-workbench-parser` | Maintainers | `export_*.py` / `ingest_*.py` only (no HTML) |
| This repo `tools/localization_workbench/` | Maintainers | HTML **templates** the exporters inject into |

### For volunteers

1. Clone / unzip the workbench folder (keep `kit/NLPP_Translate_Images/media/` next to its `index.html`).
2. Open **`index.html`** → tabs:
   - **Scripts** — leftover dialogue for **Nene `a*`**, **Rinko `k*`**, **Manaka `t*`**, **common `p*`** (not Manaka-only)
   - **Strings** — leftover **SMS** (all three heroines) + **TRB** / menu strings still JP
   - **Images** — **full UI PNG audit** (**1745** unique masters in **95 / 95** `IMAGE_MAP` folders: softkeys, menus, headers, mail, date-edit, camera, title, popups, …). Intro111/203/304 are sparse, not empty.
3. Edit → **Save progress** → download JSON (`nlpp-contrib-….json`, `nlpp-strings-….json`, or `nlpp-images-….json` with optional `png_b64`).
4. Post the JSON in Discord **[#translated-work-to-review](https://discord.com/channels/1536915629787840572/1545180296343715891)**.

Keep nickname tokens (`▲高嶺＊＊▲`), `※`, `▼`, and `●` unchanged. Image replacements must match original width × height.

**What’s in the kits (sources):** see **`technical.md` §20.2** — Scripts = `assets/scripts/` XML + dump/NLPPATCH `.dbin2` (JP when dump is Japanese); Strings = `img.bin` SMS pkg 92 + TRB leftovers; Images = all `IMAGE_MAP` PNGs under `assets/images/` (prefer `.check` / `_eng`). Former `scripts_deferred/` ML/EN stash removed. Volunteer-facing summary: workbench `kit/README.md`. Fansite copy prompts: `docs/VOLUNTEER_WORKBENCH_PAGE_PROMPT.md` (contribute pages), `docs/FANSITE_PROGRESS_NUMBERS_PROMPT.md` (progress numbers).

### For maintainers

Configure `paths.local.json` in the parser (see `.example`):

```json
{ "eng_patcher": "C:/path/to/NewLovePlusPlusEngPatcher", "workbench": "C:/path/to/nlpp-localization-workbench" }
```

```bash
cd nlpp-localization-workbench-parser
python export_workkit.py      # → kit/NLPP_Translate.html (assets/scripts + dump/NLPPATCH dbin2)
python export_strings.py      # → kit/NLPP_Translate_Strings.html
python export_images.py       # → kit/NLPP_Translate_Images/ (+ zip)
python sync_hub.py            # → workbench/index.html from EngPatcher template

python ingest_pack.py their-nlpp-contrib.json --apply
python ingest_strings.py their-nlpp-strings.json --apply
python ingest_images.py their-nlpp-images.json --apply
```

Edit kit UI in EngPatcher `tools/localization_workbench/*.html`, then re-export. Full pack schema, validation rules, and session notes: **`technical.md` §20**.



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
# PATCH SUMMARY log: out/logs/patch_YYYYMMDD_HHMMSS.txt + latest.txt
# python src/patch_cia.py --cia "path\to\game.cia" --log D:\patch.txt
# python src/patch_cia.py --cia "path\to\game.cia" --no-log

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

# Hub main menu + Eng Patch badge / CESA only (onto release/bake_img.bin)
python tools/deploy_title_engpatch_en.py
python tools/deploy_cesa_en.py

# SpotPass inject (optional real extdata — Watcher #28 is already in name_input_code.bin)
# python tools/build_spotpass_inject.py
# python tools/build_spotpass_inject.py --azahar

# Patch code.bin only (finds cache/vanilla_from_rom or sibling dump)
python src/patch_code.py

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
- A gold bake **in this git repo** — `release/bake_img.bin` is gitignored. Fetch from **nlpp-gold-maker** Release tag `gold` (`tools/fetch_release_bake.py`) or rebuild locally.
