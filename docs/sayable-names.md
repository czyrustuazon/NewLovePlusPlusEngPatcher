# Speakable names (heroine voice)

How New Love Plus+ decides which names a girlfriend can **say**. Scanned 2026-09-13 from vanilla `code.bin` + `textresource_jpn.trb`.

Related: Profile name-input (`technical.md` §17), resident name table (`src/patch_names.py`). This page is **voice / 呼ばれ方**, not on-screen kanji chrome.

Regenerate the reading lists:

```bash
python tools/export_sayable_names.py
```

## What lives where

`code.bin` does **not** contain the thousands of player-name readings. It holds a small katakana voice-token table and then looks up the rest through TextResource packs.

| Layer | Location | What it is |
|-------|----------|------------|
| Heroine name voice keys | `code.bin` `0x73FD32`, pointer table `0x7A57F0` | タカネ / マナカ / リンコ / ネネ + -chan/-kun/-san + a few special lines |
| Stock voice tokens | `code.bin` `0x7382AD` | Yes/no, family terms, おはよ / おやす |
| Siren mora table | `code.bin` `0x744DFA` | Single kana for concatenative TTS |
| Siren bank | `romfs/Plus/Sound/Siren14voice.bin` + `Siren14Voice.spp` | Actual waveforms |
| **呼ばれ方 readings** | TRB pack **`0x7100`** (INDX cat 113) | **3,687** unique hiragana given-name / nickname readings |
| Surname readings | TRB pack **`0x7200`** (INDX cat 114) | **3,377** unique; 3,290 overlap with 0x7100 |
| Name-input kanji | TRB pack **`0x7000`** (INDX cat 112) | Keyboard + kanji *candidates* (display, not voice) |
| Banned words | TRB pack **`0x7300`** (INDX cat 115) | Profanity / blocked input |
| IME dictionary | `romfs/dictionary/all2_u.bin` | NintendoWare SWKBD — **not** the voice list |

Name-input fill (`NameInput_FillCandidates` @ `0x1FB438`) already uses packs `0x7008`–`0x7033` for on-screen candidates. Spoken coverage for **how she calls you** is pack **`0x7100`**.

Do not treat `all2_u.bin` as the name-voice dictionary (same note as SMS: `maildic_*.mdc` is also unrelated).

## Docs in this folder

| File | Contents |
|------|----------|
| [sayable-names-heroine.md](sayable-names-heroine.md) | Hardcoded heroine + special + stock tokens (English) |
| [sayable-names-readings.md](sayable-names-readings.md) | Full **0x7100** list with Hepburn + honorific |
| [sayable-names-surnames.md](sayable-names-surnames.md) | Full **0x7200** list with Hepburn + honorific |

JSON dumps (gitignored `out/`): `out/sayable_names/sayable_names_en.json`, `trb_cat_113_hira.txt`.

Searchable table (open beside chat): canvas `sayable-names.canvas.tsx`.

## Honorifics on 0x7100

Parsed from the end of each hiragana reading (longest suffix first):

| Suffix | English | Count (0x7100) |
|--------|---------|----------------|
| *(none)* | base reading only | 3,531 |
| ちゃん | -chan | 72 |
| くん | -kun | 43 |
| さん | -san | 33 |
| さま | -sama | 3 |
| にいさま | -nii-sama | 2 |
| おにいちゃん | -onii-chan | 2 |
| せんぱい | -senpai | 1 |

Examples that are **not** a generic Japanese name: `ごしゅじんさま` (Goshujin-sama), `ぷろでゅーさーさん` (Producer-san), `まあくんせんぱい` (Maa-kun-senpai). If the reading is in 0x7100, Siren can attempt it.

## English / romaji notes

- Hepburn is **generated** (revised): `ん` + vowel/y → `n'`; `っ` doubles the next consonant; youon (`きゃ` → `kya`, `しょ` → `sho`).
- Title case on the whole reading (`Manaka`, `Shin'ichi`). This is a lookup aid, not an in-game string.
- In-game Profile input still uses the gojūon / romaji stack in `code.bin` (§17). Matching a **呼ばれ方** candidate depends on the hiragana reading landing in pack 0x7100.
- **TODO:** keep Hepburn on the translated kana grid / name field, but associate each tap with its hiragana so Siren still says whitelist names (`akiko` on screen → stored `あきこ` → `0x7100`). Tracked in `technical.md` §17.6 item 6. Today insert is romaji-only, so English Called names display and are not spoken.

## Quick “can she say this?”

1. Convert the intended call-name to hiragana (including ちゃん/くん/さん if wanted).
2. Search [sayable-names-readings.md](sayable-names-readings.md) for that reading or its romaji.
3. If missing, she can still *display* a typed name; she will **not** have that reading in the 呼ばれ方 candidate / voice dictionary.
4. Her **own** names are the hardcoded katakana table, not 0x7100.
