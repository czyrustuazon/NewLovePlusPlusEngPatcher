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
5. For volunteer HTML kits / Discord ingest: **§20** (and EngPatcher `tools/localization_workbench/`).

**Already settled (do not rediscover):**

- Clock Back/Next/Confirm = NCommonIcon pkg **5238** `Com_btn_{m,t,k}01_b` (pixel-matched; Confirm EN = `OK`).
- Header `３ＤＳ本体時計` is **not** a contiguous string in romfs/`code.bin`/`img.bin` (any common encoding) — see §9.
- Global MakeStr hook and full `img.bin` rewrite are banned — see §11.
- **Never** `splice_packages_into_img(bak, …, live MOD)` — copies bak over the whole LayeredFS img and wipes later EN packages (§12.5.1).
- **Main Menu hub rows** (ゲームスタート / オプション / …) = `Title.arc` pkg **5261** `Title_btn02_t01..t06` — **not** NCommonMSel Text02–05 (those are submenus). See §15.
- Gold bake / clone pitfalls and fixes: **§15** (acquisition workflow **§15.5**; unit tests **§15.6**; title-loop NX abort **§15.7**).
- Cold PNG-pack / exact-zlib speedup (empty-block-before-zopfli + `--pkg-workers` + zopfli pad; typically under an hour): **§12.5.3**.

- **Boot CESA warning** (pkg **90** TEX, not Zhoumaru / not `IMAGE_MAP`): `tools/render_cesa_en.py` 2× masks + companion `logo_white` blurb, then `deploy_cesa_en.py` — **§12.7**.

- **Girlfriend Comm. white header** (`カノジョ通信`) is MultiWin **5237** 192×16 ETC1A4, not the MSel plate. Full “Girlfriend Communication” fries that bar; shipped copy is **Heart to Heart** (**§12.4.1**).
- **Profile white header** (`プロフィール`) is A8 `Plate_Text01_00_00` @ **5246** 144×28. Ship Heisei W5 on a 16px strip (same as Heart to Heart), not MPLUS and not Zhoumaru paint — **§12.4.2**.
- **Profile Call / atlas labels** (`Last Name` / `Written` / `Called`) are RGB565 chroma @ **5252**. Use JP yellow/green/cyan **ramps** (2× Heisei), not 1-bit crush — **§12.4.4**.
- **Profile hometown region chips** (`全国` / `北海道東北` / …) are RGBA4444 `Profile_Btn_Com02_Text01..08` @ **5252**, not DrawText. Zhoumaru two-line EN overflowed the rounded pills — contain-fit to the 6px inset (**§12.4.3**).
- **Profile First Name / name-input:** `python tools/deploy_name_input_en.py` or `.\make.ps1 deploy-a` — **§17**. Never deploy `candmode_reset` (`+0x24=0` → dead taps).

- **Message Speed delays:** Options preview is `FUN_005d1e18` @ `0x005D1E18` (vanilla 18/12/6/0 → **14/8/2/0**). In-game TalkWindow table @ `0x006E3024` (vanilla 40/70/90/110/220 → **10/18/22/28/55**) plus tick cap `min(delay, table)` so voiced lines honor the slider — **§21**. Sample sentence is UTF-8 at `0x005D1928`, not TRB.

- **Azahar a/b instances:** `ab_test/README.md` — dual LayeredFS user dirs; do not tell the user to quit Azahar between tests.
- **Communications load hang on Azahar (2026-09-18):** not extra data `00000F4E`, not pkg **5237**. Stock `FSFile::OpenLinkFile` reset the clone to the full extra-data blob; **§10.1**.
- **Game Start hang on Azahar (2026-09-18):** same extra-data smash (`Write32 0x33373338`), but `OpenLinkFile` of the **parent** archive (`size≈1.62 GiB`, `subfile=false`). Clone patch does not help; reset unsticks it. **Not hardware.** **§10.2**.
- **Title hub loop NX abort (2026-09-18):** prefetch abort PC `0`, LR `0x00645A2C` (`FindPaneByName` `BLX r3`) — null child in the pane list (`r4=4`). Guard is `src/patch_lyt_null_pane.py` in `name_input_code.bin` — **§15.7**.
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

