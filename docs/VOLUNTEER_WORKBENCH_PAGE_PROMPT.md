# LLM prompt — update volunteer pages with the localization workbench

Copy everything below the line into another chat (with your fansite / Contribute page source attached or linked).

---

## Prompt

You are updating **volunteer-facing** documentation for the New Love Plus+ English localization project (fansite: newloveplus.loc.moe and related Contribute / Help translate pages).

### Goal

Rewrite or extend the volunteer “how to help translate” pages so they document the **browser workbench** in full: **Scripts + Strings**. Prefer clear steps for non-technical volunteers. Do **not** document maintainer Python tooling, EngPatcher bake/CIA pipelines, Ghidra, or `img.bin` splicing beyond naming sources at a high level if needed.

### Facts you must use (do not invent alternatives)

**Product name:** NLPP Localization Workbench (volunteer HTML kits).

**Repo (volunteers):** https://github.com/czyrustuazon/nlpp-localization-workbench  
Clone or download the repo ZIP. No Python install required.

**Entry point:** open `index.html` at the repo root (tabbed hub). The hub is Scripts and Strings. There is no Images tab.

**Two tools (hub tabs):**

| Tab | What volunteers do | Built files (under `kit/`) | Save filename |
|-----|--------------------|---------------------------|---------------|
| **Scripts** | Proofread dialogue. The Japanese line is the game's Japanese. The edit box is the English the patcher ships now | `NLPP_Translate.html` | `nlpp-contrib-YYYY-MM-DD.json` |
| **Strings** | Proofread **SMS** (all 3 heroines). TRB rows appear only when that exact Japanese string is not already translated | `NLPP_Translate_Strings.html` | `nlpp-strings-YYYY-MM-DD.json` |

**Scripts — routes (not Manaka-only):**

| Stem prefix | Route | Example jump |
|-------------|-------|--------------|
| `a` | Nene | `a042` |
| `k` | Rinko | `k100` |
| `t` | Manaka | `t151 - #775` |
| `p` | Common | `p060` |

List is alphabetical (`a…` then `k…` then `p…` then `t…`). A script whose edit box is already finished English stays in the kit under **All scripts** and drops out of **Needs translation**.

**Strings — what is included:**

- SMS phone messages for **Manaka, Nene, and Rinko**.
- TRB lines only when the full vanilla string is still missing from the patcher's translation table.
- Jump: `sms/manaka#12`, `sms/nene#0`, `sms/rinko#40`, `trb#2837`.
- SMS length limited (tool warns) — shorten English if needed.

**Standard volunteer loop:**

1. Get the workbench (clone or ZIP from GitHub).
2. Open root `index.html` in Chrome / Edge / Firefox.
3. Pick a tab; translate or proofread; use **Save progress**.
4. Upload/post the downloaded JSON in Discord **`#translated-work-to-review`**:  
   https://discord.com/channels/1536915629787840572/1545180296343715891

**Hard rules (call out prominently):**

- Keep nickname / player-name tokens exactly: e.g. `▲高嶺＊＊▲`, `▲主人公＊▲`.
- Keep control marks **`※`** and **`▼`** — removing them blocks Save.
- Translate **`●`** as I / me / my. It is the player's word for "I"; left in, the game shows 俺 or 僕.
- Leave placeholder-only lines (`○○○`) and punctuation-only lines alone.
- Scripts badge **`N left · total`** = lines still needing work (not “N done”).

**UX tips:**

- Hub tabs keep tools loaded; dirty close warns.
- Last spot / jump restore position.
- Hard-refresh (`Ctrl+F5`) after kit updates if a tab looks empty.

**What this is / is not:**

- **Is:** help proofread dialogue (all routes) and SMS — no toolchain install.
- **Is not:** the playable English CIA patcher. Do not tell volunteers to run Python or EngPatcher.

### Tone and structure

- Friendly; numbered steps; one “rules” callout.
- Cover **both tabs** with equal clarity.
- Prefer one primary CTA: open workbench → Save → post JSON to Discord.
- Optional FAQ: no Python; tokens/`※`/`▼`; which JSON; where Nene/Rinko IDs are (`a*` / `k*`).

### Output

Ready-to-paste page copy (Markdown or HTML matching the site). If multiple pages exist, propose edits per page and make the workbench the primary contribute path.

### Do not include

Maintainer parser repo details, `paths.local.json`, ingest commands, EngPatcher template paths, pack schema internals, zlib/`img.bin` RE notes.
