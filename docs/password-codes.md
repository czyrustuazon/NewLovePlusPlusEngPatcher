# Options password codes (NEW Love Plus+)

Enter from the title menu: **Options → Password**. Use the ABC keyboard. Codes are **case-sensitive**.

Each code works **once** per save. Give presents one at a time; stocking every gift at once can lock the shop.

Vanilla magazine/collab strings live in `textresource_jpn.trb` pack **`0xb000`** (INDX cat 176, slots 0–52). They are **not** ASCII in `code.bin`. `FUN_00132d40` `strcmp`s the typed buffer against those slots (0..`0x34`). EngPatcher fills the old `なし` serial holes via `src/patch_password_serials.py` (rebuild: `tools/deploy_name_kanji_trb.py`). Umbrella presents for `UriboKasa*` are a `code.bin` table remap (`src/patch_password_uribo.py`, ships in `release/name_input_code.bin`). Chrome on this screen is BCLIM (pkg **5251** / **5245**), not TRB.

---

## How matching and grants work

Two different systems. Filling a `0xb000` hole only makes the string match; the **present** comes from a later grant table.

1. **Match** — `FUN_00132d40` walks pack `0xb000`. Shared hit stores `+0x88=1`, `+0x94=slot`, `+0x89=0`. Per-copy serials use `+0x89=1` / `+0x8b=1` via PAK `FUN_00598f14` (VISA `LV…`, Pia book serial, ウリボー product serial). Vanilla empty holes all point at the shared placeholder STRI **24550** `なし` (NLP flag 0). The ABC keyboard cannot type it, so those slots never matched. Do **not** rewrite 24550 globally.
2. **Used bit** — `FUN_00257600` / `FUN_002575c4` keep an 8-byte bitfield (`+0xc`, slots 0–52). Each code is once per save.
3. **Grant** — `FUN_0038dc70` reads `s32 item_id[53]` at file **`0x006B6F00`** (VA `0x007B6F00`). Positive ids go to `FUN_00390058`. Sentinels branch:

| Table value | Vanilla slots | Effect |
|-------------|---------------|--------|
| positive item id | 0–17, 19–22 | magazine present (`0x0404` catalog) |
| `-1` | 18, 23, 30–32 | 100 Riches (`FUN_0025959c(..., 100)`) |
| `-200` | 24–26 | VISA: heroine items **465/466/467** + Your Nickname (`FUN_003b82e0` checks slot **24**) |
| `-100` | 27–29 | Pia muffler ids **350 / 352 / 353** (heroine 0/1/2) |
| `-500` | 33–40 | junk item `uxth(-500)` + **内部** inventory flags |
| `-300` | 41–52 | 2014 collab straps (extra per-heroine table) |

Inventory-key split in the same function (`cmp r4, #0x21` @ `0x0038DDA0`):

| Slot range | Vanilla meaning | Flag formula |
|------------|-----------------|--------------|
| `< 33` (`#0x21`) | presents / VISA / Pia / Riches | `0x04000614 + slot` |
| `33–51` | 内部 then straps | `0x04000659 + slot` |
| `52` | last strap pack | `0x0400066C + slot` |

EngPatcher `patch_password_uribo.py` writes **465/466/467** over slots 33–35 and changes the compare to `#0x24`, so `UriboKasa*` use present flags `0x04000635..637` instead of 内部. Slots 36–40 stay `-500` / 内部.

Pack **`0xb001`** is the source *label* (週刊ファミ通, VISAカード, 内部, …). Serial conversion only retargets `0xb000`; 内部 labels on 33–40 stay in `0xb001`.

---

## EngPatcher shared codes (new)

These replace empty pack `0xb000` slots that used to require VISA student IDs, per-copy Pia serials, or internal/PAK serials.

### VISA → Your Nickname (slots 24–26)

| Code | Girl | Slot |
|------|------|------|
| `JuhanoManaka` | Manaka | 24 |
| `JuhanoRinko` | Rinko | 25 |
| `JuhanoNene` | Nene | 26 |

Vanilla asked for the 十羽野 student ID printed on a Love Plus VISA card (`LV…` path + PAK table). These three are ordinary shared passwords now. The grant table `-200` branch already loads umbrella item ids 465–467, so `Juhano*` may add ウリボー傘 **and** Your Nickname.

