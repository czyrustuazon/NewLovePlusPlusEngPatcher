# New Love Plus+ — reverse engineering notes

Technical reference from localization / RE work on title `00040000000F4E00` (New Love Plus+), focused on UI text, textures, name-input, and system chrome. This file lives in **NewLovePlusPlusEngPatcher** (with the patcher tooling).

Cursor rules under `.cursor/rules/` summarize the same material for agents — keep them in sync when you learn something new.

---

## 0. Start here (do not restart from scratch)

Before hunting strings, re-extracting packages, or inventing a new “global text fix”:

1. Read **this file** end-to-end (especially §§5–6, 9, 11–12).
2. Skim Cursor rules: `read-docs-first`, `patch-safety`, `ghidra-mcp`, `ui-localization-method`, `nlpp-repo-workflow`, `clock-confirm-ui-localization`, `azahar-test-workflow`.
3. For LayeredFS iteration: **`ab_test/README.md`**.
4. Reuse EngPatcher work products before regenerating them:
   - `out/clock_recheck/` — scans, header/date viz, pkg 5238 extract
   - `release/textresource/` — durable TRB dumps / `translations.json` (not under wipeable `out/`)
   - `assets/images/*.check/` — decoded UI masters (prefer over guessing filenames)

**Already settled (do not rediscover):**

- Clock Back/Next/Confirm = NCommonIcon pkg **5238** `Com_btn_{m,t,k}01_b` (pixel-matched; Confirm EN = `OK`).
- Header `３ＤＳ本体時計` is **not** a contiguous string in romfs/`code.bin`/`img.bin` (any common encoding) — see §9.
- Global MakeStr hook and full `img.bin` rewrite are banned — see §11.
- **Never** `splice_packages_into_img(bak, …, live MOD)` — copies bak over the whole LayeredFS img and wipes later EN packages (§12.5.1).
- **Main Menu hub rows** (ゲームスタート / オプション / …) = `Title.arc` pkg **5261** `Title_btn02_t01..t06` — **not** NCommonMSel Text02–05 (those are submenus). See §15.
- Gold bake / clone pitfalls and fixes: **§15** (acquisition workflow **§15.5**; unit tests **§15.6**).
- SpotPass boot inject (Azahar HLE + real 3DS): **§16**. Do not look for it in the StreetPass Communication menu.
- **Profile First Name / name-input:** `python tools/deploy_name_input_en.py` or `.\make.ps1 deploy-a` — **§17**. Never deploy `candmode_reset` (`+0x24=0` → dead taps).
- **Azahar a/b instances:** `ab_test/README.md` — dual LayeredFS user dirs; do not tell the user to quit Azahar between tests.
- **CIA patcher input:** decrypted dumps only — no `decrypt.exe` in tree (user decrypts first).

---

## 1. Address spaces and binaries

| Item | Value |
|------|--------|
| Title ID | `00040000000F4E00` |
| Main code | `extracted/exefs/code.bin` |
| Image archive | `extracted/romfs/img.bin` (~712 MB) |
| TextResource | `extracted/romfs/SystemData/TextResource/textresource_jpn.trb` (+ `textresource_config.trb`) |
| Resident / TOP blob | **Runtime:** `img.bin` pkg **5508** (custom `TOP` chunks). RomFS `textresource_resident_jpn.trb` is the same format but **unused** — not referenced in `code.bin` (dev leftover). |
| Ghidra image base | `0` |
| Runtime VA | **file offset + `0x100000`** |

Pointers stored in `code.bin` are usually **runtime VAs**. Convert before seeking:

```text
file_offset = runtime_va - 0x100000
```

#### TextResource notes (2026-07-28)

- `code.bin` string table under `/SystemData/TextResource/` names only `textresource_config.trb` and `textresource_jpn.trb` — **no** `textresource_resident*`.
- Day-counter / resident name TOP data: patch **pkg 5508**; optional `release/textresource/textresource_resident_jpn.trb` is an edit convenience only.
- **Pending (unverified collaborator notes):** resident may be a pre-merged dev dump; main TRB ≈30k entries with reuse → ~45–50k uses; an ID→text map exists (improved `trb2xlsx` forthcoming). See Cursor rule `nlpp-repo-workflow` § Unverified / pending.

### Useful restore points

- `extracted/exefs/code.bin.bak_clocktext` — pre–MakeStr-hook backup (do not redeploy the abandoned global hook).

### 1.1 Ghidra MCP (`user-ghidra`)

1. Call `GetMcpTools` for schemas before invoking tools.
2. `list_open_programs` / `list_instances` + `connect_instance` if disconnected.
3. Prefer current program `code.bin` (also `/codeV2.bin` may exist). Image base **0**.

**Xrefs / pointers**

- Ghidra file address ≈ offset in `code.bin`.
- When `get_xrefs_to` on a string at file `0x006c3ea4` is empty, search LE bytes of the **runtime** pointer `0x007c3ea4` via `search_byte_patterns`.
- Ghidra string search often **misses UTF-8 Japanese** — use Python over `code.bin` / TRB instead.

**Efficient RE pattern**

- Start from ASCII anchors (`OptionAdjustTimeUIOperator`, `Lyt_Clock*`, `Pos_Com_btn_*`) → xrefs → decompile callers.
- Softkey Pos names are duplicated (`Pos_Com_Btn_m` vs `Pos_com_btn_m`) — different UI families; confirm which DAT a function uses.
- Tool schemas matter: e.g. `analyze_function_complete` wants `name`; `batch_decompile` wants `functions` (not ad-hoc keys).

**Known APIs (don’t re-derive)**

| Role | Address / name |
|------|----------------|
| TextResource pack+slot | `FUN_005c0e7c` → `FUN_0056ed00` |
| MakeStr | `FUN_005a1ec8` @ `005A1EC8` |
| DrawTextToPane | `FUN_0054b880` |
| Header pane draw | `FUN_0024842c` |
| Softkey m / o / t enable | `FUN_001d2498` / `001d1c70` / `001d2080` |
| Options button BCLIM bind | `OptionMenu_BindBtnTextures` @ `001eb3dc` |
| MSel icon+text bind | `BindMSelBtnIconAndText` @ `0020ad74` |
| Options/clock plate bind | `OptionMenu_BindPlateTextures` @ `0020bcc0` (slot 6 = clock title) |

---

## 2. Text / draw pipeline (high level)

```text
TextResource TRB (STRI/STRB/INDX)
        │
        ▼
FUN_005c0e7c(dst, maxlen, pack, slot)
        │  pack = (cat << 8) | sub
        ▼
FUN_0056ed00(…, cat, sub, slot, …)  → decode NLP codebook / UTF-8 into buffer
        │
        ▼
FUN_005a1ec8  MakeStr
        │
        ▼
FUN_0054b880  DrawTextToPane  → A8 / alpha pane (often dumped as RGB=0, alpha=glyph)
```

Alternate path for softkeys: **no MakeStr** — BCLIM textures bound to layout panes (`Pos_Com_Btn_*` / `Pos_com_btn_*`).

Header-pane helper used by option/date UIs:

- `FUN_0024842c(ui, paneIndex, stringSrc)` → MakeStr + `DrawTextToPane` into pane slot.

---

## 3. TextResource details

### 3.1 Main TRB (`textresource_jpn.trb`)

Chunks (order matters): `STRI`, `CDEI`, `STRB`, `CDEB`, `CONF`, `INDX`.

| Chunk | Role |
|-------|------|
| STRI | Entry table: `stringindex`, `bytelength`, `flag` per slot |
| STRB | String payloads (NLP codebook indices or UTF-8 when `flag == 1`) |
| INDX | Hierarchy: category → subcategory → slot → STRI entry index |
| CDEI / CDEB | Codebook-related |
| CONF | Small config (`trb` size bookkeeping) |

Codebook file used by EngPatcher:

`NewLovePlusPlusEngPatcher/tools/Trb2xlsx/TrbExport/lookup.txt` (~3445 entries, 1-based indices in NLP encoding).

**Companion site progress (script text):** `src/report_progress.py` diffs
`release/textresource/textresource_jpn.trb` vs vanilla JP — count of non-empty
`JP_RE` entries whose text changed → `scriptPercent`. POSTs to the site Worker
KV (`POST /api/admin/progress`). Auto after `rebuild`, Drop CIA.bat, and
nlpp-gold CI when `NLPP_PROGRESS_*` is set. Resident TOP TRB is **out of scope**.
Graphics track is manual. See `infra/README.md`.

### 3.2 Pack / hierarchy lookup

```c
// FUN_005c0e7c
FUN_0056ed00(..., (pack & 0xff00) >> 8, pack & 0xff, slot, 1);
```

Example known IDs (from earlier RE):

| String | Hierarchy `(cat, sub, slot)` | Pack |
|--------|------------------------------|------|
| `もどる` | `(3, 0, 0)` | `0x0300` |
| `戻る` | `(18, 0, 40)` | `0x1200` slot 40 |
| `次へ` | `(131, 0, 3)` | `0x8300` slot 3 |
| Flat STRI | 3453=`戻る`, 23509=`次へ`, 157/158/159=`日`/`月`/`年` |

**INDX parse sketch (cat 1 verified):**

- Bytes `0x00..0x3FF`: `u32` offsets per category (0 = unused).
- At `cat_off`: `u32 sub_count`, then `sub_count` relative `u32` offsets.
- Sub at `cat_off + rel`: `u32 slot_count`, then `slot_count` × `u16` STRI entry indices.

**Gotcha:** `FUN_0034cd98` calls `FUN_005c0e7c(..., pack=0x107, slot from +0x84)`.  
`0x107` → `(cat=1, sub=7)` = **prefecture names**, not the clock header. That fill targets object `+0x106` in a broader date/profile UI.

### 3.3 Resident TRB

- Magic/layout starts with `TOP` sections (null-separated UTF-8 fragments).
- Contains date/time building blocks (`０時`…`２３時`, `年`/`月`/`日`, weekdays, etc.).
- Does **not** contain contiguous `３ＤＳ本体時計`.

