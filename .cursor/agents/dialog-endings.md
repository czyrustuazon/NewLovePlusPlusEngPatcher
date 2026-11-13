---
name: dialog-endings
description: >-
  Restores sentence endings that English dialogue dropped from the Japanese
  script, then refreshes the volunteer workbench. Use proactively when a
  heroine's conversation is missing punctuation, or after English script lines
  change, so the workbench edit boxes match the patcher.
---

You restore dropped sentence endings in New Love Plus+ dialogue and publish
that text to the volunteer workbench.

The patcher is the source of truth. The workbench is the sibling checkout
`../nlpp-localization-workbench`. Do not hand-edit `kit/*.html` or the JSON
embedded in those pages.

## When to run

Run this whole sequence when someone reports missing punctuation in Nene,
Rinko, Manaka, or common dialogue, or after you change English lines in
`rebuild_dbin2/`, `assets/scripts/`, or `assets/gemini_heroines/`.

## What to do

1. From the EngPatcher repo, dry-run the ending tool:

```bash
python tools/restore_dialog_endings.py
```

2. Read the report. The tool only touches a talk line whose Japanese ends
   with `。`, `！`, `？`, or `……` and whose English has no ending. It leaves
   alone a line that already has `.` `!` `?` `…`, a period on a `ね？` / `よ？`
   tag, a `*sigh*` / `*yawn*` sound, a drawn-out `～`, a cut-off `--`, or a
   `▼` continue mark. Do not invent a second punctuation pass on top of it.

3. When the dry-run lists lines, apply them:

```bash
python tools/restore_dialog_endings.py --apply
```

4. Rebuild the workbench from the patcher. This also points a Gemini phrase
   that ships as one English string at that string.

```bash
python tools/sync_workbench.py
```

5. If a changed line was the Gemini machine pass, add its dialog index to
   `assets/script_contrib/unreviewed.json` under that stem. An agent rewrite
   is not a proofread. Skip a stem listed in
   `assets/gemini_heroines/proofread.json`. See `.cursor/agents/script-review.md`.

6. Say which lines changed and the new workbench build number. Do not commit
   either repo unless the user asks. Do not deploy LayeredFS or launch Azahar
   unless the user asks.

If the dry-run prints `would change 0 line(s)` and the scripts were already
fixed, still run `sync_workbench.py` so the volunteer kit catches up.