### Pia muffler (slots 27–29)

| Code | Girl | Slot |
|------|------|------|
| `PiaMufflerM` | Manaka | 27 |
| `PiaMufflerR` | Rinko | 28 |
| `PiaMufflerN` | Nene | 29 |

Wiki’s leaked Pia serial `34874P6786` is **not** in this ROM’s `0xb000` table (each ラブプラスぴあ copy had its own serial). Use the codes above. Grant ids 350/352/353 are the collab mufflers (name STRI ピンク/イエロー/ブルーのマフラー sit next door at `0x0404` slots 349–351).

### ウリボー umbrella (slots 33–35) + remaining 内部 holes (36–40)

ウリボー has **no** dedicated vanilla `0xb000` slot (PAK serial only). `UriboKasa*` occupy the first 内部 triplet. Without the `code.bin` remap those bits still fired 内部 unlocks (Arcade Colorful Clip / MEDAL Happy Daily Life / all Love Plus mode). `patch_password_uribo.py` remaps grant table slots 33–35 to present ids **465/466/467** (`0x0404` ウリボー傘, three identical names for M/R/N) and keeps those slots on the present inventory path. Slots 36–40 stay 内部.

Use `UriboKasa*` for umbrella **without** the VISA nickname. `Juhano*` is nickname (and may also add the umbrella via `-200`).

| Code | Reward | Slot |
|------|--------|------|
| `UriboKasaM` | ウリボー傘 Manaka | 33 |
| `UriboKasaR` | ウリボー傘 Rinko | 34 |
| `UriboKasaN` | ウリボー傘 Nene | 35 |
| `SpecGallery` | Special gallery (all illustrations) | 36 |
| `MeishiPaper` | All business-card templates | 37 |
| `MeishiSeal` | All business-card stickers | 38 |
| `AllCostumes` | All costumes | 39 |
| `KiseVoice` | All voice messages (着ボイス) | 40 |

---

## Vanilla codes still in the game (old)

### NEW Love Plus+ collab straps (2014) — all three girls

| Code | Source | Reward | Slot |
|------|--------|--------|------|
| `WfamiKG6` | Weekly Famitsu | Famitsu strap | 41 |
| `4GNHJ4F4` | 4Gamer.net | 4-kame strap | 42 |
| `FamiCPrn` | Famitsu.com | Famitsu.com strap | 43 |
| `GsMscAzX` | Dengeki G’s magazine | G’s collab strap | 44 |
| `AsWEanps` | Weekly ASCII | Satora instructor strap | 45 |
| `NinD3Sea` | Nintendo Dream | Nindori-kun strap | 46 |
| `CompF45G` | Comptiq | Comptiq strap | 47 |
| `GSRiEfYc` | Monthly Shonen Rival | Nanami K. Bladefield strap | 48 |
| `DenOnCZp` | Dengeki Online | Dengeki strap | 49 |
| `ItmeTh7P` | ITmedia / ねとらぼ | IT-chan strap | 50 |
| `TVBr9KGt` | TV Bros. | TV-kun strap | 51 |
| `NPoKGbEb` | Official Complete Guide | rabbick + Killer Bunnies + Dexy’s strap | 52 |

`FamiCPrn` is one word (wikis sometimes wrap it as `FamiCPr n`).

### Inherited from NEW Love Plus (2011–2012)

**Girl-specific presents**

| Code | Girl | Reward | Source | Slot |
|------|------|--------|--------|------|
| `Wfamitsu` | Manaka | Gloves | Weekly Famitsu | 0 |
| `Sfamitsu` | Rinko | Gloves | Weekly Famitsu | 1 |
| `Famitsu` | Nene | Gloves | Weekly Famitsu | 2 |
| `GsMagazine` | Manaka | Apron | Dengeki G’s | 3 |
| `DengekiGs` | Rinko | Apron | Dengeki G’s | 4 |
| `DGsM` | Nene | Apron | Dengeki G’s | 5 |
| `TVBrosLP` | Manaka | Pochette | TV Bros. | 6 |
| `TVBrosLOVE` | Rinko | Pochette | TV Bros. | 7 |
| `TVBros` | Nene | Pochette | TV Bros. | 8 |
| `AsciiWeek` | Manaka | Hat | Weekly ASCII | 9 |
| `AsciiAKB` | Rinko | Hat | ASCII Akihabara | 10 |
| `AsciiPlus` | Nene | Hat | ASCII Akihabara | 11 |
| `1BankujiLP` | Manaka | Loungewear | Ichiban Kuji | 20 |
| `1kujiNewLP` | Rinko | Loungewear | Ichiban Kuji | 21 |
| `IchibanNLP` | Nene | Loungewear | Ichiban Kuji | 22 |