### 3.4 Translation quirks

- EngPatcher translations: `release/textresource/translations.json`.
- Many UI strings are already EN in the Azahar LayeredFS TRB overlay; if a screen stays JP, **do not assume missing TRB** — check textures / DrawText source.
- Closest TRB string to the clock header: `ＤＳ本体の時計と同じ` (different wording; not the confirm title).
- `３ＤＳ本体時計` was **not** found as UTF-8, UTF-16LE, Shift-JIS, or NLP codebook index sequence in `code.bin`, `img.bin`, main TRB, resident TRB, or BCLYT files.
- **Dialog wrap:** `fit_wrap` / `python src/patch_textresource.py rewrap --deploy-azahar` reflows multi-line EN to ~2× the longest JP line (clamped 18–30). Skips single-line blobs (newsletters). Rollback: `textresource_jpn.trb.bak_pre_rewrap`.

---

## 4. Image archive (`img.bin`)

### 4.1 Tools

Under `NewLovePlusPlusEngPatcher/tools/nlpp-tools/`:

| Tool | Role |
|------|------|
| `bin/ie` | Unpack package blob(s) from `img.bin` by index |
| `bin/pe` | Unpack/repack a package → `.arc` / `new_NNNN` |
| `opt/bin/png2bclim.exe` | Fallback BCLIM encode (often changes size — avoid when possible) |

These are **Python entrypoints** (invoke with `python ie …`), not Win32 native binaries.

```bash
python ie --src_img <img.bin> --img_dir <out> unpack --idx 5238
python pe <out>/5238 unpack    # → 5238_data/*.arc
python pe <out>/5238 repack    # → new_5238
```

### 4.2 Safe vs unsafe rebuild

| Method | Result |
|--------|--------|
| Same-offset **package splice** (`pack_images.splice_packages_into_img`) | Safe for LayeredFS |
| Full `Image.write()` / `--full-repack` | **Black-screen boot** — do not use |

If `pe` recompresses slightly smaller, pad the spliced blob to the original package slot length.

### 4.3 EngPatcher image map

`src/image_map.py` maps folder keys → `(package_index, arc_name)`.

Important keys for clock / softkeys:

| Key | Pkg | ARC |
|-----|-----|-----|
| `ncommonicon` | 5238 | `NCommonIcon.arc` |
| `ncommonmsel(8)` | **5240** | `NCommonMSel.arc` — Business Card submenu (Text04_02) |
| `ncommonmsel(7)` | **5241** | `NCommonMSel.arc` — Communication home (Text04) |
| `ncommonmsel(6)` | **5242** | `NCommonMSel.arc` — Data Management home (Text05) |
| `ncommonmsel(4)` | **5244** | `NCommonMSel.arc` — Gallery home (Text02) |
| `ncommonmsel(3)` | **5245** | `NCommonMSel.arc` — Options chrome + clock title plate |
| `option06` | 5248 | `Option06.arc` — Y/M/D date units |
| `dateeditbase01` / `02` | 4195 / 4196 | `DateEditBase01/02.arc` |
| `optionclock` | 5249 | `OptionClock.arc` |
| `myroomheader` | 5575 | `MyroomHeader.arc` — **not** Options/clock titles |
| `syspopup` | 5259 | `SysPopup.arc` |

Pack CLI:

```bash
python src/pack_images.py --only ncommonicon --img-bin <src> --out cache/new_img.bin [--deploy-azahar]
```

Prefer `assets/images/<Name>.check/` over raw trees when both exist.

---

## 5. BCLIM / imaging conversion quirks

### 5.1 Format IDs (this project)

| CLIM fmt | Meaning | Notes |
|----------|---------|--------|
| 1 | A8 | Alpha / text panes |
| 3 | RGB565 | Some Release buttons |
| 8 | RGBA4444 | Common UI labels |
| `0xB` / 11 | ETC1A4 | 16 bytes per 4×4 block; Ohana scramble |

**Azahar dump filenames** use a different “fmt” number (e.g. `_13_`). Never trust dump fmt for encode — always `parse_bclim` on the archive file.

Implementation: `EngPatcher/src/bclimutil.py`

- Morton / Z-order 8×8 tiles: `d2xy`, `gcm`
- ETC1A4: `etc1_scramble`, `encode_etc1a4_pixels` (etcpak + byte-reversed color + scramble)
- Same-size writers: `png_to_bclim_a8_same_size`, `png_to_bclim_rgba4444_same_size`, `png_to_bclim_etc1a4_same_size`

### 5.2 Hard rules for conversion

1. **Output BCLIM byte length must equal original** or DARC inject / in-game panes break (grey panels, wrong alpha).
2. `png2bclim` often expands (e.g. 4 KB → 32 KB) — EngPatcher rejects those.
3. Transparent pixels: encoder may fill RGB with `(86,86,86)` when `a==0` (matches prior png2bclim behavior).
4. ETC1A4 logical size may be smaller than compressed canvas (POT derived from payload length).
5. Alpha-only GPU dumps: RGB channels are 0; visualize via alpha before comparing.

### 5.3 Pixel-matching methodology

When identifying which BCLIM a screen uses:

1. Capture Azahar texture dump at the moment the UI is visible.
2. Decode candidate BCLIMs (correct fmt).
3. Compare with text-region MAD / glyph Jaccard (or full-frame MAD for opaque buttons).
4. **MAD = 0** against `assets/images/NCommonIcon.check/timg/…` confirmed exact masters for clock softkeys.

---

## 6. Softkey system

### 6.1 NCommonIcon (pkg 5238)

Contents:

- `NCommonIcon.arc` — button BCLIMs
- `MenuNComBtnM.dmst` — DMST state (`DMST` magic) listing `Pos_*` / `Pts_*` / `.bclan` tags

Button letter codes (decoded from usage / art):

| Code | Meaning (JP) |
|------|----------------|
| `m` | 戻る (Back) |
| `t` | 次へ (Next) |
| `k` | 決定 |
| `o` | OK |
| `re` | 再検索 |
| `tk` | 投稿 |
| `dl` / `dlr` | DL variants |
| … | `chg`, `hs`, `hz`, `pr`, `bye`, `q`, `plus`, `exp`, … |

Enable helpers (write visibility flags + poke layout Pos):

| Function | Pos | Object flag |
|----------|-----|--------------|
| `FUN_001d2498` | `Pos_Com_Btn_m` | `+0x25` / sticky `+0x38` |
| `FUN_001d1c70` | `Pos_Com_Btn_o` | `+0x28` / `+0x3b` |
| `FUN_001d2080` | `Pos_Com_btn_t` | `+0x37` / `+0x49` |

Init table builder: `FUN_001d14e0`.

### 6.2 Clock confirm softkeys (verified)

| UI | GPU dump | BCLIM | Pkg | Fmt | Size |
|----|----------|-------|-----|-----|------|
| Back `戻る` | `tex1_64x64_F305C9338867CC37_13_mip0.png` | `timg/Com_btn_m01_b.bclim` | 5238 | ETC1A4 (11) | 4136 |
| Next `次へ` | `tex1_64x64_4352FF452CC91909_13_mip0.png` | `timg/Com_btn_t01_b.bclim` | 5238 | ETC1A4 (11) | 4136 |

ON variants: `Com_btn_m01_bON`, `Com_btn_t01_bON` (dumps `42FF2BB2…`, `75A87132…`).

Exact PNG masters:

`NewLovePlusPlusEngPatcher/assets/images/NCommonIcon.check/timg/Com_btn_{m,t}01_b.png`

**Note:** Nested `NCommonIcon.check/NCommonIcon/timg/` copies are different art (poor match). DateEdit `Com_btn_m01_b` is a different style (e.g. hiragana もどる + arrow).

`OptionClockPopSetup` (`0034d214`) enables **m + o**, not m + t. The confirm screen that shows Next may use another state; textures still come from NCommonIcon `t01` when that Pos is shown.

### 6.3 Wrong softkey path (do not patch for clock)

`FUN_00249fd4` / `Tex_Bt%02d` uses `FUN_005c0e7c(..., 0x106, buttonIndex)` → hierarchy `(1,6,*)` = blood types (Ａ型/Ｂ型/…). Profile UI, not clock Back/Next.

---

## 7. Clock / option UI anchors (Ghidra)

| Symbol / item | File address | Notes |
|---------------|--------------|--------|
| `OptionAdjustTimeUIOperator` | `002d2ea0` | Class name string |
| Factory | `FUN_002d2e50` | Alloc / vtable install |
| Caller | `FUN_0039fc64` | Creates operator |
| Vtable (runtime ptr `0x0081c6a8`) | `0071c6a8` | Method slots |
| `Lyt_ClockPop_01.bclyt` | `0073d8ac` | |
| `Lyt_ClockSet_01.bclyt` | `0073d8c2` | |
| Layout desc ClockPop | `~079d2ec` | Points at lyt + handlers |
| Layout desc ClockSet | `~079d30c` | |
| `Com_lyt_rigt_hdr.bclyt` | `0073f63f` | Header chrome layout name |
| Rigt_hdr descriptor | `006c505c` | Loaded with clock UIs via `FUN_001dc494` path |
| `OptionClockPopSetup` | `0034d214` | Softkeys + may copy title buffer |
| `FUN_00350a1c` | `00350a1c` | Multi-pane `FUN_0024842c` draws |
| `Anm_ClockPop_01` / `Anm_ClockSet_01` | `00239298` / `00239b38` | |

MyroomHeader pkg **5575** contains `blyt/Com_lyt_rigt_hdr.bclyt` (tiny ~312 B shell) and `Com_pts_rigt_hdr.bclyt` — **no embedded title string**.

OptionClock pkg **5249**: Cancel/Ok + date spinner assets; **not** the square Back/Next pair.

---

## 8. Clock confirm UI — observed GPU dumps