Under `NewLovePlusPlusEngPatcher/tools/nlpp-tools/` (vendored **[kiwiz/nlpp-tools](https://github.com/kiwiz/nlpp-tools)**):

| Tool | Role |
|------|------|
| `bin/ie` | Unpack package blob(s) from `img.bin` by index |
| `bin/pe` | Unpack/repack a package → `.arc` / `new_NNNN` |
| `opt/bin/png2bclim.exe` | Fallback BCLIM encode (often changes size — avoid when possible) |
| Python `img` module | Package/ARC model imported by `pack_images.py` and `deploy_*` |

These are **Python entrypoints** (invoke with `python ie …`), not Win32 native binaries.

**DARC on Windows:** use EngPatcher `src/darcutil.py` (same-size inject). The in-tree `opt/bin/darctool` ([yellows8/darctool](https://github.com/yellows8/darctool)) is a Linux ELF and is **not** invoked by deploy scripts. `png2texi.exe` ([deaknaew/png2texi](https://github.com/deaknaew/png2texi)) is bundled but unused on the gold UI bake path.

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

CESA is **not** in this map. Boot warning is `CESA_240X400.texi` inside img.bin package **90** (TEX, not BCLIM/ARC). See **§12.7**.

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

### 10.1 `OpenLinkFile` — Communications stuck on loading (2026-09-18)

**Symptom:** Main-menu **Communication** stays on the loading spinner. Guest is already dead.

**Log (instance A):**

1. `OpenLinkFile Path: [Binary: 0000…]` (was logged as STUBBED).
2. Unmapped `Read32` @ `PC 0x0010CAB4`.
3. Heap smash `Write32 0x33373338` @ `PC 0x0011531C` / `0x00120590`, then `WriteBlock` @ `PC 0x005EF4CC`.

**Not the cause (verified):**

| Suspect | Why it looks related | Why it is not |
|---------|----------------------|----------------|
| Title extra data `00000F4E` “broken” | Communications reads `LP_NET` / `LP_NET_CARD` | Archives present; same file set/sizes as instance B |
| SpotPass extra data `00000321` missing | Log: `Failed to open SpotPass ext data archive` | Boot SpotPass check only (§16). Not the StreetPass Communication menu |
| MultiWin pkg **5237** extras / zopfli salt | Timed with Girlfriend Comm. header work | Packages decompress `unused_data=0`; rolling **5237** back did not stop the smash |
| LayeredFS `img.bin.bak_*` in `romfs/` | Extra overlay files + `OpenLinkFile` in the same log | Still move baks to `_bak/` (`make.ps1 launch-a`); hang persisted with only `img.bin` + two TRBs |

**Cause:** Azahar `File::OpenLinkFile` created a new session but **did not clone** the current handle. 3dbrew / libctru: “opens a clone / duplicate handle.” The stub set `offset=0`, `size=backend->GetSize()`, `subfile=false`. NLPP opens an extra-data **subfile** (`OpenSubFile`) then `OpenLinkFile`. `GetSize` on the clone then returned the **entire** extra-data blob (tens–hundreds of MB). The game treated that as a small `NLPPARC` record and heap-walked ASCII as pointers (`0x33373338`).

**Fix (local Azahar, not CIA `img.bin`):** `File::OpenLinkFile` snapshots `priority` / `offset` / `size` / `subfile` from the source session *before* `ClientConnected`, then copies them onto the clone. `File::Close` must **not** close the shared backend while another session (the clone) is still live — that zeros later reads and brings the spinner back. Patch in this repo: `ab_test/patches/azahar-openlinkfile.patch`. `.\make.ps1 build-azahar` applies it if missing, rebuilds `citra_meta`, and copies `azahar.exe` into `out/azahar_instances/{a,b}/`. Default log line: `OpenLinkFile … clone offset=… size=… subfile=… backend=…`. Drop CIA does not need this — hardware FS clones handles correctly.

**Do not** restore extra data or re-splice **5237** / **5241** for this spinner. **Do not** treat missing `00000321` as a Communication-menu fix.

Texture dump (`Utility_DumpTextures`) floods `Texture size (1x1) is not multiple of 4` and makes a wedged guest look frozen. Leave it off while playtesting. Game Start can look the same with dump **off** — NLPP itself uses 1×1 textures, and a smashed guest keeps the GPU thread alive (**§10.2**).

### 10.2 Game Start hang — parent extra-data `OpenLinkFile` (2026-09-18)

**Symptom:** Tapping Main Menu **Game Start** sometimes freezes. Azahar **reset** tears down the guest (`GDBStub` stop + `Cleaning up process 11`) and the next boot can continue. Looks like a hang, not a crash dialog.

**Live instance A (2026-09-18):** `out/azahar_instances/a/azahar.exe` (`75134fc-dirty`, clone patch **present**). Log rotated to `user/log/azahar_log.old.txt`.

1. `OpenLinkFile Path: [Binary: 0000…] clone offset=0x0 size=0x65a13720 subfile=false backend=0x65a13720`  
   (`0x65a13720` ≈ **1.62 GiB** — ExtSaveData **quota / backend** size, not an on-disk file that large.)
2. Heap smash `Write32 0x33373338` @ `PC 0x0011531C` (file `0x0001531C`, `FUN_00015304` heap unlink), then `PC 0x00120590` / `WriteBlock` @ `PC 0x005EF4CC`. Same ASCII-as-pointer walk as **§10.1**.
3. GPU keeps logging `Texture size (1x1)` (`Utility_DumpTextures: false`) — wedged guest looks frozen.
4. Reset at ~122 s guest time: `Stopping GDB` + process-11 cleanup. That is why reset “fixes” it.

**Same smash as Communications, different FS shape:**

| | Communications **§10.1** | Game Start **§10.2** |
|--|--------------------------|----------------------|
| Game call | `OpenSubFile` then `OpenLinkFile` | `OpenLinkFile` on the **parent** extra-data handle |
| Stock Azahar | Clone reset to full blob (`subfile=false`) | Source **already** the full blob |
| `azahar-openlinkfile.patch` | Fixes — clone inherits the small window | **Does not help** — faithfully copies `size=0x65a13720`, `subfile=false` |
| Hardware | Clones the subfile | `GetSize` is the real extra-data file, not a 1.7 GiB quota |

**Not the cause:** gold bake `img.bin` / Title pkg **5261**, `name_input_code.bin`, extra-data “restore”, missing SpotPass `00000321`, pkg **5237**.

**Do not:** treat this as a Drop CIA / console bug; ship a `code.bin` workaround; restore extra data; re-splice menus. Remaining Azahar gap is `GetSize` / `OpenLinkFile` on the **parent** ExtSaveData archive reporting quota instead of an inner file. That is still HLE. Hardware FS will not expose this.

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
7. **ETC1A4 MultiWin 192×16 bar fried or pixel-y:** BCLIM, not TRB. Zhoumaru stem may be Network or an 8px strip. Full EN 2× as wide as Communication cannot keep ~13px cores — shorten the **bar** copy (Girlfriend Comm. → **Heart to Heart**, **§12.4.1**). Never LANCZOS-fill a plate onto this bar.

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
| Quit `やめる` | ETC1A4 BCLIM `Com_btn_y01_b{,ON}` @ **5238** | Deployed (`Quit`) — Zhoumaru `NCommonIcon.check`; `tools/deploy_softkey_quit_en.py` (Save Export confirm, shared) |
| Clock header `３ＤＳ本体時計` | A8 BCLIM `Com_M_Sel_Plate_Text03_06_00` (+ `_01`) @ **5245** | **EN verified** (`3DS System Clock`) |
| Options header + buttons + Display/Sound plates | A8 BCLIM Text03 / Text04_04 @ **5245** | **EN** (Options / Display Settings / Sound Settings / Network / Password + **Communication Settings** plate) — `tools/deploy_msel_options_en.py` / `deploy_msel_opt_plates_en.py` |
| Password entry window `パスワード` | ETC1A4 `Pass_Win01` @ OptionPassword **5251** | **EN** (`Password`) — `tools/deploy_optionpassword_en.py` (Zhoumaru; not DrawText) |
| Password entry header `パスワード入力` | A8 rewrite of `Com_M_Sel_Plate_Text03_05_00` @ **5245** (`OptionMenu_BindPlateTextures` slot 5) | **EN** (`Password Input`) — Zhoumaru. Vanilla plate is ETC1A4 and misses the slot; encode as A8 like the other Options plates. MultiWin `Text03_05` @ **5237** is a different bind (`FUN_00255a18` idx 0x1f), not this screen. |
| Display Settings panel | RGBA4444 `Opt_TxtItem_{Help,Message}` + `Opt_HelpBtn_{A,B}_*` @ Option **5247** | **EN** (`Help Display` / `Message Speed` / `Every Time` / `Once`) — `tools/deploy_display_settings_en.py` |
| Sound Settings panel | RGBA4444 `Opt_txtItem_{SE,VOICE,MIC}` @ Option **5247** | **EN** (`SE` / `Voice` / `Mic Sensitivity`) — same script (also `deploy_sound_settings_en.py`) |
| Floating `初期設定` (Defaults) | ETC1A4 `Com_btn_sy01_{a,b}` @ **5238** (not pkg **5247**) | **EN** (`Restore Default`) — Zhoumaru `NCommonIcon.check`; `tools/deploy_softkey_defaults_en.py`. Twin BCLIM also in Common02Icon **4184** `C_Com_icon_Sy` (already in bake). |
| Message speed sample `メッセージ速度テストです。` | UTF-8 in `code.bin` @ `0x005D1928` + typewriter `FUN_002d544c` | **EN** (`This is a text-speed test.`) — in-place pool rewrite in `patch_message_speed.py` §21.7 |
| Extra-data recreate warning `作成には時間がかかるので…` | DrawText / TRB STRI **4429** (`Lyt_C_Com_Win01` `Tex_Sentence`; SysPopup). Not `Com_Win_Warning` BCLIM (that is empty chrome). | **EN** — `translations.json`. Sibling create/start strings STRI 4431–4434. |
| Anywhere Date empty list `デートデータがありません。「デートの編集」から…` | DrawText / TRB STRI **25183** on `Lyt_De0200` Opt_Win (no body BCLIM; DateEdit `De_*_Txt` are short labels). | **EN** — full JP key in `translations.json`. A truncated key ending `デートを作` never matched, so LayeredFS kept JP. |
| Options help line | DrawText / TRB | Already EN |
| 年 / 月 / 日 | Option06 A4 @ 5248 + date-format bytes | EN `Y`/`M`/`D` verified |
| Gallery home | A8 Text02 @ **5244** | Deployed (`Gallery` / Event / Illustration / Options) |
| Event Gallery rows | A8 `Com_M_Sel_Btn_Text02_01_01..04` @ **5244** | Zhoumaru `NCommonMSel(4).check`: Memory / Dream After / Trip Memory / Drama Gallery |
| Event Gallery girl-list headers `告白までの思い出` / `旅の思い出` / `青春の１ページ` | ETC1A4 MultiWin `Text02_01_01..04` @ **5237** + A8 plates @ **5244** | Zhoumaru plates **Confession Memories** / **After the Dream** / **Trip Memories** / **Youthful Page** (MultiWin `01_01` PNG is Friend's Memory — do not use) |
| Gallery **submenu white headers** | ETC1A4 `Com_MultiWin_W01_Text02_*` @ **5237** via `FUN_00255a18` | Deployed (`Gallery` / Event / Illustration / Dream / Special / Gallery Options) — `tools/deploy_multiwin_headers_en.py` (plates of same labels also in **5244**) |
| Gallery girl-select labels | ETC1A4 `Gallery_txt01..03` + RGBA4444 `Gallery_txt04..06` + `Gal_girl_select{M,N,R}` @ **5153** | Deployed (`Preview` / `Slideshow` / `All` + heroine names on list + Dream Gallery buttons) — `tools/deploy_gallery_common_en.py` |
| Communication home | A8 Text04 @ **5241** | Deployed (`Communication` / Girlfriend Comm. / Business Card / Wireless Battle) |
| Girlfriend Comm. session rows `２人会話を募集` / `３人会話を募集` / `会話に参加` | A8 `Com_M_Sel_Btn_Text04_01_04..06` @ **5241** | Zhoumaru `NCommonMSel(7).check`: **Find Two-Person Chat** / **Find Three-Person Chat** / **Join Chat** — `deploy_msel_menus_en.py` |
| Girlfriend Introduction / Double Date rows | A8 `Com_M_Sel_Btn_Text04_01_07..10` @ **5241** | Zhoumaru: **Introduce Girlfriend** / **Get Introduced** / **Find Couple** / **Join Double Date** |
| Girlfriend Comm. white header `カノジョ通信` | ETC1A4 MultiWin `Text04_01_00` (+ `01_01`) @ **5237** + A8 plate `Plate_Text04_01_01` @ **5241** | **Heart to Heart** — see **§12.4.1**. Menu row stays **Girlfriend Communication**. Loading hang was Azahar `OpenLinkFile` — **§10.1**. |
| Business Card submenu | A8 Text04_02 @ **5240** | Deployed (header + My/Friends/Direct Exchange/StreetPass) |
| Select Save Data / StreetPass / Friends headers | plates @ **5240** | Deployed |
| Friends list sort `受信日時` | RGB565 `Flist_Txt03` @ Card **4152** | Deployed (`Received Date`; Heisei W5 hard cyan ~200px — Zhoumaru fill was 4× vanilla ink and remapped as a slab) |
| Profile header + field labels | A8 `Com_M_Sel_Plate_Text01_00_00` @ **5246** + RGB565 atlas `Profile_Info_Profile_t` @ **5252** | Header **Profile** — see **§12.4.2**. Field labels Heisei W5 size 15 2× AA + vanilla chroma ramps (First Name / Last Name / Birthday / M·D / Blood / Hometown) — **§12.4.4**, `tools/deploy_profile_en.py` |
| Profile Written/Called names | RGB565 `Profile_Info_Call01_t` @ **5252** | Deployed (`Last Name` / `First Name` / `Written` / `Called`; chroma AA, not 1-bit) — **§12.4.4**, `tools/deploy_profile_en.py` |
| Profile hometown region chips `全国` / `北海道東北` / … | RGBA4444 `Profile_Btn_Com02_Text01..08` @ **5252** | Deployed (Zhoumaru: Nation / Hokkaido Tohoku / Kanto / Chubu / Kinki / Chugoku Shikoku / Kyushu Okinawa). Two-line EN is contain-fit to a **6px** side inset so it stays inside the rounded pill — **§12.4.3**. |
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
| Boot CESA anti-piracy warning | RGB TEX `CESA_240X400.texi` @ pkg **90** (240×400 visible) | **EN** — NLPPPATCH Heisei Gothic, vanilla layout; **§12.7** |
| CESA companion blurb | RGB TEX `logo_white.texi` @ pkg **90** (CesaLogo `0x5A0008`; **240×320** portrait; vanilla 16×16 stub) | **EN** (verified 2026-09-15) — teal gothic; PACK rebuild **+ idx `dec_len` 1576192** + skip 400×400 stub quad; **§12.7** |

**Ghidra bind sites (code.bin):**

| Addr | Name | Role |
|------|------|------|
| `001eb3dc` | `OptionMenu_BindBtnTextures` | Wires 4 Options buttons |
| `0020ad74` | `BindMSelBtnIconAndText` | Loads icon+text BCLIM by filename |
| `0020bcc0` | `OptionMenu_BindPlateTextures` | Plate header/text; slot **6** = clock title |
| `00255a18` | MultiWin header bind | Filename table ~`0x6c3f9c`; Girlfriend Comm. bar = `Text04_01_00` |
| `0016f338` | `CesaLogo` ctor | `+0x60` / `+0x64` constructor IDs (pkg **90** TEXI, **1-based**) |
| `0016ec1c` | `CesaLogo` state 2 | `FUN_005af3ac` bind; `0x5A0008` 400×400 stub quad @ `0x0016ed84` |
| `00598ff4` | TEXI lookup | `(id & 0xffff) - 1` → TEXI index |

Button map from `OptionMenu_BindBtnTextures`:
0. `Btn_Text03_01` Display · 1. `Btn_Text03_02` Sound · 2. `Btn_Text04_04` Network · 3. `Btn_Text03_05` Password

`optn_tex_optionmenu_*` (MyroomHeader **5575**) has **no xrefs** for this screen — dead end.

#### 12.4.1 Girlfriend Comm. white header — Heart to Heart (2026-09-18)

The thin white bar on Girlfriend Communication is **not** DrawText, not TRB, and **not** the 144×28 MSel plate that `find_ui_png` prefers by filename.

| | |
|--|--|
| Bind | `FUN_00255a18` table ~`0x6c3f9c`; `Text04_01_00` pointer @ file `0x006c4030` |
| Live BCLIM | ETC1A4 `Com_MultiWin_W01_Text04_01_00` (+ sibling `01_01`) @ pkg **5237**, **192×16** |
| Home-menu row | A8 `Com_M_Sel_Btn_Text04_01_01` @ **5241** (Zhoumaru; stays **Girlfriend Communication**) |
| Help blurb | TRB DrawText (shortened to five lines in `53010b1`; not this bar) |

**Zhoumaru files do not match the live bar**

| Stem | What the PNG actually is |
|------|--------------------------|
| MultiWin `Text04_01_00` | **Network** (wrong screen) |
| MultiWin `Text04_01_01` | Cramped **8px-tall** 192×16 strip of the long EN title |
| MSel `Plate_Text04_01_01` | Same 192×16 strip, while the live plate BCLIM is **144×28** |

`Communication` / `Double Date` look smooth because Zhoumaru painted them **native 192×16** with ~13px glyph height, dark ink **(68,68,68)**, and a few gray AA ramps (~989 ink px, bbox ~48–142). ETC1 4×4 blocks keep those cores.

**What failed (do not repeat)**

1. Canvas-fit / glyph-fill the 8px plate onto the 192×16 bar (LANCZOS + threshold = “deep fried”).
2. Override `01_00` → `01_01` and ship that cramped strip as-is (still fried).
3. Letterbox-contain `01_01` onto the 144×28 plate (readable but tiny).
4. Self-render the **full** phrase `Girlfriend Communication` at 192×16:
   - MPLUS 2× bilinear, white RGB: max alpha ~216, ~11px, ETC1 eats hairlines (“broken lined”).
   - Heisei W5 1-bit + 4× dilate + nearest: readable, but chunkier than Communication. That is the **format ceiling** for ~24 letters on this bar.

**What shipped**

Shorten the **bar copy** to **Heart to Heart** (カノジョ通信). Heisei W5 size 15, 2× bilinear, ink (68), alpha normalized to 255: bbox **47–143**, gh **12** — same scale as Communication. Skip both Zhoumaru MultiWin files (`SKIP_UI_PNG`) and font-render (`render_header_aa` in `deploy_common.py`). Plate `Plate_Text04_01_01` @ **5241** uses the same wording at 144×28 `target_h=13` (do not glyph-fill the 8px PNG).

Redeploy: `python tools/deploy_msel_menus_en.py --only 5241` then `python tools/deploy_multiwin_headers_en.py` (extras pass; exact-zopfli pad, splice live bake + instance A). Do **not** treat a Communications **loading** spinner as a 5237 fault — that is Azahar `OpenLinkFile` (**§10.1**).

`find_ui_png` / `fit_png_to_canvas` must **never** resample a mismatched master onto dest **(192, 16)**. `contain_no_upscale` is the letterbox helper if a strip must sit on a taller plate without upscaling glyphs.

#### 12.4.2 Profile white header — match Heart to Heart (2026-09-18)

The Profile screen title is the same *kind* of white bar as Girlfriend Communication, but it is **not** MultiWin **5237**. Filling the 144×28 A8 plate with MPLUS made “Profile” look unlike Heart to Heart / Communication.

| | |
|--|--|
| Live BCLIM | A8 `Com_M_Sel_Plate_Text01_00_00` @ pkg **5246**, **144×28** |
| Shared renderer | `render_header_aa` / `chrome_font` in `deploy_common.py` (Heisei W5 index 1, ink **(68,68,68)**, `HEADER_CORE_PX=15`, `HEADER_STRIP_H=16`) |
| Field atlas / Call / hometown | RGB565 Call/atlas labels are chroma AA, not 1-bit crush — **§12.4.4**. Hometown chips stay Zhoumaru @ **5252** — **§12.4.3**. |

**Zhoumaru files exist but are the wrong look**

| Stem | What the PNG actually is |
|------|--------------------------|
| `NCommonMSel.check` `Com_M_Sel_Plate_Text01_00_00` | Native 144×28 painted **Profile** (~13px). Same family as other Zhoumaru plates, **not** the Heisei Heart to Heart bar. |
| `Profile.check` `Profile_Plate_Text01` | 128×16 **Profile** (different canvas; not the 5246 plate). |
| `Title.check` `Profile_Plate_Text01` | Misnamed — reads **ToDoList**. |

Heart to Heart skipped Zhoumaru because those stems were Network / an 8px strip (**§12.4.1**). Profile *does* have a correct-stem Zhoumaru PNG; we still font-render so the title matches the main-menu bars the player already saw.

**What shipped**

Paint Heisei W5 size 15 on a **16px** strip (gh **12**, same as Heart to Heart at 192×16), then center that strip on the 144×28 A8 canvas. Do **not** start `render_header_aa` at 28px tall — size 15 on the full plate would be larger than the MultiWin bar. Soft AA zopfli is **1719**; pkg **5246** ARC slot is **1725**. The old trial cap **1651** is stale — it forced `hard=True` 1-bit and undid the AA match. `patch_header_arc(..., slot_len=cmp_len)` uses the live slot.

Redeploy: `python tools/deploy_profile_en.py` (bake + instance A via `_iter_splice_imgs`). Fully quit Azahar so LayeredFS reloads.

**Do not**

1. Re-render this header with MPLUS / JP glyph-height (`render_en_alpha` before `c6b3f9e`).
2. `find_ui_png` the Zhoumaru Profile plate to “use the pack” — that is a different gothic than Heart to Heart.
3. Glyph-fill `Profile_Plate_Text01` (128×16) onto 144×28.
4. Gate the soft-AA trial on a hardcoded 1651-byte budget.

#### 12.4.3 Profile hometown region chips (2026-09-18)

The Hometown dropdown (`▼全国` / `北海道東北` / `関東` / …) is **not** DrawText and **not** TRB. It is RGBA4444 text overlays on rounded pills.

| | |
|--|--|
| Live BCLIM | `Profile_Btn_Com02_Text01..08` @ pkg **5252**, **64×24** fmt **8** |
| Pill chrome | `Profile_Btn_Com02_Color` is ETC1A4 **80×40**; text sits in the inner 64×24 |
| Masters | Zhoumaru `Profile.check/timg/Profile_Btn_Com02_Text01.png` … `Text08` |
| Deploy | `fit_region_png` in `tools/deploy_profile_en.py` then exact-zlib splice **5252** |

| Stem | EN (Zhoumaru) | Notes |
|------|----------------|-------|
| Text01 / Text02 | ▼/▲ Nation | Collapsed / expanded `全国` |
| Text03 | Hokkaido Tohoku | Two-line |
| Text04 | Kanto | One-line; already fit |
| Text05 | Chubu | One-line; already fit |
| Text06 | Kinki | One-line; already fit |
| Text07 | Chugoku Shikoku | Two-line |
| Text08 | Kyushu Okinawa | Two-line |

Vanilla JP (even 北海道東北) is **one line**, glyph box **52×12**, **6px** pad on every side of the 64×24 overlay. Zhoumaru two-line paint filled ~55×21 (pad ~4–5 / 1–2), so Hokkaido / Chugoku / Kyushu clipped the rounded 80×40 pill.

**What shipped**

Keep Zhoumaru paint. `fit_region_png` contain-scales any glyph bbox that exceeds inner **52×18** (`REGION_PAD_X=6`, `REGION_PAD_Y=3`) and recenters it. Kanto / Chubu / Kinki stay native. Do **not** font-render these chips (Heisei two-line is a different gothic than the pack).

Redeploy: `python tools/deploy_profile_en.py` (bake + instance A). Gold PNG pack still skipped these — they only land via this deploy.

**Do not**

1. Canvas-fill the 64×24 overlay with two-line EN (clips the pill).
2. Treat this list as StreetPass / Card / TownVoice (wrong packages).
3. LANCZOS-fill onto a different canvas size; the BCLIM is already 64×24.

#### 12.4.4 Profile Call / atlas labels — chroma AA (2026-09-18)

Verified in-game: **Last Name** / **Written** / **Called** now match the **Profile** header and **Clear** / **Delete** instead of looking deep-fried. **Not word count** — those strings are short.

| | |
|--|--|
| Live BCLIM | RGB565 `Profile_Info_Call01_t` (+ Call02 + `Profile_Info_Profile_t`) @ pkg **5252**, **240×152** |
| Header (good) | A8 `Plate_Text01_00_00` @ **5246** — real alpha AA |
| Clear / Delete (good) | RGBA4444 `Profile_Btn_Clear_*` / `Profile_Btn_Com01_Text07` — painted AA |
| Why it fried | `render_hard_label` crushed to **3 colors** (yellow / green / cyan). Vanilla JP uses **~18** chroma ramps. |

**Vanilla Call01 unique colors (do not flatten)**

Yellow key `(255,226,0)` (most of the atlas). Plate `(49,129,0)` plus G steps `133…157`. Ink `(49,157,255)`. Mid AA is the same G steps with **B=131**. Cyan remaps to dark text in UI; yellow keys out to the bar/cell.

**What failed**

1. 1× Heisei + threshold (`dist > 40` → solid ink). Same gothic as the header, still 1-bit.
2. Soft yellow↔cyan lerp without snapping to the JP palette (DataDelete: pale outlined mush).
3. Atlas ink `(160,210,230)` — not vanilla cyan `(49,157,255)`.
4. Zhoumaru `Profile_Info_Call01_t.png` is gray AA **Written :** / **Called As :** — different copy, not chroma.

**What shipped**

`render_hard_label` in `tools/deploy_profile_en.py`: Heisei W5 size 15, **2× bilinear** (same as the header), lerp **plate→ink** (JP green halo), quantize to `CALL_PALETTE`. Box fill stays yellow key or green plate. Field atlas uses the same path. Deployed unique colors went **3 → 9** (subset of the JP ramps).

Redeploy: `python tools/deploy_profile_en.py` (bake + instance A).

**Do not**

1. Crush Call/atlas glyphs to 1-bit “because chroma cannot AA.”
2. Blame overflowing English — **Last Name** / **Written** / **Called** all fit size 15.
3. `find_ui_png` the Zhoumaru Call01 mock for this BCLIM.

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

**Cold-build order in `compress_to_exact_slot` (2026-09-05):** fast → slow. Do **not** start with zopfli.

| Priority | Situation | Strategy |
|----------|-----------|----------|
| 1 | Level-9 SYNC_FLUSH body fits under slot | `compress_exact_empty_blocks` (stdlib zlib + empty stored blocks; `remain >= 5` and `remain % 5 == 0`) — **no zopfli** |
| 2 | Fits but congruence miss | Gap-salt + empty-block (`compress_exact_with_gap_tune`) — still zlib-speed |
| 3 | Large ARC; prior urandom salt bloated body | **Zero all inter-file pads**, then empty-block again |
| 4 | zlib body already larger than slot budget | Escalate to **zopfli**; binary-search gap salt / near-miss for exact length |
| — | Soft AA overshoots slot | Trial hard edges / smaller glyphs (`deploy_msel_menus_en.py` pattern) |
| — | Shared header ARC **5575** | Rebuild all known `*_toptex_*` EN labels from vanilla in one pass |

`try_fast_exact_slot` / `zlib_body_fits_slot` gate step 1–3. Finished `zlib.compress()` / zopfli blobs **cannot** have empty blocks appended (stream already closed with final block + Adler) — empty pads only apply to SYNC_FLUSH raw bodies.

**Do not:** `pe` repack (grows PACK); trailing NUL after short zlib; shrink `cmp_len`; bak→MOD wipe; per-byte zopfli fine-tune on large ARCs (`--fine-tune` is opt-in only).

Tools: `deploy_msel_options_en.py`, `deploy_msel_menus_en.py`, `deploy_confirm_btn_en.py`, `deploy_mydata_en.py`, …  
Rollbacks: `img.bin.bak_pre_<feature>` under LayeredFS `romfs/`.

#### 12.5.3 Cold PNG-pack speedup (2026-09-05)

Historical first-run gold bake was **~16 hours**, dominated by sequential **zopfli** exact-length searches (one heavy compress per binary-search / near-miss trial per changed ARC element). Three changes cut that without relaxing slot constraints:

**A. Empty-block / zlib before zopfli** (`src/exact_zlib.py`)

Previously `compress_to_exact_slot` always ran zopfli first, then fell back to empty-block. That paid zopfli’s CPU cost even when stdlib zlib already fit under `cmp_len`. New order:

1. `zlib_body_fits_slot` — if level-9 SYNC_FLUSH + one empty block already exceeds the slot, skip straight toward zopfli (after a zero-gaps retry).
2. Else `try_fast_exact_slot` → empty-block → gap-tune empty-block → zeroed-gaps empty-block.
3. Only then `compress_exact_zopfli` (binary-search salt, bounded near-miss ThreadPool, then empty-block fallback).

Game constraints unchanged: stream length == slot, `unused_data == 0`, same-size BCLIM / package splice.

**B. Package-level `ProcessPoolExecutor`** (`src/pack_images.py`)

PNG→BCLIM was already threaded; packages were sequential. Now:

- Main thread: `ie` unpack + `pe` unpack all packages, then splice finished blobs into `img.bin`.
- Workers (`_process_one_package`): convert PNGs + exact-zlib repack; return picklable result dicts.
- `--pkg-workers` (default `min(8, cpu//2)`); `--workers` = per-package PNG threads (lowered automatically when `pkg_workers > 1` to avoid oversubscribe).
- Shared `cache/img_pack/` still content-addressed with atomic writes (safe across processes).
- Near-miss zopfli pool capped at ~4 threads (was 8) so package workers do not multiply into dozens of concurrent zopflis.

```bash
python src/pack_images.py --img-bin <vanilla> --out cache/new_img.bin
python src/pack_images.py --pkg-workers 1          # sequential packages (debug)
python tools/rebuild_bake_img.py --rom game.cia --pkg-workers 4
```

**C. Closed-stream zopfli pad (2026-09-15)** (`src/exact_zlib.py`)

When zopfli comes in *short* of the slot, pad the finished stream at EOB with empty deflate blocks instead of burning CPU on 256 near-miss trials (the old 56-byte-undershoot stall). Still only then binary-search salt / bounded near-miss.

Warm `cache/img_pack/` still turns re-packs into minutes. Cold time depends on how many ARCs miss the zlib fast path (tight ETC1A4 softkeys still often need zopfli).

**Live elapsed timer:** `pack_images`, `rebuild_bake_img`, and `patch_cia` print ``[timer]`` lines — start wall-clock, stage marks, a heartbeat every 60s while still running, and ``[timer] total …`` at finish. Watch those for actual runtime (do not rely on a fixed hour estimate). Gold rebuild also writes the wall-clock total to `[rebuild] OK` and `out/logs/rebuild_*.txt`.

**Ballpark (cold, no bake cache) — engineering estimate only:**

| Machine | Cold full gold rebuild (`rebuild_bake_img.py`) |
|---------|--------------------------------------------------|
| High-thread desktop (e.g. 32-thread / `--pkg-workers` default) | Measured **~27 min** end-to-end (2026-09-18) |
| Typical modern multi-core desktop (e.g. 8-core / `--pkg-workers` default) | Often **under an hour** if many ARCs hit the zlib fast path |
| Low-core / `--pkg-workers 1` | Longer — can still approach historical ~16h if every tight ARC hits zopfli |
| Warm `cache/img_pack/` + bake present | **Minutes** (Drop CIA reuses bake) |

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

### 12.7 Boot CESA warning (pkg 90 TEX — 2026-09-13)

Not Zhoumaru UI pack, not `IMAGE_MAP`, not BCLIM, not TRB. The boot anti-piracy slide is a **TEX** in img.bin package **90** (`CESA_240X400.texi`): 256×512 Morton BGR8, **240×400** visible, black padding. Vanilla compressed slot is **13667 bytes**. `pack_images` still **skips** CESA unless `--only cesa` (white-boot history); gold path is `tools/deploy_cesa_en.py` at the tail of `rebuild_bake_img.py`.

The **blank screen beside CESA** is `logo_white.texi` (verified Azahar A/B, 2026-09-15): same 240-wide **portrait** column as CESA, **240×320** visible / 256×512 canvas.

**Constructor IDs are 1-based TEXI indices** (`FUN_00598ff4`: `(id & 0xffff) - 1`). Do not treat `0x5A0000` as TEXI 0.

| TEXI (0-based) | Filename | Constructor ID |
|----------------|----------|----------------|
| 0 | `Bottom_Thank.texi` | `0x5A0001` |
| 1 | `CESA_240X400.texi` | `0x5A0002` |
| 2 | `CESA_400X240.texi` | `0x5A0003` |
| 7 | `logo_white.texi` | `0x5A0008` |
| 8 | `ProductionLogo_240X320.texi` | `0x5A0009` |
| 9 | `ProductionLogo_320X240.texi` | `0x5A000A` |
| 10 | `Upper_ThankYou_00.texi` | `0x5A000B` |

CesaLogo (`FUN_0016f338`): `+0x60 = 0x5A0002` (`CESA_240X400`) and `+0x64 = 0x5A0008` (`logo_white`) in orientation 0/2. State 2 (`FUN_0016ec1c`) binds both via `FUN_005af3ac`. Vanilla then forces a **400×400** quad on `0x5A0008` (`s19` at `0x0016ed84`) so the 16×16 white stub fills the pane. A real TEX at that size stretches and clips. `patch_cesa_logo_white_native_size` (`src/patch_code.py`) turns the `bne` at `0x0016ED80` into an always-`b` so bind keeps `FUN_005aeef4`'s TEXI size (**240×320**). Ships in `deploy_name_input_en.py` → `release/name_input_code.bin`. `NintendoLogo` also binds `0x5A0008` (white flash).

**Wrong slots (right pane stayed white):** `Bottom_Thank` (`0x5A0001`), `CESA_400X240` (`0x5A0003`), `ProductionLogo_320X240` (`0x5A000A`). Patching CesaLogo IDs to those slots duplicated CESA / Love Plus Production eyecatches — do not remap `+0x60`/`+0x64`. Landscape **320×240** art on `logo_white` sat on its side next to portrait CESA.

Vanilla `logo_white` is a **16×16 stub**. Cannot grow the 15-byte stub zlib in place. Deploy **rebuilds** the PACK inside the original **29232-byte** img.bin package from **vanilla** pkg 90: zopfli the three real TEXs (CESA / Konami / ProductionLogo), give `logo_white` its own 256×512 / **240×320** TEX, leave the other stubs, pad the file back to 29232. Pair by **filename**. Do not shrink img.bin package length. Rebuilding from an already-patched bake leaves leftover TEXI dims and can hide the blurb or smash boot.

**Idx table (hardware crash 2026-09-14):** growing the inner PACK header `dec_len` 1182976 → 1576192 is not enough. img.bin's index table (`0x800 + 90*0x14`, `=4s4x2I2xBB`) still stored **1182976**. The game mallocs **that** arena, then writes the companion TEX at `dec_off=1182976` (one byte past the end) → heap smash → ARM11 data abort in malloc `FUN_0000de04` @ runtime `0x0010DE4C` (FAR=3, `ldr r2,[r0,#4]` with `r0=0xFFFFFFFF`). `patch_img_bin_with_companion` now writes the matching idx `dec_len`. Do not grow PACK `dec_len` without the idx field.

Vanilla JP (decode with `src/patch_cesa.py --decode`): white field, `#FF0000` gothic title with ruby, **two** title lines each with a 2px red underline, black body, one red legal line, black closing. Ink occupies roughly **y=73–322**.

#### English master (how it is drawn)

`tools/render_cesa_en.py` → `assets/images/cesa/CESA_240X400.png`. Fonts are the NLPPPATCH Graphics & Text Reference (2025) already at `assets/fonts/reference/nlppatch-2025/` ([LovePlusProject/NLPPCTR](https://github.com/LovePlusProject/NLPPCTR) zip). **Not** MPLUS1p and **not** Geomanist — those miss the JP gothic.

| Role | File | TTC face |
|------|------|----------|
| Title (heavy) | `df-heiseigothic-w9.ttc` | index **1** `DFPHSGothic-W9` (proportional Latin; index 0 is fullwidth) |
| Body / emphasis | `df-heiseigothic-w5.ttc` | index **1** `DFPHSGothic-W5` |

Layout copies vanilla: two red title lines with **per-line** underlines, five black body lines, red `strictly prohibited by law.`, two-line thanks. No English ruby; title starts ~y=82 to keep the JP title band.

**2× coverage masks (the AA / “drop-shadow” fix):**

1. Draw red glyphs + underlines onto an **L** mask and black glyphs onto a **second** L mask, both at **480×800**.

2. LANCZOS-downscale each mask to 240×400.

3. Composite onto white: black coverage darkens RGB; red coverage then lerps toward `(255,0,0)`. Where red coverage > 0, **zero the black coverage** so red AA is only red↔white (pink), never red mixed with black.

4. Quantize each coverage to **12 ramp steps** (`RAMP_STEPS`). That keeps visible AA but few unique colors.

`deploy_cesa_en.py` re-runs both renders, then `rebuild_pkg90_with_companion` (zopfli, same 29232-byte PACK) into live bake (and Azahar when present), and **syncs img.bin idx-table `dec_len`** to the new PACK header. The 400×400 skip lives in `name_input_code.bin` (bake rebuild / Drop CIA). Rollback: `bake_img.bin.bak_pre_cesa`. Tests: `tests/test_render_cesa_en.py`, `tests/test_patch_cesa_idx.py`, `tests/test_patch_cesa_logo_scale.py`. A/B: `.\make.ps1 cesa-ab` then `launch-a` (thank-you) / `launch-b` (CESA EN, white stub).

#### Companion blurb (`logo_white` — 2026-09-15)

`tools/render_cesa_en.py` `render_cesa_companion_en()` → `assets/images/cesa/logo_white.png` (**240×320** portrait, same 240-wide column as CESA; spliced into `logo_white.texi`). Same Heisei W9/W5 index 1, **no red**: two-line title + highlights in dark teal `(16,96,112)` (`free`, `never be sold`, `scammed`, `official release`). 2× masks like CESA, but **3 ramp steps** (`COMPANION_RAMP_STEPS`) so zopfli stays under the PACK budget. White TEX padding (not black) so Morton tiles at the 240×320 crop stay poster-white.

Budget after lossless zopfli of Konami (~2875) + ProductionLogo (~8021) + CESA EN (~10934) + 16×16 stub: ~4.8k left in the 29232 PACK. 8-step companion was ~7.2k (overflow). Fill `logo_white` **by filename**. Always extract pkg 90 from vanilla before the PACK rebuild.

#### Compression (why not “just keep full AA”)

| Approach | ~zlib lvl9 of the TEX | On-screen |
|----------|----------------------|-----------|
| Vanilla JP | **13667** on the nose (lvl6) | Smooth gothic, pink/gray AA |
| Early EngPatcher MPLUS1p EN | ~3k | Thin, not gothic |
| Full AA Heisei on one RGB canvas | ~17–19k | Smooth, but **over** the slot |
| Hard 3-color snap (white / `#FF0000` / black) | ~5k | Fits, but **grainy**; dark red AA → black fringe that reads as a **drop-shadow** |
| 2× masks + 12-step ramps (CESA warning) | ~12k (zopfli ~10934; no longer padded to 13667 once the PACK is rebuilt) | Smooth gothic, no red shadow |
| 2× masks + 3-step ramps (logo_white blurb) | zopfli ~4k | Teal highlights; extra TEX fits the PACK |

`compress_zlib_exact` can **pad a short** stream (SYNC_FLUSH empty stored blocks, `unused_data == 0`). It **cannot** shrink a stream that already exceeds 13667. Zopfli of a too-fat TEX is still over; do not NUL-pad or shrink `cmp_len` (CESA white boot — same class as §12.5).

#### Do not

- Snap to 3 colors to “make zlib fit.”

- Draw red and black with `ImageDraw` on the **same** RGB image (PIL AA blends red into neighboring black).

- Use Geomanist / MPLUS1p for this slide.

- Auto-pack CESA through `pack_images` (opt-in `--only cesa` only).

- `pe` grow / trailing NUL zlib / bak→MOD wipe.

- Fill `Bottom_Thank` / `CESA_400X240` / `ProductionLogo_320X240` for the dual-screen (wrong constructor IDs).

- Remap CesaLogo `+0x60`/`+0x64` (duplicates CESA / Production eyecatches).

- Landscape **320×240** `logo_white` next to portrait CESA.

- Leave the vanilla 400×400 `logo_white` stub quad (`bne` @ `0x0016ED80`).

---

## 13. EngPatcher scripts and Cursor rules

### 13.1 Scripts

| Script | Purpose |
|--------|---------|
| `src/pack_images.py` | PNG → BCLIM → DARC same-size → img splice; `--pkg-workers` ProcessPool |
| `src/bclimutil.py` | BCLIM parse/encode helpers |
| `src/darcutil.py` | DARC extract / same-size replace |
| `src/image_map.py` | Folder key → package index |
| `src/patch_textresource.py` | TRB dump / translate / rebuild / inplace |
| `src/patch_cesa.py` | Boot CESA TEX encode/decode + pkg **90** PACK rebuild (`logo_white` 240×320 companion) |
| `src/patch_code.py` | code.bin patches (incl. CesaLogo skip 400×400 stub quad @ `0x0016ED80`) |
| `src/patch_message_speed.py` | Options 18/12/6/0 → **14/8/2/0**, TalkWindow 40/70/90/110/220 → **10/18/22/28/55**, tick `min` vs table @ `0x0013B718` |
| `src/patch_drawtext_titles.py` | DrawTextToPane remap (help/other titles; **not** Options/clock chrome) |
| `src/patch_ui_titles.py` | Older FUN_0024842c-only remapper (superseded) |
| `src/patch_clock_text.py` | **Abandoned** global MakeStr experiment |
| `tools/render_cesa_en.py` | EN CESA 240×400 + companion 240×320 PNG: NLPPPATCH Heisei Gothic (**§12.7**) |
| `tools/deploy_msel_options_en.py` | Options + clock-title A8 → exact zlib pkg **5245** (splice into **live** MOD) |
| `tools/deploy_optionpassword_en.py` | Password window `パスワード` → `Password` ETC1A4 `Pass_Win01` @ **5251** |
| `tools/deploy_msel_menus_en.py` | Gallery/Comm/Data A8 → pkgs **5244/5241/5242** (+ Business Card **5240**) |
| `tools/deploy_msel_opt_plates_en.py` | Soft re-render Options plates on live **5245** (best-effort; uses shared `exact_zlib`) |
| `tools/deploy_confirm_btn_en.py` | Confirm `決定` → `OK` ETC1A4 @ **5238** (lean trials + shared exact zlib) |
| `tools/deploy_softkey_quit_en.py` | Quit `やめる` → `Quit` ETC1A4 `Com_btn_y01_b{,ON}` @ **5238** (after Back/Next) |
| `tools/deploy_softkey_defaults_en.py` | Restore Default `初期設定` ETC1A4 `Com_btn_sy01_{a,b}` @ **5238** (last-writer after Quit) |
| `tools/deploy_title_main_menu_en.py` | **Main-menu hub rows** `Title_btn02_t01..t06` RGBA4444 @ **5261** (labels only; custom BCLIM/BCLYT black-screened — do not re-add yet) |
| `tools/deploy_cesa_en.py` | Re-render CESA + companion then splice rebuilt pkg **90** |
| `tools/ab_cesa_bake.py` | Gold-bake A/B: A = CESA + `logo_white` + native-size skip; B = CESA EN only |
| `tools/rebuild_bake_img.py` | Gold bake: PNG pack → TRB → ordered deploys → SMS → `release/bake_img.bin` + `name_input_code.bin` |
| `tools/fetch_release_bake.py` | Optional: download `bake_img.bin` + `romfs_overlay.zip` from nlpp-gold GitHub Release tag `gold` (`--best-effort` for Drop CIA fallback) |
| `src/patch_cia.py` | Decrypted CIA/3DS in → inject scripts + gold bake + TRB overlay + name patches → CIA out (`out/2_[Or this]/`) + LayeredFS (`out/1_[Either use this-LayerFS]/luma/`) |
| `src/extract_vanilla_from_rom.py` | Decrypt/extract vanilla `img.bin` + TRBs from dropped `.cia`/`.3ds` → `cache/vanilla_from_rom/` |
| `src/exact_zlib.py` | Exact-length zlib: **empty-block first**, then zopfli / gap-tune / near-miss |
| `src/run_timer.py` | Live ``[timer]`` elapsed / 60s heartbeat for pack, gold rebuild, CIA patcher |
| `tools/deploy_display_settings_en.py` | Display + Sound panel labels @ **5247** |
| `tools/deploy_sound_settings_en.py` | Sound-only subset of **5247** (HelpBtn note: not Defaults) |
| `tools/deploy_myroom_main_en.py` | Myroom buttons + Back @ **5380** |
| `tools/deploy_mydata_en.py` | My Data header **5575** + To-Do/Status **5380** (zero-gaps → empty-block) |
| `tools/deploy_schedule_header_en.py` | Schedule header @ **5575** (rebuild shared toptex set) |
| `tools/deploy_profile_en.py` | Profile Heisei header **5246** (§12.4.2) + Call/atlas chroma AA **5252** (§12.4.4) + hometown chips (§12.4.3) |
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
| `src/patch_names.py` | Heroine names in `.dbin2`, resident TRB, `img.bin` table (NLPTextTool XOR reimplemented) |
| `src/script_inject.py` | Layered `.dbin2` inject used by `patch_cia` (`rebuild_dbin2` → optional NLPPATCH → ROM) |
| `src/deploy_nlppatch_scripts.py` | Optional deploy of community (ex-NLPPATCH) `.dbin2` from rebuild_dbin2 / assets/nlppatch |
| `tools/deploy_ui_buttons_en.py` | UI Buttons bundle: keyboard **5190**, SysPopup **5259**, scoped Back **5380**, Album delete **4149** |
| `tools/import_ui_buttons_bundle.py` | One-time import from `NLPP_English_UI_Buttons_only.zip` → `assets/images/*.check/timg/` |
| `tools/import_nlppctr_textures.py` | Optional dev: import [LovePlusProject/NLPPCTR](https://github.com/LovePlusProject/NLPPCTR) Citra textures for A/B compare (`ab_test/`) |
| `tools/export_progress_metrics.py` | Fansite metrics → `out/progress_metrics.json` |

**Dialog scripts at patch time:** `rebuild_dbin2/*.dbin2` (pre-built from `assets/scripts/*.xml`). XML uses the [NLPTextTool](https://github.com/LovePlusProject/NLPTextTool) DBIN2 schema; rebuild offline with a local NLPTextTool clone if you edit scripts — the CIA pipeline does not invoke NLPTextTool.

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
| `zhoumaru-ui-pack.mdc` | §12.7 | Zhoumaru `.check` PNGs; **CESA is not in that pack** |
| `from-scratch-bake.mdc` | §15.5 | Drop CIA / gold bake; name-input caves in `.text` |
| `azahar-test-workflow.mdc` | §10, §18 | a/b instances; **OpenLinkFile** Communications hang + Game Start parent-archive hang |

When RE discovers something durable, update **both** this file and the relevant rule so agents don’t diverge.

### 13.3 Third-party stack (what EngPatcher actually invokes)

Full fan-facing credits: root [`README.md` Credits](README.md#credits). Summary for RE / tooling:

| Tier | Components |
|------|------------|
| **Vendored + invoked** | kiwiz **nlpp-tools** (`ie`, `pe`, `png2bclim`, `img`); deaknaew **Trb2xlsx** → `lookup.txt` only; optional **NLPPATCH** snapshot; EngPatcher **darcutil** / **bclimutil** |
| **Auto-fetched CIA** | 3dstool, ctrtool, makerom, seeddb.bin |
| **Format / lineage only** | gdkchan / LovePlusProject **NLPTextTool** (DBIN2 XML + XOR); **NLPUnpacker** superseded by `ie`/`pe` |
| **Bundled, unused on gold path** | yellows8 **darctool** ELF, deaknaew **png2texi** exe (inside nlpp-tools tree) |
| **Optional dev** | LovePlusProject **NLPPCTR** import (`import_nlppctr_textures.py`) |
| **Not dependencies** | kiwiz **nlpp-fmt**, **NLPLineWrapper**, **Kuriimu**; **Makein/NLPPGit** is a sister asset repo (no code copied) |

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
| Omitted `PyYAML` from `requirements.txt` | `ModuleNotFoundError: yaml` in `ie` / `img/__init__.py` at gold unpack | Vendored nlpp-tools imports `yaml`; drop-bat only pip’d Pillow/numpy/zopfli/etcpak |
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
| Packed Zhoumaru `Title_menu_word.png` + rebuilt Title.arc from `bak_pre_title_engpatch` | First hub show: **colorful tiled noise** where “Main Menu” should be; `Title_btn02_t*` rows + Eng Patch still EN | GPU dump: alpha = glyphs, RGB = swizzle garbage. Offline alpha-composite looks fine. Vanilla BCLIM is already EN gray. `bak_pre_*` was packed MOD, not vanilla — **§15.1.1** |

**Eng Patch badge (verified standalone — do not merge into `Copyright.bclim`):**

| Piece | Role |
|-------|------|
| `timg/Eng_Patch.bclim` | Separate ETC1A4 strip (`Eng Patch v1.0.0-rc3` + newloveplus.loc.moe); **white glyphs + thick black outline** (readable on Main Menu white column) |
| `timg/Copyright.bclim` | **Vanilla Konami only** — never overwrite with Eng text |
| `blyt/Pts_Copyright.bclyt` | `Pic_EngPatch` under `Nul_Copyright` (`ENG_PANE_TY=20`, `NUL_H=56`); DMST path, not `Lyt_Copyright` pics |
| Deploy | `tools/deploy_title_engpatch_en.py` (hub labels + Eng insert); bake list last-writer for **5261** |

Working recipe: Pts wire + standalone BCLIM (Aug 2026 confirm). Soft white-only fringe **vanishes** on Main Menu even when bake/CIA contain the strip — outline strength is the visibility fix, not “merge into Copyright.”

**Title loop NX abort** when rebinding this Parts tree: **§15.7** (do not treat as a CESA / extra-data / `.rodata` cave crash).

**Bake vs CIA mismatch (2026-09-05):** `release/bake_img.bin` pkg **5261** can contain `Eng_Patch` while a Drop’d CIA does not. Desktop `NewLovePlusPlus-EN.cia` (6:31pm) had **vanilla** Title (`sha=37dad8c6aca1`, hub labels JP, no Eng) while bake had EN+Eng (`8b9916be34b2`). Name-input still worked (`--inject-code`). Root causes: (1) shipping **stale luma/Azahar** imgs without the badge; (2) **`patch_cia` swallowed `PatchError` from the Eng-Patch guard and continued scripts-only** — vanilla `img.bin` + EN `code.bin` = JP menus, no badge, name input OK. Fixes: refuse any inject without `Eng_Patch`; **hard-fail** image errors (no scripts-only fallback); `rebuild_test_cia` prefers bake. Tests: `tests/test_patch_cia_gold_bake.py`, `tests/test_rebuild_test_cia_img.py`.

**Wrong Title asset wording (fixed in deploy):** old `assets/images/Title/Title_btn02_t04..t06` said “Save Data / Connection / Dating App”. Vanilla mapping is:

| BCLIM | JP | EN (deploy) |
|-------|----|-------------|
| `t01` | オプション | Options |
| `t02` | ゲームスタート | Game Start |
| `t03` | ギャラリー | Gallery |
| `t04` | データ管理 | Data Management |
| `t05` | コミュニケーション | Communication |
| `t06` | どこでもデート | Anywhere Date |

(`Title_btn02_01..06` are **32×32 icons**, not labels. Header “Main Menu” is BCLIM `Title_menu_word` — **§15.1.1**, not TRB.)

#### 15.1.1 Hub header garbled on first boot (`Title_menu_word` RGB dump — 2026-09-18)

**Symptom:** After CESA / title logo, the Main Menu hub shows a small **colorful tiled noise** strip at the top (above Game Start). Hub rows stay EN (`GAME START` / `OPTIONS` / …) and the Eng Patch badge is readable. Looks like a format/swizzle smash, not Japanese leftover.

**What it is:** RGBA4444 BCLIM `timg/Title_menu_word.bclim` (100×20) in Title.arc pkg **5261**, bound by `Pts_Title_menu` onto `Lyt_Tit02` `Pos_Tit02_menu` / `Vis_Tit02_menu`. Not TRB, not DrawText, not `Title_btn02_t01..t06`.

**Vanilla is already English.** Opaque pixels are gray `(51,51,51)` “Main Menu”. No localization splice was required.

**Zhoumaru `Title.check/timg/Title_menu_word.png` is a bad GPU dump:**

| Channel | Dump | In-game |
|---------|------|---------|
| Alpha | Clean “Main Menu” glyphs | Mask only |
| RGB | Swizzled black/white noise (often just `(0,0,0)` and `(255,255,255)`) | **This is what the pic pane shows** |

`decode_bclim_to_image` + alpha-composite on gray looks like a clean label (alpha hides the RGB trash). Do not trust that preview for GPU dumps. Split RGB vs alpha; if opaque chroma is high while alpha looks like text, **do not pack**.

**How it landed in gold bake:** `pack_images` prefers `.check` and replaced the vanilla BCLIM. `deploy_title_engpatch_en.py` is last-writer for **5261**, but it used `img.bin.bak_pre_title_engpatch` as the Title ARC source. That bak is created from **packed** MOD (`bak.write_bytes(MOD_IMG.read_bytes())`), so the dump survived. Deploy only rewrote hub labels + `Eng_Patch`.

**Fix:** Rebuild Title.arc from **vanilla** (`src_for_pkg = VANILLA`). Keep vanilla `Title_menu_word` (and vanilla `Title_Logo*` — Zhoumaru logos are still JP). Restore `assets/images/Title.check/timg/Title_menu_word.png` from the vanilla decode (gray RGB). Tests: `tests/test_title_engpatch_badge.py` (`test_title_engpatch_rebuilds_title_arc_from_vanilla`, `test_title_menu_word_png_rgb_matches_glyphs`).

**Do not:** treat this as a CESA / extra-data / §15.7 null-pane leftover; those crash or skip panes, they do not paint swizzled RGB into `Pts_Title_menu`.

### 15.2 What we got right

| Practice | Why it worked |
|----------|----------------|
| `release/bake_img.bin` as gold; `cache/` scratch | Drop-bat reuses bake in minutes; rebuild is the long path |
| `tools/rebuild_bake_img.py --rom <cia\|3ds>` + `extract_vanilla_from_rom.py` | Clone can seed vanilla from the dropped ROM → `cache/vanilla_from_rom/` |
| `--skip-pack` after PNG pack finished | Resume deploys/TRB/SMS without another long pack |
| Shared `src/exact_zlib.py` for deploys | Gap-tune, empty-block, near-miss; **zlib/empty-block before zopfli** (§12.5.3) |
| Soft-then-hard glyph trials | Soft AA prettier; hard 1-bit often the only fit under slot |
| Zero DARC inter-file gaps before measuring zopfli | Prior urandom salt inflates zlib on shared ARCs |
| Package ProcessPool (`--pkg-workers`) | Parallel exact-zlib across packages; main thread splices (§12.5.3) |
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

1. Python 3.10+ + `pip install -r requirements.txt` (**must** include Pillow, numpy, zopfli, **etcpak**, PyYAML).
2. Drop known-dump `.cia` / `.3ds` / `.cci` on **`Drop CIA or 3DS Here to Patch.bat`** (or run `patch_cia.py` / `rebuild_bake_img.py --rom …` manually).
3. **If `release/bake_img.bin` is missing or `release/bake_stamp.txt` does not match this RC**, Drop rebuilds from this tree **from scratch** (no `cache/img_pack`, leftover bake overwritten). Same-RC stamped bake is reused. CI gold fetch only if `NLPP_REUSE_BAKE=1`. See **§15.5**.
4. First **local** gold rebuild: PNG pack is the long step (historically ~16h when every ARC ran zopfli sequentially). Empty-block-first + `--pkg-workers` + zopfli undershoot pad → typically **under an hour** on a multi-core desktop (measured **~27 min** on a high-thread machine, 2026-09-18; §12.5.3); leave the window open and watch `[timer]` / `[exact-zlib]` / `[pack]` progress.
   Subsequent full packs with unchanged assets reuse ``cache/img_pack/`` (BCLIM + exact-zlib) and are typically minutes (`--no-cache` to force).
5. After bake exists: drop again → **minutes** (reuse bake; no rebuild).
6. Resume mid-deploy only: `python tools/rebuild_bake_img.py --skip-pack` from **repo root**.
7. Testing in Azahar: fully quit the emulator; confirm LayeredFS `img.bin` was spliced (or re-drop CIA). Don’t assume bake alone updated mods.

8. CESA: `tools/render_cesa_en.py` then `deploy_cesa_en.py` / rebuild tail — not ad-hoc `pe` repack. Rollback: `bake_img.bin.bak_pre_cesa`. **§12.7**.

9. Dev sanity: `pip install -r requirements-dev.txt && python -m pytest tests/ -v` (§15.6).

### 15.4 Package quick map (hub vs submenu)

| UI | Package | Deploy / note |
|----|---------|----------------|
| Boot CESA warning | **90** | `render_cesa_en.py` → `deploy_cesa_en.py` (CESA + `logo_white` 240×320; PACK rebuild) + `patch_cesa_logo_white_native_size` in `name_input_code.bin`. **§12.7** |
| Main Menu **rows** + Eng Patch badge | **5261** Title.arc | `deploy_title_engpatch_en.py` (hub labels + `Eng_Patch.bclim`; replaces labels-only `deploy_title_main_menu_en.py` in bake) |
| Gallery / Comm / Data **homes** | **5244 / 5241 / 5242** | `deploy_msel_menus_en.py` |
| Gallery girl-select | **5153** | `deploy_gallery_common_en.py` |
| MultiWin headers (+ Delete Save Data) | **5237** | `deploy_datadelete_en.py` then `deploy_multiwin_headers_en.py --full` (gold Gallery/Comm home). Bake then runs the same script with no flag (Girlfriend Communication extras; zopfli empty-block pad, not gap-salt). |
| Softkeys Back / Next / Confirm / Quit / Restore Default | **5238** | `deploy_confirm_btn_en.py` then `deploy_softkey_back_next_en.py` then `deploy_softkey_quit_en.py` then `deploy_softkey_defaults_en.py` |
| Options chrome | **5245** | `deploy_msel_options_en.py` (+ optional opt_plates) |
| Password entry window | **5251** | `deploy_optionpassword_en.py` (`Pass_Win01`) |
| Keyboard mode tabs / popup buttons | **5190** / **5259** / … | `deploy_ui_buttons_en.py` then `deploy_input_keyboard_en.py` |
| Profile name-input (romaji) | ExeFS `code.bin` | `deploy_name_input_en.py` → `release/name_input_code.bin` (not in `img.bin`; also applies Message Speed Options −4 frames + TalkWindow ÷4 + voice cap, §21) |
| “Main Menu” title string | **5261** `Title_menu_word` (`Pts_Title_menu`) | Vanilla already EN — keep vanilla BCLIM; Zhoumaru dump RGB was swizzled |

### 15.5 Gold bake acquisition workflow (Drop CIA — 2026-09-01)

Design goal: **self-contained clone** — everything needed to *build* the bake is in git; the bake binary itself is not. Optional **nlpp-gold** CI can publish a pre-built bake to skip the first local pack (typically under an hour; historically ~16h sequential zopfli) when that infra exists.

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
             (long first time; vanilla from cache/vanilla_from_rom/;
              §12.5.3 empty-block-first + pkg ProcessPool)
        3. if still no bake:
             HARD STOP — do not patch (prevents half-EN CIA)
  → patch_cia.py:
        inject rebuild_dbin2 + gold bake img.bin + romfs_overlay
        + apply_name_patches + optional --inject-code name_input_code.bin
  → out/1_[Either use this-LayerFS]/luma/ + out/2_[Or this]/NewLovePlusPlus-EN.cia + out/3_but not both
```

Each successful patch writes the **PATCH SUMMARY** (the `[OK]` / `[SKIPPED]` / `[WARN]` box) to **`out/logs/`**: a timestamped `patch_YYYYMMDD_HHMMSS.txt` plus `latest.txt`. That folder survives `out/` cleanup. `--log PATH` chooses a file (or a directory to write into). `--no-log` or `NLPP_NO_LOG=1` skips it. Full `[images]` / `[inject]` console lines are still console-only — redirect stdout if you need those for diagnosis.

Scratch cleanup is incremental (not only at the end): PNG pack drops each package’s ie/pe unpack after `new_XXXX` is written; gold rebuild deletes `out/rebuild_bake_img_work`, the duplicate `cache/new_img.bin`, deploy `out/*` dirs, and the vanilla bake bak after they are consumed; CIA rebuild deletes extracted CXI, `romfs.bin`, the injected RomFS tree, `romfs_patched.bin`, and `patched.cxi` as soon as the next container exists. `--keep-work` keeps all of that. Durable artifacts stay: `release/bake_img.bin`, `cache/vanilla_from_rom/`, `out/1_[Either use this-LayerFS]/`, `out/2_[Or this]/`, `out/3_but not both`, `out/logs/`.

#### Environment overrides

| Variable | Effect |
|----------|--------|
| `NLPP_SKIP_GOLD_FETCH=1` | Skip GitHub Release poll; go straight to local rebuild (offline) |
| `NLPP_GITHUB_REPO` / `NLPP_GOLD_REPO` | Override nlpp-gold repo (`OWNER/nlpp-gold`) |
| `NLPP_GOLD_TAG` | Release tag (default `gold`) |
| `NLPP_WITH_IMAGES=0` | Scripts-only CIA — **no** menu chrome (explicit opt-out) |
| `NLPP_REPACK_IMAGES=1` | Dev: rebuild `cache/new_img.bin` PNG scratch only — **incomplete vs gold** |
| `NLPP_VANILLA_IMG` | Point rebuild at a vanilla `img.bin` if ROM extract fails |
| `NLPP_NO_LOG=1` | Skip writing `out/logs/` PATCH SUMMARY files |

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
| `test_patch_summary.py` | PATCH SUMMARY rows + `out/logs/` write / `--no-log` / cleanup keeps `logs/` |
| `test_fetch_release_bake.py` | `try_fetch_gold()`, `--best-effort` exit codes, 404 → fallback |
| `test_patch_cia_gold_bake.py` | Gold bake preferred over PNG cache in inject path |
| `test_rebuild_bake_img.py` | `DEPLOY_SCRIPTS` includes menu chrome + ordering |
| `test_scratch_cleanup.py` | Incremental scratch delete (pack/extract/CIA intermediates) |
| Others | `patch_names`, `exact_zlib`, `nlpp_paths`, `image_map`, `img_pack_cache`, … |

GitHub Actions: `.github/workflows/test.yml` on push/PR to `main` / `Bleeding-Edge`.

**Out of scope for unit tests** (integration / manual): full PNG pack, CIA rebuild via makerom, per-screen Azahar verify, individual `deploy_*` texture splices.

### 15.7 Title hub loop — prefetch abort PC 0 (2026-09-18)

NX-accurate Azahar (and a real 3DS) abort when the title hub **loops back to itself** (Main Menu rebuild / copyright Parts rebind). Older Azahar executed the bytes at address 0 anyway (`ExceptionRaised(NoExecuteFault)` text: “Azahar used to run the bytes anyway”).

| Dump field | Value | Meaning |
|------------|-------|---------|
| Process | `nlpp` `00040000000F4E00` | Guest, not host Qt |
| Exception | prefetch abort, **Permission - Page**, `NoExecuteFault` | Instruction fetch from NX / page 0 |
| PC | `0x00000000` | `BLX` to a null fn pointer |
| LR | `0x00645A2C` | Next insn after `BLX r3` (VA = file + `0x100000`) |
| r3 | `0` | Vtable slot `+0x2C` was 0 |
| r4 | `4` | Intrusive list node for a **null pane** (`object+4`) |
| r12 | `0x5F736F50` (`Pos_`) | Search name was `Pos_Copyright_*` / `Pos_Tit02_*` |

**Call site (file / Ghidra base 0):** `Pane_FindPaneByName` loop @ `0x005459D8` … `0x00545A48`.

```
LDR r1, [r4, #-4]     ; vtable
LDR r3, [r1, #0x2C]   ; virtual Find/Compare
MOV r1, r7            ; name (Pos_…)
BLX r3                ; @ 0x00545A28  → PC=0 when r3=0
```

**How `r4` becomes 4:** `Pane_AttachToParent` @ `0x00545550` takes parent in `r0`, child in `r1`. `IntrusiveDList_InsertFront` uses node `child+4`. A **null child** inserts node address `4` into the parent’s child list. The next recursive `FindPaneByName` (`r2=1`) walks that poison and `BLX`s through page 0.

Likely constructor failure: extra `pic1` **`Pic_EngPatch`** in `Pts_Copyright` (pkg **5261**, `deploy_title_engpatch_en.py`) — new material/tex index 1 on a Parts instance under `Pos_Copyright_*`. Vanilla Pts has only `Pic_Copyright`. First hub show can work; **rebind on loop-back** hits the poison. This is **not** the old `.rodata` name-input pad (that dump was PC `0x007E6A78`).

**Fix (code.bin, last `.text` RX page — ships in `release/name_input_code.bin`):** `src/patch_lyt_null_pane.py`, applied from `tools/deploy_name_input_en.py` (stack step **1b**). Does **not** replace the name-input call-site parent guard @ `0x001FA790`.

| Cave | File | Role |
|------|------|------|
| Shared pad `+0x28` (`0x0068F828`, 0x18) | Hook `0x00545550` | Skip attach if child (`r1`) or parent (`r0`) is 0 — stops writing node `4` |
| Shared pad `+0xA0` (`0x0068F8A0`, 0x20) | Hook `0x00545A28` (`BLX r3`) | If node is 0/4 → not-found; if vtable slot is 0 → next sibling; else `BLX r3` |

`+0xA0` was reserved for banned `candmode_reset` — **this** is the shipped occupant now. Tests: `tests/test_name_input_caves.py` (`test_lyt_null_pane_caves_assemble_and_hook_vanilla`). Rebuild from vanilla `code.bin.bak` after moving caves, then Drop CIA / LayeredFS `exefs/code.bin`.

**Verified 2026-09-18:** instance A title → menu → title loop **no longer prefetch-aborts** with this `name_input_code.bin`. Guard skips a failed Eng pic attach; it does not by itself prove `Pic_EngPatch` always constructs (badge visibility is still the Pts/BCLIM path in §15.1).

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
| 1b | Attach/FindPane null child | `src/patch_lyt_null_pane.py` | Title hub loop NX abort — skip attach if child/parent is 0; skip `FindPaneByName` `BLX r3` if node/`+0x2C` is 0 (**§15.7**) |
| 2 | SetDisplayMode +0x10 guard | `src/patch_input_candidate_nullguard.py` | Guard `0x1fbc08` / `0x1fbd24` |
| 3 | Fill-flag + mode clamp | `src/patch_input_candmode_fillflag_reset.py` | `+0x44=0`, clamp `+0x30` @ `0x1fa828` |
| 4 | Romaji DrawCell | `src/patch_input_romaji.py` | Hepburn labels **and** insert buffer; ABC fullwidth→ASCII (**§17.7**); cave `@0x0068F900` |
| 5 | Skip kanji list | `src/patch_input_kana_direct_insert.py` | NOP `@0x1fb070` — gojūon uses ABC insert path |
| 6 | Skip ASCII dakuten | `src/patch_input_skip_ascii_dakuten.py` | Hepburn taps skip ゛/っ combine |
| 7 | Raw strcat join | `src/patch_input_strcat_raw.py` | byte strcat; collapse KKE; 8-glyph cap |
| 8 | Message Speed delays | `src/patch_message_speed.py` | Options 14/8/2/0 + TalkWindow ÷4 + voice/script cap (bake sidecar) |
| 9 | CesaLogo native size | `patch_cesa_logo_white_native_size` | skip 400×400 stub quad on `logo_white` |

Umbrella rollback: `exefs/code.bin.bak_pre_name_input_en`. Optional mode-tab BCLIM: `tools/deploy_input_keyboard_en.py` (pkg **5190**).

**Live checklist:** **Hiragana/Kata** show Hepburn romaji on the gojūon grid (not an empty checkerboard); tap → romaji in name field; **Kanji** tab has no candidate list (empty candidate chrome is OK — the gojūon keyboard itself must still show keys); ABC/Lower insert **ASCII** (not fullwidth `Ａ`); name length still ≤8 chars.

### 17.2 Hard ban: `candmode_reset` (`+0x24 = 0`)

`src/patch_input_candmode_reset.py` **must not be deployed.** Bisect (vanilla → add one patch at a time):

- pane nullguard → taps OK  
- \+ candidate nullguard → taps OK  
- \+ **candmode_reset** → **taps dead**  
- fillflag_reset **without** candmode_reset → taps OK  

`nameInputObj+0x24` selects keyboard vs candidate identification/lookup tables inside `NameInput_OnCellTap` / fill helpers. Vanilla often shows stale non-zero heap (e.g. `0xffffffa6`) and **still works**. Forcing `+0x24=0` on every redraw makes OnCellTap match the wrong pane-name table → silent no-op taps. Shared-pad `+0xA0` now holds the FindPane NX guard (**§15.7**), not this banned patch.

### 17.3 Architecture notes (verified)

**Addresses (file / Ghidra base 0; VA = file + `0x100000`):**

| Name | File |
|------|------|
| Pane warmup / create+attach loop | `0x1fa2d0` … (absorbed into bogus mega-fn `FUN_000f9ea8` in Ghidra — re-split later) |
| `Pane_AttachToParent` call (create path) | `0x1fa790` |
| `NameInput_RedrawKeyboard` | `0x1fa81c` |
| `NameInput_FillKeyboard_Kanji` | `0x1fa918` (tail before shared epilogue `0x1faa20`) |
| `NameInput_FillKeyboard_ABC` | `0x1fab9c` (mode 4; pack `0x7004`) |
| `NameInput_OnCellTap` | `0x1faee4` |
| `GetCharWidthCells` | `0x005c0748` (ASCII `< 0x80` → 1, else 2; used by `DrawTextToPane`) |
| `NameInput_SetDisplayMode` | `0x1fba38` |
| `NameInput_FillCandidates` | `0x1fb438` (tail `strb +0x44=1` @ `0x1fb724`) |
| `NameInput_FillGridFromResourceTable` | (fills all 60 from TRB when tick allows) |
| `NameInput_TickDeferredGridFill` | `0x1fb964` (vtable; if `+0x44!=0` && `+0x540==0` → FillGrid…) |
| `NameInput_DrawCell` | `0x1fc304` |
| `Delegate_BindByKey` | `0x005eba00` |
| `Pane_AttachToParent` | `0x00545550` |
| `Pane_FindPaneByName` | `0x005459d8` (`BLX r3` @ `0x00545a28`, VA `0x00645A2C` = LR of the title NX dump) |

**Parent for attach is not “uninitialized luck” alone:** `Delegate_BindByKey` writes an out-struct at `sp+0x38`; field at `+4` (`sp+0x3c`) is the parent passed to attach. Live vanilla/modded (when Bind succeeds): `sp+0x38` stable (e.g. `0x82ee38`), `sp+0x3c` = per-cell parent stepping by `0x250`.

**Candidate packs:** runtime pack table for candidates is `0x7008`–`0x7033` (not keyboard-label pack `0x7002`). Cell metadata at `nameInputObj + cellIdx*0x10 + 0x180` (string / flags / pack / slot).

**gdb_probe gotcha:** `break` with `max-hits N` **detaches on the last hit without `continue`**, aborting the function. Attaching mid pane-warmup (e.g. 5/60 attaches) leaves a half-built, unclickable grid until a clean re-entry. Prefer post-fill tail breaks (`0x1faa20`, `0x1fb724`) or read-only `gdb_probe.py read`. Tool: `tools/gdb_probe.py` (Azahar gdbstub port `24689`).

**LayeredFS:** “vanilla ROM” still loads `mods\00040000000F4E00\exefs\code.bin` if present under the **active** Azahar user dir — use a/b instances or rename that folder to test true vanilla. Prefer `NLPP_AZAHAR_USER_DIR` → `out/azahar_instances/{a,b}/user` over roaming AppData while iterating.

**Live code caves (shipped stack only; file `< 0x00690000` = .text RX):**

| Pad | Contents |
|-----|----------|
| `@0x0068F800` | Shared nullguard / fillflag caves (do not collide offsets below) |
| `@0x0068F900` | Romaji DrawCell blob (Hepburn tables + code; strings still built on stack) |
| `@0x1fb070` | Kana-direct = **single NOP** (no cave) |

Old pads `@0x006E6A38` / `@0x006FBB08` are **.rodata** (no-X). Azahar still runs them; a real 3DS prefetch-aborts (`Permission - Page`, PC `0x007E6A78` = old shared +0x40).

Shared map `@0x0068F800`:

| Offset | Patch |
|--------|--------|
| `+0x00` | TalkWindow delay cap (`patch_message_speed.py`, 0x28) — **§21** |
| `+0x28` | `patch_lyt_null_pane.py` attach null child/parent (0x18) — **§15.7** |
| `+0x40` / `+0x60` | candidate nullguard |
| `+0x90` | pane-registry nullguard |
| `+0xA0` | `patch_lyt_null_pane.py` FindPaneByName `BLX r3` guard (0x20) — **§15.7**. Slot was candmode_reset (banned); do not revive `+0x24=0` here |
| `+0xC0` | fillflag_reset (`+0x44` / `+0x30`) |

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
4. **Hardware NX:** name-input caves must stay in `.text` page padding (`src/patch_input_cave_map.py`). Rebuild `release/name_input_code.bin` from vanilla after moving caves, then re-Drop the CIA.
5. Optional: compact ABC grid empty slots 26–29 (Y/Z then four blanks before lowercase) — TRB pack `0x7004` leftover 6-col layout, not the spacing bug.

### 17.7 ABC fullwidth Latin → ASCII (2026-09-18)

ABC/Symbols TRB pack **`0x7004`** (`NameInput_FillKeyboard_ABC` `@0x001fab9c`; mode-4 packs at file `0x006c2d48`) is U+FF01–U+FF5E (`Ａ` not `A`). `GetCharWidthCells` `@0x005C0748` (from `DrawTextToPane`) returns **2** for those codepoints (ASCII `< 0x80` → 1), so First Name and in-game DrawText look like `A B C`. Do **not** change `GetCharWidthCells` globally.

`kana_to_romaji` (`patch_input_romaji.py` cave `@0x0068F900`) maps that UTF-8 (`EF BC 81..BF` / `EF BD 80..9E`) to ASCII **before** the DrawCell copy into `obj+idx*8+0x541`. `NameInput_OnCellTap` copies that slot into `+0x46`; strcat-raw joins the save string. New ABC names are packed halfwidth everywhere DrawText runs (profile field + dialogue tags). Re-enter an already-saved fullwidth name to convert it.

Tests: `tests/test_name_input_caves.py` (`test_fullwidth_latin_to_ascii_abc_pack`, `test_romaji_cave_converts_fullwidth_utf8`). Rebuild: `python tools/deploy_name_input_en.py --src <code.bin.bak> --out release/name_input_code.bin`.

| Symbol | File |
|--------|------|
| `NameInput_OnCellTap` | `0x1faee4` |
| Kana-direct NOP site | `0x1fb070` |
| `NameInput_DrawCell` | `0x1fc304` |
| Romaji cave | `0x0068F900` |

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
| Shared Nene save | `ab_test/saves/nene/` via `.\make.ps1 save-nene` (`tools/import_azahar_save.py`) — SD title save `sdmc/.../000f4e00/data/00000001`, not extra data |

Do **not** tell the user to quit Azahar between deploys (standing preference).

### 18.2 CIA patcher — no decryptor

`src/patch_cia.py` / drop bat accept **decrypted** `.cia` / `.3ds` / `.cci` only (`Crypto Key: None`). Encrypted input fails with a short “decrypt yourself first” message. `decrypt.exe` / Batch CIA 3DS Decryptor Redux were **removed** from the tree — users decrypt outside EngPatcher (GodMode9, etc.). Still vendored: `tools/cia/` `3dstool` / `ctrtool` / `makerom` / `seeddb`.

Offline `vendor/NLPPATCH/` was removed from main (2026-08-31); NLPP-005 may re-vendor it for layered script inject (§19). Dialogue/TRB still primarily live in `rebuild_dbin2/` + `assets/`. Optional: `patch_textresource.py seed --alt-trb <other.trb>` if you bring an external EN TRB.

### 18.3 Communications loading hang — OpenLinkFile (2026-09-18)

See **§10.1**. `.\make.ps1 build-azahar` applies `ab_test/patches/azahar-openlinkfile.patch` and copies `azahar.exe` into the instance folders. Drop CIA / gold `img.bin` do not include this (hardware FS is fine).

### 18.4 Game Start hang — parent extra-data OpenLinkFile (2026-09-18)

See **§10.2**. Same `0x33373338` smash as Communications, but the clone patch is already in instance A and the source handle is the full extra-data backend (`subfile=false`, `size=0x65a13720`). Reset unsticks it. Does **not** extend to a real 3DS. Do not restore extra data or patch `code.bin` for this.

---

*Last updated 2026-09-18 — §10.2 Game Start parent extra-data hang (not hardware); §12.4.4 Profile Call/atlas chroma AA (not 1-bit); §12.4.3 hometown chips; §12.4.2 Profile header Heisei strip; §15.1.1 hub header RGB dump (`Title_menu_word`); §17.7 ABC fullwidth→ASCII; §12.4.1 Heart to Heart MultiWin bar; §15.7 title hub loop NX abort (`patch_lyt_null_pane.py`); §10.1 OpenLinkFile patch + `build-azahar`; §21 gold `name_input_code.bin` Message Speed; keep main §§16–18; NLPP-005 §19 / §20 volunteer workbench; §13.3 third-party stack.*

---

## 19. Patch composition reset + progress metrics (2026-09-01 session)

Session goal: ship a **known-good stack** — community NLPPPATCH baseline + full Manaka + EN UI bake + working nicknames — and document **measurable progress** for a fansite.

### 19.1 Script inject (layered)

**Module:** `src/script_inject.py` — used by `patch_cia.py` `inject_dbin2()`.

| Priority | Source | Stems |
|----------|--------|-------|
| 1 | `rebuild_dbin2/<pack>/t*.dbin2` | Manaka 100% (175 in `script` pack) |
| 2 | `rebuild_dbin2/<pack>/p*.dbin2` | Common 100% (55) |
| 3 | `rebuild_dbin2/script/{a,k}*.dbin2` | Community ~28% (ex-NLPPATCH; allowlist `assets/nlppatch/stems.json`, ~96 stems) |
| 4 | Base ROM | Everything else JP |

**Not injected from XML:** Nene (`a*`) / Rinko (`k*`) — community binaries in `rebuild_dbin2` / JP ROM until promoted. (Former `assets/scripts_deferred/` machine-EN stash removed 2026-09-03.)

**Community layer:** integrated into EngPatcher — no `vendor/NLPPATCH` required for Drop. Re-import: `tools/fetch_nlppatch_release.py` then `tools/integrate_nlppatch_into_rebuild.py` (NLPPCTR fallback if the old release zip 404s).

**Headline script-pack coverage:** **326 / 578 (56.4%)**. Legacy "28%" = community layer alone (~169 stems upstream / ~96 injected after Manaka/`p*` override).

### 19.2 Nickname / name-table fix

| Issue | Fix |
|-------|-----|
| `▲高嶺＊＊▲` expanded to plain `Takane` in `.dbin2` | `patch_names.py` default keeps dialog tokens; `--strip-dialog-tokens` legacy |
| Stale `rebuild_dbin2` without tokens | Rebuild from XML (`tools/rebuild_dbin2_from_xml.py` when present); `tools/restore_nickname_tokens.py` (Makein ref in `cache/makein_compare/`) |
| Resident TRB sourced from EN-pre-patched sibling dump → 0 `patch_names` replacements | `patch_cia._resolve_resident_trb()` prefers `release/romfs_overlay/.../textresource_resident_jpn.trb` first |

### 19.3 UI / menu images (NLPPCTR migration)

Community EN menu art was merged into the normal `img.bin` pipeline (not Citra hash overrides):

| Source | Tool | Into |
|--------|------|------|
| [NLPPCTR](https://github.com/LovePlusProject/NLPPCTR) texture pack | `tools/import_nlppctr_textures.py` | `assets/images/*.check/timg/` → `pack_images` / `release/bake_img.bin` |
| NLPP English UI Buttons zip | `tools/import_ui_buttons_bundle.py` | pkgs **5190** / **5259** / **5380** / **4149** via `deploy_ui_buttons_en.py` |
| A/B compare baseline vs NLPPCTR winners | `ab_test/make.ps1` (`nlppctr-ab`) | Isolated Azahar instances |

Gold bake unchanged by script-layer changes; redeploy LayeredFS after `img.bin` edits.

### 19.4 SMS / phone text

| Item | Detail |
|------|--------|
| Storage | `img.bin` pkg **92**: `maildic_m.mdc`, `maildic_n.mdc`, `maildic_r.mdc` |
| Gold bake | **Japanese** (rolled back for nickname-placeholder audit) |
| Re-enable EN | `tools/translate_sms_en.py` → `assets/sms_en/` → `rebuild_bake_img.py --include-sms` or `deploy_sms_maildic_en.py` |
| Restore JP | `tools/restore_sms_maildic_jpn.py` |

**1822** SMS messages total (599 + 634 + 589). Included in fansite “scripts + SMS” rollup (**326 / 2400 = 13.6%** with current JP SMS).

### 19.5 Progress metrics export (fansite)

| Tool | Output |
|------|--------|
| `tools/export_progress_metrics.py` | `out/progress_metrics.json` — per-file script lists, SMS messages, TRB STRI indices, UI PNG names |
| `tools/script_coverage_report.py` | Console summary |
| `docs/TRANSLATION_PROGRESS.md` | Human-readable headline table + fansite layout notes (2026-09-11: **562** chrome / **1727** mapped PNG masters) |

Regenerate before publishing; `out/` is gitignored.

### 19.6 `cache/` hygiene

Safe to delete (~5 GB): duplicate `cache/*.img.bin` scratch (smoke tests, NLPPCTR A/B, deploy intermediates). **Keep** `cache/nlppctr/import/` (A/B) and `cache/makein_compare/` (nickname restore) unless abandoning those workflows.

### 19.7 Open / next steps

| Item | Status |
|------|--------|
| In-game verify nicknames after resident TRB fix | **Test** — Manaka pet name, `▲主人公＊▲`, NLPPPATCH Rinko/Nene chunks |
| Re-enable EN SMS after placeholder audit | WIP — `assets/sms_en/`; use `--include-sms` |
| Full Rinko / Nene routes | **JP** except NLPPPATCH early ~28% per route |
| `img.bin` name table — 0 replacements on last deploy | Investigate if nicknames still fail in UI labels |
| Fansite progress page | Consume `out/progress_metrics.json`; see `docs/TRANSLATION_PROGRESS.md` |
| Image % denominator | Count vanilla BCLIMs per UI ARC (`ie`/`pe`) — export currently reports PNG master **counts** only |
| Commit / push session tooling | `script_inject.py`, `export_progress_metrics.py`, `restore_*.py`, etc. — whitelisted in `.gitignore` |
| README / forum post | Community update: NLPPCTR menu migration, 28% baseline restore, nickname fix, progress % |

---

## 20. Volunteer localization workbench (2026-09-03)

Browser HTML kits for community translators (no Python). Maintainer Python lives in a sibling folder; HTML **templates** live in this EngPatcher tree.

### 20.1 Three trees

| Path | Role |
|------|------|
| `…/nlpp-localization-workbench/` | **Volunteer share** — `index.html` hub + `kit/` (built Scripts / Strings / Images) |
| `…/nlpp-localization-workbench-parser/` | **Maintainer** — `export_*.py`, `ingest_*.py`, `common.py`, `paths.py`, `sync_hub.py` only |
| `EngPatcher/tools/localization_workbench/` | **Templates** — `workbench.html`, `strings_workbench.html`, `images_workbench.html`, hub `index.html` |

GitHub (volunteer): `git@github.com:czyrustuazon/nlpp-localization-workbench.git`.

Configure parser `paths.local.json` (gitignored; see `.example`):

```json
{
  "eng_patcher": "C:/path/to/NewLovePlusPlusEngPatcher",
  "workbench": "C:/path/to/nlpp-localization-workbench"
}
```

Or set `NLPP_ENG_PATCHER` / `NLPP_WORKBENCH`.

### 20.2 What each kit is for

| Kit | Built output | Content | Save → Discord JSON |
|-----|--------------|---------|---------------------|
| **Scripts** | `kit/NLPP_Translate.html` | Dialogue still needing EN (dialogs only in embed; ~6 MB) | `nlpp-contrib-….json` (`kind: nlpp-contrib`) |
| **Strings** | `kit/NLPP_Translate_Strings.html` | SMS (`maildic_*`) + TRB leftovers still JP | `nlpp-strings-….json` (`kind: nlpp-strings-contrib`) |
| **Images** | `kit/NLPP_Translate_Images/` | All UI PNG masters (**1727** across **92 / 95** `IMAGE_MAP` folders) | `nlpp-images-….json` (`kind: nlpp-images-contrib`, optional `png_b64`) |

Hub tabs lazy-load iframes; unsaved edits warn via `postMessage` `{type:'nlpp-unsaved', tool, dirty}`.

**Volunteer loop:** open hub → edit → **Save progress** → post JSON in Discord `#translated-work-to-review`.

Snapshot sizes fluctuate as EN lands; regenerate kits before sharing. Example post-export counts (2026-09-11): Scripts ~342 / ~10k JP lines; Strings ~1822 SMS + leftover TRB; Images **1727** PNGs / **92 of 95** folders (empty: `intro111`, `intro203`, `intro304`). Chrome-only subset for the fansite bar is **562** in 25 folders (`tools/export_progress_metrics.py`).

#### Scripts kit — routes and sources (`export_workkit.py`)

Includes stems for **all routes**, but the sidebar **Needs translation** filter only lists scripts that still have real JP after token/punct stripping. That is why a “needs work” list can look **Manaka-only** (`t*`) even though Nene (`a*`) / Rinko (`k*`) are present under **All scripts**.

| Prefix | Route |
|--------|-------|
| `a*` | Nene |
| `k*` | Rinko |
| `t*` | Manaka |
| `p*` | Common |

**Source priority (volunteer baselines):**

1. **Post-game** (`a`/`k`/`t`/`p` id ≥ **800**, incl. **Manaka `t8xx`/`t9xx`**): JP `.dbin2` first (CIA cache → NLPPATCH → dump), then `assets/scripts/`
2. **Early-game:** `assets/scripts/*.xml` first (Manaka/common WIP), then the same `.dbin2` search order
3. **JP `.dbin2` order:** `cache/vanilla_from_rom/romfs/script/bin/script/` (from known JP CIA) → NLPPATCH → sibling `extracted/` (often EN-overwritten — last resort)

Refresh JP cache (keeps scripts even with `--slim`):

```text
python src/setup_tools.py
python src/extract_vanilla_from_rom.py --rom "<known JP .cia>" --force --slim
```

Known encrypted CIA SHA-1 `a9fbd2e6…` (see README). Env override: `NLPP_VANILLA_SCRIPT`.

Former `assets/scripts_deferred/` (machine/community EN) was **deleted** 2026-09-03.

**Empty post-game stubs:** many ids (`a800`, `t800`, `t921`, …) are **0 dialogs** even on JP retail — export correctly skips them. Contentful post-game (e.g. `a970` / `k970` / `t970` / `t912` / `t999`) loads from the JP cache.

Jump: `a042`, `k100`, `a970`, `k970`, `t151 - #775`. Filter: All / Needs JP / Done / Edited (no route dropdown).

#### Strings kit — SMS + TRB (`export_strings.py`)

| Kind | What | Source | Notes |
|------|------|--------|-------|
| **SMS** | Phone texts for Manaka / Nene / Rinko | `img.bin` package **92** `maildic_{m,n,r}.mdc` (vanilla or bake) | Optional overlay `assets/sms_en/*.en.xml` if present; only lines still JP after overlay |
| **TRB** | Main table leftovers | `textresource_jpn.trb` + `assets/textresource/translations.json` | Only STRI entries whose **working** text still has JP (already-mapped EN omitted) |

Heroine SMS stems: Manaka `maildic_m`, Nene `maildic_n`, Rinko `maildic_r`. Jump: `sms/manaka#12`, `trb#2837`. SMS max ~254 UTF-8 bytes. Keep `※` / `▼` / `▲…＊…▲`.

#### Images kit — UI PNG audit (`export_images.py`)

**Goal:** community review of **every** EngPatcher UI PNG master mapped in `src/image_map.py` (menus, softkeys, headers, mail, date-edit, camera, title, syspopup, …) — not dialogue scripts.

| Piece | Path / rule |
|-------|-------------|
| Masters root | `EngPatcher/assets/images/` |
| Folder pick | `prefer_asset_folders`: prefer `*.check` dumps, then plain folders, over `*.arc` trees |
| Files | All PNGs under each mapped folder via `iter_asset_pngs` (prefer `*_eng` / `timg/`; skip copies / `_jpn` / `(2)`) |
| Share layout | `kit/NLPP_Translate_Images/index.html` + `media/<folder_key>/…` + `catalog.json` (+ `.zip`) |
| Volunteer actions | Unchecked → **OK** / **Needs fix** / **Upload PNG** (same W×H) → Save → JSON may embed `png_b64` |
| Preview | Background toggle (light checker default) — view only |

**Not included:** non-`IMAGE_MAP` folders, `Images-Done` archives as a separate tree (EN masters already preferred via `.check` / `_eng`), fonts, scripts XML, TRB binaries. Large chrome packages appear as folder keys such as `ncommonicon`, `ncommonmsel*`, `title`, `myroomheader`, `syspopup`, `dateedit*`, `mail`, `option*`, etc. Full mapped export is **92 of 95** keys / **1727** PNGs (empty: `intro111`, `intro203`, `intro304`). Do not quote the old ~68 / ~1210 snapshot.

Ingest: `ingest_images.py --apply` writes replacements back under `assets/images/` for later `pack_images` / bake.

### 20.3 Maintainer export / ingest

```bash
cd nlpp-localization-workbench-parser
python export_workkit.py
python export_strings.py
python export_images.py
python sync_hub.py

python ingest_pack.py path/to/nlpp-contrib.json --apply
python ingest_strings.py path/to/nlpp-strings.json --apply
python ingest_images.py path/to/nlpp-images.json --apply
```

- Export reads templates from `tools/localization_workbench/` via `paths.templates_dir()`.
- Export writes under `workbench/kit/` (and hub `index.html`).
- Ingest applies into EngPatcher `assets/` (scripts XML, `translations.json` / SMS, UI PNGs) — review before bake/CIA.

Pack **schema `1`**. Edit UI behavior in EngPatcher templates, then re-export (do not hand-edit the giant embedded kit HTML).

### 20.4 Validation / UX rules (kit + ingest)

| Rule | Behavior |
|------|----------|
| Nickname tokens `▲…＊…▲` (incl. unclosed forms) | Warn / confirm on save; ingest errors if multiset changes |
| Control marks `※`, `▼` | **Hard block** save if count drops vs baseline; ingest rejects |
| `●` bullets | Scripts warn if count changes |
| Lone `ー` / `・` | Not counted as “needs JP” (katakana block false positive) |
| Punct-only / circle placeholders `○○○` | Locked / skip “needs work” |
| SMS UTF-8 length | Cap 254 bytes (+NUL slot); Strings kit blocks oversize |
| Image replace | Must match catalog width × height; `png_b64` in JSON |
| Script list badge | `N left · total` (remaining JP dialogs, not “done / total”) |
| Images preview bg | Toggle light/dark/white/black/magenta checker (view only; PNG unchanged) |

Nav: Prev/Next paginate; jump (`t151 - #775`, `sms/manaka#12`, `trb#2837`, `folder / stem`); Last spot + `localStorage`.

### 20.5 What not to confuse

- Volunteer **built** kits ≠ EngPatcher **templates** — only templates are edited for UI changes.
- Parser repo must stay **Python-only** (HTML removed 2026-09-03).
- `contrib/` in EngPatcher is a pointer README only (old in-tree workbench moved out).
- Workbench kits are for **leftover** JP / UI audit — finished shipping assets remain under EngPatcher `assets/` + `rebuild_dbin2/`.

### 20.6 Open follow-ups

| Item | Notes |
|------|-------|
| Private vs public parser GitHub | Parser has local paths via `paths.local.json` only; safe to publish if desired |
| Large kit HTML on Git | Volunteer repo may ship full `kit/` (~tens of MB); Drive/zip OK as alternate |
| Discord size limits | Large `png_b64` JSON may need zip-of-PNGs later; ingest still expects `png_b64` today |
| Bake after ingest | Always re-run bake / deploy / CIA after applying contrib packs |

---

## 21. Message Speed typewriter (2026-09-13, in-game 2026-09-17)

Display Settings → **Message Speed** is a 1–4 slider. It is **not** TRB and not a BCLIM. Three printers share the saved level (`cfg+0x0C`) but **not** the same delay table:

1. Options preview widget — `FUN_005d1e18` 18/12/6/0 → **14/8/2/0** (§21.2).
2. Unvoiced TalkWindow — `.rodata` @ `0x006E3024` 40/70/90/110/220 → **10/18/22/28/55** (§21.4).
3. Voiced / scripted TalkWindow — `+0xd60` / `+0xd5c` replace that table unless capped (§21.5–21.6).

Ghidra image base **0**. Runtime VA = file + `0x100000`.

### 21.1 Call chain

1. Display Settings UI operator setup `FUN_001d2f90` @ `0x001D2F90` (VA `0x002D2F90`) copies the sample via `FUN_005d191c` and binds pane `Window_Message` (`0x001D3080`) through `FUN_002d4d2c` → ctor `FUN_002d5574`.

2. Slider change `FUN_001d2e5c` @ `0x001D2E5C` reads the slit/knob with `FUN_005c4578`, maps level→delay with `FUN_005d1e18`, stores delay at UI object **`+0x118`**.

3. Tick `FUN_002d544c` @ `0x002D544C` (VA `0x003D544C`) advances one glyph when the frame accumulator at widget `+0x2C` reaches delay at **`+0x24`**. Delay `0` dumps the whole string through `DrawTextToPane` (`FUN_0054b880`). Replay/reset is `FUN_002d553c` (clears `+0x28` / `+0x2C` on the widget at UI `+0xF4`).

Message widget (Display Settings `this+0xF4`; delay alias `this+0x118` = widget `+0x24`):

| Offset | Field |
|--------|--------|
| `+0x08` | Text pane |
| `+0x0C` | MakeStr object (`FUN_005a1dcc`) |
| `+0x1C` | Glyph total (used when delay is 0) |
| `+0x24` | **Frames per glyph** (`0` = instant) |
| `+0x28` | Glyphs currently shown |
| `+0x2C` | Frame accumulator |
| Symbol | File offset | Runtime VA |
|--------|-------------|------------|
| `FUN_005d1e18` delay lookup | `0x005D1E18` | `0x006D1E18` |
| `FUN_002d544c` typewriter tick | `0x002D544C` | `0x003D544C` |
| `FUN_002d5574` message-pane ctor | `0x002D5574` | `0x003D5574` |
| `FUN_002d553c` replay/reset | `0x002D553C` | `0x003D553C` |
| `FUN_001d2e5c` slider → delay | `0x001D2E5C` | `0x002D2E5C` |
| `FUN_001d2f90` sample setup | `0x001D2F90` | `0x002D2F90` |
| `FUN_005d191c` strncpy wrapper | `0x005D191C` | `0x006D191C` |
| Sample UTF-8 `メッセージ速度テストです。` | `0x005D1928` | `0x006D1928` |
| `Window_Message` C-string | `0x001D3080` | `0x002D3080` |
| `DrawTextToPane` | `0x0054B880` | `0x0064B880` |

Options Display Settings is window index **2** (`FUN_00682830` / `UIWindowMgr_Show(..., 0, 2, ...)`).

### 21.2 Delay table (patched −4 frames)

`FUN_005d1e18` is a unique `cmp` / `moveq r0,#imm` / `beq` chain (only one copy in `code.bin`). EngPatcher subtracts 4 from each **positive** delay; level 4 stays 0 (cannot go negative).

| Slider | Vanilla frames | Vanilla insn | Patch frames | Patch insn |
|--------|----------------|--------------|--------------|------------|
| 1 | 18 | `moveq r0,#0x12` @ `0x005D1E1C` | **14** | `#0x0E` |
| 2 | 12 | `moveq r0,#0x0C` @ `0x005D1E28` | **8** | `#0x08` |
| 3 | 6 | `moveq r0,#0x06` @ `0x005D1E34` | **2** | `#0x02` |
| 4 | 0 (instant) | `moveq r0,#0x00` @ `0x005D1E40` | **0** | unchanged |

Script: `src/patch_message_speed.py` (Options + TalkWindow table §21.4 + voice/script cap §21.6). Applied from `tools/deploy_name_input_en.py` so Drop CIA / `rebuild_bake_img.py` inject it inside `release/name_input_code.bin`. LayeredFS-only: `python src/patch_message_speed.py --deploy-azahar` (backup `exefs/code.bin.bak_pre_msg_speed`). Tests: `tests/test_patch_message_speed.py`.

### 21.3 Save encoding

The slider **level** (1–4), not the 18/12/6/0 delay, is what gets written to save/config. `FUN_005d1e18` has **two** Options-only callers (`FUN_001d2e5c` and the Display Settings tick at `0x001D3520`). In-game talk does **not** read that table.

Config manager singleton pointer **`0x0089A330`** (literals at `0x005CD30C` load / `0x005CDBA0` save).

| Op | Function | File | What |
|----|----------|------|------|
| Save | `FUN_005cdaa0` → `FUN_002d87a4` | `0x005CDAA0` / `0x002D87A4` | `*(cfg+0x0C) = level * 0x40 - 1` → `0x3F` / `0x7F` / `0xBF` / `0xFF` |
| Load | `FUN_005cd218` | `0x005CD218` | `level = (*(cfg+0x0C) + 1) >> 6` (clamped 1–4) |
| Clamp | `FUN_002d87a4` | `0x002D87A4` | min word `0x006C5504` = `0`, max `0x006C5508` = `0xFF` |
| Load object | `*(singleton+0x68)+0x0C` | | |
| Save object | `*(singleton+0x6C)+0x0C` | | |

Help Display Every Time/Once is a neighboring byte at config `+0x20` (inverted: `0` → show every time). Color knob is `+0x10…+0x1C` via `FUN_002d8754`.

### 21.4 In-game TalkWindow delay (patched /4)

NLPP-024 patched only `FUN_005d1e18`. That table is **Options-only** (`FUN_002d544c` has no ARM `BL` callers — vtable / Display Settings widget). Date talk did not change.

Live date talk is `TalkWindowProcess` (`FUN_0013f6a4`), not `Window_Message`. Glyph progress lives at talk object `+0xd50` (shown) / `+0xd54` (total). The per-glyph tick at `0x0013B6C4` divides elapsed time by a wait from this `.rodata` table:

| File | Runtime VA | Vanilla dwords | Patch |
|------|------------|----------------|-------|
| `0x006E3024` | `0x007E3024` | **40, 70, 90, 110, 220, 0** | **10, 18, 22, 28, 55, 0** |

Index is TalkWindow `+0xd9c`. Setter `FUN_0013f260` @ `0x0013F260` stores `r1` only if `r1 < 5` (so table[5]=0 instant is unused; delay 0 would divide-by-zero in `FUN_0001a43c`). Converter `FUN_002d8874` @ `0x002D8874` maps saved `cfg+0x0C`:

| Slider | Saved rate | Index | Vanilla wait | Patch wait |
|--------|------------|-------|--------------|------------|
| 1 | `0x3F` | 3 | 110 | **28** |
| 2 | `0x7F` | 2 | 90 | **22** |
| 3 | `0xBF` | 1 | 70 | **18** |
| 4 | `0xFF` | 0 | 40 | **10** |

Callers (pass `*(obj+0x0C)` through `FUN_002d8874` then `FUN_0013f260`): `FUN_003bd280`, `FUN_003c2130`. Draw with new glyph count: `FUN_0013bd20`. Tap-to-complete is a separate skip (`r11`) that copies `+0xd54` → `+0xd50`.

Patching this table (still `src/patch_message_speed.py`) made **unvoiced player** lines fast. It is not sufficient for voiced talk — §21.5.

### 21.5 Tick delay select (player vs NPC vs heroine)

After the table load, the same tick **replaces** `r2` before `cpy r6, r2` @ `0x0013B718`:

| Priority | Condition | `r2` becomes | Who |
|----------|-----------|--------------|-----|
| 1 | `+0xd5c > 0` | script wait (skip voice) | some NPC / scripted lines |
| 2 | `+0xd5c == 0` and `+0xd60 > 0` and `+0xd54 > 0` | `(+0xd60 / +0xd54) + 1` via `FUN_00022d48` | main heroines (voice clip) |
| 3 | else | `table[+0xd9c]` | unvoiced player |

Voice divide is `BL 0x00022D48` @ `0x0013B710`, then `add r2, r0, #1` @ `0x0013B714`. That `BL` clobbers `r2`, so the table value is gone by the time voice-sync finishes. `GetTalkDelay` @ `0x00625EC4` duplicates this logic; no ARM `BL` callers in `code.bin` (leave it).

`+0xd60` writers (duration, one path clamps `movge r0, #0x1F4` = 500): `0x0013F4C8`, `0x0013C00C`, `0x0013C09C`. `+0xd5c` writers: `0x0013EC3C`, `0x0013EF08`, ctor `0x0013F930`.

A/B on Azahar instances (2026-09-17), same /4 table, same slider:

- Player lines: fast (table path).
- NPC lines: slightly slower (`+0xd5c` or a short `+0xd60`).
- Heroine date lines: vanilla-slow (voice-sync ignores the table).

Do **not** hunt `cfg+0x0C` readers in `FUN_005cb47c` / `FUN_005d1d00` — those are unrelated. Do **not** treat Options `FUN_002d544c` as the in-game printer.

### 21.6 Voice/script cap cave (NLPP-025)

Intent: Message Speed is a **ceiling**. Script/voice may still print *faster* than the slider; they must not print *slower*.

Hook **after** all three paths, replacing `cpy r6, r2` (`E1A06002`) @ `0x0013B718` with `BL` to a `.text` cave. Cannot fold the `min` into the `0x0013B710` `BL` slot — the divide already ate `r2`, and a callee-saved save would need the same extra bytes.

Cave @ `0x0068F800` (`ADDR_TALK_CAP_CAVE`, `TALK_CAP_CAVE_LEN = 0x28`). Last `.text` RX page (hardware NX: do not put this in `.rodata`). Cand nullguard starts at shared pad `+0x40` (`0x0068F840`); this cave must stay below that.

`r4` is TalkWindow `this` for the whole tick. `r0`/`r1` are scratch after return (`0x0013B720` reloads a 1e6 constant into `r2`). Cave:

```
ldr  r0, [r4, #0xd9c]          ; slider index
ldr  r1, [pc, #table]          ; VA 0x007E3024
ldr  r1, [r1, r0, lsl #2]      ; table[index]
cmp  r1, #0
moveq r1, #1                   ; never cap with 0 (divide-by-zero)
cmp  r2, r1
movgt r2, r1                   ; r2 = min(computed, table)
cpy  r6, r2                    ; original insn
bx   lr
.word 0x007E3024
```

`is_fully_patched` requires Options **and** TalkWindow table **and** this hook (half-patched `name_input_code.bin` used to skip the table because `is_patched` meant Options-only).

Ship path: `apply_patch` from `tools/deploy_name_input_en.py` → `release/name_input_code.bin` (Drop CIA / `rebuild_bake_img.py`). Rebuild from vanilla (`code.bin.bak` preferred) when gold still has TalkWindow 40/70/90/110/220:

```bash
python tools/deploy_name_input_en.py --src extracted/exefs/code.bin.bak --out release/name_input_code.bin
```

LayeredFS: copy that file to instance `exefs/code.bin` (and mod-root `code.bin`), or `--deploy-azahar` / `.\make.ps1 talk-speed-ab` (**A** = table + cap, **B** = table only / vanilla heroine). Tests: `tests/test_patch_message_speed.py`, cave overlap in `tests/test_name_input_caves.py`.

Verified 2026-09-17: heroine date line on **A** matches player speed; **B** still crawls.

### 21.7 Sample sentence

`メッセージ速度テストです。` is a UTF-8 literal in `code.bin` at `0x005D1928` (39 bytes + NUL, immediately before the next ARM insn at `0x005D1950`). Ghidra string search misses it; it is **not** TRB. `FUN_001d2f90` copies it through `FUN_005d191c`.

Patch: in-place EN `This is a text-speed test.` + NUL pad in the same 40-byte slot (`patch_message_speed.py` / gold `name_input_code.bin`). Do not grow the pool. Do not use a `.rodata` pad.

---

*Last updated 2026-09-17 — §21 TalkWindow table + voice/script cap (NLPP-025); UI PNG masters **1727** mapped / **562** chrome (`export_progress_metrics.py`); volunteer kit sizes in §20.2.*