Nene’s TV Bros. code is `TVBros`, not `TVBrosSpecial`.

**Shared (all three girls)**

| Code | Reward | Source | Slot |
|------|--------|--------|------|
| `4GamerNet` | Glasses | 4Gamer.net | 12 |
| `DenOnline` | Scarf | Dengeki Online | 13 |
| `FamitsuCom` | Pair of teacups | Famitsu.com | 14 |
| `ITmediaNLP` | Watch | ITmedia | 15 |
| `GSRival` | Silver accessory | Monthly Shonen Rival | 16 |
| `WSMagazine` | Ring | Weekly Shonen Magazine | 17 |
| `WMLOVEPLUS` | 100 Riches | Weekly Shonen Magazine | 18 |
| `BSMagazine` | Earrings | Bessatsu Shonen Magazine | 19 |
| `Nk7rP39vgF` | 100 Riches | NLP official guidebook | 23 |
| `L5jsyuN97f` | 100 Riches | Manaka no Kokoro | 30 |
| `BT4kx85puE` | 100 Riches | Rinko no Kokoro | 31 |
| `VtY69j7isw` | 100 Riches | Nene no Kokoro | 32 |

Kokoro / guidebook Riches codes each work **once** (buying extra copies does not grant again).

---

## Full slot map (`0xb000`)

`0xb001` is the vanilla source label (serial conversion does not retarget it). Grant is `item_id[slot]` @ `0x006B6F00` after the uribo remap.

