# LLM prompt — update volunteer pages with the localization workbench

Copy everything below the line into another chat (with your fansite / Contribute page source attached or linked).

---

## Prompt

You are updating **volunteer-facing** documentation for the New Love Plus+ English localization project (fansite: newloveplus.loc.moe and related Contribute / Help translate pages).

### Goal

Rewrite or extend the volunteer “how to help translate” pages so they document the **browser workbench** (2026-09-03+) in full: **Scripts + Strings + Images**. Prefer clear steps for non-technical volunteers. Do **not** document maintainer Python tooling, EngPatcher bake/CIA pipelines, Ghidra, or `img.bin` splicing beyond naming sources at a high level if needed.

### Facts you must use (do not invent alternatives)

**Product name:** NLPP Localization Workbench (volunteer HTML kits).

**Repo (volunteers):** https://github.com/czyrustuazon/nlpp-localization-workbench  
Clone or download the repo ZIP. No Python install required.

**Entry point:** open `index.html` at the repo root (tabbed hub). For Images, keep `kit/NLPP_Translate_Images/index.html` next to its `media/` folder (unzip `NLPP_Translate_Images.zip` into `kit/` if needed).

**Three tools (hub tabs) — be complete:**

| Tab | What volunteers do | Built files (under `kit/`) | Save filename | Rough full-kit size |
|-----|--------------------|---------------------------|---------------|---------------------|
| **Scripts** | Translate leftover Japanese **dialogue** for **all routes** | `NLPP_Translate.html` (~6 MB) | `nlpp-contrib-YYYY-MM-DD.json` | ~300+ scripts / ~10k JP lines |
| **Strings** | Translate leftover **SMS** (all 3 heroines) + **TRB** menu/system lines | `NLPP_Translate_Strings.html` | `nlpp-strings-YYYY-MM-DD.json` | ~1822 SMS + ~400+ TRB |
| **Images** | Audit **all** UI PNG masters: OK / Needs fix / upload fixed PNG | `NLPP_Translate_Images/` (+ optional `.zip`) | `nlpp-images-YYYY-MM-DD.json` (may include `png_b64`) | ~1210 PNGs / ~68 folders |

**Scripts — routes (not Manaka-only):**

| Stem prefix | Route | Example jump |
|-------------|-------|--------------|
| `a` | Nene | `a042` |
| `k` | Rinko | `k100` |
| `t` | Manaka | `t151 - #775` |
| `p` | Common | `p060` |

List is alphabetical (`a…` then `k…` then `p…` then `t…`). Fully English scripts are omitted from the kit. (Maintainers rebuild from `assets/scripts/` + game/NLPPATCH `.dbin2` — volunteers do not need those paths.)

**Strings — what is included:**

- SMS phone messages for **Manaka, Nene, and Rinko** that still look Japanese.
- Leftover **TRB** (main text-table) lines still Japanese (already-English mapped lines omitted).
- Jump: `sms/manaka#12`, `sms/nene#0`, `sms/rinko#40`, `trb#2837`.
- SMS length limited (tool warns) — shorten English if needed.

**Images — what is included (full UI audit):**

- Roughly **every** EngPatcher UI texture folder used for patching: softkeys, option/menus, title, my-room headers, mail, date editor, camera UI, sys popups, map, shop, profile, gallery, transfer, web UI chrome, etc. (~**68** folders / ~**1210** PNGs in a full export).
- **Not** fonts, not dialogue XML, not TRB files.
- Actions: mark OK / Needs fix, or upload a **same width × height** PNG; Save embeds uploads as `png_b64` in the JSON.
- Use **Preview background → Light checker** (or white) if transparent text is hard to see — does not change the file.
- Jump: `folder / stem` (e.g. `dateeditcom / De_btn05_t32`).

**Standard volunteer loop:**

1. Get the workbench (clone or ZIP from GitHub).
2. For Images: keep the folder intact — `index.html` next to `media/`.
3. Open root `index.html` in Chrome / Edge / Firefox.
4. Pick a tab; translate or audit; use **Save progress**.
5. Upload/post the downloaded JSON in Discord **`#translated-work-to-review`**:  
   https://discord.com/channels/1536915629787840572/1545180296343715891

**Hard rules (call out prominently):**

- Keep nickname / player-name tokens exactly: e.g. `▲高嶺＊＊▲`, `▲主人公＊▲`.
- Keep control marks **`※`** and **`▼`** — removing them blocks Save.
- Keep **`●`** when present in the reference.
- Leave placeholder-only lines (`○○○`) and punctuation-only lines alone.
- Image replacements: **PNG**, **exact same pixel size**.
- Scripts badge **`N left · total`** = lines still needing work (not “N done”).

**UX tips:**

- Hub tabs keep tools loaded; dirty close warns.
- Last spot / jump restore position.
- Hard-refresh (`Ctrl+F5`) after kit updates if a tab looks empty.

**What this is / is not:**

- **Is:** help finish remaining JP dialogue (all routes), SMS/TRB leftovers, and UI image review — no toolchain install.
- **Is not:** the playable English CIA patcher. Do not tell volunteers to run Python or EngPatcher.

### Tone and structure

- Friendly; numbered steps; one “rules” callout.
- Cover **all three tabs** with equal clarity (do not bury Images).
- Prefer one primary CTA: open workbench → Save → post JSON to Discord.
- Optional FAQ: no Python; Images `media/` layout; tokens/`※`/`▼`; same-size PNGs; which JSON; where Nene/Rinko IDs are (`a*` / `k*`).

### Output

Ready-to-paste page copy (Markdown or HTML matching the site). If multiple pages exist, propose edits per page and make the workbench the primary contribute path.

### Do not include

Maintainer parser repo details, `paths.local.json`, ingest commands, EngPatcher template paths, pack schema internals, zlib/`img.bin` RE notes.