| Role | Dump pattern | Notes |
|------|--------------|--------|
| Header | `tex1_256x32_2EC64BAE152688B3_8_mip0.png` | Alpha-only lookalike; actual source = A8 BCLIM `Plate_Text03_06_*` @ **5245** — **EN verified** |
| Year | `tex1_16x16_8B9E56BD535BF1C4_11_mip0.png` | = `Opt_Time_tex2` (Option06 A4) — EN `Y` **verified** |
| Month | `tex1_16x16_6B2CD1FB667B8DF0_11_mip0.png` | = `Opt_Time_Week01` (also Mon) — EN `M` **verified** |
| Day | `tex1_16x16_63A5BD96C326E5FF_11_mip0.png` | = `Opt_Time_Week07` (also Sun) — EN `D` **verified** |
| Back / Next | 64×64 dumps above | NCommonIcon — EN `Back`/`Next` **verified** |

Dump folder:

`%AppData%\Azahar\dump\textures\00040000000F4E00\`

**Option06 note:** `月`/`日` textures are shared with weekday Mon/Sun. EN `M`/`D` is intentional for date units; weekday row inherits the same letters.

---

## 9. Header string — negative findings

Searched and **not found** as a contiguous payload:

- `code.bin` (UTF-8 / UTF-16 / SJIS / u16 codepoint run / NLP index run)
- `img.bin` (same)
- Main TRB flat + full INDX walk for `本体時計` / `３ＤＳ本体時計`
- Resident TRB
- BCLYT embedded strings in MyroomHeader header layouts

**Resolved (2026-07-20):** title is **not** a contiguous string and **not** DrawText. It is A8 BCLIM `Com_M_Sel_Plate_Text03_06_00` (+ `_01`) in pkg **5245**, bound by `OptionMenu_BindPlateTextures` (slot 6). See §§12.4–12.5.

`optn_tex_optionmenu_05` (MyroomHeader) and the earlier DrawText/`FUN_0024842c` path are **dead ends** for this title.

---

## 10. Emulator / LayeredFS

```text
%AppData%\Azahar\load\mods\00040000000F4E00\
  romfs\img.bin
  romfs\SystemData\TextResource\...
  exefs\code.bin
```

| Path | Use |
|------|-----|
| `…\romfs\img.bin` | Texture packages (spliced) |
| `…\romfs\SystemData\TextResource\*.trb` | Strings |
| `…\exefs\code.bin` | Code patches |
| `%AppData%\Azahar\dump\textures\00040000000F4E00\` | GPU dumps |

Custom texture replacements (`pack.json`, `use_new_hash: true`) can briefly remap dumps but caused misbinds/crashes. **OK for RE reconnaissance only** — not a shipping strategy. Prefer archive splice; keep custom/dump/async off unless deliberately testing.

When deploying with `pack_images --deploy-azahar`, prefer splicing onto the **current Azahar mod** `img.bin` if it already has other patches (e.g. CESA), not only vanilla.

Treat dump `extracted/` as mostly **read-only**; write patches through EngPatcher → LayeredFS.

---

## 11. Patch safety and abandoned approaches

### 11.1 Hard bans (never)

- Full-rebuild `img.bin` with `Image.write()` or `pack_images --full-repack` → black-screen boot.
- Redeploy `EngPatcher/src/patch_clock_text.py` global MakeStr hook as-is → crash or blank all text. Restore from `code.bin.bak_clocktext` if needed.
- BCLIM size/format changes — if encode differs from original length, keep the archive entry.
- Broad image packs without `--only` that skip-fail half of NCommonIcon; scope keys and only replace intended PNGs.
- Shipping Azahar custom-texture packs as the real localization fix.
- `pe` repack that grows a PACK slot, or short zlib + trailing NUL / shrunk `cmp_len` into a compressed ARC (Options freeze / CESA-class crash).
- Treating MyroomHeader `optn_tex_*` as Options/clock titles (use NCommonMSel **5245**).
- **`splice_packages_into_img(bak, …, live MOD)`** when bak ≠ MOD — copies the whole bak over LayeredFS and wipes later EN packages (§12.5.1).
- Per-byte zopfli fine-tune loops on large ARCs (hangs for minutes); use seed retries + bounded scans instead.

### 11.2 Always

- Same-offset / same-length package splice into the **current** LayeredFS `img.bin`.
- Exact-length zlib for compressed ARCs (`unused_data == 0`); see §12.5.2 (zopfli gap-salt **or** SYNC_FLUSH empty-blocks; zero gaps first on large ARCs when needed).
- Backup before each feature deploy (`img.bin.bak_pre_<feature>`); test one change at a time; fully quit Azahar after `img.bin` changes.
- Verify asset identity (MAD≈0 vs dump) before patching “similar” filenames.

### 11.3 Abandoned approaches (do not revive blindly)

1. Global MakeStr UTF-8 hook at `FUN_005a1ec8` (`005A1EC8`) — cave outside `.text` crashed; cave in `.text` blanked all text.
2. Patching SysPopup / OptionClock pill buttons for square Back/Next.
3. Assuming TRB EN for `戻る`/`次へ`/`年`/`月`/`日` updates this confirm chrome.
4. Full `img.bin` rewrite.
5. `FUN_00249fd4` blood-type softkey drawer as clock buttons.
6. Treating prefecture pack `0x107` fill as clock title.
7. Treating `optn_tex_optionmenu_05` / MyroomHeader as Options or clock confirm titles.
8. **`pe` repack that grows a PACK** then selective `ie` rewrite — avoid; keep same package slot size.
9. **Zlib ARC replace with trailing NUL / shrunk `cmp_len`** — freezes Options (same class as CESA white boot). Must be an **exact-length** zlib stream (`unused_data == 0`).
10. **Options redeploy with bak as splice base** — wiped Confirm / Myroom / header EN (2026-07-20). Fixed in `deploy_msel_options_en.py`.

---

## 12. UI localization method

### 12.1 Decision tree (screen still JP despite EN TRB)

1. **GPU-dump** the visible chrome. Note W×H and whether RGB is empty (**alpha text**) vs full color (**baked control**).
2. **Opaque/colored control** (softkey, icon label): pixel-match BCLIM in `img.bin` → EngPatcher PNG → same-size splice. TRB edits will not change it.
3. **Alpha-only “text” that survives a DrawText nuclear remap:** still a **BCLIM** (often A8 menu plate/button). Trace filename strings in Ghidra (`Com_M_Sel_*_Text*.bclim`) → bind function → package. Do **not** assume DrawText.
4. **True runtime DrawText** (help/error lines, some titles): `DrawTextToPane` / MakeStr. Nuclear test: force all DrawText → if chrome stays JP, it’s textures.
5. **List/quest titles already EN but clipped:** TRB string too long for the capsule — **shorten EN** (pane font is global). See §12.6 (To-Do STRI 2837).
6. **TRB already EN for the same words:** wrong path (different asset or runtime buffer). Stop re-translating those keys.

### 12.2 Verify identity before patching

- Prefer MAD≈0 against dumps over filename similarity (`OptionClock` ≠ confirm softkeys).
- Confirm package via `image_map.py` + `ie`/`pe`; confirm fmt via `bclimutil.parse_bclim` (ignore Azahar dump “fmt” numbers).
- Shared softkeys (`Com_btn_*` in pkg 5238) affect **all** screens that use them — usually desirable for EN.

### 12.3 Practical loop

1. Hit the screen in Azahar → dump textures.
2. Classify (texture vs DrawText) using §12.1.
3. Patch the smallest surface (one BCLIM set, one TRB slot, or one call site).
4. Same-size splice + LayeredFS deploy → retest.
5. Document new dead ends / wins back into this file and the matching Cursor rule.

### 12.4 Clock confirm + Options — verified in-game (2026-07-20)

| Piece | Kind | Status |
|-------|------|--------|
| Back / Next | ETC1A4 BCLIM `Com_btn_{m,t}01_b` @ 5238 | **EN verified** |
| Confirm `決定` | ETC1A4 BCLIM `Com_btn_k01_b{,ON}` @ **5238** | Deployed (`OK`) — `tools/deploy_confirm_btn_en.py` |
| Clock header `３ＤＳ本体時計` | A8 BCLIM `Com_M_Sel_Plate_Text03_06_00` (+ `_01`) @ **5245** | **EN verified** (`3DS System Clock`) |
| Options header + buttons + Display/Sound plates | A8 BCLIM Text03 / Text04_04 @ **5245** | **EN** (Options / Display Settings / Sound Settings / Network / Password + plates) — `tools/deploy_msel_options_en.py` |
| Display Settings panel | RGBA4444 `Opt_TxtItem_{Help,Message}` + `Opt_HelpBtn_{A,B}_*` @ Option **5247** | **EN** (`Help Display` / `Message Speed` / `Every Time` / `Once`) — `tools/deploy_display_settings_en.py` |
| Sound Settings panel | RGBA4444 `Opt_txtItem_{SE,VOICE,MIC}` @ Option **5247** | **EN** (`SE` / `Voice` / `Mic Sensitivity`) — same script (also `deploy_sound_settings_en.py`) |
| Floating `初期設定` (Defaults) | outside `Lyt_Opt_Scene` / not in pkg **5247** | **unmapped** (not SJIS/UTF-8/NLP in romfs; not HelpBtn) |
| Message speed sample `メッセージ速度テストです。` | likely DrawText / TRB | **unmapped** (not in translations.json) |
| Options help line | DrawText / TRB | Already EN |
| 年 / 月 / 日 | Option06 A4 @ 5248 + date-format bytes | EN `Y`/`M`/`D` verified |
| Gallery home | A8 Text02 @ **5244** | Deployed (`Gallery` / Event / Illustration / Options) |
| Gallery **submenu white headers** | ETC1A4 `Com_MultiWin_W01_Text02_*` @ **5237** via `FUN_00255a18` | Deployed (`Gallery` / Event / Illustration / Dream / Special / Gallery Options) — `tools/deploy_multiwin_headers_en.py` (plates of same labels also in **5244**) |
| Gallery girl-select labels | ETC1A4 `Gallery_txt01..03` + RGBA4444 `Gallery_txt04..06` + `Gal_girl_select{M,N,R}` @ **5153** | Deployed (`Preview` / `Slideshow` / `All` + heroine names on list + Dream Gallery buttons) — `tools/deploy_gallery_common_en.py` |
| Communication home | A8 Text04 @ **5241** | Deployed (`Communication` / Girlfriend Comm. / Business Card / Wireless Battle) |
| Business Card submenu | A8 Text04_02 @ **5240** | Deployed (header + My/Friends/Direct Exchange/StreetPass) |
| Select Save Data / StreetPass / Friends headers | plates @ **5240** | Deployed |
| Friends list sort `受信日時` | RGB565 `Flist_Txt03` @ Card **4152** | Deployed (`Received`) |
| Profile header + field labels | A8 `Com_M_Sel_Plate_Text01_00_00` @ **5246** + RGB565 atlas `Profile_Info_Profile_t` @ **5252** | Deployed (`Profile` / First Name / Last Name / Birthday / M·D / Blood / Hometown; uniform size) — `tools/deploy_profile_en.py` |
| Myroom main buttons | ETC1A4 `main_tex_{yotei,sleep,mail,tel}_RGBA4_NEW` + `common_modoru_RGBA4` @ **5380** | Deployed (`Schedule` / `Sleep` / `Mail` / `Phone` / `Back`) — `tools/deploy_myroom_main_en.py` |
| Schedule header `予定入力` | ETC1A4 `scd_toptex_RBGA4` @ MyroomHeader **5575** | Deployed (`Schedule`) — `tools/deploy_schedule_header_en.py` (live-package splice) |
| Mail home | ETC1A4 `mail_toptex_RBGA4` @ **5575** + RGBA4444 `mail_tex_{jyusin,shinki}` @ **5207** | Deployed (`Mail` / `Inbox` / `New Mail`) — `tools/deploy_mail_home_en.py` |
| My Data home | ETC1A4 `mydata_toptex_RGBA4` @ **5575** + `mcmn_tex_{todo,status}` @ **5380** | Deployed (`My Data` / `To-Do List` / `Status`) — `tools/deploy_mydata_en.py` |
| Status / boyfriend-power stats | ETC1A4 `stat_tex_{undo,chisiki,kanse,miryoku}` @ **5501** + `Scd_Status_Tit_{M,K,S,C}` @ **5255** | Deployed (`Fitness` / `Intel`* / `Sense` / `Charm`; schedule titles use full `Knowledge`) — `tools/deploy_status_stats_en.py` |
| To-Do submenu | ETC1A4 `mydata_toptex_01..06` @ **5575** + RGBA4444 `Que_Txt01{b,d}` @ Quest **5253** | Deployed (headers + `To-Do List` / `History`) — `tools/deploy_todo_en.py` |
| To-Do History points | RGBA4444 `Que_Txt01c` @ Quest **5253** | Deployed (`Earned ToDo Points:`) — `tools/deploy_todo_hist_en.py` (rebuilds Quest from vanilla with 01b/01c/01d) |
| Play-day counter `N日目(曜)` | TOP `日目` + weekday `(月)`… inside **img.bin pkg 5508** (loose RomFS resident TRB is unused leftover) | Deployed (`N Day  (Mon)`) — `tools/deploy_day_counter_en.py` (**5508** is what matters; release resident file is only a convenient edit source) |
| Girl SMS / mail bodies | MDC `maildic_{m,n,r}.mdc` @ img.bin pkg **92** (UTF-8 records; **not** `dictionary/all2_u.bin`) | Deployed EN — `tools/translate_sms_en.py` → `tools/deploy_sms_maildic_en.py` (FF-pad to slot) |
| Data Management home | A8 Text05 @ **5242** | Deployed (`Data Management` / Delete / Export Save Data) |

**Ghidra bind sites (code.bin):**

| Addr | Name | Role |
|------|------|------|
| `001eb3dc` | `OptionMenu_BindBtnTextures` | Wires 4 Options buttons |
| `0020ad74` | `BindMSelBtnIconAndText` | Loads icon+text BCLIM by filename |
| `0020bcc0` | `OptionMenu_BindPlateTextures` | Plate header/text; slot **6** = clock title |

Button map from `OptionMenu_BindBtnTextures`:
0. `Btn_Text03_01` Display · 1. `Btn_Text03_02` Sound · 2. `Btn_Text04_04` Network · 3. `Btn_Text03_05` Password

`optn_tex_optionmenu_*` (MyroomHeader **5575**) has **no xrefs** for this screen — dead end.

### 12.5 Exact-zlib ARC splice (Options / clock plates / softkeys)

Compressed ARCs (e.g. NCommonMSel **5245** ~18672 B, NCommonIcon **5238** ~22519 B, Myroom **5380** ~134232 B) must be spliced **without** growing the PACK:

1. Decompress ARC from a **vanilla package extract** (from `img.bin.bak_pre_msel5245` if needed) — or from live when preserving prior EN in the same ARC.
2. Same-size BCLIM replace; for A8 **full-clear** canvas before drawing EN (avoids JP glyph stain).
3. Build an exact-length zlib stream (`unused_data == 0`) — see strategies below.
4. Write compressed blob back at original `cmp_off`; **do not** change entry `cmp_len` / headers / DMST.
5. `splice_packages_into_img(**live MOD_IMG**, img_data, [pkg], MOD_IMG)`.

#### 12.5.1 NEVER wipe live LayeredFS with bak

`splice_packages_into_img(src, …, dst)` **copies `src` → `dst` when paths differ**, then overlays packages.

```text
# BAD  — restores entire img.bin to bak_pre_msel5245, wiping Confirm/Myroom/etc.
splice_packages_into_img(bak_pre_msel5245, img_data, [5245], MOD_IMG)