| Slot | Code (after EngPatch) | `0xb001` label | Grant |
|------|----------------------|----------------|-------|
| 0 | `Wfamitsu` | 週刊ファミ通 | item 355 gloves |
| 1 | `Sfamitsu` | 週刊ファミ通 | item 358 gloves |
| 2 | `Famitsu` | 週刊ファミ通 | item 359 gloves |
| 3 | `GsMagazine` | 電撃G's magazine | item 91 apron |
| 4 | `DengekiGs` | 電撃G's magazine | item 152 apron |
| 5 | `DGsM` | 電撃G's magazine | item 213 apron |
| 6 | `TVBrosLP` | TV Bros. | item 377 pochette |
| 7 | `TVBrosLOVE` | TV Bros. | item 378 pochette |
| 8 | `TVBros` | TV Bros. | item 380 pochette |
| 9 | `AsciiWeek` | 週刊アスキー | item 332 hat |
| 10 | `AsciiAKB` | 週刊アスキー秋葉原限定版 | item 338 hat |
| 11 | `AsciiPlus` | 週刊アスキー秋葉原限定版 | item 343 hat |
| 12 | `4GamerNet` | 4Gamer | item 325 glasses |
| 13 | `DenOnline` | 電撃オンライン | item 319 scarf |
| 14 | `FamitsuCom` | ファミ通.com | item 425 teacups |
| 15 | `ITmediaNLP` | ITmedia | item 304 watch |
| 16 | `GSRival` | 月刊少年ライバル | item 314 silver accessory |
| 17 | `WSMagazine` | 週刊少年マガジン | item 292 ring |
| 18 | `WMLOVEPLUS` | 週刊少年マガジン | `-1` 100 Riches |
| 19 | `BSMagazine` | 別冊少年マガジン | item 284 earrings |
| 20 | `1BankujiLP` | 一番くじプレミアム | item 106 loungewear |
| 21 | `1kujiNewLP` | 一番くじプレミアム | item 167 loungewear |
| 22 | `IchibanNLP` | 一番くじプレミアム | item 228 loungewear |
| 23 | `Nk7rP39vgF` | NEWラブプラス公式ガイド | `-1` 100 Riches |
| 24 | `JuhanoManaka` | VISAカード | `-200` nickname + item 465 |
| 25 | `JuhanoRinko` | VISAカード | `-200` nickname + item 466 |
| 26 | `JuhanoNene` | VISAカード | `-200` nickname + item 467 |
| 27 | `PiaMufflerM` | ラブプラスぴあ | `-100` muffler 350 |
| 28 | `PiaMufflerR` | ラブプラスぴあ | `-100` muffler 352 |
| 29 | `PiaMufflerN` | ラブプラスぴあ | `-100` muffler 353 |
| 30 | `L5jsyuN97f` | マナカのココロ(SDカード) | `-1` 100 Riches |
| 31 | `BT4kx85puE` | リンコのココロ(SDカード) | `-1` 100 Riches |
| 32 | `VtY69j7isw` | ネネのココロ(SDカード) | `-1` 100 Riches |
| 33 | `UriboKasaM` | 内部 | item 465 ウリボー傘 (vanilla `-500` arcade Colorful Clip) |
| 34 | `UriboKasaR` | 内部 | item 466 ウリボー傘 (vanilla `-500` MEDAL Happy Daily Life) |
| 35 | `UriboKasaN` | 内部 | item 467 ウリボー傘 (vanilla `-500` all Love Plus mode) |
| 36 | `SpecGallery` | 内部 | `-500` all illustrations |
| 37 | `MeishiPaper` | 内部 | `-500` all card templates |
| 38 | `MeishiSeal` | 内部 | `-500` all card stickers |
| 39 | `AllCostumes` | 内部 | `-500` all costumes |
| 40 | `KiseVoice` | 内部 | `-500` all 着ボイス |
| 41 | `WfamiKG6` | 週刊ファミ通 | `-300` Famitsu strap |
| 42 | `4GNHJ4F4` | 4Gamer | `-300` 4-kame strap |
| 43 | `FamiCPrn` | ファミ通.com | `-300` Famitsu.com strap |
| 44 | `GsMscAzX` | 電撃G's magazine | `-300` G’s strap |
| 45 | `AsWEanps` | 週刊アスキー | `-300` Satora strap |
| 46 | `NinD3Sea` | ニンテンドードリーム | `-300` Nindori-kun strap |
| 47 | `CompF45G` | コンプティーク | `-300` Comptiq strap |
| 48 | `GSRiEfYc` | 月刊少年ライバル | `-300` Nanami K. strap |
| 49 | `DenOnCZp` | 電撃オンライン | `-300` Dengeki strap |
| 50 | `ItmeTh7P` | ITmedia | `-300` IT-chan strap |
| 51 | `TVBr9KGt` | TV Bros. | `-300` TV-kun strap |
| 52 | `NPoKGbEb` | (reuses slot 23’s guide label) | `-300` rabbick + Killer Bunnies + Dexy’s strap |

Slot 18 is both a magazine code (`WMLOVEPLUS`) and a `-1` Riches grant — the table value wins over a present id.

---

## Not shared passwords (vanilla only)

These never had a public magazine string in this `+` TRB. Match was PAK / unique serial, not `0xb000` `strcmp`.

| Input | Vanilla how | EngPatcher |
|-------|-------------|------------|
| Love Plus VISA **学籍番号** | Printed on 十羽野高校 student ID; `LV…` + PAK | `JuhanoManaka` / `Rinko` / `Nene` |
| ラブプラスぴあ muffler serial | Unique per book; wiki leak `34874P6786` | `PiaMufflerM` / `R` / `N` |
| ウリボー collab umbrella | Per-product PAK serial (no `0xb000` slot) | `UriboKasaM` / `R` / `N` + grant table 465/466/467 |

Rebuild: TRB codes with `python tools/deploy_name_kanji_trb.py` (bake overlay + `--deploy-azahar`). Umbrella grant with `python tools/deploy_name_input_en.py` → `release/name_input_code.bin`. LayeredFS needs `exefs/code.bin` present.

Source of vanilla lists: ROM pack `0xb000` / `0xb001` and grant table `0x006B6F00`, plus [NEWラブプラス＋ wiki](https://seesaawiki.jp/newloveplusplus2ch/d/%a5%d1%a5%b9%a5%ef%a1%bc%a5%c9) and [NEWラブプラス wiki](https://w.atwiki.jp/newloveplus2ch/pages/82.html) for 内部 / reward names.