# GOOD — vanilla bak only to extract pkg 5245; splice result into live MOD
splice_packages_into_img(MOD_IMG, img_data, [5245], MOD_IMG)
```

Incident (2026-07-20): Options redeploy used bak as splice base → Options EN returned but Confirm / My Data / Schedule headers reverted to JP. Recovery: restore newest feature bak (`bak_pre_confirm_btn`), re-apply Confirm + 5380 To-Do/Status; fix `deploy_msel_options_en.py`.

#### 12.5.2 Compression strategies

| Situation | Strategy |
|-----------|----------|
| zopfli length == slot | Use zopfli |
| Slight undershoot; zero gaps remain | Binary-search **urandom gap salt**; **retry seeds**. Avoid per-byte fine loops (hang on large ARCs) |
| Undershoot; zlib SYNC_FLUSH body fits under slot | `compress_exact_empty_blocks`: SYNC_FLUSH body + empty stored blocks (`remain >= 5` and `remain % 5 == 0`) |
| Large ARC (5380); zlib body > slot after prior EN | **Zero all inter-file pads first** (old urandom hurts zlib), then empty-block — worked for To-Do/Status |
| Shared header ARC **5575** | Rebuild all known `*_toptex_*` EN labels from vanilla in one pass; live single-label patches can clobber siblings |
| Soft AA overshoots slot | Trial hard edges / smaller glyphs (`deploy_msel_menus_en.py` pattern) |

**Do not:** `pe` repack (grows PACK); trailing NUL after short zlib; shrink `cmp_len`; bak→MOD wipe.

Tools: `deploy_msel_options_en.py`, `deploy_msel_menus_en.py`, `deploy_confirm_btn_en.py`, `deploy_mydata_en.py`, …  
Rollbacks: `img.bin.bak_pre_<feature>` under LayeredFS `romfs/`.

### 12.6 To-Do list titles (TRB, not BCLIM)

Numbered To-Do rows (e.g. 021–024) draw titles via `FUN_005c0e7c(..., pack=0x0600, slot)` → DrawText into Quest pane `Txt_Title` (`Lyt_Quest_o01`/`o02`).

| UI # | Slot | STRI | JP | EN (current) |
|------|------|------|----|--------------|
| 021 | 20 | 2835 | 写真を100枚撮る | Take 100 Photos |
| 022 | 21 | 2836 | 写真を500枚撮る | Take 500 Photos |
| 023 | 22 | 2837 | カノジョ専属カメラマン | Girlfriend's Personal Photographer (**overflows** capsule) |
| 024 | 23 | 2838 | 全スポットを解禁 | Unlock All Spots |

Also reused at pack `0x0601` slot 22. Source: `release/textresource/translations.json` → rebuild TRB with `patch_textresource.py`.

**Overflow fix:** shorten EN string — font size is **pane-global**, not per-line. Prefer e.g. `Personal Photographer` over shrinking every list row.

---

## 13. EngPatcher scripts and Cursor rules

### 13.1 Scripts

| Script | Purpose |
|--------|---------|
| `src/pack_images.py` | PNG → BCLIM → DARC same-size → img splice |
| `src/bclimutil.py` | BCLIM parse/encode helpers |
| `src/darcutil.py` | DARC extract / same-size replace |
| `src/image_map.py` | Folder key → package index |
| `src/patch_textresource.py` | TRB dump / translate / rebuild / inplace |
| `src/patch_code.py` | code.bin patches |
| `src/patch_drawtext_titles.py` | DrawTextToPane remap (help/other titles; **not** Options/clock chrome) |
| `src/patch_ui_titles.py` | Older FUN_0024842c-only remapper (superseded) |
| `src/patch_clock_text.py` | **Abandoned** global MakeStr experiment |
| `src/patch_cesa.py` | Boot CESA TEX + `compress_zlib_exact` helper |
| `tools/deploy_msel_options_en.py` | Options + clock-title A8 → exact zlib pkg **5245** (splice into **live** MOD) |
| `tools/deploy_msel_menus_en.py` | Gallery/Comm/Data A8 → pkgs **5244/5241/5242** (+ Business Card **5240**) |
| `tools/deploy_msel_opt_plates_en.py` | Soft re-render Options plates on live **5245** (best-effort; uses shared `exact_zlib`) |
| `tools/deploy_confirm_btn_en.py` | Confirm `決定` → `OK` ETC1A4 @ **5238** (lean trials + shared exact zlib) |
| `tools/deploy_title_main_menu_en.py` | **Main-menu hub rows** `Title_btn02_t01..t06` RGBA4444 @ **5261** (labels only; custom BCLIM/BCLYT black-screened — do not re-add yet) |
| `tools/deploy_cesa_en.py` | Boot CESA warning PNG → pkg **90** (`patch_cesa` exact zlib) |
| `tools/rebuild_bake_img.py` | Gold bake: PNG pack → TRB → ordered deploys → SMS → `release/bake_img.bin` + `name_input_code.bin` |
| `tools/fetch_release_bake.py` | Optional: download `bake_img.bin` + `romfs_overlay.zip` from nlpp-gold GitHub Release tag `gold` (`--best-effort` for Drop CIA fallback) |
| `src/patch_cia.py` | Decrypted CIA/3DS in → inject scripts + gold bake + TRB overlay + name patches → CIA out (+ `out/luma/` LayeredFS) |
| `src/extract_vanilla_from_rom.py` | Decrypt/extract vanilla `img.bin` + TRBs from dropped `.cia`/`.3ds` → `cache/vanilla_from_rom/` |
| `src/exact_zlib.py` | Shared exact-length zopfli / gap-tune / empty-block / near-miss |
| `tools/deploy_display_settings_en.py` | Display + Sound panel labels @ **5247** |
| `tools/deploy_sound_settings_en.py` | Sound-only subset of **5247** (HelpBtn note: not Defaults) |
| `tools/deploy_myroom_main_en.py` | Myroom buttons + Back @ **5380** |
| `tools/deploy_mydata_en.py` | My Data header **5575** + To-Do/Status **5380** (zero-gaps → empty-block) |
| `tools/deploy_schedule_header_en.py` | Schedule header @ **5575** (rebuild shared toptex set) |
| `tools/deploy_profile_en.py` | Profile header + field atlas |
| `tools/deploy_status_stats_en.py` | Fitness / Intel / Sense / Charm |
| `tools/deploy_todo_en.py` / `deploy_todo_hist_en.py` | To-Do submenu chrome |
| `tools/deploy_mail_home_en.py` | Mail home |
| `tools/translate_sms_en.py` | OpenAI-translate SMS maildic XML → `assets/sms_en/` |
| `tools/mdcutil.py` + `deploy_sms_maildic_en.py` | Pack EN SMS into MDC + splice img.bin pkg **92** |
| `tools/deploy_day_counter_en.py` | Play-day counter TRB + pkg **5508** |
| `tools/deploy_card_flist_en.py` | Friends list sort label |
| `tools/build_spotpass_inject.py` | SpotPass boss `info.dat` → `out/spotpass_*` (+ optional Azahar SDMC) |
| `tools/spotpass/` | Archived BOSS dump (`info.dat`, `.boss`, decrypted container) |
| `tools/restore_img_pre_msel5245.ps1` | Restore LayeredFS `img.bin` from pre-5245 bak |
| `tools/gdb_drawtext_capture.py` | GDB capture of DrawTextToPane `[r3+4]` + LR |

### 13.2 Cursor rules (`.cursor/rules/`, mirrored in EngPatcher)

| Rule | Mirrors this doc | Role |
|------|------------------|------|
| `read-docs-first.mdc` | §0 | Don’t restart from scratch; read this file + rules first |
| `nlpp-repo-workflow.mdc` | §§1, 3–5, 10 | Addresses, pack/deploy, TRB, tools |
| `patch-safety.mdc` | §11 | Hard bans and LayeredFS layout |
| `img-exact-zlib-deploy.mdc` | §12.5 | Exact-length zlib/zopfli; bak wipe ban; script map |
| `ghidra-mcp.mdc` | §1.1 | Ghidra MCP, VA conversion, known APIs |
| `ui-localization-method.mdc` | §12 | Texture vs TRB vs DrawText tree + chrome status |
| `clock-confirm-ui-localization.mdc` | §§6–9, 12.4–12.5 | Clock + Options + Confirm softkeys |

When RE discovers something durable, update **both** this file and the relevant rule so agents don’t diverge.

---

## 14. DrawText UI headers (capture → narrow patch → CIA)

### 14.1 Capture site

| Item | Value |
|------|--------|
| Function | `DrawTextToPane` `FUN_0054b880` |
| Runtime VA | `0x0064B880` (file + `0x100000`) |
| MakeStr object | `r3` on entry |
| C-string | `[r3+4]` — DrawText re-`MakeStr`s from this pointer (`ldr r1,[r3,#4]` @ `0054b8a4`) |
| Encoding | Match UTF-8, NLP codebook, and Shift-JIS of known titles (string absent from rom) |
| GDB tool | `tools/gdb_drawtext_capture.py` (JIT off; customs off) |

**Why not `FUN_0024842c` alone:** infinite-loop patch on that entry did **not** freeze opening clock confirm → header is not always on that drawer. `OptionClockPopSetup` *can* call `FUN_0024842c(..., 5, ClockSet+0x3c)` when flag `+0x38` is set, and `HeaderRelated_24a7d4` also calls `DrawTextToPane` directly. Shared choke point is **DrawTextToPane**.

### 14.2 Narrow patch

- Script: `src/patch_drawtext_titles.py`
- Hook: branch at `0054b880` → cave `0x68F7FC` (~1096 B table-driven exact-match remap)
- String pointers in the cave use **runtime VA** (`file + 0x100000`); file offsets alone miss guest RAM.
- Remaps only listed titles (clock / Options / Gallery set); other DrawText untouched
- Backup: `code.bin.bak_drawtext` (seeded from `.bak_titles` when present)
- Deploy: Azahar `load/mods/.../exefs/code.bin`, then CIA via `--inject-code`
- BLZ note: filling `.text` zero-pad grows compressed `.code` by a few hundred bytes; `inject_exefs_code` allows ExeFS growth (3dstool rebuild).

**Nuclear DrawText test (2026-07-20):** forcing every `DrawTextToPane` string to `"Options"` changed help/error text but **left Options header + four buttons Japanese**. Those chrome labels are **A8 BCLIMs** in `NCommonMSel` pkg **5245** (see §12.4–12.5), **not** MyroomHeader `optn_tex_*` and **not** DrawText.

DrawText remapper remains useful for true DrawText titles (Gallery strings, some help). Options/clock **menu chrome** uses §12.5 exact-zopfli BCLIM splice.

---

## 15. Gold bake / clone readiness retrospective (2026-07-22)

First successful **self-contained** gold bake on a clean clone (no sibling `New Love Plus Plus/extracted/`), then CIA patch. Record of what failed, what fixed it, and what not to repeat.

### 15.1 What we got wrong

| Mistake | Symptom | Root cause |
|---------|---------|------------|
| Assumed sibling dump always exists | `FileNotFoundError: vanilla … img.bin` on first drop | Clone only had EngPatcher + ROM; path `../New Love Plus Plus/extracted/` missing |
| Omitted `etcpak` from `requirements.txt` | `ModuleNotFoundError: etcpak` mid PNG pack | ETC1A4 BCLIM encode needs it; bat pip install couldn’t pull what wasn’t listed |
| Local exact-zlib forks in deploy scripts | `could not build exact zlib` / `could not hit exact zopfli` on **5245** plates, **5242**, etc. | Hand-rolled binary search without empty-block / near-miss; after Options filled the slot, soft plates overshot congruence |
| Confirm deploy: one heavy ETC1A4 style only | `zopfli 23082 exceeds slot 23047` @ **5238** | Live ARC already fat from PNG pack; no lean trials / zero-gaps / vanilla base |
| Day-counter assumed release resident TRB | `resident TRB not found` | Main TRB rebuild doesn’t emit resident; clone never copied `textresource_resident_jpn.trb` into `release/` |
| Treated NCommonMSel deploys as “main menu” | Hub rows stayed JP while Gallery submenu was EN | **Main Menu list = `Title.arc` pkg 5261** (`Title_btn02_t01..t06`), not Text02/03/04/05 plates |
| CESA left opt-in / off rebuild path | Boot warning stayed JP or vanished after ad-hoc patch | `pack_images` skips CESA unless `--only cesa` (white-boot history); no deploy until late |
| Patched bake but not Azahar LayeredFS | Emulator still showed JP hub + old CESA after “success” | `iter_deploy_targets` only mirrored Azahar when `NLPP_ALSO_AZAHAR=1`; bake ≠ what Azahar loaded |
| Misleading bat error after deploy failure | “Need a .cia / set NLPP_VANILLA_IMG” after zlib fail | Generic message ignored the real traceback |
| Old Drop CIA fell through without bake | English dialog + heroine names OK, **menus still JP** | Bat defaulted `PACKED_IMG` to `cache/new_img.bin` and could patch without `release/bake_img.bin`; menu chrome lives only in gold bake |
| Assumed git clone includes English menus | Clean machine “patched in minutes” with JP UI | `release/bake_img.bin` is **gitignored** (~680 MB); clone has sources + scripts, not the pre-baked `img.bin` |
| Ran `python tools\rebuild…` from inside `tools\` | `tools\tools\rebuild_bake_img.py` not found | CWD doubled the path |
| Added `timg/Eng_Patch.bclim` + edited `Lyt_Copyright.bclyt` (DARC grow) without abs BCLIM align | Title logo / chrome went **black** | Need `DarcArchive.insert_file_entry` + `rebuild_from_dir(..., align_mode="absolute")` + Pts_Copyright wire; bake now uses `deploy_title_engpatch_en.py` |

**Eng Patch badge (verified standalone — do not merge into `Copyright.bclim`):**

| Piece | Role |
|-------|------|
| `timg/Eng_Patch.bclim` | Separate ETC1A4 strip (`Eng Patch v1.0.0-rc1`); **white glyphs + thick black outline** (readable on Main Menu white column) |
| `timg/Copyright.bclim` | **Vanilla Konami only** — never overwrite with Eng text |
| `blyt/Pts_Copyright.bclyt` | `Pic_EngPatch` under `Nul_Copyright` (`ENG_PANE_TY=20`, `NUL_H=56`); DMST path, not `Lyt_Copyright` pics |
| Deploy | `tools/deploy_title_engpatch_en.py` (hub labels + Eng insert); bake list last-writer for **5261** |

Working recipe: Pts wire + standalone BCLIM (Aug 2026 confirm). Soft white-only fringe **vanishes** on Main Menu even when bake/CIA contain the strip — outline strength is the visibility fix, not “merge into Copyright.”

**Wrong Title asset wording (fixed in deploy):** old `assets/images/Title/Title_btn02_t04..t06` said “Save Data / Connection / Dating App”. Vanilla mapping is:

| BCLIM | JP | EN (deploy) |
|-------|----|-------------|
| `t01` | オプション | Options |
| `t02` | ゲームスタート | Game Start |
| `t03` | ギャラリー | Gallery |
| `t04` | データ管理 | Data Management |
| `t05` | コミュニケーション | Communication |
| `t06` | どこでもデート | Anywhere Date |

(`Title_btn02_01..06` are **32×32 icons**, not labels. Header “Main Menu” is TRB / `Title_menu_word`, already EN.)

### 15.2 What we got right

| Practice | Why it worked |
|----------|----------------|
| `release/bake_img.bin` as gold; `cache/` scratch | Drop-bat reuses bake in minutes; rebuild is the long path |
| `tools/rebuild_bake_img.py --rom <cia\|3ds>` + `extract_vanilla_from_rom.py` | Clone can seed vanilla from the dropped ROM → `cache/vanilla_from_rom/` |
| `--skip-pack` after PNG pack finished | Resume deploys/TRB/SMS without another ~16h pack |
| Shared `src/exact_zlib.py` for deploys | Gap-tune, empty-block, near-miss close 1–2 B misses local forks can’t |
| Soft-then-hard glyph trials | Soft AA prettier; hard 1-bit often the only fit under slot |
| Zero DARC inter-file gaps before measuring zopfli | Prior urandom salt inflates zlib on shared ARCs |
| Seed resident TRB into `release/textresource/` from vanilla/cache | Convenient same-size TOP blob to patch before splicing into pkg **5508** (RomFS resident path itself unused at runtime) |
| `deploy_title_main_menu_en.py` + `deploy_cesa_en.py` on rebuild list | Hub + boot warning covered in gold path |
| Softkeys / multiwin / gallery / UI buttons / keyboard tabs on rebuild list | Remaining chrome deploy scripts in `DEPLOY_SCRIPTS` |
| `release/name_input_code.bin` from bake | Drop-bat `--inject-code` for Profile romaji name-input |
| Mirror Azahar LayeredFS by default on deploy | Emulator tests match bake (`NLPP_ALSO_AZAHAR=0` to opt out) |
| Soft-skip redundant `opt_plates` when exact zlib fails | Options deploy already wrote those plates; don’t fail the whole rebuild |
| Drop CIA polls CI then rebuild; hard-stop without bake | Prevents silent “scripts-only” CIAs that look partially EN (§15.5) |
| `fetch_release_bake.py --best-effort` + `try_fetch_gold()` | 404 / missing Release → exit 1 quietly; bat falls back to local rebuild |
| `pytest` suite under `tests/` (§15.6) | Guards gold-bake resolution, fetch fallback, bat workflow strings |

### 15.3 Clone / first-drop checklist

1. Python 3.10+ + `pip install -r requirements.txt` (**must** include Pillow, numpy, zopfli, **etcpak**).
2. Drop known-dump `.cia` / `.3ds` / `.cci` on **`Drop CIA or 3DS Here to Patch.bat`** (or run `patch_cia.py` / `rebuild_bake_img.py --rom …` manually).
3. **If `release/bake_img.bin` is missing** (normal on a fresh clone), the bat runs the acquisition chain in **§15.5** — do **not** expect a finished CIA in minutes unless step 3a (CI download) succeeds or you already built a bake on that machine.
4. First **local** gold rebuild: expect **~16 hours** PNG pack, then deploys. Leave the window open.
   Subsequent full packs with unchanged assets reuse ``cache/img_pack/`` (BCLIM + exact-zlib) and are typically minutes (`--no-cache` to force).
5. After bake exists: drop again → **minutes** (reuse bake; no rebuild).
6. Resume mid-deploy only: `python tools/rebuild_bake_img.py --skip-pack` from **repo root**.
7. Testing in Azahar: fully quit the emulator; confirm LayeredFS `img.bin` was spliced (or re-drop CIA). Don’t assume bake alone updated mods.
8. CESA: use `deploy_cesa_en.py` / rebuild tail — not ad-hoc `pe` repack. Rollback: `bake_img.bin.bak_pre_cesa`.
9. Dev sanity: `pip install -r requirements-dev.txt && python -m pytest tests/ -v` (§15.6).

### 15.4 Package quick map (hub vs submenu)

| UI | Package | Deploy / note |
|----|---------|----------------|
| Boot CESA warning | **90** | `deploy_cesa_en.py` (not auto PNG-pack) |
| Main Menu **rows** + Eng Patch badge | **5261** Title.arc | `deploy_title_engpatch_en.py` (hub labels + `Eng_Patch.bclim`; replaces labels-only `deploy_title_main_menu_en.py` in bake) |
| Gallery / Comm / Data **homes** | **5244 / 5241 / 5242** | `deploy_msel_menus_en.py` |
| Gallery girl-select | **5153** | `deploy_gallery_common_en.py` |
| MultiWin headers (+ Delete Save Data) | **5237** | `deploy_datadelete_en.py` then `deploy_multiwin_headers_en.py` |
| Softkeys Back / Next / Confirm | **5238** | `deploy_confirm_btn_en.py` then `deploy_softkey_back_next_en.py` |
| Options chrome | **5245** | `deploy_msel_options_en.py` (+ optional opt_plates) |
| Keyboard mode tabs / popup buttons | **5190** / **5259** / … | `deploy_ui_buttons_en.py` then `deploy_input_keyboard_en.py` |
| Profile name-input (romaji) | ExeFS `code.bin` | `deploy_name_input_en.py` → `release/name_input_code.bin` (not in `img.bin`) |
| “Main Menu” title string | TRB / Title_menu_word | Already EN via textresource |

### 15.5 Gold bake acquisition workflow (Drop CIA — 2026-09-01)

Design goal: **self-contained clone** — everything needed to *build* the bake is in git; the bake binary itself is not. Optional **nlpp-gold** CI can publish a pre-built bake to skip the ~16h first run when that infra exists.

#### What git contains vs what a patched CIA needs

| Layer | In git? | Role |
|-------|---------|------|
| English dialog `.dbin2` | Yes (`rebuild_dbin2/`) | Injected into RomFS `script/bin/` |
| TRB overlay source | Yes (`assets/textresource/translations.json`) | Rebuilt into `release/romfs_overlay/` during bake |
| UI PNG sources | Yes (`assets/images/`) | Packed into `img.bin` during bake |
| Deploy scripts | Yes (`tools/deploy_*_en.py`) | Menu chrome splices during bake |
| **`release/bake_img.bin`** | **No** (gitignored) | Pre-packed English `img.bin` — **all menu textures** |
| **`release/romfs_overlay/`** | **No** (generated) | Patched TRBs auto-applied by `patch_cia` |
| **`release/name_input_code.bin`** | **No** (generated) | Profile romaji stack → ExeFS inject |

**Symptom cheat sheet:** English dialog + heroine name rewrites but **Japanese menus** → `img.bin` menu chrome never landed. Scripts/TRB/name patches do not replace bake.

#### Default Drop CIA flow (`Drop CIA or 3DS Here to Patch.bat`)

```text
decrypted .cia / .3ds / .cci dropped
  → pip install requirements.txt + setup_tools.py
  → SHA-1 gate (known dumps)
  → if release/bake_img.bin exists:
        use gold bake → patch CIA in minutes
  → else (fresh clone):
        1. fetch_release_bake.py --best-effort
             poll GitHub Release {owner}/nlpp-gold @ tag gold
             (owner from git remote or NLPP_GITHUB_REPO)
           success → release/bake_img.bin + romfs_overlay/
           fail (404, no repo, network) → continue
        2. if still no bake:
             rebuild_bake_img.py --rom <dropped ROM>
             (~16h first time; vanilla from cache/vanilla_from_rom/)
        3. if still no bake:
             HARD STOP — do not patch (prevents half-EN CIA)
  → patch_cia.py:
        inject rebuild_dbin2 + gold bake img.bin + romfs_overlay
        + apply_name_patches + optional --inject-code name_input_code.bin
  → out/NewLovePlusPlus-EN.cia + out/luma/
```

There is **no saved patch log file** by default — output is the console window only. Re-run with redirection if you need `[images]` / `[inject]` lines for diagnosis.

#### Environment overrides

| Variable | Effect |
|----------|--------|
| `NLPP_SKIP_GOLD_FETCH=1` | Skip GitHub Release poll; go straight to local rebuild (offline) |
| `NLPP_GITHUB_REPO` / `NLPP_GOLD_REPO` | Override nlpp-gold repo (`OWNER/nlpp-gold`) |
| `NLPP_GOLD_TAG` | Release tag (default `gold`) |
| `NLPP_WITH_IMAGES=0` | Scripts-only CIA — **no** menu chrome (explicit opt-out) |
| `NLPP_REPACK_IMAGES=1` | Dev: rebuild `cache/new_img.bin` PNG scratch only — **incomplete vs gold** |
| `NLPP_VANILLA_IMG` | Point rebuild at a vanilla `img.bin` if ROM extract fails |

#### nlpp-gold CI (optional accelerator)

When set up (`infra/README.md`), pushes to EngPatcher `main` can trigger an Ubuntu runner that publishes rolling Release tag **`gold`** with `bake_img.bin` + `romfs_overlay.zip`. The Drop CIA bat **polls this automatically** when local bake is absent.

**Not required** for the self-contained design — if CI is missing or returns 404, local `rebuild_bake_img.py` is the fallback. Manual fetch: `python tools/fetch_release_bake.py --repo OWNER/nlpp-gold --tag gold`.

#### `patch_cia.py` image resolution

`resolve_inject_img()` prefers `release/bake_img.bin` over `cache/new_img.bin` unless `--repack-images`. The bat always passes `--packed-img release/bake_img.bin` on the normal path.

### 15.6 Unit tests and CI (2026-09-01)

Regression guards for the gold-bake workflow and core helpers:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

| Test module | Guards |
|-------------|--------|
| `test_drop_bat_gold_flow.py` | Bat: CI poll before rebuild, `PACKED_IMG` → release bake, hard-stop without bake |
| `test_fetch_release_bake.py` | `try_fetch_gold()`, `--best-effort` exit codes, 404 → fallback |
| `test_patch_cia_gold_bake.py` | Gold bake preferred over PNG cache in inject path |
| `test_rebuild_bake_img.py` | `DEPLOY_SCRIPTS` includes menu chrome + ordering |
| Others | `patch_names`, `exact_zlib`, `nlpp_paths`, `image_map`, `img_pack_cache`, … |

GitHub Actions: `.github/workflows/test.yml` on push/PR to `main` / `Bleeding-Edge`.

**Out of scope for unit tests** (integration / manual): full PNG pack, CIA rebuild via makerom, per-screen Azahar verify, individual `deploy_*` texture splices.

---

## 16. SpotPass (BOSS NsData / とわのウォッチャー)

### 16.1 What this is (and is not)

| Item | Detail |
|------|--------|
| Feature | SpotPass / いつの間に通信 — boot-time BOSS NsData check |
| **Not** | In-game **Communication** menu (Girlfriend Comm / Business Card / Wireless Battle = StreetPass / local wireless) |
| Title | `00040000000F4E00` |
| Boss extdata ID | **`0x321`** (`extdata/00000000/00000321/boss/`) |
| NsDataId | **`1`** |
| Datatype | `0x10001` |
| Payload version | `0x500` |
| On-disk name | `info.dat` (game string + Azahar/Citra boss scan) |
| Archived content | 「とわのウォッチャー」第28号 |
| Dump credit | **Cetaceaqua** (provided the SpotPass archive) |

Vendored sources: EngPatcher `tools/spotpass/` (`info.dat`, `info.dat.boss`, `info.dat.boss.decrypted`). Builder: `tools/build_spotpass_inject.py` (default mode **`real3ds`**). These paths are tracked in git (see `.gitignore` exceptions) so a **GitHub clone can rebuild injects** with `python tools/build_spotpass_inject.py` after the SpotPass commit lands — no separate download.

`src/patch_cia.py` (and the drop bat) call this automatically after a successful patch → `out/spotpass_real3ds/`. Flags: `--skip-spotpass`, `--spotpass-mode {real3ds,azahar,azahar_exact}`, `--spotpass-install-azahar`.

### 16.2 How the inject file is made (shareable summary)

For title `00040000000F4E00`, the archived payload is a raw NsData blob (`tools/spotpass/info.dat`, **2324** bytes). The game does not use that file alone on disk — BOSS expects it as extdata:

`extdata/00000000/00000321/boss/info.dat`

**What we do to the file:** we do **not** change the payload contents. We prepend a **0x34-byte Boss header** (program ID, datatype `0x10001`, size, NsDataId `1`, version `0x500`) in front of the original 2324 bytes → **2376** bytes total for hardware / exact mode.

**On Azahar**, stock HLE has two issues:

1. The game tries to `ReadNsData` with a huge buffer (`0x7D004`) while the real payload is small — so we **zero-pad** the file to that size for the emulator (`--azahar`), or use an Azahar build that allows short reads (`--azahar-exact`).
2. `GetNsDataNewFlag` always returns `0`, so the boot prompt never treats the data as new — that needs a small Azahar fix/patch so the flag returns `1` when NsDataId `1` exists.

**On a real 3DS**, use the **exact** (unpadded) header+payload file, and put it **only** under `…/00000321/boss/` (create `boss` on PC/GodMode9 if FBI does not show it). Do **not** paste it into normal Extra Data / `user/` or you will break additional data.

### 16.3 How we accomplished the Azahar inject (RE detail)

1. **Located the payload** in Cetaceaqua’s archived CDN dump:
   - `info.dat.boss` — encrypted BOSS container (`boss` magic)
   - `info.dat.boss.decrypted` — cleartext container (headers + UTF-16 notification)
   - `info.dat` — NsData body, **2324** bytes (`0x914`)
2. **Parsed** the payload content header (program ID + size + NsDataId + version) from the decrypted container.
3. **Built** a Citra/Azahar `BossHeader` (**0x34** bytes = 0x18 extdata prefix + 0x1C payload content header fields, big-endian) + payload, matching Azahar `OnlineService::BossHeader`.
4. **Installed** under Azahar SDMC:

   `%AppData%\Azahar\sdmc\Nintendo 3DS\…\extdata\00000000\00000321\boss\info.dat`

5. **Hit two stock Azahar HLE bugs** (game path is correct; emulator stubs are not):

| Bug | Symptom | Workaround / fix |
|-----|---------|------------------|
| `ReadNsData` rejects short reads when the title asks for buffer **`0x7D004`** but payload is `0x914` | Log: `Invalid request to read 0x7D004 … payload length is 0x914` | Pad header+file to `0x7D004` (`--azahar`), **or** patch Azahar `online_service.cpp` to clamp/short-read like real BOSS |
| `GetNsDataNewFlag` always returns module default **`0`** | Boot dialog **“No SpotPass data found.”**; no `ReadNsData` | Return **`1`** when NsDataId exists under boss extdata (source map in `boss.cpp`), **or** binary-patch the stub so the IPC reply flag is `1` |

6. With both addressed (padded inject + flag returning `1`), cold boot proceeds past the “not found” gate and can `ReadNsData`.

**Ghidra / game anchors (image base 0):** `info.dat` consumers around `FUN_00608cac` / `FUN_00609ef4`; `SpotPass_TryReadNsData` @ `00609c98`; ReadNsData wrappers `FUN_0051eb8c` / IPC `FUN_0051f238`. CDN task strings include `PTASK01` / `PTASK02` and `https://npdl.cdn.nintendowifi.net/p01/nsa/QwyHOPV4LsvQ2I3U/`.

### 16.4 Implement in Azahar

```bash
cd NewLovePlusPlusEngPatcher
python tools/build_spotpass_inject.py --azahar
# exact size if your Azahar has the short-read clamp:
python tools/build_spotpass_inject.py --azahar-exact
```

- `--azahar` writes `out/spotpass_azahar/` and syncs live SDMC (unless `--no-install-azahar`).
- Relaunch Azahar after replacing `info.dat` (cold-boot NLPP to re-check SpotPass).
- Confirm the **running** `azahar.exe` is the one with the `GetNsDataNewFlag` fix (Programs install vs Documents build vs Desktop Localization Studio Fork are different binaries).
- Expect log: `GetNsDataNewFlag` with `ns_data_new_flag=0x01`, then `ReadNsData` success — not the ERROR dialog alone.

Upstream-style source fixes (for a proper rebuild):

- `core/hle/service/boss/online_service.cpp` — clamp `ReadNsData` length to remaining payload.
- `core/hle/service/boss/boss.cpp` / `boss.h` — per-NsDataId new-flag map; if uncached and entry exists → return `1`.

### 16.5 Implement on real hardware (CFW)

Nintendo’s SpotPass CDN will not re-serve this archive. Inject cleartext boss extdata (same approach as community Puzzle Swap BOSS pastes).

```bash
python tools/build_spotpass_inject.py
# → out/spotpass_real3ds/info.dat          (flat)
# → out/spotpass_real3ds/00000321/boss/info.dat
# → out/spotpass_real3ds/README.txt
```

Exact size only: **2376** bytes (`0x34 + 0x914`). **Never** use the Azahar HLE-padded ~512 KiB blob on a console.

1. Luma CFW; NLPP installed / run once so extdata `00000321` exists.
2. Enable SpotPass in the game’s **network / communication settings** if present (again: not the StreetPass Communication submenu).
3. Put `info.dat` **only** under `…/00000321/boss/` (create `boss` via PC or GodMode9 — FBI often has no SpotPass browse path). Leave `user/` alone.
4. Fully close the title, cold-boot, watch for the SpotPass apply prompt.

SD layout (ID0/ID1 are console-specific):

`Nintendo 3DS/<ID0>/<ID1>/extdata/00000000/00000321/boss/info.dat`

**Caveat:** Real BOSS also tracks “new” / arrived state in sysmodule DBs. Azahar invents entries by scanning boss files; hardware may still report “not found” if NsDataId `1` is not marked new. If paste alone fails, next steps are BOSS DB / proper container install paths (Luma unsigned BOSS), not re-padding the file. Pasting into Ext Save Data **without** `/boss` can corrupt **additional data** (追加データ) and show a “not compatible / not from this game card” style error.

### 16.6 File / size cheat sheet

| Artifact | Bytes | Notes |
|----------|------:|-------|
| `tools/spotpass/info.dat` | 2324 | Raw NsData payload (Cetaceaqua) |
| `tools/spotpass/info.dat.boss` | 9414 | Encrypted CDN container |
| `tools/spotpass/info.dat.boss.decrypted` | 9414 | Header source for builder |
| `out/spotpass_real3ds/info.dat` | 2376 | Hardware / exact |
| `out/spotpass_azahar/info.dat` | ~512056 | Stock Azahar HLE pad |

---

## 17. Profile name-input (gojūon romaji + direct insert) — 2026-08-31

Screen: Profile → First Name. Gojūon grid shows Hepburn; tap inserts romaji into the name field. Kanji candidate list is suppressed.

**Outcome:** scrap the candidate-list caves (C3/C4/B_Place @ `0x006FC000` etc.) — ship nullguards + romaji DrawCell cave + one NOP so mode-0 uses the ABC insert path.

### 17.1 Verified working LayeredFS stack

**Isolation (how name-input was proven):** Azahar **a/b** + **vanilla** `img.bin` / `code.bin.bak` — **not** bake alone. Full EN TRB maps gojūon `あ→A` and blanks those cells.

```bash
.\make.ps1 deploy-a      # name-input + name-kanji TRB on vanilla img
.\make.ps1 launch-a
```

**Combine with Bleeding-Edge bake UI** (EN chrome + working Profile keyboard):

```bash
.\make.ps1 combine-a     # instance A
.\make.ps1 combine       # roaming AppData
# or: python tools/deploy_bleeding_edge_name_input.py --refresh-artifacts
```

Writes: `bake_img.bin` + `name_input_code.bin` + **name-kanji** TRB (not full EN TRB). Drop-bat already injects `release/name_input_code.bin`; bake rebuild uses name-kanji TRB via `rebuild_bake_img.py`.

a/b guide: **`ab_test/README.md`**.

| # | Patch | Script | Role |
|---|-------|--------|------|
| 1 | Pane attach null parent | `src/patch_input_pane_registry_nullguard.py` | Skip `Pane_AttachToParent` @ `0x1fa790` when parent is 0 |
| 2 | SetDisplayMode +0x10 guard | `src/patch_input_candidate_nullguard.py` | Guard `0x1fbc08` / `0x1fbd24` |
| 3 | Fill-flag + mode clamp | `src/patch_input_candmode_fillflag_reset.py` | `+0x44=0`, clamp `+0x30` @ `0x1fa828` |
| 4 | Romaji DrawCell | `src/patch_input_romaji.py` | Hepburn labels **and** insert buffer; cave `@0x006FBB08` |
| 5 | Skip kanji list | `src/patch_input_kana_direct_insert.py` | NOP `@0x1fb070` — gojūon uses ABC insert path |

Umbrella rollback: `exefs/code.bin.bak_pre_name_input_en`. Optional mode-tab BCLIM: `tools/deploy_input_keyboard_en.py` (pkg **5190**).

**Live checklist:** **Hiragana/Kata** show Hepburn romaji on the gojūon grid (not an empty checkerboard); tap → romaji in name field; **Kanji** tab has no candidate list (empty candidate chrome is OK — the gojūon keyboard itself must still show keys); ABC/Lower still show Latin; name length still ≤8 chars.

### 17.2 Hard ban: `candmode_reset` (`+0x24 = 0`)

`src/patch_input_candmode_reset.py` **must not be deployed.** Bisect (vanilla → add one patch at a time):

- pane nullguard → taps OK  
- \+ candidate nullguard → taps OK  
- \+ **candmode_reset** → **taps dead**  
- fillflag_reset **without** candmode_reset → taps OK  

`nameInputObj+0x24` selects keyboard vs candidate identification/lookup tables inside `NameInput_OnCellTap` / fill helpers. Vanilla often shows stale non-zero heap (e.g. `0xffffffa6`) and **still works**. Forcing `+0x24=0` on every redraw makes OnCellTap match the wrong pane-name table → silent no-op taps.

### 17.3 Architecture notes (verified)

**Addresses (file / Ghidra base 0; VA = file + `0x100000`):**

| Name | File |
|------|------|
| Pane warmup / create+attach loop | `0x1fa2d0` … (absorbed into bogus mega-fn `FUN_000f9ea8` in Ghidra — re-split later) |
| `Pane_AttachToParent` call (create path) | `0x1fa790` |
| `NameInput_RedrawKeyboard` | `0x1fa81c` |
| `NameInput_FillKeyboard_Kanji` | `0x1fa918` (tail before shared epilogue `0x1faa20`) |
| `NameInput_OnCellTap` | `0x1faee4` |
| `NameInput_SetDisplayMode` | `0x1fba38` |
| `NameInput_FillCandidates` | `0x1fb438` (tail `strb +0x44=1` @ `0x1fb724`) |
| `NameInput_FillGridFromResourceTable` | (fills all 60 from TRB when tick allows) |
| `NameInput_TickDeferredGridFill` | `0x1fb964` (vtable; if `+0x44!=0` && `+0x540==0` → FillGrid…) |
| `NameInput_DrawCell` | `0x1fc304` |
| `Delegate_BindByKey` | `0x005eba00` |
| `Pane_AttachToParent` | `0x00545550` |

**Parent for attach is not “uninitialized luck” alone:** `Delegate_BindByKey` writes an out-struct at `sp+0x38`; field at `+4` (`sp+0x3c`) is the parent passed to attach. Live vanilla/modded (when Bind succeeds): `sp+0x38` stable (e.g. `0x82ee38`), `sp+0x3c` = per-cell parent stepping by `0x250`.

**Candidate packs:** runtime pack table for candidates is `0x7008`–`0x7033` (not keyboard-label pack `0x7002`). Cell metadata at `nameInputObj + cellIdx*0x10 + 0x180` (string / flags / pack / slot).

**gdb_probe gotcha:** `break` with `max-hits N` **detaches on the last hit without `continue`**, aborting the function. Attaching mid pane-warmup (e.g. 5/60 attaches) leaves a half-built, unclickable grid until a clean re-entry. Prefer post-fill tail breaks (`0x1faa20`, `0x1fb724`) or read-only `gdb_probe.py read`. Tool: `tools/gdb_probe.py` (Azahar gdbstub port `24689`).

**LayeredFS:** “vanilla ROM” still loads `mods\00040000000F4E00\exefs\code.bin` if present under the **active** Azahar user dir — use a/b instances or rename that folder to test true vanilla. Prefer `NLPP_AZAHAR_USER_DIR` → `out/azahar_instances/{a,b}/user` over roaming AppData while iterating.

**Live code caves (shipped stack only):**

| Pad | Contents |
|-----|----------|
| `@0x006E6A38` | Shared nullguard / fillflag caves (do not collide offsets below) |
| `@0x006FBB08` | Romaji DrawCell blob only (~4 KiB vanilla zero pad; RX — build strings on stack, not by storing into the cave) |
| `@0x1fb070` | Kana-direct = **single NOP** (no cave) |

Shared map `@0x006E6A38`:

| Offset | Patch |
|--------|--------|
| `+0x40` / `+0x60` | candidate nullguard |
| `+0x90` | pane-registry nullguard |
| `+0xC0` | fillflag_reset (`+0x44` / `+0x30`) |
| ~~`+0xA0`~~ | ~~candmode_reset — banned / never ship~~ |

**Scrapped caves (do not revive):** `@0x006FC000` was reserved for B_Place / C4 candidate-list placers (`FillCandidates` hooks, wipe+place ≤6 cells, SHOW/`+0x540` gymnastics). That whole path was abandoned — we **skip the kanji list** with the NOP at `@0x1fb070` and insert romaji via the DrawCell cave instead. Leave `@0x006FC000` empty unless a new experiment documents a fresh carve.

### 17.4 TRB

`tools/deploy_name_kanji_trb.py` — keep single CJK **and** single hiragana/katakana as JP for name-input keys (Latin-only EN mappings blank this font). Romaji path does **not** require changing gojūon TRB slots (DrawCell rewrite).

### 17.5 Abandoned approaches (removed from tree 2026-08-31)

We tried custom candidate UI (B_Place SHOW `0x1E`, C3 `MList` stripes, C4 left-column placer @ `0x006FC000`) and various hide/redraw hacks. **Scrapped** — product path is romaji keyboard + direct insert (§17.1). Do not revive without a fresh bisect:

- B_Place SHOW slot `0x1E` / hometown slots 1/7
- C3 `MList` stripe img splice (shared UV with gojūon → hybrid chrome)
- C4 left-column kanji placer (`FillCandidates` cave @ `0x006FC000`)
- Hide empty panes via `pane+0xb7`; SetDisplayMode → RedrawKeyboard/FillCandidates
- `candmode_reset` (`+0x24=0`)

### 17.6 Next steps

1. Header cleanup — title can show stray kanji + reading (DrawText, not DrawCell).
2. Name length — 8-char pane budget vs multi-letter Hepburn syllables.
3. Optional EN mode-tab BCLIM via `deploy_input_keyboard_en.py`.

| Symbol | File |
|--------|------|
| `NameInput_OnCellTap` | `0x1faee4` |
| Kana-direct NOP site | `0x1fb070` |
| `NameInput_DrawCell` | `0x1fc304` |
| Romaji cave | `0x006FBB08` |

---

## 18. Azahar a/b + CIA input policy (2026-08-31)

### 18.1 Dual Azahar instances

Scripts: `ab_test/` (call via root `.\make.ps1` / `Makefile`). Guide: **`ab_test/README.md`**.

| Item | Path / note |
|------|-------------|
| Instance user dirs | `out/azahar_instances/{a,b}/user` |
| Env override | `NLPP_AZAHAR_USER_DIR` / `AZAHAR_USER_DIR` |
| Machine paths | `ab_test/paths.local.ps1` (from `.example`; gitignored) |
| Default `deploy-a` | Name-input stack (§17) — swap scripts for other experiments |

Do **not** tell the user to quit Azahar between deploys (standing preference).

### 18.2 CIA patcher — no decryptor

`src/patch_cia.py` / drop bat accept **decrypted** `.cia` / `.3ds` / `.cci` only (`Crypto Key: None`). Encrypted input fails with a short “decrypt yourself first” message. `decrypt.exe` / Batch CIA 3DS Decryptor Redux were **removed** from the tree — users decrypt outside EngPatcher (GodMode9, etc.). Still vendored: `tools/cia/` `3dstool` / `ctrtool` / `makerom` / `seeddb`.

Offline `vendor/NLPPATCH/` snapshot was also **removed** (2026-08-31). Dialogue/TRB live in `rebuild_dbin2/` + `assets/`. Optional: `patch_textresource.py seed --alt-trb <other.trb>` if you bring an external EN TRB.

---

*Last updated 2026-09-01 — §15.5 Drop CIA gold-bake acquisition (CI poll → local rebuild → hard-stop); §15.6 pytest suite; §17 live caves only (scrapped C4 @0x006FC000); §18 a/b + no decrypt/vendor.*
